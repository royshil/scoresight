---
title: vMix
parent: Outputs
nav_order: 4
description: "Send ScoreSight readings to one vMix input or every title with matching fields, using HTTP or TCP."
---

# vMix Integration
{: .no_toc }

ScoreSight updates text fields in vMix titles directly. By default it sends values to one input through the vMix **Web API** (HTTP, served by vMix's **Web Controller** on port **8088**). You can also update **every title that has the field**, including titles off air, so a scorebug, half-time graphic and time-out graphic share the same scores and clocks. Both target modes support HTTP or vMix's TCP API.

<details open markdown="block">
  <summary>On this page</summary>
  {: .text-delta }
1. TOC
{:toc}
</details>

{: .important }
Type the **Web API port** (normally **8088**) in the port box, even when sending over TCP. TCP sending uses port **8099** as well; it does not replace the Web API connection used to fetch fields. ScoreSight 0.1.x and older defaulted to 8099 by mistake ([#25](https://github.com/royshil/scoresight/issues/25), [#55](https://github.com/royshil/scoresight/issues/55)); ScoreSight 0.2.0 changed a saved 8099 to 8088 once. A port you set later is kept as you typed it.

## 1. Enable the Web Controller in vMix

In vMix, open **Settings** > **Web Controller**, tick **Enabled**, and note the **Port** (8088 by default).

![vMix Settings > Web Controller with the Web Controller enabled on port 8088](image-8.png)

If ScoreSight runs on a different computer than vMix:

- use the vMix computer's IP address as the host in ScoreSight,
- allow the Web API port (normally 8088) through the firewall on the vMix computer, and
- if you set a Web Controller **Username/Password**, tick **Allow access to following pages without login: API**. ScoreSight doesn't send a vMix login.

If you choose **TCP (port 8099)** in ScoreSight, also allow TCP port **8099** through the firewall on that same computer. HTTP needs only the Web API port. TCP keeps one connection open for sending values and needs both ports: the Web API for fetching fields, and 8099 for updates.

## 2. Add a title and note its field names

Add a title input in vMix, for example one of the built-in scoreboard titles:

![A vMix scoreboard title](image-9.png)

Right-click the input and open the **Title Editor** to see the names of its text fields:

![Opening the vMix Title Editor](image-10.png)

Field names in the Title Editor look like `Home Score.Text`, `Away Score.Text` or `CLOCK.Text`. You need these exact names, **including the `.Text` suffix**. Names are case-sensitive and spaces matter. To update several graphics together, give their corresponding text fields the same name; use different names for unrelated fields.

{: .tip }
The repository includes a ready-made vMix preset, [`scoresight.vmix`](https://github.com/royshil/scoresight/blob/main/scoresight.vmix). It contains a scoreboard title with the fields `Home Score.Text`, `Away Score.Text`, `CLOCK.Text`, `Home Title.Text`, `Away Title.Text`, `Title 1.Text` and `Title 2.Text`. Open it in vMix (**Open** preset) to get started quickly.

## 3. Configure vMix in ScoreSight

Set up your boxes first (see the [Quickstart](quickstart.md)):

![Boxes placed over the scores and clock in ScoreSight](image-11.png)

Then select **vMix** in the **Outputs** tab on the right (or click **vMix** in the status bar). Its settings show under the list:

![The shared vMix settings with target selection, HTTP and TCP sending, and discovered fields](vmix-output.png)

| Setting | Value |
|---|---|
| **Connection** | Host (`localhost` or the vMix computer's IP) |
| **Web API** | The Web Controller port, normally `8088`. Used for fetching fields with either transport, and for sending values over HTTP |
| **Send to: Input** | Update one vMix title input: enter its number (as shown on the input in vMix), full name, or key (GUID). The field list and **Titles** counts refer to that input |
| **Send to: Every title that has the field** | Update every loaded title with the exact mapped field name, including titles off air. No input number is needed |
| **Send using** | **HTTP (Web API port)** is the default and uses only the Web API port. **TCP (port 8099)** keeps a connection open for updates and also needs the Web API port to fetch fields |
| **Fetch fields** | Request the available text-field names from vMix. Double-click a mapping cell to choose a name from its dropdown, or type the name manually to configure before vMix is reachable |
| **Output Mapping** | One row per ScoreSight field. In the vMix field column, select or type the exact name, for example `Home Score.Text`. The default is the ScoreSight field name, which usually needs the `.Text` suffix added. The mapping the table shows is used right away, even for rows you haven't edited. Clear a cell to stop sending that field |
| **Titles** | Number of discovered title inputs containing that mapped field. In **Input** mode it counts only the selected input; in **Every title** mode it counts all matches. This is a count from the last fetch, not confirmation of delivery |
| **Also resend unchanged values** (was **Send Same?**) | Off: send only new values. On: also resend unchanged values on every cycle. This is useful if someone else may overwrite the title in vMix |

Click **Start vMix** (or the switch of the vMix row) to begin sending (the button changes to **Stop vMix**). Click it again to stop sending without losing the settings.

A change to the host, port or input takes effect when you press **Enter** or leave the field. Spaces around the values are ignored. You don't need to stop and start the output: the mapping and the Start/Stop state are kept.

Once the mapping is complete, the title updates live in vMix:

![The vMix title showing live values from ScoreSight](image-13.png)

## When are fields fetched?

ScoreSight fetches the title fields when you click **Start vMix**, change the connection while the output is running, or click **Fetch fields** (also while stopped). It does not poll the preset periodically. Switching target modes or selecting another input reuses the cached list.

After adding, removing, renaming or changing titles in vMix, click **Fetch fields**. Fetching does not overwrite your mappings. Newly discovered matching titles receive the last good published values, even if those values have not changed. Reordering existing inputs does not redirect all-title updates, because ScoreSight identifies those inputs by their keys (GUIDs).

You can still type field names manually. If fetching fails, **Input / HTTP** can send using those names. Input mode also accepts `0` (Preview) and `-1` (Active); fetch again after changing which title those selectors refer to.

## Is vMix receiving the values?

The vMix row of the **Outputs** list (and **vMix** in the status bar) shows it:

| State | The vMix row says |
|---|---|
| ● Working | *Sending to localhost:8088, input 1*, or *Updating 4 titles at 192.168.1.40:8099* in all-title mode, and when the last value was sent (*2 s ago*) |
| ◐ Waiting | *Waiting for a new value for ...* or *Ready for 4 titles; waiting for values*: started, but no new value has been sent yet. vMix gets a value when it changes (or every time, with **Also resend unchanged values**). *Discovering vMix title fields…* means the first field fetch is still pending |
| ▲ Retrying | *Can't reach 192.168.1.40:8088 · retrying* or *No answer from ... · retrying*: vMix can't be reached. ScoreSight retries by itself and sends the latest values when vMix is back |
| ▲ Needs attention | *No fields to send* (nothing mapped), *N mapped fields not found in vMix*, or *1 of 4 failing: ...* when some fields arrive and others don't |
| ■ Not working | *Port 8099 is vMix's TCP API: use 8088*, *HTTP 401: vMix asks for a login*, or another error vMix answered with |

When vMix is selected and has a problem, a box over its settings says what to do. Hover the row for the full error.

## What ScoreSight sends

ScoreSight fetches the available titles and text fields from `http://<host>:<web-port>/api/`.

For every field with a new value (and a mapping), **HTTP** sends a `GET` request to:

```
http://<host>:<port>/api/?Function=SetText&Input=<input>&SelectedName=<field name>&Value=<value>
```

For example `http://localhost:8088/api/?Function=SetText&Input=1&SelectedName=CLOCK.Text&Value=4%3A27`. The field name and the value are percent-encoded, with spaces as `%20` (`SelectedName=Home%20Score.Text`); ScoreSight 0.2.0 and earlier sent spaces as `+`, which vMix may show as a literal `+`. You can paste such a URL into a browser to test vMix without ScoreSight. See the vMix [Developer API documentation](https://www.vmix.com/help30/DeveloperAPI.html) for details.

With **TCP (port 8099)**, ScoreSight sends a UTF-8 command terminated by a carriage return and newline over one persistent connection to `<host>:8099`:

```text
FUNCTION SetText Input=<input>&SelectedName=<field name>&Value=<value>
```

The parameters use the same percent encoding as HTTP, including `%20` for spaces. ScoreSight waits for vMix to acknowledge each command, and reconnects after a disconnect or timeout. A rejected field does not block other fields. See the vMix [TCP API documentation](https://www.vmix.com/help30/TCPAPI.html).

In **Every title that has the field** mode, each matching title receives its own update, identified by its input key. Selecting a transport does not change which titles receive values. If the chosen transport fails, ScoreSight retries it rather than silently switching to the other one.

Requests are sent in the background with a 2-second timeout. If vMix is busy or unreachable, ScoreSight keeps reading, keeps only the latest value of each field, retries with an increasing delay, and sends the latest values when vMix responds again. For HTTP, any 2xx response counts as success; for TCP, vMix must acknowledge the command with `FUNCTION OK`. Errors are logged at most once every 30 seconds.

Failed or empty OCR readings keep the last good value. Clearing a published value sends empty text. **Pause outputs** and **Hold value** apply to vMix like the other outputs.

## Alternative: vMix Data Sources

Instead of the direct integration, you can feed vMix titles from ScoreSight's HTTP server or files with vMix **Data Sources** (**Settings** > **Data Sources**, then bind title fields in the Data Source's mapping). vMix reads one row per poll and binds each column to a title field.

| Data Source type | URL or file | Notes |
|---|---|---|
| **XML** | `http://<scoresight-ip>:18099/xml?pivot&all`, XPath `/data` | One element per field: the names have no spaces (`HomeScore`, `AwayScore`) |
| **Excel/CSV** (from a URL or file) | `http://<scoresight-ip>:18099/csv?pivot&all`, with **first row as column names** | The columns are the field names (`Home Score`) |
| **JSON** | `http://<scoresight-ip>:18099/json?pivot&array` | vMix JSON Data Sources need an array of rows. `/json?pivot` returns a single object, which vMix doesn't read as a row; `?array` wraps it: `[{"Home Score": "21", ...}]` |
| **Text/CSV/XML file** | `results.csv` (or `results.xml`) from the [Text Files](text-files.md) output | `results.csv` has a `Timestamp` column first |

- Use `&all` (or the JSON `?array`, which includes it): every field is then always there with its last good value. Without it, a field whose reading is rejected for a moment is missing from that poll, and vMix may blank its title field.
- Set the Data Source's refresh interval to 250–500 ms.

These setups are **untested**: they follow vMix's documentation (and, for JSON, a vMix forum answer saying it needs an array). The direct integration above sends each change as it happens, and is the one we recommend.

## Troubleshooting

The vMix row of the **Outputs** list says what is wrong (see [above](#is-vmix-receiving-the-values)). vMix errors in the log start with `vMix:`.

| The vMix row says (the log says) | Fix |
|---|---|
| *Port 8099 is vMix's TCP API: use 8088* (`vMix: VMixTCPPortError: localhost:8099 answered like the vMix TCP API ('VERSION OK')...`) | The **Web API** box points at the TCP API port. Change it to the Web Controller port, **8088** by default, even if **Send using** is set to TCP |
| *Can't reach ...* or *No answer from ...* (`vMix: ConnectionError: ...`, connection refused, or a timeout) | The vMix Web Controller is not enabled, the port is wrong, or a firewall blocks it. Open `http://<host>:8088/api` in a browser to test |
| *HTTP 401: vMix asks for a login* (`vMix: OutputError: SetText 'Home Score.Text' returned HTTP 401`, or 403) | The Web Controller requires a login. Allow API access without login (see step 1) |
| ◐ *Waiting for a new value*, nothing changes in vMix | The mapping names don't match the Title Editor (remember `.Text`), or the **Input** is wrong. Values are sent when they change: turn on **Also resend unchanged values** to send them every time |
| ○ *Off* | Click **Start vMix** |
| Some fields update, others don't (*1 of 4 failing: ...* when vMix answers some of them with an error) | Check each mapping row against the Title Editor: empty cells are not sent. Readings that are yellow or red in ScoreSight are not sent |
| Fields cannot be fetched | Check the host, Web API port and API access without login. Open `http://<host>:8088/api/` in a browser to test. **Input / HTTP** can still send with manually entered mappings if discovery is unavailable |
| Fields are found, but TCP sends fail (the error identifies `<host>:8099`) | Successful fetching confirms only the Web API connection. Allow TCP port **8099** through the firewall on the same vMix computer, or select HTTP to send through the Web API port |
| *N mapped fields not found in vMix*, or **Titles** is zero | Compare each name with the Title Editor, including case, spaces and `.Text`, then click **Fetch fields**. In **Input** mode, check that the selected input contains those fields |
| A new title does not update until **Fetch fields** is clicked | The title list is cached. Click **Fetch fields** after changing titles in vMix. In **Every title** mode, newly discovered matches receive the available last good values |
| *vMix rejected a title field* | Check the mapped name and that the target title still exists, then click **Fetch fields**. Other valid fields can continue updating |
