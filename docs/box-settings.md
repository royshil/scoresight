---
title: Per-Box Settings
parent: Reference
nav_order: 1
description: "Reference for every per-box recognition setting in ScoreSight: UI label, JSON key, range, default, effect and when to use it."
---

# Per-Box Settings Reference
{: .no_toc }

Each box has its own settings. Select its field in the field list (or its box on the picture), and the **Box** tab of the inspector, on the right of the window, shows them under the field's name, in three sections:

- **Reading**: what the box contains (**Type**, **Format**) and how the value is written.
- **Filtering**: which readings are accepted.
- **Image cleanup**: how the box's picture is prepared for a Tesseract model. It is collapsed until you open it (ScoreSight remembers whether it's open), and its header says how many of its settings you changed (*all default*, *2 changed*...) and has a **Binary view** button that shows the result. While a [PP-OCR model](ocr-models.md) reads the boxes, its settings are disabled (and kept) with the note *Image cleanup is for the Tesseract models; PP-OCR reads the picture as it is*: PP-OCR reads each box's picture untouched, which works much better for it. They stay available for a box that counts lights.

**Reset to defaults** puts every setting of the field back to its default. Every slider shows its value next to it (*Off* when the setting is off), and every setting has a tooltip, which also gives its name in ScoreSight 0.1.x. Settings are saved with your layout and included in **File > Export field layout...**. In exported files and `scoresight.json`, they appear under each box's `settings` object, using the JSON keys listed here.

A few settings apply to every box at once. They are in **All boxes**, at the bottom of the Box tab, always available: the [OCR model](ocr-models.md), **Detections / s** (see [Performance](performance.md)) and [Update on change](outputs.md#which-readings-are-sent).

For a task-oriented guide, see [Recognition Tuning](recognition-tuning.md).

<details open markdown="block">
  <summary>On this page</summary>
  {: .text-delta }
1. TOC
{:toc}
</details>

## Summary

| UI label (0.1.x label) | JSON key | Values | Default |
|---|---|---|---|
| **Reading** | | | |
| [Type](#type) | `type` | `0` Number, `1` Time, `2` Text | Time box: Time. Others: Number |
| [Format](#format) (Select Preset) | `format_regex` | regular expression | depends on the field (see below) |
| [Remove leading zeros](#remove-leading-0s) (Remove leading 0s) | `remove_leading_zeros` | on/off | off |
| [Add ordinal suffix](#ordinal) (Ordinal) | `ordinal_indicator` | on/off | Period: on. Others: off |
| [Count lights](#dot-counter) (Dot Counter) | `dot_detector` | on/off | off |
| **Filtering** | | | |
| [Minimum confidence](#conf-th-confidence-threshold) (Conf. Th) | `conf_thresh` | 0.00–0.99 (slider 0–99 = the OCR model's confidence in %) | 0 (off) |
| [Smooth over last 5 readings](#average-output) (Average Output) | `smoothing` | on/off | off |
| [Skip OCR while image is unchanged](#skip-similar-image) (Skip Similar Image) | `skip_similar_image` | on/off | off |
| [When blank](#when-blank) | `clear_value` | `never` Keep the last value, `blank` Clear the value, `blank_or_zero` Clear the value, also at zero | `never` |
| **Image cleanup** (Tesseract models and the dot counter) | | | |
| [Black & white](#binarize) (Binarize) | `binarization_method` | `0` Whole picture, `1` None, `2` This box, `3` Adaptive | `0` Whole picture |
| [Remove specks](#cleanup) (Cleanup) | `cleanup_thresh` | 0.00–0.99 (slider 0–99) | 0 (off) |
| [Squash height](#vscale) (V.Scale) | `vscale` | 1–10 | 10 (no scaling) |
| [Straighten slant](#skew) (Skew) | `skew` | −10 to 10 | 0 |
| [Thicken strokes](#dilate) (Dilate) | `dilate` | 0–5 | 1 |
| [Invert colours](#invert-input) (Invert Input) | `invert_patch` | on/off | off |
| [Crop to text](#auto-crop) (Auto Crop) | `autocrop` | on/off | off |
| [Resize to 35 px](#rescale-input) (Rescale Input) | `rescale_patch` | on/off | on |
| [Normalize digit width](#normalize-w-h-ratio) (Normalize W-H Ratio) | `normalize_wh_ratio` | on/off | off |
| [Per-character sub-boxes](#composite-per-character) (Composite) | `composite_box` | on/off | off |
| **Template** | | | |
| [Build from other fields](#template-field) (Template Field) | `templatefield`, `templatefield_text` | on/off, text | off, empty |
| (not shown) | `is_custom` | true/false | true for fields you added with **+** |
| OBS page: **Text sources** | `obs_source_name` | text | see [OBS source name](#obs-source-name) |

## Processing order

With a **Tesseract** model, for each box, on every detection cycle, ScoreSight:

1. takes the part of the box that is inside the processed picture (a box that reaches past the edge is read from its visible part; its saved position isn't changed),
2. turns it into **black and white** (*Black & white*),
3. removes small specks (*Remove specks*),
4. squashes it vertically (*Squash height*) and shears it (*Straighten slant*),
5. thickens strokes (*Thicken strokes*),
6. inverts it (*Invert colours*),
7. reports the box as `Empty` without running OCR if the image is blank (every pixel the same, for example a box over plain background); a *Count lights* box reports `0` instead,
8. skips OCR if the image hasn't changed (*Skip OCR while image is unchanged*),
9. crops to the text (*Crop to text*),
10. scales it (*Resize to 35 px*, *Normalize digit width*),
11. counts lights (*Count lights*) **or** runs OCR with the character set of the *Type*,
12. checks the raw text against the *Format* and the *Minimum confidence*,
13. applies *Smooth over last 5 readings* (to accepted readings only), *Remove leading zeros* and *Add ordinal suffix*,
14. marks the reading `Empty` if no text is left, or `SameNoChange` if it equals the box's last good reading and **Update on change** is on.

Each box is processed on its own copy of the picture, so overlapping boxes never affect each other. **Binary View** shows the result of steps 1–5 for every box: exactly the image the OCR receives, before *Invert colours*.

With a **PP-OCR** model, ScoreSight skips the Image cleanup steps (2–6, 9 and 10) for every box but a *Count lights* box, which is processed as above. For the others it:

1. takes the part of the box that is inside the processed picture, **in colour**,
2. reports the box as `Empty` without running OCR if the picture has almost no contrast (a display that is off, the unlit LEDs of a dot-matrix display, a black frame, a box over plain background: less than 30 gray levels between its darkest and brightest parts, ignoring the 2% extremes), since a model would guess,
3. skips OCR if the picture hasn't changed (*Skip OCR while image is unchanged*; the picture is compared thresholded on its own, so a change is seen on a dim display too),
4. reads every box of the frame together with the character set of each box's *Type*,
5. continues with steps 12–14 above: *Format*, *Minimum confidence* (PP-OCR's confidence), smoothing, leading zeros, ordinal suffix.

**Binary View** shows a PP-OCR box's picture in gray: what PP-OCR reads, without its colour.

## Reading

### Type

`type`: which characters the OCR may output.

| Value | UI | Allowed characters |
|---|---|---|
| `0` | Number 0-9 | `0123456789` |
| `1` | Time 0-9 , . : | `0123456789` plus `:` and `.` |
| `2` | Text | letters, digits, space and common punctuation |

**Use**: always set the narrowest type. *Number* for scores, fouls, periods and shot clocks. *Time* for clocks. *Text* only for names or other words.

{: .new }
In ScoreSight 0.1.x the Type of a box was lost after a restart or export ([#22](https://github.com/royshil/scoresight/issues/22)). It is saved since 0.2.0.

### Format

`format_regex`: a regular expression the **raw** OCR text must match completely, before averaging, leading-zero removal and ordinal suffixes. If it doesn't match, the reading is marked `FailedFilter` (yellow) and outputs that send only good values ignore it.

The **Format** list shows the preset whose expression is in the field under it, or **Custom** for any other expression. Choose a preset to use its expression, or type your own (choosing **Custom** selects the expression for typing). An expression that isn't a valid regular expression gets a red border and the message *Not a valid expression, so it is ignored*: the OCR then accepts every reading. Its tooltip says what is wrong, for example *missing ), unterminated subpattern*.

| Preset | Expression | Default for |
|---|---|---|
| Time mm:ss.d | `mm:ss` or `ss.d` (expression below) | Time |
| Time mm:ss or ss:d | `mm:ss`, or `ss:d` or `ss.d` (expression below) | |
| Time mm:ss | `^\d{1,3}:[0-5]\d$` | |
| Time ss.d | `^[0-5]?\d\.\d$` | |
| Time 0-59 | `^[0-5]?\d$` | |
| Shotclock 0-39 | `^[0-3]?\d$` | Shot Clock |
| Score 1dd | `^1?\d{1,2}$` | Home Score, Away Score |
| Score ddd | `^\d{1,3}$` | |
| Period 1-4 | `^[1-4]{1}$` | Period |
| Period d | `^\d{1}$` | |
| Alphanumeric | `^[A-Za-z0-9]*$` | |
| Any text | `^.*$` | |
| Any number | `^\d*$` | Home Fouls, Away Fouls, custom fields |

The *Time mm:ss.d* expression is:

```
^(?:(?:\d{1,3}:[0-5]\d)|(?:[0-5]?\d\.\d))$
```

The minutes of the `mm:ss` presets take up to three digits, so clocks that count up past an hour work: a soccer clock's `60:00` to `90:00` and extra time. Up to ScoreSight 0.4.2 they took minutes 0–59, and a soccer clock stopped at `59:59` in the outputs; boxes that use those presets are updated when you open the new version.

Some boards show the tenths after a **colon** below a minute: `1:00`, then `59:8`, `59:7`... *Time mm:ss.d* rejects those readings (yellow), so the clock stops at `1:00` in the outputs. Choose **Time mm:ss or ss:d** for such a board: one digit after the colon is tenths (a minutes clock always shows two), and the readings are sent as the board shows them. Its expression is:

```
^(?:(?:\d{1,3}:[0-5]\d)|(?:[0-5]?\d[.:]\d))$
```

It isn't the default, because with Tesseract a digit of a clock is sometimes missed (`12:04` read as `12:0`): *Time mm:ss.d* rejects that misread, *Time mm:ss or ss:d* would send it. With PP-OCR this is rare. A [sport](game.md) reads `59:8` as 59.8 seconds.

**Use**: always. A tight format is the most effective protection against wrong values reaching your graphics. Examples of custom formats: `^[0-3]?\d$` (shot clock with or without a leading zero), `^(1[0-2]|[1-9]):[0-5]\d$` (12-minute quarters), `^[0-4]$` (downs).

{: .note }
A brace that doesn't form a repeat count, as in `^\d{1,2$`, is read as a plain character, so that expression is valid but no score matches it: every reading is rejected (yellow). Check the expression when a box only shows rejected readings.

### Remove leading zeros
{: #remove-leading-0s }

`remove_leading_zeros`: removes zeros at the start, so `07` becomes `7` (and `00` becomes `0`). An empty reading stays empty. In ScoreSight 0.1.x: **Remove leading 0s**.

**Use**: for scoreboards that zero-pad scores or fouls, when your graphics should show `7`.

### Add ordinal suffix
{: #ordinal }

`ordinal_indicator`: appends an ordinal suffix: `1` becomes `1st`, `2` becomes `2nd`, `3` becomes `3rd`, `4` becomes `4th`. In ScoreSight 0.1.x: **Ordinal (1st, 2nd, ..)**.

**Use**: for periods, quarters, innings or downs when the graphics should show "2nd". On by default for **Period**.

### Count lights (dot counter)
{: #dot-counter }

`dot_detector`: instead of reading characters, counts the separate bright blobs (larger than about 5 square pixels) in the processed box image and reports the count, for example `3`. The reading is always considered valid, and a box with no lit blobs reports `0`. In ScoreSight 0.1.x: **Dot Counter**.

**Use**: for indicator lights such as balls/strikes/outs, possession arrows, bonus lights or timeouts left. Use one box per row of lights, and check in **Binary View** that each lit light is a separate white blob. Use **Invert colours** if lights appear dark.

## Filtering

### Minimum confidence
{: #conf-th-confidence-threshold }

`conf_thresh`: the minimum confidence, in percent, that the OCR model must report for a reading. The slider goes from 0 to 99, and the setting is stored as a fraction (slider ÷ 100, so 60 % is stored as `0.6`). A reading below the threshold is marked `FailedFilter` (yellow). **0 turns the check off, and is the default.** In ScoreSight 0.1.x: **Conf. Th**.

- With a **PP-OCR** model, the confidence is the mean probability of the characters read (0–100 %). It is reliable: in the OCR evaluation, with a threshold of 90 % PP-OCR (accurate) still published 85 % of its readings, and only 1 % of the boxes got a wrong value, against 4 % with no threshold.
- With a **Tesseract** model, ScoreSight uses Tesseract's mean confidence for the recognized text. Tesseract sometimes reports 0 for a correct, non-empty reading; in that case the average of the per-character confidences is used instead.
- A value above 1 in a hand-edited settings file is taken as a percentage (`60` means 60 %).

**Use**: with PP-OCR, 80–90 rejects most wrong readings; the box keeps its last good value meanwhile. With Tesseract, leave it off unless wrong values get through a strict **Format**, then try 30–50 and raise it slowly while watching for correct readings that turn yellow: Tesseract's correct readings of real scoreboard footage often score only 30–50 %, so high thresholds reject good values. With either engine, a box whose readings never reach the threshold never updates, so set it while watching your scoreboard.

{: .new }
In ScoreSight 0.1.x this setting had no effect, because a confidence of 0–100 was compared with a threshold of 0–1. ScoreSight 0.2.0 compares them correctly. Since the old default (50) never did anything, boxes saved by an older version get their threshold set to 0 (off) once, the first time 0.2.0 loads them, so they read exactly as before. The settings file records this with `"boxes_schema_version": 2`, and the log mentions it.

### Smooth over last 5 readings
{: #average-output }

`smoothing`: replaces each reading with the most common value among the box's last 5 accepted (`Success`) readings, comparing whole values. Ties go to the most recent value. Rejected and empty readings don't enter the history. In ScoreSight 0.1.x: **Average Output**.

**Use**: for values that flicker between two readings, for example during LED refresh. A new value must win the vote before it is shown, which delays changes by a couple of detection cycles, so prefer a stricter **Format** or better exposure for fast clocks.

{: .new }
ScoreSight 0.1.x voted character by character, so a change from `12` to `9` could briefly produce `92`. 0.2.0 votes on whole values.

### Skip OCR while image is unchanged
{: #skip-similar-image }

`skip_similar_image`: compares the processed box image (with PP-OCR: the box's picture, thresholded on its own) with the image of the box's last accepted (`Success`) reading. If fewer than 2% of the text pixels (the digits, not the background) changed, OCR is skipped and the box repeats its last good value as an unchanged reading (`SameNoChange`). The comparison image isn't refreshed on skipped cycles, so slow changes add up until they are read. It isn't refreshed by a rejected or empty reading either, so when the first reading of a new value fails, the box is read again on the next cycle. Resizing the box starts over. In ScoreSight 0.1.x: **Skip Similar Image**.

**Use**: to save CPU on values that change rarely (scores, periods). Because the change is measured against the digits, a one-digit change (for example `18` to `19`) is read. Turn it off if a very small change (a single segment of a large display) is ever missed.

{: .new }
ScoreSight 0.1.x measured the change against the whole box, so a one-digit change could be skipped, and it reported skipped cycles as a yellow `SIM` reading. It also compared with the image of the last reading, even a rejected or empty one, so a new value whose first reading failed wasn't read again until the image changed once more.

### When blank
{: #when-blank }

`clear_value`: what the outputs get when the box shows nothing (it is read as `Empty`) for 2 seconds:

- **Keep the last value** (`never`, the default): they keep showing the box's last good reading. A board that blanks out for a moment (a flickering LED, a person walking in front of the board, a camera flash) changes nothing on air.
- **Clear the value** (`blank`): they get an empty value, which clears the text in vMix, OBS, the overlays, the files and every other output. While the box stays blank, the empty value is its unchanged reading (`SameNoChange`), so *Also resend unchanged values* resends it too. The next value the board shows goes out at once.
- **Clear the value, also at zero** (`blank_or_zero`): the same, and a box that reads zero (`0`, `00`, `0:00`, `00:00`, `0.0`) for 2 seconds is cleared too. The zero goes out first.

A blank shorter than 2 seconds keeps the value.

**Use**: for a value that disappears from the board when it no longer applies, such as a handball or hockey penalty timer that goes out (or stops at `0:00`) when the penalty ends, a player number, or a lap board taken away. Leave it on *Keep the last value* for scores and the clock.

{: .new }
Added in ScoreSight 0.4.2 ([discussion #140](https://github.com/royshil/scoresight/discussions/140)). It replaces *Skip empty values* (`skip_empty`), which had no effect since 0.2.0.

## Image cleanup

These settings prepare the box's picture for a **Tesseract** model, and for the dot counter (*Count lights*) with any model. While a PP-OCR model reads the boxes they are disabled, and kept for when you go back to Tesseract.

### Black & white
{: #binarize }

`binarization_method`: how the box is turned into black and white before OCR. In ScoreSight 0.1.x: **Binarize**, with the choices *Global*, *No Binarization*, *Local* and *Adaptive*.

| Value | UI (0.1.x) | How it works | Use when |
|---|---|---|---|
| `0` | Whole picture (Global), the default | One automatic (Otsu) threshold computed over the **whole** picture | The picture is mostly the scoreboard (crop helps) and lighting is even |
| `1` | None (No Binarization) | The grayscale image is passed to the OCR as is | Clean, high-contrast screen captures and TV graphics |
| `2` | This box (Local) | An automatic (Otsu) threshold computed for **this box only** | Dark surroundings, small board in a wide shot, low contrast. A good first thing to try |
| `3` | Adaptive | A threshold that varies across the box (Gaussian adaptive) | Uneven lighting, glare, reflections or gradients across the digits |

The whole-picture threshold is computed only when at least one box uses *Whole picture*, so the other methods don't pay for it.

### Remove specks
{: #cleanup }

`cleanup_thresh`: removes connected blobs smaller than a fraction of the box area. The limit is (slider position ÷ 100) × 5% of the box area, so at the maximum, blobs smaller than about 5% of the box area are removed. In ScoreSight 0.1.x: **Cleanup**.

**Use**: for specks, dust, LED "dead pixels" or bits of the frame inside the box. Too high a value erases thin digits such as `1`.

### Squash height
{: #vscale }

`vscale`: squashes the box vertically to `value/10` of its height (10 = unchanged; the slider shows 100 % to 10 %), keeping it centred. It has no effect on boxes only a pixel high. In ScoreSight 0.1.x: **V.Scale**.

**Use**: for very tall, narrow fonts that the OCR misreads. Try 60–80 %.

### Straighten slant
{: #skew }

`skew`: shears the image horizontally by `value/40` (−0.25 to +0.25) to straighten slanted digits. In ScoreSight 0.1.x: **Skew**.

**Use**: for italic fonts or a camera that is slightly rotated. Adjust until the digits stand upright in Binary View.

### Thicken strokes
{: #dilate }

`dilate`: thickens the bright strokes by this many passes of a 3×3 dilation (0 = off). It applies to the image the OCR reads with every **Black & white** choice, including *None*. In ScoreSight 0.1.x: **Dilate**.

**Use**: raise it when the segments of 7-segment or dot-matrix digits don't touch each other. Lower it to 0 when digits merge into blobs.

{: .new }
In ScoreSight 0.1.x, Dilate changed the Binary View but didn't reach the OCR with every binarization method. In 0.2.0 what you see in Binary View is what the OCR reads.

### Invert colours
{: #invert-input }

`invert_patch`: swaps black and white before OCR. In ScoreSight 0.1.x: **Invert Input**.

**Use**: when readings improve with the colours swapped, or for dark digits on a light background combined with **Count lights**.

### Crop to text
{: #auto-crop }

`autocrop`: crops the box to the area that contains bright pixels, plus a 10-pixel margin, before OCR. With display style **All**, the cropped area is shown as a green rectangle. In ScoreSight 0.1.x: **Auto Crop**.

**Use**: when the box must be larger than the digits, for example because the value changes width. Combine with **Remove specks** so specks don't widen the crop.

### Resize to 35 px (recommended)
{: #rescale-input }

`rescale_patch`: scales the box image to 35 pixels high before OCR, the size the bundled models work best with. In ScoreSight 0.1.x: **Rescale Input**.

**Use**: keep it on. Turn it off only to experiment with external models trained at another size.

### Normalize digit width
{: #normalize-w-h-ratio }

`normalize_wh_ratio`: measures the typical width-to-height ratio of the digits (the median over the last 50 accepted characters `0` and `2`–`9`), then stretches or squeezes the image horizontally so digits come out about half as wide as they are tall. The measurement starts over when you change **Black & white**, **Squash height**, **Straighten slant**, **Thicken strokes** or **Crop to text**, and it isn't saved: it is measured again after a restart. In ScoreSight 0.1.x: **Normalize W-H Ratio**.

**Use**: for unusually narrow or wide fonts.

### Experimental and legacy settings

The last setting of **Image cleanup**, under *Experimental / legacy*, doesn't change how the box is read.

#### Per-character sub-boxes
{: #composite-per-character }

`composite_box` (with the per-character sub-boxes stored as `mini_rects`): experimental. Lets you draw one sub-box per character. The sub-boxes are saved, but in this release recognition still reads the whole box (*not used for reading yet*). See [Composite boxes](boxes.md#composite-per-character-boxes-experimental). In ScoreSight 0.1.x: **Composite (Per-Character)**.

## Template

### Build from other fields
{: #template-field }

`templatefield`, `templatefield_text`: makes a custom field a template whose value is built from other fields, for example `{% raw %}{{Home Score}} - {{Away Score}}{% endraw %}`. **Insert field** next to the template adds a field at the cursor, spelled exactly as the template needs it. Available for custom fields that aren't on the picture (a standard field shows *only custom fields can be built from other fields*). See [Template fields](boxes.md#template-fields). In ScoreSight 0.1.x: **Template Field**.

## Not shown in the window

### OBS source name

`obs_source_name`: the OBS text source this box updates (see [OBS Studio](obs.md)). Set it in the **Text sources** table of the OBS page (**Outputs** tab > **OBS**). Standard fields use `Home score`, `Away score`, `Clock`, `Period`, `#Home Fouls`, `#Away Fouls` and `shotclock`. Custom fields have an empty name, and an empty name doesn't update OBS. (In 0.1.x it could only be changed in an exported configuration file.)

### is_custom

`is_custom`: `true` for fields created with **+**. Custom fields can be renamed, deleted and turned into template fields.

## Other controls

- **Reset to defaults** (in ScoreSight 0.1.x: **Defaults**), at the top of the Box tab, or **Reset settings to defaults** in the field list's context menu: restores all settings of the selected box to the defaults for its field.
- **Remove from picture** also resets them: the next time you place the field, its box starts with the defaults. When you changed any of its settings, ScoreSight asks first.

{: .note }
The **Force Format** checkbox of ScoreSight 0.1.x had no effect and was removed in 0.2.0.
