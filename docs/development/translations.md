---
title: Translations
parent: Developer Guide
nav_order: 4
description: "Update, translate and compile ScoreSight's Qt translation files, and add a new language."
---

# Translations
{: .no_toc }

<details open markdown="block">
  <summary>On this page</summary>
  {: .text-delta }
1. TOC
{:toc}
</details>

ScoreSight's interface is translated with Qt's translation system. Every language has a source file `translations/scoresight_<locale>.ts` (XML, edited by translators) and a compiled file `translations/scoresight_<locale>.qm` (loaded by the app). Both are committed.

Available locales: `en_US`, `da_DK`, `de_DE`, `es_ES`, `fr_FR`, `it_IT`, `ja_JP`, `ko_KR`, `nl_NL`, `pl_PL`, `pt_BR`, `pt_PT`, `ru_RU` and `zh_CN`.

At startup ScoreSight picks the language in this order:

1. the language chosen in **View > Language** (saved as the `language` setting),
2. the system's UI languages and locale: an exact match such as `de_DE`, or else another region of the same language (`de_AT` gets `de_DE`, `fr_CA` gets `fr_FR`, `pt_AO` gets `pt_PT`; the language's "home" region is preferred),
3. `en_US`.

## Workflow

### 1. Extract new strings

After you add or change user-visible text in `src/*.ui` or in Python code (wrapped in `QCoreApplication.translate(...)` / `self.tr(...)`), update all `.ts` files from the repository root, with the dev environment active:

```bash
python scripts/update_translations.py
```

It updates every `translations/*.ts` file from `src/*.ui` and the non-generated `src/*.py` files, so your virtual environment, build folders and the generated `src/ui_*.py` aren't scanned. Then it compiles every `.qm` file (step 3). Existing translations are kept, new strings are added as unfinished, and strings that are gone are kept as obsolete.

{: .warning }
Don't pass the `src` directory to lupdate (`pyside6-lupdate src -ts ...`). It then scans only the `.ui` files and drops every string from the Python code, and CI's translations check fails. If you run lupdate yourself, list the files the way the script does (in bash):

```bash
pyside6-lupdate src/*.ui $(ls src/*.py | grep -v '/ui_') -ts translations/*.ts
```

### 2. Translate

Open a `.ts` file in **Qt Linguist** (`pyside6-linguist translations/scoresight_de_DE.ts`), translate the unfinished entries and mark them as done.

Most entries of the 13 translations are machine-drafted (in 0.2.0, Danish in 0.4.4): they have a translation, but are still marked unfinished, with the translator comment *Machine-drafted translation; please review*. `lrelease` ships unfinished translations, so the drafts show in the app; reviewing a language means correcting what reads wrong and marking each entry as done. The About dialog's license text stays English.

`tests/test_app_mainwindow_smoke.py::test_every_language_fits` checks, for every `.qm`, that no label or button of the side panes, the viewer column, the output pages or the status bar is cut off at 1366x768. A long translation that fails it can usually be shortened; a hint line can wrap.

Translators who prefer PO-file tools (Poedit, Weblate and similar) can convert with `ts2po` from the [Translate Toolkit](https://toolkit.translatehouse.org/) (`scripts/ts2po.ps1` converts every file), and convert back with `po2ts` afterwards.

### 3. Compile

After translating, compile the `.ts` files to `.qm` without rescanning the sources:

```bash
python scripts/update_translations.py --qm-only
```

On Windows, `scripts/compile_translations.ps1` does the same. By hand: `for ts in translations/*.ts; do pyside6-lrelease "$ts" -qm "${ts%.ts}.qm"; done`.

### 4. Test and commit

Start ScoreSight, choose the language in **View > Language** and check the main window and dialogs for truncated or untranslated text. Commit both the `.ts` and the `.qm` files.

{: .note }
Connection values in the `.ui` files (the vMix host, port and input, the UNO URL and Essentials overlay ID, the template text) are marked as not translatable, so switching the language never resets them. Keep it that way for any field whose default text is a value rather than a label.

## Adding a language

1. Create the new `.ts` file with lupdate, from the repository root in bash:

   ```bash
   pyside6-lupdate src/*.ui $(ls src/*.py | grep -v '/ui_') -ts translations/scoresight_sv_SE.ts
   ```

   lupdate sets `<TS language="sv_SE">` from the file name. From then on, `python scripts/update_translations.py` keeps the file up to date with the others, because it picks up every `translations/*.ts`.
2. Translate it and compile the `.qm` file (steps 2–3 above).
3. Add the language to the `LANGUAGES` tuple at the top of `src/mainwindow.py`, with its name in its own language (the **View > Language** menu lists the languages that way, untranslated):

   ```python
   ("sv_SE", "Svenska"),
   ```

4. The packaged app bundles every `translations/*.qm` file through the `DATA_GLOBS` list in `scoresight.spec`, so nothing needs to change there. `tests/test_packaging.py` checks it.
5. Add the language to the lists in `README.md` and in this documentation (FAQ and Keyboard & Mouse pages).

## Tips

- Keep translations short. Many labels sit in narrow side panels.
- Don't translate placeholders, product names (OBS, vMix, NDI, UNO) or technical values such as `{% raw %}{{template}}{% endraw %}`, `mm:ss` or `.Text`.
- If you only want to improve one language, a pull request that changes just that `.ts`/`.qm` pair is welcome.
