---
title: OBS Studio
parent: Outputs
nav_order: 3
description: "Update OBS text sources from ScoreSight over the OBS WebSocket, or use browser and file-based alternatives."
---

# OBS Studio
{: .no_toc }

ScoreSight can update text sources in OBS Studio directly over the OBS WebSocket (protocol v5, built into OBS 28 and newer).

<a href="https://youtu.be/anQl1D921O0" target="_blank" rel="noopener"><img src="videos/10-obs.jpg" width="45%" alt="Video: Live scoreboard scores in OBS Studio (2:44)"/></a>

<details open markdown="block">
  <summary>On this page</summary>
  {: .text-delta }
1. TOC
{:toc}
</details>

## Three ways to get scores into OBS

| Method | How | Pros |
|---|---|---|
| **WebSocket** (this page) | ScoreSight sets the text of OBS text sources | Native OBS text, no files, works across computers |
| **Browser Source** | An HTML overlay polls the [HTTP server](http_server.md), for example `http://<scoresight-ip>:18099/scoresight` or your own page reading `/json?pivot&all` | Full design freedom (HTML/CSS), any field name including custom fields |
| **Text from file** | OBS text sources read the [text files](text-files.md) (*Read from file*) | Simple, works with every OBS version. OBS checks the file about once a second, so it lags up to a second |

{: .tip }
A page that ScoreSight serves (`/scoresight`) is on the same address as the data, so browser security checks about reading the local network don't apply to it. If your own overlay page is hosted elsewhere (for example on a public https site), ScoreSight's HTTP server allows it to read the data (CORS, including Chromium's local-network preflight), but OBS may still block http:// requests from an https:// page.

## 1. Enable the WebSocket server in OBS

1. In OBS, open **Tools** > **WebSocket Server Settings**.
2. Tick **Enable WebSocket server**. The default port is **4455**.
3. Tick **Enable Authentication** and set a password (recommended), or click **Show Connect Info** to see the generated one.
4. Click **OK**.

## 2. Connect ScoreSight

1. In ScoreSight, select **OBS** in the **Outputs** list (or click **OBS** in the status bar) and click **Connect OBS**. The OBS row's switch does the same.
2. Enter the OBS computer's address (`localhost` if OBS runs on the same computer), port `4455`, and the password. The password is hidden; tick **Show password** to check it. **Cancel** closes the dialog without connecting.
3. Click **Connect**. If the connection works within 3 seconds, the dialog closes and the scene controls become available. If not, the dialog says "Cannot connect to OBS" and why, for example *Can't reach localhost:4455* (OBS isn't running, or its WebSocket server is off) or *OBS refused the connection: check the password*.

Once connected, the OBS row says *Connected to localhost:4455* with a green ●, and when a text source was last updated. The button becomes **Change connection...** (to connect to another OBS), and **Disconnect** closes the connection.

ScoreSight remembers the connection and connects again in the background the next time it starts, so the window appears right away even if OBS isn't running yet. If that fails, the OBS row shows ■ *Not connected* with the reason: start OBS, then click **Connect OBS**. After you click **Disconnect**, ScoreSight keeps the connection settings for the dialog but doesn't connect at the next start until you connect again.

If OBS restarts or the connection drops while ScoreSight is running, the OBS row shows ▲ *Reconnecting to OBS at localhost:4455…*, and ScoreSight reconnects by itself as soon as OBS is reachable again (the log shows `OBS: reconnected to <host>:<port>`). The latest value of each text source is sent after the reconnect.

## 3. Create the text sources

ScoreSight updates OBS text sources whose names exactly match the standard fields:

| ScoreSight field | OBS text source name |
|---|---|
| Home Score | `Home score` |
| Away Score | `Away score` |
| Time | `Clock` |
| Period | `Period` |
| Home Fouls | `#Home Fouls` |
| Away Fouls | `#Away Fouls` |
| Shot Clock | `shotclock` |

You have two options:

- **Use the ready-made scene**: type a scene name (default *ScoreSight Scene*) and click **Create OBS Scene**. ScoreSight builds a complete scoreboard graphic in OBS, with the text sources above plus team names, logos and backgrounds you can restyle. If a scene with that name already exists, **Recreate** (on by default) empties it and rebuilds it; with **Recreate** off, the existing scene is kept as it is. A line under the button says what happened: *Created the scene*, *Made the scene again*, *OBS already has a scene...: it was kept as it is*, or *Couldn't create the scene* (the log has the details).

  **Recreate never deletes a source that another scene uses.** It removes the scene's items from that scene only. A source itself is deleted only if it looks like one ScoreSight made (it has the name and kind of a source of the ready-made scene, for example a FreeType 2 text source named `Clock`) and no other scene or group uses it. Any other source you added to the scene, and any source that other scenes share, stays in OBS: a shared ScoreSight source (for example `Clock` added to another scene with **Add Existing**) is put back into the rebuilt scene with its own settings and filters. So don't keep your own text sources with the ready-made scene's names only in that scene if you want to keep them.

  {: .note }
  In ScoreSight 0.2.0 and earlier, Recreate deleted every source of the scene from the whole scene collection, including sources that other scenes shared.
- **Use your own design**: create *Text (GDI+)* or *Text (FreeType 2)* sources with the names in the table, anywhere in your scenes. Names are case-sensitive.

The **Text sources** table on the OBS page lists every field on the picture with the OBS text source it updates. Double-click a source name to change it, for example to use the names of your own design; leave it empty to send nothing to OBS for that field. The names are saved with the boxes (and in exported field layouts).

Once connected, every change of a field's value updates its OBS text source.

{: .new }
In ScoreSight 0.1.x, OBS updates only ran when an output folder was set in the **Text Files** tab, and a slow OBS connection could freeze ScoreSight. In 0.2.0, OBS updates are independent of the file output, are sent in the background, survive an OBS restart, and the OBS row of the **Outputs** list shows whether they arrive.

## What gets sent

- A box's **good** reading (green or light green) is sent when it differs from the text ScoreSight last sent to that OBS source. Rejected (yellow) and empty readings never change the OBS text, so it keeps the last good value.
- Updates are sent as soon as the value changes, in the background. They are **not** limited by the **Save / s** setting of the text files, and they don't need an output folder.
- If OBS is slow, only the latest text of each source is kept and sent.
- Boxes without an OBS source name are skipped (see [Custom fields](#custom-fields)).
- **Pause outputs** freezes the OBS text.

## Custom fields

Custom fields have no OBS source name at first, so they don't update OBS. Your options:

- Type the name of an OBS text source next to the field in the **Text sources** table of the OBS page. The custom field then updates that text source like a standard field. (In ScoreSight 0.1.x this needed an exported configuration file edited by hand.)
- Use a **Browser Source** with the [HTTP server](http_server.md). It can show any field.
- Use a text source that **reads from file** with the field's `.txt` file ([Text Files](text-files.md)).

## A clip of every score

OBS's **replay buffer** keeps the last seconds of the program in memory, and saves them as a clip when asked. ScoreSight can ask after each score, so that after the game OBS's recordings folder holds a clip of every score, with the scorebug: highlights for social media without editing.

1. In OBS, turn on the replay buffer: **Settings** > **Output** > **Replay Buffer** > **Enable Replay Buffer**, and set its **Maximum Replay Time** (20–30 seconds covers the play before a score). Clips go to the **Recording Path** of the same page.
2. Start it before the game: **Start Replay Buffer** in OBS's **Controls**.
3. In ScoreSight, choose the [sport](game.md#choose-the-sport) (the scores are the ones the game counts) and, on the **OBS** page, turn on **Save the replay buffer after each score**.

**Delay** (5 seconds by default, up to 60) waits after the score before the clip is saved, so the clip also shows what followed (the celebration, the scorebug changing). A score during the wait starts it again, so one clip shows both scores. Nothing is saved while **Pause outputs** is on.

The log says `OBS: saved the replay buffer after the score` for each clip. If it says that the replay buffer isn't running, start it in OBS (step 2).

## Troubleshooting

Start with the OBS row of the **Outputs** list (or **OBS** in the status bar): it says what is wrong. OBS messages in the log start with `OBS:`.

| The OBS row (or the dialog) says | Check |
|---|---|
| *Can't reach localhost:4455* or *No answer from ...* | OBS is running, the WebSocket server is enabled (**Tools** > **WebSocket Server Settings**), the port matches, and the firewall on the OBS computer allows the port |
| *OBS refused the connection: check the password* or *OBS needs a password* | The password matches the one in OBS (**Show Connect Info**) |
| *OBS has no text source "Clock"* (▲ when other fields work) | OBS has no input with that name (code 600, "resource not found", in the log). Check the source names: they are case-sensitive |
| *Connected, but no field has an OBS text source* | No field on the picture has an OBS source name. Place the standard fields, or see [Custom fields](#custom-fields) |
| *Reconnecting to OBS at ...* | OBS closed or the network dropped. ScoreSight reconnects by itself when OBS is back (the log shows `OBS: OBSConnectionLost: ...` at most every 30 seconds). If it doesn't, click **Connect OBS** again |
| ● *Connected*, but the text doesn't change | The reading is green in ScoreSight, and **Pause outputs** is off. The time next to the OBS row shows when a text source was last updated |
| One field never updates | Its OBS text source in the **Text sources** table is empty or doesn't match a source in OBS (custom fields have none at first, see [Custom fields](#custom-fields)) |

{: .note }
ScoreSight 0.2.0 no longer writes the OBS WebSocket password to its log files.
