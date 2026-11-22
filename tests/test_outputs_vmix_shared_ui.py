"""Shared vMix page: manual/fetched names, modes, settings and no polling."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QMainWindow

from storage import SETTINGS_FILE, fetch_data, store_data
from ui_mainwindow import Ui_MainWindow
from vmix_ui_handler import VMixUIHanlder
from test_outputs_vmix_discovery import FakeVmix, flush

pytestmark = pytest.mark.qt


@pytest.fixture
def page(qtbot):
    server = FakeVmix()
    for key, value in {
        "vmix_host": "127.0.0.1",
        "vmix_port": server.port,
        "vmix_mapping": {},
        "vmix_send_same": False,
    }.items():
        store_data(SETTINGS_FILE, key, value)
    window = QMainWindow()
    qtbot.addWidget(window)
    ui = Ui_MainWindow()
    ui.setupUi(window)
    handler = VMixUIHanlder(ui)
    handler.vmixUpdater.set_connection(
        "127.0.0.1", server.port, tcp_port=server.tcp_port
    )
    yield handler, server
    handler.close()
    server.close()


def model(handler):
    return handler.ui.tableView_vmixMapping.model()


def test_fetch_filters_choices_for_one_input_and_all_titles(page, make_target):
    handler, server = page
    handler.ui.inputLineEdit_vmix.setText("2")  # halftime has only Home Score
    handler.vmixConnectionChanged()
    handler.updatevMixTable([make_target("Home Score"), make_target("Time")])
    model(handler).item(0, 1).setText("HOMESCORE.Text")
    model(handler).item(1, 1).setText("TIME.Text")
    handler.ui.pushButton_vmixFetch.click()
    flush(handler.vmixUpdater)
    handler.refresh()
    assert handler.delegate.fields == ["HOMESCORE.Text"]
    assert model(handler).item(0, 2).text() == "1"
    assert model(handler).item(1, 2).text() == "0"
    assert not handler.vmixUpdater.running
    count = server.discovery_requests
    handler.ui.radioButton_vmixAll.setChecked(True)
    assert not handler.ui.inputLineEdit_vmix.isEnabled()
    assert handler.delegate.fields == ["HOMESCORE.Text", "TIME.Text"]
    assert model(handler).item(0, 2).text() == "3"
    assert model(handler).item(1, 2).text() == "2"
    for _ in range(100):
        handler.refresh()
    assert server.discovery_requests == count
    assert handler.ui.tableView_vmixMapping.verticalHeader().count() == 2


def test_manual_names_work_without_fetch(page, make_target, make_result):
    handler, server = page
    handler.updatevMixTable([make_target("Home Score")])
    model(handler).item(0, 1).setText("HOMESCORE.Text")
    server.override_xml = "<html/>"  # discovery fails, direct HTTP still works
    handler.ui.pushButton_startvmix.setChecked(True)
    handler.vmixUpdater.update_vmix([make_result("Home Score", "5")])
    flush(handler.vmixUpdater)
    assert server.inputs["scoreboard-guid"]["HOMESCORE.Text"] == "5"
    assert server.inputs["halftime-guid"]["HOMESCORE.Text"] == ""
    assert handler.destinationStatus().state == "ok"
    assert server.tcp_connections == 0


def test_editor_accepts_typed_and_selected_names(page, make_target, qtbot):
    handler, _ = page
    handler.updatevMixTable([make_target("Home Score")])
    handler.ui.tab_vmix.show()
    table = handler.ui.tableView_vmixMapping
    table.edit(model(handler).index(0, 1))
    editor = table.findChild(QComboBox)
    assert editor is not None and editor.isEditable()
    editor.setEditText("HOMESCORE.Text")
    qtbot.keyClick(editor.lineEdit(), Qt.Key.Key_Return)
    qtbot.waitUntil(
        lambda: handler.vmixUpdater.field_mapping["Home Score"] == "HOMESCORE.Text"
    )
    assert fetch_data(SETTINGS_FILE, "vmix_mapping") == {"Home Score": "HOMESCORE.Text"}


def test_settings_and_language_refresh_keep_shared_selection(page, make_target):
    handler, _ = page
    handler.updatevMixTable([make_target("Home Score")])
    model(handler).item(0, 1).setText("HOMESCORE.Text")
    handler.ui.radioButton_vmixAll.setChecked(True)
    handler.ui.comboBox_vmixTransport.setCurrentIndex(1)
    handler.ui.checkBox_vmix_send_same.setChecked(True)
    handler.restoreUiState()
    assert fetch_data(SETTINGS_FILE, "vmix_all_titles") is True
    assert fetch_data(SETTINGS_FILE, "vmix_transport") == "tcp"
    assert fetch_data(SETTINGS_FILE, "vmix_send_same") is True
    assert handler.ui.radioButton_vmixAll.isChecked()
    assert handler.ui.comboBox_vmixTransport.currentData() == "tcp"
    assert model(handler).item(0, 1).text() == "HOMESCORE.Text"
    assert handler.ui.lineEdit_vmixPort.minimumWidth() >= 90
    assert handler.ui.lineEdit_vmixTcpPort.isReadOnly()


def test_all_titles_tcp_and_one_shared_switch(page, make_target, make_result):
    handler, server = page
    handler.updatevMixTable([make_target("Home Score")])
    model(handler).item(0, 1).setText("HOMESCORE.Text")
    handler.ui.radioButton_vmixAll.setChecked(True)
    handler.ui.comboBox_vmixTransport.setCurrentIndex(1)
    handler.ui.pushButton_startvmix.setChecked(True)
    handler.vmixUpdater.update_vmix([make_result("Home Score", "5")])
    flush(handler.vmixUpdater)
    assert all(fields["HOMESCORE.Text"] == "5" for fields in server.inputs.values())
    assert handler.destinationStatus().key == "vmix"
    assert handler.destinationStatus().state == "ok"
    handler.ui.pushButton_startvmix.setChecked(False)
    assert not handler.vmixUpdater.running
    assert handler.destinationStatus().state == "off"


def test_development_settings_migrate_once(qtbot):
    store_data(SETTINGS_FILE, "vmix_plus_mapping", {"Time": "CLOCK.Text"})
    store_data(SETTINGS_FILE, "vmix_plus_host", "192.168.1.92")
    store_data(SETTINGS_FILE, "vmix_plus_send_same", True)
    window = QMainWindow()
    qtbot.addWidget(window)
    ui = Ui_MainWindow()
    ui.setupUi(window)
    handler = VMixUIHanlder(ui)
    try:
        assert handler.vmixUpdater.host == "192.168.1.92"
        assert handler.vmixUpdater.field_mapping == {"Time": "CLOCK.Text"}
        assert handler.vmixUpdater.all_titles
        assert handler.vmixUpdater.transport == "tcp"
        assert handler.vmixUpdater.update_same is True
        assert not handler.vmixUpdater.running
        handler.ui.radioButton_vmixInput.setChecked(True)
        handler.close()
        other = VMixUIHanlder(ui)
        try:
            assert (
                not other.vmixUpdater.all_titles
            )  # old settings don't overwrite edits
        finally:
            other.close()
    finally:
        handler.close()
