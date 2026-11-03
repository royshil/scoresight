"""Sport profiles: what ScoreSight knows about a sport so that it can follow the
game (game_state.py): its fields (roles), how many regular periods it has and
what they are called, whether its clock counts down, and which score changes
make sense (basketball scores go up by 1, 2 or 3 at a time). A lap race has a
lap board instead of scores: laps to go and/or laps completed.

A box gets its role from its name (role_of): "Home Score", "Score Home" or
"Home" is the home score, "Time", "Clock" or "Game Clock" the clock, "Laps To
Go" or "Laps" the laps to go, and so on. The profiles' names are English; the
UI translates them (context "Sports").
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass

# roles
HOME_SCORE = "home_score"
AWAY_SCORE = "away_score"
CLOCK = "clock"
PERIOD = "period"
SHOT_CLOCK = "shot_clock"
HOME_FOULS = "home_fouls"
AWAY_FOULS = "away_fouls"
HOME_TIMEOUTS = "home_timeouts"
AWAY_TIMEOUTS = "away_timeouts"
LAPS_TO_GO = "laps_to_go"
LAPS_COMPLETED = "laps_completed"
TOTAL_LAPS = "total_laps"
# a game's roles
GAME_ROLES = (
    HOME_SCORE,
    AWAY_SCORE,
    CLOCK,
    PERIOD,
    SHOT_CLOCK,
    HOME_FOULS,
    AWAY_FOULS,
    HOME_TIMEOUTS,
    AWAY_TIMEOUTS,
)
# a lap race's lap board
LAP_ROLES = (LAPS_TO_GO, LAPS_COMPLETED, TOTAL_LAPS)
ROLES = GAME_ROLES + LAP_ROLES

HOME = "home"
AWAY = "away"
# the team of each per-team role
TEAM_OF = {
    HOME_SCORE: HOME,
    AWAY_SCORE: AWAY,
    HOME_FOULS: HOME,
    AWAY_FOULS: AWAY,
    HOME_TIMEOUTS: HOME,
    AWAY_TIMEOUTS: AWAY,
}

# The box names of each role, in lower case with letters and digits only
# ("Home Score" -> "homescore"); the standard boxes (defaults.py) first
_ROLE_NAMES = {
    HOME_SCORE: (
        "homescore",
        "scorehome",
        "home",
        "homepoints",
        "pointshome",
        "hometeam",
        "hometeamscore",
    ),
    AWAY_SCORE: (
        "awayscore",
        "scoreaway",
        "away",
        "guestscore",
        "scoreguest",
        "guest",
        "guests",
        "visitorscore",
        "visitorsscore",
        "scorevisitor",
        "scorevisitors",
        "visitor",
        "visitors",
        "awaypoints",
        "guestpoints",
        "awayteam",
        "awayteamscore",
    ),
    CLOCK: (
        "time",
        "clock",
        "gameclock",
        "gametime",
        "timer",
        "mainclock",
        "periodclock",
        "periodtime",
    ),
    PERIOD: ("period", "quarter", "qtr", "half", "set", "per", "periodnumber"),
    SHOT_CLOCK: (
        "shotclock",
        "shottime",
        "shot",
        "possessionclock",
        "attackclock",
        "attacktime",
        "playclock",
    ),
    HOME_FOULS: ("homefouls", "foulshome", "hometeamfouls", "homefoul", "foulhome"),
    AWAY_FOULS: (
        "awayfouls",
        "foulsaway",
        "awayteamfouls",
        "awayfoul",
        "foulaway",
        "guestfouls",
        "foulsguest",
        "guestfoul",
        "visitorfouls",
        "visitorsfouls",
        "foulsvisitor",
    ),
    HOME_TIMEOUTS: (
        "hometimeouts",
        "timeoutshome",
        "hometimeout",
        "hometol",
        "hometimeoutsleft",
    ),
    AWAY_TIMEOUTS: (
        "awaytimeouts",
        "timeoutsaway",
        "awaytimeout",
        "awaytol",
        "awaytimeoutsleft",
        "guesttimeouts",
        "timeoutsguest",
        "guesttimeout",
        "guesttol",
        "visitortimeouts",
        "visitorstimeouts",
    ),
    # a lap board counts down (lap cards, "5 to go"), so "Laps" is the laps to
    # go; "Lap" isn't a role: "Lap 5" may be the lap being raced or the laps
    # completed
    LAPS_TO_GO: (
        "lapstogo",
        "lapsremaining",
        "lapsleft",
        "remaininglaps",
        "ltg",
        "togo",
        "laps",
        "lapcards",
        "lapboard",
    ),
    LAPS_COMPLETED: (
        "lapscompleted",
        "lapscomplete",
        "completedlaps",
        "lapsdone",
        "lapcount",
    ),
    TOTAL_LAPS: ("totallaps", "lapstotal", "racelaps", "oflaps"),
}
_ROLE_OF_NAME = {name: role for role, names in _ROLE_NAMES.items() for name in names}


def name_key(name: str) -> str:
    """A box name in lower case with letters and digits only."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def role_of(name: str) -> str | None:
    """The role a box has by its name, or None."""
    return _ROLE_OF_NAME.get(name_key(name))


@dataclass(frozen=True)
class SportProfile:
    key: str
    name: str  # English; the UI translates it
    roles: tuple[str, ...]  # the roles the sport has
    # how much a team's score goes up at once
    score_steps: frozenset[int] = frozenset()
    periods: int = 0  # regular periods
    period_prefix: str = ""  # "Q" -> Q1, Q2...
    # True: the clock counts down (a period ends at 0:00), False: up, None:
    # no clock
    clock_counts_down: bool | None = None
    overtime: bool = True  # periods after the regular ones are overtime
    # the scores start again from 0 every period (volleyball sets)
    scores_reset_each_period: bool = False

    @property
    def active(self) -> bool:
        """A sport is chosen (not None)."""
        return bool(self.roles)

    @property
    def counts_laps(self) -> bool:
        """A lap race: a lap board instead of scores."""
        return LAPS_TO_GO in self.roles or LAPS_COMPLETED in self.roles

    def period_label(self, period: int | None) -> str:
        """ "Q2", "OT", "OT2", "Set 3"; "" without a period."""
        if period is None:
            return ""
        if self.overtime and self.periods and period > self.periods:
            extra = period - self.periods
            return "OT" if extra == 1 else f"OT{extra}"
        return f"{self.period_prefix}{period}"


_ALL = GAME_ROLES
NONE = SportProfile("none", "None", ())
BASKETBALL = SportProfile(
    "basketball",
    "Basketball",
    _ALL,
    frozenset({1, 2, 3}),
    periods=4,
    period_prefix="Q",
    clock_counts_down=True,
)
BASKETBALL_HALVES = SportProfile(
    "basketball_halves",
    "Basketball (halves)",
    _ALL,
    frozenset({1, 2, 3}),
    periods=2,
    period_prefix="H",
    clock_counts_down=True,
)
SOCCER = SportProfile(
    "soccer",
    "Soccer",
    (HOME_SCORE, AWAY_SCORE, CLOCK, PERIOD),
    frozenset({1}),
    periods=2,
    period_prefix="H",
    clock_counts_down=False,
)
# the clock stops with the ball and counts down from 20:00; the team fouls
# (accumulated fouls: from the sixth, a free kick from 10 m) go back to 0 at
# halftime; extra time is two halves of 5 minutes
FUTSAL = SportProfile(
    "futsal",
    "Futsal",
    (
        HOME_SCORE,
        AWAY_SCORE,
        CLOCK,
        PERIOD,
        HOME_FOULS,
        AWAY_FOULS,
        HOME_TIMEOUTS,
        AWAY_TIMEOUTS,
    ),
    frozenset({1}),
    periods=2,
    period_prefix="H",
    clock_counts_down=True,
)
# two halves of 30 minutes with the clock counting up (most boards: 0-30,
# then 30-60), goals one at a time, team timeouts (3 a game); extra time is
# two halves of 5 minutes. The 2-minute suspensions aren't followed: a board
# shows them as lights or as players' timers, not as one value per team.
HANDBALL = SportProfile(
    "handball",
    "Handball",
    (HOME_SCORE, AWAY_SCORE, CLOCK, PERIOD, HOME_TIMEOUTS, AWAY_TIMEOUTS),
    frozenset({1}),
    periods=2,
    period_prefix="H",
    clock_counts_down=False,
)
HOCKEY = SportProfile(
    "hockey",
    "Ice hockey",
    (HOME_SCORE, AWAY_SCORE, CLOCK, PERIOD, HOME_TIMEOUTS, AWAY_TIMEOUTS),
    frozenset({1}),
    periods=3,
    period_prefix="P",
    clock_counts_down=True,
)
FOOTBALL = SportProfile(
    "football",
    "American football",
    (HOME_SCORE, AWAY_SCORE, CLOCK, PERIOD, SHOT_CLOCK, HOME_TIMEOUTS, AWAY_TIMEOUTS),
    # a safety or a two-point conversion, a field goal, a touchdown (with the
    # extra point(s) when the board adds them at once)
    frozenset({1, 2, 3, 6, 7, 8}),
    periods=4,
    period_prefix="Q",
    clock_counts_down=True,
)
VOLLEYBALL = SportProfile(
    "volleyball",
    "Volleyball",
    (HOME_SCORE, AWAY_SCORE, PERIOD, HOME_TIMEOUTS, AWAY_TIMEOUTS),
    frozenset({1}),
    periods=5,
    period_prefix="Set ",
    overtime=False,
    scores_reset_each_period=True,
)
# one lap board everyone races to (track cycling, motorsport, skating,
# swimming, athletics), not a lap count per competitor
RACING = SportProfile(
    "racing",
    "Racing (laps)",
    (CLOCK, LAPS_TO_GO, LAPS_COMPLETED, TOTAL_LAPS),
    clock_counts_down=False,
    overtime=False,
)

PROFILES: dict[str, SportProfile] = {
    profile.key: profile
    for profile in (
        NONE,
        BASKETBALL,
        BASKETBALL_HALVES,
        SOCCER,
        FUTSAL,
        HANDBALL,
        HOCKEY,
        FOOTBALL,
        VOLLEYBALL,
        RACING,
    )
}


def profile(key) -> SportProfile:
    """The profile of a stored key (None for an unknown one)."""
    try:
        return PROFILES.get(key, NONE)
    except TypeError:  # e.g. a list in a hand-edited settings file
        return NONE


def assign_roles(names: Iterable[str], sport: SportProfile) -> dict[str, str]:
    """{role: box name} for the sport's roles: the first box with each role."""
    roles: dict[str, str] = {}
    for name in names:
        role = role_of(name)
        if role is not None and role in sport.roles and role not in roles:
            roles[role] = name
    return roles
