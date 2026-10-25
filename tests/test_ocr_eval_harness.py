"""ocr_eval: engine discovery, the runner, results files, comparison, the
Training Dojo importer and the command line, with fake engines (no OCR)."""

import gzip
import io
import json
import sys
import textwrap

import pytest

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")

from ocr_eval import cli, utf8_output  # noqa: E402
from ocr_eval.compare import compare_results, render_comparison  # noqa: E402
from ocr_eval.dataset import load_dataset, validate_dataset  # noqa: E402
from ocr_eval.dojo import import_dojo  # noqa: E402
from ocr_eval.engines import (  # noqa: E402
    Engine,
    EngineUnavailable,
    Recognition,
    Registry,
    discover,
    parse_engine_spec,
)
from ocr_eval.fields import (  # noqa: E402
    box_name,
    box_settings,
    guess_field_type,
    role_box,
    scoresight_postfilter,
    whitelist,
)
from ocr_eval.report import read_results, render_report, write_results  # noqa: E402
from ocr_eval.runner import RunOptions, run_all  # noqa: E402
from test_ocr_eval_dataset import _row, make_dataset  # noqa: E402


class OracleEngine(Engine):
    """Reads the truth from a lookup the test fills in (by image size)."""

    name = "oracle"
    variants = ("good", "bad")
    batch_size = 3
    answers: dict = {}

    def recognize(self, crops, field_types):
        out = []
        for crop in crops:
            assert not crop.flags.writeable
            assert crop.ndim == 3 and crop.dtype == np.uint8
            text = self.answers[crop.shape[1]]
            if self.variant == "bad":
                text = text[::-1] + "x"
            out.append((text, 0.9))
        return out


class BrokenEngine(Engine):
    name = "broken"

    def recognize(self, crops, field_types):
        raise RuntimeError("boom")


class MissingEngine(Engine):
    name = "missing"
    imports = ("a_module_that_does_not_exist_anywhere",)


class UnloadableEngine(Engine):
    name = "unloadable"

    def load(self):
        raise EngineUnavailable("no GPU")


@pytest.fixture
def dataset(tmp_path):
    rows = [
        _row(id="s1", image="images/s1.png", text="12", field_type="score"),
        _row(
            id="s2", image="images/s2.png", text="1:05", field_type="clock", split="dev"
        ),
        _row(id="s3", image="images/s3.png", text="HOME", field_type="text"),
        _row(id="s4", image="images/s4.png", text="245", field_type="score"),
    ]
    folder = make_dataset(tmp_path / "ds", rows)
    # distinct widths identify the crops for OracleEngine
    answers = {}
    for width, row in enumerate(rows, start=10):
        image = np.full((12, width), 128, np.uint8)
        cv2.imwrite(str(folder / row["image"]), image)
        answers[width] = row["text"]
    OracleEngine.answers = answers
    return load_dataset(folder)


def test_discovery_finds_the_tesseract_adapter():
    registry = discover()
    assert "tesseract" in registry.engines
    engine = registry.engines["tesseract"]
    assert engine.requirements == []
    assert "scoreboard_general" in engine.variants
    assert "scoreboard_general-nobin" in engine.variants
    assert not registry.broken, registry.broken


def test_discovery_of_a_package(tmp_path, monkeypatch):
    package = tmp_path / "fake_engines"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "alpha.py").write_text(
        textwrap.dedent(
            """
            from ocr_eval.engines import Engine
            REQUIREMENTS = ["alpha-ocr==1.0"]
            class Base(Engine):
                pass  # no name: not collected
            class Alpha(Base):
                name = "alpha"
                imports = ("alpha_ocr",)
            """
        ),
        encoding="utf-8",
    )
    (package / "beta.py").write_text(
        "raise ImportError('needs beta')\n", encoding="utf-8"
    )
    (package / "dup.py").write_text(
        "from ocr_eval.engines import Engine\nclass Again(Engine):\n    name = 'alpha'\n",
        encoding="utf-8",
    )
    (package / "_private.py").write_text(
        "raise SystemExit('never imported')\n", encoding="utf-8"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    registry = discover("fake_engines")
    assert set(registry.engines) == {"alpha"}
    alpha = registry.engines["alpha"]
    assert alpha.requirements == ["alpha-ocr==1.0"]
    reason = alpha.unavailable_reason()
    assert "alpha_ocr" in reason and "alpha-ocr==1.0" in reason
    assert "fake_engines.beta" in registry.broken
    assert "already used" in registry.broken["fake_engines.dup"]
    for name in [m for m in sys.modules if m.startswith("fake_engines")]:
        del sys.modules[name]


def test_parse_engine_spec():
    registry = Registry({"oracle": OracleEngine})
    assert parse_engine_spec("oracle", registry) == [
        (OracleEngine, "good"),
        (OracleEngine, "bad"),
    ]
    assert parse_engine_spec("oracle:bad", registry) == [(OracleEngine, "bad")]
    assert parse_engine_spec("oracle:*", registry) == parse_engine_spec(
        "oracle", registry
    )
    with pytest.raises(ValueError):
        parse_engine_spec("oracle:ugly", registry)
    with pytest.raises(KeyError):
        parse_engine_spec("nobody", registry)


def test_engine_rejects_unknown_variant():
    with pytest.raises(ValueError):
        OracleEngine("ugly")
    assert OracleEngine().variant == "good"


def test_run_scores_and_latency(dataset):
    results = run_all(
        [dataset],
        [(OracleEngine, "good"), (OracleEngine, "bad")],
        RunOptions(single_latency_samples=2),
        log=None,
    )
    good, bad = results["runs"]
    assert good["status"] == "ok"
    raw = good["scores"]["raw"]
    assert raw["exact"]["value"] == 1.0
    assert raw["cer"]["value"] == 0.0
    # 245 doesn't match the Home Score format (1dd): the post-filter rejects it
    post = good["scores"]["postfilter"]
    assert post["exact"]["k"] == 3
    rejected = [p for p in good["predictions"] if p["id"] == "s4"][0]
    assert rejected["pf_text"] == "" and rejected["exact"] and not rejected["pf_exact"]
    assert good["latency"]["batch_size"] == 3
    assert good["latency"]["single"]["n"] == 2
    assert good["latency"]["batch"]["n"] == 4
    cpu = good["latency"]["cpu_ms"]
    assert cpu["batch"] >= 0 and cpu["single"] >= 0
    assert good["predictions"][0]["conf"] == 0.9
    assert bad["scores"]["raw"]["exact"]["value"] == 0.0
    assert set(raw["by_field_type"]) == {"score", "clock", "text"}
    assert results["datasets"]["ds"]["n"] == 4


def test_run_reports_unavailable_and_failing_engines(dataset):
    results = run_all(
        [dataset],
        [
            (MissingEngine, "default"),
            (UnloadableEngine, "default"),
            (BrokenEngine, "default"),
        ],
        log=None,
    )
    missing, unloadable, broken = results["runs"]
    assert missing["status"] == "skipped" and "a_module_that" in missing["reason"]
    assert unloadable["status"] == "skipped" and unloadable["reason"] == "no GPU"
    assert broken["status"] == "error" and "boom" in broken["reason"]


def test_results_round_trip_and_report(dataset, tmp_path):
    results = run_all([dataset], [(OracleEngine, "good")], log=None)
    path = tmp_path / "out" / "results.json"
    write_results(path, results)
    text = path.read_text(encoding="utf-8")
    # one line per prediction
    assert sum('{"id":' in line for line in text.splitlines()) == 4
    assert read_results(path) == json.loads(json.dumps(results))
    report = render_report(read_results(path))
    assert "oracle:good" in report and "## ds (4 crops)" in report
    with pytest.raises(ValueError):
        (tmp_path / "x.json").write_text("{}", encoding="utf-8")
        read_results(tmp_path / "x.json")


def test_gzipped_results_read_like_plain_ones(dataset, tmp_path):
    results = run_all([dataset], [(OracleEngine, "good")], log=None)
    plain = tmp_path / "results.json"
    packed = tmp_path / "results.json.gz"
    write_results(plain, results)
    write_results(packed, results)
    assert packed.read_bytes()[:2] == b"\x1f\x8b"
    assert gzip.decompress(packed.read_bytes()) == plain.read_bytes()
    assert read_results(packed) == read_results(plain)
    # reproducible: no time or file name in the gzip header
    again = tmp_path / "again" / "results.json.gz"
    write_results(again, results)
    assert again.read_bytes() == packed.read_bytes()
    # recognized by content, not by name
    renamed = tmp_path / "renamed.json"
    renamed.write_bytes(packed.read_bytes())
    assert read_results(renamed) == read_results(plain)
    # compare and report take them too
    assert cli.main(["compare", str(plain), str(packed)]) == 0
    assert cli.main(["report", str(packed), "--out", str(tmp_path / "r.md")]) == 0
    with pytest.raises(ValueError):
        (tmp_path / "junk.json.gz").write_bytes(gzip.compress(b"\xff\xfe not json"))
        read_results(tmp_path / "junk.json.gz")


def test_utf8_output_survives_a_legacy_code_page(monkeypatch):
    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", stream)
    utf8_output()
    print("Δ –")
    stream.flush()
    assert raw.getvalue().decode("utf-8").strip() == "Δ –"


def _fake_results(
    flags, status="ok", dataset="ds", key="e:v", sha="abc", platform="win32"
):
    return {
        "schema": "scoresight-ocr-eval/1",
        "harness_version": "1",
        "environment": {"platform": platform},
        "datasets": {dataset: {"manifest_sha256": sha}},
        "runs": [
            {
                "dataset": dataset,
                "key": key,
                "status": status,
                "predictions": [
                    {
                        "id": f"i{n}",
                        "truth": "1",
                        "text": "1" if ok else "",
                        "exact": ok,
                        "pf_exact": ok,
                    }
                    for n, ok in enumerate(flags)
                ],
            }
        ],
    }


def test_compare_flags_a_drop_beyond_max_drop():
    base = _fake_results([True] * 90 + [False] * 10)
    same = _fake_results([True] * 90 + [False] * 10)
    assert compare_results(base, same).ok
    small = _fake_results([True] * 89 + [False] * 11)
    assert compare_results(base, small, max_drop=0.02).ok
    big = _fake_results([True] * 85 + [False] * 15)
    comparison = compare_results(base, big, max_drop=0.02)
    assert not comparison.ok
    row = comparison.rows[0]
    assert (row.lost, row.gained) == (5, 0)
    assert row.baseline == pytest.approx(0.9) and row.new == pytest.approx(0.85)
    assert "REGRESSION" in render_comparison(comparison, 0.02)
    # requiring significance: 5 lost, 0 gained has p = 0.0625
    assert compare_results(base, big, max_drop=0.02, alpha=0.05).ok
    # an improvement is never a regression
    assert compare_results(big, base).ok


def test_compare_missing_failed_and_changed_runs():
    base = _fake_results([True] * 10)
    failed = _fake_results([True] * 10, status="error")
    assert not compare_results(base, failed).ok
    other = _fake_results([True] * 10, key="e:other")
    assert compare_results(base, other).ok
    assert not compare_results(base, other, require_all=True).ok
    changed = _fake_results([True] * 10, sha="def", platform="linux")
    comparison = compare_results(base, changed)
    assert comparison.ok
    assert any("changed" in w for w in comparison.warnings)
    assert any("platform" in n for n in comparison.notes)


def test_field_type_box_settings_follow_scoresight_defaults():
    from ocr_eval._src import import_defaults

    defaults = import_defaults()
    score = box_settings("score")
    assert score["type"] == defaults.FieldType.NUMBER
    assert score["format_regex"] == defaults.format_prefixes[6]
    assert box_settings("clock")["type"] == defaults.FieldType.TIME
    period = box_settings("period")
    assert period["format_regex"] == defaults.format_prefixes[8]
    assert period["ordinal_indicator"] is False  # output formatting is off
    assert box_settings("number")["format_regex"] == defaults.format_prefixes[12]
    text = box_settings("text")
    assert text["type"] == defaults.FieldType.TEXT
    assert text["format_regex"] == defaults.format_prefixes[11]
    assert box_settings("score")["binarization_method"] == 0
    assert box_settings("score", binarization_method=1)["binarization_method"] == 1
    assert whitelist("clock") == "0123456789:."
    with pytest.raises(ValueError):
        box_settings("jersey")


@pytest.mark.parametrize(
    ("text", "field_type", "published"),
    [
        ("12", "score", "12"),
        (" 12 ", "score", "12"),
        ("245", "score", ""),  # Home Score accepts 0-199
        ("245", "number", "245"),
        ("1O", "number", "1"),  # letters are outside the whitelist
        ("12:34", "clock", "12:34"),
        ("12.34", "clock", ""),  # neither MM:SS nor SS.D
        ("3", "period", "3"),
        ("5", "period", ""),  # Period accepts 1-4
        ("HOME", "text", "HOME"),
    ],
)
def test_scoresight_postfilter(text, field_type, published):
    assert scoresight_postfilter(text, field_type) == published


def test_a_role_with_a_preset_is_read_with_it():
    from ocr_eval._src import import_defaults

    defaults = import_defaults()
    assert role_box("number", "shot_clock") == "Shot Clock"
    assert role_box("score", "away_score_2") == "Away Score"
    assert role_box("number", "home_fouls") == "Home Fouls"
    # no preset for the role, no role, or a preset for another kind of value
    assert role_box("number", "home_timeouts") is None
    assert role_box("number", None) is None
    assert role_box("text", "period") is None  # a period that shows "4TH"
    assert role_box("clock", "shot_clock") is None  # a shot clock with tenths
    assert box_name("number", "shot_clock") == "Shot Clock"
    assert box_name("number", "down") == "Eval number"
    shot_clock = box_settings("number", "shot_clock", dilate=0)
    assert shot_clock["format_regex"] == defaults.format_prefixes[5]
    assert shot_clock["dilate"] == 0
    # the Shot Clock preset's format takes one or two digits, 0-39
    assert scoresight_postfilter("07", "number", "shot_clock") == "07"
    assert scoresight_postfilter("7", "number", "shot_clock") == "7"
    assert scoresight_postfilter("40", "number", "shot_clock") == ""
    assert scoresight_postfilter("40", "number", "home_timeouts") == "40"


class RoleEngine(Engine):
    """Echoes each crop's role, when the runner passes them."""

    name = "roles"
    reads_roles = True
    batch_size = 2
    seen: list = []

    def recognize(self, crops, field_types, roles=None):
        self.seen.extend(roles)
        return [(role or "", 1.0) for role in roles]


def test_engines_that_read_roles_get_each_crops_role(tmp_path):
    rows = [
        _row(id="a", image="images/a.png", text="5", role="shot_clock"),
        _row(id="b", image="images/b.png", text="7"),
    ]
    folder = make_dataset(tmp_path / "ds", rows)
    RoleEngine.seen = []
    results = run_all(
        [load_dataset(folder)], [(RoleEngine, "default")], RunOptions(), log=None
    )
    [run] = results["runs"]
    assert run["status"] == "ok", run.get("traceback")
    assert RoleEngine.seen[-2:] == ["shot_clock", None]
    assert [p["text"] for p in run["predictions"]] == ["shot_clock", ""]


def test_guess_field_type():
    assert guess_field_type("12:34") == "clock"
    assert guess_field_type("4.5") == "clock"
    assert guess_field_type("105") == "number"
    assert guess_field_type("2nd") == "text"


def test_whitelists_match_the_tesseract_module():
    pytest.importorskip("tesserocr")
    from ocr_eval._src import ensure_src_on_path

    ensure_src_on_path()
    import tesseract

    assert whitelist("number") == tesseract.CHAR_WHITELISTS[0]
    assert whitelist("text") == tesseract.GENERAL_CHAR_WHITELIST


def _dojo_folder(folder):
    folder.mkdir()
    gray = np.full((20, 40), 90, np.uint8)
    for base, text in [("aaa", "12"), ("bbb", "1:05"), ("ccc", "HOME"), ("ddd", "7")]:
        binary = np.where(gray > 100, 255, 0).astype(np.uint8)
        cv2.imwrite(str(folder / f"{base}.png"), binary)  # binarized, never used
        cv2.imwrite(str(folder / f"{base}_gray.png"), gray)
        (folder / f"{base}.txt").write_text(text, encoding="utf-8")
    (folder / "ddd_gray.png").unlink()
    (folder / "approved_annotations.json").write_text(
        json.dumps({"aaa": "12", "bbb": "1:06", "ddd": "7"}), encoding="utf-8"
    )
    return folder


def test_import_dojo(tmp_path):
    folder = _dojo_folder(tmp_path / "dojo")
    out = tmp_path / "dataset"
    added, skipped = import_dojo(
        folder, out, author="A. Person", license="CC0-1.0", log=None
    )
    assert added == 2
    reasons = dict(skipped)
    assert reasons["ccc"] == "not approved in the Training Dojo"
    assert "gray" in reasons["ddd"]
    assert validate_dataset(out, strict_licenses=True).ok
    samples = {s.id: s for s in load_dataset(out).samples}
    assert samples["dojo_bbb"].text == "1:06"  # the approved text
    assert samples["dojo_bbb"].field_type == "clock"
    assert samples["dojo_aaa"].label_source == "human"
    # importing again adds nothing; unapproved samples on request
    assert (
        import_dojo(folder, out, author="A. Person", license="CC0-1.0", log=None)[0]
        == 0
    )
    added, _ = import_dojo(
        folder,
        out,
        author="A. Person",
        license="CC0-1.0",
        include_unapproved=True,
        log=None,
    )
    assert added == 1
    assert load_dataset(out).samples[-1].label_source == "model-assisted-unverified"


def test_cli_run_compare_report(dataset, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        "ocr_eval.engines.discover", lambda: Registry({"oracle": OracleEngine})
    )
    out = tmp_path / "run"
    assert (
        cli.main(
            [
                "run",
                "--dataset",
                str(dataset.path),
                "--engine",
                "oracle:good",
                "--out",
                str(out),
                "--quiet",
            ]
        )
        == 0
    )
    assert (out / "results.json").is_file() and (out / "report.md").is_file()
    worse = tmp_path / "worse"
    assert (
        cli.main(
            [
                "run",
                "--dataset",
                str(dataset.path),
                "--engine",
                "oracle:good",
                "--out",
                str(worse),
                "--quiet",
            ]
        )
        == 0
    )
    results = read_results(worse / "results.json")
    for prediction in results["runs"][0]["predictions"]:
        prediction["exact"] = prediction["pf_exact"] = False
    write_results(worse / "results.json", results)
    assert (
        cli.main(["compare", str(out / "results.json"), str(out / "results.json")]) == 0
    )
    markdown = tmp_path / "cmp.md"
    assert (
        cli.main(
            [
                "compare",
                str(out / "results.json"),
                str(worse / "results.json"),
                "--markdown",
                str(markdown),
            ]
        )
        == 1
    )
    assert "REGRESSION" in markdown.read_text(encoding="utf-8")
    assert cli.main(["report", str(out / "results.json")]) == 0
    assert "oracle:good" in capsys.readouterr().out
    assert (
        cli.main(
            [
                "run",
                "--dataset",
                str(dataset.path),
                "--engine",
                "nobody",
                "--out",
                str(out),
            ]
        )
        == 2
    )
    assert cli.main(["validate", str(dataset.path)]) == 0
    assert cli.main(["requirements", "oracle"]) == 0


def test_cli_run_on_a_stratified_sample(dataset, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "ocr_eval.engines.discover", lambda: Registry({"oracle": OracleEngine})
    )
    out = tmp_path / "run"
    args = ["run", "--dataset", str(dataset.path), "--engine", "oracle:good"]
    assert cli.main(args + ["--out", str(out), "--sample", "3", "--quiet"]) == 0
    results = read_results(out / "results.json")
    info = results["datasets"]["ds"]
    assert info["n"] == 3
    assert info["subset"]["sample"] == 3 and info["subset"]["manifest_n"] == 4
    # one crop of each field type (score 2 crops, clock 1, text 1)
    ids = {p["id"] for p in results["runs"][0]["predictions"]}
    assert len(ids) == 3 and {"s2", "s3"} <= ids
    report = (out / "report.md").read_text(encoding="utf-8")
    assert "Subset: a stratified sample (by field_type, seed 0) of 3 of 4" in report
    assert "## ds (3 crops)" in report
    # the full run has no subset
    assert cli.main(args + ["--out", str(tmp_path / "all"), "--quiet"]) == 0
    full = read_results(tmp_path / "all" / "results.json")
    assert "subset" not in full["datasets"]["ds"]


def test_cli_list(capsys):
    assert cli.main(["list"]) == 0
    output = capsys.readouterr().out
    assert "tesseract" in output and "synthetic_7seg" in output
    assert cli.main(["list", "--json"]) == 0
    listing = json.loads(capsys.readouterr().out)
    assert {e["name"] for e in listing["engines"]} >= {"tesseract"}


def test_engine_info_and_recognition_defaults():
    engine = OracleEngine("bad")
    info = engine.info()
    assert info["name"] == "oracle" and info["variant"] == "bad"
    assert engine.key == "oracle:bad"
    assert Recognition("1") == ("1", None, None)
