---
title: OCR Evaluation
parent: Developer Guide
nav_order: 6
description: "Measure OCR engines on real scoreboard crops against committed baselines: the datasets, the engines and how to run them, CI, adding an engine, and contributing data."
---

# OCR Evaluation
{: .no_toc }

<details open markdown="block">
  <summary>On this page</summary>
  {: .text-delta }
1. TOC
{:toc}
</details>

## Why

Whether ScoreSight should keep Tesseract, tune it, or move to another engine is decided by measurement only: every engine reads the same real scoreboard crops, the results are compared with committed baselines, and the comparison runs in CI. The harness is the `ocr_eval` package at the repository root (not shipped with the app).

**Where it stands** (the [OCR engine evaluation report](https://github.com/royshil/scoresight/blob/main/ocr_eval/results/2026-10-11/REPORT.md) has the details, from methodology to latency, packaging and a recommendation): on the 2,040 real crops a ScoreSight user would box (the Commons fields and TextOCR's scoreboard values, from 305 photos), PaddleOCR's PP-OCRv6 recognizers read 90–96% exactly, against 31% for ScoreSight's Tesseract setup, 46% for the best of its 8 untuned presets and 57% for Tesseract tuned on the dev split. The report recommends adding PP-OCRv6 with the whitelist decoder next to Tesseract, with `tiny` as the default until `small` (5 points more accurate, but 83–87% of a fast desktop core at the default load, and more than a whole slower core) has been measured on a laptop-class CPU, or a choice between them from the measured OCR time, and OCR moved off the capture thread.

| Engine:variant | User-relevant crops, exact % (n=2,040; 95% CI, photos resampled) | `commons_scoreboards` % | `textocr_scoreboards` % | Both real datasets % (n=2,320) | CPU ms per crop (1 thread, i9-14900K performance core) |
|---|---:|---:|---:|---:|---:|
| `ppocr:v6-medium-wl` | 96.4 (95.4–97.4) | 96.2 | 96.2 | 96.2 | 81 |
| `ppocr:v6-small-wl` | 95.1 (93.8–96.3) | 94.8 | 94.7 | 94.8 | 17 |
| `ppocr:v5-en-mobile-wl` | 92.3 (90.4–94.1) | 90.6 | 92.9 | 91.9 | 21 |
| `ppocr:v6-tiny-wl` | 90.0 (88.0–92.0) | 88.1 | 90.8 | 89.6 | 3.5 |
| `onnxtr:parseq-wl` | 86.4 (84.0–88.4) | 85.4 | 85.5 | 85.5 | 47 |
| `onnxtr:crnn_mobilenet_v3_small-wl` | 79.3 (76.4–81.9) | 78.8 | 77.5 | 78.1 | 1.2 |
| `tesseract:tuned` (settings chosen on the dev split) | 56.8 (53.5–60.2) | 58.0 | 52.2 | 54.8 | 2.2 |
| `tesseract:eng-nobin` (the best untuned preset) | 45.9 (42.4–49.4) | 52.8 | 35.9 | 43.5 | 3.2 |
| `tesseract:scoreboard_general` (the app's default) | 31.2 (27.8–34.5) | 40.5 | 17.6 | 27.9 | 2.0 |
| `windows-ocr:tile-digits` | 23.0 (19.9–26.3) | 22.8 | 25.5 | 24.3 | 2.8 |

Small vision-language models read about as well as PP-OCR `small` (Qwen3-VL-2B 93.5% on `textocr_scoreboards` against 94.7%, a statistical tie) but took 0.4–0.9 s per crop on a CPU; their evaluation was stopped ([below](#vision-language-models)).

## Quick start

```bash
python -m ocr_eval list                                   # datasets, engines and whether they can run here
python -m ocr_eval run --dataset textocr_scoreboards --dataset synthetic_7seg \
    --engine tesseract --out results/my-change            # results.json + report.md
python -m ocr_eval compare ocr_eval/baselines/tesseract.json results/my-change/results.json
python -m ocr_eval report results/my-change/results.json  # print the markdown report again
python -m ocr_eval review commons_scoreboards             # HTML contact sheet for checking labels
python -m ocr_eval requirements ppocr                     # an engine's pip requirements
```

Run it from the repository root. The Tesseract engine needs nothing beyond the app's development environment (see [Building from Source](building.md)). The harness never touches your ScoreSight settings or logs: it points `SCORESIGHT_DATA_DIR` and `SCORESIGHT_LOG_DIR` at a temporary folder unless you set them.

`run` options: `--engine NAME` runs the engine's default variants, `NAME:VARIANT` (or `NAME:V1,V2`, `NAME:*`) chooses; both `--dataset` and `--engine` repeat. `--split dev` or `--split test` keeps one split, `--limit N` the first N crops (quick runs), `--sample N` a stratified sample of N crops (for slow engines: allocated to the field types in proportion, with at least one each, and chosen by a hash of the crop id and `--seed`, so it is reproducible and the same crops on every machine), `--single-latency-samples N` how many crops engines that batch also read one at a time for the single-crop latency (default 50), `--label` names the run in the report. A run on a subset records it in `results.json` (`datasets.<name>.subset`) and its report says which subset it is. `compare` exits with 1 when a run regresses (see [CI](#continuous-integration)) and 2 on bad input; `--markdown FILE` also writes the comparison. `python -m ocr_eval.pairwise A.json B.json` pairs the runs of two results files crop by crop, for example two different engines (McNemar test, crops only one of them reads).

### The evaluation environment

Engines other than Tesseract need extra packages (onnxruntime, pywinrt, ...). They are not app dependencies: install them in a separate virtual environment, never in the app's. `requirements-eval.txt` pins every engine's extras, grouped by engine:

```bash
uv venv --python 3.13 .venv-eval
# Windows (.venv-eval/bin/python and requirements-mac.txt on macOS, no platform file on Linux)
uv pip install --python .venv-eval/Scripts/python.exe -r requirements-dev.txt -r requirements-win.txt -r requirements-eval.txt
.venv-eval/Scripts/python.exe -m ocr_eval list
```

`python -m ocr_eval requirements ENGINE` prints one engine's extras, for a lighter environment. The vision-language models' pins (PyTorch, transformers) are listed in `requirements-eval.txt` but commented out. Model weights are downloaded on first use into the libraries' caches and never committed; `HF_HUB_OFFLINE=1` makes the Hugging Face models load from the cache only.

## Datasets

A dataset is a folder with `manifest.jsonl`, the crop images, and `LICENSE` and `ATTRIBUTION.md` files. Datasets are found by name in `ocr_eval/datasets/` and in the folders listed in `$OCR_EVAL_DATASETS` (separated like `PATH`), or given by path. `python -m ocr_eval validate NAME_OR_PATH [--strict-licenses]` checks one.

Each line of `manifest.jsonl` is one crop:

| Field | Meaning |
|---|---|
| `id` | Unique id: letters, digits, `.`, `_`, `-` |
| `image` | The crop, a PNG path relative to the folder. Always the **raw** colour or gray crop, as a user's box would cut it from the frame, never a binarized one: preprocessing is part of what is evaluated |
| `text` | The ground truth, exactly as displayed |
| `field_type` | `score`, `clock`, `period`, `number`, `text` or `other` (below) |
| `display_tech` | `led7` (7-segment), `dotmatrix`, `lcd`, `bulb`, `flip` (flip or hand-hung cards), `broadcast` (rendered graphics), `printed` (painted or printed text), `unknown` |
| `split` | `dev` (tune on it) or `test` (report on it); `train` for crops meant for training. Assigned per source image, so one scoreboard is never in two splits |
| `label_source` | `human`, `model-assisted-unverified` or `synthetic` |
| `license` | The crop's license, SPDX style (`CC-BY-2.0`, `CC-BY-SA-4.0`, `CC0-1.0`, `PDM-1.0`, ...) |
| `source_url`, `author`, `attribution` | Where the source image comes from, who made it, and the attribution line its license asks for |
| `source_box` | `[x, y, w, h]` of the crop in the source image, or `null` |
| `notes` | Free text |

Other keys are allowed and kept (the TextOCR rows add `source_image` and `word_box`; the Commons rows `source_image`, `group`, `role`, `sport` and `source_size`). Three of them say which crops come from the same photo: `group` (photos of the same board and game), else `source_image`, else `frame`. Crops of one photo share its board, lighting and focus, so they aren't independent observations, and the clustered statistics below resample these photos instead of crops (`Sample.cluster`; a crop without any of the three is its own cluster).

Each field type is read with the box settings ScoreSight gives that kind of box (`ocr_eval/fields.py`, from `defaults.py`):

| `field_type` | ScoreSight box | Character whitelist | Format regex |
|---|---|---|---|
| `score` | Home Score preset | digits | `^1?\d{1,2}$` (0 to 199) |
| `clock` | Time preset | digits, `:`, `.` | `MM:SS` or `SS.D` |
| `period` | Period preset | digits | `^[1-4]$` |
| `number` | custom box | digits | any number |
| `text`, `other` | custom box of type Text | letters, digits, punctuation | any text |

Where a dataset gives each crop a role (`commons_scoreboards` does), a crop whose role has one of ScoreSight's preset boxes is read with that preset, as a user would box it: `home_score` and `away_score` with Home Score and Away Score, `clock` with Time, `period` with Period, `home_fouls` and `away_fouls` with Home Fouls and Away Fouls, and `shot_clock` with Shot Clock, whose format takes one or two digits (`0` to `39`; up to 0.3.0 it took exactly two, so a shot clock showing `7` was rejected). That applies only when the preset reads the same kind of value as the field type (a period that shows `4TH` is a `text` field, read as text); other roles (timeouts, downs, cricket counts, names) are read with their field type's box. An engine that reads with box settings (Tesseract) gets the roles too (`Engine.reads_roles`).

Settings that only matter across frames or format the output (smoothing, "skip similar image", ordinal indicator, leading zeros) are off: every crop is read once, as a fresh box.

### The committed datasets

| Dataset | Crops | Source | Labels | License |
|---|---:|---|---|---|
| `textocr_scoreboards` | 1,276 from 219 photos (dev 268, test 1,008) | Open Images photos tagged "Scoreboard" or "Digital clock" by TextVQA | TextOCR's human transcriptions; selection and display technologies reviewed with a model's help | CC BY 2.0 photos, CC BY 4.0 transcriptions |
| `commons_scoreboards` | 1,044 fields of 186 photos (dev 142, test 902) | Wikimedia Commons photos of scoreboards and video boards | Drawn and transcribed with a model's help: `model-assisted-unverified` until a person checks them | Per photo: CC BY-SA (747 crops), CC BY (224), CC0 (46), public domain (27) |
| `synthetic_7seg` | 56 | Rendered 7-segment LED and LCD digits | Synthetic | CC0 |

**`textocr_scoreboards`** (about 11 MB): real scoreboards and clocks. The photos are the TextVQA images tagged "Scoreboard" or "Digital clock" whose Open Images metadata lists a license that allows redistribution (all of them are CC BY 2.0); the transcriptions are TextOCR's human annotations (CC BY 4.0). `ocr_eval/builders/textocr_scoreboards.py` rebuilds it from scratch (`python -m ocr_eval.builders.textocr_scoreboards --cache FOLDER`; it downloads about 3.1 GB, 2.7 GB of which is the Open Images metadata CSV, filtered as it streams in, and keeps about 0.5 GB in the cache folder). It keeps clocks (`M:SS`, `MM:SS`, `S.D`), numbers of 1 to 3 digits, ordinals and common scoreboard words that are at least 12 px tall and nearly level, at most 12 per photo, and pads each word box by a quarter of its height like a user's box. Every remaining crop was then reviewed on contact sheets (`--contact-sheets FOLDER` renders them): crops that aren't scoreboard values (phone screens, analog dials, signs, jerseys, ads, keypads), aren't legible, or whose transcription disagrees with the display were dropped, and each photo or crop got a display technology. The decisions are in `ocr_eval/builders/textocr_scoreboards_review.json`, and the dataset's `dropped.jsonl` and `README.md` list every dropped candidate with its reason. Field types come from the transcription only: `number` covers scores, periods, innings and other numbers alike. The review was model-assisted (Claude), so a second human pass is welcome.

**`commons_scoreboards`** (about 24 MB with the downscaled photos): the fields of physical scoreboards and stadium video boards photographed by Wikimedia Commons contributors: ice hockey, basketball, American, Canadian and association football, cricket, volleyball, table tennis and a few others. Each field is its own crop, cut by a box drawn the way a ScoreSight user would draw it, and labelled with its role (`home_score`, `clock`, `shot_clock`, `period`, `home_fouls`, `down`, `overs`, ...) and a field type from its meaning: `score` for scores, `clock` for game, shot and penalty clocks with a separator, `period`, `number` for other counts (shot clocks in whole seconds, fouls, timeouts, downs, cricket totals), `text` for team names and words. Display technologies: 411 crops 7-segment LED, 304 dot matrix, 216 video boards, 54 bulb, 51 flip or hand-hung cards. Licenses are per photo (CC BY 2.0 to 4.0, CC BY-SA 2.0 to 4.0, CC0 and public domain; crops of CC BY-SA photos stay CC BY-SA), re-checked with the Commons API on every build, and `LICENSE` and `ATTRIBUTION.md` credit every photo. `PDM-1.0` stands for every public-domain photo, whatever the reason: some are their authors' PD-self dedications, some US government works. SPDX has no identifier for a PD-self dedication, the strict license check (`validate --strict-licenses`) accepts no `LicenseRef-` ids, and the Commons metadata the builder reads says only "Public domain" for both, so each photo's reason is on its file page (linked from `ATTRIBUTION.md`). `frames.jsonl` lists each photo with the URL of its 1280 px rendition and all its boxes, and `frames/` holds the photos downscaled to 576 px, for the review page and whole-frame experiments. `ocr_eval/builders/commons_scoreboards.py --cache FOLDER --discover` lists the candidates (2,901 files with a usable license in the scoreboard categories) and downloads their thumbnails for choosing; about 900 thumbnails of the sport categories were looked at, 235 photos picked, and 186 used (the 49 others are in the labels file with the reason). `--cache FOLDER --frames` rebuilds the dataset from `ocr_eval/builders/commons_scoreboards_labels.json`, fetching about 60 MB of renditions at most one request per second. Photos of the same board and game share a split (`group`). The labels were drawn and transcribed with a model's help (Claude): every field looked at zoomed in, fields that weren't clearly legible left out, and every crop checked on contact sheets. Only the crops the engines disagreed on were checked again: the 32 where three or more of the strongest engines agreed on a reading other than the label. One of those labels was still wrong (`cm1368756_away_score`, a 5×7 dot-matrix `19` labelled `18`, found by a methodology review and fixed in `commons_scoreboards_labels.json`, which keeps the old text as `corrected_from`); most of the others are engines reading unlit segments as lit (`1` as `18`), a neighbour's digit, or letters outside ASCII (`GÄSTE` as `GASTE`). No other label has been re-checked, and the labels stay `model-assisted-unverified` until a person checks them (see [Checking labels](#checking-labels)).

**`synthetic_7seg`** (56 crops): rendered 7-segment LED and LCD displays from `tests/synthetic_images.py`, CC0. A control, not a measure of real-world accuracy; `python -m ocr_eval.builders.synthetic_7seg` rebuilds it.

### Whole boards: Scoreboard Fields

[Scoreboard Fields](https://huggingface.co/datasets/royshilkrot/scoreboard-fields), on Hugging Face and not used by `ocr_eval`, is for finding the fields instead of reading them: 291 whole photos (232 from Wikimedia Commons, 59 from Open Images), with a box on every field, its role (`home`, `away`, `clock`, `period` or `other`) and each board's four corners, labelled by hand. It is for training models that suggest a board's boxes and its four-corner correction. It has train, validation and test splits, and the 186 photos of `commons_scoreboards` aren't in it. The labels are CC BY 4.0, and each photo keeps its own license, listed with it.

## Metrics

Both the prediction and the ground truth are normalized first: Unicode NFKC (full-width digits and colons become ASCII), every space removed, and `text`/`other` compared case-insensitively. Nothing else, and in particular **a clock's separator must match**: `12:34` (minutes:seconds) and `12.34` are different readings, ScoreSight's Time formats tell them apart, and an overlay showing the wrong one is wrong.

| Metric | Definition |
|---|---|
| Exact | The normalized prediction equals the normalized truth. The headline number |
| Digits | For numeric field types, the digits match with every other character removed (`12.34` matches `12:34`; `1O` doesn't match `10`). For `text`/`other`, the same as Exact |
| CER | Character error rate: total edit distance / total ground-truth characters |
| Empty | The engine returned nothing |
| Post-filter exact | Exact match of what ScoreSight would publish: the reading without characters outside the field type's whitelist, or nothing if it doesn't fully match the box's format regex. For Tesseract this is the pipeline's own verdict (its prediction records `info.state`: `Success`, `FailedFilter` or `Empty`); for other engines it shows what plugging them into ScoreSight's filters would give |
| Latency | Per crop, in ms, p50 / p95. *Single*: one crop per call. *Batch*: the call time divided by the crops in it, for engines that take batches |
| CPU time | Per crop, in ms (`latency.cpu_ms`): the process's CPU time (every thread) divided by the crops read, one at a time and batched. What a crop costs the machine, which wall time hides when an engine uses several cores. It comes from `time.process_time()`, which on Windows advances in 15.6 ms ticks: a run's total is known to a tick or two, about 0.05–0.1 ms per crop over 300 crops (a few percent of Tesseract's 2 ms, under 1% of PP-OCR `small`'s 17 ms) |

Accuracies come with a 95% Wilson score interval and CER with a 95% bootstrap interval (2,000 resamples, fixed seed), so small differences aren't over-read: on 1,276 crops an accuracy near 30% is known to about ±2.5 points. Every metric is also broken down by field type, display technology and split. `compare` pairs the two runs crop by crop and reports the crops lost and gained and an exact McNemar test.

Those intervals and McNemar's test treat every crop as independent, but a photo gives several crops (the 2,320 real crops come from 358 photos or groups of photos of one board), and crops of one photo tend to be read alike. `ocr_eval/metrics.py` therefore also has clustered statistics: `cluster_bootstrap_interval` (a percentile bootstrap that resamples whole photos, 2,000 resamples, fixed seed) and `cluster_sign_flip_p` (a paired test of two engines on the per-photo differences: each photo's difference keeps or flips its sign at random; exact up to 16 photos with a difference, else 20,000 random sign patterns, so p ≥ 5×10⁻⁵). The report's intervals and paired tests use them, and `python -m ocr_eval.pairwise` adds them when it finds the dataset. With one crop per photo they reduce to the crop bootstrap and McNemar's test.

## Engines

Every engine reads the raw crop and returns its own reading (and a confidence in [0, 1] when it has one); the harness applies ScoreSight's post-filter itself, for every engine alike.

| Engine | What | Variants | Size | License | Runs on |
|---|---|---|---|---|---|
| `tesseract` | ScoreSight's own pipeline (`src/tesseract.py`) with each bundled model | `<model>[-nobin]`, `tuned` | 3–23 MB per model | Apache-2.0 | everywhere |
| `ppocr` | PaddleOCR PP-OCRv6 and PP-OCRv5 recognizers on onnxruntime | `<model>[-bin][-wl]` | 4.5–85 MB | Apache-2.0 | Windows, Linux, macOS (onnxruntime) |
| `onnxtr` | docTR's PARSeq, ViTSTR, CRNN and VIPTR recognizers (OnnxTR) | `<model>[-int8][-bin][-wl]` | 6–97 MB | Apache-2.0 | Windows, Linux, macOS (onnxruntime) |
| `windows-ocr` | `Windows.Media.Ocr` through pywinrt | `raw`, `upscale`, `tile`, `[-digits]` | built in | Windows | Windows 10/11 |
| `apple-vision` | Apple's Vision and Live Text through ocrmac | `<level>-<preprocessing>[-digits]` | built in | macOS | macOS (not yet run) |
| `florence2`, `smolvlm`, `qwen-vl` | Small vision-language models on PyTorch | per model, `[-wl]` | 0.5–4 GB | MIT, Apache-2.0 | evaluation stopped |

Common variant suffixes: **`-wl`** limits decoding to the field type's character whitelist (the characters ScoreSight allows Tesseract, from `ocr_eval.fields.whitelist()`): on the real datasets it gains 1–3 points for PP-OCR and 9–14 for OnnxTR, and never lost more than 3 crops in a pair; **`-bin`** gives the engine ScoreSight's binarized patch (`preprocess_patch`) instead of the colour crop: 28–44 points worse on `textocr_scoreboards` for every neural engine, so a recognizer like these must read the raw crop.

### Tesseract (`tesseract`)

`ocr_eval/engines/tesseract_scoresight.py` drives ScoreSight's real `tesseract.TextDetector` with the box settings of each field type (above), so it measures exactly what the app does with default settings. Variants: the bundled model (`scoreboard_general`, the app's default; `scoreboard_general_large`, `daktronics`, `eng`) and `-nobin` (binarization off): ScoreSight's presets as they are, untuned (dilation is always on, as in the app, and nothing evens out light text on a dark board). The crop plays the role of the frame: ScoreSight's default global binarization is an Otsu threshold of the padded crop here, of the whole frame in the app.

`tuned` is Tesseract with settings chosen on the `dev` split of the two real datasets only: `ocr_eval/results/2026-10-11/tune_tesseract.py` runs the pipeline with every combination of model (`eng`, `scoreboard_general`), binarization (none or Otsu), dilation (0 or 1), polarity (as it is, or inverted to dark text on a light background when Otsu's bright side is the minority) and the crop's height (the app's 35 px rescale, or scaled to 16–80 px first) on the 410 `dev` crops, and its output, `tesseract_tuning.md` next to it, ranks them. The best, and `tuned`: the `eng` model, no binarization, no dilation, dark text on light, the crop scaled to 24 px high (heights from 20 to 35 px are within about 3 points of it), PSM 8 as always. The polarity and the height are applied before the pipeline (ScoreSight can invert a box's patch but doesn't choose that itself, and its rescale target is fixed at 35 px); everything else is a box setting the app has.

`ocr_eval/baselines/tesseract.json` (`textocr_scoreboards` and `synthetic_7seg`) and `tesseract-commons.json` (`commons_scoreboards`) hold every variant with every prediction, and are what CI compares with; their `.md` files are the reports. They were made on Linux (tesserocr 2.11.0 with Tesseract 5.5.1, as in CI); Windows (tesserocr 2.10.0, Tesseract 5.5.2) gave identical predictions on `textocr_scoreboards` and all but one (wrong on both) on `commons_scoreboards`.

| Variant | `textocr_scoreboards` exact % | `commons_scoreboards` exact % | `synthetic_7seg` % |
|---|---:|---:|---:|
| `tuned` (settings chosen on the dev split) | 52.2 (49.5–54.9) | 58.0 (54.9–60.9) | 33.9 |
| `eng-nobin` | 35.9 (33.3–38.6) | 52.8 (49.7–55.8) | 42.9 |
| `eng` | 30.1 (27.6–32.7) | 47.4 (44.4–50.4) | 39.3 |
| `scoreboard_general-nobin` | 18.6 (16.5–20.8) | 44.4 (41.5–47.5) | 35.7 |
| `scoreboard_general` (the app's default) | 17.6 (15.6–19.7) | 40.5 (37.6–43.5) | 58.9 |
| `scoreboard_general_large` | 14.9 (13.0–17.0) | 33.9 (31.1–36.8) | 41.1 |
| `scoreboard_general_large-nobin` | 14.8 (13.0–16.9) | 37.4 (34.5–40.3) | 37.5 |
| `daktronics` | 8.9 (7.4–10.5) | 20.2 (17.9–22.8) | 3.6 |
| `daktronics-nobin` | 7.6 (6.3–9.2) | 22.4 (20.0–25.0) | 8.9 |

(Wilson intervals, as in the baselines' reports: they treat the crops of a photo as independent.) With its default settings, ScoreSight's pipeline reads one real crop in six (TextOCR's word crops) to two in five (Commons' user-like boxes). Of the presets, the general English model without binarization does best on real crops; the scoreboard models never output a letter, so they read no words; turning binarization off helps every model; on 7-segment LED digits `scoreboard_general-nobin` is best (65% on Commons); and clocks are the weakest field (4–16% with the default). Part of the gap is the eval's single-crop, default-settings setup (users tune boxes, invert patches and pick a model per board): `tuned` shows what settings chosen on the dev split buy, about 11 points over `eng-nobin`, most of it from turning dilation off, and still far below PP-OCR. The Period format also rejects periods 0 and 5 (up to 0.4.2, the Time format also rejected soccer clocks past 59 minutes, `89:41` and `90:00`; up to 0.3.0, the Shot Clock format also rejected a shot clock shown as one digit).

### PaddleOCR (`ppocr`)

`ocr_eval/engines/ppocr.py` runs PaddleOCR's text recognition models with onnxruntime: PP-OCRv6 `v6-tiny` (1.1M parameters, 4.5 MB), `v6-small` (5.2M, 21 MB) and `v6-medium` (19M, 77 MB), and PP-OCRv5 `v5-mobile`, `v5-en-mobile` (English dictionary, 7.8 MB) and `v5-server`. The official ONNX exports (Apache-2.0) are downloaded from the Hugging Face Hub at revisions pinned in the module. Only the recognizer runs, since a box already is the text line, with the models' own preprocessing (48 px high, padded to at least 320 px); crops are batched by padded width, so a reading never depends on the rest of its batch. The adapter decodes the CTC output itself (greedy, like RapidOCR, whose texts it matches on every crop), which lets `-wl` limit it to the box's characters: at every step the blank competes only with the allowed characters, and dictionary characters that are the same under NFKC (full-width digits) count as one.

Variants are `<model>[-bin|-gray][-wl]`: `-gray` reads the crop in gray, as ScoreSight's capture thread converts the frame before OCR (`camera_thread.to_gray`). `--engine ppocr` runs every model but `v5-server` (about 0.6 s per crop even on all cores) on the colour crop, raw and `-wl`; `ppocr:*` runs all 36 variants. `OCR_EVAL_ORT_THREADS` sets onnxruntime's intra-op threads (default 1, like Tesseract; 0 = all cores) and `OCR_EVAL_ORT_SPINNING=0` lets idle pool threads sleep instead of spinning; predictions are the same either way.

```bash
.venv-eval/Scripts/python.exe -m ocr_eval run --dataset textocr_scoreboards --dataset commons_scoreboards \
    --dataset synthetic_7seg --engine ppocr:v6-tiny-wl,v6-small-wl,v6-medium-wl --out results/ppocr
```

Results: the [report](https://github.com/royshil/scoresight/blob/main/ocr_eval/results/2026-10-11/REPORT.md) (all three datasets), `ocr_eval/baselines/ppocr-ci.json` (the variants CI checks) and `ocr_eval/baselines/ppocr.json.gz` with `ppocr.md` (every variant, including `-bin` and PP-OCRv5, on `textocr_scoreboards` and `synthetic_7seg`). PaddleOCR doesn't publish its training data, and the model card names "digital displays" and "dot-matrix characters" among its scenarios. TextOCR is part of the standard real-data training mixes for text recognizers, so the models may have been trained on `textocr_scoreboards`' very words (that its train and val photos read alike proves nothing); the check is `commons_scoreboards`, whose photos aren't in those mixes and whose boxes and labels were made for this evaluation (`v6-small-wl` 94.8%, as on TextOCR), with `synthetic_7seg` (100% for every PP-OCRv6 `-wl` model) and new footage (Training Dojo data).

### The app's PP-OCR engine (`ppocr-app`)

`ocr_eval/engines/ppocr_scoresight.py` measures the app itself: ScoreSight's PP-OCR engine (`src/ppocr_engine.py`) through its pipeline (`tesseract.TextDetector`), as `tesseract` does for Tesseract. A batch of up to 16 crops is laid out side by side in one colour frame and read as that frame's boxes with one `detect_multi_text` call, so the app's batching (one onnxruntime run per padded width) is measured too. Each box has its field type's (or role's) settings, which for PP-OCR decide only its character whitelist and its format. Variants: `accurate` (PP-OCRv6 small) and `fast` (tiny), the app's "PP-OCR (accurate)" and "PP-OCR (fast)" ("PP-OCR (automatic)" picks one of them from the computer's speed, so it isn't a variant). The models are the app's: `python scripts/fetch_models.py` downloads them into `ocr_models/ppocr/` at the same pinned revisions as `ppocr`'s `v6-small` and `v6-tiny`; the engine needs nothing beyond the app's `requirements.txt`.

Its predictions equal `ppocr:v6-small-wl`'s and `ppocr:v6-tiny-wl`'s on every crop of the three datasets, texts and confidences, on Linux and Windows and with onnxruntime 1.31.0 and 1.23.2 (the macOS x86_64 pin): 94.7% and 90.8% on `textocr_scoreboards`, 94.8% and 88.1% on `commons_scoreboards`, 100% on `synthetic_7seg`. `ocr_eval/baselines/ppocr-app-ci.json` (made on Linux) is CI's baseline for it, and `tests/test_ocr_eval_ppocr_scoresight.py` checks that it has `ppocr-ci.json`'s predictions crop for crop, and (with the models) that the app reads a sample of crops exactly as `ppocr-ci.json` says.

```bash
python -m ocr_eval run --dataset textocr_scoreboards --dataset commons_scoreboards     --dataset synthetic_7seg --engine ppocr-app --out results/ppocr-app
```

### OnnxTR (`onnxtr`)

`ocr_eval/engines/onnxtr.py` runs docTR's word recognizers through [OnnxTR](https://github.com/felixdittrich92/OnnxTR) (its ONNX exports, Apache-2.0): `parseq` (23.8M parameters, 97 MB), `vitstr_small` (21.4M, 86 MB), `crnn_mobilenet_v3_small` (2.1M, 8 MB) and `viptr_tiny` (3.3M, 20 MB), and OnnxTR's 8-bit exports `parseq-int8`, `vitstr_small-int8` (dynamic quantization) and `crnn_mobilenet_v3_small-int8` (static). Models are downloaded from OnnxTR's GitHub releases into `~/.cache/onnxtr` (`$ONNXTR_CACHE_DIR`). Without `-wl` the adapter gives exactly what OnnxTR's `RecognitionPredictor` gives; `-wl` restricts the CTC models and ViTSTR exactly, but PARSeq decodes autoregressively inside its graph, so for it only each position's final choice is restricted. `OCR_EVAL_ONNX_THREADS` sets onnxruntime's threads (default 0 = all cores). Windows and Linux gave identical predictions.

`--engine onnxtr` runs the fp32 models with every suffix. Best: `parseq-wl` 85.5% on both real datasets, `crnn_mobilenet_v3_small-wl` 78.1% (as cheap as Tesseract). Avoid `crnn_mobilenet_v3_small-int8` (17 points worse) and `viptr_tiny` (25–47 s to load). Results: the report, and `ocr_eval/baselines/onnxtr.json.gz` with `onnxtr.md` (every variant on `textocr_scoreboards` and `synthetic_7seg`).

### Operating-system OCR (`windows-ocr`, `apple-vision`)

`windows-ocr` (`Windows.Media.Ocr`, built into Windows 10 and 11) and `apple-vision` (Apple's Vision framework and Live Text, through [ocrmac](https://github.com/straussmaximilian/ocrmac)) read crops with the OCR that comes with the operating system: nothing to download or bundle, but each runs on one platform only, and both are document OCR, with a text detector, a language model, and no character whitelist or single-word mode. Their adapters share `ocr_eval/engines/_os_ocr.py`, and their variants combine one preprocessing with an optional `-digits` suffix:

| Variant part | What the engine is given |
|---|---|
| `raw` | The crop as it is |
| `upscale` | A crop shorter than 64 px scaled up to 64 px (bicubic), with a margin of half its height on every side in the crop's border colour: the detectors miss small text and text that touches the image edge |
| `tile` | `upscale`, then three copies of the crop side by side, half a height apart. Words are assigned to the copy under them (a word spanning several copies that reads as equal parts, like `333`, is split) and the copies' readings are majority-voted. Windows OCR never returns a lone character, and half of the real crops are one digit |
| `-digits` | For numeric field types, letters these engines read for digits are mapped to them (`O`→`0`, `l`→`1`, `S`→`5`, `B`→`8`, ...) before voting: the stand-in for Tesseract's digit whitelist |

`apple-vision` variants also name a recognition level: `accurate-...`, `fast-...` or `livetext-...` (macOS 14 or later), for example `accurate-tile-digits`. The geometry (64 px, half-height margins and gaps, three copies) was chosen on the `dev` split with Windows OCR; values around it gave the same accuracy within about a point.

**Windows.** `requirements-eval.txt` installs the `winrt-*` packages; check that `python -m ocr_eval list` shows `windows-ocr` as available. It also needs the OCR language pack for English (United States), which comes with that Windows language; if it is missing, `list` says so, and an administrator PowerShell installs it with `Add-WindowsCapability -Online -Name "Language.OCR~~~en-US~0.0.1.0"`. The adapter keeps one `OcrEngine` (winocr's helpers create one per call, which costs about 2.5 ms per crop). pywinrt ships an old `msvcp140.dll` that crashes Tesseract if it is loaded first, so the adapter loads the system's copy before importing pywinrt, and `--engine windows-ocr --engine tesseract` can share a run.

**macOS.** `apple-vision` needs `ocrmac==1.0.1` and `pyobjc-framework-Vision==12.2.2` (in `requirements-eval.txt`). It hasn't been run on a Mac yet: it was written against ocrmac's API and tested with ocrmac faked, and its results record `"verified": false`. Run `python -m ocr_eval run --dataset textocr_scoreboards --dataset commons_scoreboards --dataset synthetic_7seg --engine apple-vision --out results/apple-vision` on a Mac to measure it (and to verify it: no run should end in `error`).

**Results.** As it is (`raw`), Windows OCR is unusable on scoreboard crops: it returns nothing for 91% of them and reads no single characters. With upscaling, tiling and the digit mapping (`tile-digits`, each step significant) it reads 24.3% of the real crops: better than the app's default Tesseract setup on `textocr_scoreboards`, worse on `commons_scoreboards`, and far behind PP-OCR. It reads multi-character values (clocks, words, numbers of three or more digits) better than any Tesseract variant, but 7-segment and LCD digits poorly (14% and 4% on TextOCR). Being Windows-only, it can't be ScoreSight's cross-platform engine. `ocr_eval/baselines/windows-ocr.json.gz` and `windows-ocr.md` hold every variant on `textocr_scoreboards` and `synthetic_7seg` (Windows 11 build 26200); CI doesn't run them (it runs on Linux).

### Vision-language models

**The VLM evaluation was stopped before it was finished, and VLMs are not candidates for ScoreSight's per-frame loop.** They read real scoreboards well (Qwen3.5-0.8B 91.5%, Qwen3-VL-2B 93.5% on `textocr_scoreboards`), and the best is statistically tied with PP-OCR `small`; the verdict rests on cost, not accuracy. On a CPU they took 0.4–0.9 s per crop, 100–400 times Tesseract's cost and far beyond a budget of tens of crops per second, and they need PyTorch and a 0.5–4 GB model. That was fp32 eager PyTorch, without int8, llama.cpp or OpenVINO, so it likely overstates their cost several times; but even 10 times faster, ScoreSight's default 50 crops a second would need 2 to 4.5 seconds of that per second. PP-OCR's recognizers read as well at a few milliseconds per crop. What was measured is below, as a reference; the runs it lists are the finished ones, and the variants whose runs weren't finished or were invalidated by a bug are left out.

`ocr_eval/engines/vlm.py` runs small vision-language models (VLMs) on the CPU with PyTorch and Hugging Face transformers. Their pins are commented out in `requirements-eval.txt`; install them in their own environment (on Linux, install PyTorch's CPU wheels first: PyPI's Linux wheels bundle CUDA, about 3 GB):

```bash
uv venv --python 3.13 .venv-vlm
# Linux only, first:
uv pip install --python .venv-vlm/bin/python --index-url https://download.pytorch.org/whl/cpu torch==2.14.1 torchvision==0.29.1
uv pip install --python .venv-vlm/Scripts/python.exe -r requirements.txt -r requirements-win.txt $(python -m ocr_eval requirements qwen-vl)
.venv-vlm/Scripts/python.exe -m ocr_eval run --dataset textocr_scoreboards --engine qwen-vl --sample 200 --out results/qwen
```

| Engine | Variants: model | Parameters (download) | License |
|---|---|---|---|
| `florence2` | `florence2-base`, `florence2-large`: Florence-2 with its `<OCR>` task | 0.23B (0.44 GB), 0.77B (1.5 GB) | MIT |
| `smolvlm` | `smolvlm-256m`, `smolvlm-500m`: SmolVLM-Instruct, the cheap control | 0.26B (0.49 GB), 0.51B (0.97 GB) | Apache-2.0 |
| `qwen-vl` | `qwen3.5-0.8b`: Qwen3.5-0.8B; `qwen3-vl-2b`: Qwen3-VL-2B-Instruct (non-thinking) | 0.9B (1.7 GB), 2.1B (4.1 GB) | Apache-2.0 |

- Every model is pinned to a Hugging Face revision and downloaded into the Hugging Face cache on first use.
- The chat models get one prompt per crop that says what the box holds (ScoreSight knows each box's field type), e.g. *"This image is cropped from a scoreboard. Read the game clock (digits with ':' or '.') shown in it. Answer with only the characters on the display, exactly as shown."* Florence-2 takes no prompt: it runs its `<OCR>` task on the crop centred on a square (variant suffix `-sq`: stretched to its square input instead).
- Decoding is greedy (temperature 0, no repetition penalty), at most 16 tokens. The answer is cleaned up mechanically only (its first line, without quotes and a trailing period); the raw answer is kept in the prediction's `info` when that changed it. The confidence is the probability of the generated sequence.
- Variant suffix `-wl`: decoding may only use tokens made of the field type's characters, the VLM counterpart of masking a CTC decoder.
- The chat models read 8 crops per call (left-padded batches gave the same answers as one crop at a time); latency is reported for both. `OCR_EVAL_VLM_BATCH`, `OCR_EVAL_TORCH_THREADS` and `OCR_EVAL_TORCH_DEVICE` (`cpu`, `cuda`, `mps`) change that.

**Results on CPU.** Measured on Windows 11 with an Intel Core i9-14900K (24 cores, 32 threads; PyTorch's 24 threads, fp32), torch 2.14.1 and transformers 5.18.0; no GPU. Every prediction is in `ocr_eval/baselines/vlm/`: `crops.json.gz` (the variants run on every crop), `sample400.json.gz` (those run on a stratified sample of 400 `textocr_scoreboards` crops, and every `synthetic_7seg` crop), `latency.json.gz`, and `frames219.json.gz` and `frames100.json.gz` (whole frames, below), each with its `.md` report. They are reference results, not checked by CI.

`textocr_scoreboards`, exact match (95% CI) by field type:

| Engine:variant | Crops | Exact % | Clock % | Number % | Text % | CER % | Post-filter % |
|---|---:|---:|---:|---:|---:|---:|---:|
| `qwen-vl:qwen3-vl-2b` | 1276 | 93.0 (91.5–94.3) | 92.8 | 92.3 | 96.8 | 5.2 | 92.6 |
| `qwen-vl:qwen3-vl-2b-wl` | 1276 | 93.5 (92.0–94.7) | 92.8 | 92.9 | 96.8 | 4.9 | 92.9 |
| `qwen-vl:qwen3.5-0.8b` | 1276 | 91.3 (89.6–92.7) | 88.5 | 91.0 | 95.1 | 5.8 | 90.8 |
| `qwen-vl:qwen3.5-0.8b-wl` | 1276 | 91.5 (89.9–92.9) | 88.5 | 91.4 | 95.1 | 5.6 | 91.1 |
| `smolvlm:smolvlm-256m` | 1276 | 67.8 (65.2–70.3) | 46.8 | 68.6 | 80.5 | 58.1 | 68.1 |
| `smolvlm:smolvlm-256m-wl` | 1276 | 68.6 (66.0–71.1) | 54.7 | 68.5 | 80.5 | 25.0 | 68.3 |
| `smolvlm:smolvlm-500m` | 400 | 66.2 (61.5–70.7) | 29.5 | 69.7 | 77.6 | 48.0 | 66.2 |
| `florence2:florence2-base-wl` | 400 | 64.2 (59.4–68.8) | 40.9 | 64.6 | 81.0 | 25.0 | 64.2 |
| `florence2:florence2-base` | 400 | 56.5 (51.6–61.3) | 36.4 | 54.9 | 81.0 | 30.3 | 56.5 |
| `florence2:florence2-base-sq` | 400 | 47.8 (42.9–52.6) | 18.2 | 47.5 | 72.4 | 40.2 | 48.0 |
| `ppocr:v6-small-wl` (for comparison) | 1276 | 94.7 (93.4–95.8) | 84.2 | 96.1 | 96.8 | 3.0 | 94.4 |
| `tesseract:eng-nobin` (baseline) | 1276 | 35.9 (33.3–38.6) | 12.2 | 40.6 | 30.3 | 55.6 | 35.9 |

The 400-crop sample is `run --sample 400` (seed 0: 297 numbers, 58 texts, 44 clocks, 1 other); on those crops Tesseract `eng-nobin` reads 37.0% (32.4–41.8), Qwen3.5-0.8B 90.2% and Qwen3-VL-2B 91.5%, within about a point of their full-set numbers, so the sample's rows compare with the others. On `synthetic_7seg` (56 crops): Qwen3.5-0.8B 98.2%, Qwen3-VL-2B 94.6%, SmolVLM-500M 69.6%, Florence-2-base-wl 57.1%, SmolVLM-256M 51.8%.

Not in the table: `florence2-large` was never run, and the 400-crop runs of `florence2-large-wl` (45.3%) and `smolvlm-500m-wl` (62.5%) are left out because they ran before the fix of the `-wl` decoding (commit "a masked period or newline ends a constrained answer"): most of their errors are the run-on answers that fix is about (`90 1 1 1 0 1 1 2 …` for `90`). The `florence2-base-wl` run predates that fix too, but only 1 of its 143 errors is such an answer, so it is kept.

Latency per crop, on a stratified sample of 100 crops with the machine otherwise idle (`latency.json.gz`; one crop per call, and in calls of 8 crops for the chat models): SmolVLM-256M 382 ms (335 in batches), Qwen3.5-0.8B 710 ms (413), its `-wl` 622 ms (390), Florence-2-base-wl 663 ms, Qwen3-VL-2B 898 ms (704), against about 2 ms for Tesseract; loading takes 1–5 s from the cache. Qwen3.5's linear-attention layers run PyTorch's reference implementation on a CPU (the fast kernels need CUDA), so it may get faster on a GPU. Their confidence is useful (Qwen3.5-0.8B's answers with confidence ≥ 0.7 cover 68% of the crops at 99.2% accuracy), `-wl` makes no difference to the Qwen models and helps Florence-2 (+7.7 points), and Florence-2 needs its crop letterboxed (stretched, it loses 8.8 points). Head to head on the same 1,276 crops, PP-OCR `v6-small-wl` reads 77 crops Qwen3.5-0.8B-wl misses and misses 36 it reads (McNemar p = 1.4×10⁻⁴, 0.007 with photos resampled), and against Qwen3-VL-2B-wl it is a tie: 63 crops against 47 (p = 0.15, 0.20 with photos); `v6-medium-wl` beats both.

**Whole frames.** A VLM can also look at the whole frame once and read every box in one call. `python -m ocr_eval.frames` groups a dataset's crops by the frame they were cut from (the row's `frame` or `source_image` key), finds the frame's image (the row's `frame_image`, a path in the dataset folder, or `--frames-dir FOLDER/<id>.jpg`), gives the engine the frame and every box (the crop's `source_box`, plus the row's `role`, e.g. "home score", when the dataset has one) and scores each box's reading like a crop's:

```bash
python -m ocr_eval.frames --dataset textocr_scoreboards --frames-dir CACHE/images \
    --engine qwen-vl:qwen3.5-0.8b --mode boxes,marks --out results/frames [--frames 50]
python -m ocr_eval.pairwise results/qwen/results.json results/frames/results.json
```

Modes: `qwen-vl` `boxes` lists the boxes' coordinates (0–1000 scale) in the prompt, `marks` draws numbered boxes on the frame; both ask for a JSON object of the boxes' texts. `florence2` `spot` runs `<OCR_WITH_REGION>` on the frame and gives each box the words centred in it. An engine reads frames if it has `frame_modes` and `read_frame(frame, fields, mode)`. On `textocr_scoreboards`'s photos, reading the whole frame was much worse than reading crops (Qwen3-VL-2B 39.6% of 563 boxes against 90.8% as crops; Qwen3.5-0.8B 31.5% of all 1,276 boxes) and not faster per box (1–1.8 s per box): the models misplace boxes, and a 15–30 px digit in a 1,000 px photo is a much smaller target than in its crop. Prompting by role on `commons_scoreboards` (which has frames and roles) is implemented but not measured.

## Results files and where they live

`results.json` (schema `scoresight-ocr-eval/1`) holds the environment, the datasets (with the hash of each manifest, and a `subset` when the run didn't read every crop: `splits`, `sample` with its `seed`, `limit`, or the `frames` of a whole-frame run) and one record per dataset and engine variant: `status` (`ok`, `skipped` or `error`, with a `reason`), `engine_info`, `load_seconds`, `latency` (`single`, `batch`, `batch_size`, `total_seconds`, `cpu_ms`), `scores.raw` and `scores.postfilter` (the metrics above, each with `value`, `k`, `n` and `ci95`, plus `by_field_type`, `by_display_tech` and `by_split`), and `predictions`: one line per crop with `id`, `truth`, `text`, `conf`, `ms`, `exact`, `pf_exact`, and `pf_text` and `info` when present. A whole-frame run (`ocr_eval.frames`) has the key `<engine>:<variant>@frames-<mode>`, `latency.frame` (per frame), `frames` and the frame's key in each prediction. `HARNESS_VERSION` in `ocr_eval/__init__.py` changes when a metric's definition does.

Every command reads results gzipped too (`.json.gz`, recognized by content), and writing to a path ending in `.gz` compresses reproducibly. In the repository:

| Path | What | Format |
|---|---|---|
| `ocr_eval/baselines/tesseract.json`, `tesseract-commons.json`, `ppocr-ci.json`, `ppocr-app-ci.json` | The baselines CI compares with (made on Linux) | Plain JSON, so that a pull request that updates one shows which crops changed |
| `ocr_eval/baselines/ppocr`, `onnxtr`, `windows-ocr`, `vlm/*` | Reference runs of every variant of an engine (Windows), CI doesn't compare them | `.json.gz`, with a `.md` report |
| `ocr_eval/results/2026-10-11/` | The evaluation report: `REPORT.md`, `results.json.gz` (every non-VLM engine on the three datasets), `latency.json.gz` (the timing runs), `pinned.json.gz` (a timing spot check pinned to one performance or efficiency core), `gray.json.gz` (PP-OCR on gray crops), `startup.json`, `results.md` (the harness's report of the accuracy run), `tune_tesseract.py` and its output `tesseract_tuning.md` (the choice of `tesseract:tuned`'s settings), and `tables.py`, which recomputes the report's tables from them | `.json.gz` |

Every prediction in these files carries its crop's ground truth (`truth`): for `textocr_scoreboards` that is TextOCR's transcription (Singh et al., 2021, CC BY 4.0), credited with the photos in `ocr_eval/datasets/textocr_scoreboards/ATTRIBUTION.md`; for `commons_scoreboards`, see its `ATTRIBUTION.md`.

## Continuous integration

`.github/workflows/ocr-eval.yml` runs on pull requests and pushes to `main` that change recognition (`src/tesseract.py`, `src/ppocr_engine.py`, `src/defaults.py`, `src/text_detection_target.py`, `tesseract/`, `scripts/fetch_models.py`, `ocr_eval/`, `requirements.txt`, `requirements-eval.txt`, the workflow) and manually, on Ubuntu 24.04, in three jobs:

- **Tesseract vs. baseline** validates the datasets (`--strict-licenses`), runs every Tesseract variant on the three datasets, and compares with `ocr_eval/baselines/tesseract.json` and, in a second step, `tesseract-commons.json`.
- **PP-OCR vs. baseline** installs `python -m ocr_eval requirements ppocr`, runs `ppocr:v6-small-wl,v6-tiny-wl` on the three datasets and compares with `ocr_eval/baselines/ppocr-ci.json`. The models are downloaded by `python -m ocr_eval.fetch_models` and cached (`actions/cache`, keyed by the pinned revisions that `fetch_models --pins` lists, with older caches as restore keys). It retries network errors (connection errors, timeouts, HTTP 429 and 5xx) and fails at once on a revision or file that doesn't exist, a renamed, removed or gated repository, or an import error. Only on a pull request, and only when the Hub is still unreachable after the retries (exit status 75), is the comparison skipped with a warning; on pushes to `main` and manual runs that fails the job too.
- **PP-OCR in the app vs. baseline** installs `requirements-dev.txt`, restores the app's models from `actions/cache` (keyed by `scripts/fetch_models.py`, which pins them) and runs `python scripts/fetch_models.py`, which checks every file's SHA-256 and fails after its retries; then runs `ppocr-app` on the three datasets and compares with `ocr_eval/baselines/ppocr-app-ci.json`.

```bash
python -m ocr_eval compare ocr_eval/baselines/tesseract.json ocr-eval-results/results.json \
    --max-drop 0.02 --require-all
```

A comparison fails when a variant's exact-match accuracy (raw or post-filter) drops by more than 2 points on a dataset, or a variant didn't run. Add `--alpha 0.05` to also require the drop to be significant (McNemar). The comparisons and the reports go to the job summary, and the results are uploaded as artifacts (`ocr-eval-results`, `ocr-eval-ppocr`, `ocr-eval-ppocr-app`).

When a change improves recognition, or changes a dataset, update the baselines in the same pull request: run the command the workflow runs, on Linux (or check that your platform gives the same predictions: Windows did for Tesseract, OnnxTR and PP-OCR), and copy `results.json` and `report.md` over the baseline and its `.md`: `tesseract.json`/`.md` for the run on `textocr_scoreboards` and `synthetic_7seg`, `tesseract-commons.json`/`.md` for `commons_scoreboards` alone, `ppocr-ci.json`/`.md` for the PP-OCR run on all three, and `ppocr-app-ci.json`/`.md` for the `ppocr-app` run on all three (it must keep `ppocr-ci.json`'s predictions). A changed dataset is flagged by `compare` (the manifest hash differs), which then compares the crops both runs have.

## Adding an engine

Engines are found automatically: every module in `ocr_eval/engines/` whose name doesn't start with `_` is imported, and every `Engine` subclass with a `name` defined in it is registered. There is no registry to edit, so adapters can be added in parallel.

```python
# ocr_eval/engines/my_engine.py
from ocr_eval.engines import Engine, EngineUnavailable, Recognition

# pip requirements beyond ScoreSight's requirements.txt (shown by
# `python -m ocr_eval requirements my-engine` and in unavailable reasons;
# also add them to requirements-eval.txt)
REQUIREMENTS = ["some-ocr-package==1.2.3", "onnxruntime==1.31.0"]


class MyEngine(Engine):
    name = "my-engine"                  # [a-z0-9_-]+, unique
    variants = ("small", "large")       # e.g. models or preprocessing options
    default_variants = ("small",)       # run by `--engine my-engine`; None = all
    description = "What it is"
    size = "5.3M parameters, 21 MB"     # for the report; info() can refine per variant
    license = "Apache-2.0"
    runtime = "onnxruntime, CPU"
    imports = ("some_ocr_package", "onnxruntime")  # checked by unavailable_reason()
    batch_size = 16                     # the most crops recognize() gets per call

    @classmethod
    def unavailable_reason(cls):       # optional: OS checks, model files ...
        return super().unavailable_reason()

    def load(self):                    # timed separately; import heavy deps here
        import some_ocr_package
        try:
            self.model = some_ocr_package.load(self.variant)
        except FileNotFoundError as e:
            raise EngineUnavailable(f"model not downloaded: {e}")

    def recognize(self, crops, field_types):
        # crops: read-only uint8 BGR arrays (H, W, 3); field_types: e.g. "clock"
        texts, scores = self.model.read(crops)
        return [Recognition(t, s) for t, s in zip(texts, scores)]

    def close(self):
        self.model = None
```

Rules:

- Don't import optional dependencies at module level: discovery must work without them. An engine that can't run is listed as unavailable with the reason and is reported as skipped, not as an error.
- `recognize()` returns one `Recognition(text, confidence, info)` (or a `(text, confidence)` tuple) per crop, in order. `confidence` is in [0, 1] or `None`; `info` is a small JSON-serializable dict kept with the prediction (e.g. a VLM's raw answer).
- Return what the engine read. Don't apply ScoreSight's filters yourself: the post-filter scoring does that for every engine. Engine-specific output cleanup (e.g. masking a CTC decoder to the field type's whitelist from `ocr_eval.fields.whitelist()`) is fair, and makes a good variant.
- Pin the extras in `REQUIREMENTS` and in `requirements-eval.txt` (`tests/test_ocr_eval_requirements.py` checks that they match, and that one version of each package installs on every platform), and install them in the evaluation environment, never in the app's.
- Add fast tests in `tests/test_ocr_eval_<engine>.py` that skip when the engine's dependencies are missing (`pytest.importorskip`).
- Model downloads go to the library's default cache (e.g. the Hugging Face cache) at a pinned revision; never commit weights.

## Contributing data

The more real crops, the narrower the intervals. Only data whose license allows redistribution is committed: CC0, CC BY, CC BY-SA or the public domain mark, with attribution (`validate --strict-licenses`, run by the tests and CI, enforces the license ids). Never commit frames of TV or streamed broadcasts (copyrighted), stock photos, or data under non-commercial or "no redistribution" terms (SoccerNet, SVHN, Roboflow's sets without the author's permission); keep those in a private dataset folder listed in `$OCR_EVAL_DATASETS`.

**From the Training Dojo.** ScoreSight's "Save OCR training data" writes each reading as `<id>.png` (binarized), `<id>_gray.png` (the raw crop) and `<id>.txt`; the Training Dojo corrects and approves the texts (`approved_annotations.json`). Turn a reviewed folder into a dataset:

```bash
python -m ocr_eval import-dojo "path/to/ocr_training_data" --out ocr_eval/datasets/my_dojo \
    --author "Your Name" --license CC0-1.0 --display-tech led7 [--field-type clock]
```

Only approved samples are imported (`label_source: human`; `--include-unapproved` adds the rest as `model-assisted-unverified`), always with the raw gray crop. The field type is guessed from the text unless given; running it again adds only new samples. Contributions need the contributor to grant CC0-1.0 or CC-BY-4.0 and to own the footage (your own camera at your own venue, not a broadcast).

**From other sources.** Write a builder in `ocr_eval/builders/` that downloads, selects and crops reproducibly (see `textocr_scoreboards.py`, or `commons_scoreboards.py` for photos labelled by hand), records every photo's license and author, and keeps decisions made by hand in a review or labels file next to it. Keep crops small (the committed sets downscale to at most 160 px tall) and the total for a dataset under about 25 MB: every contributor clones it. A large set belongs on a dataset host, with a small subset here.

### Checking labels

Labels that a model helped make (`label_source: model-assisted-unverified`) should be checked by a person. `python -m ocr_eval review DATASET [--out FILE] [--results RESULTS.json [--run engine:variant,...]]` writes one self-contained HTML page (the images are embedded) with every crop, its text, field type, display technology and role, grouped by source photo with its link, author and license; for datasets with `frames.jsonl`, each photo can be opened with all its boxes drawn. With `--results`, each crop also shows what each engine read, and "only crops no engine read" filters to the likeliest label errors. Mark each crop **OK**, **Fix** (type the correct text) or **Drop** (with a reason); "Mark shown as OK" marks every shown crop without a decision. Decisions are kept in the browser, and **Export decisions** saves them as a JSON file (`scoresight-ocr-eval-review/1`: the dataset, its manifest hash, the reviewer and `decisions` by crop id), which **Import** loads again. For `commons_scoreboards`, `python -m ocr_eval.builders.commons_scoreboards --apply-review FILE` applies an export to the labels file (checked fields become `human`, fixed texts keep the old one as `corrected_from`, dropped fields move to `rejected_fields`); rebuild with `--cache FOLDER --frames` and regenerate its baselines afterwards. For other datasets, carry the decisions into their review file (the crop ids of `textocr_scoreboards` are the TextOCR word ids that `textocr_scoreboards_review.json` uses).
