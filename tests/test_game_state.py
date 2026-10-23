"""The game-state engine (game_state.py) and the sport profiles (sports.py):
reading the values, the roles of the boxes, and the events of whole game
sequences with a fake clock."""

import pytest

import game_state
import sports
from game_state import (
    CLOCK_START,
    CLOCK_STOP,
    FINAL,
    FINAL_LAP,
    FINISH,
    FOULS,
    LAP,
    NEW_RACE,
    PERIOD_END,
    PERIOD_START,
    SCORE,
    TIMEOUTS,
    GameEngine,
    parse_clock,
    parse_count,
    parse_period,
)


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def game(make_result):
    """game(sport) -> a Game that feeds readings to a GameEngine."""

    class Game:
        def __init__(self, sport):
            self.clock = FakeClock()
            self.engine = GameEngine(sport, clock=self.clock, wall_clock=lambda: 1.0)

        def read(self, step=0.5, states=None, **values):
            """One cycle, step seconds after the last one: {box name: text}
            (keyword arguments with "_" for spaces)."""
            self.clock.now += step
            states = states or {}
            results = []
            for key, text in values.items():
                name = key.replace("_", " ")
                results.append(
                    make_result(name, text, state=states.get(name, "Success"))
                )
            return self.engine.update(results)

        def kinds(self, events):
            return [event.kind for event in events]

    return Game


# --- reading the values ------------------------------------------------------------


@pytest.mark.parametrize(
    "text, expected",
    [
        ("21", 21),
        ("07", 7),
        (" 105 ", 105),
        ("1 2", 12),
        ("", None),
        ("2a", None),
        ("1234", None),
    ],
)
def test_parse_count(text, expected):
    assert parse_count(text) == expected


@pytest.mark.parametrize(
    "text, expected",
    [
        ("4:32", 272.0),
        ("12:00", 720.0),
        ("04:32", 272.0),
        ("45.3", 45.3),
        ("0:09.8", 9.8),
        ("9.8", 9.8),
        ("45", 45.0),
        ("0", 0.0),
        ("0.0", 0.0),
        ("90:00", 5400.0),
        ("1:02:03", 3723.0),
        ("4:72", None),
        ("abc", None),
        ("", None),
    ],
)
def test_parse_clock(text, expected):
    result = parse_clock(text)
    if expected is None:
        assert result is None
    else:
        assert result == pytest.approx(expected)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("2", 2),
        ("2nd", 2),
        ("Q2", 2),
        ("P3", 3),
        ("Set 4", 4),
        ("OT", 5),
        ("ot", 5),
        ("OT2", 6),
        ("2OT", 6),
        ("", None),
        ("H", None),
        ("0", None),
    ],
)
def test_parse_period(text, expected):
    assert parse_period(text, sports.BASKETBALL) == expected


def test_overtime_is_after_the_regular_periods():
    assert parse_period("OT", sports.HOCKEY) == 4
    assert parse_period("OT", sports.VOLLEYBALL) is None  # no overtime


# --- sports and roles ----------------------------------------------------------------


def test_roles_from_box_names():
    role_of = sports.role_of
    assert role_of("Home Score") == sports.HOME_SCORE
    assert role_of("score_home") == sports.HOME_SCORE
    assert role_of("GUEST") == sports.AWAY_SCORE
    assert role_of("Visitors Score") == sports.AWAY_SCORE
    assert role_of("Game Clock") == sports.CLOCK
    assert role_of("Time") == sports.CLOCK
    assert role_of("Quarter") == sports.PERIOD
    assert role_of("Shot Clock") == sports.SHOT_CLOCK
    assert role_of("Home Fouls") == sports.HOME_FOULS
    assert role_of("Guest TOL") == sports.AWAY_TIMEOUTS
    assert role_of("Laps To Go") == sports.LAPS_TO_GO
    assert role_of("LTG") == sports.LAPS_TO_GO
    assert role_of("laps_remaining") == sports.LAPS_TO_GO
    assert role_of("Laps") == sports.LAPS_TO_GO
    assert role_of("Laps Completed") == sports.LAPS_COMPLETED
    assert role_of("Total Laps") == sports.TOTAL_LAPS
    # the lap being raced, or the laps completed: not a role
    assert role_of("Lap") is None
    assert role_of("Sponsor") is None


def test_every_standard_box_has_a_role():
    from defaults import default_boxes

    assert all(sports.role_of(box["name"]) for box in default_boxes)


def test_assign_roles_follows_the_sport_and_takes_the_first_box():
    names = ["Home Score", "Home", "Away Score", "Time", "Home Fouls"]
    assert sports.assign_roles(names, sports.BASKETBALL) == {
        sports.HOME_SCORE: "Home Score",
        sports.AWAY_SCORE: "Away Score",
        sports.CLOCK: "Time",
        sports.HOME_FOULS: "Home Fouls",
    }
    # soccer has no fouls on the board
    assert sports.HOME_FOULS not in sports.assign_roles(names, sports.SOCCER)
    assert sports.assign_roles(names, sports.NONE) == {}
    # a race has no scores, a game no laps
    names = ["Home Score", "Time", "Laps To Go", "Total Laps"]
    assert sports.assign_roles(names, sports.RACING) == {
        sports.CLOCK: "Time",
        sports.LAPS_TO_GO: "Laps To Go",
        sports.TOTAL_LAPS: "Total Laps",
    }
    assert sports.LAPS_TO_GO not in sports.assign_roles(names, sports.BASKETBALL)


def test_profiles():
    assert sports.profile("basketball") is sports.BASKETBALL
    assert sports.profile("curling") is sports.NONE
    assert sports.profile(["basketball"]) is sports.NONE
    assert not sports.NONE.active and sports.BASKETBALL.active
    assert sports.BASKETBALL.period_label(2) == "Q2"
    assert sports.BASKETBALL.period_label(5) == "OT"
    assert sports.BASKETBALL.period_label(6) == "OT2"
    assert sports.BASKETBALL.period_label(None) == ""
    assert sports.SOCCER.period_label(2) == "H2"
    assert sports.HOCKEY.period_label(3) == "P3"
    assert sports.VOLLEYBALL.period_label(5) == "Set 5"
    assert sports.profile("racing") is sports.RACING
    assert sports.RACING.counts_laps and not sports.BASKETBALL.counts_laps


# --- a basketball game ----------------------------------------------------------------


def start_basketball(game, home="0", away="0", period="1", time="8:00"):
    g = game(sports.BASKETBALL)
    for _ in range(2):
        assert g.read(Home_Score=home, Away_Score=away, Period=period, Time=time) == []
    return g


def test_no_sport_follows_nothing(game):
    g = game(sports.NONE)
    for score in ("0", "2", "2"):
        assert g.read(Home_Score=score) == []
    assert g.engine.state().home is None


def test_the_first_readings_make_no_events(game):
    g = start_basketball(game, home="34", away="30", period="3", time="5:12")
    state = g.engine.state()
    assert (state.home, state.away, state.period, state.clock) == (34, 30, 3, "5:12")
    assert state.period_label == "Q3"
    assert g.engine.events == ()


def test_a_score_counts_once_read_twice(game):
    g = start_basketball(game)
    assert g.read(Home_Score="2", Away_Score="0", Period="1", Time="8:00") == []
    events = g.read(Home_Score="2", Away_Score="0", Period="1", Time="8:00")
    assert g.kinds(events) == [SCORE]
    event = events[0]
    assert (event.team, event.delta, event.value) == ("home", 2, 2)
    assert (event.home, event.away, event.period_label, event.clock) == (
        2,
        0,
        "Q1",
        "8:00",
    )
    assert event.text() == "Home +2 (2–0)"


def test_same_no_change_confirms_a_score(game):
    g = start_basketball(game)
    g.read(Away_Score="3", Home_Score="0")
    events = g.read(
        Away_Score="3", Home_Score="0", states={"Away Score": "SameNoChange"}
    )
    assert [(e.team, e.delta) for e in events] == [("away", 3)]


def test_a_flicker_makes_no_event(game):
    g = start_basketball(game, home="21")
    g.read(Home_Score="81")
    g.read(Home_Score="21")
    g.read(Home_Score="21")
    assert g.engine.events == ()
    assert g.engine.state().home == 21


def test_rejected_readings_neither_count_nor_reset(game):
    g = start_basketball(game)
    g.read(Home_Score="2")
    g.read(Home_Score="?", states={"Home Score": "FailedFilter"})
    assert g.kinds(g.read(Home_Score="2")) == [SCORE]


def test_a_change_the_sport_does_not_allow_waits(game):
    g = start_basketball(game, home="21")
    # +60 (21 -> 81): read steadily, it counts after HOLD_SECONDS
    for _ in range(5):
        assert g.read(step=0.5, Home_Score="81") == []
    events = g.read(step=1.0, Home_Score="81")
    assert [(e.kind, e.delta) for e in events] == [(SCORE, 60)]


def test_a_correction_counts_after_the_hold(game):
    g = start_basketball(game, home="24")
    for _ in range(10):
        events = g.read(step=0.5, Home_Score="22")
        if events:
            break
    assert [(e.kind, e.delta, e.value) for e in events] == [(SCORE, -2, 22)]
    assert events[0].text() == "Home score corrected to 22 (22–0)"


def test_the_clock_starts_and_stops(game):
    g = start_basketball(game, time="8:00")
    events = g.read(step=1.0, Time="7:59")
    assert g.kinds(events) == [CLOCK_START]
    assert g.engine.state().clock_running
    g.read(step=1.0, Time="7:58")
    g.read(step=1.0, Time="7:57")
    # stopped: the same time for longer than the clock's stop delay (at least
    # CLOCK_STOP_SECONDS, longer when the boxes are read less often)
    assert g.read(step=1.0, Time="7:57") == []
    events = []
    for _ in range(3):
        events += g.read(step=1.0, Time="7:57")
    assert g.kinds(events) == [CLOCK_STOP]
    assert events[0].clock == "7:57"
    assert not g.engine.state().clock_running


def test_a_second_back_does_not_start_the_clock(game):
    g = start_basketball(game, time="4:32")
    assert g.read(step=1.0, Time="4:33") == []
    assert g.engine.state().clock == "4:33"
    assert g.kinds(g.read(step=1.0, Time="4:32")) == [CLOCK_START]


def test_a_clock_jump_waits(game):
    g = start_basketball(game, time="7:00")
    # 7:00 -> 1:00 in a second: a misread, or the clock being set
    assert g.read(step=1.0, Time="1:00") == []
    assert g.engine.state().clock == "7:00"


def test_a_quarter_ends_at_zero_and_the_next_starts(game):
    g = start_basketball(game, home="10", away="8", time="0:02")
    g.read(step=1.0, Time="0:01")
    events = g.read(step=1.0, Time="0.0")
    assert g.kinds(events) == [PERIOD_END]
    assert events[0].text() == "End of Q1 (10–8)"
    # the board goes to the second quarter: no second end
    g.read(step=1.0, Period="2", Time="8:00")
    events = g.read(step=1.0, Period="2", Time="8:00")
    # (and the clock has stood at 0.0 long enough to count as stopped)
    assert g.kinds(events) == [PERIOD_START, CLOCK_STOP]
    assert events[0].text() == "Start of Q2"
    assert g.kinds(g.engine.events).count(PERIOD_END) == 1


def test_final_after_the_last_period_unless_tied(game):
    g = start_basketball(game, home="60", away="58", period="4", time="0:01")
    g.read(step=1.0, Time="0.0")
    # a last basket counts first: the final waits a few seconds
    g.read(step=1.0, Home_Score="60", Away_Score="61", Time="0.0")
    g.read(step=1.0, Home_Score="60", Away_Score="61", Time="0.0")
    g.read(step=2.0, Home_Score="60", Away_Score="61", Time="0.0")
    final = [e for e in g.engine.events if e.kind == FINAL]
    assert len(final) == 1 and final[0].text() == "Final (60–61)"
    assert g.engine.state().final

    tied = start_basketball(game, home="60", away="60", period="4", time="0:01")
    tied.read(step=1.0, Time="0.0")
    for _ in range(5):
        tied.read(step=1.0, Time="0.0")
    assert FINAL not in tied.kinds(tied.engine.events)


def test_overtime_ends_the_game(game):
    g = start_basketball(game, home="70", away="70", period="OT", time="0:01")
    g.read(step=1.0, Home_Score="72", Time="0.0")
    g.read(step=1.0, Home_Score="72", Time="0.0")
    for _ in range(4):
        g.read(step=1.0, Home_Score="72", Time="0.0")
    assert FINAL in g.kinds(g.engine.events)


def test_the_line_score(game):
    g = start_basketball(game)
    assert g.engine.state().line_score_complete
    for home, away in (("2", "0"), ("2", "3"), ("5", "3")):
        g.read(Home_Score=home, Away_Score=away)
        g.read(Home_Score=home, Away_Score=away)
    for _ in range(2):
        g.read(Period="2", Home_Score="5", Away_Score="3")
    for _ in range(2):
        g.read(Period="2", Home_Score="5", Away_Score="5")
    lines = [(p.label, p.home, p.away) for p in g.engine.state().line_score]
    assert lines == [("Q1", 5, 3), ("Q2", 0, 2)]


def test_a_game_joined_late_has_a_partial_line_score(game):
    g = start_basketball(game, home="34", away="30", period="3")
    assert not g.engine.state().line_score_complete


def test_fouls_and_timeouts(game):
    g = start_basketball(game)
    for _ in range(2):
        g.read(Home_Fouls="3", Away_Timeouts="4")
    for _ in range(2):
        events = g.read(Home_Fouls="4", Away_Timeouts="3")
    assert [(e.kind, e.team, e.value, e.delta) for e in events] == [
        (FOULS, "home", 4, 1),
        (TIMEOUTS, "away", 3, -1),
    ]
    assert events[0].text() == "Home fouls: 4"
    # back to 0 at halftime is allowed
    for _ in range(2):
        events = g.read(Home_Fouls="0", Away_Timeouts="3")
    assert [(e.kind, e.value) for e in events] == [(FOULS, 0)]


def test_new_game_and_another_sport_start_over(game):
    g = start_basketball(game)
    g.read(Home_Score="2")
    g.read(Home_Score="2")
    assert g.engine.events
    g.engine.new_game()
    assert g.engine.events == () and g.engine.state().home is None
    g.engine.set_sport(sports.SOCCER)
    assert g.engine.state().sport == "soccer"


# --- other sports ---------------------------------------------------------------------


def test_volleyball_sets(game):
    g = game(sports.VOLLEYBALL)
    for _ in range(2):
        g.read(Home_Score="0", Away_Score="0", Set="1")
    for home, away in (("24", "20"),):
        # fast-forward: hold the jump to 24-20
        for _ in range(8):
            g.read(Home_Score=home, Away_Score=away, Set="1")
    for _ in range(2):
        g.read(Home_Score="25", Away_Score="20", Set="1")
    # the board goes to set 2: the scores go back to 0 (not a correction)
    events = []
    for _ in range(2):
        events += g.read(Home_Score="0", Away_Score="0", Set="2")
    assert g.kinds(events) == [PERIOD_END, PERIOD_START]
    assert events[0].text() == "End of Set 1 (25–20)"
    assert all(e.delta is None or e.delta > 0 for e in g.engine.events)
    lines = [(p.label, p.home, p.away) for p in g.engine.state().line_score]
    assert lines == [("Set 1", 25, 20), ("Set 2", 0, 0)]


def test_soccer_clock_counts_up_and_halves(game):
    g = game(sports.SOCCER)
    for _ in range(2):
        g.read(Home_Score="0", Away_Score="0", Period="1", Time="44:58")
    events = g.read(step=1.0, Time="44:59")
    assert g.kinds(events) == [CLOCK_START]
    g.read(step=1.0, Time="45:00")
    for _ in range(2):
        events = g.read(step=1.0, Period="2", Time="45:00")
    assert PERIOD_END in g.kinds(events) and PERIOD_START in g.kinds(events)
    assert FINAL not in g.kinds(g.engine.events)


def test_a_clock_counting_the_other_way_is_learned(game):
    # a youth soccer board counting down: after a few moves it is learned,
    # and 0:00 ends the half
    g = game(sports.SOCCER)
    for _ in range(2):
        g.read(Period="1", Time="0:05")
    for time_ in ("0:04", "0:03", "0:02", "0:01"):
        g.read(step=1.0, Time=time_)
    events = g.read(step=1.0, Time="0:00")
    assert g.kinds(events) == [PERIOD_END]


def start_futsal(game, home="0", away="0", period="1", time="20:00", fouls="0"):
    g = game(sports.FUTSAL)
    for _ in range(2):
        assert (
            g.read(
                Home_Score=home,
                Away_Score=away,
                Period=period,
                Time=time,
                Home_Fouls=fouls,
                Away_Fouls=fouls,
            )
            == []
        )
    return g


def test_futsal_follows_the_team_fouls_and_a_clock_counting_down(game):
    g = start_futsal(game, home="3", away="1", time="0:02")
    for _ in range(2):
        events = g.read(step=1.0, Home_Fouls="1")
    assert [(e.kind, e.team, e.value) for e in events] == [(FOULS, "home", 1)]
    g.read(step=1.0, Time="0:01")
    events = g.read(step=1.0, Time="0:00")
    assert g.kinds(events) == [PERIOD_END]
    assert events[0].text() == "End of H1 (3–1)"
    # the second half: the team fouls go back to 0
    for _ in range(2):
        events = g.read(step=1.0, Period="2", Time="20:00", Home_Fouls="0")
    assert sorted(g.kinds(events)) == [FOULS, PERIOD_START]


def test_futsal_ends_at_0_00_of_the_second_half(game):
    g = start_futsal(game, home="3", away="1", period="2", time="0:01")
    for _ in range(4):
        g.read(step=1.0, Time="0:00")
    final = [e for e in g.engine.events if e.kind == FINAL]
    assert len(final) == 1 and final[0].text() == "Final (3–1)"


def test_futsal_scores_go_up_one_goal_at_a_time(game, cycle):
    # a dot-matrix 3 misread as 9 (#136) is held back from the outputs
    g = start_futsal(game, home="3", away="1", time="2:15")
    held, events = cycle(g, Home_Score="9")
    assert (
        held == {"Home Score": "a score going up by 6, which Futsal doesn't allow"}
        and events == []
    )
    assert cycle(g, Home_Score="4") == ({}, [])
    held, events = cycle(g, Home_Score="4")
    assert held == {} and [(e.kind, e.delta) for e in events] == [(SCORE, 1)]


# --- a lap race -----------------------------------------------------------------------


def start_race(game, **values):
    g = game(sports.RACING)
    for _ in range(2):
        assert g.read(**values) == []
    return g


def read_board(g, times, **values):
    """The same readings times in a row; the events they made."""
    events = []
    for _ in range(times):
        events += g.read(**values)
    return events


def test_a_race_counting_laps_to_go(game):
    g = start_race(game, Laps_To_Go="3", Time="0:40")
    events = read_board(g, 2, Laps_To_Go="2")
    assert [(e.kind, e.delta, e.value, e.laps_to_go) for e in events] == [
        (LAP, 1, 2, 2)
    ]
    assert events[0].text() == "Laps to go: 2"
    events = read_board(g, 2, Laps_To_Go="1")
    assert g.kinds(events) == [LAP, FINAL_LAP]
    assert events[1].text() == "Final lap"
    events = read_board(g, 2, Laps_To_Go="0")
    assert g.kinds(events) == [LAP, FINISH]
    assert events[1].text() == "Finish"
    state = g.engine.state()
    assert state.final and state.laps_to_go == 0
    # the race clock counts up
    assert g.kinds(g.read(step=1.0, Time="0:41")) == [CLOCK_START]


def test_lap_card_misreads_make_no_events(game):
    # what PP-OCR read off hand-flipped lap cards: a hand over the 0 (99), a
    # card half turned (88), the gap between two cards read as a 1 (919)
    g = start_race(game, Laps_To_Go="10")
    for text in ("99", "99", "1", "88", "919", "919", "11", "11"):
        assert g.read(Laps_To_Go=text) == []
    # 10 to 09 turns both cards: 19 while only the units card is turned
    events = read_board(g, 3, Laps_To_Go="19") + read_board(g, 2, Laps_To_Go="09")
    assert [(e.kind, e.value) for e in events] == [(LAP, 9)]


def test_numbers_of_half_turned_lap_cards():
    assert game_state.half_turned(20, 19) == {10, 29}
    assert game_state.half_turned(10, 9) == {0, 19}
    assert game_state.half_turned(9, 10) == {19, 0}
    assert game_state.half_turned(100, 99) == {0, 190, 109, 90, 9, 199}
    # one card turned for the lap: nothing in between
    assert game_state.half_turned(12, 11) == set()
    assert game_state.half_turned(0, -1) == set()


def test_a_lap_turning_two_cards_one_at_a_time(game):
    # #125's 45-lap video, read by PP-OCR every 0.2 s: 20 to 19 showed 10
    # (the tens card turned first) for 3.2 s, then the units card turning
    g = start_race(game, Laps_To_Go="20")
    events = []
    for _ in range(17):
        events += g.read(step=0.2, Laps_To_Go="10")
    for text in ("13", "15"):
        events += g.read(step=0.2, Laps_To_Go=text)
    assert events == []
    events = read_board(g, 2, Laps_To_Go="19")
    assert [(e.kind, e.delta, e.value) for e in events] == [(LAP, 1, 19)]
    # 10 to 09 showed 00 (a finish!) for about 2 s; a slower hand: 10 s
    g = start_race(game, Laps_To_Go="10")
    assert read_board(g, 20, Laps_To_Go="00") == []
    events = read_board(g, 2, Laps_To_Go="09")
    assert [(e.kind, e.value) for e in events] == [(LAP, 9)]
    assert not g.engine.state().final
    # the units card turned first: 19
    g = start_race(game, Laps_To_Go="10")
    assert read_board(g, 20, Laps_To_Go="19") == []
    assert g.kinds(read_board(g, 2, Laps_To_Go="09")) == [LAP]
    # laps completed: 19 to 20 shows 10 or 29
    g = start_race(game, Laps_Completed="19")
    assert read_board(g, 20, Laps_Completed="10") == []
    assert read_board(g, 20, Laps_Completed="29") == []
    events = read_board(g, 2, Laps_Completed="20")
    assert [(e.kind, e.delta, e.value) for e in events] == [(LAP, 1, 20)]


def test_a_lap_card_left_half_turned_counts_after_a_while(game):
    g = start_race(game, Laps_To_Go="20")
    seconds = game_state.CARD_TURN_HOLD_SECONDS
    assert read_board(g, int(seconds / 0.5), Laps_To_Go="10") == []
    events = read_board(g, 2, Laps_To_Go="10")
    assert [(e.kind, e.delta, e.value) for e in events] == [(LAP, 10, 10)]


def test_a_lap_board_corrected(game):
    g = start_race(game, Laps_To_Go="12")
    # two cards turned at once: counts once read steadily for 3 s
    assert read_board(g, 5, Laps_To_Go="10") == []
    events = read_board(g, 3, Laps_To_Go="10")
    assert [(e.kind, e.delta) for e in events] == [(LAP, 2)]
    # and put back: a lap back is a correction
    events = read_board(g, 8, Laps_To_Go="11")
    assert [(e.kind, e.delta, e.value) for e in events] == [(LAP, -1, 11)]
    assert events[0].text() == "Laps to go corrected to 11"


def test_a_new_race(game):
    g = start_race(game, Laps_To_Go="1")
    assert g.kinds(read_board(g, 2, Laps_To_Go="0")) == [LAP, FINISH]
    # the board set for the next race: once read steadily for 3 s
    assert read_board(g, 4, Laps_To_Go="5") == []
    events = read_board(g, 4, Laps_To_Go="5")
    assert [(e.kind, e.value) for e in events] == [(NEW_RACE, 5)]
    assert events[0].text() == "New race"
    assert not g.engine.state().final
    for to_go in ("4", "3", "2", "1"):
        events = read_board(g, 2, Laps_To_Go=to_go)
    assert g.kinds(events) == [LAP, FINAL_LAP]
    # a race started again before the finish
    assert g.kinds(read_board(g, 8, Laps_To_Go="20")) == [NEW_RACE]
    assert g.kinds(read_board(g, 2, Laps_To_Go="19")) == [LAP]


def test_a_race_counting_laps_completed(game):
    g = start_race(game, Laps_Completed="0", Total_Laps="3")
    events = read_board(g, 2, Laps_Completed="1", Total_Laps="3")
    assert [(e.kind, e.delta, e.value) for e in events] == [(LAP, 1, 1)]
    assert events[0].text() == "Laps completed: 1"
    events = read_board(g, 2, Laps_Completed="2", Total_Laps="3")
    assert g.kinds(events) == [LAP, FINAL_LAP]
    events = read_board(g, 2, Laps_Completed="3", Total_Laps="3")
    assert g.kinds(events) == [LAP, FINISH]
    # back to 0: the next race
    events = read_board(g, 8, Laps_Completed="0", Total_Laps="3")
    assert g.kinds(events) == [NEW_RACE]
    # a lap back is a correction
    g.read(Laps_Completed="1")
    g.read(Laps_Completed="1")
    events = read_board(g, 8, Laps_Completed="2")
    events = read_board(g, 8, Laps_Completed="1")
    assert [(e.kind, e.delta) for e in events] == [(LAP, -1)]
    assert events[0].text() == "Laps completed corrected to 1"


def test_laps_completed_without_a_total_have_no_finish(game):
    g = start_race(game, Laps_Completed="4")
    for completed in ("5", "6", "7"):
        assert g.kinds(read_board(g, 2, Laps_Completed=completed)) == [LAP]
    assert g.engine.state().total_laps is None


def test_both_lap_counters_make_one_lap(game):
    g = start_race(game, Laps_To_Go="2", Laps_Completed="8")
    events = read_board(g, 2, Laps_To_Go="1", Laps_Completed="9")
    assert g.kinds(events) == [LAP, FINAL_LAP]
    assert (events[0].laps_to_go, events[0].laps_completed) == (1, 9)
    assert events[0].text() == "Laps to go: 1"
    data = g.engine.state().to_dict()
    assert data["sport"] == "racing"
    assert data["laps"] == {"to_go": 1, "completed": 9, "total": None}
    assert data["home"]["score"] is None
    assert [e["kind"] for e in data["events"]] == ["lap", "final_lap"]
    assert data["events"][0]["laps_to_go"] == 1


# --- the snapshot ---------------------------------------------------------------------


def test_state_to_dict(game):
    g = start_basketball(game)
    g.read(Home_Score="3", Home_Fouls="1", Shot_Clock="14")
    g.read(Home_Score="3", Home_Fouls="1", Shot_Clock="14")
    data = g.engine.state().to_dict()
    assert data["sport"] == "basketball"
    assert data["home"] == {"score": 3, "fouls": 1, "timeouts": None}
    assert data["away"]["score"] == 0
    assert data["period_label"] == "Q1"
    assert data["shot_clock"] == "14"
    assert data["roles"]["home_score"] == "Home Score"
    assert data["laps"] == {"to_go": None, "completed": None, "total": None}
    assert data["line_score"] == [{"period": 1, "label": "Q1", "home": 3, "away": 0}]
    assert [event["text"] for event in data["events"]] == ["Home +3 (3–0)"]
    last = data["events"][-1]["id"]
    assert g.engine.state().to_dict(since=last)["events"] == []


def test_the_event_log_is_capped(game, monkeypatch):
    monkeypatch.setattr(game_state, "MAX_EVENTS", 3)
    g = start_basketball(game)
    for score in range(1, 6):
        g.read(Home_Score=str(score))
        g.read(Home_Score=str(score))
    events = g.engine.events
    assert [e.value for e in events] == [3, 4, 5]
    assert events[-1].id == 5


# --- the UI's texts ----------------------------------------------------------------------


def test_every_sport_has_a_translatable_name(qapp):
    from game_ui_handler import sport_names

    names = sport_names()
    assert set(names) == set(sports.PROFILES)
    assert names["hockey"] == "Ice hockey"


def test_the_ui_texts_match_the_engine_in_english(game, qapp):
    from game_ui_handler import event_text

    g = start_basketball(game, home="60", away="58", period="4", time="0:02")
    for _ in range(2):
        g.read(step=1.0, Home_Score="57", Home_Fouls="3", Away_Timeouts="2")
    for _ in range(8):
        g.read(
            step=1.0, Home_Score="57", Home_Fouls="4", Away_Timeouts="1", Time="0:01"
        )
    g.read(step=1.0, Home_Score="57", Time="0.0")
    for _ in range(5):
        g.read(step=1.0, Home_Score="57", Time="0.0")
    kinds = set(g.kinds(g.engine.events))
    assert {SCORE, FOULS, TIMEOUTS, CLOCK_START, CLOCK_STOP, PERIOD_END, FINAL} <= kinds
    for event in g.engine.events:
        assert event_text(event) == event.text()


def test_status_text(game, qapp):
    from game_ui_handler import status_text

    g = start_basketball(game, home="24", away="21", period="2", time="4:32")
    assert status_text(g.engine.state(), sports.BASKETBALL) == (
        "Follows Home Score, Away Score, Time, Period\nQ2 · 24–21 · clock stopped"
    )
    g.read(step=1.0, Time="4:31")
    assert status_text(g.engine.state(), sports.BASKETBALL).endswith("clock running")
    assert status_text(g.engine.state(), sports.NONE) == ""
    other = game(sports.BASKETBALL)
    other.read(Sponsor="ACME")
    assert status_text(other.engine.state(), sports.BASKETBALL).startswith(
        "No field is named like a score"
    )


def test_the_race_texts_match_the_engine_in_english(game, qapp):
    from game_ui_handler import event_text

    to_go = start_race(game, Laps_To_Go="12")
    read_board(to_go, 8, Laps_To_Go="10")
    read_board(to_go, 8, Laps_To_Go="11")
    for laps in ("10", "1", "0", "5"):
        read_board(to_go, 8, Laps_To_Go=laps)
    completed = start_race(game, Laps_Completed="3", Total_Laps="5")
    for laps in ("4", "3", "5"):
        read_board(completed, 8, Laps_Completed=laps, Total_Laps="5")
    events = to_go.engine.events + completed.engine.events
    assert {LAP, FINAL_LAP, FINISH, NEW_RACE} <= {e.kind for e in events}
    texts = {e.text() for e in events}
    assert {"Laps to go corrected to 11", "Laps completed corrected to 3"} <= texts
    for event in events:
        assert event_text(event) == event.text()


def test_race_status_text(game, qapp):
    from game_ui_handler import status_text

    g = start_race(game, Time="1:02", Laps_To_Go="5")
    assert status_text(g.engine.state(), sports.RACING) == (
        "Follows Time, Laps To Go\n5 laps to go · clock stopped"
    )
    g = start_race(game, Laps_To_Go="1")
    read_board(g, 2, Laps_To_Go="0")
    assert status_text(g.engine.state(), sports.RACING).endswith(
        "0 laps to go · finished"
    )
    g = start_race(game, Laps_Completed="7", Total_Laps="20")
    assert status_text(g.engine.state(), sports.RACING).endswith(
        "\n7 of 20 laps completed"
    )
    g = start_race(game, Laps_Completed="7")
    assert status_text(g.engine.state(), sports.RACING).endswith("\n7 laps completed")
    other = game(sports.RACING)
    other.read(Home_Score="3")
    assert status_text(other.engine.state(), sports.RACING).startswith(
        "No field is named like the laps"
    )


# --- held back from the outputs -------------------------------------------------------


@pytest.fixture
def cycle(game, make_result):
    """cycle(g, step=0.5, skip=(), **values) -> (held_back, events): one cycle as
    MainWindow.ocrResult runs it."""

    def run(g, step=0.5, skip=frozenset(), **values):
        g.clock.now += step
        results = [
            make_result(key.replace("_", " "), text) for key, text in values.items()
        ]
        held = g.engine.held_back(results, skip=skip)
        return held, g.engine.update(results)

    return run


def test_a_change_the_sport_allows_is_not_held_back(game, cycle):
    g = start_basketball(game, home="21")
    assert cycle(g, Home_Score="23") == ({}, [])
    held, events = cycle(g, Home_Score="23")
    assert held == {} and g.kinds(events) == [SCORE]


def test_a_flicker_is_held_back(game, cycle):
    g = start_basketball(game, home="21")
    held, events = cycle(g, Home_Score="81")
    assert held == {
        "Home Score": "a score going up by 60, which Basketball doesn't allow"
    }
    assert events == []
    assert cycle(g, Home_Score="21") == ({}, [])
    held, _ = cycle(g, Home_Score="19")
    assert held["Home Score"].startswith("a score going down")


def test_a_correction_is_held_back_until_the_game_counts_it(game, cycle):
    g = start_basketball(game, home="21")
    for _ in range(6):  # 0.5 s apart: not 3 s yet
        held, events = cycle(g, Home_Score="18")
        assert "Home Score" in held and events == []
    # read steadily for 3 s: counted, and no longer held back
    held, events = cycle(g, Home_Score="18")
    assert held == {} and g.kinds(events) == [SCORE]
    assert events[0].text() == "Home score corrected to 18 (18–0)"


def test_held_back_judges_every_followed_field(game, cycle):
    g = start_basketball(game, period="2", time="8:00")
    held, _ = cycle(g, Period="4", Time="1:00", Home_Fouls="0", Shot_Clock="99")
    assert held == {
        "Period": "the period going from 2 to 4, which Basketball doesn't allow",
        "Time": "the clock jumping from 8:00 to 1:00, which Basketball doesn't allow",
    }
    # the fouls are known once read twice; the shot clock isn't judged
    cycle(g, Home_Fouls="0")
    held, _ = cycle(g, Home_Fouls="5")
    assert held == {"Home Fouls": "a change of +5, which Basketball doesn't allow"}
    # a clock that runs isn't held back
    assert cycle(g, step=1.0, Time="7:59")[0] == {}


def test_a_running_clock_held_back_catches_up(game, cycle):
    # read 5 times a second; 5:26 was taken for 5:25 (skip similar image), so
    # 5:27 comes 0.2 s after a 5:25: held back, but the clock runs on and is
    # sent again a reading later, not judged against 5:25 "just read" forever
    # (#140)
    g = game(sports.SOCCER)
    for _ in range(6):
        cycle(g, step=0.2, Time="5:25")
    held, _ = cycle(g, step=0.2, Time="5:27")
    assert held == {
        "Time": "the clock jumping from 5:25 to 5:27, which Soccer doesn't allow"
    }
    held, events = cycle(g, step=0.2, Time="5:27")
    assert held == {} and g.kinds(events) == [CLOCK_START]
    for clock in ("5:27", "5:27", "5:28", "5:28", "5:28", "5:28", "5:28", "5:29"):
        assert cycle(g, step=0.2, Time=clock)[0] == {}
    assert g.engine.state().clock == "5:29"
    # a misread is still held back
    held, _ = cycle(g, step=0.2, Time="5:39")
    assert "Time" in held and g.engine.state().clock == "5:29"


def test_held_back_skips_and_follows_no_sport(game, cycle, make_result):
    g = start_basketball(game, home="21")
    assert cycle(g, skip={"Home Score"}, Home_Score="81")[0] == {}
    assert cycle(game(sports.NONE), Home_Score="81")[0] == {}
    # rejected readings aren't judged
    results = [make_result("Home Score", "8l", "FailedFilter")]
    assert g.engine.held_back(results) == {}


def test_lap_board_misreads_are_held_back(game, cycle):
    g = start_race(game, Laps_To_Go="10")
    held, _ = cycle(g, Laps_To_Go="99")
    assert held == {
        "Laps To Go": "the laps to go going from 10 to 99, which Racing (laps) "
        "doesn't allow"
    }
    assert cycle(g, Laps_To_Go="9")[0] == {}


def test_a_half_turned_lap_board_is_held_back_longer(game, cycle):
    # the outputs mustn't get 10 while 20 to 19 is turned one card at a time
    g = start_race(game, Laps_To_Go="20")
    for _ in range(12):
        held, events = cycle(g, Laps_To_Go="10")
        assert events == []
    assert held == {
        "Laps To Go": "the laps to go going from 20 to 10 (a lap card turned, not "
        "yet the other), which Racing (laps) doesn't allow"
    }
    assert cycle(g, Laps_To_Go="19") == ({}, [])
