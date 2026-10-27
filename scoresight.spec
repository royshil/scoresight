# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for ScoreSight.

    pyinstaller --clean --noconfirm scoresight.spec              # release build
    pyinstaller --clean --noconfirm scoresight.spec -- --debug   # console build

Download the PP-OCR models first (python scripts/fetch_models.py): the build
bundles them and fails without them. Builds a onedir app for the platform it
runs on (PyInstaller can't cross-compile):
  Windows  dist/scoresight/scoresight.exe, with a splash screen. Build the
           camera enumerator first: cd src/win32DeviceEnum &&
           python setup.py build_ext --inplace
  macOS    dist/ScoreSight.app, signed with the identity in the
           APPLE_APP_DEVELOPER_ID environment variable if it is set, otherwise
           ad-hoc signed
  Linux    dist/scoresight/scoresight

src/main.py is the only entry script and PyInstaller follows its imports, so new
modules in src/ are bundled automatically. Data files come from DATA_GLOBS
(tests/test_packaging.py checks them against the resources the code loads). The
version comes from src/version.py. The old --win and --mac_osx flags are still
accepted, but the platform is detected.
"""

import argparse
import glob
import importlib.machinery
import os
import runpy
import sys

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
)

IS_WINDOWS = sys.platform == "win32"
IS_MACOS = sys.platform == "darwin"

parser = argparse.ArgumentParser(prog="pyinstaller scoresight.spec --")
parser.add_argument(
    "--debug",
    action="store_true",
    help="console build (Windows), so the log output and tracebacks are visible",
)
parser.add_argument("--win", action="store_true", help=argparse.SUPPRESS)
parser.add_argument("--mac_osx", action="store_true", help=argparse.SUPPRESS)
args = parser.parse_args()
if (args.win and not IS_WINDOWS) or (args.mac_osx and not IS_MACOS):
    parser.error(
        f"--win/--mac_osx don't match this platform ({sys.platform}); "
        "PyInstaller can't cross-compile"
    )

ROOT = SPECPATH  # SPECPATH is defined by PyInstaller: the folder of this file
SRC = os.path.join(ROOT, "src")

_versioning = runpy.run_path(os.path.join(ROOT, "scripts", "ci", "versioning.py"))
VERSION = _versioning["read_version"](os.path.join(SRC, "version.py"))
NUMERIC_VERSION = _versioning["numeric_version"](VERSION)  # X.Y.Z.0
SHORT_VERSION = NUMERIC_VERSION.rsplit(".", 1)[0]  # X.Y.Z

# Data files loaded through resource_path(): (glob relative to the repository
# root, folder inside the bundle). The build fails if a glob matches nothing.
DATA_GLOBS = [
    ("icons/*.svg", "icons"),
    ("icons/*.ico", "icons"),
    ("tesseract/tessdata/*.traineddata", "tesseract/tessdata"),
    # the PP-OCR models (not in git: scripts/fetch_models.py downloads them)
    # and their license
    ("ocr_models/ppocr/LICENSE", "ocr_models/ppocr"),
    ("ocr_models/ppocr/NOTICE", "ocr_models/ppocr"),
    (
        "ocr_models/ppocr/PP-OCRv6_small_rec/inference.onnx",
        "ocr_models/ppocr/PP-OCRv6_small_rec",
    ),
    (
        "ocr_models/ppocr/PP-OCRv6_small_rec/characters.txt",
        "ocr_models/ppocr/PP-OCRv6_small_rec",
    ),
    (
        "ocr_models/ppocr/PP-OCRv6_small_rec/config.json",
        "ocr_models/ppocr/PP-OCRv6_small_rec",
    ),
    (
        "ocr_models/ppocr/PP-OCRv6_tiny_rec/inference.onnx",
        "ocr_models/ppocr/PP-OCRv6_tiny_rec",
    ),
    (
        "ocr_models/ppocr/PP-OCRv6_tiny_rec/characters.txt",
        "ocr_models/ppocr/PP-OCRv6_tiny_rec",
    ),
    (
        "ocr_models/ppocr/PP-OCRv6_tiny_rec/config.json",
        "ocr_models/ppocr/PP-OCRv6_tiny_rec",
    ),
    ("translations/*.qm", "translations"),
    ("obs_data/Scoresight_OBS_scene_collection.json", "obs_data"),
    ("obs_data/Scoreboard parts/*.png", "obs_data/Scoreboard parts"),
    ("casparcg/*.html", "casparcg"),
    # the browser overlays' client, styles and example (overlays.py)
    ("overlays/*.js", "overlays"),
    ("overlays/*.css", "overlays"),
    ("overlays/*.html", "overlays"),
    # the phone camera's page (phone_camera.py)
    ("phone/*.html", "phone"),
]

datas = []
for pattern, destination in DATA_GLOBS:
    matches = sorted(glob.glob(os.path.join(ROOT, pattern)))
    if not matches:
        hint = (
            " (download the PP-OCR models: python scripts/fetch_models.py)"
            if pattern.startswith("ocr_models/")
            else ""
        )
        raise SystemExit(f"scoresight.spec: no files match {pattern!r}{hint}")
    datas += [(match, destination) for match in matches]


def _is_module_name(name):
    # cyndilib ships per-platform library folders such as
    # wrapper/bin/x86_64-linux-gnu, which aren't importable modules
    return all(part.isidentifier() for part in name.split("."))


# Imports made from compiled code are invisible to PyInstaller: tesserocr's
# extension imports cysignals (the PyPI package on macOS and Linux, a private
# tesserocr.cysignals copy in the Windows wheel), and cyndilib's extensions import
# each other and pugixml_cython.
hiddenimports = []
for package in ("tesserocr", "cyndilib", "pugixml_cython"):
    hiddenimports += collect_submodules(package, filter=_is_module_name)
if not IS_WINDOWS:
    hiddenimports += ["cysignals", "cysignals.signals"]
# The PP-OCR engine imports onnxruntime when a PP-OCR model is first chosen
# (src/ppocr_engine.py), not at startup. pyinstaller-hooks-contrib's hook
# collects its native libraries (onnxruntime and its pybind11 module, about
# 40 MB on Windows); its license and third-party notices ship next to them.
hiddenimports += ["onnxruntime"]
datas += collect_data_files(
    "onnxruntime", includes=["LICENSE", "ThirdPartyNotices.txt"]
)

pathex = [SRC]
binaries = []
excludes = ["PyQt5", "PyQt6", "tkinter", "_tkinter"]

if IS_WINDOWS:
    # The DirectShow camera enumerator (a pybind11 extension built in place).
    device_enum_dir = os.path.join(SRC, "win32DeviceEnum")
    if not any(
        os.path.isfile(os.path.join(device_enum_dir, "win32DeviceEnumBind" + suffix))
        for suffix in importlib.machinery.EXTENSION_SUFFIXES
    ):
        raise SystemExit(
            "scoresight.spec: build the camera enumerator for this Python first: "
            "cd src/win32DeviceEnum && python setup.py build_ext --inplace"
        )
    pathex.append(device_enum_dir)
    hiddenimports += [
        "screen_capture_source_windows",
        "win32DeviceEnum.enum_devices_dshow",
        "win32DeviceEnumBind",
    ]
    # cyndilib/__init__.py calls os.add_dll_directory(cyndilib/wrapper/bin), so
    # that folder, with the NDI runtime DLL, must exist in the frozen app. The
    # UWP and DirectShow-filter variants of the runtime (66 MB) aren't used.
    binaries += [
        (source, destination)
        for source, destination in collect_dynamic_libs("cyndilib")
        if ".UWP." not in source and ".DirectShow." not in source
    ]
    datas += collect_data_files("cyndilib", includes=["wrapper/bin/*.txt"])
    # The Windows tesserocr wheel keeps the Tesseract and Leptonica DLLs next to
    # its extension module.
    binaries += collect_dynamic_libs("tesserocr")
    excludes += ["screen_capture_source_mac"]
elif IS_MACOS:
    hiddenimports += ["screen_capture_source_mac"]
    excludes += ["screen_capture_source_windows", "win32DeviceEnum"]
else:
    excludes += [
        "screen_capture_source_mac",
        "screen_capture_source_windows",
        "win32DeviceEnum",
    ]

a = Analysis(
    [os.path.join(SRC, "main.py")],
    pathex=pathex,
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)

if IS_WINDOWS:
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo,
        StringFileInfo,
        StringStruct,
        StringTable,
        VarFileInfo,
        VarStruct,
        VSVersionInfo,
    )

    version_numbers = tuple(int(part) for part in NUMERIC_VERSION.split("."))
    version_info = VSVersionInfo(
        ffi=FixedFileInfo(filevers=version_numbers, prodvers=version_numbers),
        kids=[
            StringFileInfo(
                [
                    StringTable(
                        "040904B0",
                        [
                            StringStruct("CompanyName", "Roy Shilkrot"),
                            StringStruct("FileDescription", "ScoreSight"),
                            StringStruct("FileVersion", VERSION),
                            StringStruct("InternalName", "scoresight"),
                            StringStruct("LegalCopyright", "MIT License"),
                            StringStruct("OriginalFilename", "scoresight.exe"),
                            StringStruct("ProductName", "ScoreSight"),
                            StringStruct("ProductVersion", VERSION),
                        ],
                    )
                ]
            ),
            VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
        ],
    )
    splash = Splash(
        os.path.join(ROOT, "icons", "splash.png"),
        binaries=a.binaries,
        datas=a.datas,
        # the loading messages, under the logo (brand/make_assets.py)
        text_pos=(73, 330),
        text_size=9,
        text_color="#9AA7BD",
    )
    exe = EXE(
        pyz,
        a.scripts,
        splash,
        [],
        exclude_binaries=True,
        name="scoresight",
        icon=os.path.join(ROOT, "icons", "scoresight.ico"),
        version=version_info,
        console=args.debug,
        upx=False,
    )
    coll = COLLECT(
        exe, a.binaries, a.datas, splash.binaries, upx=False, name="scoresight"
    )
elif IS_MACOS:
    codesign_identity = os.environ.get("APPLE_APP_DEVELOPER_ID") or None
    entitlements_file = os.path.join(ROOT, "entitlements.plist")
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="scoresight",
        console=False,
        upx=False,
        argv_emulation=False,
        codesign_identity=codesign_identity,
        entitlements_file=entitlements_file,
    )
    coll = COLLECT(exe, a.binaries, a.datas, upx=False, name="scoresight")
    app = BUNDLE(
        coll,
        name="ScoreSight.app",
        icon=os.path.join(ROOT, "icons", "scoresight-macos.png"),
        # Keep the identifier: macOS ties the camera permission to it.
        bundle_identifier="com.royshilkrot.scoresight",
        version=SHORT_VERSION,
        info_plist={
            "CFBundleName": "ScoreSight",
            "CFBundleDisplayName": "ScoreSight",
            "CFBundleShortVersionString": SHORT_VERSION,
            "CFBundleVersion": SHORT_VERSION,
            # The tesserocr wheels (bundled Tesseract) target macOS 15.
            "LSMinimumSystemVersion": "15.0",
            "LSApplicationCategoryType": "public.app-category.video",
            "NSPrincipalClass": "NSApplication",
            "NSHighResolutionCapable": True,
            "NSAppleScriptEnabled": False,
            # OCR keeps running while the window is in the background: no App Nap.
            "NSAppSleepDisabled": True,
            "NSCameraUsageDescription": (
                "ScoreSight reads the scoreboard in the camera image."
            ),
            "NSScreenCaptureUsageDescription": (
                "ScoreSight reads the scoreboard in the window or screen you "
                "choose to capture."
            ),
        },
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="scoresight",
        console=True,
        upx=False,
    )
    coll = COLLECT(exe, a.binaries, a.datas, upx=False, name="scoresight")
