"""Windows' built-in OCR engine (Windows.Media.Ocr, the engine winocr wraps).

Needs Windows 10 or 11 with the OCR language pack for LANGUAGE (en-US), which
comes with the English (United States) language; install it in an
administrator PowerShell with:

    Add-WindowsCapability -Online -Name "Language.OCR~~~en-US~0.0.1.0"

The adapter does what winocr.recognize_cv2() does (BGR -> RGBA SoftwareBitmap
-> OcrEngine.recognize_async), through the same pywinrt packages winocr
installs, but creates the OcrEngine once in load(): winocr creates one per
call, which costs about 2.5 ms per crop and isn't part of the engine.

The engine returns lines of words with their boxes and no confidence, so every
prediction's confidence is None. Variants combine a preprocessing (raw, upscale
or tile) with an optional -digits suffix; see _os_ocr.py.

pywinrt 3.x shipped its own msvcp140.dll (14.29, Visual Studio 2019). Loaded
first, it is what every later extension gets, and code built with Visual Studio
2022 17.10 or later crashes with it: running Tesseract after Windows OCR in one
process ended in an access violation. pywinrt 4 ships none, but an older
install may still have it, so before importing pywinrt the adapter loads
System32's msvcp140.dll (the Visual C++ redistributable's), which later
imports then share (_load_system_msvcp140).
"""

import ctypes
import importlib.metadata
import os
import platform
import sys

import cv2

from ocr_eval.engines import Engine, EngineUnavailable, _os_ocr

# The pywinrt projections winocr 0.0.15 depends on (it doesn't pin them).
REQUIREMENTS: list[str] = [
    "winrt-runtime==4.1.0",
    "winrt-Windows.Foundation==4!10.0.28000.2957",
    "winrt-Windows.Foundation.Collections==4!10.0.28000.2957",
    "winrt-Windows.Globalization==4!10.0.28000.2957",
    "winrt-Windows.Graphics.Imaging==4!10.0.28000.2957",
    "winrt-Windows.Media.Ocr==4!10.0.28000.2957",
    "winrt-Windows.Storage.Streams==4!10.0.28000.2957",
]

LANGUAGE = "en-US"
LANGUAGE_PACK_HINT = (
    "install the OCR language pack in an administrator PowerShell: "
    f'Add-WindowsCapability -Online -Name "Language.OCR~~~{LANGUAGE}~0.0.1.0"'
)
WINRT_MODULES = (
    "winrt.windows.globalization",
    "winrt.windows.graphics.imaging",
    "winrt.windows.media.ocr",
    "winrt.windows.storage.streams",
)


def _platform() -> str:
    return sys.platform


def _load_system_msvcp140() -> None:
    """Load the Visual C++ runtime's msvcp140.dll from System32, if there is
    one, so that pywinrt's older bundled copy is never loaded (see the module
    docstring). Must run before the first pywinrt import; harmless if repeated."""
    if _platform() != "win32" or not hasattr(ctypes, "WinDLL"):
        return
    system = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")
    path = os.path.join(system, "msvcp140.dll")
    if os.path.isfile(path):
        try:
            ctypes.WinDLL(path)
        except OSError:
            pass


def _language_reason() -> str | None:
    """Why LANGUAGE can't be recognized here, or None if it can."""
    from winrt.windows.globalization import Language
    from winrt.windows.media.ocr import OcrEngine

    tags = [lang.language_tag for lang in OcrEngine.available_recognizer_languages]
    if OcrEngine.is_language_supported(Language(LANGUAGE)):
        return None
    installed = ", ".join(tags) or "none"
    return (
        f"no Windows OCR language pack for {LANGUAGE} (installed: {installed}); "
        f"{LANGUAGE_PACK_HINT}"
    )


class WindowsOcr(Engine):
    name = "windows-ocr"
    variants = _os_ocr.variant_names()
    description = (
        f"Windows.Media.Ocr, the OCR built into Windows 10/11 ({LANGUAGE}), "
        "as wrapped by winocr"
    )
    size = "built into Windows (OCR language pack)"
    license = "Windows component (proprietary); pywinrt bindings MIT"
    runtime = "WinRT (pywinrt), CPU, one crop per call"
    batch_size = 1

    def __init__(self, variant: str | None = None):
        super().__init__(variant)
        self.spec = _os_ocr.parse_variant(self.variant)
        self._engine = None
        self._max_dimension = None

    @classmethod
    def unavailable_reason(cls) -> str | None:
        if _platform() != "win32":
            return "Windows only (Windows.Media.Ocr)"
        # finding winrt.windows.* imports the winrt package
        _load_system_msvcp140()
        missing = _os_ocr.missing_modules(WINRT_MODULES)
        if missing:
            return (
                f"missing Python modules: {', '.join(missing)} "
                f"(pip install {' '.join(cls.requirements or REQUIREMENTS)})"
            )
        try:
            return _language_reason()
        except Exception as e:  # a broken WinRT install; load() reports details
            return f"Windows OCR is not usable: {type(e).__name__}: {e}"

    def load(self) -> None:
        _load_system_msvcp140()
        try:
            from winrt.windows.globalization import Language
            from winrt.windows.graphics.imaging import (
                BitmapPixelFormat,
                SoftwareBitmap,
            )
            from winrt.windows.media.ocr import OcrEngine
            from winrt.windows.storage.streams import DataWriter
        except ImportError as e:
            raise EngineUnavailable(f"can't import the WinRT OCR API: {e}") from None
        engine = OcrEngine.try_create_from_language(Language(LANGUAGE))
        if engine is None:
            raise EngineUnavailable(
                f"Windows can't create an OCR engine for {LANGUAGE}; "
                f"{LANGUAGE_PACK_HINT}"
            )
        self._engine = engine
        self._max_dimension = int(OcrEngine.max_image_dimension)
        self._bitmap_api = (BitmapPixelFormat, SoftwareBitmap, DataWriter)

    def _read(self, image) -> list[_os_ocr.Word]:
        BitmapPixelFormat, SoftwareBitmap, DataWriter = self._bitmap_api
        rgba = cv2.cvtColor(image, cv2.COLOR_BGR2RGBA)
        writer = DataWriter()
        writer.write_bytes(rgba.tobytes())
        bitmap = SoftwareBitmap.create_copy_from_buffer(
            writer.detach_buffer(),
            BitmapPixelFormat.RGBA8,
            rgba.shape[1],
            rgba.shape[0],
        )
        result = self._engine.recognize_async(bitmap).get()
        words = []
        for line in result.lines:
            for word in line.words:
                box = word.bounding_rect
                words.append(
                    _os_ocr.Word(word.text, box.x, box.y, box.width, box.height)
                )
        return words

    def recognize(self, crops, field_types):
        results = []
        for crop, field_type in zip(crops, field_types):
            prepared = _os_ocr.prepare(
                crop, self.spec.preprocessing, max_dimension=self._max_dimension
            )
            words = self._read(prepared.image)
            results.append(
                _os_ocr.assemble(words, prepared, field_type, self.spec.digits)
            )
        return results

    def close(self) -> None:
        self._engine = None

    def info(self) -> dict:
        info = super().info()
        info["language"] = LANGUAGE
        info.update(_os_ocr.describe(self.spec))
        if _platform() == "win32":
            info["os_version"] = f"Windows {platform.version()}"
        try:
            info["version"] = (
                f"winrt-runtime {importlib.metadata.version('winrt-runtime')}"
            )
        except importlib.metadata.PackageNotFoundError:
            pass
        return info
