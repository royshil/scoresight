---
title: Getting Started
nav_order: 2
has_children: true
description: "Install ScoreSight and read your first scoreboard."
---

# Getting Started

New to ScoreSight? Follow these two pages in order:

1. [Installation](INSTALL.md): download and install ScoreSight on Windows, macOS or Linux, and grant the camera and screen-recording permissions it needs.
2. [Quickstart](quickstart.md): open a video source, draw boxes over the score and clock, check the readings and send them to your graphics.

## System requirements

| | Requirement |
|---|---|
| Windows | Windows 10 (version 1809 or newer) or Windows 11, 64-bit (x64). The installer checks this |
| macOS | macOS 15 (Sequoia) or newer. Apple Silicon (M1 and later); 0.4.4 is the last release for Intel Macs |
| Linux | 64-bit x86_64 distribution with glibc 2.35 or newer (for example Ubuntu 22.04 or newer, Debian 12 or newer) and an X11 or Wayland desktop |
| CPU / RAM | Any recent dual-core CPU and 4 GB RAM. CPU use grows with the number of boxes and the Detections / s setting (see [Performance Tuning](performance.md)) |
| Network | Optional. Needed only for NDI, URL/RTSP sources, network outputs and the update check |

{: .note }
ScoreSight 0.1.x and older ran on older macOS versions. Starting with 0.2.0, the bundled OCR engine and Qt framework require macOS 15 or newer.

## Key concepts

Source
: Where the picture comes from: a camera or capture card, an NDI feed, a URL (HTTP/RTSP) stream, a screen or window capture, or a video file. See [Video Sources](sources.md).

Box (field)
: A rectangle you draw over one value on the scoreboard, such as "Home Score" or "Time". Every box has a name and its own recognition settings. See [Detection Boxes & Templates](boxes.md).

Reading (result)
: The text ScoreSight recognized in a box during one detection cycle, together with its state: **new**, **unchanged**, **failed filter** or **empty**. New and unchanged readings are the **good** readings that outputs use.

Output
: A destination for the readings: text files, the built-in HTTP server, OBS, vMix, overlays.uno or your own HTTP endpoint. See [Outputs](outputs.md).

Profile
: A named, independent set of settings, so you can run several ScoreSight windows side by side. See [Multiple Instances & Profiles](profiles.md).
