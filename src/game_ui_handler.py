"""The Sport choice, New game and the game's status line, in the Box tab's All
boxes group: binds them to the "sport" setting and to the GameEngine that
MainWindow feeds with the readings (game_state.py), and writes the game's
events to the log. The events' texts on screen are translated here (the
engine's own texts, in the log and /game, are English).
"""

import time

from PySide6.QtCore import QCoreApplication

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
    GameEvent,
    GameState,
)
from sc_logging import logger
from storage import fetch_data, store_data

SETTINGS_FILE = "scoresight.json"
SETTINGS_KEY = "sport"
# the latest events, in the status line's tooltip
TOOLTIP_EVENTS = 12
# events logged at INFO (the clock's at DEBUG: they come at every whistle)
INFO_KINDS = (
    SCORE,
    PERIOD_START,
    PERIOD_END,
    FINAL,
    FOULS,
    TIMEOUTS,
    LAP,
    FINAL_LAP,
    FINISH,
    NEW_RACE,
)


def sport_names() -> dict[str, str]:
    """{sport key: its name in the current language}."""
    return {
        "none": QCoreApplication.translate("Sports", "None"),
        "basketball": QCoreApplication.translate("Sports", "Basketball"),
        "basketball_halves": QCoreApplication.translate(
            "Sports", "Basketball (halves)"
        ),
        "soccer": QCoreApplication.translate("Sports", "Soccer"),
        "futsal": QCoreApplication.translate("Sports", "Futsal"),
        "handball": QCoreApplication.translate("Sports", "Handball"),
        "hockey": QCoreApplication.translate("Sports", "Ice hockey"),
        "football": QCoreApplication.translate("Sports", "American football"),
        "volleyball": QCoreApplication.translate("Sports", "Volleyball"),
        "racing": QCoreApplication.translate("Sports", "Racing (laps)"),
    }


def team_name(team: str | None) -> str:
    if team == sports.HOME:
        return QCoreApplication.translate("Game", "Home")
    if team == sports.AWAY:
        return QCoreApplication.translate("Game", "Away")
    return ""


def score_text(home: int | None, away: int | None) -> str:
    """ "24–21" (home first)."""
    return f"{'?' if home is None else home}–{'?' if away is None else away}"


def event_text(event: GameEvent) -> str:
    """The event in the current language."""
    team = team_name(event.team)
    score = score_text(event.home, event.away)
    kind = event.kind
    if kind == SCORE:
        if event.delta is not None and event.delta < 0:
            return QCoreApplication.translate(
                "Game", "{team} score corrected to {value} ({score})"
            ).format(team=team, value=event.value, score=score)
        return QCoreApplication.translate("Game", "{team} +{points} ({score})").format(
            team=team, points=event.delta, score=score
        )
    if kind == PERIOD_START:
        return QCoreApplication.translate("Game", "Start of {period}").format(
            period=event.period_label
        )
    if kind == PERIOD_END:
        return QCoreApplication.translate("Game", "End of {period} ({score})").format(
            period=event.period_label, score=score
        )
    if kind == FINAL:
        return QCoreApplication.translate("Game", "Final ({score})").format(score=score)
    if kind == CLOCK_START:
        return QCoreApplication.translate("Game", "Clock started at {clock}").format(
            clock=event.clock
        )
    if kind == CLOCK_STOP:
        return QCoreApplication.translate("Game", "Clock stopped at {clock}").format(
            clock=event.clock
        )
    if kind == FOULS:
        return QCoreApplication.translate("Game", "{team} fouls: {count}").format(
            team=team, count=event.value
        )
    if kind == TIMEOUTS:
        return QCoreApplication.translate("Game", "{team} timeouts: {count}").format(
            team=team, count=event.value
        )
    if kind == LAP:
        corrected = event.delta is not None and event.delta < 0
        if event.laps_to_go is not None:
            text = (
                QCoreApplication.translate("Game", "Laps to go corrected to {laps}")
                if corrected
                else QCoreApplication.translate("Game", "Laps to go: {laps}")
            )
            return text.format(laps=event.laps_to_go)
        text = (
            QCoreApplication.translate("Game", "Laps completed corrected to {laps}")
            if corrected
            else QCoreApplication.translate("Game", "Laps completed: {laps}")
        )
        return text.format(laps=event.laps_completed)
    if kind == FINAL_LAP:
        return QCoreApplication.translate("Game", "Final lap")
    if kind == FINISH:
        return QCoreApplication.translate("Game", "Finish")
    if kind == NEW_RACE:
        return QCoreApplication.translate("Game", "New race")
    return kind


def status_text(state: GameState, sport: sports.SportProfile) -> str:
    """The status line: which fields are followed, and where the game is."""
    if not sport.active:
        return ""
    if not state.roles:
        if sport.counts_laps:
            return QCoreApplication.translate(
                "Game",
                "No field is named like the laps: name the lap board Laps To Go "
                "(or Laps Completed), and the race clock Time.",
            )
        return QCoreApplication.translate(
            "Game",
            "No field is named like a score, the clock or the period: name them "
            "like Home Score, Away Score, Time and Period.",
        )
    fields = [state.roles[role] for role in sports.ROLES if role in state.roles]
    lines = [
        QCoreApplication.translate("Game", "Follows {fields}").format(
            fields=", ".join(fields)
        )
    ]
    parts = []
    if state.period_label:
        parts.append(state.period_label)
    if state.home is not None or state.away is not None:
        parts.append(score_text(state.home, state.away))
    if state.laps_to_go is not None:
        parts.append(
            QCoreApplication.translate("Game", "{laps} laps to go").format(
                laps=state.laps_to_go
            )
        )
    elif state.laps_completed is not None:
        if state.total_laps is not None:
            parts.append(
                QCoreApplication.translate(
                    "Game", "{laps} of {total} laps completed"
                ).format(laps=state.laps_completed, total=state.total_laps)
            )
        else:
            parts.append(
                QCoreApplication.translate("Game", "{laps} laps completed").format(
                    laps=state.laps_completed
                )
            )
    if state.final and sport.counts_laps:
        parts.append(QCoreApplication.translate("Game", "finished"))
    elif state.final:
        parts.append(QCoreApplication.translate("Game", "final"))
    elif state.clock is not None:
        if state.clock_running:
            parts.append(QCoreApplication.translate("Game", "clock running"))
        else:
            parts.append(QCoreApplication.translate("Game", "clock stopped"))
    if parts:
        lines.append(" · ".join(parts))
    return "\n".join(lines)


def events_tooltip(events) -> str:
    """The latest events, newest first, with their times."""
    latest = list(events)[-TOOLTIP_EVENTS:]
    if not latest:
        return QCoreApplication.translate("Game", "No events yet")
    lines = [QCoreApplication.translate("Game", "Latest events:")]
    for event in reversed(latest):
        when = time.strftime("%H:%M:%S", time.localtime(event.at))
        lines.append(f"{when}  {event_text(event)}")
    return "\n".join(lines)


class GameUIHandler:
    def __init__(self, ui, engine: GameEngine):
        self.ui = ui
        self.engine = engine
        engine.set_sport(
            sports.profile(fetch_data(SETTINGS_FILE, SETTINGS_KEY, "none"))
        )
        self.fillSports()
        ui.comboBox_sport.currentIndexChanged.connect(self.sportChosen)
        ui.toolButton_newGame.clicked.connect(self.newGame)
        self.refresh()

    def fillSports(self):
        """The sports in the current language."""
        combo = self.ui.comboBox_sport
        names = sport_names()
        combo.blockSignals(True)
        try:
            combo.clear()
            for key in sports.PROFILES:
                combo.addItem(names[key], key)
            combo.setCurrentIndex(max(0, combo.findData(self.engine.sport.key)))
        finally:
            combo.blockSignals(False)

    def sportChosen(self, index: int):
        sport = sports.profile(self.ui.comboBox_sport.itemData(index))
        if sport == self.engine.sport:
            return
        store_data(SETTINGS_FILE, SETTINGS_KEY, sport.key)
        self.engine.set_sport(sport)
        logger.info("Game: following %s", sport.name)
        self.refresh()

    def newGame(self):
        self.engine.new_game()
        logger.info("Game: new game")
        self.refresh()

    def eventsHappened(self, events: list[GameEvent]):
        """Log the events a cycle made."""
        for event in events:
            where = " ".join(part for part in (event.period_label, event.clock) if part)
            message = f"Game: {event.text()}" + (f" [{where}]" if where else "")
            if event.kind in INFO_KINDS:
                logger.info(message)
            else:
                logger.debug(message)

    def refresh(self):
        """Once a second (and after a change): the status line."""
        sport = self.engine.sport
        self.ui.toolButton_newGame.setEnabled(sport.active)
        label = self.ui.label_gameStatus
        label.setVisible(sport.active)
        if not sport.active:
            return
        state = self.engine.state()
        text = status_text(state, sport)
        if label.text() != text:
            label.setText(text)
        label.setToolTip(events_tooltip(state.events))

    def retranslate(self):
        """After a language change."""
        self.fillSports()
        self.refresh()
