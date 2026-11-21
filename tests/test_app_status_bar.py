"""The main window's status bar: what it says for a StatusSnapshot."""

import pytest

from camera_info import CameraInfo
from status_bar import (
    SOURCE_ERROR,
    SOURCE_NONE,
    SOURCE_OPENING,
    SOURCE_RUNNING,
    SOURCE_STALLED,
    StatusSnapshot,
    format_duration,
    http_server_urls,
    http_text,
    ocr_is_slow,
    ocr_text,
    paused_text,
    primary_lan_address,
    source_display_name,
    source_text,
    without_credentials,
)

RUNNING = StatusSnapshot(
    source_name="scoreboard.avi",
    source_state=SOURCE_RUNNING,
    resolution=(1280, 720),
    fps=32.51,
    ocr_rate=4.74,
    ocr_target=5,
    http_url="http://192.168.1.20:18099",
    http_urls=("http://192.168.1.20:18099", "http://localhost:18099"),
    http_port=18099,
)


def test_a_running_source():
    assert source_text(RUNNING) == "scoreboard.avi · 1280×720 · 32.5 fps"
    assert ocr_text(RUNNING) == "Reading 4.7/s of 5"
    assert not ocr_is_slow(RUNNING)
    assert paused_text(RUNNING) == ""
    assert http_text(RUNNING) == "http://192.168.1.20:18099"


@pytest.mark.parametrize(
    ("state", "text"),
    [
        (SOURCE_NONE, "No source"),
        (SOURCE_OPENING, "Opening scoreboard.avi…"),
        (SOURCE_STALLED, "scoreboard.avi: no new frames"),
        (SOURCE_ERROR, "scoreboard.avi: can't be read"),
    ],
)
def test_source_states(state, text):
    snapshot = StatusSnapshot(source_name="scoreboard.avi", source_state=state)
    assert source_text(snapshot) == text
    # the OCR rate only while frames arrive
    assert ocr_text(snapshot) == ""


def test_a_slow_ocr_rate_is_flagged():
    slow = StatusSnapshot(
        source_name="cam", source_state=SOURCE_RUNNING, ocr_rate=2.0, ocr_target=5
    )
    assert ocr_is_slow(slow)
    assert ocr_text(slow) == "Reading 2.0/s of 5"


def test_paused_time():
    assert paused_text(StatusSnapshot(paused_seconds=134.4)) == "PAUSED 02:14"
    assert format_duration(3725) == "1:02:05"


def test_a_busy_http_port():
    assert http_text(StatusSnapshot(http_port=18099)) == (
        "HTTP server not running (port 18099 busy)"
    )


def test_http_server_urls():
    assert http_server_urls(18099, "10.0.0.5") == (
        "http://10.0.0.5:18099",
        "http://localhost:18099",
    )
    assert http_server_urls(18100, None) == ("http://localhost:18100",)


def test_the_lan_address_is_an_ipv4_address_or_none():
    address = primary_lan_address()
    assert address is None or address.count(".") == 3


def test_source_names():
    # as the main window makes them: description, uuid and id are the path/URL
    path = "C:\\games\\final.mp4"
    file = CameraInfo(path, path, path, CameraInfo.CameraType.FILE)
    assert source_display_name(file) == "final.mp4"
    stream = "rtsp://user:secret@10.0.1.200:554/11"
    url = CameraInfo(stream, stream, stream, CameraInfo.CameraType.URL)
    # a stream's password never shows
    assert source_display_name(url) == "rtsp://10.0.1.200:554/11"
    screen = CameraInfo(-1, -1, -1, CameraInfo.CameraType.SCREEN_CAPTURE)
    assert source_display_name(screen) == "Screen capture"
    camera = CameraInfo("USB Camera", "uuid", 0, CameraInfo.CameraType.OPENCV)
    assert source_display_name(camera) == "USB Camera"
    assert source_display_name(None) is None


def test_without_credentials():
    assert without_credentials("http://a:b@host/x?y=1") == "http://host/x?y=1"
    assert without_credentials("rtsp://host:554/s") == "rtsp://host:554/s"


@pytest.mark.qt
def test_the_status_bar_widgets(qapp, monkeypatch):
    from PySide6.QtGui import QPalette
    from PySide6.QtWidgets import QApplication, QStatusBar

    from status_bar import MainStatusBar

    statusbar = QStatusBar()
    widgets = MainStatusBar(statusbar)
    try:
        widgets.update(RUNNING)
        assert "scoreboard.avi · 1280×720" in widgets.label_source.text()
        assert widgets.label_ocr.text() == "Reading 4.7/s of 5"
        assert widgets.label_paused.isHidden()
        assert widgets.label_http.text() == "http://192.168.1.20:18099"
        assert "http://localhost:18099" in widgets.label_http.toolTip()
        widgets.button_copy.click()
        assert QApplication.clipboard().text() == "http://192.168.1.20:18099"

        widgets.update(StatusSnapshot(paused_seconds=5, http_port=18099))
        assert not widgets.label_paused.isHidden()
        assert widgets.label_paused.text() == "PAUSED 00:05"
        assert widgets.label_ocr.isHidden()
        assert "No source" in widgets.label_source.text()
        assert "not running" in widgets.label_http.text()
        assert widgets.button_copy.isHidden()

        # Feedback, always there, in the link colour (it opens a web page)
        feedback = []
        widgets.feedback_clicked.connect(lambda: feedback.append(True))
        assert not widgets.button_feedback.isHidden()
        assert widgets.button_feedback.text() == "Feedback"
        assert "Discussions" in widgets.button_feedback.toolTip()
        link = statusbar.palette().color(QPalette.ColorRole.Link).name()
        assert link in widgets.button_feedback.styleSheet()
        assert not widgets.button_feedback.icon().isNull()
        widgets.button_feedback.click()
        assert feedback == [True]
    finally:
        statusbar.deleteLater()


@pytest.mark.qt
def test_the_outputs_summary(qapp):
    from PySide6.QtWidgets import QStatusBar

    from output_status import DESTINATIONS, DestinationStatus
    from status_bar import MainStatusBar

    statusbar = QStatusBar()
    widgets = MainStatusBar(statusbar)
    clicked = []
    widgets.destination_clicked.connect(clicked.append)
    try:
        assert widgets.widget_outputs.isHidden()  # nothing to show yet
        outputs = (
            DestinationStatus("files", "ok", "Writing to D:\\Scores · 4 files", True),
            DestinationStatus("http", "ok", "http://x:18099", True, switchable=False),
            DestinationStatus("obs", "off", "Not connected"),
            DestinationStatus(
                "vmix",
                "retrying",
                "Can't reach 192.168.1.40:8088 · retrying",
                True,
                hint="Check that vMix is running.",
                last_activity_at=97.0,
            ),
            DestinationStatus("uno", "off", "Off"),
            DestinationStatus("api", "error", "HTTP 401: access denied", True),
            DestinationStatus("tcp", "off", "Off"),
            DestinationStatus("team_performance", "off", "Off"),
        )
        widgets.update(StatusSnapshot(outputs=outputs, now=100.0, http_port=18099))
        assert not widgets.widget_outputs.isHidden()
        assert widgets.label_outputs.text().strip() == "Outputs:"
        buttons = widgets.output_buttons
        assert list(buttons) == list(DESTINATIONS)
        assert [b.text() for b in buttons.values()] == [
            "Files",
            "HTTP",
            "OBS",
            "vMix",
            "UNO",
            "API",
            "TCP",
            "TP",
        ]
        tooltip = buttons["vmix"].toolTip().splitlines()
        assert tooltip[:4] == [
            "vMix: ▲ retrying",
            "Can't reach 192.168.1.40:8088 · retrying",
            "Check that vMix is running.",
            "Last sent 3 s ago",
        ]
        assert buttons["api"].accessibleName() == "API: not working"
        assert all(not b.icon().isNull() for b in buttons.values())

        buttons["vmix"].click()
        buttons["files"].click()
        assert clicked == ["vmix", "files"]
    finally:
        statusbar.deleteLater()


# --- the OCR engine --------------------------------------------------------------------


def engine(**values):
    from dataclasses import replace

    return replace(RUNNING, **values)


def test_while_ppocr_loads():
    import ppocr_engine
    from status_bar import ocr_tooltip

    snapshot = engine(ocr_model="ppocr:auto", ocr_engine_state=ppocr_engine.LOADING)
    assert ocr_text(snapshot) == "Loading PP-OCR…"
    assert not ocr_is_slow(engine(**{**snapshot.__dict__, "ocr_rate": 0.1}))
    assert "loading" in ocr_tooltip(snapshot)


def test_a_ppocr_that_didnt_load():
    import ppocr_engine
    from status_bar import ocr_fallback, ocr_tooltip

    snapshot = engine(
        ocr_model="ppocr:small",
        ocr_engine_state=ppocr_engine.FAILED,
        ocr_engine_error="ImportError: DLL load failed",
    )
    assert ocr_fallback(snapshot)
    assert (
        ocr_text(snapshot) == "Reading 4.7/s of 5 · with Tesseract: PP-OCR didn't load"
    )
    assert "DLL load failed" in ocr_tooltip(snapshot)
    assert "Tesseract (General Scoreboard)" in ocr_tooltip(snapshot)


@pytest.mark.parametrize(
    ("model", "state", "accurate_slow"),
    [
        ("ppocr:small", "ready", True),
        ("ppocr:auto", "ready", False),
        ("ppocr:tiny", "ready", False),
        (1, None, False),
    ],
)
def test_the_cpu_advice_is_for_ppocr_accurate(model, state, accurate_slow):
    from status_bar import ocr_tooltip, ppocr_accurate_is_slow

    snapshot = engine(ocr_model=model, ocr_engine_state=state, ocr_rate=2.0)
    assert ocr_is_slow(snapshot)
    assert ppocr_accurate_is_slow(snapshot) is accurate_slow
    tooltip = ocr_tooltip(snapshot)
    assert ("Choose PP-OCR (fast)" in tooltip) is accurate_slow
    assert ("lower Detections / s, use fewer boxes" in tooltip) is not accurate_slow


@pytest.mark.parametrize(
    ("model", "reason", "accurate_ms", "interval_ms", "text"),
    [
        (None, None, None, None, ""),
        (
            "ppocr:small",
            "starting",
            None,
            200.0,
            "PP-OCR automatic: accurate (measuring how long it needs here)",
        ),
        (
            "ppocr:small",
            "keeps up",
            41.6,
            200.0,
            "PP-OCR automatic: accurate (it needs 42 ms per reading here, of the "
            "200 ms between readings)",
        ),
        (
            "ppocr:tiny",
            "too slow",
            110.0,
            100.0,
            "PP-OCR automatic: fast (accurate needs 110 ms per reading here, more "
            "than 70% of the 100 ms between readings)",
        ),
        (
            "ppocr:tiny",
            "unavailable",
            None,
            None,
            "PP-OCR automatic: fast (accurate didn't load)",
        ),
    ],
)
def test_what_automatic_reads_with(model, reason, accurate_ms, interval_ms, text):
    from status_bar import ocr_tooltip, ppocr_auto_text, snapshot_auto_text

    assert ppocr_auto_text(model, reason, accurate_ms, interval_ms) == text
    snapshot = engine(
        ocr_model="ppocr:auto",
        ocr_engine_state="ready",
        ocr_auto_model=model,
        ocr_auto_reason=reason,
        ocr_auto_accurate_ms=accurate_ms,
        ocr_auto_interval_ms=interval_ms,
    )
    assert snapshot_auto_text(snapshot) == text
    if text:
        assert text in ocr_tooltip(snapshot)
    # only for automatic
    assert snapshot_auto_text(engine(**{**snapshot.__dict__, "ocr_model": 1})) == ""
