"""The Team Performance output page; timing is served by the existing HTTP server."""

import json

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication, QWidget

import http_server
import output_status
from storage import SETTINGS_FILE, fetch_data, store_data
from team_performance import TimingConfig
from ui_team_performance import Ui_TeamPerformancePage

SETTINGS_KEY = "team_performance"


class TeamPerformanceUIHandler(QObject):
    def __init__(self, stacked_widget, parent=None):
        super().__init__(parent)
        self.page = QWidget()
        self.page.setObjectName("tab_team_performance")
        self.ui = Ui_TeamPerformancePage()
        self.ui.setupUi(self.page)
        stacked_widget.addWidget(self.page)
        stored = fetch_data(SETTINGS_FILE, SETTINGS_KEY, {})
        stored = stored if isinstance(stored, dict) else {}
        self.config = TimingConfig(
            enabled=stored.get("enabled") is True,
            scoreboard_field=str(stored.get("scoreboard_field") or "Time"),
            shot_clock_field=str(stored.get("shot_clock_field") or "Shot Clock"),
        )
        self.ui.checkBox_enabled.setChecked(self.config.enabled)
        self.setBoxNames(["Time", "Shot Clock"])
        http_server.configure_team_performance(self.config)
        self.ui.checkBox_enabled.toggled.connect(self.save)
        self.ui.comboBox_scoreboardField.currentTextChanged.connect(self.save)
        self.ui.comboBox_shotClockField.currentTextChanged.connect(self.save)
        self.ui.pushButton_copyScoreboard.clicked.connect(
            lambda: QApplication.clipboard().setText(
                self.ui.lineEdit_scoreboardUrl.text()
            )
        )
        self.ui.pushButton_copyShotClock.clicked.connect(
            lambda: QApplication.clipboard().setText(
                self.ui.lineEdit_shotClockUrl.text()
            )
        )

    def setBoxNames(self, names):
        names = list(names)
        for combo, selected in (
            (self.ui.comboBox_scoreboardField, self.config.scoreboard_field),
            (self.ui.comboBox_shotClockField, self.config.shot_clock_field),
        ):
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(list(dict.fromkeys([selected, *names])))
            combo.setCurrentText(selected)
            combo.blockSignals(False)

    def save(self, *_):
        self.config = TimingConfig(
            self.ui.checkBox_enabled.isChecked(),
            self.ui.comboBox_scoreboardField.currentText(),
            self.ui.comboBox_shotClockField.currentText(),
        )
        store_data(SETTINGS_FILE, SETTINGS_KEY, vars(self.config))
        http_server.configure_team_performance(self.config)
        self.refresh()

    def refresh(self):
        port = http_server.get_http_server_port()
        host = getattr(self.parent(), "lanAddress", None) or "127.0.0.1"
        base = f"http://{host}:{port}" if port is not None else ""
        for edit, button, path in (
            (
                self.ui.lineEdit_scoreboardUrl,
                self.ui.pushButton_copyScoreboard,
                "/timeclock/time-as-array",
            ),
            (self.ui.lineEdit_shotClockUrl, self.ui.pushButton_copyShotClock, "/time"),
        ):
            url = base + path if base else ""
            if edit.text() != url:
                edit.setText(url)
                edit.setCursorPosition(0)
                edit.setToolTip(url)
            button.setEnabled(bool(url))
        previews = []
        for scoreboard, field in (
            (True, self.config.scoreboard_field),
            (False, self.config.shot_clock_field),
        ):
            try:
                value = json.dumps(http_server.team_performance_payload(scoreboard))
            except ValueError:
                value = self.tr("No valid clock available")
            previews.append(f"{field}: {value}")
        self.ui.label_preview.setText("\n".join(previews))

    def destinationStatus(self):
        key = output_status.TEAM_PERFORMANCE
        if not self.config.enabled:
            return output_status.DestinationStatus(
                key, output_status.OFF, self.tr("Off")
            )
        last = http_server.team_performance_last_request()
        if http_server.get_http_server_port() is None:
            return output_status.DestinationStatus(
                key,
                output_status.ERROR,
                self.tr("HTTP server is not running"),
                enabled=True,
                hint=self.tr("Check the HTTP server output and its port."),
            )
        try:
            http_server.team_performance_payload(True)
            http_server.team_performance_payload(False)
        except ValueError:
            state, detail = (
                output_status.WARNING,
                self.tr("Waiting for valid clock readings"),
            )
        else:
            state = output_status.OK if last is not None else output_status.SENDING
            detail = (
                self.tr("Timing requested")
                if last is not None
                else self.tr("Ready; waiting for Team Performance")
            )
        return output_status.DestinationStatus(
            key,
            state,
            detail,
            enabled=True,
            last_activity_at=last,
            activity=output_status.ACTIVITY_REQUEST,
            hint=self.tr(
                "Copy the two URLs into Config. timing devices in Team Performance."
            ),
        )

    def retranslate(self):
        self.ui.retranslateUi(self.page)
        self.refresh()
