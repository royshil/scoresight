"""Apple's built-in OCR on macOS (the Vision framework, and Live Text), through
ocrmac.

UNVERIFIED: this adapter was written against ocrmac 1.0.1's documented API and
source and tested with ocrmac mocked (tests/test_ocr_eval_apple_vision.py); it
has not been run on a Mac yet. The first run on macOS should check that
`python -m ocr_eval run --dataset synthetic_7seg --engine apple-vision` reads
most crops and that no run ends in "error".

Each crop is read with

    ocrmac.OCR(image, framework=..., recognition_level=...,
               language_preference=[LANGUAGE], detail=True).recognize(px=True)

which returns (text, confidence, (x1, y1, x2, y2)) per text observation, in
pixels with the origin at the top left. Variants are LEVEL-PREPROCESSING with
an optional -digits suffix:

  accurate   Vision's VNRecognizeTextRequest, accurate recognition level
  fast       the same, fast recognition level (quicker, usually less accurate)
  livetext   Live Text (VisionKit's VKCImageAnalyzer, a private API ocrmac
             calls; it needs macOS 14 Sonoma or later and may change between
             macOS releases). It reports no confidence (ocrmac returns 1.0),
             so the adapter records None.

and the preprocessings of _os_ocr.py (raw, upscale, tile). Vision's language
correction stays on: ocrmac doesn't expose usesLanguageCorrection. ocrmac
creates a request per call and PNG-encodes the image; both are part of the
measured latency.
"""

import importlib.metadata
import platform
import sys

import cv2

from ocr_eval.engines import Engine, EngineUnavailable, _os_ocr

# ocrmac 1.0.1 depends on pyobjc-framework-Vision (unpinned), pillow and click.
REQUIREMENTS: list[str] = ["ocrmac==1.0.1", "pyobjc-framework-Vision==13.0"]

LANGUAGE = "en-US"
LEVELS = ("accurate", "fast", "livetext")
# ocrmac supports Live Text from macOS 14 Sonoma (Vision's text recognition
# itself needs 10.15)
LIVETEXT_MIN_MACOS = (14, 0)


def _platform() -> str:
    return sys.platform


def _macos_version() -> tuple[int, ...]:
    release = platform.mac_ver()[0]
    try:
        return tuple(int(part) for part in release.split("."))
    except ValueError:
        return ()


class AppleVision(Engine):
    name = "apple-vision"
    variants = _os_ocr.variant_names(LEVELS)
    default_variants = (
        "accurate-raw",
        "accurate-upscale",
        "accurate-upscale-digits",
        "accurate-tile-digits",
        "fast-tile-digits",
        "livetext-upscale-digits",
        "livetext-tile-digits",
    )
    description = (
        f"Apple Vision text recognition built into macOS ({LANGUAGE}), via ocrmac"
    )
    size = "built into macOS"
    license = "macOS component (proprietary); ocrmac and pyobjc MIT"
    runtime = "Vision / VisionKit (pyobjc), Apple Neural Engine or CPU"
    imports = ("ocrmac", "Vision", "objc", "PIL")
    batch_size = 1

    def __init__(self, variant: str | None = None):
        super().__init__(variant)
        self.spec = _os_ocr.parse_variant(self.variant)
        self.level = self.spec.level
        self._ocrmac = None
        self._image_class = None

    @classmethod
    def unavailable_reason(cls) -> str | None:
        if _platform() != "darwin":
            return "macOS only (Apple Vision)"
        return super().unavailable_reason()

    def load(self) -> None:
        try:
            from ocrmac import ocrmac
            from PIL import Image
        except ImportError as e:
            raise EngineUnavailable(f"can't import ocrmac: {e}") from None
        if self.level == "livetext":
            version = _macos_version()
            if version and version < LIVETEXT_MIN_MACOS:
                raise EngineUnavailable(
                    "Live Text needs macOS "
                    f"{'.'.join(map(str, LIVETEXT_MIN_MACOS))} or later "
                    f"(this is {'.'.join(map(str, version))})"
                )
            if not getattr(ocrmac, "LIVETEXT_AVAILABLE", False):
                raise EngineUnavailable("ocrmac can't use Live Text on this Mac")
        self._ocrmac = ocrmac
        self._image_class = Image

    def _read(self, image) -> list[_os_ocr.Word]:
        rgb = self._image_class.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
        if self.level == "livetext":
            ocr = self._ocrmac.OCR(
                rgb,
                framework="livetext",
                language_preference=[LANGUAGE],
                detail=True,
            )
        else:
            ocr = self._ocrmac.OCR(
                rgb,
                framework="vision",
                recognition_level=self.level,
                language_preference=[LANGUAGE],
                detail=True,
            )
        words = []
        for text, confidence, (x1, y1, x2, y2) in ocr.recognize(px=True):
            words.append(
                _os_ocr.Word(
                    str(text),
                    float(x1),
                    float(min(y1, y2)),
                    float(x2 - x1),
                    float(abs(y2 - y1)),
                    None if self.level == "livetext" else float(confidence),
                )
            )
        return words

    def recognize(self, crops, field_types):
        results = []
        for crop, field_type in zip(crops, field_types):
            prepared = _os_ocr.prepare(crop, self.spec.preprocessing)
            words = self._read(prepared.image)
            results.append(
                _os_ocr.assemble(words, prepared, field_type, self.spec.digits)
            )
        return results

    def close(self) -> None:
        self._ocrmac = None

    def info(self) -> dict:
        info = super().info()
        info["language"] = LANGUAGE
        info["level"] = self.level
        info.update(_os_ocr.describe(self.spec))
        # not yet run on a Mac (see the module docstring)
        info["verified"] = False
        if _platform() == "darwin":
            info["os_version"] = f"macOS {platform.mac_ver()[0]}"
        versions = []
        for package in ("ocrmac", "pyobjc-framework-Vision"):
            try:
                versions.append(f"{package} {importlib.metadata.version(package)}")
            except importlib.metadata.PackageNotFoundError:
                pass
        if versions:
            info["version"] = ", ".join(versions)
        return info
