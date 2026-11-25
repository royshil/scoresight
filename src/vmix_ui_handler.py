"""One vMix page: shared connection/mappings, one input or every matching title."""

from PySide6.QtCore import QObject, QCoreApplication, Qt
from PySide6.QtGui import QFontMetrics, QStandardItemModel, QStandardItem
from PySide6.QtWidgets import QComboBox, QHeaderView, QStyledItemDelegate

import output_status
from theme import button_text_color, media_icon
from storage import fetch_data, store_data
from sc_logging import logger
from vmix_output import DEFAULT_VMIX_PORT, VMIX_TCP_API_PORT
from vmix_discovery import VMixOutput

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


class VMixUIHanlder(QObject):
    def __init__(self, ui):
        super().__init__(ui.tab_vmix)
        self.ui = ui
        self._filling = True
        migrate_vmix_port()
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
        edit = self.ui.lineEdit_vmixPort
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
        output = self.vmixUpdater
        return output_status.vmix_status(
            output.running,
            output.host,
            output.port,
            output.input_number,
            output.field_mapping,
            output.status(),
            all_titles=output.all_titles,
            transport=output.transport,
            tcp_port=output.tcp_port,
            discovery=output.discovery_status(),
            fields=output.fields(),
        )

    def close(self):
        self.vmixUpdater.close()
