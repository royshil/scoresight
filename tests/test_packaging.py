"""Packaging and release tooling: the version helpers, scripts/bump_version.py,
the frozen-app smoke test runner, and the consistency of scoresight.spec,
scoresight.iss and the workflows with the code and with each other."""

import ast
import fnmatch
import importlib.util
import re
import sys
import textwrap
from pathlib import Path

import pytest

import version
from conftest import REQUIRE_PPOCR

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
SPEC_FILE = REPO_ROOT / "scoresight.spec"
ISS_FILE = REPO_ROOT / "scoresight.iss"
WORKFLOWS = REPO_ROOT / ".github" / "workflows"


def _load_script(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


versioning = _load_script("versioning", REPO_ROOT / "scripts" / "ci" / "versioning.py")
bump_version = _load_script("bump_version", REPO_ROOT / "scripts" / "bump_version.py")
smoke_test = _load_script("smoke_test", REPO_ROOT / "scripts" / "ci" / "smoke_test.py")


# --- version parsing ----------------------------------------------------------


def test_read_version_matches_the_version_module():
    assert versioning.read_version() == version.__version__
    versioning.parse_version(version.__version__)


@pytest.mark.parametrize(
    "source, expected",
    [
        ('__version__ = "1.2.3"\n', "1.2.3"),
        ("'''Docs.'''\n\n__version__ = '1.2.3-rc.1'\nOTHER = 1\n", "1.2.3-rc.1"),
    ],
)
def test_read_version_parses_without_importing(tmp_path, source, expected):
    path = tmp_path / "version.py"
    path.write_text(source, encoding="utf-8")
    assert versioning.read_version(path) == expected


def test_read_version_requires_a_string_literal(tmp_path):
    path = tmp_path / "version.py"
    path.write_text("__version__ = get_version()\n", encoding="utf-8")
    with pytest.raises(ValueError, match="__version__"):
        versioning.read_version(path)


def test_versions_sort_prereleases_before_the_release():
    ordered = [
        "0.1.0",
        "0.2.0-beta.1",
        "0.2.0-beta.2",
        "0.2.0-beta.10",
        "0.2.0-rc.1",
        "0.2.0",
        "0.2.1",
        "0.10.0",
        "1.0.0",
    ]
    assert sorted(ordered, key=versioning.parse_version) == ordered


@pytest.mark.parametrize(
    "bad",
    ["v0.2.0", "0.2", "0.2.0.1", "0.2.0-alpha.1", "0.2.0rc1", "0.2.0-rc", "0.2.0 "],
)
def test_invalid_versions_are_rejected(bad):
    with pytest.raises(ValueError, match="invalid version"):
        versioning.parse_version(bad)


@pytest.mark.parametrize(
    "value, numeric, prerelease",
    [("0.2.0", "0.2.0.0", False), ("1.10.3-rc.2", "1.10.3.0", True)],
)
def test_numeric_version_and_prerelease(value, numeric, prerelease):
    assert versioning.numeric_version(value) == numeric
    assert versioning.is_prerelease(value) is prerelease


def test_package_label_marks_non_release_builds_with_the_commit():
    sha = "1a2b3c4d5e6f7a8b9c0d"
    assert versioning.package_label("0.2.0", release=True, sha=sha) == "0.2.0"
    assert versioning.package_label("0.2.0", release=False, sha=sha) == "0.2.0-1a2b3c4"
    assert versioning.package_label("0.2.0", release=False, sha=None) == "0.2.0"


def test_check_tag():
    versioning.check_tag("0.2.0-rc.1", "0.2.0-rc.1")
    with pytest.raises(ValueError, match="does not match"):
        versioning.check_tag("0.2.1", "0.2.0")
    with pytest.raises(ValueError, match="invalid version"):
        versioning.check_tag("v0.2.0", "0.2.0")


def test_check_tag_command(capsys):
    assert versioning.main(["check-tag", version.__version__]) == 0
    assert versioning.main(["check-tag", "999.0.0"]) == 1
    assert "does not match" in capsys.readouterr().err


def test_github_output(tmp_path, monkeypatch):
    output = tmp_path / "github_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    assert versioning.main(["github-output", "--sha", "abcdef0123456789"]) == 0
    values = dict(line.split("=", 1) for line in output.read_text().splitlines())
    current = version.__version__
    assert values == {
        "version": current,
        "label": f"{current}-abcdef0",
        "numeric": versioning.numeric_version(current),
        "prerelease": str(versioning.is_prerelease(current)).lower(),
    }


# --- CHANGELOG sections -------------------------------------------------------

CHANGELOG = """\
# Changelog

Intro text.

## [Unreleased]

### Added

- Profiles ([#8](https://github.com/royshil/scoresight/issues/8)).

### Fixed

- A crash.

## [0.1.0] - 2024-11-07

### Added

- UNO Essentials support.

## [0.0.1] - 2024-04-25

- First release.

[Unreleased]: https://github.com/royshil/scoresight/compare/0.1.0...HEAD
[0.1.0]: https://github.com/royshil/scoresight/compare/0.0.1...0.1.0
[0.0.1]: https://github.com/royshil/scoresight/releases/tag/0.0.1
"""


def test_changelog_section():
    assert versioning.changelog_section(CHANGELOG, "0.1.0") == (
        "### Added\n\n- UNO Essentials support.\n"
    )


def test_changelog_section_leaves_out_the_link_definitions():
    assert versioning.changelog_section(CHANGELOG, "0.0.1") == "- First release.\n"


@pytest.mark.parametrize("missing", ["0.2.0", "0.1", "0x1x0", "0.1.0-rc.1"])
def test_changelog_section_must_exist(missing):
    with pytest.raises(ValueError, match="no '## \\["):
        versioning.changelog_section(CHANGELOG, missing)


def test_changelog_section_must_not_be_empty():
    text = "## [0.3.0] - 2026-01-01\n\n## [0.2.0] - 2025-01-01\n\n- x\n"
    with pytest.raises(ValueError, match="empty"):
        versioning.changelog_section(text, "0.3.0")


def test_changelog_command(tmp_path, capsys):
    path = tmp_path / "CHANGELOG.md"
    path.write_text(CHANGELOG, encoding="utf-8")
    assert versioning.main(["changelog", "0.1.0", "--file", str(path)]) == 0
    assert "UNO Essentials support" in capsys.readouterr().out
    assert versioning.main(["changelog", "9.9.9", "--file", str(path)]) == 1


# --- scripts/bump_version.py --------------------------------------------------


@pytest.fixture
def release_files(tmp_path):
    version_file = tmp_path / "version.py"
    version_file.write_text(
        '"""Single source of truth."""\n\n__version__ = "0.1.0"\n', encoding="utf-8"
    )
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(CHANGELOG, encoding="utf-8")
    return version_file, changelog


def test_bump_version(release_files):
    version_file, changelog = release_files
    unreleased = versioning.changelog_section(
        CHANGELOG.replace("## [Unreleased]", "## [9.9.9]"), "9.9.9"
    )

    diff = bump_version.bump("0.2.0", "2026-10-10", version_file, changelog)

    assert versioning.read_version(version_file) == "0.2.0"
    text = changelog.read_text(encoding="utf-8")
    assert "## [Unreleased]\n\n## [0.2.0] - 2026-10-10\n\n### Added" in text
    # the old Unreleased notes are now the release notes of 0.2.0
    assert versioning.changelog_section(text, "0.2.0") == unreleased
    assert (
        "[Unreleased]: https://github.com/royshil/scoresight/compare/0.2.0...HEAD\n"
        in text
    )
    assert (
        "[0.2.0]: https://github.com/royshil/scoresight/compare/0.1.0...0.2.0\n" in text
    )
    assert text.count("## [Unreleased]") == 1
    assert '+__version__ = "0.2.0"' in diff


def test_bump_version_dry_run_writes_nothing(release_files):
    version_file, changelog = release_files
    diff = bump_version.bump(
        "0.2.0-rc.1", "2026-10-10", version_file, changelog, dry_run=True
    )
    assert versioning.read_version(version_file) == "0.1.0"
    assert changelog.read_text(encoding="utf-8") == CHANGELOG
    assert "+## [0.2.0-rc.1] - 2026-10-10" in diff


def test_bump_version_keeps_crlf_line_endings(release_files):
    version_file, changelog = release_files
    changelog.write_bytes(CHANGELOG.replace("\n", "\r\n").encode("utf-8"))
    bump_version.bump("0.2.0", "2026-10-10", version_file, changelog)
    data = changelog.read_bytes()
    assert b"\r\n## [0.2.0] - 2026-10-10\r\n" in data
    assert data.count(b"\n") == data.count(b"\r\n")


@pytest.mark.parametrize(
    "new_version, date, message",
    [
        ("0.1.0", "2026-10-10", "already has a '## \\[0.1.0\\]' section"),
        ("0.1.0-rc.1", "2026-10-10", "older than"),
        ("0.0.9", "2026-10-10", "older than"),
        ("v0.2.0", "2026-10-10", "invalid version"),
        ("0.2.0", "10/10/2026", "invalid --date"),
    ],
)
def test_bump_version_refuses(release_files, new_version, date, message):
    version_file, changelog = release_files
    with pytest.raises(bump_version.BumpError, match=message):
        bump_version.bump(new_version, date, version_file, changelog)
    assert versioning.read_version(version_file) == "0.1.0"
    assert changelog.read_text(encoding="utf-8") == CHANGELOG


def test_bump_version_to_the_version_already_set(release_files):
    # src/version.py is set to the upcoming version during development, so the
    # first release only cuts the CHANGELOG section
    version_file, changelog = release_files
    version_file.write_text('__version__ = "0.2.0"\n', encoding="utf-8")
    diff = bump_version.bump("0.2.0", "2026-10-10", version_file, changelog)
    assert version_file.read_text(encoding="utf-8") == '__version__ = "0.2.0"\n'
    assert "version.py" not in diff
    text = changelog.read_text(encoding="utf-8")
    assert "Profiles" in versioning.changelog_section(text, "0.2.0")


def _add_unreleased_notes(changelog, notes):
    text = changelog.read_text(encoding="utf-8")
    changelog.write_text(
        text.replace("## [Unreleased]\n", f"## [Unreleased]\n\n{notes}\n", 1),
        encoding="utf-8",
    )


def test_bump_version_cuts_pre_releases_of_the_version_in_development(
    release_files,
):
    # src/version.py holds the version in development (0.2.0): its betas and
    # release candidates were refused as "older than the current version"
    version_file, changelog = release_files
    version_file.write_text('__version__ = "0.2.0"\n', encoding="utf-8")

    bump_version.bump("0.2.0-beta.1", "2026-10-01", version_file, changelog)
    assert versioning.read_version(version_file) == "0.2.0-beta.1"
    text = changelog.read_text(encoding="utf-8")
    assert "Profiles" in versioning.changelog_section(text, "0.2.0-beta.1")
    base = "https://github.com/royshil/scoresight/compare/"
    assert f"[0.2.0-beta.1]: {base}0.1.0...0.2.0-beta.1\n" in text

    _add_unreleased_notes(changelog, "### Fixed\n\n- Another crash.\n")
    bump_version.bump("0.2.0-rc.1", "2026-10-05", version_file, changelog)
    # an older pre-release than the newest release is still refused
    with pytest.raises(bump_version.BumpError, match="older than the latest"):
        bump_version.bump("0.2.0-beta.2", "2026-10-06", version_file, changelog)
    # and a pre-release needs changes of its own
    with pytest.raises(bump_version.BumpError, match="empty"):
        bump_version.bump("0.2.0-rc.2", "2026-10-06", version_file, changelog)


def test_the_final_release_takes_over_its_pre_releases_notes(release_files):
    # After X.Y.Z-rc.N the Unreleased section is usually empty: releasing X.Y.Z
    # was refused, and its notes (versioning.py changelog X.Y.Z, used by the
    # release workflow) would have left out everything in the pre-releases.
    version_file, changelog = release_files
    version_file.write_text('__version__ = "0.2.0"\n', encoding="utf-8")
    bump_version.bump("0.2.0-beta.1", "2026-10-01", version_file, changelog)
    _add_unreleased_notes(changelog, "### Fixed\n\n- Another crash.\n")
    bump_version.bump("0.2.0-rc.1", "2026-10-05", version_file, changelog)

    bump_version.bump("0.2.0", "2026-10-10", version_file, changelog)
    assert versioning.read_version(version_file) == "0.2.0"
    text = changelog.read_text(encoding="utf-8")
    assert versioning.changelog_section(text, "0.2.0") == (
        "### Added\n\n"
        "- Profiles ([#8](https://github.com/royshil/scoresight/issues/8)).\n\n"
        "### Fixed\n\n"
        "- Another crash.\n"
        "- A crash.\n"
    )
    # the pre-releases' sections and links are folded into the release's
    assert "## [0.2.0-" not in text and "[0.2.0-" not in text
    base = "https://github.com/royshil/scoresight/compare/"
    assert f"[Unreleased]: {base}0.2.0...HEAD\n[0.2.0]: {base}0.1.0...0.2.0\n" in text
    assert "## [Unreleased]\n\n## [0.2.0] - 2026-10-10\n\n### Added" in text
    assert "- A crash.\n\n## [0.1.0] - 2024-11-07" in text
    # with changes after the release candidate, they come first
    _add_unreleased_notes(changelog, "### Fixed\n\n- A third crash.\n")
    bump_version.bump("0.2.1-rc.1", "2026-10-11", version_file, changelog)
    _add_unreleased_notes(changelog, "### Fixed\n\n- A fourth crash.\n")
    bump_version.bump("0.2.1", "2026-10-12", version_file, changelog)
    text = changelog.read_text(encoding="utf-8")
    assert versioning.changelog_section(text, "0.2.1") == (
        "### Fixed\n\n- A fourth crash.\n- A third crash.\n"
    )
    assert f"[0.2.1]: {base}0.2.0...0.2.1\n" in text


def test_folding_pre_releases_keeps_crlf_line_endings(release_files):
    version_file, changelog = release_files
    changelog.write_bytes(CHANGELOG.replace("\n", "\r\n").encode("utf-8"))
    bump_version.bump("0.2.0-rc.1", "2026-10-05", version_file, changelog)
    bump_version.bump("0.2.0", "2026-10-10", version_file, changelog)
    data = changelog.read_bytes()
    assert b"\r\n## [0.2.0] - 2026-10-10\r\n" in data
    assert b"0.2.0-rc.1" not in data
    assert data.count(b"\n") == data.count(b"\r\n")


def test_bump_version_refuses_an_empty_unreleased_section(release_files):
    version_file, changelog = release_files
    bump_version.bump("0.2.0", "2026-10-10", version_file, changelog)
    with pytest.raises(bump_version.BumpError, match="empty"):
        bump_version.bump("0.2.1", "2026-10-11", version_file, changelog)
    assert versioning.read_version(version_file) == "0.2.0"


def test_bump_version_refuses_an_existing_section(release_files):
    version_file, changelog = release_files
    changelog.write_text(
        CHANGELOG.replace("## [0.0.1]", "## [0.3.0] - 2020-01-01\n\n- x\n\n## [0.0.1]"),
        encoding="utf-8",
    )
    with pytest.raises(bump_version.BumpError, match="already has"):
        bump_version.bump("0.3.0", "2026-10-10", version_file, changelog)


def test_bump_version_command(release_files, monkeypatch, capsys):
    version_file, changelog = release_files
    monkeypatch.setattr(bump_version, "VERSION_FILE", version_file)
    monkeypatch.setattr(bump_version, "CHANGELOG_FILE", changelog)

    assert bump_version.main(["0.2.0", "--dry-run"]) == 0
    assert "dry run" in capsys.readouterr().out
    assert versioning.read_version(version_file) == "0.1.0"

    assert bump_version.main(["0.2.0", "--date", "2026-10-10"]) == 0
    assert "git tag -a 0.2.0" in capsys.readouterr().out
    assert versioning.read_version(version_file) == "0.2.0"

    assert bump_version.main(["0.2.0"]) == 1
    assert "already has" in capsys.readouterr().err
    assert bump_version.main(["0.1.5"]) == 1
    assert "older than" in capsys.readouterr().err


def test_bumped_version_file_stays_trivially_parseable(tmp_path):
    path = tmp_path / "version.py"
    path.write_text(
        Path(version.__file__).read_text(encoding="utf-8"), encoding="utf-8"
    )
    path.write_text(
        bump_version.bump_version_file(path.read_text(encoding="utf-8"), "9.8.7"),
        encoding="utf-8",
    )
    assert versioning.read_version(path) == "9.8.7"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    assert not any(isinstance(n, (ast.Import, ast.ImportFrom)) for n in tree.body)


# --- scoresight.spec vs the code ----------------------------------------------


def _spec_tree():
    return ast.parse(SPEC_FILE.read_text(encoding="utf-8"), filename=str(SPEC_FILE))


def _spec_data_globs():
    for node in _spec_tree().body:
        if isinstance(node, ast.Assign) and any(
            getattr(t, "id", None) == "DATA_GLOBS" for t in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError("scoresight.spec has no DATA_GLOBS list")


def _bundled_files():
    """Bundle-relative paths of the data files the spec collects."""
    bundled = set()
    for pattern, destination in _spec_data_globs():
        for path in REPO_ROOT.glob(pattern):
            if path.is_file():
                bundled.add(f"{destination}/{path.name}")
    return bundled


# The PP-OCR models are downloaded rather than committed
# (scripts/fetch_models.py): checked only once they are there (CI fetches them
# and sets SCORESIGHT_REQUIRE_PPOCR). Their LICENSE and NOTICE are committed.
FETCHED_FOLDER = "ocr_models/ppocr/"
COMMITTED_IN_FETCHED_FOLDER = ("LICENSE", "NOTICE")


def _is_fetched(pattern):
    return (
        pattern.startswith(FETCHED_FOLDER)
        and pattern[len(FETCHED_FOLDER) :] not in COMMITTED_IN_FETCHED_FOLDER
    )


def _skip_unless_fetched(pattern):
    if (
        _is_fetched(pattern)
        and not any(p.is_file() for p in REPO_ROOT.glob(pattern))
        and not REQUIRE_PPOCR
    ):
        pytest.skip(f"{pattern}: run python scripts/fetch_models.py")


def test_every_spec_data_glob_matches_files():
    missing = []
    for pattern, _ in _spec_data_globs():
        if _is_fetched(pattern) and not REQUIRE_PPOCR:
            continue
        if not [p for p in REPO_ROOT.glob(pattern) if p.is_file()]:
            missing.append(pattern)
    assert missing == []


def test_spec_bundles_the_ppocr_models_and_onnxruntime():
    """Every file of every PP-OCR model the engine loads (and fetch_models.py
    downloads) is in DATA_GLOBS, with the license, and onnxruntime is
    collected."""
    import ppocr_engine

    fetch_models = _load_script(
        "fetch_models", REPO_ROOT / "scripts" / "fetch_models.py"
    )
    globs = dict(_spec_data_globs())
    folders = {info.folder for info in ppocr_engine.MODELS.values()}
    assert folders == {model.folder for model in fetch_models.MODELS}
    for folder in folders:
        for name in (
            ppocr_engine.ONNX_FILE,
            ppocr_engine.CHARACTERS_FILE,
            ppocr_engine.CONFIG_FILE,
        ):
            assert globs.get(f"ocr_models/ppocr/{folder}/{name}") == (
                f"ocr_models/ppocr/{folder}"
            ), (folder, name)
    for name in ("LICENSE", "NOTICE"):
        assert (REPO_ROOT / "ocr_models" / "ppocr" / name).is_file()
        assert globs.get(f"ocr_models/ppocr/{name}") == "ocr_models/ppocr"
    assert (
        fetch_models.ONNX_FILE,
        fetch_models.CHARACTERS_FILE,
        fetch_models.CONFIG_FILE,
    ) == (
        ppocr_engine.ONNX_FILE,
        ppocr_engine.CHARACTERS_FILE,
        ppocr_engine.CONFIG_FILE,
    )
    spec = SPEC_FILE.read_text(encoding="utf-8")
    assert 'hiddenimports += ["onnxruntime"]' in spec


def test_spec_has_a_single_entry_script():
    # Every script passed to Analysis runs as __main__ in the frozen app, so
    # listing modules there re-ran them at startup and after the window closed.
    calls = [
        node
        for node in ast.walk(_spec_tree())
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "Analysis"
    ]
    assert len(calls) == 1
    scripts = calls[0].args[0]
    assert isinstance(scripts, ast.List) and len(scripts.elts) == 1
    assert "main.py" in ast.unparse(scripts.elts[0])


def test_spec_files_exist():
    # every os.path.join(ROOT, "literal", ...) path in the spec
    for node in ast.walk(_spec_tree()):
        if (
            isinstance(node, ast.Call)
            and ast.unparse(node.func) == "os.path.join"
            and node.args
            and getattr(node.args[0], "id", None) == "ROOT"
            and all(isinstance(a, ast.Constant) for a in node.args[1:])
        ):
            path = REPO_ROOT.joinpath(*(a.value for a in node.args[1:]))
            assert path.exists(), path


# Resources the code loads that the app doesn't need bundled.
NOT_BUNDLED = {".env": "optional developer file with SCORESIGHT_DEBUG; never shipped"}

# Folders the code references as a whole, with the files it loads from them
# (glob patterns relative to the folder). Every matching file must be bundled.
# A folder reference that isn't listed here means "everything in the folder".
FOLDER_CONTENTS = {
    # main.find_translation_file: scoresight_<locale>.qm (the .ts sources are
    # only for translators)
    "translations": ["scoresight_*.qm"],
    # tesseract.TextDetector: the models, loaded by name from the folder
    "tesseract/tessdata": ["*.traineddata"],
}

# Known broken resource references (pattern: reason), marked as strict expected
# failures. When the reference is fixed it disappears or starts to pass, and its
# entry must be removed.
KNOWN_BROKEN = {}


def _resource_references():
    """(location, pattern) for every resource_path(...) call in src/.

    String arguments are joined with "/"; f-strings and variables become "*".
    Calls whose first argument isn't a literal are skipped.
    """
    references = []
    for module in sorted(SRC_DIR.glob("*.py")):
        if module.name.startswith("ui_") or module.name == "resource_path.py":
            continue
        tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "resource_path"
                and node.args
                and isinstance(node.args[0], ast.Constant)
            ):
                continue
            parts = []
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    parts.append(arg.value)
                elif isinstance(arg, ast.JoinedStr):
                    parts.append(
                        "".join(
                            v.value if isinstance(v, ast.Constant) else "*"
                            for v in arg.values
                        )
                    )
                else:
                    parts.append("*")
            references.append((f"{module.name}:{node.lineno}", "/".join(parts)))
    return references


def _reference_params():
    params = []
    for location, pattern in _resource_references():
        marks = []
        if pattern in KNOWN_BROKEN:
            marks.append(pytest.mark.xfail(reason=KNOWN_BROKEN[pattern], strict=True))
        params.append(pytest.param(pattern, id=f"{location} {pattern}", marks=marks))
    return params


def test_resource_references_were_found():
    patterns = {pattern for _, pattern in _resource_references()}
    assert "tesseract/tessdata" in patterns
    assert "translations/scoresight_*.qm" in patterns
    assert "icons/circle-x.svg" in patterns
    # the folder and known-broken lists describe current references only
    assert set(FOLDER_CONTENTS) <= patterns
    assert set(KNOWN_BROKEN) <= patterns


@pytest.mark.parametrize("pattern", _reference_params())
def test_resources_loaded_by_the_code_are_bundled(pattern):
    """What works from source must also work in the frozen app."""
    _skip_unless_fetched(pattern)
    bundled = _bundled_files()
    if pattern in NOT_BUNDLED:
        assert not any(fnmatch.fnmatch(f, pattern) for f in bundled), (
            f"{pattern} must not be bundled: {NOT_BUNDLED[pattern]}"
        )
        return
    in_repo = REPO_ROOT / pattern
    if "*" not in pattern and in_repo.is_dir():
        # a folder: the files the code loads from it (by default all of them)
        contents = FOLDER_CONTENTS.get(pattern, ["*"])
        expected = {
            f"{pattern}/{p.name}"
            for p in in_repo.iterdir()
            if p.is_file() and any(fnmatch.fnmatch(p.name, c) for c in contents)
        }
    else:
        expected = {
            p.relative_to(REPO_ROOT).as_posix()
            for p in REPO_ROOT.glob(pattern)
            if p.is_file()
        }
    assert expected, f"{pattern} doesn't exist in the repository"
    assert expected <= bundled, sorted(expected - bundled)


def _tesseract_class(tree, name):
    return next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and node.name == name
    )


def _ocr_model_names():
    """The built-in model names TextDetector._resolve_model maps the model
    indexes to: its `return <folder>, "<name>"` statements."""
    tree = ast.parse((SRC_DIR / "tesseract.py").read_text(encoding="utf-8"))
    resolve = next(
        node
        for node in ast.walk(_tesseract_class(tree, "TextDetector"))
        if isinstance(node, ast.FunctionDef) and node.name == "_resolve_model"
    )
    return {
        node.value.elts[1].value
        for node in ast.walk(resolve)
        if isinstance(node, ast.Return)
        and isinstance(node.value, ast.Tuple)
        and len(node.value.elts) == 2
        and isinstance(node.value.elts[1], ast.Constant)
        and isinstance(node.value.elts[1].value, str)
    }


def _ocr_model_indexes():
    """The constants of TextDetector.OcrModelIndex (one per built-in model)."""
    tree = ast.parse((SRC_DIR / "tesseract.py").read_text(encoding="utf-8"))
    return {
        target.id
        for node in _tesseract_class(tree, "OcrModelIndex").body
        if isinstance(node, ast.Assign)
        for target in node.targets
    }


def test_builtin_ocr_models_exist_and_are_bundled():
    models = _ocr_model_names()
    assert {"daktronics", "scoreboard_general", "eng"} <= models
    # every model index maps to its own model
    assert len(models) == len(_ocr_model_indexes())
    bundled = _bundled_files()
    for model in models:
        path = f"tesseract/tessdata/{model}.traineddata"
        assert (REPO_ROOT / path).is_file(), path
        assert path in bundled, path


def test_every_translation_is_compiled_and_bundled():
    bundled = _bundled_files()
    sources = sorted((REPO_ROOT / "translations").glob("*.ts"))
    assert sources
    for ts in sources:
        qm = ts.with_suffix(".qm")
        assert qm.is_file(), f"{ts.name} has no compiled {qm.name}"
        assert f"translations/{qm.name}" in bundled


# --- scoresight.iss ---------------------------------------------------------------


def test_installer_upgrades_existing_installs_and_names_the_output():
    iss = ISS_FILE.read_text(encoding="utf-8")
    # 0.1.x installers had no AppId, so Inno Setup used the AppName
    assert re.search(r'^#define AppName "ScoreSight"$', iss, re.MULTILINE)
    assert re.search(r"^AppId=\{#AppName\}$", iss, re.MULTILINE)
    assert re.search(
        r"^OutputBaseFilename=scoresight-\{#AppVersion\}-windows-x64-setup$",
        iss,
        re.MULTILINE,
    )
    # the PyInstaller output folder (COLLECT name="scoresight")
    assert 'Source: "dist\\scoresight\\*"' in iss
    icon = re.search(r"^SetupIconFile=(.+)$", iss, re.MULTILINE).group(1)
    assert (REPO_ROOT / icon.replace("\\", "/")).is_file()


# --- scripts/ci/smoke_test.py -------------------------------------------------


def _fake_app(tmp_path, body):
    script = tmp_path / "fake_app.py"
    script.write_text(
        "import os, sys, time\n"
        "assert sys.argv[1:] == ['--self-test'], sys.argv\n"
        "assert os.environ['QT_QPA_PLATFORM'] == 'offscreen'\n"
        "log_dir = os.environ['SCORESIGHT_LOG_DIR']\n"
        "assert os.environ['SCORESIGHT_DATA_DIR']\n" + textwrap.dedent(body),
        encoding="utf-8",
    )
    return [sys.executable, str(script)]


def test_smoke_test_passes(tmp_path, capsys):
    app = _fake_app(tmp_path, "print('SELF-TEST OK')\n")
    assert smoke_test.run_smoke_test(app, timeout=60) == 0
    assert "smoke test passed" in capsys.readouterr().out


@pytest.mark.parametrize(
    "body, reason",
    [
        ("print('SELF-TEST OK')\nsys.exit(2)\n", "exit code 2"),
        ("print('all good')\n", "no 'SELF-TEST OK'"),
        ("time.sleep(60)\n", "no result within 3 s"),
    ],
)
def test_smoke_test_fails(tmp_path, capsys, body, reason):
    app = _fake_app(tmp_path, body)
    assert smoke_test.run_smoke_test(app, timeout=3) == 1
    assert reason in capsys.readouterr().out


def test_smoke_test_failure_prints_the_app_logs(tmp_path, capsys):
    app = _fake_app(
        tmp_path,
        """
        os.makedirs(log_dir, exist_ok=True)
        with open(os.path.join(log_dir, 'scoresight_1.log'), 'w') as f:
            f.write('Traceback: missing module foo')
        sys.exit(1)
        """,
    )
    assert smoke_test.run_smoke_test(app, timeout=60) == 1
    output = capsys.readouterr().out
    assert "scoresight_1.log" in output
    assert "missing module foo" in output


def test_smoke_test_command_needs_an_existing_executable(tmp_path, capsys):
    assert smoke_test.main([str(tmp_path / "missing.exe")]) == 1
    assert "does not exist" in capsys.readouterr().err


# --- workflows --------------------------------------------------------------------


def _github_tag_filter_to_regex(pattern):
    # GitHub's filter syntax as used in release.yml: [..] classes, "+" (one or
    # more of the previous character) and literal characters.
    regex = ""
    for token in re.findall(r"\[[^\]]*\]|.", pattern):
        if token.startswith("[") or token == "+":
            regex += token
        elif token in "*?!":
            raise AssertionError(f"unsupported filter syntax in {pattern!r}")
        else:
            regex += re.escape(token)
    return re.compile(regex)


def test_release_tag_filters_match_the_accepted_versions():
    yaml = pytest.importorskip("yaml")
    workflow = yaml.safe_load((WORKFLOWS / "release.yml").read_text(encoding="utf-8"))
    # PyYAML reads the bare `on:` key as the boolean True
    triggers = workflow.get("on", workflow.get(True))
    filters = [_github_tag_filter_to_regex(p) for p in triggers["push"]["tags"]]
    samples = [
        "0.2.0",
        "10.20.30",
        "0.2.0-beta.1",
        "0.2.0-rc.12",
        "v0.2.0",
        "0.2",
        "0.2.0-alpha.1",
        "0.2.0-rc",
        "0.2.0rc1",
        "0.2.0-rc.1-hotfix",
        "latest",
    ]
    for tag in samples:
        triggers_release = any(f.fullmatch(tag) for f in filters)
        assert triggers_release == bool(versioning.VERSION_RE.fullmatch(tag)), tag


def test_build_workflow_uploads_the_packages_the_release_expects():
    build = (WORKFLOWS / "build.yml").read_text(encoding="utf-8")
    release = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
    for suffix in [
        "windows-x64-setup.exe",
        "windows-x64-portable.zip",
        "linux-x64.tar.gz",
    ]:
        assert f"-{suffix}" in build, suffix
        assert f'"scoresight-$VERSION-{suffix}"' in release, suffix
    assert "-${{ matrix.target }}.dmg" in build
    assert "target: macos-arm64" in build
    assert '"scoresight-$VERSION-macos-arm64.dmg"' in release
    # 0.4.4 was the last release for Intel Macs
    assert "macos-x64" not in build
    assert "macos-x64" not in release


def test_the_release_notes_list_every_package_and_invite_to_discussions():
    import source_bar

    release = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
    footer = (REPO_ROOT / ".github" / "release-notes-footer.md").read_text(
        encoding="utf-8"
    )
    assert "cat .github/release-notes-footer.md >> release-notes.md" in release
    for suffix in [
        "windows-x64-setup.exe",
        "windows-x64-portable.zip",
        "macos-arm64.dmg",
        "linux-x64.tar.gz",
    ]:
        assert f'"scoresight-$VERSION-{suffix}"' in release, suffix
        assert f"`scoresight-*-{suffix}`" in footer, suffix
    # where the app's Feedback goes too
    assert f"({source_bar.COMMUNITY_URL})" in footer


def test_a_published_release_is_announced_in_discussions():
    workflow = _workflow("announce-release.yml")
    # PyYAML reads the bare `on:` key as the boolean True
    triggers = workflow.get("on", workflow.get(True))
    assert triggers["release"]["types"] == ["published"]
    assert "tag" in triggers["workflow_dispatch"]["inputs"]
    assert workflow["permissions"] == {"contents": "write", "discussions": "write"}
    assert workflow["jobs"]["announce"]["env"]["CATEGORY"] == "Announcements"


def _build_steps():
    yaml = pytest.importorskip("yaml")
    workflow = yaml.safe_load((WORKFLOWS / "build.yml").read_text(encoding="utf-8"))
    return [step for job in workflow["jobs"].values() for step in job["steps"]]


def test_windows_release_builds_sign_the_app_installer_and_uninstaller():
    job = _workflow("build.yml")["jobs"]["build"]
    gate = job["env"]["SIGN_WINDOWS"]
    for condition in [
        "inputs.release",
        "matrix.target == 'windows-x64'",
        "secrets.AZURE_CLIENT_SECRET != ''",
    ]:
        assert condition in gate, condition
    steps = job["steps"]
    names = [step.get("name") for step in steps]
    sign = names.index("Sign the app (Windows)")
    # the tests run the signed app, and the installer and the zip contain it
    assert names.index("Build with PyInstaller") < sign
    assert sign < names.index("Smoke test (--self-test)")
    assert steps[sign]["if"] == "env.SIGN_WINDOWS == 'true'"
    assert steps[sign]["run"] == (
        "./scripts/ci/sign_windows.ps1 dist/scoresight/scoresight.exe"
    )
    assert (REPO_ROOT / "scripts" / "ci" / "sign_windows.ps1").is_file()

    # Inno Setup signs Setup and the uninstaller with the same script
    package = steps[names.index("Package (Windows installer)")]
    assert "uses" not in package
    assert "/DSignTool=artifactsigning" in package["run"]
    assert (
        "/Sartifactsigning=pwsh -NoProfile -NonInteractive -File "
        "`$q$script`$q `$f" in package["run"]
    )
    assert '"$env:GITHUB_WORKSPACE\\scripts\\ci\\sign_windows.ps1"' in package["run"]
    iss = ISS_FILE.read_text(encoding="utf-8")
    assert re.search(
        r"^#ifdef SignTool\n(;.*\n)*SignTool=\{#SignTool\}\nSignedUninstaller=yes\n#endif$",
        iss,
        re.MULTILINE,
    )
    # the installer test checks the signatures before it uninstalls
    run = steps[names.index("Package (Windows portable zip) and test the installer")][
        "run"
    ]
    check = run.index("Get-AuthenticodeSignature")
    assert '$setup, "$app\\scoresight.exe", "$app\\unins000.exe"' in run[:check]
    assert check < run.index('Start-Process "$app\\unins000.exe"')


def test_secrets_reach_only_our_own_scripts():
    # A third-party action never gets a signing or notarization secret: those go
    # to `run` steps (the Inno Setup action was replaced by ISCC for this).
    for path in WORKFLOWS.glob("*.yml"):
        for job in _workflow(path.name)["jobs"].values():
            for step in job.get("steps", []):
                if "uses" in step:
                    assert "secrets." not in repr(step), (path.name, step)


LEGACY_ASSETS = {
    # the 0.1.0 release's packages (gh release view 0.1.0)
    "windows-x64": "scoresight-windows-0.1.0.zip",
    "macos-arm64": "scoresight-macos-arm64-0.1.0.dmg",
    "linux-x64": "scoresight-linux-0.1.0.tar",
}


def _workflow(name):
    yaml = pytest.importorskip("yaml")
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def test_build_workflow_tests_the_frozen_app_and_its_boot_time():
    job = _workflow("build.yml")["jobs"]["build"]
    steps = job["steps"]
    names = [step.get("name") for step in steps]
    # after the smoke test, against the built app of each target
    smoke = names.index("Smoke test (--self-test)")
    e2e, boot = names.index("End-to-end test"), names.index("Boot time")
    assert smoke < e2e < boot
    for step in (steps[e2e], steps[boot]):
        assert step["env"]["EXECUTABLE"] == "${{ matrix.executable }}"
    assert "scripts/ci/e2e_test.py" in steps[e2e]["run"]
    # our own boot time fails the build above (generous) limits
    run = steps[boot]["run"]
    assert "scripts/ci/boot_benchmark.py" in run and "--legacy" not in run
    assert "--max-cold-seconds" in run and "--max-warm-seconds" in run
    assert not steps[boot].get("continue-on-error")

    # every target compares with the 0.1.0 package for its platform
    targets = {entry["target"]: entry for entry in job["strategy"]["matrix"]["include"]}
    assert {t: e["legacy-asset"] for t, e in targets.items()} == LEGACY_ASSETS
    legacy = [step for step in steps if "0.1.0" in (step.get("name") or "")]
    assert len(legacy) >= 3
    for step in legacy:
        # the old app may misbehave headless: never fail the build
        assert step.get("continue-on-error") is True, step["name"]
    assert any("--legacy" in step.get("run", "") for step in legacy)

    # the results aren't packages: release.yml publishes the scoresight-* ones
    [upload] = [
        s for s in steps if s.get("name") == "Upload the test and benchmark results"
    ]
    assert not upload["with"]["name"].startswith("scoresight-")


def test_ci_runs_the_end_to_end_test_from_source():
    steps = _workflow("ci.yml")["jobs"]["test"]["steps"]
    [step] = [s for s in steps if "scripts/ci/e2e_test.py" in s.get("run", "")]
    assert step["run"].endswith("-- python src/main.py")
    assert not step.get("if"), "on every OS of the test matrix"


def test_linux_build_installs_the_libraries_of_qts_xcb_plugin():
    # PyInstaller bundles only the libraries it finds on the build machine.
    # Without libxcb-cursor0 and the other xcb-util libraries, the Linux package
    # failed to start on an X11 desktop that doesn't have them.
    [step] = [
        s for s in _build_steps() if s.get("name") == "Install Qt runtime libraries"
    ]
    packages = set(step["run"].split())
    for package in [
        "libxcb-cursor0",
        "libxcb-icccm4",
        "libxcb-image0",
        "libxcb-keysyms1",
        "libxcb-render-util0",
        "libxcb-shape0",
        "libxcb-xkb1",
        "libxkbcommon-x11-0",
    ]:
        assert package in packages, package


# --- repository configuration ---------------------------------------------------


def test_workflow_and_config_files_are_valid_yaml():
    yaml = pytest.importorskip("yaml")
    files = [
        *WORKFLOWS.glob("*.yml"),
        REPO_ROOT / ".github" / "dependabot.yml",
        REPO_ROOT / ".pre-commit-config.yaml",
    ]
    assert len(files) >= 5
    for path in files:
        assert isinstance(yaml.safe_load(path.read_text(encoding="utf-8")), dict), path


def test_pre_commit_ruff_matches_requirements_dev():
    pinned = re.search(
        r"^ruff==(\S+)",
        (REPO_ROOT / "requirements-dev.txt").read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    hook = re.search(
        r"astral-sh/ruff-pre-commit\s+rev:\s*v(\S+)",
        (REPO_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8"),
    )
    assert pinned and hook
    assert hook.group(1) == pinned.group(1), (
        "update the ruff-pre-commit rev in .pre-commit-config.yaml to match "
        "ruff in requirements-dev.txt"
    )


def _step_index(steps, predicate):
    return next(i for i, step in enumerate(steps) if predicate(step))


@pytest.mark.parametrize(
    ("workflow", "job", "consumer"),
    [
        ("ci.yml", "test", "python -m pytest"),
        ("build.yml", "build", "PyInstaller"),
    ],
)
def test_workflows_fetch_the_ppocr_models_first(workflow, job, consumer):
    steps = _workflow(workflow)["jobs"][job]["steps"]
    cache = _step_index(steps, lambda s: "actions/cache" in s.get("uses", ""))
    fetch = _step_index(
        steps, lambda s: s.get("run", "").strip() == "python scripts/fetch_models.py"
    )
    uses = _step_index(steps, lambda s: consumer in s.get("run", ""))
    assert cache < fetch < uses
    # cached per pinned set of models; the fetch verifies whatever was restored
    assert "hashFiles('scripts/fetch_models.py')" in steps[cache]["with"]["key"]
    assert "PP-OCRv6_small_rec" in steps[cache]["with"]["path"]
    assert not steps[fetch].get("continue-on-error")


def test_ci_tests_require_ppocr_and_run_both_engines_end_to_end():
    steps = _workflow("ci.yml")["jobs"]["test"]["steps"]
    [tests] = [s for s in steps if s.get("name") == "Run tests"]
    assert tests["env"]["SCORESIGHT_REQUIRE_PPOCR"] == "1"
    [e2e] = [s for s in steps if "scripts/ci/e2e_test.py" in s.get("run", "")]
    runs = e2e["run"].splitlines()
    assert len(runs) == 2 and "--engine tesseract" in runs[0]
    assert "--engine" not in runs[1]  # a new setup's default: PP-OCR
    build = [
        s
        for s in _workflow("build.yml")["jobs"]["build"]["steps"]
        if "scripts/ci/e2e_test.py" in s.get("run", "")
    ]
    assert ["--engine tesseract" in s["run"] for s in build] == [False, True]
    paths = _workflow("build.yml")[True]["pull_request"]["paths"]
    assert "scripts/fetch_models.py" in paths
