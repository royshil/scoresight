## Summary

<!-- What does this PR change, and why? -->

Fixes #<!-- issue number, if any -->

## Type of change

- [ ] Bug fix
- [ ] New feature
- [ ] Documentation
- [ ] Build / CI / packaging
- [ ] Refactoring / maintenance
- [ ] Translations

## How was this tested?

<!-- Describe what you ran and how you checked the result (sources, outputs, scoreboard footage...). -->

Platforms tested:

- [ ] Windows
- [ ] macOS (Apple Silicon)
- [ ] Linux

## Checklist

- [ ] `ruff check .` and `ruff format --check .` pass
- [ ] `python -m pytest` passes, and new or changed behaviour has tests
- [ ] UI changes were made in `src/*.ui` and `src/ui_*.py` was regenerated with `python scripts/compile_ui.py` (no hand edits)
- [ ] User-visible text changes: `python scripts/update_translations.py` was run and the updated `.ts` and `.qm` files are committed (CI checks this)
- [ ] New modules or data files are included in `scoresight.spec`, and the packaged app's `--self-test` passes
- [ ] Documentation in `docs/` updated if behaviour changed
- [ ] `CHANGELOG.md` has an entry under `## [Unreleased]` (for user-visible changes)
- [ ] Screenshots attached for UI changes
