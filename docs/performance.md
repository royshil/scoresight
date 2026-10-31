---
title: Performance Tuning
parent: Guides
nav_order: 6
description: "Understand Frames/s, Updates/s and Previews/s, and reduce CPU use and latency in ScoreSight."
---

# Performance Tuning
{: .no_toc }

<details open markdown="block">
  <summary>On this page</summary>
  {: .text-delta }
1. TOC
{:toc}
</details>

## Reading the statistics

Turn on **Stats** (above the picture, or **View** > **Statistics overlay**) to see the statistics in the corner of the viewer:

| Number | What it measures | Typical value |
|---|---|---|
| **Frames/s** | Frames read from the source per second. ScoreSight caps this at about 33. | 25–33 for a healthy camera or stream. Lower if the source is slower or the CPU is busy |
| **Updates/s** | How many times per second all boxes are read. | Close to your **Detections / s** setting (1–15, default **5**) |
| **Previews/s** | How often the preview picture in the viewer refreshes. | About **1**. This is intentional. With **View > Smooth preview**, up to 20 (15 for a 30 fps source) |

{: .important }
A low **Previews/s** is **not** a problem. The preview is refreshed about once per second, at any **Detections / s** setting, to save CPU for recognition. Readings are still taken and sent at the **Updates/s** rate. If your graphics update slowly, look at **Updates/s** and your output settings, not at the preview.

If the jumpy picture bothers you, turn on **View > Smooth preview**: the picture then refreshes up to 20 times a second (every other frame of a 30 fps source), so a running clock moves like video. It costs CPU (each preview is a whole frame drawn in the window), more so with a high-resolution source, but the readings don't change. If the status bar's reading rate turns orange with it on, turn it off again. A preview is only sent once the window has shown the last one, so a slow computer gets fewer previews, never a growing delay.

When a source opens, its first frame is shown and read right away, whatever the detection rate.

The status bar at the bottom of the window shows the same numbers without the overlay: the source with its resolution and **frames per second**, and **Reading 4.7/s of 5**, the detection rate against your **Detections / s** setting. The reading rate turns orange when it falls below 70% of the setting: the computer can't keep up, so lower **Detections / s**, use fewer boxes, a lower source resolution or a cheaper [OCR model](ocr-models.md#fast-or-accurate-the-cpu-cost). Its tooltip says which model **PP-OCR (automatic)** is reading with, and why.

The boxes are read on a thread of their own, so a slow OCR model never holds up the video: frames keep arriving at the source's rate (the picture of a live camera or stream stays current, and a video file plays at normal speed), and each reading is made from the latest frame. When the OCR can't keep up, it reads less often instead.

## How fast do you need to be?

**Detections / s** sets how often the boxes are read:

| Content | Suggested Detections / s |
|---|---|
| Scores, periods, fouls, timeouts | 2–5 |
| Game clock showing seconds | 5 (the default). Higher values don't make a once-per-second change appear sooner in a meaningful way |
| Clock with tenths (`9.5`), shot clock in the final seconds | 10–15 |

Every reading costs CPU for **every** box, so the total cost is roughly *number of boxes × detections per second* × the model's cost per box. **PP-OCR (accurate)** costs about five times as much as **PP-OCR (fast)** or Tesseract: at 10 boxes and 5 detections per second, most of a fast desktop core, and more than a laptop core can give; **PP-OCR (automatic)**, the default, switches to fast when that happens (see [OCR Models](ocr-models.md#fast-or-accurate-the-cpu-cost)). If you need a fast shot clock but slow scores, consider running the shot clock in a [second instance](profiles.md).

The slider goes from 1 to 15. For values that change very rarely, you can set `detection_cadence` in the [settings file](configuration.md#recognition) to a value below 1, down to `0.1` (one reading every 10 seconds), while ScoreSight is closed. The slider then shows 1 until you move it, which replaces the value.

## Reducing CPU use

1. **Lower Detections / s** to what you actually need.
2. **Remove boxes you don't use**, and keep boxes tight around the digits.
3. **Crop** the picture to the scoreboard. Less picture means less processing per frame.
4. Turn on **Skip OCR while image is unchanged** (in the Box tab's **Filtering**) for values that rarely change (scores, periods). When a box's image hasn't changed, OCR is skipped for that box and its last good value is repeated.
5. Turn **Stabilize** off when the camera is fixed or you use screen capture.
6. Use a lower source resolution. In [Video Settings](sources.md#cameras-and-capture-cards), 1280x720 with the `MJPG` format is a good choice for USB cameras. For IP cameras, use a sub stream.
7. Choose a cheaper [OCR model](ocr-models.md): **PP-OCR (fast)** costs about a fifth of **PP-OCR (accurate)** (PP-OCR (automatic) switches to it by itself when accurate can't keep up). With Tesseract, prefer **General Scoreboard** over **General Scoreboard Large** if both read your board correctly.
8. Close the [log viewer](troubleshooting.md#collect-logs-first) window when you don't need it.

## Output latency

- Outputs (OBS, vMix, UNO, the outbound API) send in the background. If a target is slow or unreachable, ScoreSight keeps only the latest values and drops intermediate ones. The window and the readings never wait for the network.
- **Update on change** (on by default) means unchanged values are not resent to vMix and UNO, which keeps traffic low. Turn on **Also resend unchanged values** on the vMix or UNO page only if your target needs constant refreshes. OBS text sources and files are only updated when their value changes anyway.
- The [outbound HTTP API](out_api.md) sends on **every** detection cycle. Point it at a fast endpoint on your local network.
- OBS updates go out as soon as a value changes. File outputs are written at most **Save / s** times per second (1–10, set on the **Text files** page), and the last change always reaches the files.
- The built-in [HTTP server](http_server.md) always serves the latest values. Browser overlays that poll it every 100–250 ms are fine.

## Video files

When tuning on a recording, use the speed button next to the source (×1–×32) to skip quickly to the interesting parts. Speed skips frames. It doesn't change how often boxes are read.

## Multiple instances

Each ScoreSight instance runs its own capture and OCR, so CPU use adds up. On a busy machine, prefer one instance with several boxes over several instances with one box each, unless you need different cameras. See [Multiple Instances & Profiles](profiles.md).
