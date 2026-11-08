---
title: Tests & Code Style
parent: Developer Guide
nav_order: 3
description: "Run ScoreSight's pytest suite and self-test, and keep the code ruff-clean with pre-commit."
---

# Tests & Code Style
{: .no_toc }

<details open markdown="block">
  <summary>On this page</summary>
  {: .text-delta }
1. TOC
{:toc}
</details>

## Running the tests

The test suite lives in `tests/` and uses pytest (configured in `pyproject.toml`). With the dev requirements installed (see [Building from Source](building.md)):

```bash
python -m pytest
```

Tests are grouped with markers:

| Marker | Needs | Example |
|---|---|---|
| (none) | Only the Python dependencies | storage, defaults, file and HTTP output formats, the game-state engine and the sport profiles (`tests/test_game_state.py`, with a fake clock), packaging (`tests/test_packaging.py`) |
| `ocr` | `tesserocr` and the bundled models in `tesseract/tessdata` | recognition of synthetic digit images |
| `ppocr` | onnxruntime and the PP-OCR models (`python scripts/fetch_models.py`) | the PP-OCR engine reading synthetic digits, clocks and text; the app reading like the OCR evaluation |
| `qt` | Qt, running offscreen | widgets and dialogs |

Without the PP-OCR models the `ppocr` tests are skipped, and the packaging tests skip the model files they would check. With `SCORESIGHT_REQUIRE_PPOCR` set (CI sets it after fetching the models) a missing model or onnxruntime stops the run with an error instead, so they can't be skipped unnoticed. The other PP-OCR tests (decoding with whitelists, batching, the result states, the lazy load, the fallback, the model list, Image cleanup, PP-OCR (automatic), the hint) use a fake onnxruntime session or a fake engine and always run.

`tests/test_packaging.py` checks the release machinery without building: version parsing and the tag check, CHANGELOG section extraction and `scripts/bump_version.py`, the smoke-test runner, that `DATA_GLOBS` in `scoresight.spec` covers every resource the code loads, the installer's invariants, and that the workflows agree on the package names.

Select or skip groups with `-m`:

```bash
python -m pytest -m "not ocr"            # skip OCR tests
python -m pytest -m "not ocr and not qt" # fastest: pure-Python tests only
python -m pytest tests/test_storage.py -q
```

Qt tests run without a display. If you run them on a headless machine and they can't find a display, set `QT_QPA_PLATFORM=offscreen`.

The tests use temporary folders for settings and logs (see `tests/conftest.py`), so they don't touch your real ScoreSight configuration.

## The self-test

`--self-test` checks a complete installation without showing a window. It:

1. prints the settings file and log file paths,
2. imports every app module (the list in `SELF_TEST_MODULES` in `src/main.py`; a test checks that it covers every module in `src/`),
3. checks that the bundled files exist,
4. builds the main window UI off-screen and loads a translation,
5. loads all four bundled Tesseract models and every PP-OCR choice (accurate, fast and automatic), and requires the English model and every PP-OCR choice to read a rendered "45". The PP-OCR models must be there in a packaged build; from source, without them, it only warns,
6. resolves uvicorn's dynamic imports,
7. enumerates the video sources. A failure here (for example the Windows camera enumerator wasn't built) is only a warning when running from source, but fails a packaged build.

It prints `SELF-TEST OK` and exits with code 0, or prints the failure and exits with code 1. It sets `QT_QPA_PLATFORM=offscreen` if that isn't set, so it works on machines without a display:

```bash
python src/main.py --self-test
```

CI runs the same check against the frozen (PyInstaller) app on every platform with `scripts/ci/smoke_test.py`, to catch missing modules or data files in the package (see [Building from Source](building.md#package-with-pyinstaller)).

## The end-to-end test

`scripts/ci/e2e_test.py` runs the real app headless against a synthetic scoreboard video and checks that the readings reach the outputs. Give it the command that starts the app, from source or a packaged build:

```bash
python scripts/ci/e2e_test.py -- python src/main.py
python scripts/ci/e2e_test.py --engine tesseract -- python src/main.py
python scripts/ci/e2e_test.py -- dist/scoresight/scoresight.exe                 # Windows build
python scripts/ci/e2e_test.py -- dist/ScoreSight.app/Contents/MacOS/scoresight  # macOS build
```

It:

1. renders a short video with the 7-segment digits of `tests/synthetic_images.py`: the home score goes 0, 1, 2 while the away score stays 3 and the clock counts down from 12:00, then the final state (2, 3, 11:51) holds for 8 seconds;
2. writes the settings of a profile `e2e` in a temporary settings folder: the video as the source, Home Score, Away Score and Time boxes, the `.txt`, `results.csv` and `results.xml` file outputs, and the outbound API pointed at a mock server that the script runs;
3. starts the app with `--profile e2e --port <free port>` and follows `GET /json`, `/csv?pivot` and `/xml`, the files and the mock server until each has shown the home score going 0, 1, 2 and the final state. A good reading that isn't one of the video's values fails the test (a rejected or empty reading doesn't);
4. stops the app the way a user would (`SIGTERM`, or Ctrl+Break on Windows), requires exit code 0 and checks that the settings file still has the boxes;
5. checks the OCR engine: `--engine ppocr` (the default) leaves the OCR model out of the settings, as in a new setup, and requires the log to show PP-OCR loaded (without falling back to Tesseract) and the settings file to have PP-OCR (automatic) stored afterwards; `--engine tesseract` chooses General Scoreboard. Whether automatic switched to its fast model is in the `--json` details.

A run takes about 10 seconds. `--work-dir DIR` keeps the video, settings, logs and outputs, `--json FILE` writes the timings and the checks, and a failure prints the app's output and log files. A video file source plays in a loop (the capture thread starts it again at the end), which is why each output is checked over the whole run. vMix isn't covered: it sends only after **Start vMix**, which isn't saved.

The boxes have autocrop on and no dilation, for Tesseract's General Scoreboard model (PP-OCR ignores those Image cleanup settings). `tests/test_ci_scripts.py` checks with the real OCR that both engines read every state of the video, so a change in the models, in Tesseract or in the PP-OCR engine shows up in the test suite first. CI runs both engines from source, and `build.yml` both on the frozen app.

## Boot time

`scripts/ci/boot_benchmark.py` measures how long the app takes from launch until its HTTP server answers, over several runs with fresh settings:

```bash
python scripts/ci/boot_benchmark.py --runs 5 -- dist/scoresight/scoresight.exe
python scripts/ci/boot_benchmark.py --runs 5 -- python src/main.py
```

Run 1 is reported as cold (the first launch of that binary), the others as warm (median and range), together with the startup phases the app measures itself (see below). In `build.yml` the self-test and the end-to-end test have already started the build, so its run 1 is the first start with fresh settings rather than the first launch of the binary (the 0.1.0 comparison's run 1 is a true first launch). `--max-cold-seconds` and `--max-warm-seconds` make it fail above a limit, `--json FILE` writes the results and `--compare A.json B.json` shows earlier results side by side. `--legacy` measures a 0.1.x build, which has no `--port` option and always serves on port 18099 (close any other ScoreSight first). It also ignores `SCORESIGHT_DATA_DIR` and `SCORESIGHT_LOG_DIR`, so it uses your real settings and log folders.

### Startup timing

Once the app is ready, it logs one line with the time each startup phase took:

```
Startup: before main.py 0.20 s, arguments 0.00 s, imports 0.35 s, QApplication 0.00 s, main window 0.03 s, show 0.00 s, first event loop pass 0.01 s; total 0.59 s; HTTP server ready at 0.57 s, video sources discovered at 0.62 s
```

"before main.py" is the time from the creation of the process (the packaged app's loader and the Python interpreter) to `src/main.py`, the phases follow each other, and "total" and the "at" times count from the creation of the process. The line is logged when the video sources are discovered, or 5 seconds after the window appeared; a later "video sources discovered" gets a line of its own. With `SCORESIGHT_STARTUP_REPORT=<path>` set, the app also writes the milestones to that file as JSON, which the benchmark reads. The milestones are recorded in `src/startup_timing.py`.

To see which imports are slow, run the app from source with Python's import timer and stop it with Ctrl+C once it is up:

```bash
python -X importtime src/main.py -platform offscreen 2> importtime.txt
```

## Code style: ruff

ScoreSight uses [ruff](https://docs.astral.sh/ruff/) for linting and formatting (configured in `pyproject.toml`, targeting Python 3.13). The generated `src/ui_*.py` files are excluded.

```bash
ruff check .            # lint
ruff check --fix .      # lint and apply safe fixes
ruff format .           # format
ruff format --check .   # what CI runs
python scripts/compile_ui.py --check   # are the generated src/ui_*.py up to date?
python scripts/update_translations.py --check   # are translations/*.ts and .qm up to date?
```

CI fails if `ruff check .`, `ruff format --check .`, `scripts/compile_ui.py --check` or `scripts/update_translations.py --check` reports anything, so run them before you push. The translations check fails when user-visible text in `src/*.ui` or a `tr()` / `translate()` string changed without a refresh of the `.ts` and `.qm` files: run `python scripts/update_translations.py` (see [Translations](translations.md)).

## pre-commit (recommended)

[pre-commit](https://pre-commit.com/) runs the checks automatically on every commit: ruff (lint with `--fix`, and format, on Python files only), YAML and TOML syntax, merge-conflict markers, trailing whitespace and end-of-file fixes, and a check for large files. The ruff version in `.pre-commit-config.yaml` must match `requirements-dev.txt` (a test checks this).

```bash
pre-commit install          # once per clone
pre-commit run --all-files  # check everything now
```

## Continuous integration

Four workflows in `.github/workflows/` run on GitHub Actions:

| Workflow | Runs on | What it does |
|---|---|---|
| `ci.yml` | Every pull request, every push to `main`, manual runs | **Lint**: `ruff check`, `ruff format --check`, `scripts/compile_ui.py --check`, `scripts/update_translations.py --check`, and a check that no file links to the lapsed `scoresight[.]live` domain. **Test**: fetches the PP-OCR models (`scripts/fetch_models.py`, cached with `actions/cache`; it fails after its retries), then `pytest` with Python 3.13 on Ubuntu 24.04 and Windows (with `SCORESIGHT_REQUIRE_PPOCR`), then the [end-to-end test](#the-end-to-end-test) from source with Tesseract and with PP-OCR (its files are uploaded if the job fails). macOS runs the tests only on pushes to `main`, to save scarce macOS runners. An extra Python 3.14 leg on Ubuntu is allowed to fail |
| `build.yml` | Pull requests that change packaging files (`scoresight.spec`, `scoresight.iss`, `entitlements.plist`, the `requirements*.txt` files except dev/tools, `scripts/ci/`, `scripts/fetch_models.py`, `ocr_models/`, `src/main.py`, `src/resource_path.py`, `src/version.py`, `src/win32DeviceEnum/`, the workflow itself), manual runs (**Actions > Build > Run workflow**), and release tags through `release.yml` | Fetches the PP-OCR models (cached; fails after its retries), builds Windows x64, macOS arm64 and Linux x86_64 with PyInstaller, runs the frozen app's `--self-test`, the [end-to-end test](#the-end-to-end-test) with PP-OCR and with Tesseract and the [boot benchmark](#boot-time) (5 runs; it fails above 60 s cold or a 20 s warm median, generous limits for GitHub-hosted runners that only catch a gross regression), and packages the installer, portable zip, disk images and archive. For comparison it also downloads the 0.1.0 release for the platform and benchmarks it (3 runs; these steps never fail the build). The job summary shows the end-to-end test and both boot times side by side, and the `ci-results-<target>` artifact has the JSON results. On Windows it also installs the installer silently, self-tests the installed app and uninstalls it. The packages are uploaded as workflow artifacts |
| `release.yml` | Version tags only | See [Releasing](releasing.md) |
| `ocr-eval.yml` | Pull requests and pushes to `main` that change recognition (`src/tesseract.py`, `src/ppocr_engine.py`, `src/defaults.py`, `src/text_detection_target.py`, `tesseract/`, `scripts/fetch_models.py`, `ocr_eval/`, `requirements.txt`, `requirements-eval.txt`, the workflow itself), and manual runs | Runs ScoreSight's Tesseract pipeline with every bundled model, the PP-OCRv6 `small` and `tiny` recognizers, and the app's own PP-OCR engine (`ppocr-app`), on the committed evaluation datasets, and fails if exact-match accuracy drops by more than 2 points against the baselines in `ocr_eval/baselines/` (`tesseract.json`, `tesseract-commons.json`, `ppocr-ci.json`, `ppocr-app-ci.json`). The PP-OCR models are cached; a download that fails fails the job, except that a pull request skips the PP-OCR comparison with a warning when the Hugging Face Hub stays unreachable after retries. The reports are in the job summary and the results are uploaded as artifacts. See [OCR Evaluation](ocr-eval.md) |

Pull request builds, including those from forks, are unsigned. A pull request should be green before review. Test packages from a pull request or a manual run are named `scoresight-<version>-<short commit>-<platform>...`.

## Writing tests

- Put tests in `tests/test_<area>_*.py` and use the fixtures from `tests/conftest.py`.
- Mark tests that need Tesseract with `@pytest.mark.ocr`, tests that need the PP-OCR models with `@pytest.mark.ppocr`, and tests that create Qt widgets with `@pytest.mark.qt`.
- A test that constructs `TextDetector` for Tesseract passes the model (`TextDetector(TextDetector.OcrModelIndex.SCOREBOARD_GENERAL)`): with nothing stored it reads with a new setup's default, PP-OCR (automatic).
- Don't open real cameras, network ports or user folders. Use temporary paths, synthetic images (`numpy`/`cv2`) and local test servers.
- For a bug fix, add a test that fails without the fix.
