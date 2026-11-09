"""Save OBS's replay buffer a few seconds after each score (issue #100): after
the game, OBS's replay folder holds a clip of every score, with the scorebug.

ReplayOnScore binds the OBS page's switch and delay (the settings
obs_replay_on_score and obs_replay_delay) and gets the game's events from
MainWindow, so only the scores the game counts save a clip (a sport must be
chosen). A score while a save waits restarts the wait, so one clip shows both.
The request runs on a daemon thread and its outcome is logged.
"""

import threading
from collections.abc import Callable, Iterable

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QCheckBox, QSpinBox

import obs_websocket
from game_state import SCORE, GameEvent
from output_worker import SendSkipped
from sc_logging import logger
from storage import fetch_data, store_data

SETTINGS_FILE = "scoresight.json"
ENABLED_SETTING = "obs_replay_on_score"
DELAY_SETTING = "obs_replay_delay"
DEFAULT_DELAY = 5  # seconds
MAX_DELAY = 60


def stored_delay() -> int:
    """The stored delay in seconds, or the default if it isn't a valid one."""
    delay = fetch_data(SETTINGS_FILE, DELAY_SETTING, DEFAULT_DELAY)
    if isinstance(delay, bool) or not isinstance(delay, int):
        return DEFAULT_DELAY
    return min(max(delay, 0), MAX_DELAY)


class ReplayOnScore(QObject):
    def __init__(
        self,
        checkbox: QCheckBox,
        spinbox: QSpinBox,
        client: Callable[[], object],
        save: Callable[[object], None] = obs_websocket.save_replay_buffer,
        parent: QObject | None = None,
    ):
        """client() gives the current OBS connection (None if there's none);
        save(client) asks OBS to save its replay buffer (blocking)."""
        super().__init__(parent)
        self.checkbox = checkbox
        self.spinbox = spinbox
        self.client = client
        self.save = save
        # the last save's thread, for tests
        self.thread: threading.Thread | None = None
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.saveNow)

        spinbox.setRange(0, MAX_DELAY)
        checkbox.setChecked(fetch_data(SETTINGS_FILE, ENABLED_SETTING, False) is True)
        spinbox.setValue(stored_delay())
        checkbox.toggled.connect(self.enabledChanged)
        spinbox.valueChanged.connect(
            lambda value: store_data(SETTINGS_FILE, DELAY_SETTING, int(value))
        )

    def enabledChanged(self, enabled: bool):
        store_data(SETTINGS_FILE, ENABLED_SETTING, bool(enabled))
        if not enabled:
            self.timer.stop()

    def eventsHappened(self, events: Iterable[GameEvent]):
        """The game's events of a cycle: a score (re)starts the wait."""
        if not self.checkbox.isChecked():
            return
        if any(event.kind == SCORE for event in events):
            self.timer.start(self.spinbox.value() * 1000)

    def pending(self) -> bool:
        return self.timer.isActive()

    def saveNow(self):
        client = self.client()
        if client is None:
            logger.warning(
                "OBS: not connected, so the replay buffer wasn't saved after the score"
            )
            return
        self.thread = threading.Thread(
            target=self._save, args=(client,), name="OBS replay", daemon=True
        )
        self.thread.start()

    def _save(self, client):
        try:
            self.save(client)
        except SendSkipped:
            # the connection was closed meanwhile
            return
        except obs_websocket.ReplayBufferOff:
            logger.warning(
                "OBS: the replay buffer isn't running, so no clip was saved after "
                "the score. Start it in OBS: Controls > Start Replay Buffer."
            )
        except Exception as e:
            logger.warning(
                "OBS: couldn't save the replay buffer after the score: "
                f"{type(e).__name__}: {e}"
            )
        else:
            logger.info("OBS: saved the replay buffer after the score")
