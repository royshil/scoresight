---
title: Recognition Tuning
parent: Guides
nav_order: 4
description: "A step-by-step method for accurate, stable scoreboard readings: capture, geometry, model, box placement, binarization and output filters."
---

# Recognition Tuning
{: .no_toc }

Most recognition problems come from the picture, not from the OCR engine. Work through these steps in order and check **Binary View** after each change. Fixing an early step often makes later tweaks unnecessary.

<a href="https://youtu.be/ZOoNYqGhmmI" target="_blank" rel="noopener"><img src="videos/05-accurate-readings.jpg" width="45%" alt="Video: Rock-solid readings: models, formats and filters (3:46)"/></a>

<details open markdown="block">
  <summary>On this page</summary>
  {: .text-delta }
1. TOC
{:toc}
</details>

## 1. Get a good picture

- **Resolution**: 720p is enough for most boards. What matters is the size of the digits on screen. Aim for digits at least 20–30 pixels tall. Zoom the camera in rather than cropping a tiny area of a wide shot.
- **Focus and exposure**: lock both. Auto-exposure "breathing" changes the brightness of LED digits from frame to frame. Slightly under-expose LED boards so the digits don't bloom into blobs.
- **Flicker and moiré**: LED boards can flicker or show rolling bands. Match the shutter speed to the local mains frequency (1/50 or 1/100 s in 50 Hz countries, 1/60 or 1/120 s in 60 Hz countries), or defocus very slightly to remove moiré.
- **Mounting**: mount the camera rigidly. If it still moves, enable [Stabilize](view-tools.md#stabilize).
- **Video Settings**: for USB cameras, choose a resolution and the `MJPG` format in [Video Settings](sources.md#cameras-and-capture-cards) to get a clean, full-frame-rate picture.

## 2. Fix the geometry

1. **Rotate** if the camera is mounted sideways.
2. **Crop** away everything around the scoreboard.
3. Use **4-corner** if the camera looks at the board at an angle (see [4-corner correction](view-tools.md#4-corner-correction)).

Do this before placing boxes. Straight, rectangular digits are much easier to read.

## 3. Choose the OCR model

The **OCR model** list, under **All boxes** at the bottom of the **Box** tab, applies to all boxes. See [OCR Models](ocr-models.md) for details.

| Model | Best for |
|---|---|
| **PP-OCR (automatic)** (default) | Almost every scoreboard, display and font: accurate while your computer keeps up, fast when it doesn't |
| **PP-OCR (accurate)** / **PP-OCR (fast)** | The same models, without switching (fast for many boxes or a slow computer) |
| **Tesseract: General Scoreboard** | LED, LCD and 7-segment digits (the default before 0.3.0) |
| **Tesseract: General Scoreboard Large** | Large, bold segment digits filling most of the box |
| **Tesseract: Daktronics** | Daktronics-style dot-matrix/LED fonts |
| **Tesseract: General Fonts (English)** | TV score bugs, apps, games and printed or on-screen text in regular fonts |
| **Load external Tesseract model...** | Your own trained Tesseract `.traineddata` model |

Start with PP-OCR: on real scoreboards it reads about three times as many values right as Tesseract with its default settings. With PP-OCR, skip step 5 (Image cleanup is for the Tesseract models). If you use Tesseract, try each of its models for a few seconds with Binary View on, and keep the one that reads most consistently.

## 4. Place the boxes well

- One value per box, with a small margin. Keep frame edges, logos, colons from neighbouring clocks and other digits out of the box.
- Set the display style to **All** to see the green "area read" rectangle (with **Crop to text**) and the blue per-character rectangles. If a character has no blue rectangle, the OCR didn't see it.
- If the box sometimes catches the edge of the scoreboard frame, turn up [Remove specks](box-settings.md#cleanup) or make the box a little smaller.

## 5. Make the binary image clean (Tesseract)

This step is for the Tesseract models and the dot counter: PP-OCR reads each box's picture as it is, and its Image cleanup settings are disabled while it reads.

Select the box and look at it in **Binary View** (also the **Binary view** button in the header of **Image cleanup**, in the Box tab). You want solid, unbroken digits on a plain background. The settings below are in the **Image cleanup** section of the Box tab: click its header to open it.

| What you see in Binary View | Try |
|---|---|
| The whole box is black or white, or digits are lost in dark/bright areas | **Black & white: This box** (threshold computed for this box only) or **Adaptive** (for uneven lighting, reflections and glare) |
| Digits look fine in the camera view but are broken or noisy in binary | **Black & white: This box**, or **None** (the OCR then gets the grayscale image) |
| Small specks or dust around the digits | Raise **Remove specks** |
| Segments of 7-segment/LED digits don't touch (an "8" looks like dotted lines) | Raise **Thicken strokes** by 1–2 |
| Digits merge into blobs | Lower **Thicken strokes** (0 or 1), or slightly under-expose the camera |
| Digits are slanted (italic) | Adjust **Straighten slant** until they stand upright |
| Very tall, narrow digits | Lower **Squash height**, or turn on **Normalize digit width** |
| Reading improves when the colours are swapped | Toggle **Invert colours** |

Binary View shows exactly what the OCR reads: **Thicken strokes**, **Remove specks**, **Squash height** and **Straighten slant** apply to the OCR with every **Black & white** choice. Keep **Resize to 35 px** on (the default). It resizes the box content to the height the OCR models were trained on. The header of **Image cleanup** says how many of its settings you changed, so you can see at a glance whether a box was tuned.

A box over an empty area (for example an unlit digit position, or a board that is switched off) reads as empty (**∅**). ScoreSight doesn't run the OCR on a blank image, so the scoreboard models can't invent digits there.

## 6. Constrain what counts as valid

Even a good picture produces an occasional wrong reading, for example while digits change or during camera flashes. These settings, in the **Reading** and **Filtering** sections of the Box tab, stop wrong readings from reaching your graphics:

- **Type**: *Number* only allows digits, and *Time* allows digits, `:` and `.`. This alone removes most garbage. Use *Text* only for real text.
- **Format**: pick a preset from the **Format** list (it always shows the preset in use, or *Custom*). A reading that doesn't fully match the format is marked as *failed filter* (yellow) and is not sent as a new value. An invalid expression is shown in red: the OCR ignores it.

  | Preset | Accepts |
  |---|---|
  | Time mm:ss.d | `12:34` or `9.5` (clocks that switch to tenths in the last minute) |
  | Time mm:ss | `12:34`, `0:59`, `90:00` |
  | Time ss.d | `9.5`, `45.1` |
  | Time 0-59 | `0` to `59`, with or without a leading zero (`7` or `07`) |
  | Shotclock 0-39 | `0` to `39`, with or without a leading zero (`7` or `07`) |
  | Score 1dd | 1–2 digits, or 3 digits starting with 1 (`0`–`199`) |
  | Score ddd | 1–3 digits |
  | Period 1-4 | a single `1`–`4` |
  | Period d | a single digit |
  | Alphanumeric | letters and digits only |
  | Any text / Any number | anything / digits only |

  You can also type your own regular expression. See [Format](box-settings.md#format).

  {: .new }
  Up to ScoreSight 0.3.0, *Time 0-59* and *Shotclock 0-39* required **two** digits, so a shot clock showing `9` rather than `09` was rejected and the outputs stayed at `10` for its last ten seconds. They now accept both, and boxes saved with the old presets are updated once (see [One-time upgrades](configuration.md#one-time-upgrades-of-older-settings)).
- **Remove leading zeros**: turns `07` into `7`. Use it for boards that zero-pad scores.
- **Smooth over last 5 readings**: shows the most common of the last 5 accepted readings to smooth out flicker. It compares whole values, so a change from `12` to `9` never shows a mix such as `92`. It adds a little delay when the value changes.
- **Minimum confidence**: the minimum confidence of the OCR model, in percent. Readings it is less confident about are marked *failed filter*, and the box keeps its last good value. It is **off (0) by default**. With PP-OCR, 80–90 rejects most wrong readings. With Tesseract, if random wrong values still get through a strict Format, try 30–50, and lower it if good values turn yellow: Tesseract's correct readings of real scoreboards often score only 30–50 %. See [Minimum confidence](box-settings.md#conf-th-confidence-threshold).
- **Add ordinal suffix**: adds st/nd/rd/th (`1st`, `2nd`...). It is on by default for Period.

## 7. Indicator lights and dots

For possession arrows, bonus lights, timeout dots or balls/strikes/outs, don't read characters. Turn on **Count lights (dot counter)** for the box instead. ScoreSight counts the lit blobs inside the box and reports the number. Use one box per row of lights, and use Binary View to check that each light is a separate white blob.

## 8. Still not reliable?

- Try the other [OCR models](ocr-models.md).
- Make sure **Detections / s** isn't higher than you need (see [Performance Tuning](performance.md)). Fewer, cleaner readings plus **Smooth over last 5 readings** often beat many noisy ones.
- [Collect training data](data_annotation.md) for your scoreboard and train a custom Tesseract model, then load it with **Load external Tesseract model...**.
- [Open an issue](https://github.com/royshil/scoresight/issues/new/choose) with a short clip or screenshots (camera view and Binary View) and your exported configuration.

## Symptom quick reference

| Symptom | Likely fix |
|---|---|
| `8` read as `0`, `6` or `B`, or `0` read as `8` | Adjust **Thicken strokes**, try the **Daktronics** or **Large** model, improve focus |
| `1` missing or read as `7` | Widen the box slightly; **Remove specks** lower; check the "1" isn't touching the box edge |
| First digit dropped on two-digit scores | Box too tight on the left; use **Score** presets; turn off **Skip OCR while image is unchanged** to test |
| Letters appear in a clock | **Type: Time** plus a **Time** format preset |
| Score shows `07` instead of `7` | **Remove leading zeros** |
| Value flickers between two readings | **Smooth over last 5 readings**, a stricter **Format**, better exposure |
| Correct readings turn yellow | The **Format** doesn't match (check the preset), or **Minimum confidence** is too high. Set it to 0 (*Off*) to test |
| A change on the board is missed | **Skip OCR while image is unchanged** treats changes of less than 2% of the digit pixels as no change. Turn it off for that box |
| Box shows **∅** (empty) | Nothing was read, or the box image is blank: check that the box is on the digits, then check **Binary View** and **Invert colours** |
| Low-contrast stadium board, dark surroundings | Crop tightly, **Black & white: This box** or **Adaptive**, one box per value, **Remove leading zeros**, a strict **Format** |
| Readings fine in daylight, bad at night (or the reverse) | Lock exposure; use **This box**/**Adaptive** black and white; save separate [profiles](profiles.md) for day and night |
