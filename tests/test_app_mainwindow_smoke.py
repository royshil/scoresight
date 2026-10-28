"""Construct the real MainWindow headless (QT_QPA_PLATFORM=offscreen).

The HTTP server, camera enumeration (DirectShow/AVFoundation/V4L + NDI
discovery) and the update check are patched out so the tests need no network,
devices or ports. Sources are opened with a fake viewer (no capture thread).
"""

import csv
from pathlib import Path
import threading

import pytest

pytestmark = pytest.mark.qt
pytest.importorskip("tesserocr")  # MainWindow imports the OCR pipeline

from PySide6 import QtCore  # noqa: E402
from PySide6.QtCore import (  # noqa: E402
    QCoreApplication,
    QEvent,
    QObject,
    QTranslator,
    Signal,
)
from PySide6.QtGui import QKeySequence  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget  # noqa: E402

from camera_info import CameraInfo  # noqa: E402
from storage import fetch_data, store_data  # noqa: E402
from update_check import UpdateCheckResult  # noqa: E402
from version import __version__  # noqa: E402


class FakeViewer(QWidget):
    """Stands in for source_view.ImageViewer (which starts a capture thread)."""

    first_frame_received_signal = Signal()
    error_signal = Signal(str)
    four_corner_changed = Signal()
    zoom_changed = Signal(float)
    box_drawn = Signal(str, QtCore.QRectF)
    place_requested = Signal(str, QtCore.QPointF)
    box_menu_requested = Signal(str, QtCore.QPoint)
    crop_drawn = Signal(QtCore.QRectF, QtCore.QSizeF)
    crop_selection_changed = Signal()

    def __init__(
        self, camera_info, fourCornersApplied, storage, itemSelected, start=True
    ):
        super().__init__()
        self.camera_info = camera_info
        self.timerThread = None
        self.four_corner_calls = []
        self.fourCornerSelectionMode = False
        self.cropSelectionMode = False
        self.placementField = None
        self.homography_corners = None
        self.corrected = False
        self.picked = 0
        self.zoom = 1.0
        self.heldValues = {}

    def startCapture(self):
        pass

    def hasPicture(self):
        return False

    def uncroppedFrameSize(self):
        return None

    def setPlacementField(self, name):
        self.placementField = name

    def updatePlacementHint(self):
        pass

    def isDrawing(self):
        return False

    def cancelDrawing(self):
        return False

    def startCropSelection(self):
        self.fourCornerSelectionMode = False
        self.cropSelectionMode = True
        self.crop_selection_changed.emit()

    def cancelCropSelection(self):
        self.cropSelectionMode = False
        self.crop_selection_changed.emit()

    def setFourCornersForHomography(self, corners):
        self.homography_corners = corners
        return True

    def setHeldValues(self, values):
        self.heldValues = dict(values)

    def hasFourCornerCorrection(self):
        return self.corrected

    def fourCornersPicked(self):
        return self.picked if self.fourCornerSelectionMode else 0

    def startFourCornerSelection(self):
        self.four_corner_calls.append("start")
        self.fourCornerSelectionMode = True
        self.four_corner_changed.emit()

    def cancelFourCornerSelection(self):
        self.four_corner_calls.append("cancel")
        self.fourCornerSelectionMode = False
        self.four_corner_changed.emit()

    def removeFourCornerCorrection(self):
        self.four_corner_calls.append("remove")
        self.corrected = False
        self.four_corner_changed.emit()

    def zoomLevel(self):
        return self.zoom

    def zoomIn(self):
        self.zoom *= 1.25
        self.zoom_changed.emit(self.zoom)

    def zoomOut(self):
        self.zoom /= 1.25
        self.zoom_changed.emit(self.zoom)

    def resetZoom(self):
        self.zoom = 0.5
        self.zoom_changed.emit(self.zoom)

    def toggleBinary(self):
        pass

    def toggleStabilization(self, state):
        pass

    def selectBox(self, name):
        pass

    def getCameraInfo(self):
        return self.camera_info


class FakeTimerThread(QObject):
    ocr_result_signal = Signal(list)
    update_error = Signal(str)


class FakeObsClient:
    def __init__(self):
        self.disconnected = False

    def disconnect(self):
        self.disconnected = True


@pytest.fixture
def patched(monkeypatch):
    """Patch the main window's external dependencies; returns the call logs."""
    import mainwindow

    calls = {"http": [], "camera_threads": [], "obs": [], "http_port_busy": False}
    cameras = []

    def fake_get_camera_info():
        calls["camera_threads"].append(threading.current_thread())
        return list(cameras)

    def fake_get_http_server_port():
        # the port of the last start, or None as if that port had been busy
        if not calls["http"] or calls["http_port_busy"]:
            return None
        return calls["http"][-1]["port"]

    monkeypatch.setattr(
        mainwindow, "start_http_server", lambda **k: calls["http"].append(k)
    )
    monkeypatch.setattr(mainwindow, "get_http_server_port", fake_get_http_server_port)
    monkeypatch.setattr(mainwindow, "get_camera_info", fake_get_camera_info)
    monkeypatch.setattr(mainwindow, "check_for_updates", lambda *a, **k: False)
    monkeypatch.setattr(mainwindow, "ImageViewer", FakeViewer)
    monkeypatch.setattr(
        mainwindow,
        "update_text_source",
        lambda client, source, text: calls["obs"].append((client, source, text)),
    )
    calls["cameras"] = cameras
    return calls


@pytest.fixture
def make_window(qapp, qtbot, patched, memory_storage):
    import mainwindow

    windows = []

    def _make(**kwargs):
        window = mainwindow.MainWindow(QTranslator(), qapp, **kwargs)
        windows.append(window)
        # source discovery runs on a worker thread
        qtbot.waitUntil(lambda: not window.sources_discovery_running)
        return window

    yield _make
    for window in windows:
        window.close()
        qapp.removeTranslator(window.translator)
        window.deleteLater()
    qapp.processEvents()
    # processEvents() outside an event loop doesn't delete them
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.fixture(autouse=True)
def windows_do_not_outlive_their_test(qapp):
    """A closed MainWindow that outlived its test kept its storage connections
    and its box save timer, and wrote its (empty) boxes into a later test's
    settings."""
    yield
    import mainwindow

    alive = [
        widget
        for widget in QApplication.topLevelWidgets()
        if isinstance(widget, mainwindow.MainWindow)
    ]
    assert alive == []


@pytest.fixture
def main_window(make_window):
    return make_window()


def test_main_window_constructs_shows_and_closes(make_window, patched, qapp):
    from defaults import default_boxes

    threads_before = set(threading.enumerate())
    main_window = make_window()

    assert main_window.windowTitle() == f"ScoreSight - v{__version__}"
    assert main_window.ui.tableWidget_boxes.rowCount() >= len(default_boxes)
    assert main_window.ui.comboBox_camera_source.count() > 0
    assert patched["http"] == [{"port": 18099}]

    main_window.show()
    qapp.processEvents()
    assert main_window.isVisible()

    main_window.close()
    qapp.processEvents()
    assert not main_window.isVisible()
    # closing persists the boxes
    assert isinstance(fetch_data("scoresight.json", "boxes"), list)
    # nothing (e.g. a server or capture thread) was left running
    leftover = [t for t in set(threading.enumerate()) - threads_before if not t.daemon]
    assert leftover == []


def test_closing_the_window_closes_its_parentless_dialogs(make_window, qapp):
    # a visible dialog without a parent keeps Qt's event loop (and the app)
    # running after the main window closed
    window = make_window()
    window.show()
    window.openOBSConnectModal()
    assert window.obs_connect_modal.isVisible()
    window.close()
    qapp.processEvents()
    assert not window.obs_connect_modal.isVisible()


def test_title_shows_the_profile(make_window, monkeypatch):
    monkeypatch.setenv("SCORESIGHT_PROFILE", "court2")
    window = make_window()
    assert window.windowTitle() == f"ScoreSight - v{__version__} [court2]"


# --- background work (#33) -----------------------------------------------------------


def test_sources_are_discovered_off_the_gui_thread(make_window, patched):
    patched["cameras"].append(
        CameraInfo("USB Camera", "0", 0, CameraInfo.CameraType.OPENCV)
    )
    window = make_window()
    assert patched["camera_threads"]
    assert threading.main_thread() not in patched["camera_threads"]
    combo = window.ui.comboBox_camera_source
    assert combo.itemText(combo.count() - 1) == "USB Camera"
    assert window.ui.pushButton_refresh_sources.isEnabled()


def test_obs_auto_connect_runs_off_the_gui_thread(make_window, monkeypatch, qtbot):
    import mainwindow

    client = FakeObsClient()
    threads = []

    def fake_open(info):
        threads.append(threading.current_thread())
        assert info == {"ip": "localhost", "port": "4455", "password": "x"}
        return client

    monkeypatch.setattr(mainwindow, "open_obs_websocket", fake_open)
    store_data(
        "scoresight.json", "obs", {"ip": "localhost", "port": "4455", "password": "x"}
    )
    window = make_window()
    qtbot.waitUntil(lambda: window.obs_websocket_client is client)
    assert threads and threads[0] is not threading.main_thread()
    assert window.ui.pushButton_createOBSScene.isEnabled()
    window.close()
    # closed with obs_websocket.close_obs_websocket, off the GUI thread
    qtbot.waitUntil(lambda: client.disconnected)


# --- outputs ---------------------------------------------------------------------------


def test_obs_updates_without_an_output_folder(main_window, patched, make_result):
    # obs-updates-gated-by-output-folder: OBS was only updated after the
    # output-folder check and at the file-save rate.
    client = FakeObsClient()
    main_window.obs_websocket_client = client
    assert main_window.out_folder is None

    main_window.ocrResult([make_result("Home Score", "12")])
    main_window.ocrResult([make_result("Home Score", "12", "SameNoChange")])
    main_window.ocrResult([make_result("Home Score", "8B", "FailedFilter")])
    main_window.ocrResult([make_result("Home Score", "13")])
    # a custom box has no OBS source
    main_window.ocrResult([make_result("Custom 1", "99")])
    assert patched["obs"] == [
        (client, "Home score", "12"),
        (client, "Home score", "13"),
    ]


def test_the_sport_choice_follows_the_game(main_window, make_result):
    from storage import fetch_data

    ui = main_window.ui
    assert ui.comboBox_sport.currentData() == "none"
    assert ui.label_gameStatus.isHidden()
    assert not ui.toolButton_newGame.isEnabled()
    ui.comboBox_sport.setCurrentIndex(ui.comboBox_sport.findData("basketball"))
    assert fetch_data("scoresight.json", "sport") == "basketball"
    assert main_window.gameEngine.sport.key == "basketball"
    assert not ui.label_gameStatus.isHidden() and ui.toolButton_newGame.isEnabled()
    for text in ("0", "0", "2", "2"):
        main_window.ocrResult(
            [make_result("Home Score", text), make_result("Away Score", "0")]
        )
    assert [event.text() for event in main_window.gameEngine.events] == [
        "Home +2 (2–0)"
    ]
    main_window.gameUiHandler.refresh()
    assert ui.label_gameStatus.text().startswith("Follows Home Score, Away Score")
    assert "Home +2 (2–0)" in ui.label_gameStatus.toolTip()
    ui.toolButton_newGame.click()
    assert main_window.gameEngine.events == ()


def test_a_change_the_sport_does_not_allow_is_held_back(
    main_window, patched, make_result
):
    client = FakeObsClient()
    main_window.obs_websocket_client = client
    ui = main_window.ui
    ui.comboBox_sport.setCurrentIndex(ui.comboBox_sport.findData("basketball"))
    clock = [1000.0]
    main_window.gameEngine._clock = lambda: clock[0]

    def read(text, state="Success"):
        clock[0] += 0.5
        main_window.ocrResult([make_result("Home Score", text, state)])

    read("21")
    read("21", "SameNoChange")
    read("81")  # a flicker
    assert "Home Score" in main_window.plausibilityHolds
    read("21")
    for _ in range(7):  # a correction, read steadily for 3 s
        read("18")
    texts = [text for _, source, text in patched["obs"] if source == "Home score"]
    assert "81" not in texts and texts[-1] == "18"
    # the game followed the readings themselves
    assert [e.text() for e in main_window.gameEngine.events] == [
        "Home score corrected to 18 (18–?)"
    ]
    # a value held by the operator goes out as it is
    main_window.heldValues.hold("Home Score", "95")
    read("18")
    texts = [text for _, source, text in patched["obs"] if source == "Home score"]
    assert texts[-1] == "95"


def test_the_sport_is_restored(make_window):
    from storage import store_data

    store_data("scoresight.json", "sport", "soccer")
    window = make_window()
    assert window.ui.comboBox_sport.currentData() == "soccer"
    assert window.gameEngine.sport.key == "soccer"


def test_create_obs_scene_sends_every_current_value_again(
    main_window, patched, make_result, monkeypatch
):
    # Creating the scene replaces the text sources with the scene collection's
    # placeholder texts ("24", "18", ...); unchanged values were never sent to
    # them, so OBS showed the placeholders until each box's value changed.
    import mainwindow
    import obs_websocket

    scenes = []

    def create(client, name, recreate=True):
        scenes.append((client, name, recreate))
        return obs_websocket.SCENE_CREATED

    monkeypatch.setattr(mainwindow, "create_obs_scene_from_export", create)
    client = FakeObsClient()
    main_window.obs_websocket_client = client
    main_window.ocrResult([make_result("Home Score", "3")])
    main_window.ui.lineEdit_sceneName.setText("ScoreSight Scene")
    main_window.createOBSScene()
    assert scenes == [(client, "ScoreSight Scene", True)]
    main_window.ocrResult([make_result("Home Score", "3", "SameNoChange")])
    assert patched["obs"] == [
        (client, "Home score", "3"),
        (client, "Home score", "3"),
    ]


@pytest.mark.parametrize(
    ("recreate", "outcome", "said"),
    [
        (True, "recreated", "again"),
        (False, "kept", "kept as it is"),
        (True, "failed", "Couldn't create"),
    ],
)
def test_create_obs_scene_follows_recreate_and_says_what_it_did(
    main_window, monkeypatch, qapp, recreate, outcome, said
):
    # Recreate was never read: an existing scene was always emptied and made
    # again
    import mainwindow

    calls = []

    def create(client, name, recreate=True):
        calls.append(recreate)
        return outcome

    monkeypatch.setattr(mainwindow, "create_obs_scene_from_export", create)
    ui = main_window.ui
    main_window.obs_websocket_client = FakeObsClient()
    main_window.show()
    assert ui.label_obsSceneStatus.isHidden()
    ui.checkBox_recreate.setChecked(recreate)
    ui.lineEdit_sceneName.setText("Court 2")
    main_window.createOBSScene()
    assert calls == [recreate]
    assert not ui.label_obsSceneStatus.isHidden()
    assert said in ui.label_obsSceneStatus.text()
    assert "“Court 2”" in ui.label_obsSceneStatus.text()
    # said again after a language change
    main_window.changeLanguage("de_DE")
    try:
        assert "Court 2" in ui.label_obsSceneStatus.text()
        assert not ui.label_obsSceneStatus.isHidden()
    finally:
        qapp.removeTranslator(main_window.translator)


def test_the_obs_text_sources_are_editable(
    main_window, patched, make_target, make_result
):
    # The OBS text source of a field could only be set by editing an exported
    # configuration file
    from PySide6.QtCore import Qt

    ui = main_window.ui
    storage = main_window.detectionTargetsStorage
    storage.add_item(make_target("Home Score"))
    storage.add_item(make_target("Custom 1"))
    model = ui.tableView_obsSources.model()
    rows = [
        (model.item(row, 0).text(), model.item(row, 1).text())
        for row in range(model.rowCount())
    ]
    assert rows == [("Home Score", "Home score"), ("Custom 1", "")]
    # the names aren't editable, the sources are
    assert not model.item(0, 0).flags() & Qt.ItemFlag.ItemIsEditable
    assert model.item(1, 1).flags() & Qt.ItemFlag.ItemIsEditable

    main_window.obs_websocket_client = client = FakeObsClient()
    model.item(1, 1).setText("  Shot clock ")  # typed in the table
    assert model.item(1, 1).text() == "Shot clock"
    box = storage.find_item_by_name("Custom 1")
    assert box.settings["obs_source_name"] == "Shot clock"
    # saved with the boxes
    main_window.saveBoxes()
    stored = {box["name"]: box for box in fetch_data("scoresight.json", "boxes")}
    assert stored["Custom 1"]["settings"]["obs_source_name"] == "Shot clock"
    # an empty name: not sent to OBS any more
    model.item(0, 1).setText("")
    assert storage.find_item_by_name("Home Score").settings["obs_source_name"] == ""
    # (the readings carry their box's settings)
    main_window.ocrResult(
        [
            make_result("Home Score", "3", obs_source_name=""),
            make_result("Custom 1", "24", obs_source_name="Shot clock"),
        ]
    )
    assert patched["obs"] == [(client, "Shot clock", "24")]


def test_template_fields_report_changes_only(main_window, make_result):
    # template-uses-failed-results: every template was reported as a new
    # Success on every cycle (defeating "update on change"), and filled with
    # rejected readings.
    def cycle(home, away):
        template = make_result(
            "Score",
            "",
            "Empty",
            templatefield=True,
            templatefield_text="{{Home Score}} - {{Away Score}}",
        )
        results = [make_result("Home Score", *home), make_result("Away Score", *away)]
        main_window.ocrResult([*results, template])
        return template.result, template.result_state.name

    assert cycle(("12", "Success"), ("7", "Success")) == ("12 - 7", "Success")
    assert cycle(("12", "SameNoChange"), ("7", "SameNoChange")) == (
        "12 - 7",
        "SameNoChange",
    )
    assert cycle(("8B", "FailedFilter"), ("7", "SameNoChange")) == (
        "12 - 7",
        "SameNoChange",
    )
    assert cycle(("13", "Success"), ("7", "SameNoChange")) == ("13 - 7", "Success")


def test_stop_updates_pauses_outputs(main_window, patched, make_result):
    main_window.obs_websocket_client = FakeObsClient()
    main_window.ui.pushButton_stopUpdates.setChecked(True)
    main_window.ocrResult([make_result("Home Score", "12")])
    assert patched["obs"] == []


def test_file_outputs_flush_the_last_change_when_the_throttle_opens(
    main_window, make_result, tmp_path, qtbot
):
    # #6: a change that arrives inside the "Save / s" window is written as
    # soon as the window opens, even if no other result arrives.
    main_window.ui.horizontalSlider_aggsPerSecond.setValue(2)
    main_window.setOutputFolder(str(tmp_path))
    home = tmp_path / "Home Score.txt"

    main_window.ocrResult([make_result("Home Score", "1")])
    assert home.read_text(encoding="utf-8") == "1"
    main_window.ocrResult([make_result("Home Score", "2")])
    main_window.ocrResult([make_result("Home Score", "2", "SameNoChange")])
    assert home.read_text(encoding="utf-8") == "1"  # throttled
    qtbot.waitUntil(lambda: home.read_text(encoding="utf-8") == "2", timeout=3000)


def test_box_changes_do_not_truncate_the_csv_log(
    main_window, make_result, make_target, tmp_path
):
    # csv-truncated-on-any-box-change: any data_changed (a click on a box, a
    # settings tweak) emptied results.csv.
    main_window.ui.comboBox_appendMethod.setCurrentIndex(0)  # append to .csv
    main_window.ui.checkBox_saveCsv.setChecked(True)
    main_window.ui.horizontalSlider_aggsPerSecond.setValue(10)
    main_window.setOutputFolder(str(tmp_path))
    storage = main_window.detectionTargetsStorage
    storage.add_item(make_target("Home Score"))

    main_window.ocrResult([make_result("Home Score", "1")])
    main_window.flushFileOutputs()
    main_window.ocrResult([make_result("Home Score", "2")])
    main_window.flushFileOutputs()

    box = storage.find_item_by_name("Home Score")
    box.settings["smoothing"] = True
    storage.edit_item("Home Score", box)

    with open(tmp_path / "results.csv", encoding="utf-8", newline="") as f:
        rows = list(csv.reader(f))
    assert rows[0] == ["Timestamp", "Home Score"]
    assert [row[1] for row in rows[1:]] == ["1", "2"]


def test_api_output_encoding_defaults_to_json_full(main_window):
    # api-encoding-blank-on-fresh-install: the default "JSON" matched no item,
    # so "" was stored and POST/PUT output never sent anything.
    assert main_window.ui.comboBox_api_encode.currentIndex() == 0
    assert fetch_data("scoresight.json", "out_api_encoding") == "JSON (Full)"
    assert fetch_data("scoresight.json", "out_api_method") == "POST"


@pytest.mark.parametrize(
    ("stored", "index", "expected"),
    [("", 0, "JSON (Full)"), ("XML", 2, "XML"), ("JSON (Simple key-value)", 1, None)],
)
def test_api_output_encoding_is_restored_or_repaired(
    make_window, stored, index, expected
):
    store_data("scoresight.json", "out_api_encoding", stored)
    window = make_window()
    assert window.ui.comboBox_api_encode.currentIndex() == index
    assert fetch_data("scoresight.json", "out_api_encoding") == (expected or stored)
    window.ui.comboBox_api_encode.setCurrentIndex(3)
    assert fetch_data("scoresight.json", "out_api_encoding") == "CSV"


def test_language_change_keeps_settings_and_texts(main_window, qapp, caplog):
    main_window.ui.comboBox_api_encode.setCurrentIndex(2)
    main_window.ui.lineEdit_vmixPort.setText("8123")
    main_window.ui.lineEdit_vmixPort.editingFinished.emit()
    main_window.reset_playing_source()  # e.g. the sources were reloaded
    main_window.changeLanguage("de_DE")
    try:
        # retranslateUi stopped half-way at a label deleted by a source change
        assert "Error retranslating UI" not in caplog.text
        assert main_window.ui.label_12.isVisibleTo(main_window)
        assert fetch_data("scoresight.json", "language") == "de_DE"
        # retranslateUi used to store the translated item text / reset fields
        assert fetch_data("scoresight.json", "out_api_encoding") == "XML"
        assert main_window.ui.lineEdit_vmixPort.text() == "8123"
        assert main_window.windowTitle() == f"ScoreSight - v{__version__}"
    finally:
        qapp.removeTranslator(main_window.translator)


def test_language_change_keeps_the_runtime_texts(
    main_window, qapp, make_result, make_target
):
    # retranslateUi resets every text to the .ui's: the paused banner, the
    # slider readouts, the window title and the inspector's state are set again
    ui = main_window.ui
    main_window.show()
    storage = main_window.detectionTargetsStorage
    storage.add_item(make_target("Home Score", dilate=2, format_regex="^(1?\\d$"))
    main_window.itemSelected("Home Score")
    ui.horizontalSlider_conf_thresh.setValue(45)
    ui.toolButton_imageCleanup.setChecked(True)
    ui.tabWidget_inspector.setCurrentWidget(ui.widget_outputs)
    main_window.ocrResult([make_result("Home Score", "21")])
    ui.pushButton_stopUpdates.setChecked(True)
    main_window.changeLanguage("de_DE")
    try:
        assert ui.pushButton_stopUpdates.isChecked()
        # (texts in the language loaded, whether they're translated or not)
        tr = QCoreApplication.translate
        assert ui.pushButton_stopUpdates.text() == tr("MainWindow", "Resume outputs")
        assert ui.frame_pausedBanner.isVisibleTo(main_window)
        assert ui.label_pausedBanner.text() != ""
        assert main_window.windowTitle().startswith("⏸ ")
        assert ui.label_confThreshValue.text() == tr("BoxSettings", "{value} %").format(
            value=45
        )
        assert ui.label_detectionCadenceValue.text() == tr(
            "MainWindow", "{value} /s"
        ).format(value=5)
        shortcut = QKeySequence("Ctrl+Shift+P").toString(
            QKeySequence.SequenceFormat.NativeText
        )
        assert f"({shortcut})" in ui.pushButton_stopUpdates.toolTip()
        assert box_value(main_window, "Home Score") == "21"
        assert main_window.statusBarWidgets.label_http.text() != ""
        checked = [
            a.data() for a in main_window.language_actions.actions() if a.isChecked()
        ]
        assert checked == ["de_DE"]
        # the inspector: the tab, the selected field, the open section, the
        # badge and the format's error
        assert ui.tabWidget_inspector.currentWidget() is ui.widget_outputs
        assert ui.tableWidget_boxes.currentItem().text() == "Home Score"
        assert ui.stackedWidget_boxSettings.currentWidget() is ui.page_boxSettings
        assert ui.label_selectedInfo.text() == "Home Score"
        assert ui.toolButton_imageCleanup.isChecked()
        assert ui.frame_imageCleanup.isVisibleTo(ui.tab_box)
        assert ui.label_imageCleanupBadge.text() == QCoreApplication.translate(
            "BoxSettings", "%n changed", None, 1
        )
        assert ui.label_formatStatus.isVisibleTo(ui.tab_box)
        assert ui.label_formatStatus.text() == QCoreApplication.translate(
            "BoxSettings",
            "Not a valid expression, so it is ignored: every reading passes.",
        )
        assert ui.label_templateHint.text() != ""
        assert ui.comboBox_ocrModel.itemText(4) != ""
        assert ui.pushButton_removeBox.isVisibleTo(main_window)
        assert not ui.pushButton_makeBox.isVisibleTo(main_window)
    finally:
        qapp.removeTranslator(main_window.translator)


def test_language_change_keeps_the_output_controls(
    main_window, qapp, monkeypatch, make_target
):
    # retranslateUi reset the vMix/UNO start buttons to their .ui texts
    # ("Start"), the OBS scene name and the playback speed.
    ui = main_window.ui
    main_window.detectionTargetsStorage.add_item(make_target("Home Score"))
    vmix = main_window.vmixUiHandler
    uno = main_window.unoUiHandler
    monkeypatch.setattr(vmix.vmixUpdater, "start", lambda: None, raising=False)
    monkeypatch.setattr(uno.unoUpdater, "start", lambda: None, raising=False)
    vmix_text = main_window.ui.pushButton_startvmix.text()
    uno_text = main_window.ui.toolButton_toggleUno.text()
    main_window.ui.lineEdit_sceneName.setText("Court 2")
    main_window.ui.toolButton_speed.setText("x4")
    # the destinations: OBS selected and connected
    main_window.showDestination("obs")
    main_window.obs_websocket_client = FakeObsClient()
    main_window.obsAddress = "obs-pc:4455"
    main_window.updateObsUi()
    main_window.refreshLiveStatus()
    connect_text = ui.pushButton_connectObs.text()
    assert connect_text == "Change connection..."
    main_window.changeLanguage("de_DE")
    try:
        # (texts in the language loaded, whether they're translated or not)
        tr = QCoreApplication.translate
        assert main_window.ui.pushButton_startvmix.text() == tr("MainWindow", vmix_text)
        assert main_window.ui.toolButton_toggleUno.text() == tr("MainWindow", uno_text)
        assert main_window.ui.lineEdit_sceneName.text() == "Court 2"
        assert main_window.ui.toolButton_speed.text() == "x4"
        # retranslateUi set "Connect OBS" again; the selected destination and
        # its page stay
        assert ui.pushButton_connectObs.text() == tr("MainWindow", connect_text)
        assert ui.pushButton_disconnectObs.isEnabled()
        assert ui.listView_destinations.currentIndex().row() == 2
        assert ui.stackedWidget_outputs.currentWidget() is ui.tab_obs
        model = main_window.destinationsModel
        assert all(model.item(row).text() for row in range(model.rowCount()))
        assert model.status("obs").detail == tr(
            "OutputStatus", "Connected to {target}"
        ).format(target="obs-pc:4455")
        buttons = main_window.statusBarWidgets.output_buttons
        assert all(button.text() for button in buttons.values())
        assert main_window.statusBarWidgets.label_outputs.text().strip()
    finally:
        qapp.removeTranslator(main_window.translator)


def test_pause_outputs_button_text_with_a_translation(main_window, qapp):
    # stop-updates-button-blank-i18n: QTranslator.translate returns "" for a
    # missing translation, which blanked the button in every non-English UI.
    assert main_window.ui.pushButton_stopUpdates.text() == "Pause outputs"
    main_window.changeLanguage("de_DE")
    try:
        button = main_window.ui.pushButton_stopUpdates
        button.setChecked(True)
        paused_text = button.text()
        button.setChecked(False)
        assert paused_text not in ("", button.text())
        assert button.text() != ""
    finally:
        qapp.removeTranslator(main_window.translator)
    main_window.ui.pushButton_stopUpdates.setChecked(True)
    assert main_window.ui.pushButton_stopUpdates.text() == "Resume outputs"


def test_browser_tab_shows_the_http_port(make_window, patched):
    window = make_window(http_port=18100)
    assert patched["http"] == [{"port": 18100}]
    text = window.ui.label_8.text()
    assert "http://localhost:18100/json" in text
    assert "http://localhost:18100/csv" in text
    assert "?pivot" in text
    assert "18099" not in text
    assert "color:#" not in text


def test_browser_tab_says_when_the_http_port_is_busy(make_window, patched):
    patched["http_port_busy"] = True
    window = make_window(http_port=18100)
    text = window.ui.label_8.text()
    assert "not running" in text
    assert "18100" in text
    assert "--port" in text
    assert "http://localhost" not in text


# --- boxes ------------------------------------------------------------------------------


def box_rows(window):
    table = window.ui.tableWidget_boxes
    return [table.item(row, 0).text() for row in range(table.rowCount())]


def box_name_item(window, name):
    """A box's item in the boxes list's Field column."""
    table = window.ui.tableWidget_boxes
    [item] = [
        item
        for item in table.findItems(name, QtCore.Qt.MatchFlag.MatchExactly)
        if item.column() == 0
    ]
    return item


def box_value_item(window, name):
    """A box's item in the boxes list's Value column."""
    return window.ui.tableWidget_boxes.item(box_name_item(window, name).row(), 1)


def box_value(window, name):
    """The text in the boxes list's Value column for a box."""
    return box_value_item(window, name).text()


def select_box_row(window, name):
    item = box_name_item(window, name)
    window.ui.tableWidget_boxes.setCurrentItem(item)
    return item


def test_renaming_a_made_custom_box_keeps_its_row(main_window, monkeypatch):
    import mainwindow

    main_window.addBox()
    [name] = fetch_data("scoresight.json", "custom_boxes_names")
    item = select_box_row(main_window, name)
    main_window.makeBox()
    monkeypatch.setattr(
        mainwindow.QInputDialog,
        "getText",
        lambda *args, **kwargs: ("Shot Clock 2", True),
    )
    main_window.editBoxName(item)
    assert "Shot Clock 2" in box_rows(main_window)
    assert name not in box_rows(main_window)
    [renamed] = main_window.ui.tableWidget_boxes.findItems(
        "Shot Clock 2", QtCore.Qt.MatchFlag.MatchExactly
    )
    assert renamed.data(QtCore.Qt.ItemDataRole.UserRole) == "checked"
    storage = main_window.detectionTargetsStorage
    assert [box.name for box in storage.get_data()] == ["Shot Clock 2"]
    assert fetch_data("scoresight.json", "custom_boxes_names") == ["Shot Clock 2"]


def test_the_remove_button_does_not_delete_a_default_box(main_window):
    select_box_row(main_window, "Home Score")
    main_window.makeBox()
    storage = main_window.detectionTargetsStorage
    home = storage.find_item_by_name("Home Score")
    home.settings["conf_thresh"] = 0.4  # a tuned box
    main_window.removeCustomBox()
    assert storage.find_item_by_name("Home Score") is home
    assert "Home Score" in box_rows(main_window)
    main_window.saveBoxes()
    [stored] = fetch_data("scoresight.json", "boxes")
    assert (stored["name"], stored["settings"]["conf_thresh"]) == ("Home Score", 0.4)

    # a custom box is removed
    main_window.addBox()
    [name] = fetch_data("scoresight.json", "custom_boxes_names")
    select_box_row(main_window, name)
    main_window.makeBox()
    main_window.removeCustomBox()
    assert name not in box_rows(main_window)
    assert storage.find_item_by_name(name) is None
    assert fetch_data("scoresight.json", "custom_boxes_names") == []


def test_box_edits_are_saved_without_a_viewer_click(main_window, make_target, qtbot):
    # box-edits-lost-on-source-switch (part 1): only a click in the viewer or
    # closing the window saved the boxes.
    main_window.detectionTargetsStorage.add_item(make_target("Custom 1", type=2))
    qtbot.waitUntil(
        lambda: fetch_data("scoresight.json", "boxes") is not None, timeout=3000
    )
    [box] = fetch_data("scoresight.json", "boxes")
    assert box["name"] == "Custom 1"
    assert box["settings"]["type"] == 2


def test_new_source_keeps_unsaved_box_edits(make_window, make_target, qtbot):
    # box-edits-lost-on-source-switch (part 2): every new viewer reloaded the
    # boxes from disk, dropping in-memory edits.
    store_data(
        "scoresight.json",
        "boxes",
        [{"name": "Home Score", "rect": {"x": 1, "y": 2, "width": 3, "height": 4}}],
    )
    window = make_window()
    storage = window.detectionTargetsStorage
    box = storage.find_item_by_name("Home Score")
    assert box is not None  # loaded at startup
    box.settings["format_regex"] = "^edited$"
    storage.edit_item("Home Score", box)

    window.image_viewer = FakeViewer(None, None, None, None)
    window.cameraConnectedEnableUI()
    assert storage.find_item_by_name("Home Score").settings["format_regex"] == (
        "^edited$"
    )

    def saved_regex():
        [saved] = fetch_data("scoresight.json", "boxes")
        return saved.get("settings", {}).get("format_regex")

    qtbot.waitUntil(lambda: saved_regex() == "^edited$", timeout=3000)


def test_viewer_is_connected_once(main_window, monkeypatch):
    # The first-frame signal (and so cameraConnectedEnableUI) fires again after
    # e.g. a video settings change; each call used to add another connection,
    # so every OCR result was handled (and sent to every output) again.
    import mainwindow

    http_updates = []
    monkeypatch.setattr(mainwindow, "update_http_server", http_updates.append)
    viewer = FakeViewer(None, None, None, None)
    viewer.timerThread = FakeTimerThread()
    main_window.image_viewer = viewer
    main_window.cameraConnectedEnableUI()
    main_window.cameraConnectedEnableUI()
    main_window.ui.pushButton_fourCorner.click()
    viewer.timerThread.ocr_result_signal.emit([])
    assert viewer.four_corner_calls == ["start"]
    assert http_updates == [[]]

    # a new viewer replaces the old one's connections
    new_viewer = FakeViewer(None, None, None, None)
    main_window.image_viewer = new_viewer
    main_window.cameraConnectedEnableUI()
    main_window.ui.pushButton_fourCorner.click()
    assert viewer.four_corner_calls == ["start"]
    assert new_viewer.four_corner_calls == ["start"]
    # the old viewer's picking no longer shows
    viewer.four_corner_changed.emit()
    main_window.ui.pushButton_fourCorner.click()  # cancels the new one's
    assert not main_window.ui.frame_fourCornerBanner.isVisibleTo(main_window)


def test_readings_from_the_start_of_the_capture_reach_the_window(
    make_window, monkeypatch, make_result
):
    # The window connected to the capture thread only when the first preview
    # frame arrived, so the readings made before it were lost. For a box whose
    # value doesn't change those were its only Success (the later ones are
    # SameNoChange): its value never showed in the boxes list, and vMix and UNO
    # (which send only Success unless "Send Same?" is on) never got it.
    import mainwindow

    http_updates = []
    monkeypatch.setattr(mainwindow, "update_http_server", http_updates.append)

    class StartingViewer(FakeViewer):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.timerThread = FakeTimerThread()
            self.timerThread.textDetector = None

        def startCapture(self):
            self.timerThread.ocr_result_signal.emit([make_result("Home Score", "21")])

    monkeypatch.setattr(mainwindow, "ImageViewer", StartingViewer)
    store_data("scoresight.json", "source_selected", "rtsp://10.0.1.200:554/11")
    window = make_window()
    assert [[result.result for result in update] for update in http_updates] == [["21"]]
    assert box_value(window, "Home Score") == "21"


def test_the_boxes_list_shows_the_last_good_reading(main_window, make_result):
    main_window.ocrResult([make_result("Home Score", "21", state="SameNoChange")])
    assert box_value(main_window, "Home Score") == "21"
    main_window.ocrResult([make_result("Home Score", "2l", state="FailedFilter")])
    main_window.ocrResult([make_result("Home Score", "", state="Empty")])
    assert box_value(main_window, "Home Score") == "21"


def test_the_boxes_list_shows_every_reading_state(main_window, make_result):
    # The Value column was greyed out (NoItemFlags) and showed only new
    # (Success) readings: now it shows the state of every reading, and a
    # rejected or empty one keeps the last good value
    from readings_view import REJECTED_TEXT_ROLE, STATE_ROLE, reading_at

    item = box_value_item(main_window, "Home Score")
    assert item.flags() & QtCore.Qt.ItemFlag.ItemIsEnabled
    assert not item.flags() & QtCore.Qt.ItemFlag.ItemIsSelectable
    table = main_window.ui.tableWidget_boxes
    for state, text in (
        ("Success", "21"),
        ("SameNoChange", "21"),
        ("FailedFilter", "2l"),
        ("Empty", ""),
    ):
        main_window.ocrResult([make_result("Home Score", text, state=state)])
        assert item.data(STATE_ROLE) == state
        reading = reading_at(table.indexFromItem(item))
        assert (reading.value, reading.age is not None) == ("21", True)
    assert item.data(REJECTED_TEXT_ROLE) == "2l"
    assert table.itemDelegateForColumn(1) is main_window.readingDelegate
    main_window.show()
    table.grab()  # paints every row


def test_a_click_on_a_reading_selects_its_box(main_window, make_result):
    ui = main_window.ui
    select_box_row(main_window, "Home Score")
    main_window.makeBox()
    main_window.ocrResult([make_result("Home Score", "21")])
    value = box_value_item(main_window, "Home Score")
    ui.tableWidget_boxes.setCurrentItem(value)
    main_window.listItemClicked(value)
    # the name stays the current item: the settings, rename and remove use it
    assert ui.tableWidget_boxes.currentItem().text() == "Home Score"
    assert ui.label_selectedInfo.text() == "Home Score"
    # (the list is disabled until a source opens)
    assert ui.pushButton_removeBox.isEnabledTo(ui.groupBox_sb_info)

    # taken off the picture: its last reading isn't shown as current
    main_window.removeBox()
    assert box_value(main_window, "Home Score") == ""


def test_the_boxes_list_matches_names_not_values(main_window, make_result):
    # a reading that equals another box's name doesn't confuse the list
    main_window.ocrResult([make_result("Home Score", "Period", state="Success")])
    main_window.ocrResult([make_result("Period", "2")])
    assert box_value(main_window, "Home Score") == "Period"
    assert box_value(main_window, "Period") == "2"


# --- the inspector's Box tab and the Fields pane ---------------------------------------


def custom_field_names():
    return fetch_data("scoresight.json", "custom_boxes_names", [])


def test_the_box_tab_shows_the_selected_field(main_window, make_target):
    ui = main_window.ui
    storage = main_window.detectionTargetsStorage
    # nothing selected: how to select one
    assert ui.stackedWidget_boxSettings.currentWidget() is ui.page_boxEmpty
    assert ui.groupBox_allBoxes.isEnabled()  # for every field, always

    # a box on the picture: its reading settings
    storage.add_item(make_target("Home Score"))
    main_window.itemSelected("Home Score")
    assert ui.stackedWidget_boxSettings.currentWidget() is ui.page_boxSettings
    assert ui.label_selectedInfo.text() == "Home Score"
    assert ui.groupBox_target_settings.isEnabled()
    assert not ui.groupBox_target_settings.isHidden()
    assert ui.label_boxNote.isHidden()
    assert ui.pushButton_restoreDefaults.isEnabled()
    # a standard field can't be built from other fields
    assert ui.checkBox_templatefield.isHidden()
    assert "only custom fields" in ui.label_templateHint.text()

    # a field that isn't on the picture: how to place it
    main_window.itemSelected("Home Fouls")
    assert ui.label_selectedInfo.text() == "Home Fouls"
    assert ui.groupBox_target_settings.isHidden()
    assert not ui.groupBox_target_settings.isEnabled()
    assert "Drag over its numbers" in ui.label_boxNote.text()
    assert not ui.pushButton_restoreDefaults.isEnabled()

    # a new custom field is selected; it can become a template
    main_window.addBox()
    [name] = custom_field_names()
    assert ui.label_selectedInfo.text() == name
    assert ui.checkBox_templatefield.isEnabled()
    assert not ui.lineEdit_templatefield.isEnabled()
    ui.checkBox_templatefield.setChecked(True)
    assert storage.find_item_by_name(name).settings["templatefield"]
    assert ui.lineEdit_templatefield.isEnabled()
    assert ui.toolButton_insertField.isEnabled()
    assert ui.groupBox_target_settings.isHidden()
    assert "built from other fields" in ui.label_boxNote.text()

    # a custom field on the picture can't be a template too
    main_window.addBox()
    main_window.makeBox()
    assert not ui.checkBox_templatefield.isEnabled()
    assert "remove it from the picture" in ui.label_templateHint.text()

    # Esc deselects: the explanation again
    main_window.itemSelected(None)
    assert ui.stackedWidget_boxSettings.currentWidget() is ui.page_boxEmpty


def test_the_box_tab_follows_the_keyboard(main_window, make_target, qtbot):
    # The Box tab, the footer and the field's actions followed clicks only: after
    # the arrow keys, Place on picture made a second box for a placed field,
    # and the settings shown were written to another box.
    from PySide6.QtTest import QTest

    ui = main_window.ui
    table = ui.tableWidget_boxes
    storage = main_window.detectionTargetsStorage
    ui.groupBox_sb_info.setEnabled(True)  # as with a source
    storage.add_item(make_target("Away Score", dilate=3))
    with qtbot.waitActive(main_window):
        main_window.show()
        main_window.activateWindow()
    main_window.itemSelected("Time")  # not on the picture
    table.setFocus()
    QTest.keyClick(table, QtCore.Qt.Key.Key_Up)  # Away Score, on the picture
    assert ui.label_selectedInfo.text() == "Away Score"
    assert ui.horizontalSlider_dilate.value() == 3
    assert ui.pushButton_makeBox.isHidden()
    assert not ui.pushButton_removeBox.isHidden()
    ui.horizontalSlider_dilate.setValue(4)
    assert storage.find_item_by_name("Away Score").settings["dilate"] == 4
    QTest.keyClick(table, QtCore.Qt.Key.Key_Up)  # Home Score
    assert ui.label_selectedInfo.text() == "Home Score"
    assert ui.pushButton_makeBox.isEnabled()

    # a field never gets a second box, nor a box and a template
    main_window.itemSelected("Away Score")
    main_window.makeBox()
    main_window.makeTemplateField(True)
    assert [box.name for box in storage.get_data()] == ["Away Score"]
    assert not storage.find_item_by_name("Away Score").settings["templatefield"]


def test_an_imported_layout_replaces_the_placed_fields(
    main_window, make_target, tmp_path, monkeypatch
):
    # Fields whose box wasn't in the imported file stayed "on the picture"
    import json

    import mainwindow

    ui = main_window.ui
    storage = main_window.detectionTargetsStorage
    storage.add_item(make_target("Home Score"))
    storage.add_item(make_target("Time"))
    main_window.itemSelected("Home Score")
    layout = tmp_path / "layout.json"
    rect = {"x": 1, "y": 2, "width": 30, "height": 20}
    layout.write_text(
        json.dumps(
            {
                "boxes_schema_version": 2,
                "boxes": [{"name": "Time", "rect": rect, "settings": {}}],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        mainwindow.QFileDialog,
        "getOpenFileName",
        lambda *args, **kwargs: (str(layout), ""),
    )
    main_window.importConfiguration()
    role = QtCore.Qt.ItemDataRole.UserRole
    assert box_name_item(main_window, "Home Score").data(role) == "unchecked"
    assert box_name_item(main_window, "Time").data(role) == "checked"
    # the Box tab says Home Score isn't on the picture any more
    assert ui.groupBox_target_settings.isHidden()
    assert not ui.pushButton_makeBox.isHidden()


def test_when_blank_is_stored_per_box(make_window, make_target):
    window = make_window()
    ui = window.ui
    storage = window.detectionTargetsStorage
    storage.add_item(make_target("Home Score"))
    storage.add_item(make_target("Away Score", clear_value="blank"))
    combo = ui.comboBox_clearValue
    assert [combo.itemText(i) for i in range(combo.count())] == [
        "Keep the last value",
        "Clear the value",
        "Clear the value, also at zero",
    ]
    window.itemSelected("Home Score")
    assert combo.currentIndex() == 0
    combo.setCurrentIndex(2)
    assert storage.find_item_by_name("Home Score").settings["clear_value"] == (
        "blank_or_zero"
    )
    window.itemSelected("Away Score")
    assert combo.currentIndex() == 1
    window.itemSelected("Home Score")
    assert combo.currentIndex() == 2


def test_the_image_cleanup_section(make_window, make_target):
    window = make_window()
    ui = window.ui
    storage = window.detectionTargetsStorage
    # collapsed at first, with what it holds in plain words (the tooltips
    # have the names of 0.1.x)
    assert not ui.toolButton_imageCleanup.isChecked()
    assert ui.frame_imageCleanup.isHidden()
    assert ui.label_binarizationMethod.text() == "Black & white"
    assert "Binarize" in ui.label_binarizationMethod.toolTip()
    # the stored index keeps its meaning
    assert [ui.comboBox_binarizationMethod.itemText(i) for i in range(4)] == [
        "Whole picture",
        "None",
        "This box",
        "Adaptive",
    ]
    # 0.1.x's Skip empty values had no effect since 0.2.0: gone
    assert not hasattr(ui, "checkBox_skip_empty")

    # how many of its settings were changed
    storage.add_item(make_target("Home Score", dilate=2, binarization_method=2))
    window.itemSelected("Home Score")
    assert ui.label_imageCleanupBadge.text() == "2 changed"
    ui.checkBox_invertPatch.setChecked(True)
    assert ui.label_imageCleanupBadge.text() == "3 changed"
    ui.horizontalSlider_conf_thresh.setValue(30)  # Filtering: not counted
    assert ui.label_imageCleanupBadge.text() == "3 changed"
    ui.pushButton_restoreDefaults.click()
    assert ui.label_imageCleanupBadge.text() == "all default"
    assert storage.find_item_by_name("Home Score").settings["dilate"] == 1

    # opened, and still open at the next start
    ui.toolButton_imageCleanup.click()
    assert not ui.frame_imageCleanup.isHidden()
    assert ui.toolButton_imageCleanup.arrowType() == QtCore.Qt.ArrowType.DownArrow
    assert fetch_data("scoresight.json", "image_cleanup_expanded") is True
    window.close()
    again = make_window()
    assert again.ui.toolButton_imageCleanup.isChecked()
    assert not again.ui.frame_imageCleanup.isHidden()


def test_the_binary_view_shortcut(main_window, make_target):
    ui = main_window.ui
    main_window.detectionTargetsStorage.add_item(make_target("Home Score"))
    main_window.itemSelected("Home Score")
    main_window.setViewToolsEnabled(True)  # as with a source
    ui.toolButton_cleanupBinary.click()
    assert ui.pushButton_binary.isChecked()
    assert ui.toolButton_cleanupBinary.isChecked()
    ui.actionBinaryView.trigger()  # Ctrl+B
    assert not ui.toolButton_cleanupBinary.isChecked()
    # no source: the view tools are off, and so is the shortcut
    main_window.setViewToolsEnabled(False)
    ui.toolButton_cleanupBinary.click()
    assert not ui.pushButton_binary.isChecked()
    assert not ui.toolButton_cleanupBinary.isChecked()


def test_the_format_shows_its_preset_and_an_invalid_expression(
    main_window, make_target
):
    from defaults import format_prefixes

    ui = main_window.ui
    storage = main_window.detectionTargetsStorage
    storage.add_item(make_target("Home Score"))
    main_window.itemSelected("Home Score")
    combo = ui.comboBox_formatPrefix
    assert combo.currentText() == "Score 1dd"  # the field's default format
    # the list's items are the presets, in their order, then Custom
    assert combo.count() == len(format_prefixes)
    assert combo.itemText(1) == "Time mm:ss or ss:d"
    ui.lineEdit_format.setText("^[0-3]\\d\\d$")
    assert combo.currentText() == "Custom"
    combo.setCurrentIndex(2)
    assert ui.lineEdit_format.text() == format_prefixes[2]
    assert (
        storage.find_item_by_name("Home Score").settings["format_regex"]
        == (format_prefixes[2])
    )
    assert combo.currentText() == "Time mm:ss"
    # "Custom" keeps the expression, to edit it
    combo.setCurrentIndex(combo.count() - 1)
    assert ui.lineEdit_format.text() == format_prefixes[2]

    # an expression the OCR can't use (it ignores it) is marked
    assert ui.label_formatStatus.isHidden()
    ui.lineEdit_format.setText("^(1?\\d$")
    assert not ui.label_formatStatus.isHidden()
    assert "ignored" in ui.label_formatStatus.text()
    assert "missing )" in ui.label_formatStatus.toolTip()
    assert "border" in ui.lineEdit_format.styleSheet()
    ui.lineEdit_format.setText("^1?\\d$")
    assert ui.label_formatStatus.isHidden()
    assert ui.lineEdit_format.styleSheet() == ""


def test_a_shot_clock_saved_by_0_3_0_shows_its_preset(make_window):
    # up to 0.3.0 the Shotclock 0-39 preset took exactly two digits; a box
    # that stored it is migrated to the preset's expression, so the Format list
    # still shows the preset (not Custom)
    import storage
    from defaults import format_prefixes

    store_data(
        "scoresight.json",
        "boxes",
        [
            {
                "name": "Shot Clock",
                "rect": {"x": 1, "y": 2, "width": 3, "height": 4},
                "settings": {"format_regex": "^[0-3]\\d$"},
            }
        ],
    )
    store_data("scoresight.json", storage.BOXES_SCHEMA_KEY, 2)
    window = make_window()
    window.itemSelected("Shot Clock")
    assert window.ui.comboBox_formatPrefix.currentText() == "Shotclock 0-39"
    assert window.ui.lineEdit_format.text() == format_prefixes[5]
    assert fetch_data("scoresight.json", storage.BOXES_SCHEMA_KEY) == 3


def test_insert_field_into_a_template(main_window, make_target):
    ui = main_window.ui
    storage = main_window.detectionTargetsStorage
    storage.add_item(make_target("Home Score"))
    main_window.addBox()
    [name] = custom_field_names()
    ui.checkBox_templatefield.setChecked(True)
    handler = main_window.boxSettingsUiHandler
    handler.fillInsertFieldMenu()
    actions = {action.text(): action for action in handler.insertFieldMenu.actions()}
    # every other field, and whether it's on the picture
    assert "Home Score" in actions
    assert "Away Score (not on the picture)" in actions
    assert name not in actions
    ui.lineEdit_templatefield.setText("Score: ")
    actions["Home Score"].trigger()
    assert ui.lineEdit_templatefield.text() == "Score: {{Home Score}}"
    assert storage.find_item_by_name(name).settings["templatefield_text"] == (
        "Score: {{Home Score}}"
    )


def test_the_fields_footer_shows_what_applies(main_window):
    ui = main_window.ui
    ui.groupBox_sb_info.setEnabled(True)  # as with a source
    # nothing selected
    assert not ui.pushButton_makeBox.isHidden()
    assert not ui.pushButton_makeBox.isEnabled()
    assert ui.pushButton_removeBox.isHidden()
    assert ui.toolButton_removeBox.isHidden()
    # a standard field, not on the picture: Place on picture, no Delete
    main_window.itemSelected("Home Score")
    assert ui.pushButton_makeBox.isEnabled()
    assert ui.pushButton_removeBox.isHidden()
    assert ui.toolButton_removeBox.isHidden()
    ui.pushButton_makeBox.click()
    assert main_window.detectionTargetsStorage.find_item_by_name("Home Score")
    assert ui.tabWidget_inspector.currentWidget() is ui.tab_box
    # on the picture: Remove from picture instead
    assert ui.pushButton_makeBox.isHidden()
    assert not ui.pushButton_removeBox.isHidden()
    assert ui.pushButton_removeBox.isEnabled()
    # a custom field: Delete field too
    main_window.addBox()
    assert not ui.toolButton_removeBox.isHidden()
    assert ui.pushButton_makeBox.isEnabled()
    # a template field: neither Place nor Remove
    ui.checkBox_templatefield.setChecked(True)
    assert ui.pushButton_makeBox.isHidden() and ui.pushButton_removeBox.isHidden()
    assert not ui.toolButton_removeBox.isHidden()


def test_the_fields_hint_before_a_source(make_window):
    store_data("scoresight.json", "source_selected", "rtsp://10.0.1.200:554/11")
    window = make_window()
    ui = window.ui
    # the source is opening: no picture yet
    assert not ui.groupBox_sb_info.isEnabled()
    assert not ui.label_fieldsHint.isHidden()
    window.cameraConnectedEnableUI()  # the first frame
    assert ui.label_fieldsHint.isHidden()
    ui.comboBox_camera_source.setCurrentIndex(0)  # no source
    assert not ui.label_fieldsHint.isHidden()


def test_removing_a_tuned_box_from_the_picture_asks_first(main_window):
    ui = main_window.ui
    asked = []
    answer = [False]
    main_window.confirm = lambda title, text, action: asked.append(text) or answer[0]
    storage = main_window.detectionTargetsStorage
    main_window.itemSelected("Home Score")
    main_window.makeBox()
    # nothing to lose: no question
    main_window.removeFromPicture()
    assert asked == []
    assert storage.find_item_by_name("Home Score") is None
    # its settings were changed: Cancel keeps it
    main_window.makeBox()
    ui.horizontalSlider_dilate.setValue(3)
    main_window.removeFromPicture()
    assert len(asked) == 1 and "Home Score" in asked[0]
    assert storage.find_item_by_name("Home Score") is not None
    answer[0] = True
    main_window.removeFromPicture()
    assert storage.find_item_by_name("Home Score") is None
    assert box_name_item(main_window, "Home Score").data(
        QtCore.Qt.ItemDataRole.UserRole
    ) == ("unchecked")


def test_deleting_a_custom_field_asks_first(main_window):
    ui = main_window.ui
    asked = []
    answers = [False, True]
    main_window.confirm = lambda title, text, action: (
        asked.append(text) or answers.pop(0)
    )
    main_window.addBox()
    [name] = custom_field_names()
    main_window.deleteField()  # Cancel
    assert name in box_rows(main_window)
    main_window.deleteField()  # Delete
    assert name not in box_rows(main_window)
    assert custom_field_names() == []
    assert len(asked) == 2 and name in asked[0]
    # nothing is selected after it
    assert ui.stackedWidget_boxSettings.currentWidget() is ui.page_boxEmpty
    # a standard field isn't deleted (nor asked about)
    main_window.itemSelected("Home Score")
    main_window.deleteField()
    assert len(asked) == 2 and "Home Score" in box_rows(main_window)


def test_the_fields_context_menu(main_window, make_result, qapp):
    from PySide6.QtGui import QGuiApplication

    ui = main_window.ui
    main_window.itemSelected("Time")
    menu = main_window.fieldContextMenu()
    names = [action.objectName() for action in menu.actions()]
    assert names[0] == "actionPlaceOnPicture"  # not on the picture yet
    menu.deleteLater()

    main_window.makeBox()
    main_window.ocrResult([make_result("Time", "04:23")])
    menu = main_window.fieldContextMenu()
    names = [action.objectName() for action in menu.actions() if action.objectName()]
    assert names == [
        "actionRemoveFromPicture",
        "actionRenameField",
        "actionDeleteField",
        "actionResetFieldSettings",
        "actionCopyValue",
        "actionHoldValue",
        "actionZoomToBox",
    ]
    assert ui.actionHoldValue.isEnabled()
    # a standard field: no Rename or Delete, and the menu says why
    assert not ui.actionRenameField.isEnabled()
    assert not ui.actionDeleteField.isEnabled()
    assert "custom fields" in ui.actionRenameField.toolTip()
    assert ui.actionResetFieldSettings.isEnabled()
    assert not ui.actionZoomToBox.isEnabled()  # no picture
    ui.actionCopyValue.trigger()
    assert QGuiApplication.clipboard().text() == "04:23"
    menu.deleteLater()

    # a custom field
    main_window.addBox()
    main_window.fieldContextMenu().deleteLater()
    assert ui.actionRenameField.isEnabled() and ui.actionDeleteField.isEnabled()
    assert not ui.actionCopyValue.isEnabled()  # no value yet
    assert not ui.actionResetFieldSettings.isEnabled()  # no box
    # nothing to hold: it isn't read
    assert not ui.actionHoldValue.isEnabled()
    assert "picture first" in ui.actionHoldValue.toolTip()


def test_zoom_to_box(main_window, make_target, qtbot):
    # with the real viewer (not capturing): it fits the whole picture again
    # when its viewport is resized, which zooming in does
    from PySide6.QtCore import QRectF

    from source_view import MAX_ZOOM, ImageViewer

    ui = main_window.ui
    storage = main_window.detectionTargetsStorage
    viewer = ImageViewer(
        CameraInfo("stub", "stub", "stub", CameraInfo.CameraType.FILE),
        lambda corners: None,
        storage,
        lambda name: None,
        start=False,
    )
    try:
        viewer.resize(800, 450)
        with qtbot.waitExposed(viewer):
            viewer.show()
        viewer.scene.setSceneRect(0, 0, 1920, 1080)
        viewer.resetZoom()
        whole = viewer.transform().m11()
        main_window.image_viewer = viewer
        viewer.firstFrameReceived = True
        main_window.connectViewer()
        box = make_target("Home Score", rect=(900, 500, 120, 60))
        storage.add_item(box)
        main_window.itemSelected("Home Score")
        main_window.fieldContextMenu().deleteLater()
        assert ui.actionZoomToBox.isEnabled()
        ui.actionZoomToBox.trigger()
        qtbot.wait(100)  # the viewport's resize has been handled
        zoom = viewer.transform().m11()
        assert whole * 5 < zoom <= MAX_ZOOM
        # the zoom readout follows
        assert ui.label_zoom.text() == f"{round(zoom * 100)}%"
        # the box, with some of the picture around it
        shown = viewer.mapToScene(viewer.viewport().rect()).boundingRect()
        assert shown.contains(QRectF(box))
        assert shown.width() < 400
    finally:
        main_window.image_viewer = None
        viewer.close()
        viewer.deleteLater()


def test_renaming_to_a_used_name_says_so(main_window, monkeypatch):
    import mainwindow

    ui = main_window.ui
    main_window.addBox()
    [name] = custom_field_names()
    answers = [("  time ", True), ("Score Line", True)]
    asked_with = []

    def get_text(parent, title, label, text=""):
        asked_with.append(text)
        return answers.pop(0)

    warnings = []
    monkeypatch.setattr(mainwindow.QInputDialog, "getText", get_text)
    monkeypatch.setattr(
        mainwindow.QMessageBox,
        "warning",
        lambda parent, title, text: warnings.append(text),
    )
    ui.actionRenameField.trigger()  # F2
    # "time" is the Time field (names that differ only in case are the same)
    assert len(warnings) == 1 and "“time”" in warnings[0]
    # asked again, with the name typed
    assert asked_with == [name, "time"]
    assert "Score Line" in box_rows(main_window)
    assert custom_field_names() == ["Score Line"]
    assert ui.label_selectedInfo.text() == "Score Line"


def test_pausing_the_outputs_shows_everywhere(main_window, patched, make_result):
    ui = main_window.ui
    main_window.show()
    assert ui.pushButton_stopUpdates.text() == "Pause outputs"
    assert not ui.frame_pausedBanner.isVisibleTo(main_window)
    assert main_window.statusBarWidgets.label_paused.isHidden()

    main_window.ui.actionPauseOutputs.trigger()  # Ctrl+Shift+P
    assert ui.pushButton_stopUpdates.isChecked()
    assert ui.pushButton_stopUpdates.text() == "Resume outputs"
    assert ":checked" in ui.pushButton_stopUpdates.styleSheet()
    # bold, and as wide as its bold text ("Resume output" was cut off)
    from PySide6.QtGui import QFontMetrics

    button = ui.pushButton_stopUpdates
    assert button.font().bold()
    assert button.sizeHint().width() >= (
        QFontMetrics(button.font()).horizontalAdvance(button.text())
        + button.iconSize().width()
    )
    assert ui.frame_pausedBanner.isVisibleTo(main_window)
    assert "Outputs paused" in ui.label_pausedBanner.text()
    assert main_window.windowTitle() == f"⏸ ScoreSight - v{__version__}"
    chip = main_window.statusBarWidgets.label_paused
    assert not chip.isHidden() and chip.text().startswith("PAUSED 00:0")
    assert main_window.readingDelegate.paused
    # the readings keep updating, the outputs don't get them
    main_window.obs_websocket_client = FakeObsClient()
    main_window.ocrResult([make_result("Home Score", "12")])
    assert box_value(main_window, "Home Score") == "12"
    assert patched["obs"] == []

    ui.pushButton_resumeOutputs.click()  # the banner's Resume
    assert not ui.pushButton_stopUpdates.isChecked()
    assert not ui.frame_pausedBanner.isVisibleTo(main_window)
    assert main_window.windowTitle() == f"ScoreSight - v{__version__}"
    assert chip.isHidden()
    assert not main_window.readingDelegate.paused


def test_the_keyboard_shortcuts(main_window, qtbot):
    ui = main_window.ui
    shortcuts = {
        action.objectName(): action.shortcut().toString()
        for action in main_window.actions()
    }
    import platform

    assert shortcuts == {
        "actionPauseOutputs": "Ctrl+Shift+P",
        "actionBinaryView": "Ctrl+B",
        "actionFitPicture": "Ctrl+0",
        "actionZoomIn": "Ctrl+=",
        "actionZoomOut": "Ctrl+-",
        "actionReloadSources": "F5",
        "actionNewField": "Ctrl+N",
        "actionSetupLayout": "Ctrl+1",
        "actionLiveLayout": "Ctrl+2",
        # ⌘H hides the app on macOS: ⌃H there
        "actionHoldValue": "Meta+H" if platform.system() == "Darwin" else "Ctrl+H",
        "actionImportConfiguration": "Ctrl+O",
        "actionExportConfiguration": "Ctrl+Shift+S",
        "actionViewLog": "Ctrl+Shift+L",
        "actionUserGuide": "F1",
        "actionQuit": "Ctrl+Q",
    }
    # the selected field's keys, while the fields list has the focus
    table = ui.tableWidget_boxes
    field_keys = {
        action.objectName(): action.shortcut().toString() for action in table.actions()
    }
    # (Del removes the box of a field on the picture, see
    # test_del_removes_the_box_or_deletes_the_field)
    assert field_keys == {
        "actionRenameField": "F2",
        "actionRemoveFromPicture": "",
        "actionDeleteField": "Del",
        "actionCopyValue": "Ctrl+C",
    }
    assert all(
        action.shortcutContext() == QtCore.Qt.ShortcutContext.WidgetShortcut
        for action in table.actions()
    )
    from PySide6.QtTest import QTest

    with qtbot.waitActive(main_window):
        main_window.show()
        main_window.activateWindow()
    # through the window, as a real key press (shortcuts are matched there)
    QTest.keyClick(
        main_window.windowHandle(),
        QtCore.Qt.Key.Key_P,
        QtCore.Qt.KeyboardModifier.ControlModifier
        | QtCore.Qt.KeyboardModifier.ShiftModifier,
    )
    assert ui.pushButton_stopUpdates.isChecked()
    # the tooltip shows the shortcut as the platform writes it (⌘B on macOS)
    native = QKeySequence.SequenceFormat.NativeText
    assert QKeySequence("Ctrl+B").toString(native) in ui.pushButton_binary.toolTip()
    # the buttons do nothing while they are disabled (no source yet)
    assert not ui.widget_viewTools.isEnabled()
    ui.actionBinaryView.trigger()
    assert not ui.pushButton_binary.isChecked()

    # Ctrl+N: a new custom field, selected
    QTest.keyClick(
        main_window.windowHandle(),
        QtCore.Qt.Key.Key_N,
        QtCore.Qt.KeyboardModifier.ControlModifier,
    )
    [name] = custom_field_names()
    assert ui.label_selectedInfo.text() == name

    # Ctrl+2 and Ctrl+1: the Live and the Setup layout
    QTest.keyClick(
        main_window.windowHandle(),
        QtCore.Qt.Key.Key_2,
        QtCore.Qt.KeyboardModifier.ControlModifier,
    )
    assert main_window.layoutMode == "live" and ui.actionLiveLayout.isChecked()
    QTest.keyClick(
        main_window.windowHandle(),
        QtCore.Qt.Key.Key_1,
        QtCore.Qt.KeyboardModifier.ControlModifier,
    )
    assert main_window.layoutMode == "setup" and ui.actionSetupLayout.isChecked()


def test_ctrl_c_in_the_fields_list_copies_the_value(main_window, make_result, qtbot):
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtTest import QTest

    ui = main_window.ui
    ui.groupBox_sb_info.setEnabled(True)  # as with a source
    main_window.itemSelected("Time")
    main_window.makeBox()
    main_window.ocrResult([make_result("Time", "04:23")])
    with qtbot.waitActive(main_window):
        main_window.show()
        main_window.activateWindow()
    ui.tableWidget_boxes.setFocus()
    QGuiApplication.clipboard().setText("")
    # (the list copies the current item, the field's name, by itself)
    QTest.keyClick(
        ui.tableWidget_boxes,
        QtCore.Qt.Key.Key_C,
        QtCore.Qt.KeyboardModifier.ControlModifier,
    )
    assert QGuiApplication.clipboard().text() == "04:23"


def test_resuming_sends_unchanged_values_to_vmix_and_uno(
    main_window, make_result, make_target
):
    # A value that changed while the outputs were paused is an unchanged
    # (SameNoChange) reading after resuming, which vMix and UNO don't send.
    # Each box's first good reading after resuming is sent anyway.
    calls = []
    vmix = main_window.vmixUiHandler.vmixUpdater
    uno = main_window.unoUiHandler.unoUpdater
    vmix.update_vmix = lambda results, resend_unchanged=(): calls.append(
        ("vmix", set(resend_unchanged))
    )
    uno.update_uno = lambda results, resend_unchanged=(): calls.append(
        ("uno", set(resend_unchanged))
    )
    storage = main_window.detectionTargetsStorage
    storage.add_item(make_target("Home Score"))
    storage.add_item(make_target("Time"))

    def cycle(home, time):
        calls.clear()
        main_window.ocrResult(
            [make_result("Home Score", *home), make_result("Time", *time)]
        )
        return calls[:]

    assert cycle(("12", "Success"), ("1:00", "Success")) == [
        ("vmix", set()),
        ("uno", set()),
    ]
    main_window.ui.pushButton_stopUpdates.setChecked(True)
    assert cycle(("13", "Success"), ("0:45", "Success")) == []  # paused
    main_window.ui.pushButton_stopUpdates.setChecked(False)
    # the clock's first reading after resuming is rejected: it stays pending
    both = {"Home Score", "Time"}
    assert cycle(("13", "SameNoChange"), ("0:4S", "FailedFilter")) == [
        ("vmix", both),
        ("uno", both),
    ]
    assert cycle(("13", "SameNoChange"), ("0:45", "SameNoChange")) == [
        ("vmix", {"Time"}),
        ("uno", {"Time"}),
    ]
    assert cycle(("13", "SameNoChange"), ("0:45", "SameNoChange")) == [
        ("vmix", set()),
        ("uno", set()),
    ]


class FakeCaptureThread(FakeTimerThread):
    def __init__(self):
        super().__init__()
        import time

        self.frame_size = (1280, 720)
        self.fps = 29.97
        self.ups = 4.8
        self.update_frame_interval = 200
        self.last_frame_timestamp = time.monotonic()
        self.textDetector = None


def test_the_status_bar(make_window, monkeypatch, patched):
    import mainwindow

    class RunningViewer(FakeViewer):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.timerThread = FakeCaptureThread()
            self.firstFrameReceived = True

    monkeypatch.setattr(mainwindow, "ImageViewer", RunningViewer)
    monkeypatch.setattr(mainwindow, "primary_lan_address", lambda: "192.168.1.20")
    store_data("scoresight.json", "source_selected", "rtsp://user:pw@10.0.1.200:554/11")
    window = make_window(http_port=18100)
    window.refreshLiveStatus()
    bar = window.statusBarWidgets
    assert "rtsp://10.0.1.200:554/11 · 1280×720 · 30.0 fps" in bar.label_source.text()
    assert "pw" not in bar.label_source.text()
    assert bar.label_ocr.text() == "Reading 4.8/s of 5"
    assert bar.label_http.text() == "http://192.168.1.20:18100"
    assert "http://localhost:18100" in bar.label_http.toolTip()

    window.updateError("Unable to play the stream")
    window.refreshLiveStatus()
    assert "can't be read" in bar.label_source.text()
    window.reset_playing_source()
    window.refreshLiveStatus()
    assert "No source" in bar.label_source.text()


def test_the_status_bar_when_the_http_port_is_busy(make_window, patched):
    patched["http_port_busy"] = True
    window = make_window(http_port=18100)
    bar = window.statusBarWidgets
    assert "not running (port 18100 busy)" in bar.label_http.text()
    assert bar.button_copy.isHidden()
    status = destination_status(window, "http")
    assert (status.state, status.detail) == (
        "error",
        "Not running: port 18100 is in use",
    )
    assert "■" in bar.output_buttons["http"].toolTip()


# --- the output destinations -----------------------------------------------------------


def destination_index(window, key):
    model = window.destinationsModel
    return model.index(model.rowOf(key), 0)


def destination_status(window, key):
    window.refreshLiveStatus()
    return window.destinationsModel.status(key)


def switch_is_on(window, key):
    model = window.destinationsModel
    return model.item(model.rowOf(key)).checkState() == QtCore.Qt.CheckState.Checked


def free_port():
    import socket

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_the_outputs_are_destinations_over_their_pages(main_window):
    from PySide6.QtTest import QTest

    ui = main_window.ui
    model = main_window.destinationsModel
    # the Outputs tab of the inspector, in a laptop-sized window
    main_window.resize(1366, 768)
    main_window.show()
    ui.tabWidget_inspector.setCurrentWidget(ui.widget_outputs)
    # the list over the pages, with a divider to give the pages more room
    assert ui.splitter_outputs.widget(0) is ui.listView_destinations
    assert ui.splitter_outputs.widget(1).isAncestorOf(ui.stackedWidget_outputs)
    names = [model.item(row).text() for row in range(model.rowCount())]
    assert names == [
        "Text files",
        "HTTP server",
        "OBS",
        "vMix",
        "UNO",
        "HTTP API",
        "TCP / UDP",
    ]
    stack = ui.stackedWidget_outputs
    assert [stack.widget(i).objectName() for i in range(stack.count())] == [
        "tab_textFiles",
        "tab_browser",
        "tab_obs",
        "tab_vmix",
        "tab_uno",
        "tab_api",
        "tab_tcp",
    ]
    assert not hasattr(ui, "tabWidget_outputs")
    # the first one shows, as the first tab did
    assert ui.listView_destinations.currentIndex().row() == 0
    assert stack.currentWidget() is ui.tab_textFiles
    # a destination shows its page, with the controls it always had
    ui.listView_destinations.setCurrentIndex(destination_index(main_window, "vmix"))
    assert stack.currentWidget() is ui.tab_vmix
    assert ui.tab_vmix.isAncestorOf(ui.pushButton_startvmix)
    # the keyboard moves between them
    QTest.keyClick(ui.listView_destinations, QtCore.Qt.Key.Key_Down)
    assert stack.currentWidget() is ui.tab_uno
    # every destination shows without scrolling
    view = ui.listView_destinations
    assert view.height() >= model.rowCount() * view.sizeHintForRow(0)
    # the state is told by a glyph and words too (never by colour alone)
    main_window.refreshLiveStatus()
    vmix = destination_index(main_window, "vmix")
    assert vmix.data(QtCore.Qt.ItemDataRole.AccessibleTextRole) == "vMix, off, Off"
    view.grab()  # paints every row


def test_the_switches_mirror_the_output_controls(main_window):
    ui = main_window.ui
    model = main_window.destinationsModel
    vmix = main_window.vmixUiHandler.vmixUpdater
    uno = main_window.unoUiHandler.unoUpdater
    main_window.refreshLiveStatus()
    assert not any(switch_is_on(main_window, key) for key in ("vmix", "uno", "api"))

    # the outputs' own controls move the switches...
    ui.pushButton_startvmix.setChecked(True)
    assert vmix.running and switch_is_on(main_window, "vmix")
    ui.toolButton_toggleUno.setChecked(True)
    assert uno.running and switch_is_on(main_window, "uno")
    ui.checkBox_enableOutAPI.setChecked(True)
    assert switch_is_on(main_window, "api")

    # ...and the switches operate the controls, which stay the source of truth
    model.setData(
        destination_index(main_window, "vmix"),
        QtCore.Qt.CheckState.Unchecked,
        QtCore.Qt.ItemDataRole.CheckStateRole,
    )
    assert not ui.pushButton_startvmix.isChecked() and not vmix.running
    assert ui.pushButton_startvmix.text() == "Start vMix"
    assert not switch_is_on(main_window, "vmix")
    model.requestToggle(destination_index(main_window, "uno"))
    assert not ui.toolButton_toggleUno.isChecked() and not uno.running
    model.requestToggle(destination_index(main_window, "api"))
    assert not ui.checkBox_enableOutAPI.isChecked()
    assert fetch_data("scoresight.json", "enable_out_api") is False
    model.requestToggle(destination_index(main_window, "api"))
    assert ui.checkBox_enableOutAPI.isChecked()
    assert fetch_data("scoresight.json", "enable_out_api") is True

    # the HTTP server is always on: it has no switch
    http = destination_index(main_window, "http")
    assert not model.flags(http) & QtCore.Qt.ItemFlag.ItemIsUserCheckable
    model.requestToggle(http)
    assert model.status("http").enabled and not model.status("http").switchable


def test_a_switch_is_clicked_or_toggled_with_space(main_window, qtbot):
    from PySide6.QtTest import QTest

    ui = main_window.ui
    view = ui.listView_destinations
    with qtbot.waitExposed(main_window):
        main_window.show()
    main_window.showDestination("vmix")
    main_window.refreshLiveStatus()
    rect = view.visualRect(destination_index(main_window, "vmix"))
    switch = main_window.destinationDelegate.switchRect(rect).center().toPoint()
    QTest.mouseClick(view.viewport(), QtCore.Qt.MouseButton.LeftButton, pos=switch)
    assert ui.pushButton_startvmix.isChecked()
    # a click on the row elsewhere selects it, nothing more
    QTest.mouseClick(
        view.viewport(), QtCore.Qt.MouseButton.LeftButton, pos=rect.center()
    )
    assert ui.pushButton_startvmix.isChecked()
    QTest.keyClick(view, QtCore.Qt.Key.Key_Space)
    assert not ui.pushButton_startvmix.isChecked()


def test_the_text_files_switch_chooses_or_forgets_the_folder(
    main_window, monkeypatch, tmp_path, qtbot, make_result
):
    import mainwindow

    monkeypatch.setattr(
        mainwindow.QFileDialog,
        "getExistingDirectory",
        lambda *args, **kwargs: str(tmp_path),
    )
    model = main_window.destinationsModel
    assert destination_status(main_window, "files").state == "off"
    model.requestToggle(destination_index(main_window, "files"))
    qtbot.waitUntil(lambda: main_window.out_folder == str(tmp_path))
    assert main_window.ui.lineEdit_folder.text() == str(tmp_path)
    status = destination_status(main_window, "files")
    assert (status.state, status.enabled) == ("sending", True)  # nothing read yet

    main_window.ocrResult([make_result("Home Score", "3")])
    status = destination_status(main_window, "files")
    assert status.state == "ok" and status.detail.endswith("· 1 file")
    assert status.last_activity_at is not None

    model.requestToggle(destination_index(main_window, "files"))
    assert main_window.out_folder is None
    assert fetch_data("scoresight.json", "output_folder") is None
    assert destination_status(main_window, "files").state == "off"


def test_a_missing_output_folder_is_reported(main_window, tmp_path, make_result):
    ui = main_window.ui
    folder = tmp_path / "gone"
    folder.mkdir()
    main_window.setOutputFolder(str(folder))
    folder.rmdir()
    main_window.ocrResult([make_result("Home Score", "3")])
    status = destination_status(main_window, "files")
    assert (status.state, status.enabled) == ("error", False)
    assert status.detail.startswith("Folder not found")
    main_window.showDestination("files")
    assert ui.frame_destinationStatus.isVisibleTo(main_window)
    assert "Folder not found" in ui.label_destinationStatus.text()
    main_window.setOutputFolder(str(tmp_path))
    assert destination_status(main_window, "files").state != "error"
    assert not ui.frame_destinationStatus.isVisibleTo(main_window)


def test_the_status_bar_shows_every_output_and_opens_it(main_window):
    ui = main_window.ui
    bar = main_window.statusBarWidgets
    main_window.refreshLiveStatus()
    assert not bar.widget_outputs.isHidden()
    texts = [button.text() for button in bar.output_buttons.values()]
    assert texts == ["Files", "HTTP", "OBS", "vMix", "UNO", "API", "TCP"]
    vmix = bar.output_buttons["vmix"]
    assert vmix.toolTip().startswith("vMix: ○ off")
    assert vmix.accessibleName() == "vMix: off"
    assert not vmix.icon().isNull()

    # the inspector shows the Outputs tab, also when it was hidden
    main_window.resize(1366, 768)
    main_window.show()
    ui.tabWidget_inspector.setCurrentWidget(ui.tab_box)
    main_window.setPaneHidden(2, True)
    assert main_window.isPaneHidden(2)
    bar.output_buttons["api"].click()
    assert ui.tabWidget_inspector.currentWidget() is ui.widget_outputs
    assert not main_window.isPaneHidden(2)
    assert ui.listView_destinations.currentIndex().row() == 5
    assert ui.stackedWidget_outputs.currentWidget() is ui.tab_api
    bar.output_buttons["obs"].click()
    assert ui.stackedWidget_outputs.currentWidget() is ui.tab_obs


def test_an_unreachable_vmix_shows_everywhere(main_window, make_result, qtbot):
    ui = main_window.ui
    port = free_port()  # nothing listens there
    ui.lineEdit_vmixHost.setText("127.0.0.1")
    ui.lineEdit_vmixHost.editingFinished.emit()
    ui.lineEdit_vmixPort.setText(str(port))
    ui.lineEdit_vmixPort.editingFinished.emit()
    vmix = main_window.vmixUiHandler.vmixUpdater
    vmix.set_field_mapping({"Time": "CLOCK.Text"})
    ui.pushButton_startvmix.setChecked(True)
    assert destination_status(main_window, "vmix").state == "sending"

    main_window.ocrResult([make_result("Time", "1:00")])
    qtbot.waitUntil(
        lambda: destination_status(main_window, "vmix").state == "retrying",
        timeout=15000,
    )
    status = main_window.destinationsModel.status("vmix")
    assert f"127.0.0.1:{port}" in status.detail and "retrying" in status.detail
    # the details over the vMix page say what to do
    main_window.showDestination("vmix")
    assert ui.frame_destinationStatus.isVisibleTo(main_window)
    assert f"127.0.0.1:{port}" in ui.label_destinationStatus.text()
    assert "Web Controller" in ui.label_destinationStatus.text()
    # and the status bar: a triangle (not only a colour)
    button = main_window.statusBarWidgets.output_buttons["vmix"]
    assert button.toolTip().startswith("vMix: ▲ retrying")

    ui.pushButton_startvmix.setChecked(False)  # Stop vMix
    assert destination_status(main_window, "vmix").state == "off"
    assert not ui.frame_destinationStatus.isVisibleTo(main_window)


class LineReceiver:
    """A TCP server on 127.0.0.1 that keeps what its connections send."""

    def __init__(self):
        import socket

        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(4)
        self.port = self.sock.getsockname()[1]
        self.data = bytearray()
        self.connections = 0
        self.lock = threading.Lock()
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        while True:
            try:
                client, _ = self.sock.accept()
            except OSError:
                return
            with self.lock:
                self.connections += 1
            threading.Thread(target=self._read, args=(client,), daemon=True).start()

    def _read(self, client):
        while True:
            try:
                data = client.recv(4096)
            except OSError:
                return
            if not data:
                return
            with self.lock:
                self.data += data

    def received(self) -> bytes:
        with self.lock:
            return bytes(self.data)

    def close(self):
        self.sock.close()


def test_the_tcp_output_page(main_window, make_target, make_result, qtbot):
    from tcp_output import CASPARCG, LIVE_SCORE

    window_ui = main_window.ui
    tcp = main_window.tcpUiHandler
    ui = tcp.ui
    model = main_window.destinationsModel
    main_window.showDestination("tcp")
    assert window_ui.stackedWidget_outputs.currentWidget() is tcp.page
    assert destination_status(main_window, "tcp").state == "off"

    # a preset sets the port, the template and the options, and is stored
    combo = ui.comboBox_tcpPreset
    combo.setCurrentIndex(combo.findData(LIVE_SCORE))
    combo.activated.emit(combo.currentIndex())
    assert ui.plainTextEdit_tcpTemplate.toPlainText() == (
        '{"type":"ocr", "values":{json}}'
    )
    assert ui.lineEdit_tcpPort.text() == ""  # set in Live Score
    assert "untested" in ui.label_tcpPresetNote.text()
    assert not ui.groupBox_tcpCaspar.isVisibleTo(tcp.page)
    assert fetch_data("scoresight.json", "tcp_output")["preset"] == LIVE_SCORE

    # a row per field, with the preset's names; an edited name is stored
    storage = main_window.detectionTargetsStorage
    storage.add_item(make_target("Home Score"))
    storage.add_item(make_target("Time"))
    table = ui.tableView_tcpMapping.model()
    assert [
        (table.item(row, 0).text(), table.item(row, 1).text())
        for row in range(table.rowCount())
    ] == [("Home Score", "ScoreHome"), ("Time", "GameClock")]
    table.item(1, 1).setText("Clock")
    assert fetch_data("scoresight.json", "tcp_mapping") == {"Time": "Clock"}

    # the switch starts it; without a port it says what's missing
    model.requestToggle(destination_index(main_window, "tcp"))
    assert ui.pushButton_tcpStart.isChecked() and tcp.output.running
    assert ui.pushButton_tcpStart.text() == "Stop sending"
    status = destination_status(main_window, "tcp")
    assert (status.state, status.detail) == ("warning", "Enter the host and port")

    receiver = LineReceiver()
    try:
        ui.lineEdit_tcpHost.setText("127.0.0.1")
        ui.lineEdit_tcpHost.editingFinished.emit()
        ui.lineEdit_tcpPort.setText(str(receiver.port))
        ui.lineEdit_tcpPort.editingFinished.emit()
        qtbot.waitUntil(lambda: destination_status(main_window, "tcp").state == "ok")
        assert destination_status(main_window, "tcp").detail == (
            f"Live Score: Connected to 127.0.0.1:{receiver.port}"
        )
        main_window.ocrResult(
            [make_result("Home Score", "21"), make_result("Time", "3:12")]
        )
        expected = b'{"type":"ocr", "values":{"ScoreHome": "21", "Clock": "3:12"}}\n'
        qtbot.waitUntil(lambda: receiver.received().endswith(expected))
        # the preview shows what the current values make
        tcp.updatePreview()
        assert '"Clock": "3:12"' in ui.plainTextEdit_tcpPreview.toPlainText()

        # a template edit applies after the typing stops, and is stored
        ui.plainTextEdit_tcpTemplate.setPlainText("SCORES {json}")
        qtbot.waitUntil(
            lambda: (
                fetch_data("scoresight.json", "tcp_output")["template"]
                == "SCORES {json}"
            )
        )
        qtbot.waitUntil(
            lambda: receiver.received().endswith(
                b'SCORES {"ScoreHome": "21", "Clock": "3:12"}\n'
            )
        )

        # CasparCG: its settings and buttons show
        combo.setCurrentIndex(combo.findData(CASPARCG))
        combo.activated.emit(combo.currentIndex())
        assert ui.groupBox_tcpCaspar.isVisibleTo(tcp.page)
        assert ui.pushButton_tcpPlay.isEnabled()
        assert ui.lineEdit_tcpPort.text() == "5250"
        # the names of a preset that needs safe ones
        assert table is not ui.tableView_tcpMapping.model()
        table = ui.tableView_tcpMapping.model()
        assert table.item(0, 1).text() == "HomeScore"
        assert table.item(1, 1).text() == "Clock"  # edited: kept
        ui.toolButton_tcpResetNames.click()
        assert ui.tableView_tcpMapping.model().item(1, 1).text() == "Time"
        assert fetch_data("scoresight.json", "tcp_mapping") == {}
    finally:
        receiver.close()

    # the switch stops it
    model.requestToggle(destination_index(main_window, "tcp"))
    assert not ui.pushButton_tcpStart.isChecked() and not tcp.output.running
    assert destination_status(main_window, "tcp").state == "off"
    assert not ui.pushButton_tcpPlay.isEnabled()


def test_the_tcp_output_over_a_websocket(main_window, make_target, make_result, qtbot):
    from tcp_output import CASPARCG, WEBSOCKET, WEBSOCKET_JSON
    from websocket_server import WebSocketServer

    tcp = main_window.tcpUiHandler
    ui = tcp.ui
    main_window.showDestination("tcp")
    main_window.detectionTargetsStorage.add_item(make_target("Home Score"))

    # the preset: a URL and headers instead of the host and port
    combo = ui.comboBox_tcpPreset
    combo.setCurrentIndex(combo.findData(WEBSOCKET_JSON))
    combo.activated.emit(combo.currentIndex())
    assert tcp.output.config.transport == WEBSOCKET
    assert ui.lineEdit_tcpUrl.isVisibleTo(tcp.page)
    assert ui.plainTextEdit_tcpHeaders.isVisibleTo(tcp.page)
    assert not ui.lineEdit_tcpHost.isVisibleTo(tcp.page)
    assert not ui.lineEdit_tcpPort.isVisibleTo(tcp.page)
    assert not ui.comboBox_tcpEncoding.isEnabled()  # always UTF-8
    assert ui.label_tcpAddress.text() == "URL"
    assert "WebSocket" in ui.label_tcpPresetNote.text()

    server = WebSocketServer()
    try:
        ui.lineEdit_tcpUrl.setText(server.url("/live"))
        ui.lineEdit_tcpUrl.editingFinished.emit()
        ui.plainTextEdit_tcpHeaders.setPlainText("Authorization: Bearer abc")
        qtbot.waitUntil(
            lambda: (
                fetch_data("scoresight.json", "tcp_output")["headers"]
                == "Authorization: Bearer abc"
            )
        )
        assert fetch_data("scoresight.json", "tcp_output")["url"] == server.url("/live")
        ui.pushButton_tcpStart.setChecked(True)
        qtbot.waitUntil(lambda: destination_status(main_window, "tcp").state == "ok")
        assert destination_status(main_window, "tcp").detail == (
            f"WebSocket (JSON): Connected to 127.0.0.1:{server.port}"
        )
        assert server.connections[0].headers["authorization"] == "Bearer abc"
        main_window.ocrResult([make_result("Home Score", "21")])
        server.wait_for(['{"Home Score": "21"}'])
        ui.pushButton_tcpStart.setChecked(False)
    finally:
        server.close()

    # a TCP preset: the host and port again
    combo.setCurrentIndex(combo.findData(CASPARCG))
    combo.activated.emit(combo.currentIndex())
    assert not ui.lineEdit_tcpUrl.isVisibleTo(tcp.page)
    assert not ui.plainTextEdit_tcpHeaders.isVisibleTo(tcp.page)
    assert ui.lineEdit_tcpHost.isVisibleTo(tcp.page)
    assert ui.comboBox_tcpEncoding.isEnabled()


def test_the_tcp_output_keeps_its_settings_across_a_language_change(main_window, qapp):
    from tcp_output import CHYRON

    tcp = main_window.tcpUiHandler
    ui = tcp.ui
    combo = ui.comboBox_tcpPreset
    combo.setCurrentIndex(combo.findData(CHYRON))
    combo.activated.emit(combo.currentIndex())
    ui.lineEdit_tcpPort.setText("2323")
    ui.lineEdit_tcpPort.editingFinished.emit()
    template = ui.plainTextEdit_tcpTemplate.toPlainText()
    main_window.changeLanguage("de_DE")
    try:
        tr = QCoreApplication.translate
        assert combo.currentData() == CHYRON
        assert ui.lineEdit_tcpPort.text() == "2323"
        assert ui.plainTextEdit_tcpTemplate.toPlainText() == template
        assert ui.comboBox_tcpEncoding.currentData() == "iso-8859-1"
        assert ui.pushButton_tcpStart.text() == tr("MainWindow", "Start sending")
        assert ui.label_tcpPreset.text() == tr("TcpOutputPage", "Preset")
        assert tcp.output.config.port == 2323
    finally:
        qapp.removeTranslator(main_window.translator)


def test_obs_connect_and_disconnect(make_window, monkeypatch, qtbot, make_target):
    import mainwindow

    clients = []

    def fake_open(info):
        clients.append(FakeObsClient())
        return clients[-1]

    monkeypatch.setattr(mainwindow, "open_obs_websocket", fake_open)
    store_data(
        "scoresight.json", "obs", {"ip": "localhost", "port": "4455", "password": "x"}
    )
    window = make_window()
    ui = window.ui
    window.detectionTargetsStorage.add_item(make_target("Home Score"))
    qtbot.waitUntil(lambda: window.obs_websocket_client is not None)
    status = destination_status(window, "obs")
    assert (status.state, status.enabled, status.detail) == (
        "ok",
        True,
        "Connected to localhost:4455",
    )
    assert switch_is_on(window, "obs")
    assert ui.pushButton_connectObs.text() == "Change connection..."
    assert "localhost:4455" in ui.pushButton_connectObs.toolTip()
    assert ui.pushButton_disconnectObs.isEnabled()

    ui.pushButton_disconnectObs.click()
    assert window.obs_websocket_client is None
    qtbot.waitUntil(lambda: clients[0].disconnected)  # closed off the GUI thread
    status = destination_status(window, "obs")
    assert (status.state, status.enabled) == ("off", False)
    assert ui.pushButton_connectObs.text() == "Connect OBS"
    assert not ui.pushButton_disconnectObs.isEnabled()
    assert not ui.pushButton_createOBSScene.isEnabled()
    # the saved connection stays (for the dialog), but isn't opened at startup
    assert fetch_data("scoresight.json", "obs")["ip"] == "localhost"
    assert fetch_data("scoresight.json", "obs_auto_connect") is False
    window.close()
    again = make_window()
    assert len(clients) == 1 and again.obs_websocket_client is None

    # the OBS switch opens the connect dialog; connecting turns auto-connect on
    again.destinationsModel.requestToggle(destination_index(again, "obs"))
    assert again.obs_connect_modal.isVisible()
    again.obs_modal_ui.pushButton_connect.click()
    qtbot.waitUntil(lambda: again.obs_websocket_client is not None)
    assert fetch_data("scoresight.json", "obs_auto_connect") is True
    # and the switch disconnects
    again.destinationsModel.requestToggle(destination_index(again, "obs"))
    assert again.obs_websocket_client is None
    qtbot.waitUntil(lambda: clients[-1].disconnected)


def test_a_failed_obs_connection_says_why(make_window, monkeypatch, qtbot):
    import obs_websocket

    def refuse(**kwargs):
        raise ConnectionRefusedError("[WinError 10061] the target machine refused it")

    monkeypatch.setattr(obs_websocket.obs, "ReqClient", refuse)
    store_data(
        "scoresight.json", "obs", {"ip": "127.0.0.1", "port": "4455", "password": "x"}
    )
    window = make_window()  # connects at startup, in the background
    qtbot.waitUntil(lambda: window.obsConnectError is not None)
    status = destination_status(window, "obs")
    assert (status.state, status.enabled) == ("error", False)
    assert status.detail == "Not connected: Can't reach 127.0.0.1:4455"
    assert "WebSocket server" in status.hint

    window.show()
    window.openOBSConnectModal()
    window.obs_modal_ui.pushButton_connect.click()
    qtbot.waitUntil(lambda: window.obs_modal_ui.pushButton_connect.isEnabled())
    label = window.obs_modal_ui.label_error
    assert label.text() == "Cannot connect to OBS\nCan't reach 127.0.0.1:4455"
    assert "WebSocket server" in label.toolTip()


def test_the_http_page_shows_the_address_for_other_computers(
    make_window, monkeypatch, qapp
):
    import mainwindow

    monkeypatch.setattr(mainwindow, "primary_lan_address", lambda: "192.168.1.20")
    window = make_window(http_port=18100)
    link = 'href="http://192.168.1.20:18100/scoresight"'
    assert link in window.ui.label_8.text()
    status = destination_status(window, "http")
    assert status.state == "ok"
    assert status.detail.startswith("http://192.168.1.20:18100 · ")
    window.changeLanguage("de_DE")
    try:
        assert window.ui.label_8.text().count(link) == 1
        assert "localhost:18100" in window.ui.label_8.text()
    finally:
        qapp.removeTranslator(window.translator)


def test_the_http_page_builds_overlay_urls(make_window, make_target, monkeypatch, qapp):
    import mainwindow

    monkeypatch.setattr(mainwindow, "primary_lan_address", lambda: "192.168.1.20")
    window = make_window(http_port=18100)
    for name in ("Home Score", "Away Score", "Time", "Period", "Shot Clock"):
        window.detectionTargetsStorage.add_item(make_target(name))
    ui = window.ui
    url = ui.lineEdit_overlayUrl
    assert url.text() == "http://192.168.1.20:18100/overlay/scorebug"
    assert ui.toolButton_overlayFields.text() == "Standard fields"
    assert [ui.comboBox_overlayHost.itemText(i) for i in range(2)] == [
        "192.168.1.20:18100",
        "localhost:18100",
    ]

    ui.comboBox_overlayTheme.setCurrentIndex(1)  # Light
    ui.doubleSpinBox_overlayScale.setValue(1.5)
    assert url.text() == (
        "http://192.168.1.20:18100/overlay/scorebug?theme=light&scale=1.5"
    )
    # the fields, from the fields menu (made when it opens): the standard ones
    # are ticked, and the fields are shown in the order they were ticked (the
    # scorebug's are positional)
    builder = window.overlayBuilder
    builder.fillFieldsMenu()
    actions = {a.text(): a for a in builder.fieldsMenu.actions() if a.text()}
    assert [name for name, a in actions.items() if a.isChecked()] == [
        "Standard fields",
        "Home Score",
        "Away Score",
        "Time",
        "Period",
    ]
    actions["Shot Clock"].trigger()
    actions["Period"].trigger()
    assert url.text() == (
        "http://192.168.1.20:18100/overlay/scorebug"
        "?fields=Home%20Score,Away%20Score,Time,Shot%20Clock&theme=light&scale=1.5"
    )
    # (elided to fit)
    assert ui.toolButton_overlayFields.text().startswith("Home Score, ")
    assert (
        "Home Score, Away Score, Time, Shot Clock"
        in ui.toolButton_overlayFields.toolTip()
    )
    assert not actions["Standard fields"].isChecked()
    actions["Period"].trigger()  # ticked again: last
    assert "fields=Home%20Score,Away%20Score,Time,Shot%20Clock,Period&" in url.text()
    actions["Standard fields"].trigger()
    assert "fields=" not in url.text()

    # the single field picks one field, and has its own theme (Minimal)
    ui.comboBox_overlayKind.setCurrentIndex(
        ui.comboBox_overlayKind.findText("Single field")
    )
    assert ui.comboBox_overlayTheme.currentIndex() == 2  # Minimal
    builder.fillFieldsMenu()
    [shot_clock] = [a for a in builder.fieldsMenu.actions() if a.text() == "Shot Clock"]
    shot_clock.trigger()
    assert url.text() == (
        "http://192.168.1.20:18100/overlay/field?name=Shot%20Clock&scale=1.5"
    )
    # the scorebug kept its theme
    ui.comboBox_overlayKind.setCurrentIndex(0)
    assert ui.comboBox_overlayTheme.currentIndex() == 1  # Light
    ui.comboBox_overlayKind.setCurrentIndex(
        ui.comboBox_overlayKind.findText("Single field")
    )
    # for software on this computer
    ui.comboBox_overlayHost.setCurrentIndex(1)
    assert url.text().startswith("http://localhost:18100/overlay/field?")
    ui.pushButton_copyOverlayUrl.click()
    assert QApplication.clipboard().text() == url.text()

    # the choices are kept
    again = make_window(http_port=18100)
    assert again.ui.lineEdit_overlayUrl.text() == url.text()


def test_the_overlay_builder_names_the_teams(make_window, monkeypatch):
    import mainwindow

    monkeypatch.setattr(mainwindow, "primary_lan_address", lambda: None)
    window = make_window(http_port=18100)
    ui = window.ui
    url = ui.lineEdit_overlayUrl
    home, away = ui.lineEdit_overlayHomeName, ui.lineEdit_overlayAwayName
    # the placeholders show the overlay's own names
    assert (home.placeholderText(), away.placeholderText()) == ("HOME", "AWAY")

    home.setText("Lions")
    assert url.text() == "http://localhost:18100/overlay/scorebug?labels=Lions"
    away.setText("Tigers")
    assert url.text().endswith("/overlay/scorebug?labels=Lions,Tigers")
    home.clear()
    assert url.text().endswith("/overlay/scorebug?labels=,Tigers")
    home.setText("Smith, Jones")  # a comma: one parameter per name
    assert url.text().endswith("?label=Smith,%20Jones&label=Tigers")
    home.setText("Lions")

    # the lower third: its first two captions
    ui.comboBox_overlayKind.setCurrentIndex(
        ui.comboBox_overlayKind.findText("Lower third")
    )
    assert home.isEnabled()
    assert (home.placeholderText(), away.placeholderText()) == ("Home", "Away")
    assert url.text().endswith("/overlay/lower-third?labels=Lions,Tigers")
    # the clock and the single field have no teams
    ui.comboBox_overlayKind.setCurrentIndex(ui.comboBox_overlayKind.findText("Clock"))
    assert not home.isEnabled()
    assert not ui.label_overlayTeams.isEnabled()
    assert url.text() == "http://localhost:18100/overlay/clock"

    # the names are kept
    again = make_window(http_port=18100)
    assert again.ui.lineEdit_overlayHomeName.text() == "Lions"
    assert again.ui.lineEdit_overlayAwayName.text() == "Tigers"
    again.ui.comboBox_overlayKind.setCurrentIndex(0)
    assert again.ui.lineEdit_overlayUrl.text().endswith("?labels=Lions,Tigers")


def test_the_http_page_lists_the_custom_overlays(make_window, data_dir, monkeypatch):
    import mainwindow

    monkeypatch.setattr(mainwindow, "primary_lan_address", lambda: None)
    window = make_window(http_port=18100)
    ui = window.ui
    combo = ui.comboBox_overlayKind
    # the overlays folder is made with the example
    assert (data_dir / "overlays" / "example.html").is_file()
    assert combo.findText("example.html") > 0

    (data_dir / "overlays" / "My Board.html").write_text("<p>", encoding="utf-8")
    # the list is read again when it is opened (clicked)
    window.overlayBuilder.eventFilter(
        combo, QtCore.QEvent(QtCore.QEvent.Type.MouseButtonPress)
    )
    combo.setCurrentIndex(combo.findText("My Board.html"))
    assert ui.lineEdit_overlayUrl.text() == (
        "http://localhost:18100/overlay/custom/My%20Board.html"
    )
    # a custom overlay has its own look
    assert not ui.comboBox_overlayTheme.isEnabled()
    assert not ui.toolButton_overlayFields.isEnabled()


def test_the_overlay_builder_without_the_server(make_window, patched):
    patched["http_port_busy"] = True
    window = make_window()
    ui = window.ui
    assert ui.lineEdit_overlayUrl.text() == ""
    assert ui.lineEdit_overlayUrl.placeholderText() == "The HTTP server is not running"
    assert not ui.pushButton_copyOverlayUrl.isEnabled()
    assert not ui.pushButton_openOverlayUrl.isEnabled()


def test_a_language_change_keeps_the_overlay_choices(make_window, qapp, monkeypatch):
    import mainwindow

    monkeypatch.setattr(mainwindow, "primary_lan_address", lambda: None)
    window = make_window(http_port=18100)
    ui = window.ui
    ui.comboBox_overlayKind.setCurrentIndex(2)  # Clock
    ui.comboBox_overlayTheme.setCurrentIndex(2)  # Minimal
    before = ui.lineEdit_overlayUrl.text()
    assert before == "http://localhost:18100/overlay/clock?theme=minimal"
    window.changeLanguage("de_DE")
    try:
        assert ui.comboBox_overlayKind.currentIndex() == 2
        assert ui.lineEdit_overlayUrl.text() == before
    finally:
        qapp.removeTranslator(window.translator)


@pytest.fixture
def reference_font(qapp):
    """Segoe UI 9 pt (the Windows UI font) where it's installed; the offscreen
    platform doesn't find the system fonts by itself."""
    import os
    import sys

    from PySide6.QtGui import QFont, QFontDatabase

    previous = qapp.font()
    path = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "segoeui.ttf")
    loaded = sys.platform == "win32" and QFontDatabase.addApplicationFont(path) >= 0
    if loaded:
        qapp.setFont(QFont("Segoe UI", 9))
    yield loaded
    qapp.setFont(previous)


# the reference text for scaling the size limit with another font
SIZE_REFERENCE_TEXT = "Detections / s Update on change Binary View 4-corner Correction"


def test_the_window_fits_a_small_screen(make_window, qapp, qtbot, reference_font):
    # The window needed 1016x750 (1158 wide in German): more than a 1366x768
    # laptop shows. Three panes now share the width (the fields, the picture
    # and the inspector), the side panes scroll inside. The limit is for
    # Segoe UI 9 pt; a wider font (Linux, the offscreen fallback font) widens it
    # in proportion.
    from PySide6.QtGui import QFontMetricsF

    window = make_window()
    width_ratio = 1.0
    if not reference_font:
        # Segoe UI 9 pt draws the reference text 342 px wide
        width_ratio = max(
            1.0, QFontMetricsF(qapp.font()).horizontalAdvance(SIZE_REFERENCE_TEXT) / 342
        )
    ui = window.ui
    window.show()
    for language in ("en_US", "de_DE"):
        window.changeLanguage(language)
        qapp.processEvents()
        hint = window.minimumSizeHint()
        assert hint.width() <= 1024 * width_ratio, (language, hint)
        assert hint.height() <= 640, (language, hint)
        # On a 1366x768 laptop the side panes get their widths (enough for
        # their content), and the picture the rest
        window.resize(1366, 768)
        ui.splitter_main.setSizes(window.defaultPaneSizes(1366))
        qapp.processEvents()
        fields, viewer, inspector = ui.splitter_main.sizes()
        assert fields >= max(220, ui.widget_leftPane.minimumSizeHint().width())
        assert inspector >= max(300, ui.tabWidget_inspector.minimumSizeHint().width())
        assert viewer >= 360, (language, ui.splitter_main.sizes())
    qapp.removeTranslator(window.translator)


def cut_off_texts(root: QWidget) -> list[tuple]:
    """The labels and buttons under root (visible) whose text doesn't fit:
    narrower than their text, or reaching past root's right edge."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (
        QAbstractButton,
        QCheckBox,
        QLabel,
        QRadioButton,
        QToolButton,
    )

    found = []
    for widget in root.findChildren(QWidget):
        if not widget.isVisibleTo(root) or not widget.width():
            continue
        if isinstance(widget, QLabel) and widget.wordWrap():
            continue
        if not isinstance(widget, (QLabel, QAbstractButton)) or not widget.text():
            continue
        if isinstance(widget, (QLabel, QCheckBox, QRadioButton)):
            needed = widget.sizeHint().width() - 1
        elif (
            isinstance(widget, QToolButton)
            and widget.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonIconOnly
        ):
            needed = widget.iconSize().width()
        else:
            # a push or tool button's size hint has room to spare: its text
            # (and icon) must fit
            needed = widget.fontMetrics().horizontalAdvance(
                widget.text().replace("&", "")
            )
            if not widget.icon().isNull():
                needed += widget.iconSize().width()
        right = widget.mapTo(root, widget.rect().topRight()).x()
        if widget.width() < needed or right > root.width():
            found.append((widget.objectName(), widget.text(), widget.width()))
    return found


TRANSLATIONS = sorted(
    path.stem.removeprefix("scoresight_")
    for path in (Path(__file__).parent.parent / "translations").glob("*.qm")
)


@pytest.mark.parametrize("language", TRANSLATIONS)
def test_every_language_fits(language, make_window, make_target, qapp, reference_font):
    # Translations are longer than English (Russian by a third): every text of
    # the side panes and the status bar must still show whole at 1366x768
    # (wider with a wider font), and the window must fit a small screen.
    from PySide6.QtGui import QFontMetricsF

    width_ratio = 1.0
    if not reference_font:
        width_ratio = max(
            1.0, QFontMetricsF(qapp.font()).horizontalAdvance(SIZE_REFERENCE_TEXT) / 342
        )
    window = make_window()
    ui = window.ui
    window.resize(int(1366 * width_ratio), 768)
    window.show()
    window.detectionTargetsStorage.add_item(make_target("Home Score"))
    window.changeLanguage(language)
    try:
        ui.splitter_main.setSizes(window.defaultPaneSizes(window.width()))
        window.itemSelected("Home Score")
        # a sport: its row and the game's status line under All boxes
        ui.comboBox_sport.setCurrentIndex(ui.comboBox_sport.findData("basketball"))
        assert not ui.label_gameStatus.isHidden()
        ui.toolButton_imageCleanup.setChecked(True)
        # the crop panel (with Drag to crop) and the crop picking's banner
        ui.toolButton_topCrop.setChecked(True)
        window.cropMode()
        ui.frame_cropBanner.show()
        qapp.processEvents()
        qapp.processEvents()
        hint = window.minimumSizeHint()
        assert hint.width() <= 1024 * width_ratio, hint
        assert hint.height() <= 640, hint
        # the Box tab's settings scroll only vertically: they get their width
        content = ui.scrollAreaWidgetContents_boxSettings
        viewport = ui.scrollArea_boxSettings.viewport()
        assert content.minimumSizeHint().width() <= viewport.width()
        for pane in (
            viewport,
            ui.groupBox_allBoxes,
            ui.widget_leftPane,
            ui.frame_source_view,
        ):
            assert cut_off_texts(pane) == [], pane.objectName()
        assert cut_off_texts(window.statusBar()) == []
        ui.tabWidget_inspector.setCurrentWidget(ui.widget_outputs)
        for destination in ("files", "http", "obs", "vmix", "uno", "api", "tcp"):
            window.showDestination(destination)
            qapp.processEvents()
            assert cut_off_texts(ui.widget_outputs) == [], destination
        # the TCP page with every control: the CasparCG preset, started
        from tcp_output import CASPARCG

        tcp = window.tcpUiHandler
        combo = tcp.ui.comboBox_tcpPreset
        combo.setCurrentIndex(combo.findData(CASPARCG))
        combo.activated.emit(combo.currentIndex())
        tcp.ui.pushButton_tcpStart.setChecked(True)
        qapp.processEvents()
        assert tcp.ui.groupBox_tcpCaspar.isVisibleTo(ui.widget_outputs)
        assert cut_off_texts(ui.widget_outputs) == [], "tcp (CasparCG)"
        tcp.ui.pushButton_tcpStart.setChecked(False)
        # as a TCP server (stopped: no port is opened): its own address row
        # label and the note where programs connect
        tcp.ui.comboBox_tcpTransport.setCurrentIndex(2)
        qapp.processEvents()
        assert not tcp.ui.lineEdit_tcpHost.isVisibleTo(ui.widget_outputs)
        assert cut_off_texts(ui.widget_outputs) == [], "tcp (server)"
    finally:
        qapp.removeTranslator(window.translator)


@pytest.mark.parametrize("language", TRANSLATIONS)
def test_every_language_fits_the_live_layout(
    language, make_window, make_target, make_result, qapp, reference_font
):
    # The Live layout's field list (large readings, a held value's HELD chip
    # and the outputs' lines) must show whole at 1366x768 in every language
    from PySide6.QtGui import QFontMetrics, QFontMetricsF
    from PySide6.QtWidgets import QStyleOptionViewItem

    width_ratio = 1.0
    if not reference_font:
        width_ratio = max(
            1.0, QFontMetricsF(qapp.font()).horizontalAdvance(SIZE_REFERENCE_TEXT) / 342
        )
    window = make_window()
    ui = window.ui
    window.resize(int(1366 * width_ratio), 768)
    window.show()
    storage = window.detectionTargetsStorage
    for name in ("Home Score", "Away Score", "Time", "Period"):
        storage.add_item(make_target(name))
    window.changeLanguage(language)
    try:
        window.setLayoutMode("live")
        window.ocrResult(
            [
                make_result("Home Score", "21"),
                make_result("Away Score", "17"),
                make_result("Time", "03:59"),
                make_result("Period", "Z", "FailedFilter"),
            ]
        )
        window.heldValues.hold("Period", "2nd")
        window.updateHeldUi()
        qapp.processEvents()
        qapp.processEvents()
        assert window.minimumSizeHint().height() <= 640
        assert cut_off_texts(ui.widget_leftPane) == []
        # the held value, its chip and its Release button fit the row
        table = ui.tableWidget_boxes
        delegate = window.readingDelegate
        item = box_value_item(window, "Period")
        option = QStyleOptionViewItem()
        option.rect = table.visualItemRect(item)
        option.font = table.font()
        from readings_view import reading_at

        reading = reading_at(table.indexFromItem(item))
        assert delegate.releaseShown(option.rect, option.font, reading)
        value_width = QFontMetrics(delegate.valueFont(table.font())).horizontalAdvance(
            "03:59"
        )
        assert value_width + delegate.discSize(table.font()) < table.columnWidth(1)
        # the OBS page's text sources table and scene controls
        window.showDestination("obs")
        qapp.processEvents()
        assert cut_off_texts(ui.widget_outputs) == []
    finally:
        qapp.removeTranslator(window.translator)


def test_the_panes_widths_and_hidden_panes_are_kept(make_window, qtbot):
    from PySide6.QtTest import QTest

    def settled(window):
        # wide enough for any font, laid out
        window.resize(max(2000, window.minimumSizeHint().width() + 400), 800)
        with qtbot.waitExposed(window):
            window.show()
        return window.ui.splitter_main

    # the two-pane layout before the inspector is forgotten
    store_data("scoresight.json", "main_splitter_state", "AAAA/wAAAAEAAAAC")
    window = make_window()
    assert fetch_data("scoresight.json", "main_splitter_state") is None
    splitter = settled(window)
    fields, viewer, inspector = splitter.sizes()
    assert fields > 0 and inspector > 0
    left = window.ui.widget_leftPane.minimumSizeHint().width() + 60
    splitter.setSizes([left, fields + viewer - left, inspector])
    assert splitter.sizes()[0] == left
    # a double-click on the divider hides the inspector, another one shows it
    # again at its width
    QTest.mouseDClick(splitter.handle(2), QtCore.Qt.MouseButton.LeftButton)
    assert window.isPaneHidden(2)
    QTest.mouseDClick(splitter.handle(2), QtCore.Qt.MouseButton.LeftButton)
    assert splitter.sizes()[2] == inspector
    QTest.mouseDClick(splitter.handle(2), QtCore.Qt.MouseButton.LeftButton)
    window.close()
    stored = fetch_data("scoresight.json", "main_splitter_sizes")
    assert stored[0] == left and stored[2] == 0

    # hidden at the next start too
    restored = settled(make_window())
    qtbot.waitUntil(lambda: restored.sizes()[0] == left)
    assert restored.sizes()[2] == 0
    QTest.mouseDClick(restored.handle(2), QtCore.Qt.MouseButton.LeftButton)
    assert restored.sizes()[2] > 0


def test_slider_readouts(main_window, make_target):
    ui = main_window.ui
    storage = main_window.detectionTargetsStorage
    storage.add_item(make_target("Home Score", conf_thresh=0, skew=-3, vscale=8))
    main_window.itemSelected("Home Score")
    assert ui.label_confThreshValue.text() == "Off"
    assert ui.label_skewValue.text() == "\u22123"
    assert ui.label_vscaleValue.text() == "80 %"
    assert ui.label_dilateValue.text() == "1"
    assert ui.label_cleanupValue.text() == "Off"
    ui.horizontalSlider_conf_thresh.setValue(45)
    assert ui.label_confThreshValue.text() == "45 %"
    assert ui.horizontalSlider_conf_thresh.accessibleDescription() == "45 %"
    ui.horizontalSlider_detectionCadence.setValue(12)
    assert ui.label_detectionCadenceValue.text() == "12 /s"
    ui.horizontalSlider_aggsPerSecond.setValue(3)
    assert ui.label_aggsPerSecondValue.text() == "3 /s"


def test_controls_have_tooltips(main_window):
    # the controls the design critique found without one
    for name in (
        "checkBox_smoothing",
        "horizontalSlider_vscale",
        "horizontalSlider_skew",
        "horizontalSlider_dilate",
        "horizontalSlider_cleanup",
        "checkBox_compositeBox",
        "comboBox_binarizationMethod",
        "checkBox_autocrop",
        "checkBox_skip_similar_image",
        "pushButton_stopUpdates",
        "horizontalSlider_detectionCadence",
        "comboBox_ocrModel",
        "toolButton_videoSettings",
        "pushButton_refresh_sources",
        "toolButton_speed",
        "toolButton_osd",
        "toolButton_zoomReset",
        "label_zoom",
        "pushButton_fourCorner",
        "toolButton_topCrop",
        "toolButton_addBox",
        "toolButton_removeBox",
    ):
        assert getattr(main_window.ui, name).toolTip(), name


def test_output_buttons_have_text_and_no_emoji(main_window):
    for button in (
        main_window.ui.pushButton_startvmix,
        main_window.ui.toolButton_toggleUno,
    ):
        text = button.text()
        assert text in ("Start vMix", "Start sending")
        assert not button.icon().isNull()
        assert not any(ord(c) > 0x2000 for c in text)


def test_resend_unchanged_values(main_window):
    # "Send Same?" said nothing about what it does; the setting is the same
    for checkbox, setting in (
        (main_window.ui.checkBox_vmix_send_same, "vmix_send_same"),
        (main_window.ui.checkBox_uno_send_same, "uno_send_same"),
    ):
        assert checkbox.text() == "Also resend unchanged values"
        assert "Send Same?" in checkbox.toolTip()
        assert "hasn't changed" in checkbox.toolTip()
        checkbox.setChecked(True)
        # (UNO stores the check state, 2)
        assert fetch_data("scoresight.json", setting)
    assert main_window.vmixUiHandler.vmixUpdater.update_same is True
    assert main_window.unoUiHandler.unoUpdater.update_same


def test_keyboard_shortcut_rows(qapp):
    from PySide6.QtGui import QAction

    from keyboard_shortcuts import action_name, action_rows

    native = QKeySequence.SequenceFormat.NativeText
    action = QAction("&Import field layout...")
    assert action_name(action) == "Import field layout"
    assert action_name(QAction("Black && white…")) == "Black & white"
    action.setShortcuts([QKeySequence("Ctrl+O"), QKeySequence("F3")])
    plain = QAction("No key")
    assert action_rows([action, plain]) == [
        (
            "Import field layout",
            f"{QKeySequence('Ctrl+O').toString(native)}, {QKeySequence('F3').toString(native)}",
        )
    ]


def test_the_obs_dialog(main_window, qapp):
    from PySide6.QtWidgets import QLineEdit

    store_data(
        "scoresight.json", "obs", {"ip": "localhost", "port": "4455", "password": "x"}
    )
    main_window.show()
    main_window.openOBSConnectModal()
    dialog = main_window.obs_connect_modal
    ui = main_window.obs_modal_ui
    # a child of the main window: it stays in front of it
    assert dialog.parent() is main_window
    assert ui.lineEdit_password.echoMode() == QLineEdit.EchoMode.Password
    ui.checkBox_showPassword.setChecked(True)
    assert ui.lineEdit_password.echoMode() == QLineEdit.EchoMode.Normal
    assert not main_window.ui.pushButton_createOBSScene.isEnabled()

    # connected meanwhile, then Cancel: the scene controls work again
    main_window.obs_websocket_client = FakeObsClient()
    ui.pushButton_cancel.click()
    assert not dialog.isVisible()
    assert main_window.ui.pushButton_createOBSScene.isEnabled()
    main_window.obs_websocket_client = None

    # opening it again while it's open doesn't make a second one
    main_window.openOBSConnectModal()
    second = main_window.obs_connect_modal
    main_window.openOBSConnectModal()
    assert main_window.obs_connect_modal is second


def test_cancel_while_connecting_to_obs(main_window, monkeypatch, qtbot):
    # Cancel didn't stop the connection attempt: when it succeeded later, it
    # replaced the current connection and stored the cancelled settings
    import mainwindow

    release = threading.Event()
    finished = threading.Event()
    client = FakeObsClient()

    def slow_open(info):
        release.wait(5)
        finished.set()
        return client

    monkeypatch.setattr(mainwindow, "open_obs_websocket", slow_open)
    main_window.show()
    main_window.openOBSConnectModal()
    ui = main_window.obs_modal_ui
    ui.lineEdit_ip.setText("other-pc")
    ui.pushButton_connect.click()
    assert not ui.pushButton_connect.isEnabled()  # connecting
    ui.pushButton_cancel.click()
    release.set()
    assert finished.wait(5)
    # the (ignored) client is closed off the GUI thread
    qtbot.waitUntil(lambda: client.disconnected)
    assert main_window.obs_websocket_client is None
    assert fetch_data("scoresight.json", "obs") is None


def menu_items(menu):
    """The objectNames of a menu's items (a submenu's for a submenu)."""
    names = []
    for action in menu.actions():
        if action.isSeparator():
            continue
        names.append(
            action.menu().objectName() if action.menu() else action.objectName()
        )
    return names


def test_the_menus(main_window):
    # File, View, Tools and Help, every item where the redesign put it
    from PySide6.QtGui import QAction

    ui = main_window.ui
    assert menu_items(ui.menuFile) == [
        "actionImportConfiguration",
        "actionExportConfiguration",
        "actionOpenConfigurationFolder",
        "actionAskBeforeClosing",
        "actionQuit",
    ]
    assert menu_items(ui.menuView) == [
        "actionSetupLayout",
        "actionLiveLayout",
        "actionBinaryView",
        "actionFitPicture",
        "actionZoomIn",
        "actionZoomOut",
        "actionStatsOverlay",
        "actionShowUnusedFields",
        "menuAppearance",
        "menuLanguage",
    ]
    assert menu_items(ui.menuTools) == [
        "actionPauseOutputs",
        "actionReloadSources",
        "actionCollectTrainingData",
        "actionOCRTrainingDataSetup",
        "actionViewLog",
    ]
    assert menu_items(ui.menuHelp) == [
        "actionUserGuide",
        "actionKeyboardShortcuts",
        "actionCommunity",
        "actionCheckForUpdates",
        "actionAbout",
    ]
    # on macOS, About and Quit go to the application menu; "Setup layout"
    # must not be taken for the preferences
    assert ui.actionAbout.menuRole() == QAction.MenuRole.AboutRole
    assert ui.actionQuit.menuRole() == QAction.MenuRole.QuitRole
    for action in (
        ui.actionAskBeforeClosing,
        ui.actionSetupLayout,
        ui.actionLiveLayout,
        ui.actionShowUnusedFields,
        ui.actionUserGuide,
        ui.actionKeyboardShortcuts,
        ui.actionCommunity,
        ui.actionOpenConfigurationFolder,
        ui.actionCheckForUpdates,
    ):
        assert action.menuRole() == QAction.MenuRole.NoRole, action.objectName()


def test_the_help_menu(main_window, monkeypatch, qapp):
    import mainwindow

    opened = []
    monkeypatch.setattr(
        mainwindow.QDesktopServices, "openUrl", lambda url: opened.append(url)
    )
    ui = main_window.ui
    ui.actionUserGuide.trigger()  # F1
    assert [url.toString() for url in opened] == [
        "https://royshil.github.io/scoresight/"
    ]

    # the community: Help > Ask a question or share feedback, and the status
    # bar's Feedback, which is always there
    community = "https://github.com/royshil/scoresight/discussions"
    opened.clear()
    ui.actionCommunity.trigger()
    feedback = main_window.statusBarWidgets.button_feedback
    assert not feedback.isHidden()
    assert feedback.text() == "Feedback"
    feedback.click()
    assert [url.toString() for url in opened] == [community, community]

    main_window.show()
    ui.actionKeyboardShortcuts.trigger()
    dialog = main_window.keyboardShortcutsDialog
    try:
        assert dialog.isVisible()
        rows = {(name, keys) for _, name, keys in dialog.rows()}
        native = QKeySequence.SequenceFormat.NativeText
        for name, key in (
            ("Pause outputs", "Ctrl+Shift+P"),
            ("Live layout", "Ctrl+2"),
            ("Rename", "F2"),
            ("Copy value", "Ctrl+C"),
            ("Binary View", "Ctrl+B"),
        ):
            assert (name, QKeySequence(key).toString(native)) in rows, name
        assert any("Arrow keys" in keys for _, keys in rows)
    finally:
        dialog.close()


def test_quit_closes_the_window(main_window, qapp):
    main_window.show()
    main_window.ui.actionQuit.trigger()
    assert not main_window.isVisible()
    assert main_window.closing


def test_the_menus_are_translatable(main_window, qapp):
    # The File menu was made in code without tr(): never translated
    from PySide6.QtCore import QTranslator

    class Marking(QTranslator):
        def translate(self, context, source, disambiguation=None, n=-1):
            return f"«{source}»" if context == "MainWindow" else ""

    translator = Marking()
    qapp.installTranslator(translator)
    try:
        main_window.ui.retranslateUi(main_window)
        main_window.applyRuntimeTexts()
        assert main_window.ui.menuFile.title() == "«File»"
        assert main_window.ui.menuHelp.title() == "«Help»"
        assert "«Check for updates...»" in menu_titles(main_window, "menuHelp")
        assert "«Appearance»" in menu_titles(main_window, "menuView")
        assert "«Live layout»" in menu_titles(main_window, "menuView")
        appearance = [a.text() for a in main_window.appearance_actions.actions()]
        assert appearance == ["«System»", "«Light»", "«Dark»"]
    finally:
        qapp.removeTranslator(translator)
        main_window.ui.retranslateUi(main_window)
    # the languages in their own language, not translated
    languages = [a.text() for a in main_window.language_actions.actions()]
    assert "Deutsch" in languages and "日本語" in languages and "Français" in languages
    assert len(languages) == 13


def test_replaced_viewers_are_deleted(make_window, qapp):
    # A replaced viewer was removed from the layout and closed, but stayed a
    # child widget of the main window for the rest of the session.
    from PySide6.QtCore import QCoreApplication, QEvent
    from shiboken6 import isValid

    store_data("scoresight.json", "source_selected", "rtsp://10.0.1.200:554/11")
    window = make_window()
    first = window.image_viewer
    assert first is not None
    window.sourceSelectionSucessful()  # open the source again
    second = window.image_viewer
    assert second is not first
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not isValid(first)
    assert isValid(second)
    window.reset_playing_source()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not isValid(second)
    assert window.image_viewer is None


# --- sources (#10) -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "stored",
    [
        {"type": "URL", "value": "rtsp://10.0.1.200:554/11"},
        "rtsp://10.0.1.200:554/11",  # 0.1.x stored the bare URL
    ],
)
def test_url_source_is_restored(make_window, stored):
    store_data("scoresight.json", "source_selected", stored)
    window = make_window()
    assert window.ui.comboBox_camera_source.currentIndex() == 2
    camera_info = window.image_viewer.camera_info
    assert (camera_info.type, camera_info.id) == ("URL", "rtsp://10.0.1.200:554/11")
    assert fetch_data("scoresight.json", "source_selected") == {
        "type": "URL",
        "value": "rtsp://10.0.1.200:554/11",
    }


def test_sources_found_after_closing_do_not_reopen_the_source(make_window):
    store_data("scoresight.json", "source_selected", "rtsp://10.0.1.200:554/11")
    window = make_window()
    assert window.image_viewer is not None
    window.close()
    assert window.image_viewer is None
    window.update_sources.emit([])  # a late source discovery result
    assert window.image_viewer is None


def test_file_source_is_restored(make_window, tmp_path):
    video = tmp_path / "game.mp4"
    video.write_bytes(b"")
    store_data("scoresight.json", "source_selected", str(video))
    window = make_window()
    assert window.ui.comboBox_camera_source.currentIndex() == 1
    assert window.image_viewer.camera_info.type == "File"
    assert window.image_viewer.camera_info.id == str(video)


def test_missing_file_source_is_not_restored(make_window, tmp_path):
    store_data(
        "scoresight.json",
        "source_selected",
        {"type": "File", "value": str(tmp_path / "gone.mp4")},
    )
    window = make_window()
    assert window.ui.comboBox_camera_source.currentIndex() == 0
    assert window.image_viewer is None


def test_camera_source_is_stored_and_restored(make_window, patched):
    patched["cameras"].extend(
        [
            CameraInfo("Capture Card", "0", 0, CameraInfo.CameraType.OPENCV),
            CameraInfo(
                "NDI Scoreboard", "NDI Scoreboard", 0, CameraInfo.CameraType.NDI
            ),
        ]
    )
    window = make_window()
    combo = window.ui.comboBox_camera_source
    combo.setCurrentIndex(combo.count() - 1)  # the user picks the NDI source
    assert fetch_data("scoresight.json", "source_selected") == {
        "type": "NDI",
        "value": "NDI Scoreboard",
        "description": "NDI Scoreboard",
    }
    window.close()

    restored = make_window()
    assert restored.ui.comboBox_camera_source.currentText() == "NDI Scoreboard"
    assert restored.image_viewer.camera_info.type == "NDI"


def test_phone_camera_source_is_stored_and_restored(make_window, patched):
    patched["cameras"].append(
        CameraInfo("Capture Card", "0", 0, CameraInfo.CameraType.OPENCV)
    )
    window = make_window()
    combo = window.ui.comboBox_camera_source
    # the phone camera comes before the cameras found
    assert combo.itemText(4) == "Phone camera"
    assert combo.itemText(5) == "Capture Card"
    combo.setCurrentIndex(4)
    camera_info = window.image_viewer.camera_info
    assert (camera_info.type, camera_info.description) == ("Phone", "Phone camera")
    assert fetch_data("scoresight.json", "source_selected") == {
        "type": "Phone",
        "value": "phone",
    }
    window.close()

    restored = make_window()
    assert restored.ui.comboBox_camera_source.currentIndex() == 4
    assert restored.image_viewer.camera_info.type == "Phone"


@pytest.fixture
def no_dialogs(monkeypatch):
    """Record (instead of showing) the modal dialogs the main window opens."""
    from PySide6.QtWidgets import QDialog

    shown = []
    monkeypatch.setattr(
        QDialog, "exec", lambda self: shown.append(self.windowTitle()) or 0
    )
    return shown


@pytest.mark.parametrize("cameras", [1, 2])
def test_refreshing_the_sources_keeps_the_selected_camera(
    make_window, patched, qtbot, no_dialogs, cameras
):
    # Removing the current camera's item during a refresh ran sourceChanged: it
    # opened the Screen Capture dialog, and with two cameras switched to (and
    # stored) the other one.
    patched["cameras"].extend(
        CameraInfo(f"Cam {n}", f"uuid-{n}", n, CameraInfo.CameraType.OPENCV)
        for n in range(cameras)
    )
    window = make_window()
    combo = window.ui.comboBox_camera_source
    combo.setCurrentIndex(combo.findText("Cam 0"))
    stored = fetch_data("scoresight.json", "source_selected")
    assert stored["value"] == "uuid-0"

    window.getSources()  # the refresh button
    qtbot.waitUntil(lambda: not window.sources_discovery_running)
    assert no_dialogs == []
    assert combo.currentText() == "Cam 0"
    assert window.image_viewer.camera_info.uuid == "uuid-0"
    assert fetch_data("scoresight.json", "source_selected") == stored

    # the camera was unplugged: no source, and still no dialog
    patched["cameras"].pop(0)
    window.getSources()
    qtbot.waitUntil(lambda: not window.sources_discovery_running)
    assert no_dialogs == []
    assert combo.currentIndex() == 0
    assert window.image_viewer is None
    assert fetch_data("scoresight.json", "source_selected") == stored


def test_cancelling_the_file_dialog_in_a_translated_ui(
    make_window, monkeypatch, no_dialogs
):
    # The cancel selected "Select a source" by its English text, which a
    # translated combo box doesn't have: it stayed on "Open a Video File" with
    # the boxes table and view tools disabled.
    import mainwindow

    store_data("scoresight.json", "source_selected", "rtsp://10.0.1.200:554/11")
    window = make_window()
    assert window.image_viewer is not None
    combo = window.ui.comboBox_camera_source
    combo.setItemText(0, "Wählen Sie eine Quelle")
    monkeypatch.setattr(
        mainwindow.QFileDialog, "getOpenFileName", lambda *args, **kwargs: ("", "")
    )
    combo.setCurrentIndex(1)  # "Open a Video File", then Cancel
    assert combo.currentIndex() == 0
    assert window.image_viewer is None  # as in English


# --- menus, appearance (#50), dialogs ---------------------------------------------------------


def menu_titles(window, menu="menuFile"):
    """The texts of a menu's items (the File menu's by default)."""
    return [action.text() for action in getattr(window.ui, menu).actions()]


def test_menubar_stays_visible_after_the_window_is_deactivated(main_window, qapp):
    # The docs team reported that the File menu disappears when the window loses
    # focus. QWidget never forwards WindowDeactivate to changeEvent (only
    # ActivationChange), so the old hide-on-deactivate branch never ran; it was
    # removed. This pins the behavior.
    main_window.show()
    qapp.processEvents()
    for event_type in (QEvent.Type.WindowDeactivate, QEvent.Type.ActivationChange):
        QApplication.sendEvent(main_window, QEvent(event_type))
    qapp.processEvents()
    assert main_window.menuBar().isVisible()
    assert "Appearance" in menu_titles(main_window, "menuView")
    assert "Theme" not in menu_titles(main_window, "menuView")


class FakeStyleHints:
    def __init__(self):
        self.calls = []

    def setColorScheme(self, scheme):
        self.calls.append(scheme)

    def unsetColorScheme(self):
        self.calls.append("unset")


@pytest.fixture
def style_hints(monkeypatch):
    import mainwindow

    hints = FakeStyleHints()

    class FakeGuiApplication:
        @staticmethod
        def styleHints():
            return hints

    monkeypatch.setattr(mainwindow, "QGuiApplication", FakeGuiApplication)
    return hints


def test_apply_color_scheme(style_hints):
    from PySide6.QtCore import Qt

    from mainwindow import apply_color_scheme

    assert apply_color_scheme("Dark") == "Dark"
    assert apply_color_scheme("Light") == "Light"
    assert apply_color_scheme("System") == "System"
    assert apply_color_scheme(None) == "System"
    assert apply_color_scheme("Solarized") == "System"
    assert style_hints.calls == [
        Qt.ColorScheme.Dark,
        Qt.ColorScheme.Light,
        "unset",
        "unset",
        "unset",
    ]


def test_appearance_menu_applies_and_persists(main_window, style_hints):
    from PySide6.QtCore import Qt

    actions = {a.data(): a for a in main_window.appearance_actions.actions()}
    assert list(actions) == ["System", "Light", "Dark"]
    assert actions["System"].isChecked()

    actions["Dark"].trigger()
    assert fetch_data("scoresight.json", "color_scheme") == "Dark"
    assert style_hints.calls == [Qt.ColorScheme.Dark]
    assert actions["Dark"].isChecked() and not actions["System"].isChecked()


def test_appearance_menu_shows_the_stored_scheme(make_window):
    store_data("scoresight.json", "color_scheme", "Light")
    window = make_window()
    checked = [a.data() for a in window.appearance_actions.actions() if a.isChecked()]
    assert checked == ["Light"]


def test_about_dialog_shows_the_version_and_no_dead_links(main_window):
    dialog = main_window.createAboutDialog()
    assert __version__ in dialog.ui.label_version.text()
    text = dialog.ui.label.text()
    assert "scoresight.live" not in text
    assert "https://github.com/royshil/scoresight/issues" in text
    assert "https://royshil.github.io/scoresight/" in text
    assert "color:#" not in text
    dialog.deleteLater()


def test_startup_update_check_shows_an_available_update(
    make_window, monkeypatch, qtbot
):
    import mainwindow

    threads = []

    def fake_check():
        threads.append(threading.current_thread())
        return UpdateCheckResult("0.2.0", "0.3.0", update_available=True)

    monkeypatch.setattr(mainwindow, "check_for_updates", fake_check)
    window = make_window()
    qtbot.waitUntil(lambda: window.update_dialog is not None)
    assert threads[0] is not threading.main_thread()
    assert not window.update_dialog.ui.label_newVersion.isHidden()
    window.update_dialog.close()


def test_startup_update_check_respects_the_setting(make_window, monkeypatch):
    # pytest.fail() in the (background) check only killed that thread with a
    # warning, so this passed even when the setting was ignored. The check is
    # started (or not) synchronously by the constructor.
    import mainwindow

    calls = []
    monkeypatch.setattr(
        mainwindow,
        "check_for_updates",
        lambda: calls.append(1) or UpdateCheckResult(__version__, __version__),
    )
    started = []
    real_run_in_background = mainwindow.run_in_background

    def run_in_background(name, function, on_done):
        started.append(name)
        return real_run_in_background(name, function, on_done)

    monkeypatch.setattr(mainwindow, "run_in_background", run_in_background)
    store_data("scoresight.json", "disable_update_checks", True)
    window = make_window()
    assert "update check" not in started
    assert "source discovery" in started  # the background jobs are seen
    assert calls == []
    assert window.update_dialog is None


def test_manual_update_check_always_shows_the_result(make_window, monkeypatch, qtbot):
    import mainwindow

    monkeypatch.setattr(
        mainwindow, "check_for_updates", lambda: UpdateCheckResult("0.2.0", "0.2.0")
    )
    store_data("scoresight.json", "disable_update_checks", True)
    window = make_window()
    window.checkForUpdates(True)
    qtbot.waitUntil(lambda: window.update_dialog is not None)
    assert not window.update_dialog.ui.label_noNewVersion.isHidden()
    window.update_dialog.close()


def test_a_manual_check_during_the_startup_check_shows_its_result(
    make_window, monkeypatch, qtbot
):
    # File > Check for Updates while the startup check was still running did
    # nothing, and the startup check shows no dialog when there is no update.
    import mainwindow

    release = threading.Event()
    calls = []

    def slow_check():
        calls.append(threading.current_thread())
        release.wait(5)
        return UpdateCheckResult(__version__, __version__)

    monkeypatch.setattr(mainwindow, "check_for_updates", slow_check)
    window = make_window()
    assert window.update_check_running
    window.checkForUpdates(True)
    release.set()
    qtbot.waitUntil(lambda: window.update_dialog is not None)
    assert len(calls) == 1
    assert not window.update_dialog.ui.label_noNewVersion.isHidden()
    window.update_dialog.close()
    assert not window.update_check_manual_pending


def test_confidence_threshold_slider(main_window, make_target):
    ui = main_window.ui
    # either engine's confidence, with the advice for PP-OCR's
    assert "PP-OCR, 80-90" in ui.horizontalSlider_conf_thresh.toolTip()
    assert "%" in ui.label_3.toolTip()
    handler = main_window.boxSettingsUiHandler
    handler.populateSettings("")  # no box selected: the default, off
    assert ui.horizontalSlider_conf_thresh.value() == 0

    storage = main_window.detectionTargetsStorage
    storage.add_item(make_target("Home Score", conf_thresh=0.29))
    main_window.itemSelected("Home Score")
    assert ui.horizontalSlider_conf_thresh.value() == 29
    ui.horizontalSlider_conf_thresh.setValue(45)
    assert storage.find_item_by_name("Home Score").settings["conf_thresh"] == 0.45


# --- the viewer column: source bar, banners, view tools, first run -----------------------


class StartedViewer(FakeViewer):
    """A viewer whose capture is running (a frame arrived)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.timerThread = FakeCaptureThread()
        self.firstFrameReceived = True


def open_video(window, tmp_path, name="final game.mp4"):
    video = tmp_path / name
    video.write_bytes(b"")
    window.source_name = str(video)
    window.ui.comboBox_camera_source.blockSignals(True)
    window.ui.comboBox_camera_source.setCurrentIndex(1)
    window.ui.comboBox_camera_source.blockSignals(False)
    window.sourceSelectionSucessful()
    return video


def test_the_source_combo_box_shows_the_open_source(main_window, tmp_path, qapp):
    ui = main_window.ui
    combo = ui.comboBox_camera_source
    assert combo.itemText(0) == "No source"
    assert combo.itemText(1) == "Video file…"
    # wide enough for the whole name (it is elided to the combo box's width)
    main_window.resize(1800, 800)
    main_window.show()
    qapp.processEvents()
    video = open_video(main_window, tmp_path)
    assert combo.currentText() == "Video file: final game.mp4"
    assert str(video) in combo.toolTip()
    assert combo.itemData(1, QtCore.Qt.ItemDataRole.ToolTipRole) == str(video)
    # the speed is for video files, the video settings for cameras
    assert ui.toolButton_speed.isVisibleTo(main_window)
    assert ui.toolButton_speed.text() == "×1"
    assert not ui.toolButton_videoSettings.isEnabled()
    assert "only for cameras" in ui.toolButton_videoSettings.toolTip()

    # a stream: without its password
    main_window.source_name = "rtsp://admin:secret@10.0.1.200:554/11"
    combo.blockSignals(True)
    combo.setCurrentIndex(2)
    combo.blockSignals(False)
    main_window.sourceSelectionSucessful()
    assert combo.itemText(1) == "Video file…"  # the chooser again
    assert "Stream: rtsp://10.0.1.200:554/11".startswith(
        combo.currentText().split("…")[0]
    )
    assert "secret" not in combo.currentText() + combo.toolTip()
    assert not ui.toolButton_speed.isVisibleTo(main_window)

    # a language change keeps it
    main_window.changeLanguage("de_DE")
    try:
        assert combo.currentText().startswith("Stream: rtsp://")
    finally:
        qapp.removeTranslator(main_window.translator)
    main_window.reset_playing_source()
    combo.setCurrentIndex(0)
    assert combo.itemText(2) == "Stream URL (RTSP, HTTP)…"


def test_a_long_source_name_is_elided_in_the_middle(main_window, tmp_path):
    main_window.show()
    main_window.ui.comboBox_camera_source.setFixedWidth(160)
    open_video(main_window, tmp_path, "a very long name of the final game.mp4")
    combo = main_window.ui.comboBox_camera_source
    text = combo.currentText()
    assert text.startswith("Vid") and text.endswith(".mp4") and "…" in text
    assert combo.fontMetrics().horizontalAdvance(text) < 160
    assert "a very long name of the final game.mp4" in combo.toolTip()


def test_video_settings_are_for_cameras(make_window, patched):
    patched["cameras"].append(
        CameraInfo("Capture Card", "0", 0, CameraInfo.CameraType.OPENCV)
    )
    window = make_window()
    combo = window.ui.comboBox_camera_source
    combo.setCurrentIndex(combo.findText("Capture Card"))
    # (the source bar waits for the first frame)
    assert window.ui.toolButton_videoSettings.isEnabledTo(window.ui.frame_source_view)
    assert "resolution" in window.ui.toolButton_videoSettings.toolTip()
    assert combo.currentText() == "Capture Card"


def test_picking_the_open_file_again_chooses_another_one(
    main_window, tmp_path, monkeypatch
):
    import mainwindow

    video = open_video(main_window, tmp_path)
    combo = main_window.ui.comboBox_camera_source
    other = tmp_path / "second half.mp4"
    other.write_bytes(b"")
    answers = iter([("", ""), (str(other), "")])
    monkeypatch.setattr(
        mainwindow.QFileDialog,
        "getOpenFileName",
        lambda *args, **kwargs: next(answers),
    )
    first = main_window.image_viewer
    # the list opened on the open file, which is picked again: Cancel keeps it
    main_window.sourceIndexAtPopup = 1
    combo.activated.emit(1)
    assert main_window.image_viewer is first
    assert first.camera_info.id == str(video)
    main_window.sourceIndexAtPopup = 1
    combo.activated.emit(1)
    assert main_window.image_viewer.camera_info.id == str(other)
    assert combo.itemData(1, QtCore.Qt.ItemDataRole.ToolTipRole) == str(other)
    # picking another item (index changed first) doesn't ask twice
    main_window.sourceIndexAtPopup = None
    combo.activated.emit(1)


def test_the_source_health_dot(make_window, monkeypatch, patched):
    import mainwindow

    monkeypatch.setattr(mainwindow, "ImageViewer", StartedViewer)
    store_data("scoresight.json", "source_selected", "rtsp://10.0.1.200:554/11")
    window = make_window()
    dot = window.ui.label_sourceHealth
    window.refreshLiveStatus()
    assert dot.toolTip() == "Frames are arriving."
    assert not dot.pixmap().isNull()
    thread = window.image_viewer.timerThread
    thread.nominal_fps = 30.0
    thread.fps = 9.0
    window.refreshLiveStatus()
    assert "less than half" in dot.toolTip()
    assert "slow: 9.0 of 30 fps" in window.statusBarWidgets.label_source.text()
    thread.retry_count = 5
    window.refreshLiveStatus()
    assert "reconnecting" in dot.toolTip()
    window.updateError("Error: Unable to play video stream")
    assert dot.toolTip() == "The source can't be read."
    window.reset_playing_source()
    window.refreshLiveStatus()
    assert dot.toolTip() == "No source is open."


def test_a_source_error_shows_a_banner_with_retry(make_window, monkeypatch, patched):
    import mainwindow

    opened = []

    class CountingViewer(FakeViewer):
        def __init__(self, camera_info, *args, **kwargs):
            super().__init__(camera_info, *args, **kwargs)
            opened.append(camera_info)

    monkeypatch.setattr(mainwindow, "ImageViewer", CountingViewer)
    store_data("scoresight.json", "source_selected", "rtsp://10.0.1.200:554/11")
    window = make_window()
    ui = window.ui
    window.show()
    assert not ui.frame_sourceError.isVisibleTo(window)
    window.cameraConnectedEnableUI()
    assert ui.widget_viewOptions.isEnabled()

    window.updateError("Error: Unable to play video stream")
    assert ui.frame_sourceError.isVisibleTo(window)
    assert "Can't open the stream rtsp://10.0.1.200:554/11" in (
        ui.label_sourceError.text()
    )
    assert ui.pushButton_retrySource.isVisibleTo(window)
    assert not ui.pushButton_openScreenSettings.isVisibleTo(window)
    # the view tools wait for frames
    assert not ui.widget_viewOptions.isEnabled()
    assert not ui.widget_viewTools.isEnabled()

    # Retry opens the same source again
    ui.pushButton_retrySource.click()
    assert len(opened) == 2 and opened[1].id == "rtsp://10.0.1.200:554/11"
    assert not ui.frame_sourceError.isVisibleTo(window)

    # Troubleshooting opens the guide
    urls = []
    monkeypatch.setattr(mainwindow.QDesktopServices, "openUrl", urls.append)
    window.updateError("Error: Unable to play video stream")
    ui.pushButton_sourceTroubleshooting.click()
    assert urls[0].toString().endswith("troubleshooting.html#source-problems")
    popups = []
    monkeypatch.setattr(
        ui.comboBox_camera_source, "showPopup", lambda: popups.append(True)
    )
    ui.pushButton_chooseSource.click()
    assert popups == [True]
    # another source: the banner goes
    window.reset_playing_source()
    assert not ui.frame_sourceError.isVisibleTo(window)


def test_the_source_banner_asks_for_the_screen_recording_permission(
    make_window, monkeypatch
):
    import mainwindow

    monkeypatch.setattr(
        mainwindow.source_bar, "screen_recording_allowed", lambda: False
    )
    monkeypatch.setattr(mainwindow.MainWindow, "screenCaptureWindows", lambda: [])
    store_data(
        "scoresight.json", "source_selected", {"type": "Screen Capture", "value": -1}
    )
    window = make_window()
    window.show()
    ui = window.ui
    assert ui.frame_sourceError.isVisibleTo(window)
    assert "isn't allowed to record the screen" in ui.label_sourceError.text()
    # frames arrive (of the desktop only): the banner stays
    window.cameraConnectedEnableUI()
    assert ui.frame_sourceError.isVisibleTo(window)
    assert ui.pushButton_openScreenSettings.isVisibleTo(window)
    assert not ui.pushButton_retrySource.isVisibleTo(window)
    urls = []
    monkeypatch.setattr(mainwindow.QDesktopServices, "openUrl", urls.append)
    ui.pushButton_openScreenSettings.click()
    assert urls[0].toString().startswith("x-apple.systempreferences:")
    # (elided to the combo box's width)
    assert ui.comboBox_camera_source.currentText().startswith("Scre")
    assert "Entire screen" in ui.comboBox_camera_source.toolTip()


def test_four_corner_never_removes_a_correction_silently(
    main_window, monkeypatch, qtbot
):
    import mainwindow

    ui = main_window.ui
    viewer = FakeViewer(None, None, None, None)
    viewer.corrected = True
    main_window.image_viewer = viewer
    main_window.cameraConnectedEnableUI()
    main_window.updateFourCornerUi()
    main_window.show()
    assert ui.pushButton_fourCorner.isChecked()  # a correction is in place

    choices = iter([None, "remove", "remove", "redo"])
    monkeypatch.setattr(main_window, "askFourCornerAction", lambda: next(choices))
    answers = iter([QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Yes])
    monkeypatch.setattr(
        mainwindow.QMessageBox, "question", lambda *args, **kwargs: next(answers)
    )
    ui.pushButton_fourCorner.click()  # menu cancelled
    assert viewer.four_corner_calls == []
    assert ui.pushButton_fourCorner.isChecked()
    ui.pushButton_fourCorner.click()  # Remove correction..., then Cancel
    assert viewer.four_corner_calls == []
    ui.pushButton_fourCorner.click()  # Remove correction..., then Yes
    assert viewer.four_corner_calls == ["remove"]
    assert not ui.pushButton_fourCorner.isChecked()

    # no correction: a click picks corners right away, with the banner
    ui.pushButton_fourCorner.click()
    assert viewer.four_corner_calls == ["remove", "start"]
    assert ui.frame_fourCornerBanner.isVisibleTo(main_window)
    assert "0 of 4" in ui.label_fourCornerBanner.text()
    viewer.picked = 2
    viewer.four_corner_changed.emit()
    assert "2 of 4" in ui.label_fourCornerBanner.text()
    # Esc (anywhere in the window) cancels
    from PySide6.QtTest import QTest

    QTest.keyClick(main_window, QtCore.Qt.Key.Key_Escape)
    assert viewer.four_corner_calls[-1] == "cancel"
    assert not ui.frame_fourCornerBanner.isVisibleTo(main_window)

    # with a correction, Redo corners... keeps it until the new one replaces it
    viewer.corrected = True
    ui.pushButton_fourCorner.click()
    assert viewer.four_corner_calls[-1] == "start"
    assert "keeps the previous correction" in ui.label_fourCornerBanner.text()
    ui.pushButton_cancelFourCorner.click()
    assert viewer.four_corner_calls[-1] == "cancel"
    assert viewer.corrected


def test_fit_and_the_zoom_readout(make_window, monkeypatch):
    import mainwindow

    monkeypatch.setattr(mainwindow, "ImageViewer", StartedViewer)
    store_data("scoresight.json", "source_selected", "rtsp://10.0.1.200:554/11")
    window = make_window()
    ui = window.ui
    window.cameraConnectedEnableUI()
    assert ui.label_zoom.text() == "100%"
    ui.actionZoomIn.trigger()  # Ctrl+=
    assert ui.label_zoom.text() == "125%"
    ui.actionZoomOut.trigger()  # Ctrl+-
    assert ui.label_zoom.text() == "100%"
    assert ui.toolButton_zoomReset.text() == "Fit"
    ui.actionFitPicture.trigger()  # Ctrl+0
    assert ui.label_zoom.text() == "50%"
    # the hint that was a label is in the tooltips
    assert "Ctrl+scroll" in ui.toolButton_zoomReset.toolTip()
    assert "Ctrl+scroll" in ui.label_zoom.toolTip()
    assert not hasattr(ui, "label_11")
    window.reset_playing_source()
    assert ui.label_zoom.text() == ""


def test_the_statistics_overlay_is_off_for_new_settings(make_window):
    window = make_window()
    assert not window.ui.toolButton_osd.isChecked()
    assert fetch_data("scoresight.json", "show_osd") is False
    assert window.ui.toolButton_osd.text() == "Stats"
    window.ui.actionStatsOverlay.trigger()
    assert window.ui.toolButton_osd.isChecked()
    assert fetch_data("scoresight.json", "show_osd") is True


def test_the_statistics_overlay_stays_on_for_older_settings(make_window):
    # 0.2.0 and before always showed it
    store_data("scoresight.json", "boxes", [])
    window = make_window()
    assert window.ui.toolButton_osd.isChecked()
    assert window.ui.actionStatsOverlay.isChecked()
    window.ui.toolButton_osd.setChecked(False)
    window.close()
    # the choice is kept
    assert not make_window().ui.toolButton_osd.isChecked()


def test_collecting_training_data_is_a_tools_action_with_a_chip(
    main_window, monkeypatch
):
    from ocr_training_data import ocr_training_data_options

    # (ocr_training_data_options follows the setting: its subscription isn't
    # in the tests' registry)
    ui = main_window.ui
    assert not hasattr(ui, "pushButton_saveOCRTrainingData")
    assert ui.actionCollectTrainingData in ui.menuTools.actions()
    assert ui.actionOCRTrainingDataSetup in ui.menuTools.actions()
    chip = main_window.statusBarWidgets.button_training
    main_window.show()
    assert not chip.isVisibleTo(main_window)

    ui.actionCollectTrainingData.trigger()
    assert fetch_data("scoresight.json", "save_ocr_training_data") is True
    assert chip.isVisibleTo(main_window)
    assert chip.text() == "Collecting training data"
    assert ocr_training_data_options.ocr_training_data_folder in chip.toolTip()
    opened = []
    monkeypatch.setattr(main_window, "openOCRTrainingDataDialog", lambda: None)
    main_window.statusBarWidgets.training_data_clicked.disconnect()
    main_window.statusBarWidgets.training_data_clicked.connect(
        lambda: opened.append(True)
    )
    chip.click()
    assert opened == [True]

    ui.actionCollectTrainingData.trigger()
    assert fetch_data("scoresight.json", "save_ocr_training_data") is False
    assert not chip.isVisibleTo(main_window)


def test_collecting_training_data_is_restored(make_window):
    store_data("scoresight.json", "save_ocr_training_data", True)
    window = make_window()
    assert window.ui.actionCollectTrainingData.isChecked()
    window.refreshLiveStatus()
    assert not window.statusBarWidgets.button_training.isHidden()


def test_the_first_run_card(main_window, make_target, monkeypatch, no_dialogs):
    import mainwindow

    ui = main_window.ui
    main_window.show()
    assert ui.frame_firstRun.isVisibleTo(main_window)
    assert ui.label_12.text() == "Open a source to begin"
    assert "quickstart.html" in ui.label_firstRunQuickstart.text()
    # and where to ask
    assert (
        'href="https://github.com/royshil/scoresight/discussions"'
        in ui.label_firstRunQuickstart.text()
    )
    assert main_window.firstRunSteps() == (False, False, False)
    steps = [
        ui.label_firstRunStep1.accessibleName(),
        ui.label_firstRunStep2.accessibleName(),
        ui.label_firstRunStep3.accessibleName(),
    ]
    assert steps == ["Step 1", "Step 2", "Step 3"]

    # a box placed, an output on: their steps get a check mark
    main_window.detectionTargetsStorage.add_item(make_target("Home Score"))
    ui.checkBox_enableOutAPI.setChecked(True)
    main_window.refreshLiveStatus()
    assert main_window.firstRunSteps() == (False, True, True)
    assert ui.label_firstRunStep2.accessibleName() == "Step 2: done"
    assert ui.label_firstRunStep3.accessibleName() == "Step 3: done"

    # its buttons pick the source items (the file dialog is cancelled here)
    monkeypatch.setattr(
        mainwindow.QFileDialog, "getOpenFileName", lambda *args, **kwargs: ("", "")
    )
    asked = []
    original = main_window.askSourceValue
    monkeypatch.setattr(
        main_window,
        "askSourceValue",
        lambda index: asked.append(index) or original(index),
    )
    ui.pushButton_firstRunFile.click()
    ui.pushButton_firstRunUrl.click()  # the URL dialog (recorded, not shown)
    assert asked == [1, 2]
    assert no_dialogs == ["URL Source"]
    assert ui.comboBox_camera_source.currentIndex() == 0
    # no camera was found
    actions = [a.text() for a in main_window.firstRunCameraMenu.actions()]
    assert actions[0] == "No camera found"
    assert ui.actionReloadSources in main_window.firstRunCameraMenu.actions()

    # a source opens: the card goes
    main_window.image_viewer = FakeViewer(None, None, None, None)
    main_window.updateFirstRunCard()
    assert not ui.frame_firstRun.isVisibleTo(main_window)


def test_the_first_run_card_lists_the_cameras(make_window, patched, no_dialogs):
    patched["cameras"].extend(
        CameraInfo(f"Cam {n}", f"uuid-{n}", n, CameraInfo.CameraType.OPENCV)
        for n in range(2)
    )
    window = make_window()
    menu = window.firstRunCameraMenu
    assert [a.text() for a in menu.actions()][:2] == ["Cam 0", "Cam 1"]
    menu.actions()[1].trigger()
    assert window.ui.comboBox_camera_source.currentText() == "Cam 1"
    assert window.image_viewer.camera_info.uuid == "uuid-1"
    assert not window.ui.frame_firstRun.isVisibleTo(window)


def test_the_rotate_button_shows_the_angle(main_window, qapp):
    ui = main_window.ui
    assert ui.toolButton_rotate.text() == "Rotate 90° · 0°"
    main_window.rotateImage()
    assert ui.toolButton_rotate.text() == "Rotate 90° · 90°"
    main_window.changeLanguage("de_DE")
    try:
        assert ui.toolButton_rotate.text().endswith("90°")
    finally:
        qapp.removeTranslator(main_window.translator)


def test_crop_off_keeps_the_values(main_window):
    ui = main_window.ui
    main_window.setViewToolsEnabled(True)  # as with a source
    ui.toolButton_topCrop.click()
    assert not ui.toolButton_resetCrop.isEnabled()
    ui.spinBox_leftCrop.setValue(40)
    ui.toolButton_topCrop.click()
    assert fetch_data("scoresight.json", "crop_mode") is False
    assert fetch_data("scoresight.json", "left_crop") == 40
    # the kept values can be reset when the crop is on again
    ui.toolButton_topCrop.click()
    assert ui.spinBox_leftCrop.value() == 40
    assert ui.toolButton_resetCrop.isEnabled()
    assert ui.spinBox_leftCrop.suffix() == " px"


def test_checked_view_tools_are_filled(main_window):
    style = main_window.ui.widget_4.styleSheet()
    assert "QToolButton:checked" in style
    # the Adjust picture row also styles its AI buttons (in their own colour)
    adjust = main_window.ui.widget_viewTools.styleSheet()
    assert adjust.startswith(style) and "QToolButton#toolButton_autoCrop" in adjust


def test_the_viewer_column_fits_its_minimum_width(reference_font, make_window, qtbot):
    # the source bar shows icons, then puts the view tools under the source;
    # the Adjust picture row drops its label; the first-run card's buttons
    # take two lines
    from PySide6.QtCore import Qt

    import mainwindow

    main_window = make_window()
    ui = main_window.ui
    row = main_window.sourceBarRow
    main_window.resize(max(2400, main_window.minimumSizeHint().width() + 900), 800)
    main_window.show()
    qtbot.waitUntil(lambda: not row.compact)
    assert (
        ui.pushButton_binary.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonTextOnly
    )
    assert ui.label_boxDisplayStyle.isVisibleTo(main_window)
    assert ui.label_adjustPicture.isVisibleTo(main_window)

    # a viewer column of its minimum width
    sizes = ui.splitter_main.sizes()
    ui.splitter_main.setSizes(
        [sizes[0], mainwindow.VIEWER_MIN_WIDTH, sum(sizes) - sizes[0] - 360]
    )
    qtbot.waitUntil(lambda: row.wrapped)
    for button in (ui.pushButton_binary, ui.toolButton_osd, ui.toolButton_zoomReset):
        assert button.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonIconOnly
        assert not button.icon().isNull()
        assert button.toolTip()
    assert not ui.label_boxDisplayStyle.isVisibleTo(main_window)
    assert not ui.label_adjustPicture.isVisibleTo(main_window)
    # under the source
    qtbot.waitUntil(
        lambda: ui.widget_viewOptions.geometry().top() > ui.widget_3.geometry().bottom()
    )
    assert ui.frame_firstRun.isVisibleTo(main_window)
    qtbot.waitUntil(
        lambda: (
            ui.pushButton_firstRunUrl.geometry().top()
            > ui.pushButton_firstRunCamera.geometry().bottom()
        )
    )
    if not reference_font:
        return  # the widths below are for Segoe UI 9 pt
    # nothing in the column needs more room
    for widget in (
        ui.widget_4,
        ui.widget_viewTools,
        ui.widget_cropPanel,
        ui.frame_firstRun,
        ui.frame_fourCornerBanner,
    ):
        needed = widget.minimumWidth() or widget.minimumSizeHint().width()
        assert needed <= ui.frame_source_view.width(), widget.objectName()
    assert ui.frame_source_view.minimumSizeHint().width() <= (
        mainwindow.VIEWER_MIN_WIDTH
    )

    main_window.resize(2400, 800)
    ui.splitter_main.setSizes([260, 1700, 340])
    qtbot.waitUntil(lambda: not row.compact)
    assert ui.label_boxDisplayStyle.isVisibleTo(main_window)
    qtbot.waitUntil(
        lambda: (
            ui.pushButton_firstRunUrl.geometry().top()
            == ui.pushButton_firstRunCamera.geometry().top()
        )
    )


def test_retrying_a_missing_file_leaves_the_source_usable(main_window, tmp_path):
    # the file was moved: Retry can't open it, and the source bar must still
    # work (it was disabled while opening and stayed so)
    ui = main_window.ui
    main_window.show()
    video = open_video(main_window, tmp_path)
    main_window.updateError("Error: Unable to play video stream")
    assert "Can't play the video file" in ui.label_sourceError.text()
    video.unlink()
    ui.pushButton_retrySource.click()
    assert main_window.image_viewer is None
    assert ui.comboBox_camera_source.currentIndex() == 0
    assert ui.frame_source_view.isEnabled()
    assert ui.comboBox_camera_source.isEnabledTo(main_window)
    assert ui.frame_firstRun.isVisibleTo(main_window)
    assert not ui.frame_sourceError.isVisibleTo(main_window)


def test_esc_in_the_source_list_only_closes_the_list(main_window):
    from PySide6.QtGui import QKeyEvent

    viewer = FakeViewer(None, None, None, None)
    main_window.image_viewer = viewer
    main_window.cameraConnectedEnableUI()
    viewer.startFourCornerSelection()
    # (the list is a popup window: its Esc doesn't reach the main window)
    QApplication.sendEvent(
        main_window.ui.comboBox_camera_source.view(),
        QKeyEvent(
            QEvent.Type.KeyPress,
            QtCore.Qt.Key.Key_Escape,
            QtCore.Qt.KeyboardModifier.NoModifier,
        ),
    )
    assert viewer.fourCornerSelectionMode
    # Esc in the window cancels it
    QApplication.sendEvent(
        main_window,
        QKeyEvent(
            QEvent.Type.KeyPress,
            QtCore.Qt.Key.Key_Escape,
            QtCore.Qt.KeyboardModifier.NoModifier,
        ),
    )
    assert not viewer.fourCornerSelectionMode


def test_a_new_source_starts_without_binary_view(main_window, tmp_path):
    ui = main_window.ui
    open_video(main_window, tmp_path)
    main_window.cameraConnectedEnableUI()
    ui.pushButton_binary.click()
    ui.pushButton_stabilize.click()
    assert ui.actionBinaryView.isChecked()
    open_video(main_window, tmp_path, "second half.mp4")
    # the new capture shows the picture and isn't stabilized
    assert not ui.pushButton_binary.isChecked()
    assert not ui.actionBinaryView.isChecked()
    assert not ui.pushButton_stabilize.isChecked()


# --- the Setup and Live layouts ------------------------------------------------------


def visible_rows(window):
    table = window.ui.tableWidget_boxes
    return [
        table.item(row, 0).text()
        for row in range(table.rowCount())
        if not table.isRowHidden(row)
    ]


def settled_pane_widths(window, qtbot):
    """The panes' widths once the layout requests are handled: the Box tab's
    content sets the Inspector's minimum width on its layout request
    (fitBoxSettingsWidth), and the splitter follows on another one."""
    widths = []

    def stable():
        QCoreApplication.sendPostedEvents(None, QEvent.Type.LayoutRequest)
        widths.append(window.ui.splitter_main.sizes())
        return len(widths) >= 2 and widths[-1] == widths[-2]

    qtbot.waitUntil(stable)
    return widths[-1]


def test_the_live_layout(make_window, qtbot, patched, make_target, make_result):
    from defaults import default_boxes

    window = make_window()
    ui = window.ui
    window.resize(1366, 768)
    with qtbot.waitExposed(window):
        window.show()
    storage = window.detectionTargetsStorage
    storage.add_item(make_target("Home Score"))
    storage.add_item(make_target("Time"))
    # (the Box tab's content sets the Inspector's minimum width)
    window.itemSelected("Time")
    setup_sizes = settled_pane_widths(window, qtbot)
    assert setup_sizes[2] > 0
    setup_row = window.readingDelegate.rowHeight(ui.tableWidget_boxes.font())
    assert len(visible_rows(window)) == len(default_boxes)

    ui.actionLiveLayout.trigger()  # Ctrl+2
    assert window.layoutMode == "live"
    assert fetch_data("scoresight.json", "window_layout") == "live"
    fields, viewer, inspector = ui.splitter_main.sizes()
    # the Inspector collapsed, the readings about 400 pixels wide
    assert inspector == 0 and 380 <= fields <= 420 and viewer >= 360
    # the readings large, the unused fields hidden
    assert window.readingDelegate.density == "live"
    assert window.readingDelegate.rowHeight(ui.tableWidget_boxes.font()) > setup_row
    assert ui.tableWidget_boxes.verticalHeader().defaultSectionSize() > setup_row
    assert visible_rows(window) == ["Home Score", "Time"]
    assert ui.label_hiddenFields.isVisibleTo(window)
    assert f": {len(default_boxes) - 2} hidden" in ui.label_hiddenFields.text()
    assert ui.label_fields.text() == "Readings"
    # no picture adjustments; the outputs under the readings
    assert not ui.widget_viewTools.isVisibleTo(window)
    assert not ui.widget_fieldsFooter.isVisibleTo(window)
    live_list = ui.listView_liveDestinations
    assert live_list.isVisibleTo(window)
    assert live_list.model() is window.destinationsModel
    # one line per output, all of them shown
    assert live_list.height() >= window.destinationsModel.rowCount() * (
        window.liveDestinationDelegate.rowHeight(live_list.font())
    )
    live_list.grab()  # paints without errors

    # the reading and the outputs work the same
    window.obs_websocket_client = client = FakeObsClient()
    window.ocrResult([make_result("Home Score", "12"), make_result("Time", "1:00")])
    assert box_value(window, "Home Score") == "12"
    assert patched["obs"] == [(client, "Home score", "12"), (client, "Clock", "1:00")]

    # a new field is shown (it is selected) until another one is selected
    window.addBox()
    [custom] = custom_field_names()
    assert custom in visible_rows(window)
    window.itemSelected("Time")
    assert custom not in visible_rows(window)

    # View > Show unused fields, remembered for the Live layout only
    ui.actionShowUnusedFields.trigger()
    assert len(visible_rows(window)) == len(default_boxes) + 1
    assert not ui.label_hiddenFields.isVisibleTo(window)
    assert fetch_data("scoresight.json", "show_unused_fields_live") is True
    ui.actionShowUnusedFields.trigger()
    assert visible_rows(window) == ["Home Score", "Time"]

    # Setup: the widths it had, every field, the adjustments
    ui.actionSetupLayout.trigger()  # Ctrl+1
    assert settled_pane_widths(window, qtbot) == setup_sizes
    assert window.readingDelegate.density == "setup"
    assert len(visible_rows(window)) == len(default_boxes) + 1
    # every row has the Setup height, also those that were hidden in Live
    table = ui.tableWidget_boxes
    assert [table.rowHeight(row) for row in range(table.rowCount())] == [
        setup_row
    ] * table.rowCount()
    assert ui.actionShowUnusedFields.isChecked()
    assert ui.widget_viewTools.isVisibleTo(window)
    assert ui.widget_fieldsFooter.isVisibleTo(window)
    assert not live_list.isVisibleTo(window)
    assert ui.label_fields.text() == "Fields"
    assert fetch_data("scoresight.json", "main_splitter_sizes") == setup_sizes

    # the layout is remembered
    ui.actionLiveLayout.trigger()
    window.close()
    again = make_window()
    assert again.layoutMode == "live" and again.ui.actionLiveLayout.isChecked()
    assert again.readingDelegate.density == "live"
    again.resize(1366, 768)
    with qtbot.waitExposed(again):
        again.show()
    assert again.ui.splitter_main.sizes()[2] == 0
    again.ui.actionSetupLayout.trigger()
    qtbot.waitUntil(lambda: again.ui.splitter_main.sizes() == setup_sizes)


def test_the_live_layout_fits_a_small_screen_in_every_language(
    make_window, qapp, qtbot, reference_font
):
    window = make_window()
    ui = window.ui
    window.resize(1366, 768)
    with qtbot.waitExposed(window):
        window.show()
    window.setLayoutMode("live")
    try:
        for language in ("de_DE", "en_US"):
            window.changeLanguage(language)
            qapp.processEvents()
            # a language change keeps the layout
            assert window.layoutMode == "live"
            assert ui.actionLiveLayout.isChecked()
            assert ui.listView_liveDestinations.isVisibleTo(window)
            assert not ui.widget_viewTools.isVisibleTo(window)
            assert ui.label_fields.text() == QCoreApplication.translate(
                "MainWindow", "Readings"
            )
            assert window.minimumSizeHint().height() <= 640
            fields, viewer, inspector = ui.splitter_main.sizes()
            assert inspector == 0 and fields >= 300 and viewer >= 360, (
                language,
                ui.splitter_main.sizes(),
            )
            # every output on its line
            model = window.destinationsModel
            assert ui.listView_liveDestinations.height() >= model.rowCount() * (
                window.liveDestinationDelegate.rowHeight(
                    ui.listView_liveDestinations.font()
                )
            )
    finally:
        qapp.removeTranslator(window.translator)


def test_a_language_change_keeps_the_shortcuts_and_the_names_width(main_window, qapp):
    ui = main_window.ui
    zoom_in = [key.toString() for key in ui.actionZoomIn.shortcuts()]
    hold = ui.actionHoldValue.shortcut().toString()
    assert len(zoom_in) == 2
    ui.tableWidget_boxes.setColumnWidth(0, 140)  # dragged by the user
    main_window.changeLanguage("de_DE")
    try:
        assert [key.toString() for key in ui.actionZoomIn.shortcuts()] == zoom_in
        assert ui.actionHoldValue.shortcut().toString() == hold
        assert ui.tableWidget_boxes.columnWidth(0) == 140
        # back from the Live layout: that width again
        main_window.setLayoutMode("live")
        main_window.setLayoutMode("setup")
        assert ui.tableWidget_boxes.columnWidth(0) == 140
    finally:
        qapp.removeTranslator(main_window.translator)


def test_the_obs_text_sources_follow_the_fields(main_window, make_target):
    ui = main_window.ui
    storage = main_window.detectionTargetsStorage
    storage.add_item(make_target("Custom 1", obs_source_name="Shots"))
    model = ui.tableView_obsSources.model()
    first = model.item(0, 1)
    # the user's edit doesn't rebuild the table (an editor stays open)
    first.setText("Shot clock")
    assert model.item(0, 1) is first
    storage.rename_item("Custom 1", "Game Clock")
    assert [model.item(row, 0).text() for row in range(model.rowCount())] == [
        "Game Clock"
    ]
    assert model.item(0, 1).text() == "Shot clock"
    storage.remove_item("Game Clock")
    assert model.rowCount() == 0


def test_a_live_output_opens_its_settings(main_window):
    ui = main_window.ui
    main_window.setLayoutMode("live")
    live_list = ui.listView_liveDestinations
    index = main_window.destinationsModel.index(3, 0)  # vMix
    # no switch here: a click doesn't turn it on
    assert not main_window.liveDestinationDelegate.editorEvent(
        None, main_window.destinationsModel, None, index
    )
    live_list.activated.emit(index)  # a double-click or Enter
    assert ui.stackedWidget_outputs.currentWidget() is ui.tab_vmix
    assert not main_window.isPaneHidden(2)


# --- Hold value -----------------------------------------------------------------------


@pytest.fixture
def http_url():
    import http_server

    http_server.start_http_server(port=0)
    port = http_server.get_http_server_port()
    assert port
    yield f"http://127.0.0.1:{port}"
    http_server.stop_http_server()
    http_server.update_http_server([])


def test_a_held_value_reaches_every_output(
    main_window, patched, make_result, make_target, monkeypatch, tmp_path, http_url
):
    import requests

    import mainwindow

    ui = main_window.ui
    storage = main_window.detectionTargetsStorage
    storage.add_item(make_target("Home Score"))
    storage.add_item(make_target("Period"))
    ui.horizontalSlider_aggsPerSecond.setValue(10)
    main_window.setOutputFolder(str(tmp_path))
    main_window.obs_websocket_client = client = FakeObsClient()
    sent = {"vmix": [], "uno": [], "api": []}

    def readings(results):
        return {r.name: (r.result, r.result_state.name) for r in results}

    vmix = main_window.vmixUiHandler.vmixUpdater
    uno = main_window.unoUiHandler.unoUpdater
    vmix.update_vmix = lambda results, resend_unchanged=(): sent["vmix"].append(
        readings(results)
    )
    uno.update_uno = lambda results, resend_unchanged=(): sent["uno"].append(
        readings(results)
    )
    monkeypatch.setattr(
        mainwindow,
        "update_out_api",
        lambda results: sent["api"].append(readings(results)),
    )
    ui.checkBox_enableOutAPI.setChecked(True)

    def cycle(period, state="Success"):
        template = make_result(
            "Score Line",
            "",
            "Empty",
            templatefield=True,
            templatefield_text="{{Home Score}} - {{Period}}",
        )
        main_window.ocrResult(
            [
                make_result("Home Score", "12", "SameNoChange"),
                make_result("Period", period, state),
                template,
            ]
        )
        main_window.flushFileOutputs()

    def http():
        return requests.get(http_url + "/json?pivot", timeout=5).json()

    cycle("2nd")
    # Ctrl+H on the selected field: the editor is pre-filled with its value
    main_window.itemSelected("Period")
    asked = []
    monkeypatch.setattr(
        main_window,
        "askHoldValue",
        lambda name, value, held: asked.append((name, value, held)) or ("hold", "3rd"),
    )
    ui.actionHoldValue.trigger()
    assert asked == [("Period", "2nd", False)]
    patched["obs"].clear()

    cycle("Z", "FailedFilter")  # a misread
    for output in ("vmix", "uno", "api"):
        assert sent[output][-1]["Period"] == ("3rd", "Success"), output
        # templates use the held value
        assert sent[output][-1]["Score Line"] == ("12 - 3rd", "Success"), output
    assert http()["Period"] == "3rd"
    assert http()["Score Line"] == "12 - 3rd"
    assert (tmp_path / "Period.txt").read_text(encoding="utf-8") == "3rd"
    assert (tmp_path / "Score Line.txt").read_text(encoding="utf-8") == "12 - 3rd"
    assert patched["obs"] == [(client, "Period", "3rd")]
    # once new, then unchanged
    cycle("2nd", "SameNoChange")
    assert sent["vmix"][-1]["Period"] == ("3rd", "SameNoChange")
    assert sent["vmix"][-1]["Score Line"] == ("12 - 3rd", "SameNoChange")
    assert patched["obs"] == [(client, "Period", "3rd")]

    # the readings go on in the list: the OCR's value under the held one
    assert box_value(main_window, "Period") == "2nd"
    from readings_view import HELD_VALUE_ROLE

    assert box_value_item(main_window, "Period").data(HELD_VALUE_ROLE) == "3rd"

    # Release (the row's button): the readings again, sent as new
    main_window.readingDelegate.releaseRequested.emit("Period")
    assert box_value_item(main_window, "Period").data(HELD_VALUE_ROLE) is None
    cycle("2nd", "SameNoChange")
    for output in ("vmix", "uno", "api"):
        assert sent[output][-1]["Period"] == ("2nd", "Success"), output
        assert sent[output][-1]["Score Line"] == ("12 - 2nd", "Success"), output
    assert http()["Period"] == "2nd"
    assert (tmp_path / "Period.txt").read_text(encoding="utf-8") == "2nd"
    assert patched["obs"][-1] == (client, "Period", "2nd")
    cycle("2nd", "SameNoChange")
    assert sent["vmix"][-1]["Period"] == ("2nd", "SameNoChange")


def test_hold_value_in_the_field_list_and_the_picture(
    make_window, make_target, make_result, monkeypatch, qapp
):
    from PySide6.QtGui import QGuiApplication

    from readings_view import HELD_VALUE_ROLE

    store_data("scoresight.json", "source_selected", "rtsp://10.0.1.200:554/11")
    window = make_window()
    ui = window.ui
    viewer = window.image_viewer
    storage = window.detectionTargetsStorage
    storage.add_item(make_target("Period"))
    window.ocrResult([make_result("Period", "2nd")])
    window.itemSelected("Period")
    window.fieldContextMenu().deleteLater()
    assert ui.actionHoldValue.isEnabled() and not ui.actionReleaseValue.isEnabled()

    answers = [("hold", "3rd")]
    monkeypatch.setattr(window, "askHoldValue", lambda *args: answers.pop(0))
    ui.actionHoldValue.trigger()
    # the overlay says HELD
    assert viewer.heldValues == {"Period": "3rd"}
    assert box_value_item(window, "Period").data(HELD_VALUE_ROLE) == "3rd"
    menu = window.fieldContextMenu()
    names = [action.objectName() for action in menu.actions() if action.objectName()]
    menu.deleteLater()
    assert "actionReleaseValue" in names
    assert ui.actionHoldValue.text() == "Change held value..."
    ui.actionCopyValue.trigger()
    assert QGuiApplication.clipboard().text() == "3rd"
    # a new source shows it too
    window.sourceSelectionSucessful()
    assert window.image_viewer is not viewer
    assert window.image_viewer.heldValues == {"Period": "3rd"}
    # kept by a language change
    window.changeLanguage("de_DE")
    try:
        assert box_value_item(window, "Period").data(HELD_VALUE_ROLE) == "3rd"
        assert ui.actionReleaseValue.isEnabled()
    finally:
        qapp.removeTranslator(window.translator)

    # Release from the context menu
    ui.actionReleaseValue.trigger()
    assert window.image_viewer.heldValues == {}
    assert box_value_item(window, "Period").data(HELD_VALUE_ROLE) is None
    assert ui.actionHoldValue.text() == "Hold value..."

    # Release from the editor
    answers[:] = [("hold", "OT"), ("release", "")]
    ui.actionHoldValue.trigger()
    assert "Period" in window.heldValues
    ui.actionHoldValue.trigger()
    assert "Period" not in window.heldValues

    # taken off the picture: nothing to hold any more
    answers[:] = [("hold", "OT")]
    ui.actionHoldValue.trigger()
    window.removeBox()
    assert "Period" not in window.heldValues
    assert window.image_viewer.heldValues == {}
    assert not ui.actionHoldValue.isEnabled()


def test_a_renamed_field_stays_held(main_window, make_target, monkeypatch):
    import mainwindow

    main_window.addBox()
    [name] = custom_field_names()
    main_window.makeBox()
    main_window.heldValues.hold(name, "x")
    main_window.updateHeldUi()
    monkeypatch.setattr(
        mainwindow.QInputDialog, "getText", lambda *a, **k: ("Game Clock", True)
    )
    main_window.ui.actionRenameField.trigger()
    assert main_window.heldValues.values() == {"Game Clock": "x"}


def test_the_hold_value_dialog(main_window):
    from held_values import RELEASE, HoldValueDialog

    dialog = HoldValueDialog("Period", "2nd", False, main_window)
    assert dialog.value() == "2nd"
    assert dialog.releaseButton is None
    dialog.lineEdit.setText("3rd")
    dialog.holdButton.click()
    assert dialog.result() == dialog.DialogCode.Accepted
    assert dialog.value() == "3rd"
    dialog.deleteLater()

    held = HoldValueDialog("Period", "3rd", True, main_window)
    held.open()
    held.releaseButton.click()
    assert held.result() == RELEASE
    held.deleteLater()


# --- Ask before closing ------------------------------------------------------------


@pytest.fixture
def source_window(make_window):
    """A window with a source open: a stand-in viewer, taken away before the
    window is closed (closing a window closes its viewer)."""
    window = make_window()
    window.image_viewer = object()
    yield window
    window.image_viewer = None


def test_closing_with_a_source_open_asks_first(source_window, monkeypatch):
    # discussion #140: the window closed by accident during a broadcast
    window = source_window
    action = window.ui.actionAskBeforeClosing
    assert action.isChecked()
    asked = []
    answers = []
    monkeypatch.setattr(window, "canAskBeforeClosing", lambda: True)
    monkeypatch.setattr(
        window, "askToClose", lambda: asked.append(True) or answers.pop(0)
    )
    # no source open: nothing stops
    viewer, window.image_viewer = window.image_viewer, None
    assert window.closeConfirmed() and not asked
    window.image_viewer = viewer
    # Cancel: the window stays open
    answers.append((False, True))
    assert window.close() is False
    assert not window.closing and len(asked) == 1
    # Close
    answers.append((True, True))
    assert window.closeConfirmed() and len(asked) == 2
    assert action.isChecked()
    # Close with "Don't ask again"
    answers.append((True, False))
    assert window.closeConfirmed() and len(asked) == 3
    assert not action.isChecked()
    assert fetch_data("scoresight.json", "ask_before_closing") is False
    assert window.closeConfirmed() and len(asked) == 3
    # back on in the File menu
    action.setChecked(True)
    assert fetch_data("scoresight.json", "ask_before_closing") is True
    # a quit signal or Update now doesn't ask
    window.close_without_asking = True
    assert window.closeConfirmed() and len(asked) == 3


def test_ask_before_closing_is_remembered(make_window):
    store_data("scoresight.json", "ask_before_closing", False)
    assert not make_window().ui.actionAskBeforeClosing.isChecked()


def test_an_offscreen_app_closes_without_asking(source_window, monkeypatch):
    # a headless instance (the e2e test) is stopped with Ctrl+C or SIGTERM,
    # and nobody could answer
    window = source_window
    assert not window.canAskBeforeClosing()
    monkeypatch.setattr(window, "askToClose", lambda: pytest.fail("asked"))
    assert window.closeConfirmed()


@pytest.mark.parametrize(
    ("button", "dont_ask", "answer"),
    [
        ("Close", False, (True, True)),
        ("Close", True, (True, False)),
        ("Cancel", False, (False, True)),
    ],
)
def test_the_close_question(make_window, monkeypatch, button, dont_ask, answer):
    window = make_window()
    seen = {}

    def answer_it(box):
        # the question is the text: macOS shows no title (Qt clears it there)
        seen["question"] = box.text()
        seen["default"] = box.defaultButton().text()
        box.checkBox().setChecked(dont_ask)
        [clicked] = [b for b in box.buttons() if b.text() == button]
        clicked.click()

    monkeypatch.setattr(QMessageBox, "exec", answer_it)
    assert window.askToClose() == answer
    assert seen == {"question": "Close ScoreSight?", "default": "Cancel"}
