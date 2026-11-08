"""ocr_eval's Apple Vision adapter, with ocrmac faked (it only runs on macOS).

The fake follows ocrmac 1.0.1: OCR(image, framework=..., recognition_level=...,
language_preference=..., detail=True).recognize(px=True) returns
[(text, confidence, (x1, y1, x2, y2))] in pixels, origin top left, and Live
Text reports a confidence of 1.0. The adapter has not been run against the real
framework (see ocr_eval/engines/apple_vision.py)."""

import importlib.machinery
import sys
import types

import pytest

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")
pytest.importorskip("PIL")

from ocr_eval.engines import EngineUnavailable, discover  # noqa: E402
from ocr_eval.engines import apple_vision  # noqa: E402
from ocr_eval.engines.apple_vision import AppleVision  # noqa: E402


def _module(monkeypatch, name, **attributes):
    module = types.ModuleType(name)
    module.__spec__ = importlib.machinery.ModuleSpec(name, None)
    for key, value in attributes.items():
        setattr(module, key, value)
    monkeypatch.setitem(sys.modules, name, module)
    return module


class FakeOcrmac:
    """ocrmac.ocrmac with an OCR class whose results come from `read(image)`,
    a function of the PIL image returning [(text, confidence, (x1, y1, x2, y2))].
    Every call's image and keyword arguments are kept in `calls`."""

    def __init__(self, monkeypatch, read=None, livetext=True, macos=(15, 1)):
        self.calls = []
        self.read = read or (lambda image: [])
        fake = self

        class OCR:
            def __init__(
                self,
                image,
                framework="vision",
                recognition_level="accurate",
                language_preference=None,
                confidence_threshold=0.0,
                detail=True,
                unit="token",
            ):
                if framework == "livetext" and recognition_level != "accurate":
                    raise ValueError("Recognition level is not supported for Livetext")
                self.image = image
                fake.calls.append(
                    {
                        "image": image,
                        "framework": framework,
                        "recognition_level": recognition_level,
                        "language_preference": language_preference,
                        "detail": detail,
                    }
                )

            def recognize(self, px=False):
                assert px is True
                return fake.read(self.image)

        package = _module(monkeypatch, "ocrmac")
        package.__path__ = []
        module = _module(
            monkeypatch, "ocrmac.ocrmac", OCR=OCR, LIVETEXT_AVAILABLE=livetext
        )
        package.ocrmac = module
        for name in ("Vision", "objc"):
            _module(monkeypatch, name)
        monkeypatch.setattr(apple_vision, "_platform", lambda: "darwin")
        monkeypatch.setattr(apple_vision, "_macos_version", lambda: macos)


def _crop(height=24, width=36, colour=(0, 0, 200)):
    crop = np.zeros((height, width, 3), np.uint8)
    crop[:] = colour
    crop.flags.writeable = False
    return crop


def test_is_discovered_with_its_requirements_and_variants():
    registry = discover()
    assert registry.engines["apple-vision"] is AppleVision
    assert AppleVision.requirements == [
        "ocrmac==1.0.1",
        "pyobjc-framework-Vision==13.0",
    ]
    assert len(AppleVision.variants) == 18
    assert set(AppleVision.default_variants) <= set(AppleVision.variants)
    engine = AppleVision("livetext-tile-digits")
    assert engine.level == "livetext"
    assert engine.spec.preprocessing == "tile" and engine.spec.digits
    with pytest.raises(ValueError):
        AppleVision("tile")


def test_unavailable_off_macos(monkeypatch):
    monkeypatch.setattr(apple_vision, "_platform", lambda: "win32")
    assert AppleVision.unavailable_reason() == "macOS only (Apple Vision)"


def test_unavailable_without_ocrmac(monkeypatch):
    monkeypatch.setattr(apple_vision, "_platform", lambda: "darwin")
    monkeypatch.setattr(AppleVision, "imports", ("no_such_ocrmac_xyz",))
    reason = AppleVision.unavailable_reason()
    assert reason.startswith("missing Python modules: no_such_ocrmac_xyz")
    assert "pip install ocrmac==1.0.1" in reason


def test_available_with_ocrmac(monkeypatch):
    FakeOcrmac(monkeypatch)
    assert AppleVision.unavailable_reason() is None


def test_live_text_needs_sonoma(monkeypatch):
    FakeOcrmac(monkeypatch, macos=(13, 6))
    with pytest.raises(EngineUnavailable, match="needs macOS 14.0 or later"):
        AppleVision("livetext-raw").load()
    AppleVision("accurate-raw").load()  # Vision itself is fine


def test_live_text_unavailable_in_ocrmac(monkeypatch):
    FakeOcrmac(monkeypatch, livetext=False)
    with pytest.raises(EngineUnavailable, match="Live Text"):
        AppleVision("livetext-upscale").load()


def test_accurate_raw_passes_the_crop_as_rgb_and_orders_the_words(monkeypatch):
    fake = FakeOcrmac(
        monkeypatch,
        read=lambda image: [("34", 0.5, (20, 2, 34, 22)), ("12:", 1.0, (1, 2, 17, 22))],
    )
    engine = AppleVision("accurate-raw")
    engine.load()
    [result] = engine.recognize([_crop()], ["clock"])
    assert result == ("12: 34", 0.5, None)
    [call] = fake.calls
    assert call["framework"] == "vision"
    assert call["recognition_level"] == "accurate"
    assert call["language_preference"] == ["en-US"]
    assert call["detail"] is True
    image = call["image"]
    assert image.mode == "RGB" and image.size == (36, 24)
    # BGR (0, 0, 200) -> RGB (200, 0, 0)
    assert image.getpixel((0, 0)) == (200, 0, 0)
    info = engine.info()
    assert info["level"] == "accurate" and info["preprocessing"] == "raw"
    assert info["verified"] is False
    engine.close()


def test_fast_upscale_digits(monkeypatch):
    fake = FakeOcrmac(monkeypatch, read=lambda image: [("lO", 0.3, (30, 30, 90, 90))])
    engine = AppleVision("fast-upscale-digits")
    engine.load()
    results = engine.recognize([_crop(), _crop()], ["score", "text"])
    assert [(r.text, r.confidence) for r in results] == [("10", 0.3), ("lO", 0.3)]
    assert fake.calls[0]["recognition_level"] == "fast"
    # 24x36 -> 64x96, plus a 32 px margin on every side
    assert fake.calls[0]["image"].size == (160, 128)


def test_live_text_tile_has_no_confidence_and_votes(monkeypatch):
    def read(image):
        # copies of the 64x96 crop at x 32-128, 160-256, 288-384
        assert image.size == (416, 128)
        return [
            ("5", 1.0, (40, 40, 120, 90)),
            ("S", 1.0, (170, 40, 250, 90)),
            ("6", 1.0, (300, 40, 380, 90)),
        ]

    fake = FakeOcrmac(monkeypatch, read=read)
    engine = AppleVision("livetext-tile-digits")
    engine.load()
    [result] = engine.recognize([_crop()], ["score"])
    assert result.text == "5"
    assert result.confidence is None
    assert result.info == {"copies": ["5", "5", "6"]}
    assert fake.calls[0]["framework"] == "livetext"
    assert fake.calls[0]["recognition_level"] == "accurate"  # ocrmac's default


def test_runs_in_the_harness(monkeypatch, tmp_path):
    from test_ocr_eval_dataset import _row, make_dataset

    from ocr_eval.dataset import load_dataset
    from ocr_eval.runner import RunOptions, load_images, run_engine

    FakeOcrmac(monkeypatch, read=lambda image: [("12", 0.5, (0, 0, 10, 10))])
    rows = [
        _row(id="a1", image="images/a1.png", text="12"),
        _row(id="a2", image="images/a2.png", text="13"),
    ]
    dataset = load_dataset(str(make_dataset(tmp_path / "ds", rows)))
    record = run_engine(
        AppleVision,
        "accurate-upscale",
        dataset,
        load_images(dataset),
        RunOptions(),
        None,
    )
    assert record["status"] == "ok", record.get("traceback")
    assert [p["text"] for p in record["predictions"]] == ["12", "12"]
    assert [p["conf"] for p in record["predictions"]] == [0.5, 0.5]
    assert record["scores"]["raw"]["exact"]["k"] == 1
    assert record["engine_info"]["verified"] is False


def test_skipped_in_the_harness_off_macos(monkeypatch, tmp_path):
    from test_ocr_eval_dataset import _row, make_dataset

    from ocr_eval.dataset import load_dataset
    from ocr_eval.runner import RunOptions, run_engine

    monkeypatch.setattr(apple_vision, "_platform", lambda: "linux")
    dataset = load_dataset(str(make_dataset(tmp_path / "ds", [_row()])))
    record = run_engine(AppleVision, "accurate-raw", dataset, [], RunOptions(), None)
    assert record["status"] == "skipped"
    assert record["reason"] == "macOS only (Apple Vision)"
