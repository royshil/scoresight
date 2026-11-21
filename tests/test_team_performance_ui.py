"""The actual output page, its settings, URLs and output-list status."""

import pytest
from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication, QStackedWidget

import http_server
import output_status
from storage import SETTINGS_FILE, fetch_data, store_data
from team_performance import TimingConfig
from team_performance_ui_handler import SETTINGS_KEY, TeamPerformanceUIHandler

pytestmark = pytest.mark.qt


@pytest.fixture
def page(qtbot, monkeypatch):
    store_data(SETTINGS_FILE, SETTINGS_KEY, {})
    parent = QObject()
    parent.lanAddress = "192.168.0.182"
    stack = QStackedWidget()
    qtbot.addWidget(stack)
    handler = TeamPerformanceUIHandler(stack, parent)
    monkeypatch.setattr(http_server, "get_http_server_port", lambda: 18099)
    handler.refresh()
    yield handler
    http_server.configure_team_performance(TimingConfig())
    http_server.update_http_server([])
    store_data(SETTINGS_FILE, SETTINGS_KEY, {})


def test_urls_copy_and_custom_port(page, monkeypatch):
    assert (
        page.ui.lineEdit_scoreboardUrl.text()
        == "http://192.168.0.182:18099/timeclock/time-as-array"
    )
    assert page.ui.lineEdit_shotClockUrl.text() == "http://192.168.0.182:18099/time"
    page.ui.pushButton_copyScoreboard.click()
    assert QApplication.clipboard().text() == page.ui.lineEdit_scoreboardUrl.text()
    monkeypatch.setattr(http_server, "get_http_server_port", lambda: 18100)
    page.refresh()
    assert ":18100/time" in page.ui.lineEdit_shotClockUrl.text()
    page.parent().lanAddress = None
    page.refresh()
    assert "127.0.0.1:18100" in page.ui.lineEdit_scoreboardUrl.text()


def test_persist_mapping_and_enable(page):
    page.setBoxNames(["Match", "Possession"])
    page.ui.comboBox_scoreboardField.setCurrentText("Match")
    page.ui.comboBox_shotClockField.setCurrentText("Possession")
    page.ui.checkBox_enabled.setChecked(True)
    assert fetch_data(SETTINGS_FILE, SETTINGS_KEY) == {
        "enabled": True,
        "scoreboard_field": "Match",
        "shot_clock_field": "Possession",
    }
    page.setBoxNames([])
    assert page.ui.comboBox_scoreboardField.currentText() == "Match"
    assert page.ui.comboBox_shotClockField.currentText() == "Possession"
    stack = QStackedWidget()
    restored = TeamPerformanceUIHandler(stack, page.parent())
    assert restored.config == page.config
    restored.retranslate()
    assert restored.ui.comboBox_scoreboardField.currentText() == "Match"


def test_output_status(page, make_result, monkeypatch):
    assert page.destinationStatus().state == output_status.OFF
    page.ui.checkBox_enabled.setChecked(True)
    assert page.destinationStatus().state == output_status.WARNING
    http_server.update_http_server(
        [make_result("Time", "10:00"), make_result("Shot Clock", "25")]
    )
    assert page.destinationStatus().state == output_status.SENDING
    http_server._timing_response(True, True)
    assert page.destinationStatus().state == output_status.OK
    page.refresh()
    assert '"minute": 10' in page.ui.label_preview.text()
    monkeypatch.setattr(http_server, "get_http_server_port", lambda: None)
    page.refresh()
    assert page.destinationStatus().state == output_status.ERROR
    assert not page.ui.pushButton_copyScoreboard.isEnabled()
    assert page.ui.lineEdit_scoreboardUrl.text() == ""
