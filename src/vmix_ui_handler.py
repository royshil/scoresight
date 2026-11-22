"""One vMix page: shared connection/mappings, one input or every matching title."""

from PySide6.QtCore import QObject, QCoreApplication, Qt
from PySide6.QtGui import QFontMetrics, QStandardItemModel, QStandardItem
from PySide6.QtWidgets import QComboBox, QHeaderView, QStyledItemDelegate

import output_status
from theme import button_text_color, media_icon
from storage import fetch_data, store_data
from sc_logging import logger
from vmix_output import DEFAULT_VMIX_PORT, VMIX_TCP_API_PORT
from vmix_discovery import VMixOutput, VMixFunctionError

SETTINGS_FILE = "scoresight.json"


def migrate_vmix_port():
    """One-time migration: older versions defaulted the vMix port to 8099, vMix's
    TCP API, which ScoreSight can't talk to (#55). Change a stored 8099 to the
    Web API port 8088 once; a port the user sets later is left alone."""
    if fetch_data(SETTINGS_FILE, "vmix_port_migrated", False):
        return
    if str(fetch_data(SETTINGS_FILE, "vmix_port", "")).strip() == VMIX_TCP_API_PORT:
        store_data(SETTINGS_FILE, "vmix_port", DEFAULT_VMIX_PORT)
        logger.info(
            "vMix port changed from %s (vMix TCP API) to %s (vMix Web API, used "
            "by ScoreSight)",
            VMIX_TCP_API_PORT,
            DEFAULT_VMIX_PORT,
        )
    store_data(SETTINGS_FILE, "vmix_port_migrated", True)


def mapping_from_model(model: QStandardItemModel) -> dict[str, str]:
    """{box name: vMix field name} from the mapping table's model."""
    mapping = {}
    for i in range(model.rowCount()):
        item = model.item(i, 0)
        value = model.item(i, 1)
        if item and value:
            mapping[item.text()] = value.text()
    return mapping


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


def migrate_vmix_shared_settings():
    """Keep settings from the development-only API+ page, once, if configured."""
    if fetch_data(SETTINGS_FILE, "vmix_shared_migrated", False):
        return
    mapping = fetch_data(SETTINGS_FILE, "vmix_plus_mapping", {})
    if isinstance(mapping, dict) and any(mapping.values()):
        for old, new, default in (
            ("vmix_plus_host", "vmix_host", "localhost"),
            ("vmix_plus_port", "vmix_port", DEFAULT_VMIX_PORT),
            ("vmix_plus_mapping", "vmix_mapping", {}),
            ("vmix_plus_send_same", "vmix_send_same", False),
        ):
            store_data(SETTINGS_FILE, new, fetch_data(SETTINGS_FILE, old, default))
        store_data(SETTINGS_FILE, "vmix_all_titles", True)
        store_data(SETTINGS_FILE, "vmix_transport", "tcp")
    store_data(SETTINGS_FILE, "vmix_shared_migrated", True)


class VMixUIHanlder(QObject):
    def __init__(self, ui):
        super().__init__(ui.tab_vmix)
        self.ui = ui
        self._filling = True
        migrate_vmix_port()
        migrate_vmix_shared_settings()
        self.vmixUpdater = VMixOutput(
            str(fetch_data(SETTINGS_FILE, "vmix_host", "localhost")),
            str(fetch_data(SETTINGS_FILE, "vmix_port", DEFAULT_VMIX_PORT)),
            str(fetch_data(SETTINGS_FILE, "vmix_input", "1")),
            fetch_data(SETTINGS_FILE, "vmix_mapping", {}) or {},
            all_titles=bool(fetch_data(SETTINGS_FILE, "vmix_all_titles", False)),
            transport=fetch_data(SETTINGS_FILE, "vmix_transport", "http"),
        )
        self.ui.comboBox_vmixTransport.setItemData(0, "http")
        self.ui.comboBox_vmixTransport.setItemData(1, "tcp")
        self.delegate = FieldDelegate(self.ui.tableView_vmixMapping)
        self.ui.tableView_vmixMapping.setItemDelegateForColumn(1, self.delegate)
        self.ui.tableView_vmixMapping.horizontalHeader().show()
        self.restoreUiState()
        for widget in (
            ui.lineEdit_vmixHost,
            ui.lineEdit_vmixPort,
            ui.inputLineEdit_vmix,
        ):
            widget.editingFinished.connect(self.vmixConnectionChanged)
        ui.radioButton_vmixInput.toggled.connect(self.targetChanged)
        ui.radioButton_vmixAll.toggled.connect(self.targetChanged)
        ui.comboBox_vmixTransport.currentIndexChanged.connect(self.targetChanged)
        ui.pushButton_startvmix.toggled.connect(self.togglevMix)
        ui.pushButton_vmixFetch.clicked.connect(self.fetchFields)
        ui.checkBox_vmix_send_same.toggled.connect(self.sendSameChanged)
        self._filling = False

    def globalSettingsChanged(self, settingName, value):
        store_data(SETTINGS_FILE, settingName, value)

    def vmixConnectionChanged(self):
        if self._filling:
            return
        host = self.ui.lineEdit_vmixHost.text().strip()
        port = self.ui.lineEdit_vmixPort.text().strip()
        input_number = self.ui.inputLineEdit_vmix.text().strip()
        self.vmixUpdater.set_connection(host, port, input_number)
        for name, value in (
            ("vmix_host", host),
            ("vmix_port", port),
            ("vmix_input", input_number),
        ):
            if fetch_data(SETTINGS_FILE, name) != value:
                self.globalSettingsChanged(name, value)
        self.refresh()

    def sendSameChanged(self, value):
        if not self._filling:
            self.globalSettingsChanged("vmix_send_same", value)

    def targetChanged(self, *_):
        if self._filling:
            return
        self.vmixUpdater.set_mode(
            self.ui.radioButton_vmixAll.isChecked(),
            self.ui.comboBox_vmixTransport.currentData(),
        )
        self.globalSettingsChanged("vmix_all_titles", self.vmixUpdater.all_titles)
        self.globalSettingsChanged("vmix_transport", self.vmixUpdater.transport)
        self.updateModeControls()
        self.refresh()

    def updateModeControls(self):
        self.ui.inputLineEdit_vmix.setEnabled(not self.vmixUpdater.all_titles)
        self.ui.lineEdit_vmixTcpPort.setText(self.vmixUpdater.tcp_port)
        self.ui.lineEdit_vmixTcpPort.setEnabled(self.vmixUpdater.transport == "tcp")

    def fetchFields(self):
        self.vmixConnectionChanged()
        self.vmixUpdater.refresh_fields()
        self.refresh()

    def vmixMappingChanged(self, top_left=None, bottom_right=None, *_):
        if self._filling or (top_left is not None and top_left.column() > 1):
            return
        model = self.ui.tableView_vmixMapping.model()
        mapping = mapping_from_model(model)
        self.globalSettingsChanged("vmix_mapping", mapping)
        self.vmixUpdater.set_field_mapping(mapping)
        self.refresh()

    def restoreUiState(self):
        filling, self._filling = self._filling, True
        output = self.vmixUpdater
        self.ui.lineEdit_vmixHost.setText(output.host)
        self.ui.lineEdit_vmixPort.setText(output.port)
        self.ui.inputLineEdit_vmix.setText(output.input_number)
        self.ui.radioButton_vmixAll.setChecked(output.all_titles)
        self.ui.radioButton_vmixInput.setChecked(not output.all_titles)
        self.ui.comboBox_vmixTransport.setCurrentIndex(
            1 if output.transport == "tcp" else 0
        )
        self.ui.pushButton_startvmix.setChecked(output.running)
        self.ui.checkBox_vmix_send_same.setChecked(bool(output.update_same))
        model = self.ui.tableView_vmixMapping.model()
        if model is not None:
            model.setHorizontalHeaderLabels(
                [self.tr("Field"), self.tr("vMix field"), self.tr("Titles")]
            )
        self.updateModeControls()
        self.refreshToggleButton()
        # Fit five digits with the actual UI font and style, including padding.
        for edit in (self.ui.lineEdit_vmixPort, self.ui.lineEdit_vmixTcpPort):
            width = max(90, QFontMetrics(edit.font()).horizontalAdvance("65535") + 32)
            edit.setMinimumWidth(width)
            edit.setMaximumWidth(width + 20)
        self._filling = filling
        self.refresh()

    def _updateToggleText(self, running):
        button = self.ui.pushButton_startvmix
        button.setText(
            QCoreApplication.translate("MainWindow", "Stop vMix")
            if running
            else QCoreApplication.translate("MainWindow", "Start vMix")
        )
        button.setIcon(
            media_icon(
                "stop" if running else "play", button_text_color(button.palette())
            )
        )

    def refreshToggleButton(self):
        self._updateToggleText(self.vmixUpdater.running)

    def togglevMix(self, value):
        self._updateToggleText(value)
        if value:
            self.vmixUpdater.start()
        else:
            self.vmixUpdater.stop()
        self.refresh()

    def updatevMixTable(self, detectionTargets):
        stored = fetch_data(SETTINGS_FILE, "vmix_mapping", {}) or {}
        model = QStandardItemModel()
        model.setHorizontalHeaderLabels(
            [self.tr("Field"), self.tr("vMix field"), self.tr("Titles")]
        )
        for box in detectionTargets:
            name = QStandardItem(box.name)
            name.setFlags(Qt.ItemFlag.NoItemFlags)
            count = QStandardItem()
            count.setEditable(False)
            model.appendRow(
                [name, QStandardItem(stored.get(box.name, box.name)), count]
            )
        self.ui.tableView_vmixMapping.setModel(model)
        header = self.ui.tableView_vmixMapping.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        model.dataChanged.connect(self.vmixMappingChanged)
        self.vmixUpdater.set_field_mapping(mapping_from_model(model))
        self.refresh()

    def refresh(self):
        # Read cached state only. This UI timer never polls vMix.
        fields = self.vmixUpdater.fields()
        self.delegate.fields = sorted(fields)
        status = self.vmixUpdater.discovery_status()
        if status.retrying or status.failing_keys:
            problem = output_status.worker_problem(
                output_status.VMIX,
                status,
                f"{self.vmixUpdater.host}:{self.vmixUpdater.port}",
            )
            text = problem.detail if problem else self.tr("Could not fetch fields")
        elif status.busy or status.pending:
            text = self.tr("Fetching fields…")
        elif fields or status.last_success_at is not None:
            titles = len({ref for refs in fields.values() for ref in refs})
            text = self.tr("{fields} fields in {titles} titles").format(
                fields=len(fields), titles=titles
            )
        else:
            text = self.tr("Fetch fields to find vMix titles")
        self.ui.label_vmixFields.setText(text)
        model = self.ui.tableView_vmixMapping.model()
        if model is not None:
            for row in range(model.rowCount()):
                item = model.item(row, 1)
                if item is not None:
                    count = str(len(fields.get(item.text(), ()))) if item.text() else ""
                    if model.item(row, 2).text() != count:
                        model.item(row, 2).setText(count)

    def destinationStatus(self):
        key = output_status.VMIX
        output = self.vmixUpdater
        if not output.all_titles and output.transport == "http":
            return output_status.vmix_status(
                output.running,
                output.host,
                output.port,
                output.input_number,
                output.field_mapping,
                output.status(),
            )
        if not output.running:
            return output_status.DestinationStatus(
                key, output_status.OFF, self.tr("Off")
            )
        port = output.tcp_port if output.transport == "tcp" else output.port
        target = f"{output.host}:{port}"
        worker = output.status()
        hint = self.tr(
            "Each mapped field updates every matching title, including titles off air."
        )
        snapshots = [(worker, False)]
        if output.all_titles:
            snapshots.insert(0, (output.discovery_status(), True))
        for status, discovery in snapshots:
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
                elif not discovery and output.transport == "tcp":
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
        elif not output.all_titles:
            state = (
                output_status.OK
                if worker.last_success_at is not None
                else output_status.SENDING
            )
            detail = self.tr("Sending to {target}, input {input}").format(
                target=target, input=output.input_number
            )
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

    def close(self):
        self.vmixUpdater.close()
