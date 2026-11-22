"""The independent vMix API+ output page, with editable discovered-field choices."""

from PySide6.QtCore import QObject
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QComboBox, QHeaderView, QStyledItemDelegate, QWidget

import output_status
from storage import SETTINGS_FILE, fetch_data, store_data
from theme import button_text_color, media_icon
from ui_vmix_plus import Ui_VMixPlusPage
from vmix_output import DEFAULT_VMIX_PORT
from vmix_plus_output import VMixFunctionError, VMixPlusAPI


class FieldDelegate(QStyledItemDelegate):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.fields = []

    def createEditor(self, parent, option, index):
        combo = QComboBox(parent)
        combo.setEditable(True)
        combo.addItems(["", *self.fields])
        return combo

    def setEditorData(self, editor, index):
        editor.setEditText(index.data() or "")

    def setModelData(self, editor, model, index):
        model.setData(index, editor.currentText().strip())


class VMixPlusUIHandler(QObject):
    def __init__(self, stacked_widget, parent=None):
        super().__init__(parent)
        self.page = QWidget()
        self.ui = Ui_VMixPlusPage()
        self.ui.setupUi(self.page)
        self.page.setObjectName("tab_vmix_plus")
        stacked_widget.insertWidget(4, self.page)
        self.ui.lineEdit_host.setText(
            str(fetch_data(SETTINGS_FILE, "vmix_plus_host", "localhost"))
        )
        self.ui.lineEdit_port.setText(
            str(fetch_data(SETTINGS_FILE, "vmix_plus_port", DEFAULT_VMIX_PORT))
        )
        mapping = fetch_data(SETTINGS_FILE, "vmix_plus_mapping", {})
        self.output = VMixPlusAPI(
            self.ui.lineEdit_host.text(),
            self.ui.lineEdit_port.text(),
            mapping if isinstance(mapping, dict) else {},
        )
        self.ui.checkBox_sendSame.setChecked(bool(self.output.update_same))
        self.model = QStandardItemModel(self)
        self.model.setColumnCount(3)
        self.ui.tableView_mapping.setModel(self.model)
        self.delegate = FieldDelegate(self.ui.tableView_mapping)
        self.ui.tableView_mapping.setItemDelegateForColumn(1, self.delegate)
        self.ui.tableView_mapping.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self.ui.tableView_mapping.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self._updating = False
        self.ui.lineEdit_host.editingFinished.connect(self.connectionChanged)
        self.ui.lineEdit_port.editingFinished.connect(self.connectionChanged)
        self.ui.pushButton_start.toggled.connect(self.setRunning)
        self.ui.pushButton_fetch.clicked.connect(self.output.refresh_fields)
        self.ui.checkBox_sendSame.toggled.connect(
            lambda value: store_data(SETTINGS_FILE, "vmix_plus_send_same", value)
        )
        self.model.itemChanged.connect(self.mappingChanged)
        self.retranslate()

    def connectionChanged(self):
        host = self.ui.lineEdit_host.text().strip()
        port = self.ui.lineEdit_port.text().strip()
        self.output.set_connection(host, port)
        store_data(SETTINGS_FILE, "vmix_plus_host", host)
        store_data(SETTINGS_FILE, "vmix_plus_port", port)
        self.refresh()

    def setRunning(self, running):
        self.ui.pushButton_start.setChecked(running)
        if running:
            self.output.start()
        else:
            self.output.stop()
        self.refreshToggleButton()

    def refreshToggleButton(self):
        button = self.ui.pushButton_start
        button.setText(
            self.tr("Stop vMix API+")
            if self.output.running
            else self.tr("Start vMix API+")
        )
        button.setIcon(
            media_icon(
                "stop" if self.output.running else "play",
                button_text_color(button.palette()),
            )
        )

    def updateTable(self, boxes):
        names = [box.name for box in boxes]
        stored = fetch_data(SETTINGS_FILE, "vmix_plus_mapping", {})
        stored = stored if isinstance(stored, dict) else {}
        self._updating = True
        self.model.setRowCount(0)
        mapping = {}
        for name in names:
            field = str(stored.get(name, name + ".Text"))
            source = QStandardItem(name)
            source.setEditable(False)
            count = QStandardItem()
            count.setEditable(False)
            self.model.appendRow([source, QStandardItem(field), count])
            mapping[name] = field
        self._updating = False
        self.output.set_field_mapping(mapping)
        self.refresh()

    def mappingChanged(self, item):
        if self._updating or item.column() != 1:
            return
        mapping = {
            self.model.item(row, 0).text(): self.model.item(row, 1).text().strip()
            for row in range(self.model.rowCount())
        }
        store_data(SETTINGS_FILE, "vmix_plus_mapping", mapping)
        self.output.set_field_mapping(mapping)
        self.refresh()

    def refresh(self):
        self.output.refresh()
        fields = self.output.fields()
        self.delegate.fields = sorted(fields)
        status = self.output.discovery_status()
        if status.retrying or status.failing_keys:
            problem = output_status.worker_problem(
                output_status.VMIX, status, f"{self.output.host}:{self.output.port}"
            )
            text = problem.detail if problem else self.tr("Could not fetch fields")
        elif status.busy or status.pending:
            text = self.tr("Fetching fields…")
        elif status.last_success_at is not None:
            titles = len({ref for refs in fields.values() for ref in refs})
            text = self.tr("{fields} fields in {titles} titles").format(
                fields=len(fields), titles=titles
            )
        else:
            text = self.tr("Fetch fields to find vMix titles")
        self.ui.label_fields.setText(text)
        for row in range(self.model.rowCount()):
            name = self.model.item(row, 1).text().strip()
            count = str(len(fields.get(name, ()))) if name else ""
            if self.model.item(row, 2).text() != count:
                self.model.item(row, 2).setText(count)

    def destinationStatus(self):
        key = output_status.VMIX_PLUS
        output = self.output
        if not output.running:
            return output_status.DestinationStatus(
                key, output_status.OFF, self.tr("Off")
            )
        target = f"{output.host}:{output.tcp_port}"
        worker = output.status()
        hint = self.tr(
            "Each mapped field updates every matching title, including titles off air."
        )
        for status, discovery in ((output.discovery_status(), True), (worker, False)):
            endpoint = f"{output.host}:{output.port}" if discovery else target
            problem = output_status.worker_problem(output_status.VMIX, status, endpoint)
            if problem:
                rejected = status.last_error and issubclass(
                    status.last_error.type, VMixFunctionError
                )
                if rejected or (
                    status.last_error
                    and status.last_error.code
                    and status.last_error.code >= 500
                ):
                    hint = self.tr(
                        "Fetch fields again and check the exact vMix field names in the mapping table."
                    )
                elif not discovery:
                    hint = self.tr(
                        "Check that vMix's TCP API is reachable on port 8099."
                    )
                else:
                    hint = problem.hint
                return output_status.DestinationStatus(
                    key,
                    problem.state,
                    self.tr("vMix rejected a title field")
                    if rejected
                    else problem.detail,
                    enabled=True,
                    hint=hint,
                    last_activity_at=worker.last_success_at,
                    technical=str(status.last_error or ""),
                )
        mapping = {name: field for name, field in output.field_mapping.items() if field}
        fields = output.fields()
        if not mapping:
            state, detail = output_status.WARNING, self.tr("No fields to send")
        elif output.discovery_status().last_success_at is None:
            state, detail = (
                output_status.SENDING,
                self.tr("Discovering vMix title fields…"),
            )
        elif missing := set(mapping.values()) - set(fields):
            state, detail = (
                output_status.WARNING,
                self.tr("{count} mapped fields not found in vMix").format(
                    count=len(missing)
                ),
            )
            hint = ", ".join(sorted(missing))
        else:
            count = len(
                {ref for field in mapping.values() for ref in fields.get(field, ())}
            )
            state = (
                output_status.OK
                if worker.last_success_at is not None
                else output_status.SENDING
            )
            detail = (
                self.tr("Updating {count} titles at {target}").format(
                    count=count, target=target
                )
                if state == output_status.OK
                else self.tr("Ready for {count} titles; waiting for values").format(
                    count=count
                )
            )
        return output_status.DestinationStatus(
            key,
            state,
            detail,
            enabled=True,
            hint=hint,
            last_activity_at=worker.last_success_at,
        )

    def retranslate(self):
        self.ui.retranslateUi(self.page)
        self.ui.lineEdit_host.setText(self.output.host)
        self.ui.lineEdit_port.setText(self.output.port)
        self.model.setHorizontalHeaderLabels(
            [self.tr("Field"), self.tr("vMix field"), self.tr("Titles")]
        )
        self.refreshToggleButton()
        self.refresh()

    def close(self):
        self.output.close()
