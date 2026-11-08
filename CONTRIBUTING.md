# Contributing to ScoreSight

Thank you for helping make ScoreSight the best scoreboard-reading software around! Contributions of all sizes are welcome. This document explains how to get set up and what we expect from a pull request.

By participating you agree to follow our [Code of Conduct](CODE_OF_CONDUCT.md).

## Ways to contribute

- **Ask questions, share ideas and show your setup** in [Discussions](https://github.com/royshil/scoresight/discussions). Answering other users' questions there helps a lot too.
- **Report bugs** with the [bug report form](https://github.com/royshil/scoresight/issues/new/choose). Attach your log files: they are the single most useful thing for fixing a bug.
- **Suggest features** with the feature request form. Describe the production problem you want to solve, not only the solution.
- **Improve the documentation** in [`docs/`](docs/). Every page has an "Edit this page on GitHub" link.
- **Translate** the interface (see [Translations](https://royshil.github.io/scoresight/development/translations.html)).
- **Share scoreboard samples** (short clips or screenshots) that ScoreSight reads badly, in an issue.
- **Write code**: fix a bug or build a feature. For anything larger than a small fix, please open or comment on an issue first so we can agree on the approach.

Security vulnerabilities: please don't open a public issue. Follow [SECURITY.md](SECURITY.md).

## Development setup

You need Python **3.13**, git and (recommended) [uv](https://docs.astral.sh/uv/). On Windows you also need the Microsoft C++ Build Tools.

```bash
git clone https://github.com/<you>/scoresight.git
cd scoresight
uv venv --python 3.13
# activate: .venv\Scripts\activate (Windows) or source .venv/bin/activate (macOS/Linux)

uv pip install -r requirements-dev.txt -r requirements-win.txt   # Windows
uv pip install -r requirements-dev.txt -r requirements-mac.txt   # macOS
uv pip install -r requirements-dev.txt                           # Linux

python scripts/compile_ui.py      # generate src/ui_*.py from src/*.ui
python src/main.py --profile dev  # run with separate "dev" settings
```

On Windows, build the camera enumerator once (from the repository root):

```powershell
uv pip install -r requirements-build.txt
python src\win32DeviceEnum\setup.py build_ext --inplace
```

The full guide, including packaging, is in the [Developer Guide](https://royshil.github.io/scoresight/development/). The [architecture overview](https://royshil.github.io/scoresight/development/architecture.html) explains how the code fits together.

## Workflow

1. Fork the repository and create a branch from `main` with a descriptive name, for example `fix/vmix-timeout` or `feature/sets-preset`.
2. Make focused changes. One pull request per bug fix or feature is much easier to review than a large mixed one.
3. Add or update tests and documentation.
4. Run the checks below.
5. Add an entry to the `## [Unreleased]` section of [CHANGELOG.md](CHANGELOG.md) if users will notice the change.
6. Open a pull request against `main` and fill in the template.

## Code style

- Code is linted and formatted with **ruff** (configuration in `pyproject.toml`). CI runs:

  ```bash
  ruff check .
  ruff format --check .
  python scripts/compile_ui.py --check
  python scripts/update_translations.py --check
  ```

  Run `ruff check --fix .` and `ruff format .` to fix most issues automatically. If the translations check fails, run `python scripts/update_translations.py` and commit the updated `.ts` and `.qm` files (see [Translations](#translations)).
- Install the [pre-commit](https://pre-commit.com/) hooks to run the checks on every commit: `pre-commit install`.
- Follow the style of the surrounding code. Modules in `src/` import each other by bare name (`from storage import fetch_data`).
- Use `from sc_logging import logger` for logging, not `print`.
- Load bundled files (models, icons, translations) through `resource_path(...)`.

## Tests

```bash
python -m pytest                      # everything
python -m pytest -m "not ocr and not qt"   # quick pure-Python subset
python src/main.py --self-test        # headless check of the whole app
```

- Tests that need Tesseract are marked `ocr`, and tests that create Qt widgets are marked `qt`.
- Bug fixes should come with a test that fails without the fix.
- Tests must not use real cameras, network services or your real settings folder.

See [Tests & Code Style](https://royshil.github.io/scoresight/development/testing.html).

## Generated UI files

`src/ui_*.py` are **generated** from the Qt Designer files `src/*.ui`. Never edit them by hand.

1. Edit the `.ui` file in Qt Designer (`pyside6-designer src/mainwindow.ui`).
2. Run `python scripts/compile_ui.py`.
3. Commit both the `.ui` file and the regenerated `ui_*.py`.

If you change user-visible text, also update the translations (see below).

## Adding a per-box setting

A new box setting must be added in several places:

1. `defaults.normalize_settings_dict`: the key and its default (that is all saving needs: `storage.TextDetectionTargetMemoryStorage.getBoxesForStorage` saves exactly what `normalize_settings_dict` returns, and `tests/test_storage.py` checks this),
2. `box_settings_ui_handler.py` and `src/mainwindow.ui`: the UI,
3. `tesseract.py`: the processing (if any),
4. `docs/box-settings.md`: the documentation.

If the meaning of a stored value changes, also bump `storage.BOXES_SCHEMA_VERSION` and extend `storage.migrate_boxes`, so boxes saved by older versions are migrated when they are loaded.

## Translations

UI strings are translated with Qt Linguist. After changing UI text:

```bash
python scripts/update_translations.py   # extract strings from src/ into every .ts file, compile the .qm files
# translate in Qt Linguist: pyside6-linguist translations/scoresight_de_DE.ts
python scripts/update_translations.py --qm-only   # compile the .qm files after translating
```

Commit both `.ts` and `.qm` files. Details, and how to add a new language: [Translations](https://royshil.github.io/scoresight/development/translations.html).

## Packaging

PyInstaller follows the imports of `src/main.py`, so new modules are bundled automatically. Add every new module to `SELF_TEST_MODULES` in `src/main.py` (a test checks this). If you add a new data file (icon, model, translation, OBS asset) loaded through `resource_path(...)`, make sure a pattern in `DATA_GLOBS` in `scoresight.spec` matches it: `tests/test_packaging.py` fails otherwise. Pull requests that change packaging files also get test builds of every platform, including the packaged app's `--self-test`. See [Building from Source](https://royshil.github.io/scoresight/development/building.html#package-with-pyinstaller).

## Pull request expectations

- **CI is green**: lint and tests pass, and the platform builds when your change touches packaging.
- **Scope**: the PR does one thing and explains why in the description. Link the issue (`Fixes #123`).
- **Tested**: say which platforms you tested on (Windows / macOS / Linux) and how (video file, camera, NDI, RTSP...).
- **Screenshots** for UI changes.
- **Docs and CHANGELOG** updated when behaviour changes.
- **No generated or local files**: no `.venv/`, `build/`, `dist/`, `.env` or editor folders. Commit regenerated `ui_*.py` and `.qm` files only together with their sources.
- **Commit messages**: short imperative subject line (for example "Fix vMix port migration"). Prefixes like `fix:`, `feat:` and `docs:` are welcome but not required.

Maintainers may ask for changes or split large PRs. We aim to review promptly, but this is a volunteer project, so please be patient.

## License

By contributing, you agree that your contributions are licensed under the project's [MIT License](LICENSE).
