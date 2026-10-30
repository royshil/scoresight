---
title: Settings, Files & Command Line
parent: Reference
nav_order: 2
description: "Where ScoreSight stores settings and logs, command-line options, environment variables and the keys in scoresight.json."
---

# Settings, Files & Command Line
{: .no_toc }

<details open markdown="block">
  <summary>On this page</summary>
  {: .text-delta }
1. TOC
{:toc}
</details>

## Where ScoreSight keeps its files

| | Windows | macOS | Linux |
|---|---|---|---|
| Settings folder | `%LOCALAPPDATA%\scoresight\scoresight` | `~/Library/Application Support/scoresight` | `~/.local/share/scoresight` |
| Log folder | `%LOCALAPPDATA%\scoresight\scoresight\Logs` | `~/Library/Logs/scoresight` | `~/.local/state/scoresight/log` |

On Windows, `%LOCALAPPDATA%` is usually `C:\Users\<you>\AppData\Local`. Paste the path into the File Explorer address bar to open it.

The settings folder contains:

| File / folder | Content |
|---|---|
| `scoresight.json` | All settings of the default profile: source, boxes, view tools and outputs |
| `scoresight-<profile>.json` | The settings of a named [profile](profiles.md) |
| `scoresight.json.corrupt-<timestamp>` | A backup ScoreSight made of a settings file it could not read (see below) |
| `ocr_training_data/` | The default folder for [OCR training data](data_annotation.md) |

**File > Open settings folder** opens the settings folder (the one from `SCORESIGHT_DATA_DIR`, if set). **Tools > View log** (**Ctrl+Shift+L**) shows the live log. Its **Open Log Folder** button opens the log folder, and **Open on startup** shows the log window every time ScoreSight starts. If ScoreSight couldn't create a log file, the log window says that the log goes to the console instead.

Both folders can be moved with [environment variables](#environment-variables).

The window title shows the version, plus the profile name when one is active, for example `ScoreSight - v0.2.0 [court2]`.

### Settings are saved automatically

ScoreSight saves changes as you make them. Box changes are saved about half a second after the last edit. Settings files are written atomically (to a temporary file that then replaces the old one), so a crash or power loss can't leave a half-written file.

If a settings file is damaged anyway, for example by a full disk or manual editing, ScoreSight doesn't wipe your settings silently. It renames the damaged file to `<name>.corrupt-<timestamp>`, logs an error and starts with defaults. You can open the backup in a text editor to recover your boxes, for example by copying the `boxes` list into an exported configuration file and importing it.

### One-time upgrades of older settings

When ScoreSight 0.2.0 first opens a settings file from an older version, it adjusts two settings once and writes a line about each to the log:

- A vMix port of `8099` becomes `8088` (see [vMix](vmix.md)). The key `vmix_port_migrated` records that this was done.
- The **Minimum confidence** (in 0.1.x: **Conf. Th**) of every box becomes 0 (off). It had no effect in older versions, so the boxes read exactly as before (see [Minimum confidence](box-settings.md#conf-th-confidence-threshold)). The key `boxes_schema_version` (set to `2`) records that this was done.

When ScoreSight 0.3.1 or later first opens boxes saved by 0.3.0 or older (in the settings file or an imported configuration file), a box whose **Format** is the old *Time 0-59* (`^[0-5]\d$`) or *Shotclock 0-39* (`^[0-3]\d$`) expression gets the preset's new one (`^[0-5]?\d$` or `^[0-3]?\d$`), which also accepts a single digit: a shot clock shows `9`, not `09`. Other formats are kept, and the log says how many boxes changed. `boxes_schema_version` `3` records that this was done.

Settings you change afterwards are kept as you set them.

### Logs

Each run creates two log files: `scoresight_<date>_<time>.log` (ScoreSight's own log) and `scoresight_std_<date>_<time>.log` (messages from libraries, and the details of a crash if ScoreSight closes unexpectedly). ScoreSight keeps the 10 most recent logs of each kind and deletes older ones automatically, but never those of the current session. Attach both files from the session that had the problem when you [report a bug](troubleshooting.md#collect-logs-first).

## Command-line options

| Option | Description |
|---|---|
| `--profile NAME` | Use the settings file `scoresight-NAME.json` instead of `scoresight.json`. See [Multiple Instances & Profiles](profiles.md). |
| `--port N` | Run the [HTTP server](http_server.md) on port `N` (1–65535, default `18099`). |
| `--self-test` | Check the installation without showing a window, then exit. It prints the settings file and log file paths, loads all modules, checks the bundled files, builds the main window off-screen, loads every bundled OCR model (the Tesseract models and every PP-OCR choice) and reads a test image with each. It prints `SELF-TEST OK` and exits with code 0 on success, or prints the error and exits with code 1. Useful to check an installation or a build. |

Qt's own options, such as `-style fusion`, are passed on to Qt.

Examples:

```powershell
# Windows
& "C:\Program Files\ScoreSight\scoresight.exe" --profile court2 --port 18100
```

```bash
# macOS (start an additional instance with options)
open -n -a ScoreSight --args --profile court2 --port 18100

# Linux, or running from source
./scoresight/scoresight --profile court2 --port 18100
python src/main.py --self-test
```

## Environment variables

| Variable | Effect |
|---|---|
| `SCORESIGHT_PROFILE` | Same as `--profile`: use `scoresight-<value>.json`. |
| `SCORESIGHT_DATA_DIR` | Use this folder instead of the default settings folder. |
| `SCORESIGHT_LOG_DIR` | Write logs to this folder instead of the default log folder. |
| `SCORESIGHT_DEBUG` | If set (to any value), also print the log to the console, log more detail, and log every request to the HTTP server. |
| `SCORESIGHT_STARTUP_REPORT` | A file path. Once ScoreSight is ready, it writes how long each startup phase took to this file as JSON (the same times as the `Startup:` line in the log, see [Troubleshooting](troubleshooting.md#slow-start)). Used by the boot time tests. |
| `OPENCV_FFMPEG_CAPTURE_OPTIONS` | Options for OpenCV's FFmpeg backend, used by URL sources. If it isn't set, ScoreSight sets it to `rtsp_flags;prefer_tcp`: RTSP over TCP first, falling back to UDP ([RTSP over TCP](sources.md#rtsp-over-tcp)). Set it to `rtsp_transport;udp` to force UDP for cameras that only support RTSP over UDP. |
| `QT_QPA_PLATFORM` | Qt platform plugin. `offscreen` runs without a display. `--self-test` sets it to `offscreen` if it isn't set. |

When running from source, ScoreSight also reads a `.env` file in the repository root, which is handy for `SCORESIGHT_DEBUG=1`.

{: .tip }
`SCORESIGHT_DATA_DIR` makes a portable setup possible: keep ScoreSight's settings on a USB stick or a shared drive that you take from venue to venue.

## Import and export

**File > Export field layout...** (**Ctrl+Shift+S**) writes the current boxes (names, positions, settings) to a `.json` file, and **File > Import field layout...** (**Ctrl+O**) loads them (in 0.1.x: Export and Import Configuration). Other settings (source, crop, 4-corner correction, outputs) are not included. To keep complete, separate setups, use [profiles](profiles.md) or copy the profile's settings file.

## Settings keys in `scoresight.json`

You normally never edit this file: everything is set through the UI. This list helps when reading a file someone sent you, or when troubleshooting. Close ScoreSight before editing the file by hand.

### Source and view

| Key | Meaning |
|---|---|
| `source_selected` | The last source and its type, reopened at startup: `{"type": "URL", "value": "rtsp://..."}`, `{"type": "File", "value": "<path>"}` or `{"type": "Screen Capture", "value": <window id, -1 for the entire screen>}`, or for cameras and NDI `{"type": "OPENCV" or "NDI", "value": "<device id>", "description": "<name>"}`. A plain path or URL saved by 0.1.x is still understood |
| `four_corners` | The four corner points of the perspective correction |
| `crop_mode`, `left_crop`, `top_crop`, `right_crop`, `bottom_crop` | Crop on/off and crop amounts in pixels |
| `rotation` | `0`, `90`, `180` or `270` |
| `box_display_style` | `0` No Box, `1` Outline, `2` Names, `3` All |
| `show_osd` | The statistics overlay (**Stats**) on or off. Settings without it (a first start) get `false`, settings from 0.2.0 and before `true`, as it always showed then |
| `fps`, `width`, `height`, `fourcc`, `backend` | Camera [Video Settings](sources.md#cameras-and-capture-cards), applied whenever a camera opens. Only the settings you changed in the dialog are stored |

### Recognition

| Key | Meaning |
|---|---|
| `boxes` | The list of boxes: `name`, `rect` (`x`, `y`, `width`, `height`), `settings` (see [Per-Box Settings](box-settings.md)) and `mini_rects` |
| `boxes_schema_version` | The version of the box settings: `2` upgraded for 0.2.0, `3` with the one- or two-digit clock formats (see [One-time upgrades](#one-time-upgrades-of-older-settings)). Don't change it |
| `custom_boxes_names` | Names of your custom fields |
| `ocr_model` | `"ppocr:auto"` PP-OCR (automatic), `"ppocr:small"` PP-OCR (accurate), `"ppocr:tiny"` PP-OCR (fast), `0` Tesseract: Daktronics, `1` Tesseract: General Scoreboard, `2` Tesseract: General Fonts (English), `3` Tesseract: General Scoreboard Large, or the path of an external `.traineddata` file. Absent in a new setup: PP-OCR (automatic), stored when the first source opens (the Tesseract values are those of earlier versions, so an older setup keeps its model) |
| `detection_cadence` | Detections / s: 1–15 from the slider. Values down to `0.1` are accepted when set in the file (see [Performance Tuning](performance.md#how-fast-do-you-need-to-be)) |
| `update_on_change` | Update on change on/off |
| `sport` | The [sport](game.md) whose game ScoreSight follows: `none` (the default), `basketball`, `basketball_halves`, `soccer`, `futsal`, `hockey`, `football`, `volleyball` or `racing` (Racing (laps)) |

### Outputs

| Key | Meaning |
|---|---|
| `output_folder`, `save_csv`, `save_xml`, `append_method`, `aggs_per_second` | [Text files](text-files.md) output (`append_method`: `0` CSV, `1` TXT, `2` both, `3` don't append; `aggs_per_second`: Save / s) |
| `obs` | OBS connection: `ip`, `port`, `password` |
| `obs_auto_connect` | `false` after **Disconnect**: the saved OBS connection isn't opened at startup until you connect again. Missing or `true`: ScoreSight connects to OBS at startup |
| `vmix_host`, `vmix_port`, `vmix_input`, `vmix_mapping`, `vmix_send_same` | [vMix](vmix.md) output |
| `vmix_port_migrated` | `true` once the one-time change of a saved port 8099 to 8088 has run |
| `uno_url`, `uno_mapping`, `uno_send_same`, `uno_essentials`, `uno_essentials_id` | [UNO](uno.md) output |
| `enable_out_api`, `out_api_url`, `out_api_method`, `out_api_encoding` | [HTTP API](out_api.md) output. `out_api_method` is `POST`, `PUT` or `GET`; `out_api_encoding` is `JSON (Full)`, `JSON (Simple key-value)`, `XML` or `CSV`, in English whatever the interface language |
| `tcp_output` | [TCP / UDP](tcp-output.md) output, an object: `preset` (`casparcg`, `chyron`, `livescore`, `magicsoft`, `vizrt`, `websocket-json` or `custom`), `host`, `port` (`null` when not set), `transport` (`tcp`: ScoreSight connects, `udp`, `tcp-server`: programs connect to ScoreSight, or `websocket`; a TCP server needs no `host`), `url` and `headers` (a WebSocket's `ws://` or `wss://` URL, and its extra headers as `Name: value` lines; they may hold a token, in plain text), `mode` (`field`: a message per changed field, `frame`: one message with every field), `template`, `init` (the "on connect" message), `line_ending` (`crlf`, `lf`, `cr`, `nul` or `none`), `encoding` (`utf-8`, `iso-8859-1`, `cp1252`, `utf-16-le` or `ascii`), `escape` (`none`, `line`, `json`, `xml`, `amcp`, `chyron` or `nul`), `send_same`, `min_interval` and `refresh_interval` (seconds, `0` for none), and CasparCG's `channel`, `layer`, `cg_layer` and `template_name`. A missing or invalid value gets its default. The output isn't started at startup: click **Start sending** |
| `tcp_mapping` | The names you edited in the TCP / UDP output's table, `{"Box Name": "name"}` (`""` leaves the field out). Fields without an entry use the preset's name |

### Application

| Key | Meaning |
|---|---|
| `language` | The language chosen in **View > Language**, for example `de_DE`. Without it, ScoreSight follows the system language |
| `color_scheme` | **View > Appearance**: `System`, `Light` or `Dark` |
| `window_layout` | **View > Setup layout** (`setup`) or **Live layout** (`live`) |
| `main_splitter_sizes` | The widths of the field list, the picture and the inspector in pixels in the Setup layout, for example `[260, 742, 340]`. `0` means the pane is hidden |
| `live_fields_width` | The width of the field list in the Live layout, in pixels (400 by default) |
| `show_unused_fields_setup`, `show_unused_fields_live` | **View > Show unused fields** in each layout (`true` and `false` by default) |
| `smooth_preview` | **View > Smooth preview**: `true` refreshes the picture up to 20 times a second instead of about once (`false` by default) |
| `image_cleanup_expanded` | `true` while the **Image cleanup** section of the Box tab is open |
| `open_on_startup` | Show the log window at startup |
| `disable_update_checks` | `true` turns off the update check at startup (the **Don't check for updates at startup** checkbox in the update dialog). **Help > Check for updates...** always works |
| `save_ocr_training_data`, `ocr_training_data_folder`, `ocr_training_data_max_size` | [OCR training data](data_annotation.md) collection (`save_ocr_training_data` is **Tools** > **Collect OCR training data**). An empty `ocr_training_data_folder` means the default folder. The 0.1.x key `ocr_training_data_save_folder` is still read if the new key was never set |

{: .warning }
`scoresight.json` stores the OBS WebSocket password and the UNO and API URLs (which may contain access tokens) in plain text. Don't share the file publicly. Exported field layouts contain only boxes, but check them before sharing anyway.
