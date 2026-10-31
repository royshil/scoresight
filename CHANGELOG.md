# Changelog

All notable changes to ScoreSight are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Release tags are the bare version number (for example `0.1.0`).

## [Unreleased]

### Added

- **Phone camera.** A new source: an iPhone or Android phone sends its camera to ScoreSight over Wi-Fi, from its browser, with no app to install. Choose **Phone camera** in the Source list and scan the QR code the picture shows. ScoreSight serves the phone's page over HTTPS (phone browsers open the camera only on a secure page) on the port after the HTTP server's, with a certificate of its own, so the phone warns once that the connection isn't private. The phone sends a picture per detection; while none comes, the boxes aren't read ([Video Sources: Phone camera](https://royshil.github.io/scoresight/sources.html#phone-camera)).
- **Smooth preview.** **View > Smooth preview** refreshes the picture in the viewer up to 20 times a second (15 for a 30 fps source) instead of about once, so a running clock moves like video. It uses more CPU; the readings and the outputs don't change. Off by default ([#165](https://github.com/royshil/scoresight/discussions/165)).

### Fixed

- **Soccer clocks past 59 minutes.** The Time formats with minutes (*Time mm:ss.d*, the Time field's default, *Time mm:ss or ss:d* and *Time mm:ss*) took minutes 0–59, so a clock that counts up was rejected from `60:00` on and the outputs stayed at `59:59`. They now take up to three digits of minutes (`90:00`, `120:00`). Boxes that use those formats are updated once when you open this version; a custom format is kept ([#163](https://github.com/royshil/scoresight/discussions/163), [Box Settings: Format](https://royshil.github.io/scoresight/box-settings.html#format)).
- The UNO page no longer says that overlays take the match time as `mm:ss`: the Soccer Scorebug's `SetMatchTime` takes seconds. The page says what ScoreSight sends and what to do when a command takes something else ([#162](https://github.com/royshil/scoresight/discussions/162), [Overlays.uno](https://royshil.github.io/scoresight/uno.html#troubleshooting)).

## [0.4.2] - 2026-10-25

Requests and fixes from the 0.4.0 discussion: a penalty timer's value can
be cleared when it goes out, closing asks first, and clocks that show the
tenths after a colon have a format. The first release an installed Windows
0.4.1 can get with **Update now**.

### Added

- **When blank: clear the value.** A new box setting, under Filtering: when the box has shown nothing for 2 seconds, the outputs can get an empty value instead of keeping its last one, which clears the text in vMix, OBS, the overlays, the files and every other output. **Clear the value, also at zero** also clears a box that reads zero (`0`, `0:00`) for 2 seconds. For a handball or hockey penalty timer that goes out at the end of the penalty; a shorter blank (a flicker, a hand in front of the board) keeps the value ([#140](https://github.com/royshil/scoresight/discussions/140)). It replaces **Skip empty values**, which had no effect since 0.2.0.
- **Ask before closing.** Closing ScoreSight while a source is open now asks first, in both layouts, since it stops the reading and the outputs. **Don't ask again** in the question, or **File > Ask before closing**, turns it off. Stopping a headless ScoreSight (Ctrl+C, SIGTERM) and **Update now** don't ask ([#140](https://github.com/royshil/scoresight/discussions/140)).

### Fixed

- **No digits read on a dot-matrix display that is off.** The unlit LEDs of a dot-matrix display, faintly visible on camera, could be read as digits by PP-OCR: on a handball board, the penalty timer's box sent *0:10* while the operator was setting up a penalty. A box needs a bit more contrast now (30 gray levels instead of 20) before it is read, which also lets **When blank** clear such a box on time ([#140](https://github.com/royshil/scoresight/discussions/140)).
- **Auto layout's model downloads on macOS.** The first ✨ Auto crop or ✨ Auto layout on a Mac failed with *CERTIFICATE_VERIFY_FAILED*: the download didn't use the certificates bundled with ScoreSight, and the Mac app has no others. The user guide now also says where to put the model if you download it yourself ([#140](https://github.com/royshil/scoresight/discussions/140)).
- **A running clock no longer freezes after a held-back reading.** With a sport chosen, a clock reading that jumped (5:25 then 5:27 a fifth of a second later, when 5:26 was missed) was held back, as it should be, but the clock was then judged against that old value as if it had just been read, so every following second was held back too: the outputs kept the old time until the clock stopped for 3 seconds. The clock now catches up at the next reading ([#140](https://github.com/royshil/scoresight/discussions/140)).
- **A clock that shows the tenths after a colon** (`1:00`, then `59:8`, `59:7`...) stopped at `1:00` in the outputs: the default Time format accepts tenths only after a dot (`59.8`). A new Format preset, **Time mm:ss or ss:d**, accepts both; choose it for the Time box of such a board. With a sport chosen, `59:8` is now read as 59.8 seconds, not 59 minutes ([#154](https://github.com/royshil/scoresight/discussions/154)).

## [0.4.1] - 2026-10-22

Futsal, a WebSocket output, and Update now: from this version on, an
installed Windows ScoreSight updates itself to the next release in a click
(this one is still installed by hand). Lap races no longer miscount a lap
that turns two lap cards.

### Added

- **Futsal.** A new sport: the clock counts down through two halves (then extra time), goals count one at a time, and the team fouls are followed (they go back to 0 at halftime). The final comes at 0:00 of the second half. A dot-matrix 3 misread as a 9 is held back from the outputs ([#136](https://github.com/royshil/scoresight/discussions/136)).
- **WebSocket output.** The TCP / UDP output can send over a WebSocket: enter a `ws://` or `wss://` URL, and add a token in **Headers** (`Authorization: Bearer …`) or in the URL. The new **WebSocket (JSON)** preset sends a JSON object with every field each time a value changes; any template works too, for example a message per changed field. ScoreSight keeps the connection open and reconnects by itself ([#141](https://github.com/royshil/scoresight/discussions/141)).
- **Update now (Windows).** When a new version is out, the update dialog of an installed ScoreSight has an **Update now** button: ScoreSight downloads the new installer, checks it (its SHA-256 against the release's, and that it is signed by ScoreSight's publisher), installs it and starts again, with the same settings. Windows may ask to allow the installer; if you decline, or anything fails, ScoreSight keeps running. While a source is open, it asks first. The portable zip, macOS and Linux still download new versions by hand.

### Fixed

- **Lap races: a lap that turns two lap cards.** Between 20 and 19 laps to go, a board of hand-turned cards shows *10* (or *29*) until the second card is turned. When that took over 3 seconds, ScoreSight counted 10 laps at once, sent *10* to the outputs, then took 19 for a new race; from 10 to 09, the *00* in between could have made a **finish** at 10 laps to go. Such a number now counts only if the board stays that way for 15 seconds, and the next lap counts as soon as the second card is turned. Found on a velodrome's 45-lap countdown, which now gives every lap, the final lap and the finish ([#125](https://github.com/royshil/scoresight/discussions/125)).

## [0.4.0] - 2026-10-19

Set up a new source in two clicks: ✨ Auto crop finds the scoreboard, and
✨ Auto layout places the scores, the clock and the period, with ScoreSight's
own AI model running on your computer. 0.3.4 wasn't released on its own, so
this release also brings its changes (below): misreads held off the air, lap
races, team names on the overlays and the Feedback link.

### Added

- **✨ Auto crop and ✨ Auto layout.** Two new buttons with a sparkle, in violet at the start of the Adjust picture row, set up a new source in a click with AI. **Auto crop** finds the scoreboard and crops the picture to it (Reset crop undoes it). **Auto layout** finds the home and away scores, the clock and the period, and places the boxes of Home Score, Away Score, Time and Period; it asks before moving boxes you already placed. They use ScoreSight's own scoreboard model, downloaded once (42 MB, after asking) from [Hugging Face](https://huggingface.co/royshilkrot/scoreboard-layout), where its evaluation is published. It runs on your computer: the pictures aren't sent anywhere. Check what it did: it finds the scoreboard on about 9 photos in 10, and does best on close-up views.

## [0.3.4] - 2026-10-17

Misreads stay off the air: with a sport chosen, a change the sport doesn't
allow waits until it is read steadily. Also lap races, team names on the
overlays, and a Feedback link to ScoreSight's Discussions.

### Added

- **Feedback**, at the right end of the status bar, and **Help > Ask a question or share feedback** open [ScoreSight's Discussions](https://github.com/royshil/scoresight/discussions) on GitHub: ask a question, share an idea or show your setup. The first-run card links there too. Each release is now announced in Discussions.
- **Team names on the overlays.** The overlay builder (Outputs > HTTP server > Browser overlays) has a **Teams** row: type the home and away team names and they replace HOME and AWAY on the scorebug (and the Home and Away captions on the lower third). The copied address carries them (`labels=Lions,Tigers`), and they are kept for the next session.
- **Lap races.** A new sport, **Racing (laps)**, for races with one lap board everyone races to (track cycling, motorsport, skating, swimming, athletics): name the box **Laps To Go** (or **Laps Completed**, with an optional **Total Laps**) and ScoreSight notices each lap, the final lap and the finish, and a new race when the board is set again. Only one lap at a time counts at once; any other change counts once read steadily for 3 seconds, so a hand over a lap card or a card half turned makes no event. `/game` has the lap board (`laps`) and the events `lap`, `final_lap`, `finish` and `new_race`. Tried on a video of a velodrome's hand-turned lap cards ([#125](https://github.com/royshil/scoresight/discussions/125)).
- **Misreads stay off the air** ([#97](https://github.com/royshil/scoresight/issues/97)). With a sport chosen, a change the sport doesn't allow (a basketball score going from 21 to 81, a score going down, a period skipped, the clock jumping, a lap board skipping laps) is held back from every output and template field until it has been read steadily for 3 seconds: a flickered value never goes on air, and a real correction goes on air a few seconds late. Changes the sport allows go out at once, and a value set with Hold value goes out as it is. The log says what was held back and why, then whether it was sent or dropped.

## [0.3.3] - 2026-10-13

ScoreSight follows the game: choose the sport, and it notices each score,
the periods and the final buzzer. Also a TCP server for software that
connects to ScoreSight, and setup guides for 33 broadcast products.

### Added

- **Game & sports.** Choose the sport (basketball, soccer, ice hockey,
  American football, volleyball) under **All boxes**, and ScoreSight follows
  the game from the scoreboard: each score (who scored and how many points),
  the start and the end of each period, the clock starting and stopping,
  fouls and timeouts, the final buzzer, and the points of each period. A
  change is counted only once it is read again, and a change the sport
  doesn't allow (a basketball score jumping by 5, a score going down) only
  once it is read steadily for 3 seconds, so misreads make no events. The
  game is served at `/game` on the HTTP server, with its event log. It is
  the base for the graphics, highlights and player stats on the
  [roadmap](https://github.com/royshil/scoresight/issues/116).

- **TCP server.** The TCP / UDP output can now wait for other programs to
  connect to ScoreSight, for software that connects to its data source
  instead of listening: choose **TCP server** next to the port. Up to 32
  programs can connect at once; each one gets the "on connect"
  message and every current value, then each change. The Outputs list shows
  how many are connected, and says when the port is taken by another
  program. Try it with `telnet` or `nc`.

- **Reset crop.** The crop panel has a **Reset crop…** button: after you
  confirm, it removes the crop (its four values go back to 0 and cropping
  turns off), so the whole picture is read again. The boxes move with it and
  stay over the same digits.

### Changed

- **Works With… covers 33 products.** The
  [Works With…](https://royshil.github.io/scoresight/integrations.html)
  section of the documentation is now a section of its own, with a setup
  page for each product that has a documented way in: new guides for
  CharacterWorks, PlayBox TitleBox, XSplit Broadcaster, Livestream Studio
  and MagicSoft CG, and its own page for each of the earlier ones. Chyron
  LYRIC, ClassX LiveBoard, wTVision, Nemo3D and others are listed with what
  is known about them. The MagicSoft CG steps now say to use the port set
  in MagicSoft's Socket communication tab (its defaults are 2610 to 2643).

## [0.3.2] - 2026-10-12

Signed Windows downloads, and video tutorials in the documentation.

### Added

- **Video tutorials.** Short videos, from installing ScoreSight to each
  output, are at the top of the matching pages of the
  [documentation](https://royshil.github.io/scoresight/).

### Changed

- **Signed Windows downloads.** The installer, its uninstaller and
  `scoresight.exe` (also in the portable zip) are code-signed by Roy
  Shilkrot, so Windows names the publisher instead of "Unknown publisher".
  SmartScreen may still warn about a new release until enough people have
  downloaded it.

## [0.3.1] - 2026-10-11

The new logo, and two fixes: shot clocks that drop the leading zero are read
to the end again, and the field list keeps its row heights after the Live
layout.

### Changed

- **A new logo and app icon.** An amber seven-segment "S" inside the corner
  brackets of a viewfinder, the box ScoreSight draws around the digits it
  reads. It is used for the app icon on Windows and macOS, the window icon
  (now on Linux too), the installer, the Windows splash screen, the README
  and the documentation site (with a favicon). `brand/` has the masters and
  makes every file (`brand/make_assets.py`).

### Fixed

- After going back from the Live layout to the Setup layout, the fields that
  aren't on the picture kept the Live layout's taller rows in the field list.
- The **Shotclock 0-39** and **Time 0-59** formats took exactly two digits,
  so a shot clock that shows `9`, `8`, ... `0` without a leading zero failed
  the filter, and the outputs stayed at `10` for the last ten seconds of
  every shot clock. They now take one or two digits (the Shot Clock field
  uses Shotclock 0-39 by default). Boxes saved with the old formats, in the
  settings or an exported configuration, are updated once when loaded
  (`boxes_schema_version` 3); other formats are kept.

## [0.3.0] - 2026-10-11

A new OCR engine, live overlays, and many more broadcast products. Highlights:

- **PP-OCR, a much more accurate OCR engine.** PaddleOCR's PP-OCRv6 models
  read 95% of real scoreboard crops exactly in our evaluation, against 31%
  for Tesseract with its default settings. **PP-OCR (automatic)** is the
  default for new setups: it uses the accurate model, and switches to the
  fast one (90%) when the computer can't keep up, and says so. Existing setups
  keep their Tesseract model until you choose another. OCR also runs on its
  own thread now, so a slow reading can't make a live stream fall behind.
- **Live browser overlays.** ScoreSight serves transparent scorebug, lower
  third, clock and field pages that update the moment a value changes, for
  OBS, vMix, Wirecast, CasparCG, TriCaster, Magewell, Pearl and anything else
  that shows a web page. Bring your own HTML with `data-field` attributes. The
  HTTP server's page builds the URLs.
- **More broadcast products.** A **TCP / UDP output** with presets for
  CasparCG (with a ready template), Chyron PRIME, Live Score, MagicSoft and
  Vizrt; **TriCaster DataLink** and **Epiphan Pearl** presets for the
  outbound API; and a **Works with…** page covering 21 products with setup
  guides.
- **Draw a field's box right on the picture**: select a field, then drag
  over its numbers. **Drag to crop** works the same way, and boxes stay on
  their digits when the crop changes.
- **Fixes** for Create OBS Scene (it could delete sources other scenes used),
  overlays.uno (values lost when it throttled ScoreSight), and vMix (spaces
  sent as `+`).
- The whole window is translated into 12 languages (machine drafts so far:
  corrections from native speakers are welcome).

### Added

- **PP-OCR**, a second OCR engine next to Tesseract: PaddleOCR's PP-OCRv6
  text recognition models, run with ONNX Runtime and bundled with the app
  (Apache-2.0). On 2,040 real scoreboard crops (the
  [OCR evaluation](docs/development/ocr-eval.md)) PP-OCR (accurate) reads 95%
  of the values exactly and PP-OCR (fast) 90%, against 31% for Tesseract's
  General Scoreboard and 46% for the best Tesseract setup. Three choices lead
  the **OCR model** list:
  - **PP-OCR (automatic)**, the default for new setups: reads with accurate
    while the computer keeps up with **Detections / s**, and switches to fast
    when accurate needs more than 70% of the time between detections for 3
    seconds (and back when it would need less than half for 10 seconds). The
    list shows which one it uses, and its tooltip and the status bar's
    reading rate say why ("accurate needs 160 ms per reading here...").
  - **PP-OCR (accurate)** (PP-OCRv6 small): the most accurate, about five
    times the CPU of fast: most of a fast desktop core at 10 boxes read 5
    times a second, more than a laptop core can give.
  - **PP-OCR (fast)** (PP-OCRv6 tiny): for many boxes, high Detections / s or
    slower computers.
  PP-OCR reads each box's colour picture as it is, all the boxes of a frame
  at once, with only the characters of the box's **Type**; its confidence is
  reliable (80–90% as **Minimum confidence** rejects most wrong readings).
  The format, confidence, smoothing, leading-zero and ordinal settings work
  as before, and so does every output.
- When an explicitly chosen PP-OCR (accurate) can't keep up with Detections /
  s, the reading rate's tooltip and a one-time message suggest PP-OCR (fast)
  or fewer detections, with a button to switch. The model never changes on
  its own (except with PP-OCR (automatic)).
- The status bar says *Loading PP-OCR…* while the model loads (in the
  background, a fraction of a second; startup isn't slower), and says so if
  PP-OCR can't load, in which case Tesseract's General Scoreboard reads.
- `scripts/fetch_models.py` downloads the PP-OCR models for running from
  source and for builds (pinned revisions, checked against SHA-256s).
- The OCR evaluation measures the app's own PP-OCR engine (`ppocr-app`), and
  CI fails if its accuracy drops.
- **TCP / UDP output** for graphics systems that take text over a socket: a
  **TCP / UDP** row in the Outputs list, with presets for CasparCG (AMCP
  `CG ADD` and `CG UPDATE`, with a bundled HTML scorebug template and Play /
  Stop buttons), Chyron PRIME (Intelligent Interface `P\UPDATE`), Live Score
  (its Scoreboard OCR input), MagicSoft CG (`[name]=value`) and Vizrt Viz
  Engine (Shared Memory `key|value`), and a template for any other line
  protocol. It keeps a TCP connection open and reconnects by itself (or sends
  UDP datagrams), sends an optional "on connect" message, and has options for
  the line ending, the encoding, the escaping, changes only, a minimum interval
  and a periodic resend. Its status shows the connection and the receiver's
  answers (an AMCP error such as `404 CG ERROR` turns it orange), and the page
  previews what is sent. The presets haven't been tested with the real
  products yet; the Live Score and MagicSoft formats come from another
  vendor's public documentation. See the
  [TCP / UDP output](https://royshil.github.io/scoresight/tcp-output.html) page.
- **Browser overlays** served by the HTTP server, for any software that shows
  a web page as graphics (OBS, vMix, Wirecast, CasparCG, TriCaster, Magewell
  Director, Epiphan Pearl...): a transparent scorebug, lower third, clock and
  single field at `/overlay/...`, with fields, labels, theme, colours, font,
  position, layout, scale and animation set in the address. Values are pushed
  live (Server-Sent Events at `/events`, a JSON snapshot at `/overlay/state`
  for polling) and the pages reconnect by themselves. Put your own HTML in the
  `overlays` folder of the settings folder (it comes with an example): it is
  served at `/overlay/custom/...`, and `/overlay/client.js` fills its
  `data-field` elements and fires events. **Outputs > HTTP server** builds an
  overlay's address with Copy and Open in browser. See
  [Browser Overlays](docs/overlays.md).
- **Draw a field's box on the picture.** Select a field that isn't on the
  picture: the pointer turns into a crosshair, a hint says *Drag over the
  numbers to place Home Fouls*, and a drag over the digits puts the box exactly
  there, at any zoom, selected and with its settings shown. A drag of a few
  pixels counts as a click, **Esc** cancels, and clicking another box still
  selects that box. It works in the Setup and the Live layout.
- A double-click on a field that isn't on the picture puts its box in the
  middle of the part of the picture you see; a double-click on the picture
  puts the selected field's box there. A double-click on a custom field on the
  picture still renames it, as the fields' tooltips say.
- **Alt+drag** (**⌥ Option+drag** on macOS) on the picture draws the selected
  box again.
- A right-click on a box on the picture opens its menu: **Remove from
  picture**, **Rename...**, **Hold value...** and **Zoom to box**.
- **Drag to crop** in the crop panel: the viewer shows the whole picture
  (without the crop, so that it can also be made wider), and a drag around the
  scoreboard sets the four crop values. **Esc** keeps the current crop. The
  values stay for fine-tuning, and now go up to 9999 pixels for large
  pictures.
- **Works with…**: a docs page listing 21 broadcast products (Wirecast,
  NewBlue Captivate, Ross XPression, SuiteCG, TriCaster, Epiphan Pearl,
  CasparCG, Singular.live, Chyron PRIME and more), how well each works, and
  setup guides.
- **Outbound HTTP API**: **Only changes** (and **Resend all** every N s),
  **Fields per request**, one request per field with `{field}` and `{value}`
  in the URL, a **Rate** limit, names with letters, digits and `_` only,
  custom **Headers** (for example an `Authorization` token), and Digest
  logins. The defaults send as before.
- **Presets** for the outbound API: **TriCaster DataLink** (a DataLink key
  per field) and **Epiphan Pearl** (custom variables, 6 per request, at most
  5 requests a second). Both untested on the hardware so far.
- **HTTP server**: `?pivot&all` on `/json`, `/xml` and `/csv` gives every
  field with its last good value, so columns never come and go, and
  `/json?array` gives it as an array of one row, the shape vMix JSON Data
  Sources expect (untested with vMix). Responses are never cached, and a page on a public site may
  read a ScoreSight on the local network. The existing URLs answer as before.
- **Text files**: optional `results.json` (one object) and `results.txt`
  (`key=value` lines), for SuiteCG and similar.
- **overlays.uno**: the calls left today are shown, and calls are spaced out
  to stay under the per-minute limit overlays.uno reports.

### Changed

- **Existing setups keep their Tesseract model**; the Tesseract models are now
  listed as "Tesseract: General Scoreboard" etc., after the PP-OCR ones, and
  **Load external model...** is **Load external Tesseract model...**.
- While a PP-OCR model reads, the Box tab's **Image cleanup** settings are
  disabled (and kept): they prepare the picture for Tesseract, and PP-OCR
  reads it better as it is. They stay available for a box that counts lights.
- The OCR runs on a thread of its own: a slow OCR model no longer holds up the
  video. Live camera and stream pictures stay current (before, with an OCR
  taking 170 ms per reading, a stream's readings fell seconds behind the
  picture), a video file plays at normal speed, and each reading is made from
  the latest frame.
- **Binary view** shows a PP-OCR box's picture in gray: what PP-OCR reads.
- `--self-test` also reads its test image with every PP-OCR choice.
- The Windows app is 66 MB larger (onnxruntime and the two models).
- **The boxes move with the crop.** Changing the crop's left or top edge (with
  **Drag to crop**, the **Left** and **Top** values, or turning **Crop** on or
  off) used to leave every box over other pixels. The boxes, and the corners of
  a 4-corner correction, now move with it and stay over the same digits. A box
  left entirely outside the cropped picture keeps its place (a wider crop
  brings it back), and a line under the crop panel names it.
- **Del** takes the selected field's box off the picture (asking first only
  when you changed its settings, as **Remove from picture** does), in the field
  list and on the picture. For a custom field that isn't on the picture, it
  deletes the field, as before.
- **Place on picture** puts the box in the middle of the picture you see
  instead of its top-left corner. It and **Remove from picture** are now quiet
  link-style buttons under a line that says what to do with the selected
  field, for example *Drag on the picture to place it, or double-click the
  field*. The first-run card's second step says *Select a field, then drag
  over its numbers on the picture*.
- **Help > Keyboard shortcuts** lists the new mouse actions.

### Fixed

- With the **All** box display style, the area read and the characters found
  were drawn in the wrong place on a box moved with the arrow keys (and now
  with the crop or drawn again).
- **Create OBS Scene** with **Recreate** deleted every source of the scene
  from the whole OBS scene collection, including sources other scenes
  shared. It now removes only the scene's items, and deletes a source only
  if ScoreSight made it and nothing else uses it.
- **overlays.uno** dropped a value refused with HTTP 429 (too many
  requests), so a score could stay wrong on air until it changed again. The
  latest value of each field is now kept and sent when the limit resets
  (the outbound API does the same). Custom fields no longer get a command
  named after themselves by default, which overlays answered with HTTP 400
  while it still counted against the daily limit.
- **vMix** and the outbound API's `GET` sent spaces as `+`, which vMix and
  other receivers may show literally. They are now sent as `%20`.
- The vMix docs recommended `/json?pivot` as a vMix JSON Data Source, which
  vMix can't read: they now recommend `/json?array`, `/xml?pivot&all` or
  `/csv?pivot&all`.
- The outbound API no longer writes the password of a URL login to the log.

## [0.2.0] - 2026-10-10

ScoreSight is actively maintained again. This release modernizes the whole
stack, redesigns the window, fixes the most reported problems, and is tested
end to end on every platform before it ships. Highlights:

- **A redesigned window.** The field list with large live values, the picture
  and a settings panel (**Box** and **Outputs**) side by side, and a **Live
  layout** (Ctrl+2) for game time. Each output (text files, HTTP server, OBS,
  vMix, UNO, HTTP API) has an on/off switch and a live status that says what
  is wrong and what to do ("vMix: no answer from 192.168.1.40:8088 ·
  retrying"). **Pause outputs** says that it is paused everywhere, 4-corner
  correction no longer throws away the previous one by accident, a first-run
  card walks through the three steps, and **Hold value** (Ctrl+H) sends a
  typed value instead of a misread one until you release it. The window fits
  a 1366×768 laptop. Nothing was removed: every setting has a place.
- **Starts in 1 to 2 seconds**, 3 to 6 times faster than 0.1.0, measured on
  every platform in CI (on an Intel Mac, 2.0 s against 0.1.0's 12.9 s; users
  reported up to 30 s before).
- **The whole window is translated** into 12 languages (machine drafts so far:
  corrections from native speakers are welcome).
- **Outputs never freeze the window**, whatever vMix, UNO, OBS or an API
  endpoint do, and the OBS text source of each field can be edited in place.
- **Fewer crashes:** an intermittent native crash and a race that lost the
  first readings of a source are fixed, and a crash now leaves a trace in the
  log.
- **Profiles** (`--profile`) and `--port` for running several instances
  side by side, and `--self-test` to check an installation.
- Downloads for Windows (installer and portable zip), macOS (Apple Silicon and
  Intel) and Linux, with `SHA256SUMS.txt`.

### Added

- Profiles for running several ScoreSight instances side by side, for example
  one per camera ([#8](https://github.com/royshil/scoresight/issues/8)):
  - `--profile NAME` (or the `SCORESIGHT_PROFILE` environment variable) uses
    the settings file `scoresight-NAME.json` instead of `scoresight.json`. The
    window title shows the active profile.
  - `--port N` serves the HTTP API on port `N` instead of 18099. The
    **Browser** tab shows the links for the port in use.
- `--self-test` command-line option: a headless check of the installation
  (all modules, the bundled files, the main window and every bundled OCR model
  reading a test image) that prints `SELF-TEST OK` and exits with code 0.
- Ctrl+C, `SIGTERM` and Ctrl+Break (Windows) quit ScoreSight cleanly, saving
  the boxes and stopping the HTTP server, even with a dialog open. This is how
  to stop an instance that runs without a window (`-platform offscreen`). On
  Windows, such an instance attaches to the Command Prompt or PowerShell
  window it was started from, so that Ctrl+C and Ctrl+Break reach it.
- The log shows how long each start took: a `Startup:` line with the time of
  each startup phase (until the app's code runs, loading its modules, building
  the window) and when the HTTP server and the video sources were ready, to
  diagnose a slow start ([#33](https://github.com/royshil/scoresight/issues/33)).
  The `SCORESIGHT_STARTUP_REPORT` environment variable also writes these times
  to a JSON file.
- If ScoreSight crashes in a library (Qt, OpenCV, Tesseract...), the
  `scoresight_std_` log shows where: what every part of the program was doing
  at that moment. Before, such a crash left no trace.
- **View > Appearance** with System, Light and Dark colour schemes,
  remembered between runs ([#50](https://github.com/royshil/scoresight/issues/50)).
- **Help > Check for updates...** checks GitHub Releases and always shows the
  result. The check at startup shows a dialog only when a newer version
  exists, and can be turned off in that dialog.
- A `/csv?pivot` endpoint on the built-in HTTP server: a header row with the
  box names and one row with their current good values.
- `SCORESIGHT_DATA_DIR` and `SCORESIGHT_LOG_DIR` environment variables to move
  the settings and log folders.
- A damaged settings file is now backed up as `<name>.corrupt-<timestamp>`
  instead of being silently replaced by defaults.
- Release downloads for every platform, each with the version in its file
  name: a Windows installer and a portable zip, macOS disk images for Apple
  Silicon and Intel, and a Linux `.tar.gz`, plus `SHA256SUMS.txt` for verifying
  them.
- Every packaged build is tested with `--self-test` on Windows, macOS and
  Linux before it is released, and the Windows installer is test-installed.
- Every packaged build (and the app from source, on every pull request) is
  also run end to end: headless, it reads a test scoreboard video and its
  readings must reach the HTTP server, the files and the outbound API. Its
  startup time is measured and compared with 0.1.0 on each platform.
- New documentation site at <https://royshil.github.io/scoresight/>:
  quickstart, installation (including the portable version, macOS permissions
  and Linux), video sources (including RTSP,
  [#10](https://github.com/royshil/scoresight/issues/10)), boxes and template
  fields, a per-box settings reference, recognition and performance tuning
  guides ([#20](https://github.com/royshil/scoresight/issues/20),
  [#30](https://github.com/royshil/scoresight/issues/30)), an HTTP API
  reference, file, OBS, vMix, UNO and outbound API guides, troubleshooting,
  FAQ and a developer guide.
- `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, GitHub issue forms and
  a pull request template.
- For contributors: an automated test suite (pytest) and linting/formatting
  (ruff) in continuous integration, pre-commit hooks, Dependabot updates,
  `scripts/compile_ui.py` to compile the Qt Designer files on every platform,
  `scripts/update_translations.py` to refresh the translation sources from
  `src/` only, and `scripts/bump_version.py` to prepare a release.
- For contributors: an OCR evaluation (`ocr_eval/`, see the developer guide)
  that measures OCR engines on 2,320 real scoreboard crops from openly
  licensed photos, and checks in continuous integration that changes to the
  recognition don't make it worse. Its first report compares ScoreSight's
  Tesseract setup with PaddleOCR, docTR's recognizers, the Windows OCR and
  small vision-language models.
- A status bar: the source with its resolution and frame rate, how many times
  per second the boxes are read against the **Detections / s** setting (orange
  when the computer can't keep up), **PAUSED** while the outputs are paused,
  and the HTTP server's address on your network with a **Copy** button.
- Keyboard shortcuts: **Ctrl+Shift+P** pauses and resumes the outputs,
  **Ctrl+B** toggles **Binary View**, **Ctrl+0** fits the picture to the
  window and **F5** reloads the sources (**⌘** on macOS). The buttons'
  tooltips show them.
- Every slider shows its value next to it (*Off* when the setting is off), and
  every control has a tooltip.
- The outputs show whether they work. The **Outputs** list has a row for each
  output with an on/off switch, a symbol for its state (● working, ◐ waiting,
  ▲ retrying or needs attention, ■ not working, ○ off) and a line about what
  is happening, for example *Connected to localhost:4455*, *Can't reach
  192.168.1.40:8088 · retrying* or *HTTP 401: vMix asks for a login*, with
  the time it last sent something. When the selected output has a problem, a
  box over its settings says what to do. The status bar shows the state of
  every output, and a click on one shows its settings. The documented problems
  are explained in plain words: vMix on its TCP API port 8099, a vMix login,
  an overlays.uno URL that is refused or rate-limited (HTTP 429), a wrong OBS
  password, a missing OBS text source, an unreachable target, a busy HTTP port
  and a missing output folder. The UNO URL's token and keys in an API URL are
  never shown.
- **Disconnect** for OBS. After it, ScoreSight keeps the connection settings
  but doesn't connect to OBS at its next start until you connect again. The
  connect button shows **Change connection...** while connected, and a failed
  connection says why (in the dialog and in the Outputs list).
- The HTTP server's page shows its address for other computers on your
  network, and its row in the Outputs list shows how many computers or
  programs read it.
- The field list has a context menu: **Place on picture** or **Remove from
  picture**, **Rename...** (**F2** or a double-click), **Delete field...**
  (**Del**), **Reset settings to defaults**, **Copy value** (**Ctrl+C**, the
  last good reading) and **Zoom to box**. **Ctrl+N** adds a custom field.
- **Insert field** next to a template adds another field to it, spelled
  exactly as the template needs it.
- The **Format** list always shows the preset the expression matches (or
  *Custom*), instead of going back to *Select Preset*. An expression that
  isn't a valid regular expression is shown in red with *Not a valid
  expression, so it is ignored* (the OCR accepted every reading without a
  word), and its tooltip says what is wrong.
- The source shows whether it works. The **Source** drop-down names what's
  open (*Video file: final.mp4*, *Stream: rtsp://...* without the password,
  *Screen: ...*, with the full path or address in its tooltip), and a dot
  before it tells its state: ● frames arrive, ▲ opening, slow, stalled or
  reconnecting, ■ failed. When a source can't be opened or read, a red banner
  says why and what to do, with **Retry**, **Choose another source** and
  **Troubleshooting** (it replaces the large red "Unable to play video stream"
  over the picture). On macOS, a screen capture without the Screen Recording
  permission says so, with **Open System Settings**.
- A first-run card in the viewer while no source is open: **Choose a source**
  (Camera, Video file…, Stream URL…, Screen…), **Place fields** and **Send
  them**, each with a check mark once done, and a link to the 5-minute
  Quickstart.
- The selected box moves with the arrow keys, by 1 pixel or by 10 with
  **Shift**.
- Zoom with **Ctrl+=** and **Ctrl+-**, with the zoom level shown next to
  **Fit**.
- **View** and **Tools** menus with the view tools, **Pause outputs**,
  **Reload sources** and the OCR training data, showing their shortcuts.
- **Setup** and **Live** layouts (**View** menu, **Ctrl+1** and **Ctrl+2**),
  remembered between runs. The Live layout is for the game: the inspector
  is hidden, the field list is wider with the values in large type, the
  fields that aren't on the picture are hidden (**View > Show unused
  fields**, remembered for each layout), and the outputs are listed under
  the readings with their state, one line each. The **Adjust picture** row
  is hidden. The reading and the outputs work the same in both layouts, and
  the Setup layout gets its widths back.
- **Hold value...** (right-click a field, or **Ctrl+H**; **⌃H** on macOS):
  every output and template field gets a value you type instead of the
  field's readings, for example to correct a misread during a game, until
  you **Release** it. The field's row shows **HELD** and what the OCR reads
  meanwhile, and its label on the picture says **HELD**. A held value isn't
  saved.
- The OBS page has a **Text sources** table: the OBS text source each field
  updates, which you can edit (a custom field can now update OBS without
  editing an exported file). The names are saved with the boxes.
- A **Help** menu: **User guide** (**F1**, opens the documentation site),
  **Keyboard shortcuts** (lists every shortcut), **Check for updates...** and
  **About**. **File > Quit** (**Ctrl+Q**), and shortcuts for **Import field
  layout...** (**Ctrl+O**), **Export field layout...** (**Ctrl+Shift+S**)
  and **View log** (**Ctrl+Shift+L**).

### Changed

- The vMix output now defaults to port **8088**, the vMix Web API (Web
  Controller), and sends `SetText` as an HTTP GET request. A previously saved
  port 8099 (the vMix TCP API, which ScoreSight never supported) is changed to
  8088 once, and the log explains when a port answers like the vMix TCP API
  ([#55](https://github.com/royshil/scoresight/issues/55)).
- OBS, vMix, UNO and the outbound HTTP API send from background threads with
  timeouts, keeping only the latest value of each field. A slow or unreachable
  target no longer freezes the ScoreSight window or builds up a backlog of old
  values ([#33](https://github.com/royshil/scoresight/issues/33)). Any 2xx
  response counts as success.
- Repeated output errors are logged at most once every 30 seconds per output,
  with a count of the errors that were not logged, and recovery is logged once.
- OBS text sources are updated as soon as a box's good value changes, even when
  no output folder is set and independently of **Save / s**
  ([#30](https://github.com/royshil/scoresight/issues/30)). The OBS connection
  is re-established automatically after OBS restarts or the connection drops,
  and boxes without an OBS source name are skipped.
- Video sources (including NDI discovery), the saved OBS connection and the
  update check are handled in the background, so the window appears
  immediately and no longer freezes
  ([#33](https://github.com/royshil/scoresight/issues/33)).
- ScoreSight starts faster: screen capture support (pywin32 on Windows,
  Quartz on macOS) is loaded only when a screen capture source is used, and
  NDI support is loaded in the background while the sources are listed.
- ScoreSight remembers the type of the last source and reopens URL/RTSP
  streams, video files, cameras, NDI sources and screen capture at the next
  start ([#10](https://github.com/royshil/scoresight/issues/10)).
- The per-box confidence threshold (**Conf. Th**) is the minimum Tesseract
  confidence in percent and is off (0) by default. Boxes saved by an older
  version get a threshold of 0 once, because the setting had no effect before
  (see Fixed), so existing setups read exactly as before. The settings file
  records this as `"boxes_schema_version": 2`, and the log mentions it.
- Template fields use each box's last good reading, stay empty until every box
  they use has had a good reading, are reported as a new value only when their
  text changes, and can use other template fields.
- File outputs are state-based and atomic. Each file is written when its
  content changes or the file is missing, from the last good reading of each
  box, and replaced in one step so readers never see a partial file. Output is
  UTF-8, and characters that aren't allowed in file names are replaced with
  `_` ([#6](https://github.com/royshil/scoresight/issues/6),
  [#29](https://github.com/royshil/scoresight/issues/29)).
- In an append mode, `results.csv` gets a row when a value changes, and a new
  file is started (the old one is renamed `results-<timestamp>.csv`) when the
  set of boxes changes ([#29](https://github.com/royshil/scoresight/issues/29)).
  `results.xml` has a documented structure with one `<result>` element per box.
- Outbound HTTP API: *JSON (Simple key-value)* and *GET* send only good
  readings (Success or SameNoChange), and nothing is sent when there are none.
- **Average Output** votes on whole values over the last 5 accepted readings
  instead of character by character.
- **Skip Similar Image** compares the digits rather than the whole box, and a
  skipped box repeats its last good value as an unchanged reading instead of
  showing a yellow `SIM`.
- Saved **Video Settings** apply to camera sources only; their **Auto** backend
  means the platform default (DirectShow on Windows). **Capture Backend** lists
  only the backends ScoreSight's OpenCV includes, and a saved backend that
  can't open the camera falls back to the default one.
- ScoreSight remembers the language chosen in **View > Language**, and regional
  system locales (for example `de_AT` or `fr_CA`) now get the matching
  translation.
- In the Training Dojo, the next/back/remove-approval shortcuts are now
  Ctrl+N, Ctrl+B and Ctrl+U (⌘ on macOS), so N, B and U can be typed in
  annotations.
- On Linux, cameras are listed with their names and device nodes, for example
  `HD Webcam (/dev/video0)`.
- The window title shows the real version (and the profile), and the About
  dialog shows the version. The version number comes from a single place
  (`src/version.py`).
- The About and update dialogs link to the GitHub repository, the
  documentation site and GitHub Issues.
- The macOS app is now a regular app bundle that starts much faster, because
  it no longer unpacks itself on every launch
  ([#33](https://github.com/royshil/scoresight/issues/33)). It requires macOS 15
  or newer and is no longer slowed down by App Nap in the background.
- The Windows installer upgrades an existing ScoreSight installation in place,
  can install for all users or only the current user, and requires Windows 10
  version 1809 or newer.
- The Linux download is a compressed folder build (`scoresight/scoresight`)
  that needs glibc 2.35 or newer (Ubuntu 22.04+, Debian 12+). It includes
  `libxcb-cursor0` and the other xcb libraries Qt needs on X11.
- Updated to Python 3.13 with current dependencies: PySide6-Essentials 6.12
  (Qt 6.12), NumPy 2, OpenCV (headless), tesserocr 2.11 / Tesseract 5.5,
  cyndilib 0.1 (NDI), and current FastAPI, uvicorn and obsws-python.
- Settings are saved atomically and safely from any thread.
- ScoreSight can be started from source from any working directory
  (`python src/main.py`).
- For contributors: code style is enforced with ruff instead of black, the
  Windows camera enumerator builds with pybind11 from `requirements-build.txt`
  from any directory, and the PyInstaller spec builds every platform with the
  same command.
- The window has three parts: the **Fields** list on the left, the picture
  in the middle and the **inspector** on the right, with a **Box** tab (the
  selected field's settings) and an **Outputs** tab. The dividers between them
  can be dragged, a double-click on one hides or shows the field list or the
  inspector, and ScoreSight remembers the widths and the hidden panes. The
  window opens at a size that fits the screen. It fits small screens and long
  languages: its minimum size is about 910×410 pixels, in English and in
  German (it was 1016×750 and 1158×750), so it fits a 1366×768 laptop.
- The box settings are in the inspector's **Box** tab, under the field's name
  and *Settings for this field only*, in three sections: **Reading**,
  **Filtering** and **Image cleanup**. Image cleanup is collapsed until you
  open it (ScoreSight remembers it), and its header says how many of its
  settings you changed and has a **Binary view** button. The settings have
  plain names, with the 0.1.x names in their tooltips: *Remove leading zeros*
  (Remove leading 0s), *Add ordinal suffix* (Ordinal), *Count lights* (Dot
  Counter), *Minimum confidence* (Conf. Th), *Smooth over last 5 readings*
  (Average Output), *Skip OCR while image is unchanged* (Skip Similar Image),
  *Black & white* with *Whole picture*, *None*, *This box* and *Adaptive*
  (Binarize: Global, No Binarization, Local, Adaptive), *Remove specks*
  (Cleanup), *Squash height* (V.Scale), *Straighten slant* (Skew), *Thicken
  strokes* (Dilate), *Invert colours* (Invert Input), *Crop to text* (Auto
  Crop), *Resize to 35 px* (Rescale Input), *Normalize digit width* (Normalize
  W-H Ratio), *Build from other fields* (Template Field) and **Reset to
  defaults** (Defaults). *Per-character sub-boxes* (Composite) and *Skip empty
  values* (which has no effect since 0.2.0) are under *Experimental / legacy*.
  With no field selected, the tab explains how to select one; for a field
  that isn't on the picture, how to place it; a template field shows only its
  template.
- The settings for every box are together under **All boxes**, at the bottom
  of the Box tab and always available: the **OCR model** (*Load external
  model...*), **Detections / s** and **Update on change**, whose tooltip now
  says what it does.
- **Add to Scene** and **Remove Selected** are **Place on picture** and
  **Remove from picture**: one button under the field list, the one that
  applies to the selected field. **-** is **Delete field**, shown only for
  custom fields (on a standard field it did nothing). Removing a box whose
  settings you changed, and deleting a field, ask first.
- The boxes list shows the readings: each box's last good value in large type,
  a symbol and a word for the state of its latest reading (✓ new, = same,
  ! rejected, with the rejected text, ∅ no reading) and how long ago the last
  good reading was made, highlighted when it's old. A rejected or empty
  reading no longer greys out or hides the value, the list is tall enough for
  every standard box, and a click on a value selects its box.
- **Stop Updates** is now **Pause outputs** / **Resume outputs**, at the top
  of the field list. While the outputs are paused, the button is orange, a
  banner over the picture shows since when (with a **Resume outputs**
  button), the values in the boxes list are marked *not sent*, the window
  title starts with ⏸ and the status bar shows how long they have been paused.
- **The whole window is translated** into the 12 languages (German, Spanish,
  French, Italian, Japanese, Korean, Dutch, Polish, Brazilian and European
  Portuguese, Russian, Chinese). Before, most of it showed English in every
  language. The new translations are machine drafts, marked for review in the
  translation files: corrections from native speakers are welcome (see
  `docs/development/translations.md`). The Video Settings, Logs, About and
  stream URL window titles are translated too, and the settings panel widens
  to fit a long language instead of cutting labels off.
- The menus are translated, and **View > Language** lists each language
  in its own language (Deutsch, Français, 日本語, ...) with the current one
  ticked.
- The menus are **File** (**Import field layout...** and **Export field
  layout...**, formerly Import and Export Configuration, **Open settings
  folder**, **Quit**), **View** (the layouts, the view tools, **Show unused
  fields**, **Appearance** and **Language**, which moved from File),
  **Tools** (... and **View log**, formerly File > View Current Log) and
  **Help** (**Check for updates...** and **About** moved from File). On
  macOS, **About** and **Quit** are in the application menu.
- vMix and UNO: **Send Same?** is now **Also resend unchanged values**, with
  a tooltip that says what it does (the setting is the same).
- **Connect to OBS** hides the password (with **Show password**), has a
  **Cancel** button and stays in front of the main window.
- The vMix and UNO start buttons show a text and an icon instead of emoji:
  **Start vMix** / **Stop vMix** and **Start sending** / **Stop sending**.
- Long camera names no longer make the window wider: the source list is kept
  narrow, and its drop-down shows the whole names.
- The output tabs (**Text Files**, **Browser**, **OBS**, **VMix**, **UNO**,
  **API**) are replaced by the **Outputs** list, in the inspector's **Outputs**
  tab: select an output to show its settings under the list. The settings are
  the same as on the tabs, and a divider between the list and the settings
  gives the vMix and UNO mapping tables as much room as you need.
- The boxes on the picture are easier to read and no longer hide what they
  read. Each box has one label, under it (above it, or inside it, when
  there's no room), that covers no other box: a symbol for the state of the
  latest reading (✓ new, = unchanged, ! rejected, ∅ empty, instead of colours
  alone and `EMP`), the box's name and the reading, the same size at every
  zoom. Boxes are a light blue line with a dark edge, visible on red LED
  digits; the selected box has the highlight colour and white handles.
- The statistics overlay (**Stats**, was **OSD**) has a fixed size (it grew
  with the picture), is translated, and is off for new installations (the
  status bar shows the same numbers); it stays on if you used it before, and
  the choice is now remembered.
- **4-corner Correction** (now **4-corner**) no longer removes the correction
  when clicked. With a correction in place it offers **Redo corners…**,
  **Remove correction…** (asks first) and **Cancel**. While you pick corners,
  a banner counts them, the boxes hide, and **Esc** keeps the previous
  correction, which is replaced only by the fourth valid click.
- The view tools moved next to the source (**Binary View**, **Boxes:**,
  **Stats**, **Fit**, was **1:1**), and the picture adjustments have their own
  row: **Adjust picture:** **Rotate** (showing the angle), **Crop**,
  **4-corner**, **Stabilize**. A tool that is on is filled with the highlight
  colour, and in a narrow window the view tools show icons only. Reload and
  Video settings are icons; Video settings says why it's disabled for
  sources other than cameras.
- The playback speed of video files moved from the crop panel to the source
  bar, shown for video files only, and starts at ×1 for each new file.
- **Save OCR Training Data** is now **Tools** > **Collect OCR training data**,
  with a **Collecting training data** chip in the status bar while it's on.
  **OCR Training Data Setup** moved from **File** to **Tools**.
- The viewer is dark around the picture in both light and dark themes.

### Fixed

- **Recreate** next to **Create OBS Scene** did nothing: an existing scene
  was always emptied and made again. Unticked, an existing scene is now
  kept as it is, and a line under the button says what happened (created,
  made again, kept, or failed).
- Renaming a field to a name that was taken did nothing, without a message.
  ScoreSight now says so and asks again. Names that differ only in upper and
  lower case count as the same, because their text files are the same file on
  Windows and macOS.
- A custom field on the picture could also be made a template field, which
  left two boxes with the same name. Only a field that isn't on the picture
  can become a template.
- Right after **Add to Scene** (now **Place on picture**), the settings panel
  showed values that weren't the new box's (for example **Average Output**
  on), until another box was selected.
- After a language change, the settings panel showed *Select an item above*
  instead of the selected box's name.
- Moving through the field list with the arrow keys didn't update the
  settings shown, so a change was saved to another box than the one shown,
  and **Add to Scene** could add a second box with the same name.
- After **File > Import Configuration**, fields that weren't in the file were
  still marked as being on the picture.
- Setting **Detections / s** to 1 froze the video and could leave the controls
  disabled. The preview and the first reading now start on the first frame,
  and the preview refreshes about once a second at any detection rate
  ([#53](https://github.com/royshil/scoresight/issues/53),
  [#20](https://github.com/royshil/scoresight/issues/20)).
- ScoreSight could crash at random (an access violation, most likely at
  startup or with outputs active) when Python's memory cleanup ran on one of
  its background threads while the window was being updated. The cleanup now
  runs only on the window's thread.
- The first readings after a source opened were lost. A value that never
  changed (for example a score after a restart) then didn't show in the boxes
  list, and vMix and UNO didn't receive it until it changed (unless **Send
  Same?** was on).
- A value that changed while the outputs were paused didn't reach vMix and UNO
  after resuming until it changed again (unless **Send Same?** was on). After
  resuming, they now get each box's next good value even if it is unchanged.
- Closing the **Connect to OBS** dialog without connecting left **Create OBS
  Scene** disabled, even with OBS connected.
- The outbound API's method list was too narrow to show `POST`.
- Saved **Video Settings** (capture backend, video format, resolution, frame
  rate) were not applied when a camera opened, and pressing **OK** in Video
  Settings reopened the camera and threw them away
  ([#20](https://github.com/royshil/scoresight/issues/20)).
- The Video Settings resolution list offered `1980x1080` instead of
  `1920x1080`.
- RTSP/HTTP stream sources could block for about 30 seconds when unreachable.
  They now open with FFmpeg and give up after 5 seconds, and spaces around the
  URL are ignored ([#10](https://github.com/royshil/scoresight/issues/10)).
- ScoreSight hung or showed "Not Responding" when quitting on macOS. The
  built-in HTTP server now stops in-process within a few seconds
  ([#7](https://github.com/royshil/scoresight/issues/7),
  [#33](https://github.com/royshil/scoresight/issues/33)).
- Switching sources or quitting no longer hangs while a stream is stalled: the
  capture gets up to 3 seconds to stop
  ([#7](https://github.com/royshil/scoresight/issues/7),
  [#33](https://github.com/royshil/scoresight/issues/33)).
- Closing the main window while **Video Settings** or **Connect to OBS** was
  open left ScoreSight running until that window was closed too.
- If the HTTP server port is already in use, ScoreSight logs an error and keeps
  running without the server, and closing an instance never affects another
  instance's server ([#8](https://github.com/royshil/scoresight/issues/8)).
- The HTTP `/csv` endpoint returned the box positions as method names instead
  of numbers ([#29](https://github.com/royshil/scoresight/issues/29)).
  `/xml?pivot` always produces valid XML, even for box names such as
  "1st Half", and the XML endpoints are sent as UTF-8.
- The `/scoresight` demo page didn't work when opened from another computer or
  with a different `--port`.
- vMix received no data with the default settings
  ([#55](https://github.com/royshil/scoresight/issues/55)).
- Editing the vMix host, port or input, or the UNO URL, could stop the output
  silently or lose the field mapping. Changes now apply when you press Enter
  or leave the field. The vMix field mapping shown in the table is used even
  before any cell is edited.
- Per-box `.txt` files were sometimes never written, because a change that
  arrived between two file saves was dropped
  ([#6](https://github.com/royshil/scoresight/issues/6)).
- The CSV header was repeated before every row, values with commas broke the
  columns, and `results.xml` could be malformed
  ([#29](https://github.com/royshil/scoresight/issues/29)).
- Clicking a box or changing a box setting emptied `results.csv`.
- OBS text sources didn't update unless an output folder was set
  ([#30](https://github.com/royshil/scoresight/issues/30)).
- After **Create OBS Scene**, the new text sources could keep the scene's
  placeholder values until each box's value changed. Every box's current value
  is now sent with the next reading.
- The per-box confidence threshold had no effect, because Tesseract's 0–100
  confidence was compared with a 0–1 threshold. It now works, and when
  Tesseract reports a confidence of 0 for a non-empty reading, the average of
  the character confidences is used
  ([#30](https://github.com/royshil/scoresight/issues/30)).
- A box over plain background produced invented digits with the scoreboard
  models. It now reads as empty
  ([#30](https://github.com/royshil/scoresight/issues/30)).
- A **Dot Counter** box over a blank area could count one dot, for example with
  **Local** or **Adaptive** binarization. It now reports 0.
- Template fields could show rejected readings such as `SIM`, and were sent as
  a new value on every cycle, which defeated **Update on change**.
- **Dilate** didn't reach the OCR with every binarization method, and
  overlapping boxes affected each other's reading.
- A box reaching past the edge of the picture was read as empty, or moved and
  shrunk in the saved settings. It is now read from its visible part and left
  as it is.
- **Average Output** could show mixed values such as `92` when the number of
  digits changed, and **Skip Similar Image** ignored one-digit changes.
- With **Skip Similar Image** on, a new value whose first reading was rejected
  or empty wasn't read again until the image changed once more. The image is
  now compared with the box's last accepted reading.
- Video processing stopped silently on an oversized crop, a very short box with
  vertical scaling, a black frame while stabilization was on, an OCR model
  change in the middle of a reading, or a box deleted while it was being read.
- Selecting an invalid custom OCR model now keeps the current model working.
- Stabilization fed the OCR blended frames while it warmed up.
- An invalid four-corner selection (for example the same corner clicked twice)
  corrupted every frame. It is now rejected and you can click again.
- NDI sources disappeared when **Reload** was clicked again, and refreshing
  paused for a second.
- Clicking **Reload** while a camera was selected opened the Screen Capture
  dialog, and with two cameras could switch to the other camera.
- In a translated interface, cancelling **Open a Video File** left the source
  list on that entry, with the field list and the view tools disabled.
- On Linux, device nodes that can't capture video were listed, and cameras
  could open with the wrong device number.
- **Capture the entire screen** didn't work on macOS.
- Closed sources stayed in memory and could be reopened in the background by a
  later Video Settings change.
- Each Video Settings change made every OCR result be processed and sent to
  the outputs once more.
- Box setting changes, new or removed boxes and renames were lost when
  switching or reloading the source.
- Renaming a custom field that had a box removed it from the field list until
  another box changed or ScoreSight restarted, although its box was still read.
- Clicking **-** with a predefined field such as *Home Score* selected deleted
  its box and box settings. Predefined fields can't be removed, and the button
  now leaves them alone.
- A box's **Type** (Number/Time/Text) was lost after a restart or a
  configuration export ([#22](https://github.com/royshil/scoresight/issues/22)).
- The **Stop Updates**/**Resume Updates** button went blank in non-English
  languages.
- Switching the language reset the vMix connection, the UNO URL and the
  template field text.
- The Output API encoding was blank on a fresh install, so POST/PUT output
  never sent anything.
- The **Save Folder** chosen in **OCR Training Data Setup** was ignored
  ([#52](https://github.com/royshil/scoresight/issues/52)). It is now used and
  remembered, configurations from 0.1.x keep working, and the default folder
  follows `SCORESIGHT_DATA_DIR`.
- With **Save OCR Training Data** on and a template field defined, recognition
  could silently stop after a few frames. Saving samples can no longer stop
  recognition.
- Saving OCR training data scanned the whole folder on every detection and
  flooded the log when the folder was full. The size limit is now logged once,
  and saving resumes when there is room again.
- OCR training data couldn't be saved to folders with non-ASCII characters in
  their path on Windows.
- **Open Folder** in OCR Training Data Setup didn't work on macOS and Linux.
- Training Dojo: with **Only Undone** on, Enter skipped an image; clicking a
  filtered list item opened the wrong item; an empty folder, a missing
  annotation file or a damaged `approved_annotations.json` crashed it;
  Ctrl+Up/Down discarded the text being typed; unapproved items were
  unreadable in dark mode.
- The log viewer failed when the log file couldn't be created, didn't read
  logs as UTF-8, lost the scroll position with Auto Scroll off, and kept
  polling while closed.
- The standalone training-data tools in `scripts/` crashed or hung when
  cancelled or when their window was closed, didn't handle empty or missing
  folders and non-ASCII paths, and required undocumented corner click orders.
  They now also have `--help`.
- The packaged app re-ran most of its modules at startup and again after the
  window closed.

### Removed

- The unauthenticated `GET /shutdown` endpoint of the built-in HTTP server (see
  Security).
- The **File > Theme** menu (replaced by **File > Appearance**), the **Force
  Format** checkbox and the UNO **Rate Limit** field, which had no effect.
- All links to the former `scoresight[.]live` website, download server and
  e-mail addresses, in the app and the documentation, and the expired Discord
  invite.
- The `.env` file and the unused NDI UWP and DirectShow libraries from the
  packaged app (about 66 MB smaller).
- The `pygetwindow` and pinned `websockets` dependencies.

### Security

- Removed `GET /shutdown`, which let any device that could reach port 18099,
  or any web page open in a browser, close ScoreSight. Closing a second
  instance also shut down the first one.
- The OBS WebSocket password is no longer written to the log.
- The HTTP server's CORS policy allows only `GET` requests, without
  credentials.
- The About and Update dialogs of 0.1.x and older link to `scoresight[.]live`, a
  domain the project no longer controls. Download ScoreSight only from
  [GitHub Releases](https://github.com/royshil/scoresight/releases) and verify
  it against `SHA256SUMS.txt`.
- Added `SECURITY.md`, which describes how to report vulnerabilities and the
  app's network exposure (the HTTP server listens on all interfaces without
  authentication).

## [0.1.0] - 2024-11-07

### Added

- overlays.uno **Essentials** API support (content fields with an overlay ID)
  ([#44](https://github.com/royshil/scoresight/pull/44)).
- Experimental **Composite (Per-Character)** boxes: draw and save one sub-box
  per character ([#48](https://github.com/royshil/scoresight/pull/48)).
- Application style (theme) selection
  ([#51](https://github.com/royshil/scoresight/pull/51)).

### Changed

- Cameras open at their highest supported resolution
  ([#51](https://github.com/royshil/scoresight/pull/51)).
- Main window layout and translation updates
  ([#47](https://github.com/royshil/scoresight/pull/47)).

## [0.0.17] - 2024-10-15

### Added

- Load an external Tesseract OCR model (`.traineddata`)
  ([#46](https://github.com/royshil/scoresight/pull/46)).

### Fixed

- UI improvements and bug fixes, including a loading issue on macOS
  ([#45](https://github.com/royshil/scoresight/pull/45)).

## [0.0.16] - 2024-10-09

### Added

- overlays.uno (UNO) API output
  ([#42](https://github.com/royshil/scoresight/pull/42)).
- Detection box display styles, such as outline only
  ([#42](https://github.com/royshil/scoresight/pull/42)).
- Resize handles and select/deselect for detection boxes.

### Changed

- UI refactoring and bug fixes
  ([#43](https://github.com/royshil/scoresight/pull/43)).

## [0.0.15] - 2024-10-04

### Added

- Choice of HTTP method (POST, PUT, GET) for outbound API requests
  ([#39](https://github.com/royshil/scoresight/pull/39)).

### Changed

- Source files moved into `src/`, and major code refactoring
  ([#40](https://github.com/royshil/scoresight/pull/40),
  [#41](https://github.com/royshil/scoresight/pull/41)).

### Fixed

- NDI capture disabling the UI
  ([#41](https://github.com/royshil/scoresight/pull/41)).

## [0.0.14] - 2024-09-25

### Added

- **OCR Training Dojo** for annotating collected training data
  ([#38](https://github.com/royshil/scoresight/pull/38)).
- Playback speed control for video files
  ([#38](https://github.com/royshil/scoresight/pull/38)).

### Fixed

- A critical bug in screen capture mode
  ([#37](https://github.com/royshil/scoresight/pull/37)).

## [0.0.13] - 2024-09-23

### Added

- **Video Settings** dialog for cameras (FPS, resolution, format, capture
  backend) ([#36](https://github.com/royshil/scoresight/pull/36)).
- OCR training data collection.
- Sending readings to external HTTP APIs (outbound API).

## [0.0.12] - 2024-09-18

### Added

- Image rotation ([#35](https://github.com/royshil/scoresight/pull/35)).

### Fixed

- RTSP/URL sources on Windows were opened with DirectShow and could not play.
- The Detections / s setting wasn't loaded correctly at startup.

### Removed

- The unused status bar.

## [0.0.11] - 2024-09-10

### Added

- **Template fields** that combine other fields with a prefix or suffix
  ([#34](https://github.com/royshil/scoresight/pull/34)).

### Fixed

- A 4-corner correction bug.
- Duplicate entries when renaming custom fields.

## [0.0.10] - 2024-08-13

### Fixed

- vMix integration ([#28](https://github.com/royshil/scoresight/pull/28)).
- A logging error after closing the app
  ([#26](https://github.com/royshil/scoresight/pull/26)).

## [0.0.9] - 2024-07-20

### Added

- Crop function ([#21](https://github.com/royshil/scoresight/pull/21)).

### Fixed

- Loading custom boxes ([#23](https://github.com/royshil/scoresight/pull/23)).

## [0.0.8] - 2024-06-30

### Fixed

- Real-time updates of the built-in HTML scoreboard page.
- JSON pivot output.
- Camera enumeration on Linux
  ([#14](https://github.com/royshil/scoresight/pull/14)).

## [0.0.7] - 2024-06-17

### Added

- **Dot counter**, for example for counting baseball balls, strikes and outs
  ([#15](https://github.com/royshil/scoresight/pull/15)).
- Interface translations into more than 10 languages
  ([#11](https://github.com/royshil/scoresight/pull/11)).

### Changed

- Updated Tesseract and other dependencies
  ([#13](https://github.com/royshil/scoresight/pull/13)).
- UI improvements.

### Fixed

- The built-in HTTP service.

## [0.0.6] - 2024-05-23

### Fixed

- Various bug fixes.

## [0.0.5] - 2024-05-23

### Fixed

- UI bugs and the handling of result states for detection boxes
  ([#9](https://github.com/royshil/scoresight/pull/9)).

## [0.0.4] - 2024-04-28

### Added

- **Update on change**: send a value only when it changes.

## [0.0.3] - 2024-04-26

### Added

- Separate macOS builds for Intel (x86) and Apple Silicon (arm64)
  ([#2](https://github.com/royshil/scoresight/pull/2)).

## [0.0.2] - 2024-04-25

### Changed

- Packaging and build fixes.

## [0.0.1] - 2024-04-25

- First open-source release of ScoreSight.

[Unreleased]: https://github.com/royshil/scoresight/compare/0.4.2...HEAD
[0.4.2]: https://github.com/royshil/scoresight/compare/0.4.1...0.4.2
[0.4.1]: https://github.com/royshil/scoresight/compare/0.4.0...0.4.1
[0.4.0]: https://github.com/royshil/scoresight/compare/0.3.4...0.4.0
[0.3.4]: https://github.com/royshil/scoresight/compare/0.3.3...0.3.4
[0.3.3]: https://github.com/royshil/scoresight/compare/0.3.2...0.3.3
[0.3.2]: https://github.com/royshil/scoresight/compare/0.3.1...0.3.2
[0.3.1]: https://github.com/royshil/scoresight/compare/0.3.0...0.3.1
[0.3.0]: https://github.com/royshil/scoresight/compare/0.2.0...0.3.0
[0.2.0]: https://github.com/royshil/scoresight/compare/0.1.0...0.2.0
[0.1.0]: https://github.com/royshil/scoresight/compare/0.0.17...0.1.0
[0.0.17]: https://github.com/royshil/scoresight/compare/0.0.16...0.0.17
[0.0.16]: https://github.com/royshil/scoresight/compare/0.0.15...0.0.16
[0.0.15]: https://github.com/royshil/scoresight/compare/0.0.14...0.0.15
[0.0.14]: https://github.com/royshil/scoresight/compare/0.0.13...0.0.14
[0.0.13]: https://github.com/royshil/scoresight/compare/0.0.12...0.0.13
[0.0.12]: https://github.com/royshil/scoresight/compare/0.0.11...0.0.12
[0.0.11]: https://github.com/royshil/scoresight/compare/0.0.10...0.0.11
[0.0.10]: https://github.com/royshil/scoresight/compare/0.0.9...0.0.10
[0.0.9]: https://github.com/royshil/scoresight/compare/0.0.8...0.0.9
[0.0.8]: https://github.com/royshil/scoresight/compare/0.0.7...0.0.8
[0.0.7]: https://github.com/royshil/scoresight/compare/0.0.6...0.0.7
[0.0.6]: https://github.com/royshil/scoresight/compare/0.0.5...0.0.6
[0.0.5]: https://github.com/royshil/scoresight/compare/0.0.4...0.0.5
[0.0.4]: https://github.com/royshil/scoresight/compare/0.0.3...0.0.4
[0.0.3]: https://github.com/royshil/scoresight/compare/0.0.2...0.0.3
[0.0.2]: https://github.com/royshil/scoresight/compare/0.0.1...0.0.2
[0.0.1]: https://github.com/royshil/scoresight/releases/tag/0.0.1
