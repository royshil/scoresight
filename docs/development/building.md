---
title: Building from Source
parent: Developer Guide
nav_order: 2
description: "Set up a ScoreSight development environment with uv and Python 3.13, run from source, and package with PyInstaller."
---

# Building from Source
{: .no_toc }

<details open markdown="block">
  <summary>On this page</summary>
  {: .text-delta }
1. TOC
{:toc}
</details>

## Prerequisites

- **Python 3.13** (64-bit). 3.14 is also tested in CI.
- **git**
- **[uv](https://docs.astral.sh/uv/)** (recommended): a fast Python package and environment manager. Plain `python -m venv` + `pip` works too.
- **Windows**: [Microsoft C++ Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/) ("Desktop development with C++") to build the camera enumerator.
- **macOS**: Xcode Command Line Tools (`xcode-select --install`).
- **Linux**: the X11/xcb libraries Qt needs, for example on Debian/Ubuntu `sudo apt install libxcb-cursor0 libxkbcommon-x11-0 libegl1`.

## Requirements files

| File | Contents |
|---|---|
| `requirements.txt` | Runtime dependencies for all platforms (with environment markers), including onnxruntime for PP-OCR |
| `requirements-win.txt` | Windows extras, including the prebuilt Windows `tesserocr` wheel |
| `requirements-mac.txt` | macOS extras (PyObjC frameworks for camera enumeration and screen capture) |
| `requirements-dev.txt` | `-r requirements.txt` plus pytest, pytest-qt, ruff, pre-commit and PyYAML (for `scripts/fetch_models.py`) |
| `requirements-build.txt` | Packaging tools: PyInstaller, pyinstaller-hooks-contrib, pybind11, setuptools, PyYAML |
| `requirements-tools.txt` | Dependencies of the standalone scripts in `scripts/` (training-data utilities) |

`tesserocr` comes as a binary wheel with Tesseract included: from PyPI on macOS and Linux, and from the [simonflueckiger/tesserocr-windows_build](https://github.com/simonflueckiger/tesserocr-windows_build) releases on Windows (referenced in `requirements-win.txt`). You don't need a system-wide Tesseract installation.

{: .note }
The macOS `tesserocr` wheels target macOS 15 or newer. On older macOS versions, install Tesseract with Homebrew (`brew install tesseract`) and build tesserocr from source: `pip install --no-binary tesserocr tesserocr`.

## Set up the environment

```bash
git clone https://github.com/royshil/scoresight.git
cd scoresight
uv venv --python 3.13
```

Activate it:

```powershell
.venv\Scripts\activate          # Windows (PowerShell)
```
```bash
source .venv/bin/activate        # macOS / Linux
```

Install the dependencies for your platform:

```bash
uv pip install -r requirements-dev.txt -r requirements-win.txt   # Windows
uv pip install -r requirements-dev.txt -r requirements-mac.txt   # macOS
uv pip install -r requirements-dev.txt                           # Linux
```

Without uv, use `python -m venv .venv` and `pip install -r ...` with the same files.

### Windows: build the camera enumerator

On Windows, ScoreSight lists cameras through a small C++ extension (`src/win32DeviceEnum`, built with pybind11). Build it once per Python version, from the repository root:

```powershell
uv pip install -r requirements-build.txt   # pybind11 and setuptools; not installed automatically
python src\win32DeviceEnum\setup.py build_ext --inplace
```

This produces `win32DeviceEnumBind.cp313-win_amd64.pyd` (the name depends on your Python version) next to `setup.py`. The script works from any directory (`cd src\win32DeviceEnum` + `python setup.py build_ext --inplace` works too), and it stops with a clear message when it isn't run on Windows or pybind11 is missing. Without the extension, ScoreSight from source still runs but can't list cameras on Windows (`--self-test` only warns about it from source, and fails in a packaged build).

### Download the PP-OCR models

The PP-OCR engine's models (PaddleOCR's PP-OCRv6 small and tiny recognition models, 21 MB and 4.5 MB) aren't in git. Download them once:

```bash
python scripts/fetch_models.py           # what is missing; checks every file
python scripts/fetch_models.py --check   # only check (exit 1 if anything is missing or wrong)
```

It downloads each model's `inference.onnx` and `inference.yml` from its Hugging Face repository at a pinned revision (the revisions the [OCR evaluation](ocr-eval.md) measured), checks each against a pinned SHA-256, and writes `ocr_models/ppocr/<model>/inference.onnx`, `characters.txt` (the character list, so the app doesn't parse YAML) and `config.json` (the input size and channel order). It retries a failed download with a growing delay, writes through `.part` files, keeps files that are present and match (a second run downloads nothing) and exits with 1 on any failure. `HF_ENDPOINT` selects a Hugging Face mirror. `ocr_models/ppocr/` is gitignored except its `LICENSE` (Apache-2.0) and `NOTICE`, which are committed.

Without the models (or without onnxruntime) ScoreSight runs from source with Tesseract: the PP-OCR items of the OCR model list are disabled with a tooltip saying how to get them, and the `ppocr` tests are skipped. A packaged build needs them: the spec fails without them.

### Compile the UI files

The Qt Designer files `src/*.ui` are compiled into `src/ui_*.py`:

```bash
python scripts/compile_ui.py
```

(`scripts/compile_ui.ps1` and `scripts/compile_ui.sh` are thin wrappers around it.)

{: .important }
Never edit `src/ui_*.py` by hand. Change the `.ui` file in Qt Designer (`pyside6-designer`), run `scripts/compile_ui.py`, and commit both files. The generated files are excluded from ruff.

## Run from source

```bash
python src/main.py
```

You can run it from any working directory. Useful variations:

```bash
python src/main.py --profile dev --port 18199   # separate settings and port while developing
python src/main.py --self-test                  # headless sanity check, prints SELF-TEST OK
SCORESIGHT_DEBUG=1 python src/main.py           # log to the console too (macOS/Linux)
```

On Windows PowerShell, set the variable first with `$env:SCORESIGHT_DEBUG = "1"`. You can also put `SCORESIGHT_DEBUG=1` in a `.env` file in the repository root.

{: .tip }
Use a `--profile` while developing so you don't change the settings of the ScoreSight you use for real productions.

## Package with PyInstaller

The app is packaged with PyInstaller using `scoresight.spec`. Install the build requirements first:

```bash
uv pip install -r requirements-build.txt
```

Then build on the target platform (PyInstaller can't cross-compile). The command is the same on every OS; the spec detects the platform:

```bash
pyinstaller --clean --noconfirm scoresight.spec              # release build
pyinstaller --clean --noconfirm scoresight.spec -- --debug   # Windows console build that shows the log
```

On Windows, build the camera enumerator first, and on every OS download the PP-OCR models (see above). Options after `--` are passed to the spec file. The old `-- --win` and `-- --mac_osx` flags are still accepted, but no longer needed.

The spec builds a folder ("onedir") app on every OS:

| Platform | Output | Executable |
|---|---|---|
| Windows | `dist/scoresight/` | `dist/scoresight/scoresight.exe` (with a splash screen and version information) |
| macOS | `dist/ScoreSight.app` | `dist/ScoreSight.app/Contents/MacOS/scoresight` |
| Linux | `dist/scoresight/` | `dist/scoresight/scoresight` |

How the spec works:

- `src/main.py` is the only entry script. PyInstaller follows its imports, so new modules in `src/` are bundled automatically.
- Data files come from the `DATA_GLOBS` list in the spec: icons, the `.traineddata` models, the PP-OCR models (each model's `inference.onnx`, `characters.txt` and `config.json`, with the folder's `LICENSE` and `NOTICE`), the translations (`.qm`) and the OBS scene assets. The build fails if a pattern matches nothing. `tests/test_packaging.py` checks that every resource the code loads through `resource_path()` is covered, so **a new data file needs a matching glob** in `DATA_GLOBS`.
- onnxruntime is a hidden import (the PP-OCR engine imports it only when a PP-OCR model loads); pyinstaller-hooks-contrib's hook collects its native libraries, and its `LICENSE` and `ThirdPartyNotices.txt` are bundled. On Windows onnxruntime and the PP-OCR models add 66 MB to the app folder (345 MB to 411 MB): 39.7 MB of onnxruntime, 25.7 MB of models and 0.6 MB of the MSVC runtime.
- The version is read from `src/version.py`.
- The macOS app requires macOS 15 (`LSMinimumSystemVersion`), turns off App Nap, and carries the camera and screen-recording usage texts. It is signed with the identity in the `APPLE_APP_DEVELOPER_ID` environment variable if set, and ad-hoc signed otherwise.

Smoke-test the frozen app the way CI does:

```bash
python scripts/ci/smoke_test.py dist/scoresight/scoresight                       # Linux
python scripts/ci/smoke_test.py dist/scoresight/scoresight.exe                   # Windows
python scripts/ci/smoke_test.py dist/ScoreSight.app/Contents/MacOS/scoresight    # macOS
```

It runs the app's `--self-test` headless, with throw-away settings and log folders, and passes only if the app exits with code 0 and prints `SELF-TEST OK`. On failure it prints the app's output and log files. You can also run `<executable> --self-test` yourself.

### Windows installer and portable zip

The Windows installer is built from `scoresight.iss` with [Inno Setup](https://jrsoftware.org/isinfo.php) 6.3 or newer, after the PyInstaller build:

```powershell
iscc scoresight.iss
```

It reads the version from `src/version.py` and writes `dist\scoresight-<version>-windows-x64-setup.exe`. CI passes the version explicitly instead: `iscc /DAppVersion=<version> /DAppVersionNumeric=<X.Y.Z.0> scoresight.iss`. The installer:

- installs for all users by default and offers a per-user install in a dialog (or with `/CURRENTUSER` on the command line; `/ALLUSERS` forces the default),
- requires Windows 10 version 1809 or newer and an x64-compatible system,
- closes a running ScoreSight and removes the previous version's `_internal` folder before installing,
- keeps `AppId=ScoreSight`, the ID that 0.1.x installers used implicitly, so it upgrades existing installations in place. Never change it.

CI also zips `dist\scoresight` as `scoresight-<version>-windows-x64-portable.zip`.

`/DSignTool=<name>` signs Setup and the uninstaller with a Sign Tool defined on the same command line by `/S<name>=<command>`. In the command, `$f` is the quoted file and `$q` a quote. CI's release builds sign that way, and they also sign `scoresight.exe` before packaging it, with `scripts/ci/sign_windows.ps1` (Azure Artifact Signing). See [Signing](releasing.md#signing).

### macOS disk image, signing and notarization

CI copies `ScoreSight.app` and a link to `/Applications` into a compressed disk image, `scoresight-<version>-macos-arm64.dmg` (0.4.4 was the last release with an Intel build, `-macos-x64.dmg`). For **release builds**, and only when the Apple secrets are configured in the repository, CI signs the app with a Developer ID certificate, notarizes and staples both the app and the disk image (`scripts/ci/notarize_macos.sh`, then `scripts/ci/staple_macos.sh`, which tries the stapling again for about 9 minutes: right after notarization, Apple's ticket service sometimes drops the connection, stapler error 68). All other builds, including pull requests from forks, are unsigned. Run them via **System Settings** > **Privacy & Security** > **Open Anyway**, or remove the quarantine attribute with `xattr -dr com.apple.quarantine ScoreSight.app`. Entitlements are declared in `entitlements.plist`.

### Linux archive

CI packs the folder as `scoresight-<version>-linux-x64.tar.gz` (`tar -czf ... -C dist scoresight`), so it extracts to `scoresight/scoresight`. The build runs on Ubuntu 22.04, so the app needs glibc 2.35 or newer.

PyInstaller bundles only the shared libraries it finds on the build machine. The workflow's *Install Qt runtime libraries* step (in `build.yml`) installs `libxcb-cursor0` and the other xcb libraries that Qt's xcb platform plugin needs, so the package starts on X11 desktops that don't have them. Install the same packages before building a Linux package yourself.

## Standalone scripts

`scripts/` also contains standalone Tk/OpenCV utilities for preparing OCR training data. They are not part of the app. Install their dependencies in a separate environment with `uv pip install -r requirements-tools.txt` (it uses the GUI build of OpenCV), and run any of them with `--help` for its options:

| Script | What it does |
|---|---|
| `imagecropper.py` | Crop regions out of a folder of images (`--output` sets the output folder) |
| `images_pespective_cropper.py` | Perspective-correct a folder of images from four clicked corners (any click order) and save binarized PNG crops |
| `video_cropper.py` | Extract perspective-corrected crops from a video every N frames (`--every`, default 75) when enough pixels changed (`--min-changed-pixels`, default 400) |
| `imageannotator.py` | Type the text for each image and save it as a `.gt.txt` file (UTF-8), for tesstrain |

They handle missing or empty folders and non-ASCII paths, and close cleanly when you close their window.
