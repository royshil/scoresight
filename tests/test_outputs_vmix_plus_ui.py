"""The vMix API+ page, saved mappings, discovery choices and output status."""

import pytest
from PySide6.QtWidgets import QStackedWidget, QStyleOptionViewItem

from storage import SETTINGS_FILE, fetch_data, store_data
from vmix_plus_ui_handler import VMixPlusUIHandler
from test_outputs_vmix_plus import FakeVmix, flush

pytestmark = pytest.mark.qt


@pytest.fixture
def page(qtbot):
    server = FakeVmix()
    for key, value in {
        "vmix_plus_host": "127.0.0.1",
        "vmix_plus_port": server.port,
        "vmix_plus_mapping": {},
        "vmix_plus_send_same": False,
    }.items():
        store_data(SETTINGS_FILE, key, value)
    stack = QStackedWidget()
    qtbot.addWidget(stack)
    handler = VMixPlusUIHandler(stack)
    yield handler, server
    handler.close()
    server.close()
    for key, value in {
        "vmix_plus_host": "localhost",
        "vmix_plus_port": "8088",
        "vmix_plus_mapping": {},
        "vmix_plus_send_same": False,
    }.items():
        store_data(SETTINGS_FILE, key, value)


def test_fetch_fields_choices_and_title_counts(page, make_target, qtbot):
    handler, _ = page
    handler.updateTable([make_target("Home Score"), make_target("Time")])
    assert handler.ui.tableView_mapping.verticalHeader().count() == 2
    handler.model.item(0, 1).setText("HOMESCORE.Text")
    handler.model.item(1, 1).setText("TIME.Text")
    handler.ui.pushButton_fetch.click()
    flush(handler.output)
    handler.refresh()
    assert handler.delegate.fields == ["HOMESCORE.Text", "TIME.Text"]
    assert handler.model.item(0, 2).text() == "3"
    assert handler.model.item(1, 2).text() == "2"
    assert handler.ui.label_fields.text() == "2 fields in 3 titles"
    assert not handler.output.running  # discovery alone doesn't turn on sending
    index = handler.model.index(0, 1)
    editor = handler.delegate.createEditor(handler.page, QStyleOptionViewItem(), index)
    qtbot.addWidget(editor)
    handler.delegate.setEditorData(editor, index)
    assert editor.currentText() == "HOMESCORE.Text"
    assert editor.findText("TIME.Text") >= 0
    editor.setEditText("")
    handler.delegate.setModelData(editor, handler.model, index)
    assert handler.output.field_mapping["Home Score"] == ""


def test_settings_are_saved_and_language_changes_keep_them(page, make_target):
    handler, _ = page
    handler.updateTable([make_target("Home Score")])
    handler.model.item(0, 1).setText("HOMESCORE.Text")
    handler.ui.checkBox_sendSame.setChecked(True)
    assert fetch_data(SETTINGS_FILE, "vmix_plus_mapping") == {
        "Home Score": "HOMESCORE.Text"
    }
    assert handler.output.update_same is True
    handler.retranslate()
    assert handler.model.item(0, 1).text() == "HOMESCORE.Text"
    assert handler.ui.lineEdit_host.text() == "127.0.0.1"
    assert handler.ui.checkBox_sendSame.isChecked()
    handler.updateTable([make_target("Home Score"), make_target("Time")])
    assert handler.model.item(0, 1).text() == "HOMESCORE.Text"
    assert handler.model.item(1, 1).text() == "Time.Text"
    handler.updateTable([])
    assert handler.model.rowCount() == 0
    assert handler.output.field_mapping == {}


def test_status_switch_missing_fields_and_partial_delivery(
    page, make_target, make_result
):
    handler, server = page
    assert handler.destinationStatus().state == "off"
    handler.updateTable([make_target("Home Score")])
    handler.setRunning(True)
    flush(handler.output)
    assert handler.ui.pushButton_start.isChecked()
    assert handler.destinationStatus().state == "warning"
    handler.model.item(0, 1).setText("HOMESCORE.Text")
    assert handler.destinationStatus().state == "sending"
    handler.output.update_vmix([make_result("Home Score", "4")])
    flush(handler.output)
    assert handler.destinationStatus().state == "ok"
    assert "3 titles" in handler.destinationStatus().detail
    server.fail.add(("halftime-guid", "HOMESCORE.Text"))
    handler.output.update_vmix([make_result("Home Score", "5")])
    flush(handler.output)
    assert handler.destinationStatus().state == "warning"
    assert "Fetch fields again" in handler.destinationStatus().hint
    handler.ui.pushButton_start.click()
    assert not handler.output.running
    assert handler.destinationStatus().state == "off"


def test_connection_edits_and_discovery_errors(page, qtbot):
    handler, server = page
    server.override_xml = "<html/>"
    handler.ui.pushButton_fetch.click()
    flush(handler.output)
    handler.refresh()
    assert handler.output.discovery_status().failing_keys
    assert handler.ui.label_fields.text()  # error is visible while output is off
    handler.ui.lineEdit_host.setText(" 127.0.0.1 ")
    handler.ui.lineEdit_port.setText(f" {server.port} ")
    handler.connectionChanged()
    assert fetch_data(SETTINGS_FILE, "vmix_plus_host") == "127.0.0.1"
    assert fetch_data(SETTINGS_FILE, "vmix_plus_port") == server.port


def test_field_editor_commits_a_choice(page, make_target, qtbot):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QComboBox

    handler, _ = page
    handler.updateTable([make_target("Home Score")])
    handler.page.show()
    handler.ui.tableView_mapping.edit(handler.model.index(0, 1))
    editor = handler.ui.tableView_mapping.findChild(QComboBox)
    assert editor is not None
    editor.setEditText("HOMESCORE.Text")
    qtbot.keyClick(editor.lineEdit(), Qt.Key.Key_Return)
    qtbot.waitUntil(
        lambda: handler.output.field_mapping["Home Score"] == "HOMESCORE.Text"
    )
