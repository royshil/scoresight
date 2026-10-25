"""Game state: follows the game from the readings, for the sport chosen
(sports.py). GameEngine knows the scores, the clock and whether it runs, the
period, the fouls and timeouts, the points of each period (the line score),
and keeps an event log: a score, the start and the end of a period, the clock
starting and stopping, fouls and timeouts changing, the final buzzer. In a
lap race it knows the laps (to go, completed, the total) instead of scores,
and logs each lap, the final lap, the finish and a new race.

MainWindow.ocrResult calls update() with each cycle's results, after Hold value
and the template fields (a held value counts), on the GUI thread. Each box
gets its role from its name (sports.assign_roles).

A changed value counts only once it has been read again (CONFIRM_READINGS), so
a reading that flickers for one cycle makes no event. A change the sport
doesn't allow (a basketball score going up by 5 or down, 21 -> 81, a period
skipped, the clock jumping) counts only once it has been read steadily for
HOLD_SECONDS, which a real correction is. The clock's small moves count at
once. A lap counter allows only one lap at a time, the way it counts (laps to
go down, laps completed up); a lap board set for the next race (laps to go
back up, laps completed back to 0) is a new race once read steadily for
HOLD_SECONDS. A lap board of hand-turned cards shows another number while a
lap turns two of them (20 to 19 shows 10 or 29 with one card turned): such a
number counts only once read steadily for CARD_TURN_HOLD_SECONDS. Nothing here changes what the outputs get: held_back() says
which readings aren't counted yet, and plausibility_holds.py keeps them from
the outputs until they are.
"""

import re
import time
from collections import deque
from collections.abc import Iterable
from dataclasses import asdict, dataclass

import sports
from sports import (
    AWAY_FOULS,
    AWAY_SCORE,
    AWAY_TIMEOUTS,
    CLOCK,
    HOME,
    HOME_FOULS,
    HOME_SCORE,
    HOME_TIMEOUTS,
    LAPS_COMPLETED,
    LAPS_TO_GO,
    PERIOD,
    SHOT_CLOCK,
    TEAM_OF,
    TOTAL_LAPS,
    SportProfile,
)
from text_detection_target import TextDetectionTargetWithResult

_GOOD_STATES = (
    TextDetectionTargetWithResult.ResultState.Success,
    TextDetectionTargetWithResult.ResultState.SameNoChange,
)

# readings of a new value before it counts
CONFIRM_READINGS = 2
# a change the sport doesn't allow counts once read this long and this often
HOLD_SECONDS = 3.0
HOLD_READINGS = 3
# a lap board showing the next lap with only some of the cards it turns turned
# (20 to 19: 10 or 29) counts once read this long: a hand takes a few seconds
# to turn the next card, and the next lap is then counted at once
CARD_TURN_HOLD_SECONDS = 15.0
# the clock is stopped when it hasn't changed for this long (at least; longer
# when the boxes are read less often)
CLOCK_STOP_SECONDS = 1.6
# a small clock move: at most this many seconds more than the time since the
# clock was last read, times CLOCK_SLACK
CLOCK_MARGIN = 1.5
CLOCK_SLACK = 1.5
# moves against the counting direction, in a row, that turn it around
CLOCK_TURN_MOVES = 3
# the final buzzer: the last period ended this long ago, with different scores
FINAL_SETTLE_SECONDS = 3.0
MAX_EVENTS = 5000

# event kinds
SCORE = "score"
PERIOD_START = "period_start"
PERIOD_END = "period_end"
CLOCK_START = "clock_start"
CLOCK_STOP = "clock_stop"
FOULS = "fouls"
TIMEOUTS = "timeouts"
FINAL = "final"
LAP = "lap"
FINAL_LAP = "final_lap"
FINISH = "finish"
NEW_RACE = "new_race"

# --- reading the values ----------------------------------------------------------

_COUNT = re.compile(r"\d{1,3}")
_CLOCK = re.compile(
    r"(?:(?:(?P<h>\d{1,2}):)?(?P<m>\d{1,3}):)?(?P<s>\d{1,2})(?:[.,](?P<f>\d{1,2}))?"
)
_TENTHS_AFTER_COLON = re.compile(r"(\d{1,2}):(\d)")
_OVERTIME = re.compile(r"(?:OT|O)\s*(\d?)")


def parse_count(text: str) -> int | None:
    """A score, fouls or timeouts: 0-999 ("07" is 7)."""
    text = text.strip().replace(" ", "")
    return int(text) if _COUNT.fullmatch(text) else None


def parse_clock(text: str) -> float | None:
    """The clock in seconds: "4:32" 272, "12:00" 720, "45.3" 45.3, "0:09.8"
    9.8, "1:02:03" 3723, "45" (seconds only) 45, "59:8" (the tenths after a
    colon, as some boards show them below a minute) 59.8."""
    text = text.strip().replace(" ", "")
    tenths = _TENTHS_AFTER_COLON.fullmatch(text)
    if tenths is not None:
        # one digit after the colon: tenths (a minutes clock shows two)
        seconds = int(tenths[1])
        return seconds + int(tenths[2]) / 10 if seconds <= 59 else None
    match = _CLOCK.fullmatch(text)
    if match is None:
        return None
    hours = int(match["h"] or 0)
    minutes = int(match["m"] or 0)
    seconds = int(match["s"])
    if match["m"] is not None and seconds > 59:
        return None
    fraction = match["f"]
    total = hours * 3600 + minutes * 60 + seconds
    if fraction:
        total += int(fraction) / 10 ** len(fraction)
    return float(total)


def parse_period(text: str, sport: SportProfile) -> int | None:
    """The period: "2", "2nd", "Q2", "P3", "Set 4", "OT" (the first overtime:
    the period after the regular ones), "OT2", "2OT"."""
    text = text.strip().upper()
    if not text:
        return None
    overtime = _OVERTIME.fullmatch(text) or re.fullmatch(r"(\d)\s*OT", text)
    if overtime and sport.overtime and sport.periods:
        extra = int(overtime.group(1) or 1)
        return sport.periods + extra if 1 <= extra <= 9 else None
    digits = re.search(r"\d{1,2}", text)
    if digits is None:
        return None
    period = int(digits.group(0))
    return period if 1 <= period <= 20 else None


# --- the game ---------------------------------------------------------------------


def half_turned(old: int, new: int) -> set[int]:
    """The numbers a board of digit cards shows while it changes from old to
    new with some of the cards that change turned and not the others (10 to 9:
    00 and 19)."""
    if old < 0 or new < 0:
        return set()
    width = max(len(str(old)), len(str(new)))
    before, after = str(old).zfill(width), str(new).zfill(width)
    changed = [i for i in range(width) if before[i] != after[i]]
    values = set()
    # every set of turned cards but none and all
    for turned in range(1, 2 ** len(changed) - 1):
        digits = list(before)
        for bit, i in enumerate(changed):
            if turned >> bit & 1:
                digits[i] = after[i]
        values.add(int("".join(digits)))
    return values


def _score_text(home: int | None, away: int | None) -> str:
    return f"{'?' if home is None else home}–{'?' if away is None else away}"


@dataclass(frozen=True)
class GameEvent:
    id: int  # 1, 2... in the game
    kind: str
    at: float  # when it happened (seconds since the epoch)
    period: int | None
    period_label: str
    clock: str | None  # the clock as read
    home: int | None  # the scores then
    away: int | None
    team: str | None = None  # "home" or "away"
    # points, how much fouls or timeouts changed, or laps raced (a lap: 1)
    delta: int | None = None
    # the team's score, fouls or timeouts then, or the lap counter's value
    value: int | None = None
    # the lap board then (a lap race)
    laps_to_go: int | None = None
    laps_completed: int | None = None

    def text(self) -> str:
        """In English (the log, /game); the UI has its own translated text."""
        team = (self.team or "").capitalize()
        score = _score_text(self.home, self.away)
        if self.kind == LAP:
            if self.laps_to_go is not None:
                counter, laps = "Laps to go", self.laps_to_go
            else:
                counter, laps = "Laps completed", self.laps_completed
            if self.delta is not None and self.delta < 0:
                return f"{counter} corrected to {laps}"
            return f"{counter}: {laps}"
        if self.kind == FINAL_LAP:
            return "Final lap"
        if self.kind == FINISH:
            return "Finish"
        if self.kind == NEW_RACE:
            return "New race"
        if self.kind == SCORE:
            if self.delta is not None and self.delta < 0:
                return f"{team} score corrected to {self.value} ({score})"
            return f"{team} +{self.delta} ({score})"
        if self.kind == PERIOD_START:
            return f"Start of {self.period_label}"
        if self.kind == PERIOD_END:
            return f"End of {self.period_label} ({score})"
        if self.kind == FINAL:
            return f"Final ({score})"
        if self.kind == CLOCK_START:
            return f"Clock started at {self.clock}"
        if self.kind == CLOCK_STOP:
            return f"Clock stopped at {self.clock}"
        if self.kind == FOULS:
            return f"{team} fouls: {self.value}"
        if self.kind == TIMEOUTS:
            return f"{team} timeouts: {self.value}"
        return self.kind

    def to_dict(self) -> dict:
        return {**asdict(self), "text": self.text()}


@dataclass(frozen=True)
class LinePeriod:
    period: int
    label: str
    home: int
    away: int


@dataclass(frozen=True)
class GameState:
    """A snapshot of the game (GameEngine.state())."""

    sport: str
    roles: dict[str, str]  # {role: box name}
    home: int | None = None
    away: int | None = None
    period: int | None = None
    period_label: str = ""
    clock: str | None = None
    clock_running: bool = False
    shot_clock: str | None = None
    home_fouls: int | None = None
    away_fouls: int | None = None
    home_timeouts: int | None = None
    away_timeouts: int | None = None
    # the lap board, as read (a lap race)
    laps_to_go: int | None = None
    laps_completed: int | None = None
    total_laps: int | None = None
    # the points scored in each period, since ScoreSight followed the game;
    # complete when it saw the game start (0-0)
    line_score: tuple[LinePeriod, ...] = ()
    line_score_complete: bool = False
    final: bool = False
    events: tuple[GameEvent, ...] = ()

    def to_dict(self, since: int = 0) -> dict:
        """For /game: the events after event id since."""
        return {
            "sport": self.sport,
            "roles": dict(self.roles),
            "home": {
                "score": self.home,
                "fouls": self.home_fouls,
                "timeouts": self.home_timeouts,
            },
            "away": {
                "score": self.away,
                "fouls": self.away_fouls,
                "timeouts": self.away_timeouts,
            },
            "period": self.period,
            "period_label": self.period_label,
            "clock": self.clock,
            "clock_running": self.clock_running,
            "shot_clock": self.shot_clock,
            "laps": {
                "to_go": self.laps_to_go,
                "completed": self.laps_completed,
                "total": self.total_laps,
            },
            "line_score": [asdict(period) for period in self.line_score],
            "line_score_complete": self.line_score_complete,
            "final": self.final,
            "events": [event.to_dict() for event in self.events if event.id > since],
        }


class _Tracker:
    """A role's value: the one that counts, and a new one being confirmed."""

    __slots__ = (
        "value",
        "text",
        "changed_at",
        "seen_at",
        "candidate",
        "candidate_text",
        "candidate_since",
        "candidate_count",
    )

    def __init__(self):
        self.value = None
        self.text: str | None = None
        self.changed_at: float | None = None  # when the value last changed
        # when the role's value was last read (the clock's small moves)
        self.seen_at: float | None = None
        self.candidate = None
        self.candidate_text: str | None = None
        self.candidate_since = 0.0
        self.candidate_count = 0

    def offer(
        self,
        value,
        text: str,
        now: float,
        plausible: bool,
        confirm: int,
        hold_seconds: float = HOLD_SECONDS,
    ) -> bool:
        """A reading of value. True when it becomes the value: the first one,
        or a change read confirm times in a row (a change the sport doesn't
        allow: HOLD_READINGS times over hold_seconds)."""
        if value == self.value:
            self.text = text
            self.candidate = None
            return False
        if self.candidate is None or value != self.candidate:
            self.candidate = value
            self.candidate_text = text
            self.candidate_since = now
            self.candidate_count = 1
        else:
            self.candidate_count += 1
        if self.value is not None and not plausible:
            ready = (
                self.candidate_count >= HOLD_READINGS
                and now - self.candidate_since >= hold_seconds
            )
        else:
            ready = self.candidate_count >= confirm
        if not ready:
            return False
        self.value, self.text = self.candidate, self.candidate_text
        self.changed_at = now
        self.candidate = None
        return True

    def holds(
        self, value, now: float, plausible: bool, hold_seconds: float = HOLD_SECONDS
    ) -> bool:
        """Whether offer() would keep the value as it is after a reading of
        value: a change the sport doesn't allow, not read steadily for long
        enough yet (this reading included). Changes nothing."""
        if plausible or self.value is None or value == self.value:
            return False
        if self.candidate is not None and value == self.candidate:
            count, since = self.candidate_count + 1, self.candidate_since
        else:
            count, since = 1, now
        return not (count >= HOLD_READINGS and now - since >= hold_seconds)


class GameEngine:
    """Follows a game (see the module's docstring). Called on the GUI thread."""

    def __init__(
        self,
        sport: SportProfile = sports.NONE,
        clock=time.monotonic,
        wall_clock=time.time,
    ):
        self._clock = clock
        self._wall_clock = wall_clock
        self.sport = sport
        self.new_game()

    # --- settings -------------------------------------------------------------

    def set_sport(self, sport: SportProfile):
        """Follow another sport: a new game."""
        if sport != self.sport:
            self.sport = sport
            self.new_game()

    def new_game(self):
        """Forget the game: the values are learned again from the next
        readings (without events), the event log and the line score start
        over."""
        self._trackers = {role: _Tracker() for role in sports.ROLES}
        self._events: deque[GameEvent] = deque(maxlen=MAX_EVENTS)
        self._next_id = 1
        self._line: dict[int, list[int]] = {}  # {period: [home, away]}
        self._started_at_zero: bool | None = None
        self._ended: set[int] = set()  # periods whose end was an event
        self._last_end: tuple[int, float] | None = None  # (period, when)
        # the game is over: the final buzzer, or the finish of a lap race
        self._final = False
        self._final_lap = False  # the race's final lap was an event
        self._running = False
        self._direction = -1 if self.sport.clock_counts_down else 1  # -1: counts down
        self._against = 0  # clock moves against the direction, in a row
        self._last_update_at: float | None = None
        self._interval: float | None = None  # between updates (average)
        self._roles_for: tuple[tuple[str, ...], dict[str, str]] = ((), {})

    # --- the readings ---------------------------------------------------------

    def update(
        self, results: Iterable[TextDetectionTargetWithResult]
    ) -> list[GameEvent]:
        """Follow a cycle's results; returns the events they made."""
        if not self.sport.active:
            return []
        results = list(results)
        now = self._clock()
        if self._last_update_at is not None:
            gap = now - self._last_update_at
            self._interval = (
                gap if self._interval is None else (0.8 * self._interval + 0.2 * gap)
            )
        self._last_update_at = now
        roles = self.roles(result.name for result in results)
        by_name = {result.name: result for result in results}
        texts: dict[str, str] = {}
        for role, name in roles.items():
            result = by_name.get(name)
            if (
                result is None
                or result.result_state not in _GOOD_STATES
                or result.result is None
            ):
                continue
            text = str(result.result).strip()
            if text:
                texts[role] = text
        events: list[GameEvent] = []
        # the scores first: a score read with a new period still counts for
        # the period it was scored in
        for role in (HOME_SCORE, AWAY_SCORE):
            if role in texts:
                self._read_score(role, texts[role], now, events)
        for role, kind in (
            (HOME_FOULS, FOULS),
            (AWAY_FOULS, FOULS),
            (HOME_TIMEOUTS, TIMEOUTS),
            (AWAY_TIMEOUTS, TIMEOUTS),
        ):
            if role in texts:
                self._read_counter(role, kind, texts[role], now, events)
        # the total first: the finish of a race counting laps completed needs
        # it; the laps completed before the laps to go, whose events (with both
        # on the board) carry them
        if TOTAL_LAPS in texts:
            self._read_total_laps(texts[TOTAL_LAPS], now)
        for role in (LAPS_COMPLETED, LAPS_TO_GO):
            if role in texts:
                self._read_laps(role, texts[role], now, events)
        if PERIOD in texts:
            self._read_period(texts[PERIOD], now, events)
        if CLOCK in texts:
            self._read_clock(texts[CLOCK], now, events)
        if SHOT_CLOCK in texts:
            self._trackers[SHOT_CLOCK].text = texts[SHOT_CLOCK]
        self._check_clock_stopped(now, events)
        self._check_final(now, events)
        return events

    def roles(self, names: Iterable[str]) -> dict[str, str]:
        """{role: box name} for these boxes."""
        names = tuple(names)
        if names != self._roles_for[0]:
            self._roles_for = (names, sports.assign_roles(names, self.sport))
        return dict(self._roles_for[1])

    def held_back(
        self, results: Iterable[TextDetectionTargetWithResult], skip=frozenset()
    ) -> dict[str, str]:
        """{box name: why} for the good readings of a cycle that change a value
        the way the sport doesn't allow and haven't been read steadily for
        HOLD_SECONDS yet: update() won't count them yet, so the outputs
        shouldn't get them either (plausibility_holds.py). Call it before
        update() with the same readings. The boxes in skip aren't judged.
        Changes nothing."""
        if not self.sport.active:
            return {}
        results = list(results)
        now = self._clock()
        roles = self.roles(result.name for result in results)
        role_of = {name: role for role, name in roles.items()}
        held: dict[str, str] = {}
        for result in results:
            role = role_of.get(result.name)
            if (
                role is None
                or result.name in skip
                or result.result_state not in _GOOD_STATES
                or result.result is None
            ):
                continue
            text = str(result.result).strip()
            judged = self._judge(role, text, now) if text else None
            if judged is None:
                continue
            value, plausible = judged
            tracker = self._trackers[role]
            if tracker.holds(value, now, plausible, self._hold_seconds(role, value)):
                held[result.name] = self._hold_reason(role, tracker, value, text)
        return held

    def _hold_reason(self, role: str, tracker: "_Tracker", value, text: str) -> str:
        """Why a change isn't allowed, in English (the log)."""
        old = tracker.value
        if role in (HOME_SCORE, AWAY_SCORE):
            change = (
                "a score going down"
                if value < old
                else f"a score going up by {value - old}"
            )
        elif role in (HOME_FOULS, AWAY_FOULS, HOME_TIMEOUTS, AWAY_TIMEOUTS):
            change = f"a change of {value - old:+d}"
        elif role == CLOCK:
            change = f"the clock jumping from {tracker.text} to {text}"
        elif role == PERIOD:
            change = f"the period going from {tracker.text} to {text}"
        elif role in (LAPS_TO_GO, LAPS_COMPLETED):
            counter = "laps to go" if role == LAPS_TO_GO else "laps completed"
            change = f"the {counter} going from {old} to {value}"
            if self._hold_seconds(role, value) != HOLD_SECONDS:
                change += " (a lap card turned, not yet the other)"
        else:
            change = f"the total laps changing from {old} to {value}"
        return f"{change}, which {self.sport.name} doesn't allow"

    def _judge(self, role: str, text: str, now: float):
        """(the value read, whether the sport allows the change to it), or None
        when the text isn't a value of the role (or the role isn't judged: the
        shot clock, a clock in a sport without one)."""
        tracker = self._trackers[role]
        old = tracker.value
        if role in (HOME_SCORE, AWAY_SCORE):
            value = parse_count(text)
            if value is None:
                return None
            return value, old is None or (
                value - old in self.sport.score_steps
                or (self.sport.scores_reset_each_period and value == 0)
            )
        if role in (HOME_FOULS, AWAY_FOULS, HOME_TIMEOUTS, AWAY_TIMEOUTS):
            value = parse_count(text)
            if value is None:
                return None
            return value, old is None or abs(value - old) <= 1 or value == 0
        if role == PERIOD:
            value = parse_period(text, self.sport)
            if value is None:
                return None
            return value, old is None or value == old + 1
        if role == CLOCK:
            if self.sport.clock_counts_down is None:
                return None
            value = parse_clock(text)
            if value is None:
                return None
            return value, old is None or self._small_clock_move(
                old, value, tracker.seen_at, now
            )
        if role in (LAPS_TO_GO, LAPS_COMPLETED):
            value = parse_count(text)
            if value is None:
                return None
            # one lap the way the counter counts
            step = 1 if role == LAPS_COMPLETED else -1
            return value, old is None or value == old + step
        if role == TOTAL_LAPS:
            value = parse_count(text)
            if value is None:
                return None
            # the total doesn't change during a race: another one counts once
            # steady
            return value, old is None
        return None

    def _read_score(self, role: str, text: str, now: float, events: list):
        judged = self._judge(role, text, now)
        if judged is None:
            return
        value, plausible = judged
        tracker = self._trackers[role]
        old = tracker.value
        if not tracker.offer(value, text, now, plausible, CONFIRM_READINGS):
            return
        if old is None:
            self._note_first_scores()
            return
        if self.sport.scores_reset_each_period and value == 0:
            return  # a new set
        delta = value - old
        period = self._trackers[PERIOD].value
        if period is not None:
            line = self._line.setdefault(period, [0, 0])
            line[0 if TEAM_OF[role] == HOME else 1] += delta
        self._emit(SCORE, events, team=TEAM_OF[role], delta=delta, value=value)

    def _note_first_scores(self):
        """Whether the game was followed from 0-0 (the line score is
        complete), once both scores are known."""
        home = self._trackers[HOME_SCORE].value
        away = self._trackers[AWAY_SCORE].value
        if self._started_at_zero is None and home is not None and away is not None:
            period = self._trackers[PERIOD].value
            self._started_at_zero = home == 0 and away == 0 and period in (None, 1)

    def _read_counter(self, role: str, kind: str, text: str, now: float, events):
        judged = self._judge(role, text, now)
        if judged is None:
            return
        value, plausible = judged
        tracker = self._trackers[role]
        old = tracker.value
        if not tracker.offer(value, text, now, plausible, CONFIRM_READINGS):
            return
        if old is not None:
            self._emit(kind, events, team=TEAM_OF[role], delta=value - old, value=value)

    def _read_total_laps(self, text: str, now: float):
        judged = self._judge(TOTAL_LAPS, text, now)
        if judged is None:
            return
        value, plausible = judged
        self._trackers[TOTAL_LAPS].offer(value, text, now, plausible, CONFIRM_READINGS)

    def _read_laps(self, role: str, text: str, now: float, events: list):
        judged = self._judge(role, text, now)
        if judged is None:
            return
        value, plausible = judged
        tracker = self._trackers[role]
        old = tracker.value
        counts_down = role == LAPS_TO_GO
        # the laps raced by this change: a lap is 1
        raced = None if old is None else (old - value if counts_down else value - old)
        hold_seconds = self._hold_seconds(role, value)
        if not tracker.offer(
            value, text, now, plausible, CONFIRM_READINGS, hold_seconds
        ):
            return
        # with both counters on the board, the laps to go make the events
        if old is None or role != self._lap_counter():
            return
        if raced < -1 or (not counts_down and value == 0):
            # the board set for the next race (a lap back is a correction)
            self._final = self._final_lap = False
            self._emit(NEW_RACE, events, value=value)
            return
        self._emit(LAP, events, delta=raced, value=value)
        to_go = self._laps_to_go()
        if to_go is None:
            return
        if to_go > 0:
            self._final = False
        if to_go > 1:
            self._final_lap = False
        if to_go == 1 and not self._final_lap:
            self._final_lap = True
            self._emit(FINAL_LAP, events)
        if to_go <= 0 and not self._final:
            self._final = True
            self._emit(FINISH, events)

    def _hold_seconds(self, role: str, value) -> float:
        """How long a change the sport doesn't allow to value must be read
        steadily to count: longer for a lap board with only some of the cards
        of the next lap turned."""
        if role in (LAPS_TO_GO, LAPS_COMPLETED):
            old = self._trackers[role].value
            if old is not None:
                step = -1 if role == LAPS_TO_GO else 1
                if value in half_turned(old, old + step):
                    return CARD_TURN_HOLD_SECONDS
        return HOLD_SECONDS

    def _lap_counter(self) -> str | None:
        """The role of the lap counter that makes the events."""
        roles = self._roles_for[1]
        for role in (LAPS_TO_GO, LAPS_COMPLETED):
            if role in roles:
                return role
        return None

    def _laps_to_go(self) -> int | None:
        """The laps to go: read, or the total less the laps completed."""
        if self._lap_counter() == LAPS_TO_GO:
            return self._trackers[LAPS_TO_GO].value
        total = self._trackers[TOTAL_LAPS].value
        completed = self._trackers[LAPS_COMPLETED].value
        if total is None or completed is None:
            return None
        return total - completed

    def _read_period(self, text: str, now: float, events: list):
        judged = self._judge(PERIOD, text, now)
        if judged is None:
            return
        period, plausible = judged
        tracker = self._trackers[PERIOD]
        old = tracker.value
        if not tracker.offer(period, text, now, plausible, CONFIRM_READINGS):
            return
        self._line.setdefault(period, [0, 0])
        if old is None:
            self._note_first_scores()
            return
        self._end_period(old, now, events)
        self._emit(PERIOD_START, events)

    def _read_clock(self, text: str, now: float, events: list):
        judged = self._judge(CLOCK, text, now)
        if judged is None:
            return
        seconds, small = judged
        tracker = self._trackers[CLOCK]
        old = tracker.value
        counted = tracker.offer(seconds, text, now, small, 1)
        if counted or seconds == old:
            # the clock's value was read: a reading held back doesn't count,
            # or the clock, judged against a stale value from just now, could
            # never catch up while it runs
            tracker.seen_at = now
        if not counted:
            return
        if old is None:
            return
        if small:
            self._learn_direction(seconds - old)
            # only a move the way the clock counts starts it (a second back
            # is a misread, or the board being set)
            if not self._running and (seconds - old) * self._direction > 0:
                self._running = True
                self._emit(CLOCK_START, events)
        if seconds == 0 and self._direction < 0:
            self._end_period(self._trackers[PERIOD].value, now, events, at_zero=True)

    def _small_clock_move(self, old: float, new: float, seen_at, now: float) -> bool:
        """The clock ran (either way) for about the time since it was last
        read."""
        since = 0.0 if seen_at is None else max(0.0, now - seen_at)
        return abs(new - old) <= since * CLOCK_SLACK + CLOCK_MARGIN

    def _learn_direction(self, delta: float):
        """A clock set to count the other way (a soccer clock counting down)
        turns the direction around after CLOCK_TURN_MOVES moves."""
        if delta == 0:
            return
        if (delta > 0) == (self._direction > 0):
            self._against = 0
            return
        self._against += 1
        if self._against >= CLOCK_TURN_MOVES:
            self._direction = -self._direction
            self._against = 0

    def _check_clock_stopped(self, now: float, events: list):
        tracker = self._trackers[CLOCK]
        if not self._running or tracker.changed_at is None:
            return
        stop_after = max(CLOCK_STOP_SECONDS, 2.5 * (self._interval or 0.0))
        if now - tracker.changed_at > stop_after:
            self._running = False
            self._emit(CLOCK_STOP, events)

    def _end_period(self, period, now: float, events: list, at_zero=False):
        if period is None or period in self._ended:
            return
        self._ended.add(period)
        scores = {}
        if self.sport.scores_reset_each_period and period in self._line:
            # the board may show the next set's 0-0 already: the set's points
            scores = dict(zip(("home", "away"), self._line[period]))
        self._emit(PERIOD_END, events, period=period, **scores)
        if at_zero:
            self._last_end = (period, now)

    def _check_final(self, now: float, events: list):
        """The final buzzer: the clock reached 0:00 at the end of the last
        regular period (or of an overtime), and stayed there for
        FINAL_SETTLE_SECONDS (a last basket is counted first) with the
        scores not tied."""
        if self._final or self._last_end is None or not self.sport.periods:
            return
        period, ended_at = self._last_end
        if period < self.sport.periods or now - ended_at < FINAL_SETTLE_SECONDS:
            return
        if self._trackers[PERIOD].value != period or self._trackers[CLOCK].value != 0:
            return
        home = self._trackers[HOME_SCORE].value
        away = self._trackers[AWAY_SCORE].value
        if home is None or away is None or home == away:
            return
        self._final = True
        self._emit(FINAL, events)

    def _emit(self, kind: str, events: list, period=None, **fields):
        if period is None:
            period = self._trackers[PERIOD].value
        values = {
            "home": self._trackers[HOME_SCORE].value,
            "away": self._trackers[AWAY_SCORE].value,
            "laps_to_go": self._trackers[LAPS_TO_GO].value,
            "laps_completed": self._trackers[LAPS_COMPLETED].value,
            **fields,
        }
        event = GameEvent(
            id=self._next_id,
            kind=kind,
            at=self._wall_clock(),
            period=period,
            period_label=self.sport.period_label(period),
            clock=self._trackers[CLOCK].text,
            **values,
        )
        self._next_id += 1
        self._events.append(event)
        events.append(event)

    # --- what it knows --------------------------------------------------------

    @property
    def events(self) -> tuple[GameEvent, ...]:
        return tuple(self._events)

    def state(self) -> GameState:
        trackers = self._trackers
        period = trackers[PERIOD].value
        return GameState(
            sport=self.sport.key,
            roles=dict(self._roles_for[1]),
            home=trackers[HOME_SCORE].value,
            away=trackers[AWAY_SCORE].value,
            period=period,
            period_label=self.sport.period_label(period),
            clock=trackers[CLOCK].text,
            clock_running=self._running,
            shot_clock=trackers[SHOT_CLOCK].text,
            home_fouls=trackers[HOME_FOULS].value,
            away_fouls=trackers[AWAY_FOULS].value,
            home_timeouts=trackers[HOME_TIMEOUTS].value,
            away_timeouts=trackers[AWAY_TIMEOUTS].value,
            laps_to_go=trackers[LAPS_TO_GO].value,
            laps_completed=trackers[LAPS_COMPLETED].value,
            total_laps=trackers[TOTAL_LAPS].value,
            line_score=tuple(
                LinePeriod(p, self.sport.period_label(p), points[0], points[1])
                for p, points in sorted(self._line.items())
            ),
            line_score_complete=bool(self._started_at_zero),
            final=self._final,
            events=tuple(self._events),
        )
