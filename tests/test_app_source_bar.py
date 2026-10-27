"""The viewer column's texts (src/source_bar.py) and the source's health
(status_bar.source_state)."""

import sys
import types

import pytest

import source_bar
from camera_info import CameraInfo
from status_bar import (
    SOURCE_ERROR,
    SOURCE_NONE,
    SOURCE_OPENING,
    SOURCE_RECONNECTING,
    SOURCE_RUNNING,
    SOURCE_SLOW,
    SOURCE_STALLED,
    StatusSnapshot,
    adjustments_text,
    source_look,
    source_state,
    source_text,
)


def source(kind, value, description=None):
    return CameraInfo(description or value, value, value, kind)


# --- what the source combo box shows -------------------------------------------------


def test_the_open_file_stream_or_screen_is_named():
    video = source(CameraInfo.CameraType.FILE, "C:\\Games\\final\\scoreboard.avi")
    assert source_bar.source_combo_text(video) == "Video file: scoreboard.avi"
    assert source_bar.source_full_name(video) == "C:\\Games\\final\\scoreboard.avi"

    stream = source(CameraInfo.CameraType.URL, "rtsp://admin:secret@10.0.1.200:554/11")
    # never the password
    assert source_bar.source_combo_text(stream) == "Stream: rtsp://10.0.1.200:554/11"
    assert "secret" not in source_bar.source_full_name(stream)

    screen = source(CameraInfo.CameraType.SCREEN_CAPTURE, 1234)
    assert source_bar.source_combo_text(screen, "OBS - Program") == (
        "Screen: OBS - Program"
    )
    entire = source(CameraInfo.CameraType.SCREEN_CAPTURE, source_bar.ENTIRE_SCREEN)
    assert source_bar.source_combo_text(entire) == "Screen: Entire screen"

    # a camera's item already shows its name
    camera = CameraInfo("Capture Card", "0", 0, CameraInfo.CameraType.OPENCV)
    assert source_bar.source_combo_text(camera) is None
    assert source_bar.source_full_name(camera) == "Capture Card"
    assert source_bar.source_combo_text(None) is None


def test_the_chooser_items_keep_their_order():
    # the indexes are those of mainwindow's SOURCE_INDEX_* constants
    assert source_bar.chooser_texts() == (
        "No source",
        "Video file…",
        "Stream URL (RTSP, HTTP)…",
        "Screen capture…",
        "Phone camera",
    )


@pytest.mark.parametrize(
    "kind, value, headline",
    [
        (CameraInfo.CameraType.FILE, "/videos/game.mp4", "Can't play the video file"),
        (CameraInfo.CameraType.URL, "rtsp://u:p@cam/1", "Can't open the stream"),
        (CameraInfo.CameraType.SCREEN_CAPTURE, 7, "Can't capture"),
        (CameraInfo.CameraType.NDI, "NDI Scoreboard", "Can't receive the NDI"),
        (CameraInfo.CameraType.PHONE, "phone", "Can't start the phone camera"),
        (CameraInfo.CameraType.OPENCV, "Capture Card", "Can't open Capture Card"),
    ],
)
def test_a_source_error_says_what_failed_and_what_to_do(kind, value, headline):
    what, hint = source_bar.source_error_text(source(kind, value))
    assert what.startswith(headline)
    assert hint
    assert ":p@" not in what


def test_the_playback_speeds_cycle():
    speeds = [1]
    for _ in range(6):
        speeds.append(source_bar.next_speed(speeds[-1]))
    assert speeds == [1, 2, 4, 8, 16, 32, 1]
    assert source_bar.next_speed(3) == 1  # an unknown speed starts over
    assert source_bar.speed_text(4) == "×4"


def test_readouts():
    assert source_bar.zoom_text(1.0) == "100%"
    assert source_bar.zoom_text(0.587) == "59%"
    assert source_bar.rotate_text(270) == "Rotate 90° · 270°"
    assert source_bar.rotate_text(None) == "Rotate 90° · 0°"
    assert source_bar.QUICKSTART_URL in source_bar.quickstart_link()


def test_the_four_corner_banner_counts_and_says_what_esc_does():
    text = source_bar.four_corner_banner_text(2, has_correction=True)
    assert "2 of 4" in text
    assert "keeps the previous correction" in text
    assert "previous" not in source_bar.four_corner_banner_text(0, False)


# --- macOS screen recording permission ------------------------------------------------


def test_screen_recording_permission_only_on_macos(monkeypatch):
    monkeypatch.setattr(source_bar.platform, "system", lambda: "Windows")
    assert source_bar.screen_recording_allowed() is None


@pytest.mark.parametrize("allowed", [True, False])
def test_screen_recording_permission_is_asked_without_a_prompt(monkeypatch, allowed):
    monkeypatch.setattr(source_bar.platform, "system", lambda: "Darwin")
    quartz = types.ModuleType("Quartz")
    quartz.CGPreflightScreenCaptureAccess = lambda: allowed
    monkeypatch.setitem(sys.modules, "Quartz", quartz)
    assert source_bar.screen_recording_allowed() is allowed


def test_screen_recording_permission_unknown_on_old_macos(monkeypatch):
    monkeypatch.setattr(source_bar.platform, "system", lambda: "Darwin")
    monkeypatch.setitem(sys.modules, "Quartz", types.ModuleType("Quartz"))
    assert source_bar.screen_recording_allowed() is None


# --- the source's health ---------------------------------------------------------------------


def running(**overrides):
    values = dict(
        has_source=True,
        first_frame=True,
        now=100.0,
        last_frame_at=99.9,
        fps=29.0,
        nominal_fps=30.0,
        failed_reads=0,
    )
    values.update(overrides)
    return source_state(**values)


def test_source_states():
    assert source_state(has_source=False) == SOURCE_NONE
    assert running() == SOURCE_RUNNING
    assert running(error=True) == SOURCE_ERROR
    assert running(first_frame=False) == SOURCE_OPENING
    # below half the source's own frame rate
    assert running(fps=14.0) == SOURCE_SLOW
    assert running(fps=16.0) == SOURCE_RUNNING
    # a source that doesn't tell its frame rate is never "slow"
    assert running(fps=2.0, nominal_fps=None) == SOURCE_RUNNING
    assert running(failed_reads=3) == SOURCE_RECONNECTING
    assert running(failed_reads=1) == SOURCE_RUNNING  # a video file looping
    assert running(last_frame_at=90.0) == SOURCE_STALLED


def test_the_health_dot_tells_the_state_by_shape_and_colour():
    assert source_look(SOURCE_RUNNING) == ("disc", "new")
    for state in (SOURCE_OPENING, SOURCE_SLOW, SOURCE_RECONNECTING, SOURCE_STALLED):
        assert source_look(state) == ("triangle", "rejected")
    assert source_look(SOURCE_ERROR) == ("square", "empty")
    assert source_look(SOURCE_NONE) == ("ring", None)


def test_the_status_bar_says_slow_and_reconnecting():
    slow = StatusSnapshot(
        source_name="cam", source_state=SOURCE_SLOW, fps=11.04, nominal_fps=30.0
    )
    assert "slow: 11.0 of 30 fps" in source_text(slow)
    reconnecting = StatusSnapshot(source_name="cam", source_state=SOURCE_RECONNECTING)
    assert source_text(reconnecting) == "cam: reconnecting…"


def test_the_source_tooltip_lists_the_picture_adjustments():
    assert adjustments_text(StatusSnapshot()) == ""
    snapshot = StatusSnapshot(
        rotation=90, cropped=True, four_corner_corrected=True, stabilized=True
    )
    assert adjustments_text(snapshot) == (
        "Adjust picture: rotated 90°, cropped, 4-corner corrected, stabilized"
    )
