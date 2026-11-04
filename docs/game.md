---
title: Game & Sports
parent: Guides
nav_order: 9
description: "Choose the sport and ScoreSight follows the game from the scoreboard: each score, the start and end of each period, the clock starting and stopping, the final buzzer, and the points of each period. In a lap race: each lap, the final lap and the finish."
---

# Game & Sports
{: .no_toc }

Choose the **sport** being played and ScoreSight follows the **game**, not only the readings: it notices each score (who scored and how many points), the start and the end of each period, the clock starting and stopping, fouls and timeouts changing, and the final buzzer. It keeps them in the game's **event log**, adds up the **points of each period** (the line score), and serves it all at [`/game`](#the-game-over-http). In a [lap race](#lap-races) it follows the lap board instead: each lap, the final lap and the finish.

With a sport chosen, a change the sport doesn't allow (21 becoming 81) is [held back from the outputs](#wrong-readings-stay-off-the-air) until it is read steadily, so a misread never goes on air.

This is the first step of the [roadmap](https://github.com/royshil/scoresight/issues/116): graphics that react to the game (a goal animation, a line score, end-of-period cards), automatic highlights and player stats build on it.

<details open markdown="block">
  <summary>On this page</summary>
  {: .text-delta }
1. TOC
{:toc}
</details>

## Choose the sport

In the **Box** tab of the inspector, under **All boxes**, choose the **Sport**. *None* (the default) follows nothing, as in earlier versions.

| Sport | Score changes that make sense | Periods | Clock |
|---|---|---|---|
| Basketball | +1, +2, +3 | 4 quarters (Q1–Q4, then OT) | counts down |
| Basketball (halves) | +1, +2, +3 | 2 halves (H1, H2, then OT) | counts down |
| Soccer | +1 | 2 halves (H1, H2) | counts up |
| Futsal | +1 (the team fouls are followed too) | 2 halves (H1, H2, then OT) | counts down |
| Handball | +1 (the team timeouts are followed too) | 2 halves (H1, H2, then OT) | counts up |
| Ice hockey | +1 | 3 periods (P1–P3, then OT) | counts down |
| American football | +1, +2, +3, +6, +7, +8 | 4 quarters (Q1–Q4, then OT) | counts down |
| Volleyball | +1 (the scores start again each set) | up to 5 sets | none |
| Racing (laps) | no scores: one lap at a time on the lap board (see [Lap races](#lap-races)) | none | counts up (optional) |

A clock that counts the other way (a youth soccer board counting down, for example) is noticed after a few seconds.

Under the sport, a line says which fields ScoreSight follows and where the game is, for example:

> Follows Home Score, Away Score, Time, Period
> Q2 · 24–21 · clock running

Hover it for the latest events. **New game** forgets the game: the event log and the points per period start over, and the values are learned again from the next readings.

## Which fields are followed

ScoreSight finds each field by its **name**. The standard fields (*Home Score*, *Away Score*, *Time*, *Period*, *Home Fouls*, *Away Fouls*, *Shot Clock*) are followed as they are, and so are the usual variants:

| Field | Names (case, spaces and `_` don't matter) |
|---|---|
| Home score | Home Score, Score Home, Home, Home Points |
| Away score | Away Score, Guest Score, Visitor Score, Visitors Score, Score Away, Away, Guest, Visitor |
| Clock | Time, Clock, Game Clock, Game Time, Timer |
| Period | Period, Quarter, Qtr, Half, Set |
| Shot clock | Shot Clock, Shot Time, Play Clock |
| Fouls | Home Fouls, Away Fouls (or Guest / Visitor Fouls) |
| Timeouts | Home Timeouts, Away Timeouts (or Guest / Visitor Timeouts, Home TOL, Away TOL) |
| Laps to go | Laps To Go, Laps Remaining, Laps Left, LTG, To Go, Laps, Lap Cards, Lap Board |
| Laps completed | Laps Completed, Completed Laps, Laps Done, Lap Count |
| Total laps | Total Laps, Laps Total, Race Laps |

Rename a custom field to one of these names to have it followed. The sport decides which ones are used: soccer has no fouls on the board (futsal does: its team fouls go back to 0 at halftime), volleyball has no clock, a race has no scores. *Lap* alone isn't followed: on some boards it is the lap being raced, on others the laps completed.

The values are read as a scoreboard shows them: scores and laps `0`–`999` (`09` is 9), the clock as `12:00`, `4:32`, `45.3` or `0:09.8`, the period as `2`, `2nd`, `Q2`, `P3`, `Set 4`, `OT` or `OT2`.

## Wrong readings stay off the air

A misread must not become a "score", on air or in the event log. So a changed value counts only once it has been **read twice in a row**: a reading that flickers for one cycle makes no event.

A change the sport doesn't allow counts only once it has been read **steadily for 3 seconds**:
- a score going up by 5 in basketball, or 21 becoming 81;
- a score going down;
- a period skipped;
- fouls or timeouts changing by more than 1 (going back to 0 is fine);
- the clock jumping;
- laps to go changing other than down by 1, or laps completed other than up by 1.

A real correction (the scorer's table fixing a score) is steady, so it still counts, as a *corrected* score. A misread isn't.

**The outputs wait too.** Until such a change counts, every output (OBS, vMix, the HTTP server and the overlays, files, the APIs, TCP / UDP) and every [template field](boxes.md#template-fields) keeps the value it had: a flickered *81* never goes on air, and a real correction goes on air about 3 seconds late. Changes the sport allows go out at once, as before. The field list still shows what was read. The log (**Tools > View log**) says what was held back and why, then whether it was sent or dropped:

> Plausibility hold: Home Score read 81, 21 kept: a score going up by 60, which Basketball doesn't allow; it is sent once read steadily for a few seconds
> Plausibility hold: Home Score back to 21, 81 dropped

To put a value on air at once, use [Hold value](boxes.md#hold-value): a held value is never held back. It counts for the game as the value, so a held correction counts too. Template fields are built from the values sent and aren't held back themselves. The game is followed while the outputs are paused.

## Events

| Event | When |
|---|---|
| **Score** | A team's score changed: *Home +3 (24–21)*, or *Home score corrected to 22* |
| **Start of a period** | The period went up: *Start of Q2* |
| **End of a period** | A clock that counts down reached 0:00, or the period went up: *End of Q2 (34–30)* |
| **Final** | The clock reached 0:00 at the end of the last period (or of an overtime), stayed there for 3 seconds, and the scores aren't tied: *Final (64–58)* |
| **Clock started / stopped** | The clock moved the way it counts after standing still, or stood still for about 2 seconds (longer when the boxes are read less often) |
| **Fouls, timeouts** | A team's fouls or timeouts changed |
| **Lap** | A lap race's lap board moved on: *Laps to go: 12*, *Laps completed: 8*, or *Laps to go corrected to 11* |
| **Final lap** | One lap to go: *Final lap* |
| **Finish** | No laps to go: *Finish* |
| **New race** | The lap board was set for the next race: *New race* |

The events go to the log (**Tools > View log**, **Ctrl+Shift+L**): the clock's at the debug level, because they come at every whistle.

Limits:
- **Final** needs a clock that counts down, so soccer and volleyball games have no final event yet.
- The **points of each period** need a period field. They count from when ScoreSight started following the game, so they are marked complete only when it saw the game start at 0–0 in the first period.

## Lap races

Choose **Racing (laps)** for races with one lap board that everyone races to: track cycling, motorsport, speed skating, swimming, athletics. A lap count for each competitor (a timing tower) isn't followed.

Box the lap board and name the field **Laps To Go** (if it counts down) or **Laps Completed** (if it counts up). A race with laps completed finishes when they reach the **Total Laps**: box the total too, if the board shows it. Without a total, the laps are counted but there is no final lap or finish. A race clock named **Time** is followed too.

| The lap board | Counts as |
|---|---|
| Laps to go down by 1, or laps completed up by 1 | A **lap** (after two readings) |
| 1 lap to go (laps to go, or the total less the laps completed) | Also the **final lap** |
| 0 laps to go (or the laps completed reach the total) | Also the **finish** |
| Any other change, read steadily for 3 seconds: | |
| &nbsp;&nbsp;forward more than one lap (laps missed, or a card turned too far) | A **lap**, as far as the board says |
| &nbsp;&nbsp;back one lap | A *corrected* lap |
| &nbsp;&nbsp;back more than one lap, or laps completed back to 0 | A **new race** |
| A lap that turns two cards, with only one turned (*10* or *29* between 20 and 19), read steadily for 15 seconds | As any other change, above |

With both laps to go and laps completed on the board, the laps to go make the events.

### Hand-turned lap cards

Plastic lap cards turned by hand, as at a velodrome, read well with **PP-OCR (accurate)**. ScoreSight was tried on a video of a velodrome's two-card board in sunlight: the values read were the ones on the cards, and none of what a hand or a turning card does made an event:

- **Draw one box over both cards** and name it **Laps To Go**.
- **Set the Format to `^\d{1,2}$`** (two digits at most): the gap between two cards is sometimes read as a *1* (*919* for *99*), most often by PP-OCR (fast), and the format rejects those readings.
- A hand over a card, or a card half turned, is read for a moment as another number (*99* for *09*, *88* for *89*). One lap down is the only change counted at once, so these never count.
- Turning two cards for one lap shows another number until the second card is turned: *10* or *29* from 20 to 19, *00* or *19* from 10 to 09. On a 45-lap countdown, the board showed *10* for 3 seconds. Such a number counts only if the board stays that way for **15 seconds**, and the next lap counts as soon as the second card is turned, so a slow hand makes no event and the outputs keep the last lap until then.
- Hold the camera steady, or turn on [Stabilize](view-tools.md#stabilize), so the cards stay in the box.

## The game over HTTP

`http://<scoresight-ip>:18099/game` returns the game as JSON:

```json
{
  "sport": "basketball",
  "roles": {"home_score": "Home Score", "away_score": "Away Score", "clock": "Time", "period": "Period"},
  "home": {"score": 24, "fouls": 3, "timeouts": null},
  "away": {"score": 21, "fouls": 5, "timeouts": null},
  "period": 2, "period_label": "Q2",
  "clock": "4:32", "clock_running": true, "shot_clock": "14",
  "laps": {"to_go": null, "completed": null, "total": null},
  "line_score": [
    {"period": 1, "label": "Q1", "home": 18, "away": 15},
    {"period": 2, "label": "Q2", "home": 6, "away": 6}
  ],
  "line_score_complete": true,
  "final": false,
  "events": [
    {"id": 41, "kind": "score", "text": "Home +3 (24–21)", "team": "home", "delta": 3,
     "value": 24, "home": 24, "away": 21, "laps_to_go": null, "laps_completed": null,
     "period": 2, "period_label": "Q2", "clock": "4:32", "at": 1760300000.5}
  ]
}
```

- `events` is the game's event log, oldest first. Each event has an `id`, so polling `/game?since=41` returns only the events after event 41.
- `kind` is one of `score`, `period_start`, `period_end`, `final`, `clock_start`, `clock_stop`, `fouls` or `timeouts`, and in a lap race `lap`, `final_lap`, `finish` or `new_race`. A `lap` event's `delta` is the laps raced (1, or negative for a correction) and its `value` the lap counter's; every event has the lap board then in `laps_to_go` and `laps_completed`.
- `laps` is the lap board as read (`null` for what isn't on it), and `final` is `true` once a race has finished, until the next race.
- `at` is the time in seconds since 1970 (UTC).

Like the other endpoints, `/game` doesn't change while the outputs are paused.

## Settings

The sport is saved as `sport` in the settings file (see [Settings, Files & Command Line](configuration.md)). The game itself isn't saved: a new session starts a new game.
