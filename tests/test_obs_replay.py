"""Save OBS's replay buffer after each score (src/obs_replay.py, issue #100) and
the request itself (obs_websocket.save_replay_buffer)."""

import logging
import threading
from types import SimpleNamespace

import pytest
import websocket
from obsws_python.error import OBSSDKRequestError
from PySide6.QtWidgets import QCheckBox, QSpinBox

import obs_replay
import obs_websocket
from game_state import CLOCK_STOP, SCORE, GameEvent
from obs_replay import ReplayOnScore
from output_worker import SendSkipped
from storage import fetch_data, store_data

pytestmark = pytest.mark.qt


def event(kind, id=1):
    return GameEvent(id, kind, 0.0, 1, "Q1", "5:00", 2, 0, team="home", delta=2)


class Saves:
    """Stands in for obs_websocket.save_replay_buffer: records the clients."""

    def __init__(self, error=None):
        self.error = error
        self.clients = []
        self.done = threading.Event()

    def __call__(self, client):
        self.clients.append(client)
        self.done.set()
        if self.error is not None:
            raise self.error


@pytest.fixture
def make_replay(qapp):
    made = []

    def make(client="obs", save=None, enabled=None, delay=None):
        if enabled is not None:
            store_data("scoresight.json", obs_replay.ENABLED_SETTING, enabled)
        if delay is not None:
            store_data("scoresight.json", obs_replay.DELAY_SETTING, delay)
        save = save or Saves()
        replay = ReplayOnScore(QCheckBox(), QSpinBox(), lambda: client, save)
        made.append(replay)
        return replay, save

    yield make
    for replay in made:
        replay.timer.stop()


def saved(qtbot, replay):
    qtbot.waitUntil(lambda: replay.thread is not None, timeout=5000)
    replay.thread.join(5)


def test_off_by_default_with_a_5_second_delay(make_replay):
    replay, save = make_replay()
    assert not replay.checkbox.isChecked()
    assert replay.spinbox.value() == 5
    replay.eventsHappened([event(SCORE)])
    assert not replay.pending()


def test_the_switch_and_the_delay_are_saved(make_replay):
    replay, _ = make_replay()
    replay.checkbox.setChecked(True)
    replay.spinbox.setValue(12)
    assert fetch_data("scoresight.json", obs_replay.ENABLED_SETTING) is True
    assert fetch_data("scoresight.json", obs_replay.DELAY_SETTING) == 12
    again, _ = make_replay()
    assert again.checkbox.isChecked()
    assert again.spinbox.value() == 12


@pytest.mark.parametrize("stored", ["7", -3, 600, True, None])
def test_a_stored_delay_that_is_not_valid(make_replay, stored):
    replay, _ = make_replay(delay=stored)
    expected = {-3: 0, 600: obs_replay.MAX_DELAY}.get(stored, obs_replay.DEFAULT_DELAY)
    assert replay.spinbox.value() == expected


def test_a_score_saves_the_replay_buffer_after_the_delay(make_replay, qtbot, caplog):
    replay, save = make_replay(enabled=True, delay=0)
    replay.eventsHappened([event(CLOCK_STOP)])
    assert not replay.pending()
    with caplog.at_level(logging.INFO):
        replay.eventsHappened([event(CLOCK_STOP), event(SCORE, id=2)])
        assert replay.pending()
        saved(qtbot, replay)
    assert save.clients == ["obs"]
    assert "saved the replay buffer" in caplog.text


def test_another_score_while_waiting_makes_one_clip(make_replay, qtbot):
    replay, save = make_replay(enabled=True, delay=1)
    replay.eventsHappened([event(SCORE)])
    remaining = replay.timer.remainingTime()
    qtbot.wait(300)
    replay.eventsHappened([event(SCORE, id=2)])
    # the wait started again
    assert replay.timer.remainingTime() > remaining - 300
    saved(qtbot, replay)
    qtbot.wait(100)
    assert save.clients == ["obs"]


def test_turning_it_off_cancels_a_waiting_save(make_replay):
    replay, save = make_replay(enabled=True, delay=1)
    replay.eventsHappened([event(SCORE)])
    replay.checkbox.setChecked(False)
    assert not replay.pending()


def test_without_obs_nothing_is_saved(make_replay, caplog):
    replay, save = make_replay(client=None, enabled=True)
    with caplog.at_level(logging.WARNING):
        replay.saveNow()
    assert replay.thread is None
    assert save.clients == []
    assert "not connected" in caplog.text


@pytest.mark.parametrize(
    "error, logged",
    [
        (obs_websocket.ReplayBufferOff(), "replay buffer isn't running"),
        (OSError("refused"), "couldn't save the replay buffer"),
    ],
)
def test_a_failed_save_is_logged(make_replay, qtbot, caplog, error, logged):
    replay, _ = make_replay(save=Saves(error), enabled=True)
    with caplog.at_level(logging.WARNING):
        replay.saveNow()
        saved(qtbot, replay)
    assert logged in caplog.text


def test_a_closed_connection_is_not_logged(make_replay, qtbot, caplog):
    replay, _ = make_replay(save=Saves(SendSkipped()), enabled=True)
    with caplog.at_level(logging.INFO):
        replay.saveNow()
        saved(qtbot, replay)
    assert "replay" not in caplog.text


# --- the request ------------------------------------------------------------


class FakeClient:
    def __init__(self, *errors):
        self.errors = list(errors)
        self.saves = 0
        self.base_client = SimpleNamespace(
            host="obs-pc", port=4455, password="pw", timeout=3
        )

    def save_replay_buffer(self):
        if self.errors:
            raise self.errors.pop(0)
        self.saves += 1


def test_save_replay_buffer_asks_obs():
    client = FakeClient()
    obs_websocket.save_replay_buffer(client)
    assert client.saves == 1


def test_a_replay_buffer_that_is_off_says_so():
    client = FakeClient(OBSSDKRequestError("SaveReplayBuffer", 501, ""))
    with pytest.raises(obs_websocket.ReplayBufferOff):
        obs_websocket.save_replay_buffer(client)


def test_other_obs_errors_are_raised():
    client = FakeClient(OBSSDKRequestError("SaveReplayBuffer", 600, "no"))
    with pytest.raises(OBSSDKRequestError):
        obs_websocket.save_replay_buffer(client)


def test_a_lost_connection_is_reestablished_once(monkeypatch):
    client = FakeClient(websocket.WebSocketConnectionClosedException("closed"))
    reconnected = []
    monkeypatch.setattr(obs_websocket, "_reconnect", reconnected.append)
    obs_websocket.save_replay_buffer(client)
    assert reconnected == [client]
    assert client.saves == 1


def test_a_closed_client_is_skipped():
    client = FakeClient()
    obs_websocket._closed_clients.add(client)
    with pytest.raises(SendSkipped):
        obs_websocket.save_replay_buffer(client)
    assert client.saves == 0
