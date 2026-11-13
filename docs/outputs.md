---
title: Outputs
nav_order: 4
has_children: true
description: "Overview of every ScoreSight output: text files, the HTTP server, OBS, vMix, overlays.uno and outbound HTTP requests."
---

# Outputs

ScoreSight can publish its readings to several destinations at the same time. The **Outputs** tab of the inspector, on the right of the main window, lists them with a row for each one: select a row to show that output's settings under the list. Drag the divider between the list and the settings to give the settings (for example a mapping table) more room.

<a href="https://youtu.be/tKA6UBqcDC0" target="_blank" rel="noopener"><img src="videos/08-outputs.jpg" width="45%" alt="Video: Outputs: the built-in HTTP server, JSON and text files (3:23)"/></a>

| Output | In the Outputs list | Direction | Sends | Best for |
|---|---|---|---|---|
| [Text, CSV & XML files](text-files.md) | **Text files** | ScoreSight writes files | `<Box Name>.txt`, `results.csv`, `results.xml`, `results.json`, `results.txt` (key=value) | Any software that reads text files: OBS text (from file), Wirecast, vMix Data Sources, NewBlue, XPression, SuiteCG, Excel |
| [HTTP server](http_server.md) | **HTTP server** | Other software pulls from ScoreSight | HTML, JSON, XML, CSV on port 18099, and the [game](game.md) at `/game` | Browser sources, web overlays, data feeds (vMix Data Sources, XPression DataLinq, SuiteCG, Captivate), scripts, Home Assistant |
| [Team Performance](team-performance.md) | **Team Performance** | Team Performance pulls from ScoreSight | Match time as `minute` / `second`, shot clock as `time`, object or array | Timing devices in Team Performance; no separate bridge |
| [Browser overlays](overlays.md) | **HTTP server** | ScoreSight serves pages and pushes each change to them | Transparent scorebug, lower third, clock, field and your own HTML | OBS, vMix, Wirecast, CasparCG, TriCaster, Magewell, Pearl: anything that shows a web page as graphics |
| [OBS Studio](obs.md) | **OBS** | ScoreSight pushes over the OBS WebSocket | Text of OBS text sources | OBS scoreboards without browser sources |
| [vMix](vmix.md) | **vMix** | ScoreSight pushes to the vMix Web API | `SetText` on title fields | vMix GT titles |
| [Overlays.uno](uno.md) | **UNO** | ScoreSight pushes to the UNO control app API | Commands / overlay fields | overlays.uno graphics |
| [Outbound HTTP API](out_api.md) | **HTTP API** | ScoreSight pushes to your URL | JSON, XML, CSV or GET query, per cycle or per field, with presets | Your own server, cloud functions, automations, TriCaster DataLink, Epiphan Pearl, NewBlue Captivate |
| [TCP / UDP](tcp-output.md) | **TCP / UDP** | ScoreSight pushes over a TCP connection, UDP or a WebSocket, or programs connect to its TCP server | Text lines from a template (or JSON messages over a WebSocket), with presets | CasparCG (AMCP), Chyron PRIME, Live Score, MagicSoft CG, Vizrt Viz Engine, programs that connect to their data source, your own WebSocket server, custom line protocols |
| [Works With…](integrations.md) | (uses the outputs above) | | | 33 broadcast, streaming and graphics products, with their status and setup guides |
| [Other software](other-software.md) | (uses the outputs above) | | | NewBlue Captivate/Titler Live, CasparCG, Streamlabs, Home Assistant and more |

{: .new }
In ScoreSight 0.1.x, each output had a tab (*Text Files*, *Browser*, *OBS*, *VMix*, *UNO*, *API*) and showed no status. The settings on each output's page are the ones of its old tab.

## Is it working? The Outputs list and the status bar

Each row of the **Outputs** list shows:

- **A switch** that turns the output on or off. It works the output's own control, which stays where it was: **Start vMix**, **Start sending** (UNO), the API checkbox, **Connect OBS** / **Disconnect**, and choosing or clearing the files' folder. The HTTP server has a dashed switch: it is always on.
- **The output's state**, as a symbol and a short line that says what is happening, for example *Connected to localhost:4455*, *Can't reach 192.168.1.40:8088 · retrying* or *HTTP 401: vMix asks for a login*.
- **When it last delivered something** (*3 s ago*): the last value sent, the last file written, or the last request to the HTTP server.

| Symbol | State | Meaning |
|---|---|---|
| ● (green) | Working | The output is on and delivering |
| ◐ | Waiting | On, but nothing was sent yet: connecting, or waiting for a value that changed |
| ▲ (orange) | Retrying / needs attention | The target can't be reached and ScoreSight retries by itself, or some fields fail, or a setting is missing (no URL, nothing mapped) |
| ■ (red) | Not working | Needs you: a wrong port or password, a refused URL, a folder that's gone, a busy HTTP port |
| ○ | Off | Turned off, or not connected |

The shape tells the state, so you don't need to tell the colours apart. Hover a row for the full status, what to do about a problem and the technical error. When the selected output has a problem, a box over its settings says what's wrong and what to do.

The **status bar** at the bottom of the window repeats the state of every output: *Outputs: ● Files ● HTTP ○ OBS ▲ vMix ○ UNO ● API*. Click one to show its settings. So during a game, a glance at the status bar tells you whether your graphics are receiving the readings, without opening the log.

The status never shows secrets: for UNO only the host (`app.overlays.uno`) appears, never the token in its URL, and keys in an API URL are hidden.

Use the arrow keys to move through the list and **Space** to turn the selected output on or off.

## Which readings are sent?

Every detection cycle produces one reading per box, in one of four **states**:

| State | Meaning | In the viewer |
|---|---|---|
| `Success` | A new value was read | **✓** (green) |
| `SameNoChange` | The same value as the box's last good reading: with **Update on change** on, for a box whose OCR was skipped by [Skip OCR while image is unchanged](box-settings.md#skip-similar-image), and for a [template field](boxes.md#template-fields) whose text didn't change | **=** (grey) |
| `FailedFilter` | Something was read but it failed the box's Format or confidence threshold | **!** (amber) |
| `Empty` | Nothing was read | **∅** (red; 0.2.0 showed `EMP`) |

`Success` and `SameNoChange` are the **good** readings. An `Empty` reading isn't sent, so the outputs keep the box's last value while the board blanks out; for a value that should disappear from the outputs when it disappears from the board (a penalty timer), set the box's [When blank](box-settings.md#when-blank) to *Clear the value*. [Template fields](boxes.md#template-fields) follow the same rules: `Success` when their text changes, `SameNoChange` when it doesn't, and `Empty` until every box they use has had a good reading.

Each output treats states differently:

| Output | What is sent |
|---|---|
| Text files | The latest good value of each box. A file is rewritten when its content changes (or the file is missing), at most **Save / s** times per second |
| HTTP server | Always the latest reading of every box, including its state. The `?pivot` endpoints include only good values |
| OBS | A box's good value whenever it differs from the text last sent to its OBS text source. Sent right away, not limited by **Save / s**, and no output folder needed |
| vMix, UNO | New values (`Success`). With **Also resend unchanged values** (was **Send Same?**), unchanged values (`SameNoChange`) are resent too. Fields with an empty mapping are skipped |
| TCP / UDP | A field's good value when it differs from the last one sent (every good value with **Also resend unchanged values**). With **One message with every field**, each change sends every field's last good value. Fields with an empty name are skipped |
| Outbound HTTP API | *JSON (Full)*, *XML* and *CSV*: every reading of every box on every cycle, so the receiver should check the state. *JSON (Simple key-value)* and `GET`: only the good readings |

## Global controls that affect outputs

- **Pause outputs** (at the top of the field list, or **Ctrl+Shift+P**) freezes all outputs at their current values until you click **Resume outputs**. The field list in ScoreSight keeps updating, so you can watch the readings without sending them. While the outputs are paused, the button is orange, a banner over the picture says since when (with its own **Resume outputs** button), the values in the field list are marked *not sent*, the window title starts with ⏸ and the status bar shows **PAUSED** with the time. When you resume, vMix and UNO get each box's next good value even if it is unchanged, so values that changed while paused reach them. (In ScoreSight 0.1.x this button was called **Stop Updates**.)
- **Update on change** (on by default, under **All boxes** at the bottom of the Box tab) marks a reading that equals the box's last good value as `SameNoChange` instead of `Success`. vMix and UNO then don't resend unchanged values (unless their **Also resend unchanged values** is on), and the HTTP server and the outbound API report them as unchanged. OBS and the text files get a value only when it changes either way.
- **Hold value...** (right-click a field, or **Ctrl+H**) sends a value you type to every output instead of that field's readings, until you release it: to correct a misread or freeze one field. See [Hold value](boxes.md#hold-value).
- **Detections / s** (also under **All boxes**) sets how often new readings are produced (see [Performance Tuning](performance.md)).
- **Save / s** (on the **Text files** page) limits only how often the files are written. It doesn't slow down the other outputs.

## Network outputs run in the background

OBS, vMix, UNO, the outbound API and the TCP / UDP output send from background workers, never from the ScoreSight window itself:

- Every HTTP request has a timeout (2 seconds to connect, 2 seconds to answer). OBS has a 3-second timeout.
- If a target falls behind, only the most recent value of each field is kept, so old values never pile up.
- If a target can't be reached, ScoreSight retries with an increasing delay and sends the latest values when it is back. The OBS connection is re-established automatically.
- Any 2xx HTTP status counts as success.
- Errors are logged at most once every 30 seconds per output, with the number of errors that were not logged, and recovery is logged once, for example `vMix: connection restored`.
- The Outputs list and the status bar show the same in plain words as it happens: ▲ *retrying* while a target can't be reached, ● again once it receives the values.

{: .new }
In ScoreSight 0.1.x, a slow or unreachable target could freeze the ScoreSight window, and OBS updates only ran when an output folder was set. Both are fixed in 0.2.0.
