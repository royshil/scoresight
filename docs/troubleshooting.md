---
title: Troubleshooting
nav_order: 7
description: "Fixes for common ScoreSight problems: RTSP streams, macOS freezes and quit hangs, vMix and OBS not updating, bad recognition, low performance, missing files and more."
---

# Troubleshooting
{: .no_toc }

Each section describes a symptom, its usual causes and the fix. The issue numbers link to the original GitHub reports. If your problem isn't covered, see the [FAQ](faq.md) or [open an issue](https://github.com/royshil/scoresight/issues/new/choose) and attach your logs.

<a href="https://youtu.be/FVqdjvmnFIU" target="_blank" rel="noopener"><img src="videos/14-profiles.jpg" width="45%" alt="Video: Two cameras, backups and troubleshooting (3:58)"/></a>

<details open markdown="block">
  <summary>On this page</summary>
  {: .text-delta }
1. TOC
{:toc}
</details>

## Collect logs first

The log almost always shows what went wrong.

1. Open **Tools** > **View log** (**Ctrl+Shift+L**) to watch the log live. Its **Open Log Folder** button opens the folder with all log files.
2. Or open the folder directly:

   | OS | Log folder |
   |---|---|
   | Windows | `%LOCALAPPDATA%\scoresight\scoresight\Logs` |
   | macOS | `~/Library/Logs/scoresight` |
   | Linux | `~/.local/state/scoresight/log` |

3. Each session writes `scoresight_<date>_<time>.log` and `scoresight_std_<date>_<time>.log`. Attach **both** files from the session with the problem to your issue. If ScoreSight closed by itself (a crash), the end of the `scoresight_std_` file shows where: `Windows fatal exception` or `Fatal Python error`, followed by what each part of the program was doing at that moment.

{: .warning }
Logs can contain host names and URLs (including any tokens in them). ScoreSight 0.1.x also logged the OBS WebSocket password; 0.2.0 doesn't. Look through the logs and remove secrets before posting them publicly.

For even more detail, start ScoreSight with the environment variable `SCORESIGHT_DEBUG=1` (see [Environment variables](configuration.md#environment-variables)).

## Source problems

When a source can't be opened or read, a red banner under the source bar says what failed and what to try, and the dot before the **Source** drop-down turns into a red square. **Retry** opens the same source again; **Choose another source** opens the list. An amber triangle means the source is opening, slow (less than half its own frame rate), stalled or reconnecting: its tooltip says which.

### RTSP or URL stream won't open (#10)

**Symptoms**: the banner says "Can't open the stream ...", a black picture, or (in old versions) `VIDEOIO(DSHOW): backend is generally available but can't be used to capture by name` in the log ([#10](https://github.com/royshil/scoresight/issues/10)).

**Fix**:

1. Make sure you run a current version. Versions before 0.0.12 tried to open URLs with DirectShow on Windows, which can never work.
2. Test the exact URL in VLC (**Media** > **Open Network Stream**). If VLC can't play it, fix the URL, the credentials or the network first.
3. Include user, password, port and path: `rtsp://user:password@192.168.1.50:554/stream1`. URL-encode special characters in the password.
4. Check the RTSP transport. ScoreSight tries **RTSP over TCP** first, which works across VPNs, Wi-Fi and NAT, and falls back to UDP when the camera refuses TCP. If your camera only supports UDP and the stream still won't open, set `OPENCV_FFMPEG_CAPTURE_OPTIONS=rtsp_transport;udp` before starting ScoreSight to force UDP. See [RTSP over TCP](sources.md#rtsp-over-tcp).
5. Try the camera's sub stream (lower resolution).
6. Fallback: open the stream in OBS and send it to ScoreSight with NDI or OBS's Virtual Camera.

ScoreSight 0.2.0 gives up opening or reading a stream after 5 seconds, so a dead stream no longer freezes the window or makes switching sources hang.

### Camera not listed or black picture

- Click **Reload sources** (⟳, or **F5**) after plugging in a camera.
- Close other apps that use the camera (OBS, Zoom, Teams, the camera vendor's software). Most cameras serve only one app at a time.
- **macOS**: allow **Camera** access in System Settings > Privacy & Security > Camera.
- **Linux**: add your user to the `video` group and log in again. Cameras are listed as *name (/dev/videoN)*; only device nodes that can capture video are shown.
- Open **Video settings** (the gear next to the source) and try another **Capture Backend** or **Video Format** (`MJPG` vs `YUY2`).
- Capture cards: make sure the input signal is present (a resolution and frame rate the card supports), and try it in the vendor's own software.

### NDI source not listed

- Click **Reload sources** (⟳, or **F5**). Sources that start after ScoreSight appear only after a reload.
- Make sure both computers are on the same network and subnet, and that the firewall allows NDI.
- **macOS**: allow **Local Network** access for ScoreSight in System Settings > Privacy & Security.

### Screen capture shows nothing

- **macOS**: allow **Screen Recording** (System Settings > Privacy & Security > Screen & System Audio Recording), then **quit and restart** ScoreSight. Without the permission, the source banner says so, and its **Open System Settings** button opens the page.
- **Linux**: screen capture isn't supported. Use OBS with NDI or the virtual camera.
- Minimized windows can't be captured. Keep the window visible and at a fixed size.

## Slow start

Every start logs how long it took, one line per session that begins with `Startup:` in `scoresight_<date>_<time>.log` (see [Collect logs first](#collect-logs-first)), for example:

```
Startup: before main.py 0.20 s, arguments 0.00 s, imports 0.35 s, QApplication 0.00 s, main window 0.03 s, show 0.00 s, first event loop pass 0.01 s; total 0.59 s; HTTP server ready at 0.57 s, video sources discovered at 0.62 s
```

- **before main.py**: from launching the app until its Python code runs (unpacking and loading the app, which antivirus scanning or a slow disk can make long).
- **imports**, **QApplication**, **main window**, **show**, **first event loop pass**: the steps that build the window.
- **total**: from launching the app until its window is ready.
- **HTTP server ready** and **video sources discovered** happen in the background and don't hold the window up. A slow camera or NDI discovery shows here; if it took longer than about 5 seconds, it has a `Startup:` line of its own.

If ScoreSight is slow to start, [open an issue](https://github.com/royshil/scoresight/issues/new/choose) with the `Startup:` line (or the whole log) of a slow start, your OS and its version, how you installed ScoreSight (installer, portable zip, disk image, from source) and whether a second start right after the first is also slow.

## macOS: slow start, freezes, or hang when quitting (#33, #7)

**Symptoms**: in ScoreSight 0.1.x and older on macOS, the app took up to a minute to appear ([#33](https://github.com/royshil/scoresight/issues/33)), the window froze ("beach ball") for long periods, or it showed "Not Responding" when quitting and had to be force-quit ([#7](https://github.com/royshil/scoresight/issues/7)).

**Causes and fixes in 0.2.0**:

- The slow start came from the packaging: the 0.1.x macOS app unpacked itself into a temporary folder on every launch. The 0.2.0 app is a regular app bundle that starts in seconds. Finding cameras and NDI sources and connecting to OBS also happen in the background now, so the window appears right away.
- The quit hang came from the built-in HTTP server, which didn't shut down cleanly on macOS. ScoreSight 0.2.0 stops it internally, so quitting is immediate.
- Freezes during use came from network outputs (OBS, vMix, UNO) waiting for slow or unreachable targets on the main thread. In 0.2.0, all outputs run in the background with timeouts.
- Closing or switching away from a stalled source waits at most 3 seconds.
- macOS App Nap no longer slows ScoreSight down while its window is in the background.

**If you still see it**:

- Update to the latest release.
- For a slow start, look at the `Startup:` line in the log (see [Slow start](#slow-start)).
- Turn off outputs whose target is offline (stop vMix/UNO, disconnect OBS).
- Collect the logs and, for hangs, a sample from **Activity Monitor** (select ScoreSight > the "..." menu > **Sample Process**), and [open an issue](https://github.com/royshil/scoresight/issues/new/choose).

Force-quitting doesn't damage your settings: they are saved as you work.

## Output problems

### vMix shows no data (#55, #25)

**Symptom**: vMix titles don't change. ScoreSight 0.1.x logged `Failed to send data to http://localhost:8099/api/... BadStatusLine('VERSION OK ...')`. ScoreSight 0.2.0 shows ■ *Port 8099 is vMix's TCP API: use 8088* in the vMix row of the **Outputs** list and logs `vMix: VMixTCPPortError: localhost:8099 answered like the vMix TCP API ('VERSION OK')` ([#55](https://github.com/royshil/scoresight/issues/55), [#25](https://github.com/royshil/scoresight/issues/25)).

**Cause**: port 8099 is vMix's TCP API. ScoreSight uses vMix's HTTP **Web API**, which listens on port **8088**.

**Fix**:

1. In vMix, enable **Settings** > **Web Controller** (port 8088).
2. In ScoreSight, select **vMix** in the **Outputs** list, set the port to **8088** and press **Enter**. ScoreSight 0.2.0 changes a saved 8099 to 8088 automatically the first time it starts.
3. Use the exact field names from the vMix Title Editor, **including `.Text`** (for example `Home Score.Text`).
4. Check the **Input** number, and click **Start**.

Full guide: [vMix](vmix.md).

### OBS text doesn't update (#30)

- Look at the OBS row of the **Outputs** list: it says whether ScoreSight is connected, and why not (see [OBS: Troubleshooting](obs.md#troubleshooting)).
- In ScoreSight 0.1.x, OBS updates only worked when an output folder was set in the **Text Files** tab. 0.2.0 removed that requirement. Update, or set a folder as a workaround.
- The OBS text sources must be named exactly `Home score`, `Away score`, `Clock`, `Period`, `#Home Fouls`, `#Away Fouls` or `shotclock`, or use **Create OBS Scene**. Custom fields don't update OBS by default (see [OBS: Custom fields](obs.md#custom-fields)). A wrong name shows up in the log as `OBS: OBSSDKRequestError: Request SetInputSettings returned code 600`.
- If updates stop after a few minutes ([#30](https://github.com/royshil/scoresight/issues/30)), check whether OBS restarted or the WebSocket dropped. ScoreSight 0.2.0 reconnects by itself (the log shows `OBS: OBSConnectionLost: ...` while OBS is unreachable, then `OBS: reconnected to <host>:<port>`). On 0.1.x, reconnect with **Connect OBS**. A [Browser Source](http_server.md) overlay is a robust alternative.
- On macOS, prevent your Mac from sleeping during a stream. ScoreSight 0.2.0 turns off App Nap for itself, so it keeps full speed while its window is hidden.

### Text files are not written (#6)

**Symptom**: `results.csv` and `results.xml` appear, but no `<Box Name>.txt` files ([#6](https://github.com/royshil/scoresight/issues/6)).

**Cause (0.1.x)**: `.txt` files were written only at the exact moment a value changed. If that moment fell between two file saves, the file wasn't written until the next change.

**Fix**: ScoreSight 0.2.0 writes each file whenever its value differs from what it last wrote, or when the file is missing, and a value that changes between two saves is written at the next save. If files are still missing:

- Check that an output folder is set and still exists (ScoreSight forgets a folder that was deleted, and logs `Output folder does not exist`).
- Check that the box's reading is green or light green. Rejected (yellow) and empty readings aren't written.
- Look for `Error writing to <path>` in the log (permissions, a full disk, or a folder synced by OneDrive/Dropbox).
- Box names with characters that aren't allowed in file names are written with `_` instead, for example `Home_Away.txt` for *Home/Away*.

### CSV doesn't update in real time (#29)

In ScoreSight 0.2.0, `results.csv` is updated atomically with the current values (header once, values properly quoted). For a live data file, use **Don't append results**, or read `http://localhost:18099/csv?pivot` from the [HTTP server](http_server.md#get-csvpivot). For a game log, use **Results in .csv file**: a row is added whenever a value changes, and when you add, remove or rename a box, the old log is kept as `results-<timestamp>.csv` and a new file is started. See [Text, CSV & XML Files](text-files.md#resultscsv) and [#29](https://github.com/royshil/scoresight/issues/29).

### HTTP server not reachable

- **Port 18099 is already in use**: the log shows `HTTP server: port 18099 is already in use or not available`. Another ScoreSight instance (or another program) uses the port, and this instance runs without its HTTP server. Close the other program, or start this instance with `--port 18100` (see [profiles](profiles.md)).
- **Works in a browser but not in PowerShell or a script**: the server listens on IPv4 only. Use `http://127.0.0.1:18099` instead of `localhost`.
- From another computer: use the ScoreSight computer's IP address and allow ScoreSight through its firewall.

## Recognition problems

### Wrong or unstable readings (#30)

Readings come from the picture, so start there ([#30](https://github.com/royshil/scoresight/issues/30) is a good example of a low-contrast stadium board):

1. Look at the box in **Binary View**. Digits must be solid and clearly separated from the background.
2. Crop to the scoreboard and use **4-corner** for angled cameras.
3. Set **Binarize** to **Local** or **Adaptive** for low-contrast boards or dark surroundings.
4. Set the **Type** and a strict **Format** so impossible values are rejected.
5. Use **Remove leading 0s** for zero-padded scores, and consider one box per digit for very poor boards.
6. Try another **OCR model** (under **All boxes**, in the Box tab).

The full method is in [Recognition Tuning](recognition-tuning.md).

### Readings are yellow even though they look right

The reading failed the box's **Format** (the raw text didn't fully match) or the **Conf. Th** confidence threshold. Check the [format](box-settings.md#format): for example *Period 1-4* rejects an overtime period `5` (choose *Period d*), and *Time mm:ss.d* rejects a clock that shows the tenths after a colon below a minute, `59:8` (choose *Time mm:ss or ss:d*). The confidence threshold is off (0) by default; if you raised it, lower it or set it back to 0. With Tesseract, correct readings of real scoreboards often have a confidence of only 30–50 %; with PP-OCR, 80–90 % is a good threshold. See [Conf. Th](box-settings.md#conf-th-confidence-threshold).

### Digits appear on a blank box

ScoreSight 0.1.x could read digits on an empty area, such as an unlit digit position. ScoreSight 0.2.0 doesn't run the OCR on a blank image, so such a box reads as empty (**∅**). If you still see invented digits, the area isn't really blank in **Binary View**: try another **Binarize** method or raise **Cleanup**.

## Performance problems

### Low Frames/s, Updates/s or Previews/s (#20)

([#20](https://github.com/royshil/scoresight/issues/20))

- **Previews/s ≈ 1 is by design**: the preview refreshes once per second to save CPU. It doesn't affect readings. For a picture that moves like video, turn on **View > Smooth preview** (up to 20 previews per second, at some CPU cost).
- **Updates/s** follows the **Detections / s** slider (default 5, maximum 15). Raise the slider if you need more.
- **Frames/s** is capped at about 33. Lower values mean the source delivers fewer frames or the CPU is busy with OCR. Reduce the number of boxes, crop the picture, enable **Skip Similar Image**, and lower the camera resolution.

See [Performance Tuning](performance.md).

### Video freezes when Detections / s is at 1 (#53)

In ScoreSight 0.1.x, setting **Detections / s** to 1 stopped all processing, and the UI could stay disabled after a restart ([#53](https://github.com/royshil/scoresight/issues/53)). This is fixed in 0.2.0: the first frame is shown and read right away, and the preview refreshes about once a second at any detection rate. On older versions, set the slider to 2 or higher.

### The window is slow or freezes when a vMix/UNO/API target is offline

Fixed in 0.2.0: outputs send in the background with timeouts. On older versions, stop vMix/UNO and disable the API output when the target is offline.

## Other problems

### OCR training data goes to the wrong folder (#52)

In 0.1.x, a changed **Save Folder** in **OCR Training Data Setup** was ignored ([#52](https://github.com/royshil/scoresight/issues/52)). This is fixed in 0.2.0: the chosen folder is used and remembered. See [OCR Training Data](data_annotation.md).

### The interface is too light or hard to read (#50)

Use **View** > **Appearance** to choose **Dark**, **Light** or **System** (follow the operating system) ([#50](https://github.com/royshil/scoresight/issues/50)). The choice is remembered.

### Two cameras at once (#8)

Run two instances with different profiles and ports, for example `--profile shotclock --port 18100`. See [Multiple Instances & Profiles](profiles.md) and [#8](https://github.com/royshil/scoresight/issues/8).

### Antivirus or SmartScreen warnings (Windows)

Antivirus heuristics sometimes flag PyInstaller apps as false positives, especially unsigned ones (releases before 0.3.2, after which the installer and the app are code-signed by Roy Shilkrot) and new releases. Download only from the [Releases page](https://github.com/royshil/scoresight/releases/latest) and [verify the checksum](INSTALL.md#verify-your-download-recommended). Then allow that specific file (don't disable your antivirus), and report the false positive to your antivirus vendor. See [Installation](INSTALL.md#if-your-browser-or-antivirus-blocks-the-download).

### Linux: "Could not load the Qt platform plugin xcb"

Packages older than 0.2.0 may not include `libxcb-cursor0` and the other xcb libraries Qt needs (0.2.0 includes them). Update ScoreSight, or install the X11/xcb runtime libraries, for example on Debian/Ubuntu `sudo apt install libxcb-cursor0 libxkbcommon-x11-0 libegl1`.

### Start over with clean settings

1. Optionally use **File > Export field layout...** to keep your boxes.
2. Quit ScoreSight.
3. In the [settings folder](configuration.md#where-scoresight-keeps-its-files), rename `scoresight.json` (or `scoresight-<profile>.json` for a [profile](profiles.md)), for example to `scoresight.json.old`. Don't delete the folder: it also holds your other profiles and, in its default location `ocr_training_data/`, your OCR training data.
4. Start ScoreSight. It starts with defaults.

### Still stuck?

Ask in [Q&A](https://github.com/royshil/scoresight/discussions/categories/q-a), in ScoreSight's Discussions: other users and the developers answer there (in the app: **Feedback**, at the right end of the status bar). If it looks like a bug, [open an issue](https://github.com/royshil/scoresight/issues/new/choose). The bug report form asks for your version, OS, source type, outputs and logs, which is everything needed to help you.
