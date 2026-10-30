from datetime import datetime
from functools import partial
import html
import math
import os
import platform
import threading
import time
from typing import Callable
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFileDialog,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QStyle,
    QStyleOptionComboBox,
    QTableWidgetItem,
)
from PySide6.QtGui import (
    QActionGroup,
    QDesktopServices,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QIcon,
    QKeySequence,
    QPalette,
)
from PySide6.QtCore import (
    Qt,
    Signal,
    Slot,
    QPoint,
    QPointF,
    QRectF,
    QSize,
    QSizeF,
    QTimer,
    QTranslator,
    QObject,
    QCoreApplication,
    QEvent,
    QMetaMethod,
    QUrl,
)
from os import path

from api_output import out_api_status, send_mode, update_out_api
from api_ui_handler import APIUIHandler, OUT_API_ENCODINGS, OUT_API_METHODS
from auto_layout_ui import AutoLayoutUI
from box_settings_ui_handler import (
    NOT_PLACED,
    PLACED,
    TEMPLATE,
    BoxSettingsUIHandler,
    changed_settings,
)
from camera_info import CameraInfo
from camera_thread import SMOOTH_PREVIEW_SETTING, crop_margins
from destinations_view import (
    KEY_ROLE,
    STATUS_ROLE,
    CompactDestinationDelegate,
    DestinationDelegate,
    DestinationsModel,
)
from game_state import GameEngine
from game_ui_handler import GameUIHandler
from get_camera_info import get_camera_info
from held_values import RELEASE, HeldValues, HoldValueDialog
from http_server import (
    get_http_server_port,
    http_server_stats,
    start_http_server,
    update_game_state,
    update_http_server,
)
import ocr_models
from ocr_training_data import OCRTrainingDataDialog, ocr_training_data_options
import output_status
import ppocr_engine
from output_status import (
    STATE_COLORS,
    STATE_GLYPHS,
    DestinationStatus,
    describe_error,
    status_tooltip,
)
from output_worker import ErrorInfo
from keyboard_shortcuts import (
    KeyboardShortcutsDialog,
    action_rows,
    key_text,
    viewer_rows,
)
from obs_ui_handler import OBSSourcesTable
from overlay_ui_handler import OverlayBuilder
from plausibility_holds import PlausibilityHolds
from readings_view import (
    DENSITY_LIVE,
    DENSITY_SETUP,
    HELD_VALUE_ROLE,
    ReadingDelegate,
    clear_reading,
    record_reading,
    set_held,
)
from resource_path import resource_path
import source_bar
from source_view import ImageViewer, centered_rect
from status_bar import (
    SOURCE_NONE,
    MainStatusBar,
    StatusSnapshot,
    http_server_urls,
    ppocr_accurate_is_slow,
    ppocr_cpu_advice,
    primary_lan_address,
    snapshot_auto_text,
    source_display_name,
    source_look,
    source_state,
    source_state_description,
)
import theme
from defaults import (
    default_boxes,
    default_info_for_box_name,
    normalize_settings_dict,
)

from storage import (
    TextDetectionTargetMemoryStorage,
    fetch_data,
    get_data_dir,
    get_profile,
    remove_data,
    store_data,
    store_custom_box_name,
    rename_custom_box_name_in_storage,
    remove_custom_box_name_in_storage,
    fetch_custom_box_names,
)
from obs_websocket import (
    SCENE_CREATED,
    SCENE_FAILED,
    SCENE_KEPT,
    SCENE_RECREATED,
    close_obs_websocket,
    create_obs_scene_from_export,
    last_connect_error,
    obs_client_address,
    obs_output_status,
    open_obs_websocket,
    update_text_source,
)

import startup_timing
from tcp_ui_handler import TcpUIHandler
from template_fields import apply_template_fields, is_template_field
from text_detection_target import TextDetectionTarget, TextDetectionTargetWithResult
from sc_logging import logger
from uno_ui_handler import UNOUIHandler
import app_update
from app_update_ui import AppUpdater
from update_check import (
    UpdateCheckResult,
    check_for_updates,
    show_update_dialog,
    update_checks_enabled,
)
from log_view import LogViewerDialog
import file_output
from version import __version__
from video_settings import VideoSettingsDialog
from ui_mainwindow import Ui_MainWindow
from ui_about import Ui_Dialog as Ui_About
from ui_connect_obs import Ui_Dialog as Ui_ConnectObs
from ui_url_source import Ui_Dialog as Ui_UrlSource
from ui_screen_capture import Ui_Dialog as Ui_ScreenCapture
from vmix_ui_handler import VMixUIHanlder

DEFAULT_HTTP_PORT = 18099

# File > Appearance choices, persisted as the "color_scheme" setting
COLOR_SCHEMES = {
    "System": Qt.ColorScheme.Unknown,
    "Light": Qt.ColorScheme.Light,
    "Dark": Qt.ColorScheme.Dark,
}
DEFAULT_COLOR_SCHEME = "System"

# comboBox_camera_source items before the discovered cameras
SOURCE_INDEX_NONE = 0
SOURCE_INDEX_FILE = 1
SOURCE_INDEX_URL = 2
SOURCE_INDEX_SCREEN_CAPTURE = 3
SOURCE_INDEX_PHONE = 4
FIRST_CAMERA_SOURCE_INDEX = 5
# the items that open a chooser (a file dialog, the URL or the window)
CHOOSER_SOURCE_INDEXES = (
    SOURCE_INDEX_FILE,
    SOURCE_INDEX_URL,
    SOURCE_INDEX_SCREEN_CAPTURE,
)

# Box edits are written to the settings this long after the last change.
BOXES_SAVE_DELAY_MS = 500

# The data of the OCR model list's "Load external Tesseract model..." item
LOAD_EXTERNAL_MODEL = "load-external-model"
# PP-OCR (accurate) can't keep up for this many status updates (seconds) in a
# row: the hint suggesting PP-OCR (fast) or fewer detections is shown, once
PPOCR_CPU_HINT_AFTER_UPDATES = 5
# whether that hint was shown (it is shown only once, ever)
PPOCR_CPU_HINT_SETTING = "ppocr_cpu_hint_shown"

# File > Language: (locale, the language's name in that language)
LANGUAGES = (
    ("en_US", "English (US)"),
    ("fr_FR", "Français"),
    ("es_ES", "Español"),
    ("de_DE", "Deutsch"),
    ("it_IT", "Italiano"),
    ("ja_JP", "日本語"),
    ("ko_KR", "한국어"),
    ("nl_NL", "Nederlands"),
    ("pl_PL", "Polski"),
    ("pt_BR", "Português (Brasil)"),
    ("pt_PT", "Português (Portugal)"),
    ("ru_RU", "Русский"),
    ("zh_CN", "简体中文"),
)

# The widths of the Fields | viewer | Inspector panes ([fields, viewer,
# inspector]; 0 = hidden), and of the two-pane layout before them (the
# QSplitter.saveState of the boxes list | viewer splitter), which is dropped.
PANE_SIZES_SETTING = "main_splitter_sizes"
OLD_SPLITTER_STATE_SETTING = "main_splitter_state"
# The panes' default and minimum widths (pixels)
FIELDS_PANE_WIDTH = 260
INSPECTOR_WIDTH = 340
VIEWER_MIN_WIDTH = 360
# The status bar, the readings' ages and the paused time are refreshed this often.
STATUS_INTERVAL_MS = 1000
# View > Statistics overlay (camera_view reads it too)
SHOW_OSD_SETTING = "show_osd"
# Tools > Collect OCR training data (ocr_training_data reads it too)
COLLECT_TRAINING_DATA_SETTING = "save_ocr_training_data"
# File > Ask before closing (while a source is open)
ASK_BEFORE_CLOSING_SETTING = "ask_before_closing"
# The boxes list is at least this many rows tall (it gets the pane's height).
BOXES_LIST_MIN_ROWS = 3
# The outputs list is at least this many rows tall (it scrolls when shorter).
DESTINATIONS_LIST_MIN_ROWS = 2
# The window's default size, made smaller on smaller screens.
DEFAULT_WINDOW_SIZE = (1280, 800)
# False after OBS was disconnected: the saved connection ("obs") isn't opened
# at startup until the user connects again
OBS_AUTO_CONNECT_SETTING = "obs_auto_connect"
# View > Setup layout / Live layout: two arrangements of the same widgets
LAYOUT_SETTING = "window_layout"
LAYOUT_SETUP = "setup"
LAYOUT_LIVE = "live"
# The Fields pane's width in the Live layout (the setting keeps the user's;
# the Setup layout's widths are PANE_SIZES_SETTING)
LIVE_FIELDS_WIDTH = 400
LIVE_FIELDS_WIDTH_SETTING = "live_fields_width"
# View > Show unused fields (the fields not on the picture), for each layout
SHOW_UNUSED_SETTINGS = {
    LAYOUT_SETUP: "show_unused_fields_setup",
    LAYOUT_LIVE: "show_unused_fields_live",
}
SHOW_UNUSED_DEFAULTS = {LAYOUT_SETUP: True, LAYOUT_LIVE: False}
# Help > User guide
USER_GUIDE_URL = source_bar.DOCS_URL
# the status bar's Feedback and Help > Ask a question or share feedback
COMMUNITY_URL = source_bar.COMMUNITY_URL


def apply_color_scheme(name: str | None) -> str:
    """Apply a File > Appearance choice ("System", "Light" or "Dark") to the
    running application and return the choice applied. Unknown values mean
    "System" (follow the operating system)."""
    if name not in COLOR_SCHEMES:
        name = DEFAULT_COLOR_SCHEME
    style_hints = QGuiApplication.styleHints()
    if name == DEFAULT_COLOR_SCHEME:
        style_hints.unsetColorScheme()
    else:
        style_hints.setColorScheme(COLOR_SCHEMES[name])
    return name


def alt_key_name() -> str:
    """The Alt key's name, as written on the keyboard: Option on a Mac."""
    if platform.system() == "Darwin":
        return QCoreApplication.translate("MainWindow", "⌥ Option")
    return QCoreApplication.translate("MainWindow", "Alt")


def run_in_background(name: str, function: Callable, on_done: Callable):
    """Run function() on a daemon thread, then on_done(result) on that thread.

    on_done should emit a signal of a QObject that lives in the GUI thread: the
    signal is then delivered there (queued), so the result is handled on the GUI
    thread. If function raises, on_done gets None.
    """

    def target():
        try:
            result = function()
        except Exception:
            logger.exception("%s failed", name)
            result = None
        try:
            on_done(result)
        except RuntimeError:
            # the receiving window was destroyed while the call was running
            logger.debug("%s finished after its window was closed", name)

    thread = threading.Thread(target=target, name=name, daemon=True)
    thread.start()
    return thread


def stored_source_value(stored) -> dict | None:
    """Normalize the "source_selected" setting to {"type", "value", ...}.

    0.1.x stored a bare file path or URL (and nothing for cameras)."""
    if isinstance(stored, dict) and stored.get("type"):
        return stored
    if isinstance(stored, str) and stored.strip():
        stored = stored.strip()
        if path.exists(stored):
            return {"type": CameraInfo.CameraType.FILE, "value": stored}
        if "://" in stored:
            return {"type": CameraInfo.CameraType.URL, "value": stored}
    return None


class MainWindow(QMainWindow):
    # add a signal to update sources
    update_sources = Signal(list)
    get_sources = Signal()
    # results of the work done on background threads, delivered on the GUI thread
    obs_connection_result = Signal(object, int, bool, object)
    update_check_finished = Signal(object, bool)

    def __init__(
        self,
        translator: QTranslator,
        parent: QObject,
        http_port: int = DEFAULT_HTTP_PORT,
    ):
        super(MainWindow, self).__init__()
        self.parent_object = parent
        self.http_port = http_port
        self.ui = Ui_MainWindow()
        logger.info("Starting ScoreSight %s", __version__)
        self.ui.setupUi(self)
        # the HTTP server page's text, before the real port and address are
        # filled in
        self.browserEndpointsTemplate = self.ui.label_8.text()
        # this computer's address on the network (for the HTTP server's URLs)
        self.lanAddress = primary_lan_address()
        self.lanAddressCheckedAt = time.monotonic()
        self.translator = translator
        # when the outputs were paused (Pause outputs), None while they run
        self.outputsPausedAt: datetime | None = None
        self.outputsPausedMonotonic: float | None = None
        # After the outputs are resumed, vMix and UNO get each of these boxes'
        # next good reading, even an unchanged one (they normally send only
        # changed values)
        self.resendAfterPause: set[str] = set()
        # Hold value: the fields whose outputs get a value typed by the user
        # instead of their readings (not saved)
        self.heldValues = HeldValues()
        # the game, for the sport chosen (game_state.py; None: nothing)
        self.gameEngine = GameEngine()
        # a change the sport doesn't allow goes out once the game counts it
        self.plausibilityHolds = PlausibilityHolds()
        # View > Setup layout or Live layout (applied by setupLayout)
        self.layoutMode = LAYOUT_SETUP
        self.updateWindowTitle()
        if platform.system() != "Darwin":
            # the window's icon (a Mac app shows its bundle's)
            self.setWindowIcon(QIcon(resource_path("icons", "scoresight.ico")))

        self.update_check_running = False
        # a manual check was asked for while another check was running
        self.update_check_manual_pending = False
        self.update_dialog = None
        self.update_check_finished.connect(self.updateCheckFinished)
        # Update now (installed on Windows)
        self.appUpdater = AppUpdater(self)
        if self.appUpdater.available():
            # what an earlier Update now downloaded (the new version runs now)
            run_in_background(
                "removing update downloads", app_update.remove_downloads, lambda _: None
            )
        self.setupMenus()

        # handle the Escape key (deselect the current box)
        self.installEventFilter(self)

        self.ui.pushButton_connectObs.clicked.connect(self.openOBSConnectModal)
        self.ui.pushButton_disconnectObs.clicked.connect(self.disconnectObs)

        self.vmixUiHandler = VMixUIHanlder(self.ui)
        self.unoUiHandler = UNOUIHandler(self.ui)
        # the TCP / UDP output's page is the last of the output pages
        self.tcpUiHandler = TcpUIHandler(self.ui.stackedWidget_outputs, self)
        # the Sport choice and the game's status line (All boxes)
        self.gameUiHandler = GameUIHandler(self.ui, self.gameEngine)
        # the start/stop buttons show the same texts from the start as after a
        # toggle or a language change
        self.vmixUiHandler.restoreUiState()
        self.unoUiHandler.restoreUiState()
        self.boxSettingsUiHandler = BoxSettingsUIHandler(self.ui)

        self.ui.checkBox_templatefield.toggled.connect(self.makeTemplateField)

        start_http_server(port=self.http_port)
        # the browser overlays' URL builder on the HTTP server's page
        self.overlayBuilder = OverlayBuilder(
            self.ui, self.overlayFieldNames, self.overlayBaseUrls
        )
        self.updateBrowserEndpoints()

        self.ui.pushButton_stabilize.setEnabled(True)
        self.ui.pushButton_stabilize.clicked.connect(self.toggleStabilize)

        self.ui.toolButton_topCrop.clicked.connect(self.cropMode)
        # check configuation if crop is enabled
        self.ui.toolButton_topCrop.setChecked(
            fetch_data("scoresight.json", "crop_mode", False)
        )
        self.ui.widget_cropPanel.setVisible(self.ui.toolButton_topCrop.isChecked())
        self.ui.widget_cropPanel.setEnabled(self.ui.toolButton_topCrop.isChecked())
        # The crop's top-left corner in the rotated frame ((0, 0) while the
        # crop is off): the boxes move with it, so that they stay on the same
        # part of the picture. None until the values are shown.
        self.cropOrigin: tuple[int, int] | None = None
        for spin_box, setting in (
            (self.ui.spinBox_leftCrop, "left_crop"),
            (self.ui.spinBox_rightCrop, "right_crop"),
            (self.ui.spinBox_topCrop, "top_crop"),
            (self.ui.spinBox_bottomCrop, "bottom_crop"),
        ):
            spin_box.valueChanged.connect(partial(self.cropValueChanged, setting))
            spin_box.setValue(fetch_data("scoresight.json", setting, 0))
        self.cropOrigin = self.currentCropOrigin()
        self.ui.toolButton_resetCrop.setEnabled(any(self.cropValues()))
        self.ui.checkBox_enableOutAPI.toggled.connect(
            partial(self.globalSettingsChanged, "enable_out_api")
        )
        self.ui.checkBox_enableOutAPI.setChecked(
            fetch_data("scoresight.json", "enable_out_api", False)
        )

        # connect toolButton_rotate
        self.ui.toolButton_rotate.clicked.connect(self.rotateImage)

        self.ui.horizontalSlider_detectionCadence.setValue(
            fetch_data("scoresight.json", "detection_cadence", 5)
        )
        self.ui.horizontalSlider_detectionCadence.valueChanged.connect(
            self.detectionCadenceChanged
        )
        self.ui.toolButton_addBox.clicked.connect(self.addBox)
        self.ui.toolButton_removeBox.clicked.connect(self.deleteField)

        self.video_settings_dialog = None
        self.ui.toolButton_videoSettings.clicked.connect(self.openVideoSettings)

        self.ui.lineEdit_api_url.textChanged.connect(
            partial(self.globalSettingsChanged, "out_api_url")
        )
        self.ui.lineEdit_api_url.setText(
            fetch_data("scoresight.json", "out_api_url", "")
        )

        self.setupChoiceSetting(
            self.ui.comboBox_api_encode, "out_api_encoding", OUT_API_ENCODINGS
        )
        self.setupChoiceSetting(
            self.ui.comboBox_outApiMethod, "out_api_method", OUT_API_METHODS
        )
        # the API page's other options and its presets
        self.apiUiHandler = APIUIHandler(self.ui)

        self.obs_websocket_client = None
        # the text last sent to each OBS text source
        self.obs_last_sent: dict[str, str] = {}
        self.obs_connect_attempt = 0
        self.obs_connection_result.connect(self.obsConnectionResult)
        # for the OBS status: "host:port" of the connection, of an attempt
        # running, and why the last attempt failed
        self.obsAddress: str | None = None
        self.obsConnectedAt: float | None = None
        self.obsConnecting: str | None = None
        self.obsConnectError: ErrorInfo | None = None
        self.obsConnectTarget: str | None = None

        # PP-OCR (accurate) can't keep up: consecutive slow status updates, and
        # the hint about it (shown once, ever)
        self.ppocrSlowUpdates = 0
        self.ppocrCpuHint: QMessageBox | None = None
        self.ppocrCpuHintShown = False
        # the model PP-OCR (automatic) reads with, as the list shows it
        self.ocrAutoModel: str | None = None
        self.setupOcrModelChoices()

        self.ui.frame_source_view.setEnabled(False)
        self.ui.pushButton_makeBox.clicked.connect(self.placeOnPicture)
        self.ui.pushButton_removeBox.clicked.connect(self.removeFromPicture)
        self.ui.tableWidget_boxes.itemClicked.connect(self.listItemClicked)
        # a field without a box gets one, another one is renamed
        self.ui.tableWidget_boxes.itemDoubleClicked.connect(self.fieldDoubleClicked)
        # the current item is always a box's name: the box settings, removing
        # and renaming use its text
        self.ui.tableWidget_boxes.currentCellChanged.connect(self.keepNameCellCurrent)
        self.setupBoxesList()
        self.ui.pushButton_refresh_sources.clicked.connect(
            lambda: self.get_sources.emit()
        )
        self.detectionTargetsStorage = TextDetectionTargetMemoryStorage()
        # the OBS page's table: the OBS text source of each field, editable
        self.obsSourcesTable = OBSSourcesTable(
            self.ui.tableView_obsSources, self.detectionTargetsStorage
        )
        # what Create OBS Scene did last: (outcome, scene name)
        self.obsSceneOutcome: tuple[str, str] | None = None
        self.detectionTargetsStorage.data_changed.connect(self.detectionTargetsChanged)
        # Box edits (settings panel, add/remove, rename, template fields) are
        # persisted shortly after they happen, not only on a click in the viewer.
        self.boxesSaveTimer = QTimer(self)
        self.boxesSaveTimer.setSingleShot(True)
        self.boxesSaveTimer.setInterval(BOXES_SAVE_DELAY_MS)
        self.boxesSaveTimer.timeout.connect(self.saveBoxes)
        self.ui.pushButton_createOBSScene.clicked.connect(self.createOBSScene)
        self.ui.pushButton_selectFolder.clicked.connect(self.selectOutputFolder)
        self.ui.toolButton_trashFolder.clicked.connect(self.clearOutputFolder)
        self.ui.pushButton_stopUpdates.toggled.connect(self.toggleStopUpdates)
        self.ui.comboBox_boxDisplayStyle.currentIndexChanged.connect(
            partial(self.globalSettingsChanged, "box_display_style")
        )
        box_display_style = fetch_data("scoresight.json", "box_display_style", 3)
        self.ui.comboBox_boxDisplayStyle.setCurrentIndex(
            box_display_style if isinstance(box_display_style, int) else 3
        )

        self.ui.checkBox_updateOnchange.toggled.connect(self.toggleUpdateOnChange)

        # populate the tableWidget_boxes with the default and custom boxes
        custom_boxes_names = fetch_custom_box_names()

        for box_name in [box["name"] for box in default_boxes] + custom_boxes_names:
            self.setFieldPlacement(self.appendBoxRow(box_name), NOT_PLACED)

        # The boxes are app state (not per source): load them once at startup.
        # From now on the in-memory storage is the source of truth, and changes
        # are written back by saveBoxes.
        self.detectionTargetsStorage.loadBoxesFromStorage()
        self.detectionTargetsStorage.data_changed.connect(self.scheduleBoxesSave)

        self.image_viewer = None
        self.connected_viewer = None
        self.obs_connect_modal = None
        self.source_name = None
        # the title of the window a screen capture shows
        self.sourceWindowTitle: str | None = None
        self.sources_discovery_running = False
        self.closing = False
        # set by a quit signal and Update now: close without asking first
        self.close_without_asking = False
        self.updateOCRResults = True
        self.log_dialog = None
        if fetch_data("scoresight.json", "open_on_startup", False):
            logger.info("Opening log dialog on startup")
            self.openLogsDialog()

        if fetch_data("scoresight.json", "obs") and fetch_data(
            "scoresight.json", OBS_AUTO_CONNECT_SETTING, True
        ):
            self.connectObs()

        # the output folder that was found missing (the files output stopped)
        self.outputFolderLost: str | None = None
        self.out_folder = fetch_data("scoresight.json", "output_folder")
        if self.out_folder:
            if not path.exists(self.out_folder):
                logger.warning("Output folder does not exist: %s", self.out_folder)
                self.outputFolderLost = self.out_folder
                self.out_folder = None
                remove_data("scoresight.json", "output_folder")
            else:
                self.ui.lineEdit_folder.setText(self.out_folder)

        # .txt/.csv/.xml outputs; flushed at most "Save / s" times per second
        self.fileOutput = file_output.FileOutput()
        self.fileOutputTimer = QTimer(self)
        self.fileOutputTimer.setSingleShot(True)
        self.fileOutputTimer.timeout.connect(self.flushFileOutputs)
        self.ui.checkBox_saveCsv.toggled.connect(
            partial(self.globalSettingsChanged, "save_csv")
        )
        self.ui.checkBox_saveCsv.setChecked(
            fetch_data("scoresight.json", "save_csv", False)
        )
        self.ui.checkBox_saveXML.toggled.connect(
            partial(self.globalSettingsChanged, "save_xml")
        )
        self.ui.checkBox_saveXML.setChecked(
            fetch_data("scoresight.json", "save_xml", False)
        )
        for checkbox, setting in (
            (self.ui.checkBox_saveJson, "save_json"),
            (self.ui.checkBox_saveKeyValue, "save_key_value"),
        ):
            checkbox.toggled.connect(partial(self.globalSettingsChanged, setting))
            checkbox.setChecked(fetch_data("scoresight.json", setting, False))
        self.ui.comboBox_appendMethod.currentIndexChanged.connect(
            partial(self.globalSettingsChanged, "append_method")
        )
        self.ui.horizontalSlider_aggsPerSecond.valueChanged.connect(
            partial(self.globalSettingsChanged, "aggs_per_second")
        )
        self.ui.comboBox_appendMethod.setCurrentIndex(
            fetch_data("scoresight.json", "append_method", 3)
        )
        self.ui.horizontalSlider_aggsPerSecond.setValue(
            fetch_data("scoresight.json", "aggs_per_second", 5)
        )
        self.ui.checkBox_updateOnchange.setChecked(
            fetch_data("scoresight.json", "update_on_change", True)
        )
        self.ui.checkBox_vmix_send_same.setChecked(
            fetch_data("scoresight.json", "vmix_send_same", False)
        )
        self.ui.checkBox_vmix_send_same.toggled.connect(
            partial(self.globalSettingsChanged, "vmix_send_same")
        )

        # Pause outputs: the banner over the viewer, the status bar chip
        self.ui.frame_pausedBanner.hide()
        self.ui.pushButton_resumeOutputs.clicked.connect(
            lambda: self.ui.pushButton_stopUpdates.setChecked(False)
        )
        self.ui.horizontalSlider_detectionCadence.valueChanged.connect(
            self.updateSliderReadouts
        )
        self.ui.horizontalSlider_aggsPerSecond.valueChanged.connect(
            self.updateSliderReadouts
        )

        # the outputs' list (with their status) over their settings pages
        self.setupDestinations()

        # the source, OCR rate, the outputs and the HTTP address, and the
        # readings' ages
        self.sourceError = None
        self.statusBarWidgets = MainStatusBar(self.ui.statusbar)
        self.statusBarWidgets.destination_clicked.connect(self.showDestination)
        self.statusBarWidgets.feedback_clicked.connect(self.openCommunity)
        self.statusTimer = QTimer(self)
        self.statusTimer.setInterval(STATUS_INTERVAL_MS)
        self.statusTimer.timeout.connect(self.refreshLiveStatus)
        self.statusTimer.start()

        # the source bar, view tools, picture adjustments, banners and the
        # first-run card around the picture
        self.setupViewer()
        # "Open a source to place fields" while the fields list is disabled
        self.ui.groupBox_sb_info.installEventFilter(self)

        self.styleLabels()
        self.setupLayout()
        self.applyRuntimeTexts()

        self.update_sources.connect(self.updateSources)
        self.get_sources.connect(self.getSources)
        self.get_sources.emit()

        self.checkForUpdates(False)

    # --- layout, menus and texts set at runtime ---------------------------------

    def setupMenus(self):
        """Connect the menus' actions (defined in the .ui, so they are
        translated), fill the Language and Appearance submenus, and add the
        window's keyboard shortcuts."""
        ui = self.ui
        # File
        ui.actionImportConfiguration.triggered.connect(self.importConfiguration)
        ui.actionExportConfiguration.triggered.connect(self.exportConfiguration)
        ui.actionOpenConfigurationFolder.triggered.connect(self.openConfigurationFolder)
        ui.actionAskBeforeClosing.setChecked(
            fetch_data("scoresight.json", ASK_BEFORE_CLOSING_SETTING, True) is not False
        )
        ui.actionAskBeforeClosing.toggled.connect(
            lambda checked: self.globalSettingsChanged(
                ASK_BEFORE_CLOSING_SETTING, bool(checked)
            )
        )
        ui.actionQuit.triggered.connect(self.close)
        # Tools
        ui.actionOCRTrainingDataSetup.triggered.connect(self.openOCRTrainingDataDialog)
        ui.actionViewLog.triggered.connect(self.openLogsDialog)
        # Help
        ui.actionUserGuide.triggered.connect(self.openUserGuide)
        ui.actionKeyboardShortcuts.triggered.connect(self.showKeyboardShortcuts)
        ui.actionCommunity.triggered.connect(self.openCommunity)
        ui.actionCheckForUpdates.triggered.connect(lambda: self.checkForUpdates(True))
        ui.actionAbout.triggered.connect(self.openAboutDialog)
        # the selected field's held value
        ui.actionHoldValue.triggered.connect(self.holdValue)
        ui.actionReleaseValue.triggered.connect(lambda: self.releaseValue())
        if platform.system() == "Darwin":
            # ⌘H hides the application on macOS: ⌃H (the Control key) instead
            ui.actionHoldValue.setShortcut(QKeySequence("Meta+H"))

        # View > Language, each language in its own language
        self.language_actions = QActionGroup(self)
        self.language_actions.setExclusive(True)
        current_locale = self.currentLocale()
        for locale, name in LANGUAGES:
            action = ui.menuLanguage.addAction(name)
            action.setCheckable(True)
            action.setChecked(locale == current_locale)
            action.setData(locale)
            action.triggered.connect(
                lambda checked=False, locale=locale: self.changeLanguage(locale)
            )
            self.language_actions.addAction(action)

        # View > Appearance: System / Light / Dark color scheme (#50)
        self.appearance_actions = QActionGroup(self)
        self.appearance_actions.setExclusive(True)
        current_scheme = fetch_data("scoresight.json", "color_scheme")
        if current_scheme not in COLOR_SCHEMES:
            current_scheme = DEFAULT_COLOR_SCHEME
        for scheme in COLOR_SCHEMES:
            action = ui.menuAppearance.addAction(scheme)
            action.setCheckable(True)
            action.setChecked(scheme == current_scheme)
            action.setData(scheme)
            action.triggered.connect(
                lambda checked=False, scheme=scheme: self.setColorScheme(scheme)
            )
            self.appearance_actions.addAction(action)

        # shortcuts of the window (they also work while the menu bar is
        # hidden, e.g. with the macOS global menu bar)
        ui.actionZoomIn.setShortcuts(
            [QKeySequence("Ctrl+="), QKeySequence(QKeySequence.StandardKey.ZoomIn)]
        )
        for action in (
            ui.actionPauseOutputs,
            ui.actionBinaryView,
            ui.actionFitPicture,
            ui.actionZoomIn,
            ui.actionZoomOut,
            ui.actionReloadSources,
            ui.actionNewField,
            ui.actionSetupLayout,
            ui.actionLiveLayout,
            ui.actionHoldValue,
            ui.actionImportConfiguration,
            ui.actionExportConfiguration,
            ui.actionViewLog,
            ui.actionUserGuide,
            ui.actionQuit,
        ):
            action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
            self.addAction(action)
        ui.actionPauseOutputs.triggered.connect(ui.pushButton_stopUpdates.toggle)
        ui.pushButton_stopUpdates.toggled.connect(ui.actionPauseOutputs.setChecked)
        ui.actionNewField.triggered.connect(self.addBox)
        # through the buttons: they do nothing while disabled (no source yet, a
        # reload running)
        ui.actionBinaryView.triggered.connect(self.triggerBinaryView)
        ui.pushButton_binary.toggled.connect(ui.actionBinaryView.setChecked)
        ui.actionFitPicture.triggered.connect(ui.toolButton_zoomReset.click)
        ui.actionReloadSources.triggered.connect(ui.pushButton_refresh_sources.click)

    def currentLocale(self) -> str | None:
        """The locale of the loaded translation (e.g. "de_DE"), if any."""
        loaded = path.basename(self.translator.filePath() or "")
        if loaded.startswith("scoresight_") and loaded.endswith(".qm"):
            return loaded[len("scoresight_") : -len(".qm")]
        return None

    def setupBoxesList(self):
        """The boxes list: names, and the readings drawn by ReadingDelegate; a
        context menu and keys for the selected field."""
        table = self.ui.tableWidget_boxes
        self.readingDelegate = ReadingDelegate(table)
        table.setItemDelegateForColumn(1, self.readingDelegate)
        # a held value's Release button
        self.readingDelegate.releaseRequested.connect(self.releaseValue)
        header = table.verticalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.updateBoxesListHeight()
        # the names' column fits the names in the Live layout
        table.viewport().installEventFilter(self)
        self.setupNameColumnWidth = table.columnWidth(0)
        # "Unused fields hidden: 3. Show them"
        self.ui.label_hiddenFields.hide()
        self.ui.label_hiddenFields.setTextFormat(Qt.TextFormat.RichText)
        self.ui.label_hiddenFields.linkActivated.connect(
            lambda _link: self.ui.actionShowUnusedFields.setChecked(True)
        )

        ui = self.ui
        # the Box tab and the field's actions follow the selection, however it
        # changes (a click, the arrow keys, typing a name)
        table.itemSelectionChanged.connect(self.fieldSelectionChanged)
        table.customContextMenuRequested.connect(self.showFieldContextMenu)
        # F2, Del and Ctrl+C act on the selected field while the list has the
        # focus (Ctrl+C elsewhere copies as usual). Del takes the field's box
        # off the picture, or deletes a custom field that has none: the key
        # goes to one of the two actions (see updateFieldActions).
        for action in (
            ui.actionRenameField,
            ui.actionRemoveFromPicture,
            ui.actionDeleteField,
            ui.actionCopyValue,
        ):
            action.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
            table.addAction(action)
        self.deleteKeys = [QKeySequence("Del")]
        if platform.system() == "Darwin":
            # the key labelled "delete" on a Mac keyboard is Backspace
            self.deleteKeys.append(QKeySequence("Backspace"))
        ui.actionDeleteField.setShortcuts(self.deleteKeys)
        # the footer's Place on picture and Remove from picture are there for
        # the keyboard: quieter than the field list, whose drag and
        # double-click come first (the hint above them says so)
        for button in (ui.pushButton_makeBox, ui.pushButton_removeBox):
            button.setFlat(True)
        # the list takes Ctrl+C itself (it copies the current item: the field's
        # name), before the shortcut: see eventFilter
        table.installEventFilter(self)
        ui.actionPlaceOnPicture.triggered.connect(self.placeOnPicture)
        ui.actionRemoveFromPicture.triggered.connect(self.removeFromPicture)
        ui.actionRenameField.triggered.connect(self.renameField)
        ui.actionDeleteField.triggered.connect(self.deleteField)
        ui.actionResetFieldSettings.triggered.connect(
            self.boxSettingsUiHandler.restoreDefaults
        )
        ui.actionCopyValue.triggered.connect(self.copyFieldValue)
        ui.actionZoomToBox.triggered.connect(self.zoomToBox)

    def updateBoxesListHeight(self, *_):
        """Size the rows for the readings. The list gets the Fields pane's
        height; it is at least BOXES_LIST_MIN_ROWS rows tall."""
        table = self.ui.tableWidget_boxes
        row_height = self.readingDelegate.rowHeight(table.font())
        rows = table.verticalHeader()
        rows.setDefaultSectionSize(row_height)
        # a hidden row (an unused field in the Live layout) keeps the height it
        # had when it was hidden, and gets it back when shown: give it the new
        # one (resizeSection sets a hidden section's remembered size)
        for row in range(table.rowCount()):
            if rows.sectionSize(row) != row_height or table.isRowHidden(row):
                rows.resizeSection(row, row_height)
        header = table.horizontalHeader()
        header_height = 0 if header.isHidden() else header.sizeHint().height()
        table.setMinimumHeight(
            header_height + BOXES_LIST_MIN_ROWS * row_height + 2 * table.frameWidth()
        )

    def styleLabels(self):
        """The hint labels (the "hint" property in the .ui) in a muted, smaller
        type, and the selected field's name large. Colours from the palette, so
        they follow File > Appearance."""
        for label in self.findChildren(QLabel):
            if label.property("hint"):
                label.setForegroundRole(QPalette.ColorRole.PlaceholderText)
                font = QFont(label.font())
                if font.pointSizeF() > 0:
                    font.setPointSizeF(max(7.0, font.pointSizeF() * 0.9))
                label.setFont(font)
        name = self.ui.label_selectedInfo
        font = QFont(name.font())
        if font.pointSizeF() > 0:
            font.setPointSizeF(font.pointSizeF() * 1.35)
        font.setBold(True)
        name.setFont(font)

    def setupLayout(self):
        """The three panes: Fields | viewer | Inspector. Fit the window to the
        screen and restore the panes' widths (the side panes can be hidden:
        dragged to the edge, or with a double-click on their divider)."""
        splitter = self.ui.splitter_main
        for index, (stretch, collapsible) in enumerate(
            ((0, True), (1, False), (0, True))
        ):
            splitter.setStretchFactor(index, stretch)
            splitter.setCollapsible(index, collapsible)
        # The viewer column's toolbars are wider than this; it may be made
        # narrower anyway (they are then cut off), so that the three panes fit a
        # small screen.
        self.ui.frame_source_view.setMinimumWidth(VIEWER_MIN_WIDTH)
        for index in (1, 2):
            splitter.handle(index).installEventFilter(self)
        self.ui.scrollAreaWidgetContents_boxSettings.installEventFilter(self)
        # the size of a pane before it was hidden, to show it again at that size
        self.paneSizesBeforeHiding = {0: FIELDS_PANE_WIDTH, 2: INSPECTOR_WIDTH}

        screen = self.screen()
        width, height = DEFAULT_WINDOW_SIZE
        if screen is not None:
            available = screen.availableGeometry()
            # leave room for the title bar and the window frame
            width = min(width, available.width() - 16)
            height = min(height, available.height() - 48)
        self.resize(width, height)

        self.restoreSetupPaneSizes()
        # the two-pane layout before the Inspector
        if fetch_data("scoresight.json", OLD_SPLITTER_STATE_SETTING) is not None:
            remove_data("scoresight.json", OLD_SPLITTER_STATE_SETTING)
        self.splitterSaveTimer = QTimer(self)
        self.splitterSaveTimer.setSingleShot(True)
        self.splitterSaveTimer.setInterval(BOXES_SAVE_DELAY_MS)
        self.splitterSaveTimer.timeout.connect(self.saveSplitterState)
        splitter.splitterMoved.connect(lambda *_: self.splitterSaveTimer.start())
        self.setupLayoutModes()

    def restoreSetupPaneSizes(self):
        """The Setup layout's pane widths: the stored ones, or the defaults
        for the window's width."""
        splitter = self.ui.splitter_main
        stored = fetch_data("scoresight.json", PANE_SIZES_SETTING)
        if (
            isinstance(stored, list)
            and len(stored) == 3
            and all(isinstance(size, int) and size >= 0 for size in stored)
            and stored[1] > 0
        ):
            splitter.setSizes(stored)
            for index in (0, 2):
                if stored[index] > 0:
                    self.paneSizesBeforeHiding[index] = stored[index]
        else:
            splitter.setSizes(self.defaultPaneSizes(self.width()))

    def defaultPaneSizes(self, window_width: int) -> list[int]:
        """[fields, viewer, inspector] for a window this wide: the side panes'
        default widths, made narrower (down to their minimum) when the viewer
        would get less than its toolbars need."""
        splitter = self.ui.splitter_main
        margins = self.ui.centralwidget.layout().contentsMargins()
        total = (
            window_width - margins.left() - margins.right() - 2 * splitter.handleWidth()
        )
        fields = FIELDS_PANE_WIDTH
        inspector = max(
            INSPECTOR_WIDTH, self.ui.tabWidget_inspector.minimumSizeHint().width()
        )
        # what the viewer's toolbars need, beyond what it gets
        missing = self.ui.frame_source_view.minimumSizeHint().width() - (
            total - fields - inspector
        )
        # taken from the Inspector first, then from the Fields pane
        spare = inspector - self.ui.tabWidget_inspector.minimumSizeHint().width()
        taken = max(0, min(missing, spare))
        inspector -= taken
        missing -= taken
        spare = fields - self.ui.widget_leftPane.minimumSizeHint().width()
        fields -= max(0, min(missing, spare))
        return [fields, max(VIEWER_MIN_WIDTH, total - fields - inspector), inspector]

    def saveSplitterState(self):
        """Remember the panes' widths: in the Setup layout all of them, in the
        Live layout the Fields pane's width (the Setup layout's widths are
        kept for when it is chosen again)."""
        self.splitterSaveTimer.stop()
        if not self.ui.splitter_main.isVisible():
            # not laid out yet: its sizes mean nothing
            return
        sizes = self.ui.splitter_main.sizes()
        if self.layoutMode == LAYOUT_LIVE:
            if sizes[0] > 0 and (
                fetch_data("scoresight.json", LIVE_FIELDS_WIDTH_SETTING) != sizes[0]
            ):
                self.globalSettingsChanged(LIVE_FIELDS_WIDTH_SETTING, sizes[0])
            return
        if fetch_data("scoresight.json", PANE_SIZES_SETTING) != sizes:
            self.globalSettingsChanged(PANE_SIZES_SETTING, sizes)

    def isPaneHidden(self, index: int) -> bool:
        return self.ui.splitter_main.sizes()[index] == 0

    def setPaneHidden(self, index: int, hidden: bool):
        """Hide (collapse) or show the Fields pane (0) or the Inspector (2); the
        viewer gets or gives the room."""
        splitter = self.ui.splitter_main
        sizes = splitter.sizes()
        if hidden == (sizes[index] == 0):
            return
        if hidden:
            if splitter.isVisible():
                self.paneSizesBeforeHiding[index] = sizes[index]
            sizes[1] += sizes[index]
            sizes[index] = 0
        else:
            size = self.paneSizesBeforeHiding.get(index) or (
                FIELDS_PANE_WIDTH if index == 0 else INSPECTOR_WIDTH
            )
            sizes[index] = size
            sizes[1] = max(VIEWER_MIN_WIDTH, sizes[1] - size)
        splitter.setSizes(sizes)
        self.saveSplitterState()

    # --- View > Setup layout / Live layout ----------------------------------------

    def setupLayoutModes(self):
        """The Setup and Live layouts (View menu, Ctrl+1 and Ctrl+2): the same
        widgets, arranged for setting up or for the game. The OCR and the
        outputs work the same in both. The layout chosen is remembered."""
        ui = self.ui
        group = QActionGroup(self)
        group.setExclusive(True)
        for action in (ui.actionSetupLayout, ui.actionLiveLayout):
            group.addAction(action)
        ui.actionSetupLayout.triggered.connect(lambda: self.setLayoutMode(LAYOUT_SETUP))
        ui.actionLiveLayout.triggered.connect(lambda: self.setLayoutMode(LAYOUT_LIVE))
        ui.actionShowUnusedFields.toggled.connect(self.showUnusedFieldsToggled)
        stored = fetch_data("scoresight.json", LAYOUT_SETTING, LAYOUT_SETUP)
        if stored == LAYOUT_LIVE:
            self.setLayoutMode(LAYOUT_LIVE, store=False)
        else:
            self.applyLayoutUi()

    def setLayoutMode(self, mode: str, store: bool = True):
        """Arrange the window for LAYOUT_SETUP or LAYOUT_LIVE.

        Live: the Inspector is hidden, the field list is about 400 pixels wide
        with the readings large, the fields not on the picture are hidden (View
        > Show unused fields), the outputs' list is under the readings, and the
        Adjust picture row is hidden. Setup restores the panes' widths."""
        if mode not in (LAYOUT_SETUP, LAYOUT_LIVE):
            mode = LAYOUT_SETUP
        changed = mode != self.layoutMode
        if changed:
            # the widths of the layout left (the Setup ones are restored later)
            self.saveSplitterState()
            self.layoutMode = mode
            viewer = getattr(self, "image_viewer", None)
            if mode == LAYOUT_LIVE and viewer is not None:
                if viewer.fourCornerSelectionMode:
                    # the Adjust picture row is hidden: stop picking corners
                    self.cancelFourCornerSelection()
                if viewer.cropSelectionMode:
                    # (and the crop panel)
                    self.cancelCropSelection()
            logger.info("%s layout", "Live" if mode == LAYOUT_LIVE else "Setup")
        if store and fetch_data("scoresight.json", LAYOUT_SETTING) != mode:
            self.globalSettingsChanged(LAYOUT_SETTING, mode)
        # the widgets first: the panes' minimum widths depend on them
        self.applyLayoutUi()
        if changed:
            if mode == LAYOUT_LIVE:
                self.applyLivePaneSizes()
            else:
                self.restoreSetupPaneSizes()

    def splitterTotalWidth(self) -> int:
        """The width the three panes share."""
        splitter = self.ui.splitter_main
        if splitter.isVisible():
            return sum(splitter.sizes())
        margins = self.ui.centralwidget.layout().contentsMargins()
        return (
            self.width() - margins.left() - margins.right() - 2 * splitter.handleWidth()
        )

    def applyLivePaneSizes(self):
        """The Live layout's panes: the field list at its Live width (about
        400 pixels), the Inspector hidden, the picture the rest."""
        splitter = self.ui.splitter_main
        sizes = splitter.sizes()
        if splitter.isVisible() and sizes[2] > 0:
            # shown again at this width (a double-click on its divider)
            self.paneSizesBeforeHiding[2] = sizes[2]
        total = self.splitterTotalWidth()
        stored = fetch_data("scoresight.json", LIVE_FIELDS_WIDTH_SETTING)
        fields = stored if isinstance(stored, int) and stored > 0 else LIVE_FIELDS_WIDTH
        minimum = max(
            self.ui.widget_leftPane.minimumSizeHint().width(), FIELDS_PANE_WIDTH
        )
        fields = max(minimum, min(fields, total - VIEWER_MIN_WIDTH))
        splitter.setSizes([fields, max(VIEWER_MIN_WIDTH, total - fields), 0])

    def applyLayoutUi(self):
        """Show the widgets of the current layout (also after a language
        change: retranslateUi resets the texts)."""
        ui = self.ui
        live = self.layoutMode == LAYOUT_LIVE
        ui.actionSetupLayout.setChecked(not live)
        ui.actionLiveLayout.setChecked(live)
        self.readingDelegate.setDensity(DENSITY_LIVE if live else DENSITY_SETUP)
        table = ui.tableWidget_boxes
        header = table.horizontalHeader()
        # (the header is hidden in the Live layout only)
        was_live = header.isHidden()
        if live and not was_live:
            self.setupNameColumnWidth = table.columnWidth(0)
        header.setHidden(live)
        table.setIconSize(QSize(20, 20) if live else QSize())
        for row in range(table.rowCount()):
            self.applyFieldNameFont(table.item(row, 0))
        self.updateBoxesListHeight()
        if live:
            self.fitNameColumn()
        elif was_live:
            # back from the Live layout: the width the names had
            table.setColumnWidth(0, self.setupNameColumnWidth)
        ui.label_fields.setText(
            QCoreApplication.translate("MainWindow", "Readings")
            if live
            else QCoreApplication.translate("MainWindow", "Fields")
        )
        # the picture adjustments are for setting up
        ui.widget_viewTools.setVisible(not live)
        ui.widget_cropPanel.setVisible(not live and ui.toolButton_topCrop.isChecked())
        self.updateCropWarning()
        # the field actions are in the context menu (and their keys)
        ui.widget_fieldsFooter.setVisible(not live)
        ui.widget_liveDestinations.setVisible(live)
        action = ui.actionShowUnusedFields
        action.blockSignals(True)
        action.setChecked(self.showUnusedFields())
        action.blockSignals(False)
        self.updateHiddenFields()
        table.viewport().update()

    def applyFieldNameFont(self, item: QTableWidgetItem | None):
        """A field's name: larger in the Live layout."""
        if item is None:
            return
        if self.layoutMode != LAYOUT_LIVE:
            item.setData(Qt.ItemDataRole.FontRole, None)
            return
        font = QFont(self.ui.tableWidget_boxes.font())
        if font.pointSizeF() > 0:
            font.setPointSizeF(font.pointSizeF() * 1.25)
        font.setWeight(QFont.Weight.DemiBold)
        item.setFont(font)

    def fitNameColumn(self):
        """In the Live layout, the names' column fits the names, leaving at
        least half of the list to the values."""
        table = self.ui.tableWidget_boxes
        if self.layoutMode != LAYOUT_LIVE:
            return
        wanted = table.sizeHintForColumn(0) + 8
        half = table.viewport().width() // 2
        width = max(100, min(wanted, half)) if half > 0 else wanted
        if table.columnWidth(0) != width:
            table.setColumnWidth(0, width)

    def showUnusedFields(self) -> bool:
        """Whether the current layout shows the fields not on the picture."""
        stored = fetch_data(
            "scoresight.json", SHOW_UNUSED_SETTINGS[self.layoutMode], None
        )
        if isinstance(stored, bool):
            return stored
        return SHOW_UNUSED_DEFAULTS[self.layoutMode]

    def showUnusedFieldsToggled(self, show: bool):
        """View > Show unused fields, for the current layout."""
        self.globalSettingsChanged(SHOW_UNUSED_SETTINGS[self.layoutMode], bool(show))
        self.updateHiddenFields()

    def updateHiddenFields(self):
        """Hide the fields that aren't on the picture when the layout doesn't
        show them (except the selected one, e.g. a new field), and say how
        many are hidden."""
        ui = self.ui
        table = ui.tableWidget_boxes
        show = self.showUnusedFields()
        current = self.currentFieldItem()
        hidden = 0
        for row in range(table.rowCount()):
            item = table.item(row, 0)
            hide = (
                not show
                and item is not None
                and item.data(Qt.ItemDataRole.UserRole) == NOT_PLACED
                and (current is None or current.row() != row)
            )
            if table.isRowHidden(row) != hide:
                table.setRowHidden(row, hide)
            hidden += hide
        label = ui.label_hiddenFields
        if hidden:
            label.setText(
                QCoreApplication.translate(
                    "MainWindow",
                    'Fields not on the picture: {count} hidden. <a href="#show">'
                    "Show them</a>",
                ).format(count=hidden)
            )
        label.setVisible(hidden > 0)

    def applyRuntimeTexts(self):
        """Set the texts that are made at runtime: at startup and again after a
        language change (retranslateUi resets them to the .ui texts)."""
        self.updateWindowTitle()
        self.overlayBuilder.retranslate()
        self.updateBrowserEndpoints()
        self.updatePauseUi()
        self.updateSliderReadouts()
        self.boxSettingsUiHandler.retranslate()
        self.retranslateMenus()
        self.applyShortcutHints()
        self.updateObsUi()
        self.destinationsModel.retranslate()
        self.updateDestinationsListHeight()
        self.statusBarWidgets.retranslate()
        self.applyViewerTexts()
        self.refreshLiveStatus()
        self.updateAdjustHintVisibility()
        self.applyOcrModelTexts()
        self.updateFieldsHint()
        self.updateFieldActions()
        self.updateFieldToolTips()
        # "Readings" in the Live layout, the hidden fields' line
        self.applyLayoutUi()
        self.obsSourcesTable.retranslate()
        self.updateObsSceneStatus()
        splitter = self.ui.splitter_main
        splitter.handle(1).setToolTip(
            QCoreApplication.translate(
                "MainWindow",
                "Drag to resize the fields list. Double-click to hide or show it.",
            )
        )
        splitter.handle(2).setToolTip(
            QCoreApplication.translate(
                "MainWindow",
                "Drag to resize the Box and Outputs settings. Double-click to hide "
                "or show them.",
            )
        )
        self.fitBoxSettingsWidth()

    def fitBoxSettingsWidth(self):
        """The Box tab's settings scroll vertically only, and a scroll area
        doesn't pass its content's minimum width on: make it as wide as its
        content needs (a long language's labels), so that nothing is cut off
        and the Inspector's minimum follows. Runs whenever the content's layout
        changes (a language, a selection, Image cleanup opened)."""
        area = self.ui.scrollArea_boxSettings
        width = (
            area.widget().minimumSizeHint().width()
            + area.verticalScrollBar().sizeHint().width()
            + 2 * area.frameWidth()
        )
        if area.minimumWidth() != width:
            area.setMinimumWidth(width)

    def retranslateMenus(self):
        names = {
            "System": QCoreApplication.translate("MainWindow", "System"),
            "Light": QCoreApplication.translate("MainWindow", "Light"),
            "Dark": QCoreApplication.translate("MainWindow", "Dark"),
        }
        for action in self.appearance_actions.actions():
            action.setText(names.get(action.data(), action.data()))

    def applyShortcutHints(self):
        """Add the keyboard shortcut to the tooltips of the buttons that have
        one ("... (Ctrl+B)"); ⌘ on macOS."""
        for button, action in (
            (self.ui.pushButton_stopUpdates, self.ui.actionPauseOutputs),
            (self.ui.pushButton_binary, self.ui.actionBinaryView),
            (self.ui.toolButton_zoomReset, self.ui.actionFitPicture),
            (self.ui.pushButton_refresh_sources, self.ui.actionReloadSources),
            (self.ui.toolButton_addBox, self.ui.actionNewField),
            (self.ui.toolButton_cleanupBinary, self.ui.actionBinaryView),
        ):
            shortcut = action.shortcut().toString(
                QKeySequence.SequenceFormat.NativeText
            )
            tooltip = button.toolTip()
            if shortcut and f"({shortcut})" not in tooltip:
                button.setToolTip(f"{tooltip} ({shortcut})".strip())
        # Remove from picture: Del while it is shown (the key moves between it
        # and Delete field)
        delete_key = key_text(self.deleteKeys[0])
        button = self.ui.pushButton_removeBox
        if f"({delete_key})" not in button.toolTip():
            button.setToolTip(f"{button.toolTip()} ({delete_key})".strip())
        # how to zoom and pan, on the Fit button and the zoom readout
        native = QKeySequence.SequenceFormat.NativeText
        zoom_hint = QCoreApplication.translate(
            "MainWindow",
            "Zoom with Ctrl+scroll or {zoom_in} and {zoom_out}; drag with the "
            "middle mouse button to move the picture.",
        ).format(
            zoom_in=self.ui.actionZoomIn.shortcut().toString(native),
            zoom_out=self.ui.actionZoomOut.shortcut().toString(native),
        )
        for widget in (self.ui.toolButton_zoomReset, self.ui.label_zoom):
            tooltip = widget.toolTip()
            if zoom_hint not in tooltip:
                widget.setToolTip(f"{tooltip}\n{zoom_hint}".strip())

    def updateAdjustHintVisibility(self):
        """Show the hint of the Adjust picture row only when the row has room
        for it: it never makes the window wider."""
        row = self.ui.widget_viewTools
        hint = self.ui.label_adjustHint
        layout = row.layout()
        needed = layout.contentsMargins().left() + layout.contentsMargins().right()
        visible = 0
        for index in range(layout.count()):
            widget = layout.itemAt(index).widget()
            if widget is None or widget is hint or widget.isHidden():
                continue
            needed += widget.sizeHint().width()
            visible += 1
        needed += layout.spacing() * visible + hint.sizeHint().width()
        hint.setVisible(row.width() >= needed)

    def updateWindowTitle(self):
        title = f"ScoreSight - v{__version__}"
        profile = get_profile()
        if profile:
            title += f" [{profile}]"
        if self.outputsPausedAt is not None:
            # visible in the taskbar too
            title = f"⏸ {title}"
        self.setWindowTitle(title)

    def updateBrowserEndpoints(self):
        """Show the HTTP server's real port on its page, and its address for
        other computers, or that the server isn't running (its port was
        busy)."""
        self.overlayBuilder.refresh()
        port = get_http_server_port()
        if port is None:
            self.ui.label_8.setText(
                QCoreApplication.translate(
                    "MainWindow",
                    "<p>The HTTP server is not running: port {port} is already "
                    "in use or not available.</p><p>Close the other program, or "
                    "start ScoreSight with <b>--port</b> to use a different port. "
                    "The log has the details.</p>",
                ).format(port=self.http_port)
            )
            return
        # the page's links are written for the default port
        text = self.browserEndpointsTemplate.replace(
            f"localhost:{DEFAULT_HTTP_PORT}", f"localhost:{port}"
        )
        if self.lanAddress:
            url = f"http://{self.lanAddress}:{port}"
            other_computers = QCoreApplication.translate(
                "MainWindow",
                "<p>From other computers on your network, use {url} instead of "
                "http://localhost:{port}.</p>",
            ).format(url=f'<a href="{url}/scoresight">{url}</a>', port=port)
            if "</body>" in text:
                text = text.replace("</body>", other_computers + "</body>", 1)
            else:
                text += other_computers
        self.ui.label_8.setText(text)

    def overlayBaseUrls(self) -> tuple[str, ...]:
        """The HTTP server's URLs for the overlays (the network address first),
        or () when it isn't running."""
        port = get_http_server_port()
        if port is None:
            return ()
        return http_server_urls(port, self.lanAddress)

    def overlayFieldNames(self) -> list[str]:
        """The boxes' names, in the fields list's order (for the overlays)."""
        storage = getattr(self, "detectionTargetsStorage", None)
        if storage is None:
            return []
        return [target.name for target in storage.get_data()]

    def setupChoiceSetting(self, combo_box, setting_name: str, values: tuple):
        """Bind a combo box whose items are values (their text may be translated)
        to a setting that stores the value itself."""
        stored = fetch_data("scoresight.json", setting_name)
        if stored in values:
            index = values.index(stored)
        else:
            # 0.1.x stored the item text, which could be blank or translated
            index = max(
                combo_box.findText(stored if isinstance(stored, str) else ""), 0
            )
        combo_box.blockSignals(True)
        combo_box.setCurrentIndex(index)
        combo_box.blockSignals(False)
        if stored != values[index]:
            self.globalSettingsChanged(setting_name, values[index])

        def choiceChanged(index: int):
            if 0 <= index < len(values):
                self.globalSettingsChanged(setting_name, values[index])

        combo_box.currentIndexChanged.connect(choiceChanged)

    def setColorScheme(self, scheme: str):
        scheme = apply_color_scheme(scheme)
        self.globalSettingsChanged("color_scheme", scheme)
        for action in self.appearance_actions.actions():
            action.setChecked(action.data() == scheme)

    def toggleSpeed(self):
        """The next playback speed of a video file: x2, x4 ... x32, then x1."""
        if self.image_viewer and self.image_viewer.timerThread is not None:
            speed = source_bar.next_speed(self.image_viewer.timerThread.getSpeed())
            self.image_viewer.timerThread.setSpeed(speed)
            self.ui.toolButton_speed.setText(source_bar.speed_text(speed))

    def openVideoSettings(self):
        # only allow opening the video settings for an OpenCV type source
        if not self.image_viewer or self.image_viewer is None:
            return

        if self.image_viewer.getCameraInfo().type != CameraInfo.CameraType.OPENCV:
            return

        if self.video_settings_dialog is None:
            # open the logs dialog
            self.video_settings_dialog = VideoSettingsDialog()
            self.video_settings_dialog.setWindowTitle(
                QCoreApplication.translate("MainWindow", "Video Settings")
            )

        self.video_settings_dialog.init_ui(self.image_viewer.getCameraCapture())

        # show the dialog, non modal
        self.video_settings_dialog.show()

    def rotateImage(self):
        # store the rotation in the scoresight.json
        rotation = fetch_data("scoresight.json", "rotation", 0)
        rotation += 90
        if rotation >= 360:
            rotation = 0
        self.globalSettingsChanged("rotation", rotation)
        self.updateRotateText(rotation)
        self.updateCropWarning()

    def cropMode(self):
        # if the toolButton_topCrop is unchecked, go to crop mode
        if self.ui.toolButton_topCrop.isChecked():
            self.ui.widget_cropPanel.setVisible(True)
            self.ui.widget_cropPanel.setEnabled(True)
            self.globalSettingsChanged("crop_mode", True)
        else:
            self.cancelCropSelection()
            self.ui.widget_cropPanel.setVisible(False)
            self.ui.widget_cropPanel.setEnabled(False)
            self.globalSettingsChanged("crop_mode", False)
        self.cropChanged()

    def cropValueChanged(self, setting: str, value: int):
        """A crop value (left_crop, ...) was changed."""
        self.globalSettingsChanged(setting, value)
        self.cropChanged()

    def currentCropOrigin(self) -> tuple[int, int]:
        """The crop's top-left corner in the rotated frame, (0, 0) while the
        crop is off."""
        if not self.ui.toolButton_topCrop.isChecked():
            return 0, 0
        return self.ui.spinBox_leftCrop.value(), self.ui.spinBox_topCrop.value()

    def cropChanged(self):
        """The crop was turned on or off or its values changed. The boxes are
        placed on the cropped picture: when the crop's top-left corner moves,
        they (and the 4-corner correction's corners) move with it, so that
        they stay on the same part of the scoreboard."""
        origin = self.currentCropOrigin()
        previous, self.cropOrigin = self.cropOrigin, origin
        if previous is not None and origin != previous:
            self.moveForCrop(previous[0] - origin[0], previous[1] - origin[1])
        self.updateCropWarning()
        self.ui.toolButton_resetCrop.setEnabled(any(self.cropValues()))

    def cropValues(self) -> tuple[int, int, int, int]:
        """The crop's left, top, right and bottom values (kept while the crop
        is off)."""
        ui = self.ui
        return (
            ui.spinBox_leftCrop.value(),
            ui.spinBox_topCrop.value(),
            ui.spinBox_rightCrop.value(),
            ui.spinBox_bottomCrop.value(),
        )

    def moveForCrop(self, dx: int, dy: int):
        """Move the boxes and the 4-corner corners by (dx, dy) pixels."""
        # right after the crop was stored (and the capture thread follows it),
        # before anything that could let that thread run (the log's I/O)
        self.detectionTargetsStorage.move_items(dx, dy)
        viewer = self.image_viewer
        if viewer is not None and viewer.timerThread is not None:
            # the readings of the frames cropped as before are dropped
            viewer.timerThread.boxesMoved()
        logger.info("The crop moved: moved the boxes by (%d, %d) pixels", dx, dy)
        corners = fetch_data("scoresight.json", "four_corners")
        if isinstance(corners, list) and len(corners) == 4:
            try:
                moved = [[x + dx, y + dy] for x, y in corners]
            except (TypeError, ValueError):
                return
            store_data("scoresight.json", "four_corners", moved)
            if viewer is not None:
                viewer.setFourCornersForHomography(moved)

    def croppedPictureRect(self) -> QRectF | None:
        """The picture the boxes are read from (rotated and cropped), in its
        own pixels, or None before the source's first frame."""
        # (also called while the boxes load, before there is an image_viewer)
        viewer = getattr(self, "image_viewer", None)
        if viewer is None:
            return None
        size = viewer.uncroppedFrameSize()
        if size is None:
            return None
        width, height = int(size.width()), int(size.height())
        if self.ui.toolButton_topCrop.isChecked():
            ui = self.ui
            top, bottom, left, right = crop_margins(
                width,
                height,
                ui.spinBox_topCrop.value(),
                ui.spinBox_bottomCrop.value(),
                ui.spinBox_leftCrop.value(),
                ui.spinBox_rightCrop.value(),
            )
            width -= left + right
            height -= top + bottom
        return QRectF(0, 0, width, height)

    def boxesOutsidePicture(self) -> list[str]:
        """The fields whose box is entirely outside the (cropped) picture:
        they read nothing."""
        picture = self.croppedPictureRect()
        if picture is None:
            return []
        return [
            box.name
            for box in self.detectionTargetsStorage.get_data()
            if not (box.settings or {}).get("templatefield")
            and not QRectF(box).intersects(picture)
        ]

    def updateCropWarning(self):
        """Under the crop's values: the boxes the crop left outside the
        picture. They are kept where they are (widening the crop brings them
        back), but read nothing meanwhile."""
        ui = self.ui
        names = (
            self.boxesOutsidePicture()
            if ui.toolButton_topCrop.isChecked() and self.layoutMode != LAYOUT_LIVE
            else []
        )
        if names:
            ui.label_cropWarning.setText(
                QCoreApplication.translate(
                    "MainWindow",
                    "Outside the cropped picture: {names}. They read nothing: widen "
                    "the crop, or remove them from the picture and place them again.",
                ).format(names=", ".join(names))
            )
        ui.label_cropWarning.setVisible(bool(names))

    def globalSettingsChanged(self, settingName, value):
        store_data("scoresight.json", settingName, value)

    def eventFilter(self, obj, event):
        if (
            event.type() == QEvent.Type.KeyPress
            and obj is self.ui.tableWidget_boxes
            and event.matches(QKeySequence.StandardKey.Copy)
        ):
            # Ctrl+C in the fields list: the value, not the name
            self.copyFieldValue()
            return True
        if event.type() == QEvent.KeyPress and obj is self:
            # (a key the focused widget doesn't use reaches the window last)
            if event.key() == Qt.Key_Escape:
                viewer = self.image_viewer
                if viewer is not None and viewer.isDrawing():
                    # the box (or crop) isn't drawn, the field stays selected
                    viewer.cancelDrawing()
                elif viewer is not None and viewer.cropSelectionMode:
                    # stop the crop picking, the crop stays
                    self.cancelCropSelection()
                elif viewer is not None and viewer.fourCornerSelectionMode:
                    # stop picking corners, the correction stays
                    viewer.cancelFourCornerSelection()
                else:
                    # deselect any selected item
                    self.itemSelected(None)
                    if viewer is not None:
                        viewer.selectBox(None)
        elif (
            event.type() == QEvent.Type.LayoutRequest
            and obj is self.ui.scrollAreaWidgetContents_boxSettings
        ):
            self.fitBoxSettingsWidth()
        elif event.type() == QEvent.Type.Resize and obj is self.ui.widget_viewTools:
            self.updateAdjustHintVisibility()
        elif (
            event.type() == QEvent.Type.Resize
            and obj is self.ui.tableWidget_boxes.viewport()
        ):
            self.fitNameColumn()
        elif (
            event.type() == QEvent.Type.Resize
            and obj is self.ui.comboBox_camera_source
            and hasattr(self, "sourceIndexAtPopup")
        ):
            self.updateSourceBar()
        elif (
            event.type() == QEvent.Type.Show
            and obj is self.ui.comboBox_camera_source.view()
        ):
            # picking the open file, stream or screen again chooses another one
            self.sourceIndexAtPopup = self.ui.comboBox_camera_source.currentIndex()
        elif (
            event.type() == QEvent.Type.EnabledChange
            and obj is self.ui.groupBox_sb_info
        ):
            self.updateFieldsHint()
        elif event.type() == QEvent.Type.MouseButtonDblClick:
            # a double-click on a divider hides or shows the pane beside it
            splitter = self.ui.splitter_main
            for handle, pane in ((1, 0), (2, 2)):
                if obj is splitter.handle(handle):
                    self.setPaneHidden(pane, not self.isPaneHidden(pane))
                    return True
        return super().eventFilter(obj, event)

    def changeEvent(self, event):
        # File > Appearance or the system switched between light and dark: the
        # state colours follow the palette
        if event.type() in (
            QEvent.Type.PaletteChange,
            QEvent.Type.ApplicationPaletteChange,
        ) and hasattr(self, "statusBarWidgets"):
            self.updatePauseUi()
            self.applyViewerStyles()
            self.refreshLiveStatus()
            # an invalid format's red
            self.boxSettingsUiHandler.updateFormatState()
            self.updateObsSceneStatus()
        super().changeEvent(event)

    def changeLanguage(self, locale):
        locale_file = resource_path("translations", f"scoresight_{locale}.qm")
        logger.info(f"Changing language to {locale_file}")
        if not self.translator.load(locale_file):
            logger.error(f"Could not load translation for {locale_file}")
            return
        # used at the next start instead of the system language
        self.globalSettingsChanged("language", locale)
        for action in self.language_actions.actions():
            action.setChecked(action.data() == locale)
        appInstance = QApplication.instance()
        if appInstance:
            logger.info(f"installing translator for {locale}")
            appInstance.installTranslator(self.translator)
            scene_name = self.ui.lineEdit_sceneName.text()
            speed = self.ui.toolButton_speed.text()
            try:
                self.ui.retranslateUi(self)
            except Exception as e:
                logger.error(f"Error retranslating UI: {e}")
            # retranslateUi resets these texts to their .ui defaults
            self.browserEndpointsTemplate = self.ui.label_8.text()
            self.ui.lineEdit_sceneName.setText(scene_name)
            self.ui.toolButton_speed.setText(speed)
            self.vmixUiHandler.restoreUiState()
            self.unoUiHandler.restoreUiState()
            self.tcpUiHandler.retranslate()
            self.gameUiHandler.retranslate()
            self.apiUiHandler.restoreUiState()
            self.applyRuntimeTexts()

    def toggleUpdateOnChange(self, value):
        self.globalSettingsChanged("update_on_change", value)
        if self.image_viewer:
            self.image_viewer.setUpdateOnChange(value)

    def importConfiguration(self):
        # open a file dialog to select a configuration file
        file, _ = QFileDialog.getOpenFileName(
            self, "Open Configuration File", "", "Configuration Files (*.json)"
        )
        if not file:
            return
        # load the configuration from the file
        if not self.detectionTargetsStorage.loadBoxesFromFile(file):
            # show an error qmessagebox
            logger.error("Error loading configuration file")
            QMessageBox.critical(
                self,
                "Error",
                "Error loading configuration file",
                QMessageBox.StandardButton.Ok,
            )
            return

    def exportConfiguration(self):
        # open a file dialog to select the output file
        file, _ = QFileDialog.getSaveFileName(
            self, "Save Configuration File", "", "Configuration Files (*.json)"
        )
        if not file:
            return
        # save the configuration to the file
        self.detectionTargetsStorage.saveBoxesToFile(file)

    def openOCRTrainingDataDialog(self):
        # open the OCR training data dialog
        dialog = OCRTrainingDataDialog()
        dialog.exec()

    def openConfigurationFolder(self):
        # open the configuration folder (SCORESIGHT_DATA_DIR aware) in the file
        # explorer
        data_dir = get_data_dir()
        os.makedirs(data_dir, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(data_dir))

    def toggleOSD(self, value):
        """Stats (View > Statistics overlay): the viewer follows the setting."""
        self.ui.actionStatsOverlay.setChecked(value)
        self.globalSettingsChanged(SHOW_OSD_SETTING, bool(value))

    def resetZoom(self):
        if self.image_viewer:
            self.image_viewer.resetZoom()

    def detectionCadenceChanged(self, detections_per_second):
        # the capture thread follows the detection_cadence setting
        self.globalSettingsChanged("detection_cadence", detections_per_second)

    def updateSliderReadouts(self, *_):
        """Show the values of the Detections / s and Save / s sliders."""
        for slider, label in (
            (
                self.ui.horizontalSlider_detectionCadence,
                self.ui.label_detectionCadenceValue,
            ),
            (self.ui.horizontalSlider_aggsPerSecond, self.ui.label_aggsPerSecondValue),
        ):
            text = QCoreApplication.translate("MainWindow", "{value} /s").format(
                value=slider.value()
            )
            widest = QCoreApplication.translate("MainWindow", "{value} /s").format(
                value=slider.maximum()
            )
            label.setText(text)
            label.setMinimumWidth(
                QFontMetrics(label.font()).horizontalAdvance(widest) + 2
            )
            slider.setAccessibleDescription(text)

    def refreshLiveStatus(self):
        """Once a second (and when an output is turned on or off): the
        outputs' statuses, the status bar, and the boxes list (the readings'
        ages)."""
        now = time.monotonic()
        if now - self.lanAddressCheckedAt > 30:
            # the network may have changed (no traffic: a route lookup)
            lan_address = primary_lan_address()
            self.lanAddressCheckedAt = now
            if lan_address != self.lanAddress:
                self.lanAddress = lan_address
                self.updateBrowserEndpoints()
        outputs = self.refreshDestinations(now)
        self.gameUiHandler.refresh()
        snapshot = self.statusSnapshot(now, outputs)
        self.statusBarWidgets.update(snapshot)
        self.updateOcrModelAutoText(snapshot)
        self.updateImageCleanupEngine(snapshot)
        self.updatePpocrCpuHint(snapshot)
        self.updateSourceHealth(snapshot.source_state)
        self.updateFirstRunCard(outputs)
        cadence = self.ui.horizontalSlider_detectionCadence.value()
        # stale after 20 detection cycles (at least 10 s)
        self.readingDelegate.setStaleAfter(20.0 / max(cadence, 0.1))
        self.ui.tableWidget_boxes.viewport().update()

    def statusSnapshot(
        self,
        now: float | None = None,
        outputs: list[DestinationStatus] | None = None,
    ) -> StatusSnapshot:
        """What the status bar shows, from what the window already knows."""
        now = time.monotonic() if now is None else now
        if outputs is None:
            outputs = self.destinationStatuses(now)
        values = {"outputs": tuple(outputs), "now": now}
        viewer = self.image_viewer
        if viewer is not None:
            values["source_name"] = source_display_name(viewer.getCameraInfo())
            thread = getattr(viewer, "timerThread", None)
            # the capture thread's counters (written by it, read here)
            values["source_state"] = source_state(
                has_source=True,
                error=bool(self.sourceError),
                first_frame=getattr(viewer, "firstFrameReceived", False),
                now=now,
                last_frame_at=getattr(thread, "last_frame_timestamp", None),
                fps=getattr(thread, "fps", None),
                nominal_fps=getattr(thread, "nominal_fps", None),
                failed_reads=getattr(thread, "retry_count", 0) or 0,
            )
            frame_size = getattr(thread, "frame_size", None)
            if frame_size:
                values["resolution"] = tuple(frame_size)
            values["fps"] = getattr(thread, "fps", None)
            values["nominal_fps"] = getattr(thread, "nominal_fps", None)
            # the picture adjustments, for the source's tooltip
            crop = getattr(thread, "crop", None)
            values["rotation"] = int(getattr(crop, "rotation", 0) or 0)
            values["cropped"] = bool(getattr(crop, "isCropSet", False))
            values["four_corner_corrected"] = viewer.hasFourCornerCorrection()
            values["stabilized"] = bool(getattr(thread, "stabilizationEnabled", False))
            values["ocr_rate"] = getattr(thread, "ups", None)
            interval = getattr(thread, "update_frame_interval", None)
            if interval:
                values["ocr_target"] = round(1000.0 / max(interval, 1), 2)
            detector = getattr(thread, "textDetector", None)
            engine_status = getattr(detector, "engine_status", None)
            if engine_status is not None:
                status = engine_status()
                values["ocr_model"] = status.model
                values["ocr_engine_state"] = status.ppocr_state
                values["ocr_engine_error"] = status.ppocr_error
                values["ocr_auto_model"] = status.auto_model
                values["ocr_auto_reason"] = status.auto_reason
                values["ocr_auto_accurate_ms"] = status.auto_accurate_ms
                values["ocr_auto_interval_ms"] = status.auto_interval_ms
        else:
            values["source_state"] = SOURCE_NONE
        if self.outputsPausedMonotonic is not None:
            values["paused_seconds"] = now - self.outputsPausedMonotonic
        if self.ui.actionCollectTrainingData.isChecked():
            values["collecting_training_data"] = True
            values["training_data_folder"] = (
                ocr_training_data_options.ocr_training_data_folder
            )
        port = get_http_server_port()
        if port is None:
            values["http_port"] = self.http_port
        else:
            urls = http_server_urls(port, self.lanAddress)
            values["http_url"] = urls[0]
            values["http_urls"] = urls
            values["http_port"] = port
        return StatusSnapshot(**values)

    # --- the outputs: destinations and their status --------------------------------

    def setupDestinations(self):
        """The destinations list: a row per output (with its switch and status)
        that shows the output's page below it."""
        view = self.ui.listView_destinations
        self.destinationsModel = DestinationsModel(self)
        self.destinationDelegate = DestinationDelegate(view)
        view.setModel(self.destinationsModel)
        view.setItemDelegate(self.destinationDelegate)
        view.selectionModel().currentRowChanged.connect(self.destinationSelected)
        view.setCurrentIndex(self.destinationsModel.index(0, 0))
        self.destinationsModel.toggleRequested.connect(self.destinationToggleRequested)
        self.ui.frame_destinationStatus.hide()
        self.updateDestinationsListHeight()
        # The list over the selected output's page; the divider between them
        # can be dragged to give the page (e.g. a mapping table) more room. At
        # first the list shows every output.
        splitter = self.ui.splitter_outputs
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([self.destinationsListHeight(), 10000])
        # The Live layout's outputs list, under the readings: the same model on
        # one line per output (a double-click shows the output's settings)
        live = self.ui.listView_liveDestinations
        self.liveDestinationDelegate = CompactDestinationDelegate(live)
        live.setModel(self.destinationsModel)
        live.setItemDelegate(self.liveDestinationDelegate)
        live.activated.connect(lambda index: self.showDestination(index.data(KEY_ROLE)))
        live.setFixedHeight(
            self.destinationsModel.rowCount()
            * self.liveDestinationDelegate.rowHeight(live.font())
            + 2 * live.frameWidth()
        )
        self.ui.widget_liveDestinations.hide()
        # the controls the switches mirror: show their changes right away
        for signal in (
            self.ui.pushButton_startvmix.toggled,
            self.ui.toolButton_toggleUno.toggled,
            self.ui.checkBox_enableOutAPI.toggled,
            self.tcpUiHandler.ui.pushButton_tcpStart.toggled,
        ):
            signal.connect(lambda *_: self.refreshLiveStatus())

    def destinationsListHeight(self, rows: int | None = None) -> int:
        """The height of the destinations list showing rows rows (all of
        them by default)."""
        view = self.ui.listView_destinations
        if rows is None:
            rows = self.destinationsModel.rowCount()
        row_height = self.destinationDelegate.rowHeight(view.font())
        return rows * row_height + 2 * view.frameWidth()

    def updateDestinationsListHeight(self):
        """The destinations list can be made shorter (it scrolls then), down to
        DESTINATIONS_LIST_MIN_ROWS rows."""
        self.ui.listView_destinations.setMinimumHeight(
            self.destinationsListHeight(DESTINATIONS_LIST_MIN_ROWS)
        )

    def destinationSelected(self, current, previous=None):
        if current.isValid():
            self.ui.stackedWidget_outputs.setCurrentIndex(current.row())
        self.updateDestinationDetails()

    def showDestination(self, key: str):
        """Select a destination (e.g. clicked in the status bar): the Inspector
        shows the Outputs tab (also when it was hidden) with its page."""
        self.setPaneHidden(2, False)
        self.ui.tabWidget_inspector.setCurrentWidget(self.ui.widget_outputs)
        view = self.ui.listView_destinations
        index = self.destinationsModel.index(self.destinationsModel.rowOf(key), 0)
        view.setCurrentIndex(index)
        view.scrollTo(index)
        view.setFocus(Qt.FocusReason.OtherFocusReason)

    def destinationToggleRequested(self, key: str, on: bool):
        """A destination's switch was clicked: operate the output's own control,
        which stays the source of truth (the switch shows its state)."""
        if key == output_status.FILES:
            if on:
                # a modal dialog: not from inside the list's event handling
                QTimer.singleShot(0, self.selectOutputFolder)
            else:
                self.clearOutputFolder()
        elif key == output_status.OBS:
            if on:
                self.openOBSConnectModal()
            else:
                self.disconnectObs()
        elif key == output_status.VMIX:
            self.ui.pushButton_startvmix.setChecked(on)
        elif key == output_status.UNO:
            self.ui.toolButton_toggleUno.setChecked(on)
        elif key == output_status.API:
            self.ui.checkBox_enableOutAPI.setChecked(on)
        elif key == output_status.TCP:
            self.tcpUiHandler.setRunning(on)
        self.refreshLiveStatus()

    def destinationStatuses(self, now: float) -> list[DestinationStatus]:
        """The status of every output, from snapshots (nothing here waits for
        the network)."""
        port = get_http_server_port()
        urls = http_server_urls(port, self.lanAddress) if port is not None else ()
        vmix = self.vmixUiHandler.vmixUpdater
        uno = self.unoUiHandler.unoUpdater
        method_index = self.ui.comboBox_outApiMethod.currentIndex()
        encoding_index = self.ui.comboBox_api_encode.currentIndex()
        return [
            output_status.files_status(
                self.out_folder, self.fileOutput.status(), self.outputFolderLost
            ),
            output_status.http_status(
                port, self.http_port, urls, http_server_stats(now)
            ),
            self.obsDestinationStatus(),
            output_status.vmix_status(
                vmix.running,
                vmix.host,
                vmix.port,
                vmix.input_number,
                vmix.field_mapping,
                vmix.status(),
            ),
            output_status.uno_status(
                uno.running, uno.endpoint, uno.field_mapping, uno.status(), uno.quota()
            ),
            output_status.api_status(
                self.ui.checkBox_enableOutAPI.isChecked(),
                self.ui.lineEdit_api_url.text(),
                OUT_API_METHODS[method_index]
                if 0 <= method_index < len(OUT_API_METHODS)
                else "POST",
                OUT_API_ENCODINGS[encoding_index]
                if 0 <= encoding_index < len(OUT_API_ENCODINGS)
                else OUT_API_ENCODINGS[0],
                out_api_status(),
                send_mode(),
            ),
            self.tcpUiHandler.destinationStatus(),
        ]

    def obsDestinationStatus(self) -> DestinationStatus:
        client = self.obs_websocket_client
        address = None
        if client is not None:
            address = self.obsAddress or obs_client_address(client) or "OBS"
        has_sources = any(
            (box.settings or {}).get("obs_source_name")
            for box in self.detectionTargetsStorage.get_data()
        )
        return output_status.obs_status(
            address,
            self.obsConnecting,
            self.obsConnectError,
            obs_output_status() if client is not None else None,
            connected_at=self.obsConnectedAt,
            has_sources=has_sources,
            connect_target=self.obsConnectTarget,
        )

    def refreshDestinations(self, now: float | None = None) -> list[DestinationStatus]:
        """Show every output's status in the destinations list."""
        now = time.monotonic() if now is None else now
        statuses = self.destinationStatuses(now)
        self.destinationsModel.setStatuses(statuses)
        self.tcpUiHandler.refresh()
        # the times of the last activity
        self.ui.listView_destinations.viewport().update()
        self.ui.listView_liveDestinations.viewport().update()
        self.updateDestinationDetails(now)
        return statuses

    def updateDestinationDetails(self, now: float | None = None):
        """Over the selected destination's page: its problem, if it has one, and
        what to do about it."""
        now = time.monotonic() if now is None else now
        frame = self.ui.frame_destinationStatus
        label = self.ui.label_destinationStatus
        index = self.ui.listView_destinations.currentIndex()
        status = index.data(STATUS_ROLE) if index.isValid() else None
        if status is None or not status.has_problem:
            frame.hide()
            return
        palette = self.palette()
        color = theme.color(STATE_COLORS[status.state], palette)
        text = (
            f'<b><span style="color:{color.name()}">{STATE_GLYPHS[status.state]}'
            f"</span> {html.escape(status.detail, quote=False)}</b>"
        )
        if status.hint:
            text += f"<br>{html.escape(status.hint, quote=False)}"
        if label.text() != text:
            label.setText(text)
        label.setToolTip(status_tooltip(status, now))
        label.setAccessibleName(
            f"{output_status.destination_name(status.key)}: {status.detail}"
        )
        style_sheet = (
            "QFrame#frame_destinationStatus {"
            f" background-color: {theme.tint(STATE_COLORS[status.state], palette).name()};"
            f" border: 1px solid {color.name()}; border-left: 4px solid {color.name()};"
            " border-radius: 3px; }"
        )
        if frame.styleSheet() != style_sheet:
            frame.setStyleSheet(style_sheet)
        frame.show()

    # --- the OCR model ------------------------------------------------------------

    def setupOcrModelChoices(self):
        """The OCR model list: PP-OCR (accurate) and (fast), the bundled
        Tesseract models, then Load external model.... Each item's data is the
        value stored as ocr_model (see ocr_models); the texts are set in
        applyOcrModelTexts."""
        combo = self.ui.comboBox_ocrModel
        combo.blockSignals(True)
        combo.clear()
        for choice in ocr_models.CHOICES:
            combo.addItem(choice.name, choice.value)
        combo.addItem("", LOAD_EXTERNAL_MODEL)
        combo.blockSignals(False)
        self.applyOcrModelTexts()
        model = ocr_models.effective_model(ocr_models.stored_model())
        self.showOcrModel(model)
        self.boxSettingsUiHandler.setPpocr(ocr_models.is_ppocr(model))
        combo.currentIndexChanged.connect(self.ocrModelChanged)

    def ocrModelItem(self, model) -> int:
        """The index of a model's item in the list (an external model's is Load
        external model...), or -1."""
        combo = self.ui.comboBox_ocrModel
        if ocr_models.is_external(model):
            model = LOAD_EXTERNAL_MODEL
        for index in range(combo.count()):
            data = combo.itemData(index)
            if type(data) is type(model) and data == model:
                return index
        return -1

    def applyOcrModelTexts(self):
        """The OCR model list's texts and tooltips (again after a language
        change), and whether the PP-OCR models can be chosen."""
        combo = self.ui.comboBox_ocrModel
        model = combo.model()
        for index in range(combo.count()):
            value = combo.itemData(index)
            if value == LOAD_EXTERNAL_MODEL:
                combo.setItemText(
                    index,
                    QCoreApplication.translate(
                        "MainWindow", "Load external Tesseract model..."
                    ),
                )
                stored = fetch_data("scoresight.json", ocr_models.SETTING)
                tooltip = (
                    stored
                    if ocr_models.is_external(stored)
                    else QCoreApplication.translate(
                        "MainWindow",
                        "Read the boxes with a Tesseract .traineddata file",
                    )
                )
                combo.setItemData(index, tooltip, Qt.ItemDataRole.ToolTipRole)
                continue
            if not ocr_models.is_ppocr(value):
                combo.setItemData(
                    index,
                    QCoreApplication.translate(
                        "MainWindow",
                        "A Tesseract model: the boxes' Image cleanup settings prepare "
                        "their images for it",
                    ),
                    Qt.ItemDataRole.ToolTipRole,
                )
                continue
            if value == ocr_models.PPOCR_AUTO:
                combo.setItemText(index, self.autoOcrModelName())
                tooltip = QCoreApplication.translate(
                    "MainWindow",
                    "PaddleOCR PP-OCRv6: accurate while it keeps up with Detections / "
                    "s on this computer, fast when it doesn't. The status bar says "
                    "which one reads and why.",
                )
            elif value == ocr_models.PPOCR_ACCURATE:
                combo.setItemText(
                    index, QCoreApplication.translate("MainWindow", "PP-OCR (accurate)")
                )
                tooltip = QCoreApplication.translate(
                    "MainWindow",
                    "PaddleOCR PP-OCRv6 small: reads the most values right, always. "
                    "It needs about five times the CPU of PP-OCR (fast): on a laptop, "
                    "10 boxes read 5 times a second can need more than a core.",
                )
            else:
                combo.setItemText(
                    index, QCoreApplication.translate("MainWindow", "PP-OCR (fast)")
                )
                tooltip = QCoreApplication.translate(
                    "MainWindow",
                    "PaddleOCR PP-OCRv6 tiny: about a fifth of PP-OCR (accurate)'s "
                    "CPU, for many boxes, a high Detections / s or a slow computer; "
                    "it misreads more of the hard displays (clocks, bulbs, LCDs).",
                )
            missing = ppocr_engine.missing(value)
            if missing == ppocr_engine.MISSING_MODELS:
                tooltip = QCoreApplication.translate(
                    "MainWindow",
                    "The PP-OCR models aren't installed. Download them with: {command}",
                ).format(command=ppocr_engine.FETCH_COMMAND)
            elif missing == ppocr_engine.MISSING_RUNTIME:
                tooltip = QCoreApplication.translate(
                    "MainWindow",
                    "PP-OCR needs onnxruntime, which isn't installed (pip install -r "
                    "requirements.txt).",
                )
            combo.setItemData(index, tooltip, Qt.ItemDataRole.ToolTipRole)
            item = model.item(index) if hasattr(model, "item") else None
            if item is not None:
                item.setEnabled(missing is None)

    def autoOcrModelName(self) -> str:
        """PP-OCR (automatic)'s item text: with the model it reads with while a
        source is read."""
        model = getattr(self, "ocrAutoModel", None)
        if model == ocr_models.PPOCR_ACCURATE:
            return QCoreApplication.translate(
                "MainWindow", "PP-OCR (automatic: accurate)"
            )
        if model == ocr_models.PPOCR_FAST:
            return QCoreApplication.translate("MainWindow", "PP-OCR (automatic: fast)")
        return QCoreApplication.translate("MainWindow", "PP-OCR (automatic)")

    def updateOcrModelAutoText(self, snapshot: StatusSnapshot):
        """Show which model PP-OCR (automatic) reads with, and why, in the OCR
        model list (its item and tooltip), as in the status bar."""
        auto = snapshot_auto_text(snapshot)
        model = snapshot.ocr_auto_model if auto else None
        combo = self.ui.comboBox_ocrModel
        if model != getattr(self, "ocrAutoModel", None):
            self.ocrAutoModel = model
            index = self.ocrModelItem(ocr_models.PPOCR_AUTO)
            if index >= 0:
                combo.setItemText(index, self.autoOcrModelName())
        # the .ui's tooltip, plus what automatic reads with
        tooltip = QCoreApplication.translate(
            "MainWindow",
            "The OCR model that reads every box, not only the selected one. PP-OCR "
            "(automatic) reads with PP-OCR (accurate) while this computer keeps up, "
            "and with PP-OCR (fast), which needs about a fifth of the CPU, when it "
            "doesn't. The Tesseract models use the boxes' Image cleanup settings; "
            "Load external Tesseract model... reads a .traineddata file.",
        )
        if auto:
            tooltip += "\n" + auto
        if combo.toolTip() != tooltip:
            combo.setToolTip(tooltip)

    def showOcrModel(self, model):
        """Select a model's item in the list (without choosing it again)."""
        combo = self.ui.comboBox_ocrModel
        index = self.ocrModelItem(model)
        if index >= 0 and combo.currentIndex() != index:
            combo.blockSignals(True)
            combo.setCurrentIndex(index)
            combo.blockSignals(False)

    def currentTextDetector(self):
        viewer = self.image_viewer
        thread = getattr(viewer, "timerThread", None) if viewer else None
        return getattr(thread, "textDetector", None) if thread else None

    def ocrModelChanged(self, index: int):
        """The user chose an OCR model in the list."""
        value = self.ui.comboBox_ocrModel.itemData(index)
        if value == LOAD_EXTERNAL_MODEL:
            file, _ = QFileDialog.getOpenFileName(
                self, "Open OCR Model File", "", "OCR Model Files (*.traineddata)"
            )
            if not file:
                # back to the model in use
                self.showOcrModel(ocr_models.effective_model(ocr_models.stored_model()))
                return
            value = path.abspath(file)
        if value is None:
            return
        self.globalSettingsChanged(ocr_models.SETTING, value)
        self.ppocrSlowUpdates = 0
        self.applyOcrModel()
        self.applyOcrModelTexts()

    def applyOcrModel(self, opening_source: bool = False):
        """Read the boxes with the chosen OCR model: the stored one, the default
        for a new setup, or Tesseract's General Scoreboard while PP-OCR can't be
        used (not stored, so PP-OCR takes over once it is installed). A new
        setup's default is stored when its first source opens, so that the
        setup keeps it whatever later versions default to."""
        stored = ocr_models.stored_model()
        model = ocr_models.effective_model(stored)
        if opening_source and model == stored and not ocr_models.is_stored():
            self.globalSettingsChanged(ocr_models.SETTING, model)
        self.showOcrModel(model)
        detector = self.currentTextDetector()
        if detector is not None and getattr(detector, "model", None) != model:
            detector.setOcrModel(model)
        self.boxSettingsUiHandler.setPpocr(ocr_models.is_ppocr(model))

    def updateImageCleanupEngine(self, snapshot: StatusSnapshot):
        """Image cleanup follows the engine that reads: Tesseract, with its
        settings, after a PP-OCR model failed to load."""
        if snapshot.ocr_model is None:
            # no capture: as the chosen model (applyOcrModel)
            return
        ppocr = snapshot.ocr_engine_state not in (None, ppocr_engine.FAILED)
        if ppocr != self.boxSettingsUiHandler.ppocr:
            self.boxSettingsUiHandler.setPpocr(ppocr)

    def updatePpocrCpuHint(self, snapshot: StatusSnapshot):
        """Once PP-OCR (accurate) has been unable to keep up with Detections / s
        for a few seconds, suggest PP-OCR (fast) or fewer detections, once
        (the status bar's tooltip keeps saying it). The model is never changed
        without the user."""
        if ppocr_accurate_is_slow(snapshot):
            self.ppocrSlowUpdates += 1
        else:
            self.ppocrSlowUpdates = 0
        if (
            self.ppocrSlowUpdates >= PPOCR_CPU_HINT_AFTER_UPDATES
            and not self.ppocrCpuHintShown
            and fetch_data("scoresight.json", PPOCR_CPU_HINT_SETTING) is not True
        ):
            self.showPpocrCpuHint(snapshot)

    def showPpocrCpuHint(self, snapshot: StatusSnapshot):
        """A non-modal message: PP-OCR (accurate) can't keep up. Its button
        chooses PP-OCR (fast); closing it changes nothing."""
        self.globalSettingsChanged(PPOCR_CPU_HINT_SETTING, True)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle(
            QCoreApplication.translate("MainWindow", "The OCR can't keep up")
        )
        box.setText(
            QCoreApplication.translate(
                "MainWindow",
                "The boxes are read {rate} times per second instead of {target}.",
            ).format(
                rate=f"{snapshot.ocr_rate or 0:.1f}",
                target=f"{snapshot.ocr_target or 0:g}",
            )
        )
        box.setInformativeText(ppocr_cpu_advice())
        use_fast = box.addButton(
            QCoreApplication.translate("MainWindow", "Use PP-OCR (fast)"),
            QMessageBox.ButtonRole.AcceptRole,
        )
        box.addButton(
            QCoreApplication.translate("MainWindow", "Keep PP-OCR (accurate)"),
            QMessageBox.ButtonRole.RejectRole,
        )
        use_fast.setEnabled(ppocr_engine.missing(ocr_models.PPOCR_FAST) is None)
        box.setWindowModality(Qt.WindowModality.NonModal)
        box.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

        def clicked(button):
            if button is use_fast:
                index = self.ocrModelItem(ocr_models.PPOCR_FAST)
                if index >= 0:
                    # as if chosen in the list: stored and applied
                    self.ui.comboBox_ocrModel.setCurrentIndex(index)

        box.buttonClicked.connect(clicked)
        self.ppocrCpuHint = box
        self.ppocrCpuHintShown = True
        box.show()

    def openLogsDialog(self):
        if self.log_dialog is None:
            # open the logs dialog
            self.log_dialog = LogViewerDialog()
            self.log_dialog.setWindowTitle(
                QCoreApplication.translate("MainWindow", "Logs")
            )

        # show the dialog, non modal
        self.log_dialog.show()

    def checkForUpdates(self, manual: bool):
        """Check GitHub for a newer release on a background thread. The automatic
        check at startup honors "Don't check for updates at startup"; a manual
        check (File > Check for Updates) always runs and always shows a result."""
        if self.update_check_running:
            # the running check shows its result to this request too
            self.update_check_manual_pending |= manual
            return
        if not manual and not update_checks_enabled():
            logger.info("Update checks at startup are disabled")
            return
        self.update_check_running = True
        run_in_background(
            "update check",
            lambda: check_for_updates(),
            lambda result: self.update_check_finished.emit(result, manual),
        )

    @Slot(object, bool)
    def updateCheckFinished(self, result, manual: bool):
        self.update_check_running = False
        manual = manual or self.update_check_manual_pending
        self.update_check_manual_pending = False
        if not isinstance(result, UpdateCheckResult):
            result = UpdateCheckResult(__version__, error="the update check failed")
        if not (manual or result.update_available):
            return
        if self.update_dialog is not None:
            try:
                self.update_dialog.close()
            except RuntimeError:
                pass  # already closed (and deleted)
        self.update_dialog = show_update_dialog(
            result,
            self,
            self.appUpdater.start if self.appUpdater.available() else None,
        )

    def createAboutDialog(self) -> QDialog:
        about_dialog = QDialog(self)
        about_dialog.ui = Ui_About()
        about_dialog.ui.setupUi(about_dialog)
        about_dialog.setWindowTitle(
            QCoreApplication.translate("MainWindow", "About ScoreSight")
        )
        about_dialog.ui.label_version.setText(
            QCoreApplication.translate("MainWindow", "Version {version}").format(
                version=__version__
            )
        )
        return about_dialog

    def openAboutDialog(self):
        about_dialog = self.createAboutDialog()
        about_dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        about_dialog.open()

    def toggleStabilize(self):
        if not self.image_viewer:
            return
        # start or stop the stabilization
        self.image_viewer.toggleStabilization(self.ui.pushButton_stabilize.isChecked())

    def toggleStopUpdates(self, value):
        """Pause outputs (checked) or resume them. The readings keep updating in
        the window; only the outputs freeze."""
        self.updateOCRResults = not value
        if value:
            self.outputsPausedAt = datetime.now()
            self.outputsPausedMonotonic = time.monotonic()
            self.resendAfterPause = set()
            logger.info("Outputs paused")
        else:
            if self.outputsPausedAt is not None:
                logger.info("Outputs resumed")
                # values that changed while paused are unchanged readings now
                self.resendAfterPause = {
                    box.name for box in self.detectionTargetsStorage.get_data()
                }
            self.outputsPausedAt = None
            self.outputsPausedMonotonic = None
        self.updatePauseUi()
        self.refreshLiveStatus()

    def updatePauseUi(self):
        """Show whether the outputs are paused: the button (amber while paused),
        the banner over the viewer, the window title and the boxes list."""
        paused = self.ui.pushButton_stopUpdates.isChecked()
        button = self.ui.pushButton_stopUpdates
        # QCoreApplication.translate falls back to the source text when a
        # translation is missing (QTranslator.translate returns "")
        button.setText(
            QCoreApplication.translate("MainWindow", "Resume outputs")
            if paused
            else QCoreApplication.translate("MainWindow", "Pause outputs")
        )
        palette = self.palette()
        amber = theme.color("paused", palette).name()
        on_amber = theme.on_color(palette).name()
        button.setIcon(
            theme.media_icon("play", theme.on_color(palette))
            if paused
            else theme.media_icon("pause", theme.button_text_color(palette))
        )
        button.setStyleSheet(
            "QPushButton#pushButton_stopUpdates:checked {"
            f" background-color: {amber}; color: {on_amber};"
            f" border: 1px solid {amber}; border-radius: 3px;"
            " padding: 4px 8px; }"
        )
        # bold while paused, in the button's font (not the style sheet's), so
        # its size fits the bold text: "Resume outputs" was cut off
        font = QFont(button.font())
        if font.bold() != paused:
            font.setBold(paused)
            button.setFont(font)

        banner = self.ui.frame_pausedBanner
        banner.setVisible(paused)
        if paused and self.outputsPausedAt is not None:
            self.ui.label_pausedBanner.setText(
                QCoreApplication.translate(
                    "MainWindow",
                    "<b>Outputs paused</b> since {time}. Your graphics show the "
                    "last values sent; the readings here keep updating.",
                ).format(time=self.outputsPausedAt.strftime("%H:%M:%S"))
            )
        banner.setStyleSheet(
            "QFrame#frame_pausedBanner {"
            f" background-color: {theme.paused_tint(palette).name()};"
            f" border: 1px solid {amber}; border-left: 4px solid {amber}; }}"
        )
        self.ui.pushButton_resumeOutputs.setIcon(
            theme.media_icon("play", theme.button_text_color(palette))
        )
        self.vmixUiHandler.refreshToggleButton()
        self.unoUiHandler.refreshToggleButton()
        self.tcpUiHandler.refreshTheme()
        self.updateWindowTitle()
        self.readingDelegate.setPaused(paused)
        self.ui.tableWidget_boxes.viewport().update()

    def selectOutputFolder(self):
        # open a Qt dialog to select the output folder
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Output Folder",
            fetch_data("scoresight.json", "output_folder", ""),
            options=QFileDialog.Option.ShowDirsOnly,
        )
        if folder and len(folder) > 0:
            self.setOutputFolder(folder)

    def setOutputFolder(self, folder: str):
        self.ui.lineEdit_folder.setText(folder)
        self.out_folder = folder
        self.outputFolderLost = None
        self.globalSettingsChanged("output_folder", folder)
        # write the current values to the new folder right away
        self.scheduleFileOutputFlush()
        self.refreshLiveStatus()

    def clearOutputFolder(self):
        # clear the output folder
        self.ui.lineEdit_folder.setText("")
        self.out_folder = None
        self.outputFolderLost = None
        remove_data("scoresight.json", "output_folder")
        self.refreshLiveStatus()

    # --- the boxes list -------------------------------------------------------------

    def appendBoxRow(self, name: str) -> QTableWidgetItem:
        """Add a row for a box to the boxes list; returns its name item."""
        table = self.ui.tableWidget_boxes
        row = table.rowCount()
        table.insertRow(row)
        item = QTableWidgetItem(name)
        self.applyFieldNameFont(item)
        table.setItem(row, 0, item)
        # the reading: enabled (so it isn't drawn greyed out), not selectable
        # or editable (the name item stays the current item)
        valueItem = QTableWidgetItem()
        valueItem.setFlags(Qt.ItemFlag.ItemIsEnabled)
        table.setItem(row, 1, valueItem)
        return item

    def boxNameItem(self, name: str) -> QTableWidgetItem | None:
        """The name item (column 0) of a box in the boxes list. findItems also
        matches the Value column, which may hold the same text."""
        for item in self.ui.tableWidget_boxes.findItems(
            name, Qt.MatchFlag.MatchExactly
        ):
            if item.column() == 0:
                return item
        return None

    def boxValueItem(self, name: str) -> QTableWidgetItem | None:
        """The Value item (column 1) of a box in the boxes list."""
        item = self.boxNameItem(name)
        if item is None:
            return None
        return self.ui.tableWidget_boxes.item(item.row(), 1)

    def nameItemOfRow(self, item: QTableWidgetItem | None) -> QTableWidgetItem | None:
        if item is None or item.column() == 0:
            return item
        return self.ui.tableWidget_boxes.item(item.row(), 0)

    def keepNameCellCurrent(self, row, column, previous_row, previous_column):
        # e.g. a click on a reading or the arrow keys: the row's name becomes
        # the current item
        if column != 0 and row >= 0:
            self.ui.tableWidget_boxes.setCurrentCell(row, 0)

    def detectionTargetsChanged(self, detectionTargets: list[TextDetectionTarget]):
        for box in detectionTargets:
            logger.debug(f"Change: Detection target: {box.name}")
            # change the list icon to green checkmark
            item = self.boxNameItem(box.name)
            if item is None:
                logger.warning(f"Item not found: {box.name}. Adding it to the list.")
                # add the item to the list
                item = self.appendBoxRow(box.name)

            if box.settings is None or not box.settings["templatefield"]:
                # this is a detection target
                self.setFieldPlacement(item, PLACED)
            else:
                # this is a template field
                self.setFieldPlacement(item, TEMPLATE)
        # the fields whose box is gone (e.g. File > Import Configuration replaced
        # the boxes) aren't on the picture any more
        names = {box.name for box in detectionTargets}
        table = self.ui.tableWidget_boxes
        for row in range(table.rowCount()):
            item = table.item(row, 0)
            if item.text() in names or item.data(Qt.ItemDataRole.UserRole) in (
                NOT_PLACED,
                None,
            ):
                continue
            self.setFieldPlacement(item, NOT_PLACED)
            clear_reading(table.item(row, 1))
            # nothing to hold any more
            if item.text() in self.heldValues:
                self.heldValues.forget(item.text())
                self.updateHeldUi()

        self.vmixUiHandler.updatevMixTable(detectionTargets)
        self.unoUiHandler.updateUNOTable(detectionTargets)
        self.tcpUiHandler.updateTable(detectionTargets)
        self.apiUiHandler.setBoxNames(box.name for box in detectionTargets)
        self.obsSourcesTable.refresh(detectionTargets)
        # Note: results.csv is not touched here. data_changed fires on every box
        # click and settings tweak; file_output starts a new CSV file by itself
        # when the set of boxes changes.
        # the Box tab follows a change of the selected field's placement
        self.fieldSelectionChanged()
        self.updateFieldActions()
        self.updateHiddenFields()
        self.fitNameColumn()
        self.updateCropWarning()

    def scheduleBoxesSave(self, *_):
        # (re)start the timer: a burst of edits (e.g. dragging a slider) is
        # written once
        self.boxesSaveTimer.start()

    def saveBoxes(self):
        self.boxesSaveTimer.stop()
        self.detectionTargetsStorage.saveBoxesToStorage()

    def listItemClicked(self, item):
        # a click on a reading selects its box
        if item.column() != 0:
            item = self.nameItemOfRow(item)
            if item is None:
                return
            self.ui.tableWidget_boxes.setCurrentItem(item)
        # the Box tab shows the field's settings
        self.boxSettingsUiHandler.showField(
            item.text(),
            item.data(Qt.ItemDataRole.UserRole),
            custom=self.isCustomField(item.text()),
        )
        self.updateFieldActions()

        # notify the image viewer to select the box
        if self.image_viewer:
            self.image_viewer.selectBox(item.text())

    # --- the Fields pane: the selected field's actions ------------------------------

    @staticmethod
    def isCustomField(name: str) -> bool:
        return name not in [box["name"] for box in default_boxes]

    def currentFieldItem(self) -> QTableWidgetItem | None:
        """The name item of the selected field, if any."""
        table = self.ui.tableWidget_boxes
        item = self.nameItemOfRow(table.currentItem())
        if item is None or not item.isSelected():
            return None
        return item

    def fieldSelectionChanged(self):
        item = self.currentFieldItem()
        handler = self.boxSettingsUiHandler
        if item is None:
            if handler.fieldName is not None:
                handler.showField(None)
            self.updateFieldActions()
        elif (item.text(), item.data(Qt.ItemDataRole.UserRole)) != (
            handler.fieldName,
            handler.fieldRole,
        ):
            self.listItemClicked(item)
        # the selected field is shown even when unused fields are hidden
        self.updateHiddenFields()

    def updateFieldsHint(self):
        # the fields list is disabled until a source shows a picture
        self.ui.label_fieldsHint.setVisible(not self.ui.groupBox_sb_info.isEnabled())
        self.updateFieldActionHint()

    def setFieldPlacement(self, item: QTableWidgetItem, role: str):
        """A field's placement (NOT_PLACED, PLACED or TEMPLATE): its role, its
        icon and its tooltip."""
        if item.data(Qt.ItemDataRole.UserRole) != role or item.icon().isNull():
            if role == PLACED:
                icon = resource_path("icons", "circle-check.svg")
            elif role == TEMPLATE:
                icon = resource_path("icons", "template-field.svg")
            else:
                icon = resource_path("icons", "circle-x.svg")
            item.setIcon(QIcon(icon))
            item.setData(Qt.ItemDataRole.UserRole, role)
        item.setToolTip(self.fieldToolTip(item.text(), role))

    def fieldToolTip(self, name: str, role: str) -> str:
        """What a double-click (and a drag on the picture) does with a field."""
        if role == NOT_PLACED:
            tip = QCoreApplication.translate(
                "MainWindow",
                "Not on the picture yet. Drag over its numbers on the picture, or "
                "double-click here to put its box in the middle of the picture.",
            )
        elif role == TEMPLATE:
            tip = QCoreApplication.translate(
                "MainWindow", "Built from other fields: it has no box."
            )
        else:
            tip = QCoreApplication.translate(
                "MainWindow",
                "On the picture: drag its box to move it, or {alt}+drag on the "
                "picture to draw it again. Right-click for its actions.",
            ).format(alt=alt_key_name())
        if self.isCustomField(name):
            tip += " " + (
                QCoreApplication.translate("MainWindow", "F2 renames it.")
                if role == NOT_PLACED
                else QCoreApplication.translate(
                    "MainWindow", "Double-click to rename it."
                )
            )
        return tip

    def updateFieldToolTips(self):
        """The fields' tooltips, in the current language."""
        table = self.ui.tableWidget_boxes
        for row in range(table.rowCount()):
            item = table.item(row, 0)
            role = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
            if role in (NOT_PLACED, PLACED, TEMPLATE):
                item.setToolTip(self.fieldToolTip(item.text(), role))

    def updateFieldActionHint(self, role: str | None = None):
        """The line over the footer's button: how to place, move or remove
        the selected field's box."""
        ui = self.ui
        if role is None:
            item = self.currentFieldItem()
            role = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if role == NOT_PLACED:
            hint = QCoreApplication.translate(
                "MainWindow",
                "Drag on the picture to place it, or double-click the field",
            )
        elif role == PLACED:
            hint = QCoreApplication.translate(
                "MainWindow", "Drag the box to move it · {delete} removes it"
            ).format(delete=key_text(self.deleteKeys[0]))
        elif role == TEMPLATE:
            # the Box tab's note
            hint = QCoreApplication.translate(
                "BoxSettings",
                "This field is built from other fields (see Template): it has no "
                "box on the picture and no reading settings.",
            )
        else:
            hint = QCoreApplication.translate(
                "MainWindow",
                "Select a field, then drag over its numbers on the picture.",
            )
        label = ui.label_fieldActionHint
        if label.text() != hint:
            label.setText(hint)
        # (before a source: "Open a source to place fields on the picture")
        label.setVisible(ui.groupBox_sb_info.isEnabled())

    def updateFieldActions(self):
        """Enable the selected field's actions, and show the footer's buttons
        that apply to it: Place on picture or Remove from picture, and Delete
        field for a custom field."""
        ui = self.ui
        item = self.currentFieldItem()
        role = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        custom = item is not None and self.isCustomField(item.text())
        placed = role == PLACED
        value_item = (
            ui.tableWidget_boxes.item(item.row(), 1) if item is not None else None
        )
        ui.actionPlaceOnPicture.setEnabled(role == NOT_PLACED)
        ui.actionRemoveFromPicture.setEnabled(placed)
        ui.actionRenameField.setEnabled(custom)
        ui.actionDeleteField.setEnabled(custom)
        ui.actionResetFieldSettings.setEnabled(placed)
        held = item is not None and item.text() in self.heldValues
        ui.actionCopyValue.setEnabled(
            value_item is not None and (held or bool(value_item.text()))
        )
        # a value can be held for a field that is read (or a template)
        ui.actionHoldValue.setEnabled(role in (PLACED, TEMPLATE))
        ui.actionHoldValue.setText(
            QCoreApplication.translate("MainWindow", "Change held value...")
            if held
            else QCoreApplication.translate("MainWindow", "Hold value...")
        )
        ui.actionReleaseValue.setEnabled(held)
        # (also called while the boxes load, before there is an image_viewer)
        viewer = getattr(self, "image_viewer", None)
        ui.actionZoomToBox.setEnabled(placed and viewer is not None)
        # (a template field has no box: neither applies)
        ui.pushButton_makeBox.setVisible(not placed and role != TEMPLATE)
        ui.pushButton_makeBox.setEnabled(role == NOT_PLACED)
        ui.pushButton_removeBox.setVisible(placed)
        ui.pushButton_removeBox.setEnabled(placed)
        ui.toolButton_removeBox.setVisible(custom)
        ui.toolButton_removeBox.setEnabled(custom)
        # Del: the box off the picture, else (a custom field) the field
        delete_keys = getattr(self, "deleteKeys", [])
        ui.actionRemoveFromPicture.setShortcuts(delete_keys if placed else [])
        ui.actionDeleteField.setShortcuts([] if placed else delete_keys)
        if delete_keys:
            self.updateFieldActionHint(role)
        # a drag on the picture draws the box of a field that has none
        if viewer is not None:
            viewer.setPlacementField(item.text() if role == NOT_PLACED else None)

    def fieldContextMenu(self) -> QMenu:
        """The selected field's context menu (with the keys of its actions)."""
        ui = self.ui
        self.updateFieldActions()
        menu = QMenu(self)
        # the disabled actions say why
        menu.setToolTipsVisible(True)
        item = self.currentFieldItem()
        if item is not None and item.data(Qt.ItemDataRole.UserRole) == PLACED:
            menu.addAction(ui.actionRemoveFromPicture)
        else:
            menu.addAction(ui.actionPlaceOnPicture)
        menu.addAction(ui.actionRenameField)
        menu.addAction(ui.actionDeleteField)
        menu.addSeparator()
        menu.addAction(ui.actionResetFieldSettings)
        menu.addAction(ui.actionCopyValue)
        # send a value typed in instead of the readings, until released
        menu.addAction(ui.actionHoldValue)
        if ui.actionReleaseValue.isEnabled():
            menu.addAction(ui.actionReleaseValue)
        menu.addAction(ui.actionZoomToBox)
        self.updateFieldActionToolTips()
        return menu

    def boxContextMenu(self) -> QMenu:
        """The menu of the selected box on the picture: the field's actions
        that are about its box."""
        ui = self.ui
        self.updateFieldActions()
        menu = QMenu(self)
        menu.setToolTipsVisible(True)
        menu.addAction(ui.actionRemoveFromPicture)
        menu.addAction(ui.actionRenameField)
        menu.addSeparator()
        menu.addAction(ui.actionHoldValue)
        if ui.actionReleaseValue.isEnabled():
            menu.addAction(ui.actionReleaseValue)
        menu.addAction(ui.actionZoomToBox)
        self.updateFieldActionToolTips()
        return menu

    def showBoxContextMenu(self, name: str, position: QPoint):
        """A right-click on a box on the picture: its field is selected, and
        its menu shown."""
        item = self.currentFieldItem()
        if item is None or item.text() != name:
            self.itemSelected(name)
        item = self.currentFieldItem()
        if item is None or item.text() != name:
            return
        menu = self.boxContextMenu()
        menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        menu.popup(position)

    def updateFieldActionToolTips(self):
        """The tooltips of the field's actions in its menus: the disabled
        actions say why."""
        ui = self.ui
        standard_only = QCoreApplication.translate(
            "MainWindow", "Only custom fields can be renamed or deleted"
        )
        for action in (ui.actionRenameField, ui.actionDeleteField):
            action.setToolTip("" if action.isEnabled() else standard_only)
        ui.actionHoldValue.setToolTip(
            QCoreApplication.translate(
                "MainWindow",
                "Send a value you type to every output instead of this field's "
                "readings, until you release it",
            )
            if ui.actionHoldValue.isEnabled()
            else QCoreApplication.translate(
                "MainWindow", "Place the field on the picture first"
            )
        )

    def showFieldContextMenu(self, pos):
        table = self.ui.tableWidget_boxes
        item = self.nameItemOfRow(table.itemAt(pos))
        if item is None:
            return
        table.setCurrentItem(item)
        self.listItemClicked(item)
        menu = self.fieldContextMenu()
        menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        menu.popup(table.viewport().mapToGlobal(pos))

    def confirm(self, title: str, text: str, action_text: str) -> bool:
        """Ask before a destructive action; True to go ahead."""
        box = QMessageBox(QMessageBox.Icon.Question, title, text, parent=self)
        go = box.addButton(action_text, QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        confirmed = box.clickedButton() is go
        box.deleteLater()
        return confirmed

    def placeOnPicture(self):
        """Place on picture: the field's box, in the middle of the picture
        shown, then its settings in the Box tab."""
        item = self.currentFieldItem()
        if item is None:
            return
        self.placeFieldBox(item.text())

    def placeFieldBox(self, name: str, rect: QRectF | None = None) -> bool:
        """Put a field's box on the picture: at rect (picture pixels), or at
        its default size in the middle of the picture shown. The field is
        selected, with its box, and the Box tab shows its settings. Place on
        picture, a double-click and a box drawn on the picture all come here.
        Returns False if the field has a box already (or is a template)."""
        item = self.boxNameItem(name)
        if item is None or item.data(Qt.ItemDataRole.UserRole) != NOT_PLACED:
            return False
        self.ui.tableWidget_boxes.setCurrentItem(item)
        if not self.makeBox(rect):
            return False
        self.ui.tabWidget_inspector.setCurrentWidget(self.ui.tab_box)
        return True

    def defaultBoxRect(self, name: str, center: QPointF | None = None) -> QRectF:
        """A new box for a field: its default size, centred on center (the
        middle of the part of the picture shown by default), within the
        picture. Without a picture, its default place."""
        info = default_info_for_box_name(name)
        viewer = self.image_viewer
        if viewer is not None and viewer.hasPicture():
            if center is None:
                center = viewer.visiblePictureRect().center()
            return centered_rect(
                center, info["width"], info["height"], viewer.pictureRect()
            )
        return QRectF(info["x"], info["y"], info["width"], info["height"])

    def fieldDoubleClicked(self, item: QTableWidgetItem):
        """A double-click on a field (its name or its value): a field without
        a box gets one, in the middle of the picture shown; a custom field on
        the picture (or a template) is renamed."""
        item = self.nameItemOfRow(item)
        if item is None:
            return
        if item.data(Qt.ItemDataRole.UserRole) == NOT_PLACED:
            self.placeFieldBox(item.text())
        else:
            self.editBoxName(item)

    def boxDrawn(self, name: str, rect: QRectF):
        """A box drawn on the picture: the box of a field that has none, or
        the selected box drawn again (Alt+drag)."""
        box = self.detectionTargetsStorage.find_item_by_name(name)
        if box is None:
            if self.placeFieldBox(name, rect):
                logger.info("Drew the box of '%s' on the picture", name)
            return
        if (box.settings or {}).get("templatefield"):
            return
        box.setRect(rect.x(), rect.y(), rect.width(), rect.height())
        self.detectionTargetsStorage.edit_item(name, box)
        logger.info("Drew the box of '%s' again", name)
        self.itemSelected(name)

    def placeFieldAt(self, name: str, center: QPointF):
        """A double-click on the picture: the field's box, centred there."""
        self.placeFieldBox(name, self.defaultBoxRect(name, center))

    def removeFromPicture(self):
        """Remove from picture, after asking when the box's settings (which are
        lost) differ from the defaults."""
        item = self.currentFieldItem()
        if item is None or item.data(Qt.ItemDataRole.UserRole) != PLACED:
            return
        box = self.detectionTargetsStorage.find_item_by_name(item.text())
        changed = changed_settings(box.settings, box.name) if box is not None else []
        if changed and not self.confirm(
            QCoreApplication.translate("MainWindow", "Remove from picture"),
            QCoreApplication.translate(
                "MainWindow",
                "Remove “{name}” from the picture? Its settings go back to the "
                "defaults, so the settings you changed are lost.",
            ).format(name=item.text()),
            QCoreApplication.translate("MainWindow", "Remove"),
        ):
            return
        self.removeBox()

    def deleteField(self):
        """Delete field, after asking: the custom field, its box and settings."""
        item = self.currentFieldItem()
        if item is None or not self.isCustomField(item.text()):
            return
        if not self.confirm(
            QCoreApplication.translate("MainWindow", "Delete field"),
            QCoreApplication.translate(
                "MainWindow",
                "Delete the field “{name}”? Its box and its settings are deleted too.",
            ).format(name=item.text()),
            QCoreApplication.translate("MainWindow", "Delete"),
        ):
            return
        self.removeCustomBox()

    def renameField(self):
        item = self.currentFieldItem()
        if item is not None:
            self.editBoxName(item)

    def copyFieldValue(self):
        """Copy the selected field's value (its last good reading, or the value
        held for it)."""
        item = self.currentFieldItem()
        if item is None:
            return
        value = self.heldValues.value(item.text())
        if value is None:
            value = self.ui.tableWidget_boxes.item(item.row(), 1).text()
        if value:
            QGuiApplication.clipboard().setText(value)

    def zoomToBox(self):
        """Zoom the picture in on the selected field's box (Fit shows it all
        again)."""
        item = self.currentFieldItem()
        viewer = self.image_viewer
        if item is None or viewer is None:
            return
        box = self.detectionTargetsStorage.find_item_by_name(item.text())
        if box is None or box.width() <= 0 or box.height() <= 0:
            return
        # with some of the picture around it (the zoom readout follows)
        margin = max(box.width(), box.height()) * 0.5
        viewer.zoomToRect(QRectF(box).adjusted(-margin, -margin, margin, margin))
        viewer.selectBox(item.text())

    # --- Hold value ---------------------------------------------------------------

    def holdValue(self):
        """Hold value... (Ctrl+H): every output gets a value typed in instead
        of the selected field's readings, until it is released."""
        item = self.currentFieldItem()
        if item is None or item.data(Qt.ItemDataRole.UserRole) not in (
            PLACED,
            TEMPLATE,
        ):
            return
        name = item.text()
        held = self.heldValues.value(name)
        value = held
        if value is None:
            # the field's current value
            value = self.ui.tableWidget_boxes.item(item.row(), 1).text()
        answer = self.askHoldValue(name, value, held is not None)
        if answer is None:
            return
        choice, value = answer
        if choice == "release":
            self.releaseValue(name)
            return
        self.heldValues.hold(name, value)
        logger.info("Holding the value of '%s': %r", name, value)
        self.updateHeldUi()

    def askHoldValue(self, name: str, value: str, held: bool) -> tuple[str, str] | None:
        """Ask for the value to hold: ("hold", value), ("release", "") or None
        (cancelled)."""
        dialog = HoldValueDialog(name, value, held, self)
        result = dialog.exec()
        value = dialog.value()
        dialog.deleteLater()
        if result == RELEASE:
            return "release", ""
        if result == QDialog.DialogCode.Accepted:
            return "hold", value
        return None

    def releaseValue(self, name: str | None = None):
        """Send a held field's readings again (the selected field's by
        default)."""
        if not name:
            item = self.currentFieldItem()
            if item is None:
                return
            name = item.text()
        if self.heldValues.release(name):
            logger.info("Released the value of '%s'", name)
            self.updateHeldUi()

    def updateHeldUi(self):
        """The boxes list, the picture's labels and the field's actions show
        the held values."""
        table = self.ui.tableWidget_boxes
        for row in range(table.rowCount()):
            name_item = table.item(row, 0)
            value_item = table.item(row, 1)
            if name_item is None or value_item is None:
                continue
            held = self.heldValues.value(name_item.text())
            if value_item.data(HELD_VALUE_ROLE) != held:
                set_held(value_item, held)
        # (the boxes are loaded before there is an image_viewer)
        viewer = getattr(self, "image_viewer", None)
        if viewer is not None:
            viewer.setHeldValues(self.heldValues.values())
        self.updateFieldActions()
        table.viewport().update()

    # --- Help ---------------------------------------------------------------------

    def openUserGuide(self):
        """Help > User guide (F1): the documentation site."""
        QDesktopServices.openUrl(QUrl(USER_GUIDE_URL))

    def openCommunity(self):
        """The status bar's Feedback and Help > Ask a question or share
        feedback: ScoreSight's Discussions on GitHub."""
        QDesktopServices.openUrl(QUrl(COMMUNITY_URL))

    def keyboardShortcutGroups(self) -> list[tuple[str, list[tuple[str, str]]]]:
        """The window's keys in groups, from the actions that have them."""
        ui = self.ui
        delete_keys = ", ".join(key_text(key) for key in self.deleteKeys)
        return [
            (
                QCoreApplication.translate("MainWindow", "Window"),
                action_rows(
                    [
                        ui.actionSetupLayout,
                        ui.actionLiveLayout,
                        ui.actionPauseOutputs,
                        ui.actionReloadSources,
                        ui.actionImportConfiguration,
                        ui.actionExportConfiguration,
                        ui.actionViewLog,
                        ui.actionUserGuide,
                        ui.actionQuit,
                    ]
                ),
            ),
            (
                QCoreApplication.translate("MainWindow", "Fields"),
                action_rows(
                    [
                        ui.actionNewField,
                        ui.actionHoldValue,
                        ui.actionRenameField,
                        ui.actionCopyValue,
                    ]
                )
                + [
                    # Del goes to one of these, depending on the field
                    (
                        QCoreApplication.translate(
                            "MainWindow",
                            "Remove the selected field's box from the picture",
                        ),
                        delete_keys,
                    ),
                    (
                        QCoreApplication.translate(
                            "MainWindow",
                            "Delete the selected custom field (not on the picture)",
                        ),
                        delete_keys,
                    ),
                    (
                        QCoreApplication.translate(
                            "MainWindow",
                            "Put a field's box on the picture, or rename a custom "
                            "field",
                        ),
                        QCoreApplication.translate(
                            "MainWindow", "Double-click the field"
                        ),
                    ),
                ],
            ),
            (
                QCoreApplication.translate("MainWindow", "Picture"),
                action_rows(
                    [
                        ui.actionBinaryView,
                        ui.actionFitPicture,
                        ui.actionZoomIn,
                        ui.actionZoomOut,
                    ]
                )
                + viewer_rows(),
            ),
        ]

    def showKeyboardShortcuts(self):
        """Help > Keyboard shortcuts."""
        dialog = KeyboardShortcutsDialog(self.keyboardShortcutGroups(), self)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.open()
        self.keyboardShortcutsDialog = dialog

    def openOBSConnectModal(self):
        if self.obs_connect_modal is not None and self.obs_connect_modal.isVisible():
            self.obs_connect_modal.raise_()
            self.obs_connect_modal.activateWindow()
            return
        if self.obs_connect_modal is not None:
            # a new dialog, in the current language
            self.obs_connect_modal.deleteLater()

        # disable OBS options
        self.ui.lineEdit_sceneName.setEnabled(False)
        self.ui.checkBox_recreate.setEnabled(False)
        self.ui.pushButton_createOBSScene.setEnabled(False)

        # load the ui from "connect_obs.ui"; a child of the main window, so it
        # stays in front of it
        self.obs_modal_ui = Ui_ConnectObs()
        self.obs_connect_modal = QDialog(self)
        self.obs_modal_ui.setupUi(self.obs_connect_modal)
        self.obs_connect_modal.setWindowTitle(
            QCoreApplication.translate("MainWindow", "Connect to OBS")
        )

        # connect the "connect" button to a function
        self.obs_modal_ui.pushButton_connect.clicked.connect(
            lambda: self.connectObs(from_dialog=True)
        )
        password = self.obs_modal_ui.lineEdit_password
        self.obs_modal_ui.checkBox_showPassword.toggled.connect(
            lambda show: password.setEchoMode(
                QLineEdit.EchoMode.Normal if show else QLineEdit.EchoMode.Password
            )
        )
        # closed without connecting (Cancel): the scene controls are usable
        # again with the current connection
        self.obs_connect_modal.rejected.connect(self.obsConnectDialogClosed)

        # load the saved data from scoresight.json
        obs_data = fetch_data("scoresight.json", "obs")
        if obs_data:
            self.obs_modal_ui.lineEdit_ip.setText(obs_data["ip"])
            self.obs_modal_ui.lineEdit_port.setText(obs_data["port"])
            self.obs_modal_ui.lineEdit_password.setText(obs_data["password"])
        # show the modal
        self.obs_connect_modal.show()
        # focus the connect button
        self.obs_modal_ui.pushButton_connect.setFocus()

    def obsConnectDialogClosed(self):
        if not self.obs_modal_ui.pushButton_connect.isEnabled():
            # Cancel while connecting: ignore that attempt's result (it would
            # replace the current connection and store the cancelled settings)
            self.obs_connect_attempt += 1
            self.obsConnecting = None
        connected = self.obs_websocket_client is not None
        self.ui.lineEdit_sceneName.setEnabled(connected)
        self.ui.checkBox_recreate.setEnabled(connected)
        self.ui.pushButton_createOBSScene.setEnabled(connected)
        self.updateObsUi()
        self.refreshLiveStatus()

    @staticmethod
    def obsTarget(connection_info) -> str | None:
        """The "host:port" of an OBS connection's settings."""
        if not isinstance(connection_info, dict):
            return None
        host = str(connection_info.get("ip") or "").strip() or "localhost"
        port = str(connection_info.get("port") or "").strip()
        return f"{host}:{port}" if port else host

    def connectObs(self, from_dialog: bool = False):
        """Open a websocket connection to OBS, with the connect dialog's fields or
        the saved connection. Connecting can take seconds (or time out), so it runs
        on a background thread; obsConnectionResult handles the outcome."""
        if from_dialog:
            connection_info = {
                "ip": self.obs_modal_ui.lineEdit_ip.text(),
                "port": self.obs_modal_ui.lineEdit_port.text(),
                "password": self.obs_modal_ui.lineEdit_password.text(),
            }
            self.obs_modal_ui.pushButton_connect.setEnabled(False)
            self.obs_modal_ui.label_error.setText(
                QCoreApplication.translate("MainWindow", "Connecting...")
            )
            self.obs_modal_ui.label_error.setToolTip("")
        else:
            connection_info = fetch_data("scoresight.json", "obs")
            if not connection_info:
                return
        # a newer attempt supersedes the ones still running
        self.obs_connect_attempt += 1
        attempt = self.obs_connect_attempt
        self.obsConnecting = self.obsTarget(connection_info)

        def attempt_connection():
            client = open_obs_websocket(connection_info)
            # why it failed (recorded on this thread)
            return client, None if client else last_connect_error()

        run_in_background(
            "OBS connection",
            attempt_connection,
            lambda result: self.obs_connection_result.emit(
                result, attempt, from_dialog, connection_info
            ),
        )
        self.updateObsUi()
        if hasattr(self, "statusBarWidgets"):
            self.refreshLiveStatus()

    @Slot(object, int, bool, object)
    def obsConnectionResult(self, result, attempt, from_dialog, connection_info):
        client, error = result if isinstance(result, tuple) else (result, None)
        if attempt != self.obs_connect_attempt:
            self.closeObsClient(client)
            return
        self.obsConnecting = None
        if from_dialog and self.obs_connect_modal is not None:
            self.obs_modal_ui.pushButton_connect.setEnabled(True)
        if not client:
            target = self.obsTarget(connection_info)
            self.obsConnectError = error or ErrorInfo(ConnectionError, "")
            self.obsConnectTarget = target
            # show error in label_error
            if from_dialog and self.obs_connect_modal is not None:
                problem = describe_error(
                    output_status.OBS, self.obsConnectError, target
                )
                self.obs_modal_ui.label_error.setText(
                    QCoreApplication.translate("MainWindow", "Cannot connect to OBS")
                    + "\n"
                    + problem.detail
                )
                self.obs_modal_ui.label_error.setToolTip(problem.hint)
            self.updateObsUi()
            self.refreshLiveStatus()
            return

        # connection was successful
        self.closeObsClient(self.obs_websocket_client)
        self.obs_websocket_client = client
        self.obsAddress = obs_client_address(client) or self.obsTarget(connection_info)
        self.obsConnectedAt = time.monotonic()
        self.obsConnectError = None
        # send every current value to the (new) connection
        self.obs_last_sent.clear()
        if from_dialog:
            store_data("scoresight.json", "obs", connection_info)
            if self.obs_connect_modal is not None:
                self.obs_connect_modal.close()
        if fetch_data("scoresight.json", OBS_AUTO_CONNECT_SETTING, True) is not True:
            # connected again after a Disconnect: also at the next start
            store_data("scoresight.json", OBS_AUTO_CONNECT_SETTING, True)

        self.ui.lineEdit_sceneName.setEnabled(True)
        self.ui.checkBox_recreate.setEnabled(True)
        self.ui.pushButton_createOBSScene.setEnabled(True)

        logger.info("OBS: Connected")
        self.updateObsUi()
        self.refreshLiveStatus()

    def disconnectObs(self):
        """Close the connection to OBS (or stop connecting). The saved connection
        is kept for the connect dialog, but isn't opened at the next start until
        the user connects again."""
        # ignore connection attempts that are still running
        self.obs_connect_attempt += 1
        self.obsConnecting = None
        self.obsConnectError = None
        if self.obs_connect_modal is not None and self.obs_connect_modal.isVisible():
            # the dialog's attempt (if any) was cancelled with it
            self.obs_modal_ui.pushButton_connect.setEnabled(True)
            self.obs_modal_ui.label_error.setText("")
        client = self.obs_websocket_client
        self.obs_websocket_client = None
        self.obsAddress = None
        self.obsConnectedAt = None
        self.obs_last_sent.clear()
        self.closeObsClient(client)
        if fetch_data("scoresight.json", OBS_AUTO_CONNECT_SETTING, True) is not False:
            store_data("scoresight.json", OBS_AUTO_CONNECT_SETTING, False)
        if client is not None:
            logger.info("OBS: Disconnected")
        self.ui.lineEdit_sceneName.setEnabled(False)
        self.ui.checkBox_recreate.setEnabled(False)
        self.ui.pushButton_createOBSScene.setEnabled(False)
        self.updateObsUi()
        self.refreshLiveStatus()

    def updateObsUi(self):
        """The OBS page's buttons show the connection: Connect OBS, Connecting...
        or Change connection..., and Disconnect while connected (or
        connecting)."""
        connected = self.obs_websocket_client is not None
        connecting = self.obsConnecting is not None
        button = self.ui.pushButton_connectObs
        if connected:
            button.setText(
                QCoreApplication.translate("MainWindow", "Change connection...")
            )
            button.setToolTip(
                QCoreApplication.translate(
                    "MainWindow",
                    "Connected to OBS at {target}. Click to connect to another OBS.",
                ).format(target=self.obsAddress or "?")
            )
        elif connecting:
            button.setText(QCoreApplication.translate("MainWindow", "Connecting..."))
            button.setToolTip(
                QCoreApplication.translate(
                    "MainWindow", "Connecting to OBS at {target}..."
                ).format(target=self.obsConnecting)
            )
        else:
            button.setText(QCoreApplication.translate("MainWindow", "Connect OBS"))
            button.setToolTip(
                QCoreApplication.translate(
                    "MainWindow", "Connect to the WebSocket server of OBS Studio"
                )
            )
        self.ui.pushButton_disconnectObs.setEnabled(connected or connecting)

    @staticmethod
    def closeObsClient(client):
        """Disconnect an OBS client that is replaced or no longer used, and stop
        its pending text updates. close_obs_websocket waits for an update in
        flight (bounded by the OBS timeout), so it runs off the GUI thread."""
        if client is None:
            return
        run_in_background(
            "OBS disconnect", partial(close_obs_websocket, client), lambda _: None
        )

    @Slot()
    def getSources(self):
        # Device enumeration (DirectShow/AVFoundation/V4L) and NDI discovery
        # take a while: run them on a background thread (#33).
        if self.sources_discovery_running:
            return
        self.sources_discovery_running = True
        self.ui.pushButton_refresh_sources.setEnabled(False)
        run_in_background(
            "source discovery",
            lambda: get_camera_info() or [],
            lambda sources: self.update_sources.emit(sources or []),
        )

    @Slot(list)
    def updateSources(self, camera_sources: list[CameraInfo]):
        # only the first discovery (at startup) counts
        startup_timing.mark("sources_discovered")
        self.sources_discovery_running = False
        if self.closing:
            # the discovery finished after the window was closed: don't reopen
            # the source
            return
        self.ui.pushButton_refresh_sources.setEnabled(True)
        self.reset_playing_source()
        combo = self.ui.comboBox_camera_source
        # Removing the current camera item moves the current index, which would
        # run sourceChanged (opening another camera, or the Screen Capture
        # dialog). Go to "none" instead: the viewer is closed, and
        # restoreSelectedSource reopens the stored source below.
        combo.blockSignals(True)
        combo.setCurrentIndex(SOURCE_INDEX_NONE)
        # clear all the items after "Screen Capture"
        for _ in range(FIRST_CAMERA_SOURCE_INDEX, combo.count()):
            combo.removeItem(FIRST_CAMERA_SOURCE_INDEX)
        # populate the combobox with the sources
        for source in camera_sources:
            combo.addItem(source.description, source)
        combo.blockSignals(False)
        self.updateSourceBar()
        self.fitSourceList()
        self.updateFirstRunCameraMenu()

        self.ui.comboBox_camera_source.setEnabled(True)
        currentIndexChangedSignal = QMetaMethod.fromSignal(
            self.ui.comboBox_camera_source.currentIndexChanged
        )
        if self.ui.comboBox_camera_source.isSignalConnected(currentIndexChangedSignal):
            self.ui.comboBox_camera_source.currentIndexChanged.disconnect()
        self.ui.comboBox_camera_source.currentIndexChanged.connect(self.sourceChanged)

        # enable the source view frame
        self.ui.frame_source_view.setEnabled(True)

        self.restoreSelectedSource()

    def restoreSelectedSource(self):
        """Reopen the source stored in "source_selected", if it is available."""
        source = stored_source_value(fetch_data("scoresight.json", "source_selected"))
        if source is None:
            return
        logger.info("Source selected from storage: %s", source)
        source_type = source["type"]
        value = source.get("value")
        index = None
        if source_type == CameraInfo.CameraType.FILE:
            if isinstance(value, str) and path.exists(value):
                index = SOURCE_INDEX_FILE
        elif source_type == CameraInfo.CameraType.URL:
            if isinstance(value, str) and value.strip():
                index = SOURCE_INDEX_URL
                value = value.strip()
        elif source_type == CameraInfo.CameraType.SCREEN_CAPTURE:
            windows = dict(
                (window_id, title) for title, window_id in self.listScreenCaptures()
            )
            if value == source_bar.ENTIRE_SCREEN or value in windows:
                index = SOURCE_INDEX_SCREEN_CAPTURE
                self.sourceWindowTitle = windows.get(value)
        elif source_type == CameraInfo.CameraType.PHONE:
            index = SOURCE_INDEX_PHONE
        else:
            index = self.findCameraSourceIndex(source)
        if index is None:
            logger.info("The stored source is not available")
            return

        self.ui.comboBox_camera_source.blockSignals(True)
        self.ui.comboBox_camera_source.setCurrentIndex(index)
        self.ui.comboBox_camera_source.blockSignals(False)
        self.source_name = value if index < FIRST_CAMERA_SOURCE_INDEX else None
        self.sourceSelectionSucessful()

    @staticmethod
    def screenCaptureWindows() -> list:
        """The windows a Screen Capture source can capture, as (title, id)."""
        # imported when first used: it loads pywin32 / pyobjc's Quartz, which
        # would slow down every start
        from screen_capture_source import ScreenCapture

        return ScreenCapture.list_windows()

    @staticmethod
    def listScreenCaptures() -> list:
        """The windows a Screen Capture source can capture, as (title, id), or
        none if they can't be listed."""
        try:
            return list(MainWindow.screenCaptureWindows())
        except Exception:
            logger.exception("Could not list the windows for screen capture")
            return []

    @staticmethod
    def screenCaptureWindowIds() -> list:
        return [window[1] for window in MainWindow.listScreenCaptures()]

    def findCameraSourceIndex(self, source: dict) -> int | None:
        """The combo box index of the discovered camera/NDI source matching a
        stored source: same type and id (uuid) and name, else same type and name."""
        candidates = []
        for index in range(
            FIRST_CAMERA_SOURCE_INDEX, self.ui.comboBox_camera_source.count()
        ):
            camera_info = self.ui.comboBox_camera_source.itemData(index)
            if (
                isinstance(camera_info, CameraInfo)
                and camera_info.type == source["type"]
                and camera_info.description == source.get("description")
            ):
                if camera_info.uuid == source.get("value"):
                    return index
                candidates.append(index)
        return candidates[0] if candidates else None

    @staticmethod
    def sourceToStore(camera_info: CameraInfo) -> dict:
        """The "source_selected" setting for a source."""
        if camera_info.type in (
            CameraInfo.CameraType.FILE,
            CameraInfo.CameraType.URL,
            CameraInfo.CameraType.SCREEN_CAPTURE,
            CameraInfo.CameraType.PHONE,
        ):
            return {"type": camera_info.type, "value": camera_info.id}
        return {
            "type": camera_info.type,
            "value": camera_info.uuid,
            "description": camera_info.description,
        }

    def disconnectViewer(self):
        """Disconnect the main window's controls from the current image viewer."""
        viewer = self.connected_viewer
        self.connected_viewer = None
        if viewer is None:
            return
        for signal, slot in (
            (self.ui.pushButton_binary.clicked, viewer.toggleBinary),
            (viewer.four_corner_changed, self.updateFourCornerUi),
            (viewer.zoom_changed, self.updateZoomReadout),
            (viewer.box_drawn, self.boxDrawn),
            (viewer.place_requested, self.placeFieldAt),
            (viewer.box_menu_requested, self.showBoxContextMenu),
            (viewer.crop_drawn, self.cropDrawn),
            (viewer.crop_selection_changed, self.updateCropUi),
        ):
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass

    def closeImageViewer(self):
        """Close and delete the current image viewer.

        Closing stops its capture thread, waiting at most STOP_TIMEOUT_MS; a
        thread still blocked on its source then finishes in the background.
        Deleting the viewer is safe even then: the thread isn't a Qt child of
        the viewer (camera_thread keeps it alive until it finishes), and the
        viewer has already disconnected from it and from the settings."""
        viewer = self.image_viewer
        if viewer is None:
            return
        self.image_viewer = None
        self.sourceError = None
        self.disconnectViewer()
        # remove the image viewer from the layout frame_for_source_view_label
        self.ui.frame_for_source_view_label.layout().removeWidget(viewer)
        viewer.close()
        viewer.deleteLater()
        self.updateSourceBanner()
        self.updateFourCornerUi()
        self.updateCropUi()
        self.updateCropWarning()
        self.updateZoomReadout()

    def reset_playing_source(self):
        self.closeImageViewer()
        self.sourceWindowTitle = None
        # e.g. a source that couldn't be opened again: another one can be
        # chosen
        self.ui.frame_source_view.setEnabled(True)
        # the first-run card. It is hidden, never deleted: the .ui's
        # retranslateUi sets its texts (label_12 is its title) on a language
        # change.
        self.ui.frame_firstRun.show()
        self.updateSourceBar()
        self.updateFirstRunCard()

    def sourceChanged(self, index):
        # get the source name from the combobox
        self.source_name = None
        # an index change: picking the item again doesn't reopen its chooser
        self.sourceIndexAtPopup = None
        self.ui.groupBox_sb_info.setEnabled(False)
        self.ui.tableWidget_boxes.setEnabled(False)
        self.setViewToolsEnabled(False)
        index = self.ui.comboBox_camera_source.currentIndex()
        if index == SOURCE_INDEX_NONE:
            self.reset_playing_source()
            return
        if index in CHOOSER_SOURCE_INDEXES:
            chosen = self.askSourceValue(index)
            if chosen is None:
                # cancelled: no source (by index: its text is translated)
                self.ui.comboBox_camera_source.setCurrentIndex(SOURCE_INDEX_NONE)
                return
            self.source_name, self.sourceWindowTitle = chosen

        self.sourceSelectionSucessful()

    def askSourceValue(self, index: int) -> tuple | None:
        """Ask for the video file, the stream URL or the window to capture (the
        source combo box's item index): (value, window title or None), or None
        if cancelled."""
        if index == SOURCE_INDEX_FILE:
            logger.info("Open File selection dialog")
            # open a file dialog to select a video file
            file, _ = QFileDialog.getOpenFileName(
                self, "Open Video File", "", "Video Files (*.mp4 *.avi *.mov)"
            )
            if not file or not path.exists(file):
                logger.error("No file selected")
                return None
            logger.info("File selected: %s", file)
            return file, None
        if index == SOURCE_INDEX_URL:
            # open a dialog to enter the url
            url_dialog = QDialog()
            ui_urlsource = Ui_UrlSource()
            ui_urlsource.setupUi(url_dialog)
            url_dialog.setWindowTitle(
                QCoreApplication.translate("MainWindow", "URL Source")
            )
            # focus on url input
            ui_urlsource.lineEdit_url.setFocus()
            url_dialog.exec()  # wait for the dialog to close
            # check if the dialog was accepted
            if url_dialog.result() != QDialog.DialogCode.Accepted:
                return None
            # pasted URLs often carry spaces or a newline (#10)
            url = ui_urlsource.lineEdit_url.text().strip()
            return (url, None) if url else None
        if index == SOURCE_INDEX_SCREEN_CAPTURE:
            # open a dialog to select the screen
            screen_dialog = QDialog()
            ui_screencapture = Ui_ScreenCapture()
            ui_screencapture.setupUi(screen_dialog)
            # set width and height of the dialog
            screen_dialog.setFixedWidth(400)

            screen_dialog.setWindowTitle(
                QCoreApplication.translate(
                    "MainWindow", "Screen Capture Selection", None
                )
            )
            # populate comboBox_window with the available windows
            ui_screencapture.comboBox_window.clear()
            ui_screencapture.comboBox_window.addItem(
                QCoreApplication.translate(
                    "MainWindow", "Capture the entire screen", None
                ),
                source_bar.ENTIRE_SCREEN,
            )
            for window in self.screenCaptureWindows():
                ui_screencapture.comboBox_window.addItem(window[0], window[1])
            screen_dialog.exec()
            # check if the dialog was accepted
            if screen_dialog.result() != QDialog.DialogCode.Accepted:
                return None
            # get the window ID from the comboBox_window
            window_id = ui_screencapture.comboBox_window.currentData()
            title = (
                None
                if window_id == source_bar.ENTIRE_SCREEN
                else ui_screencapture.comboBox_window.currentText()
            )
            return window_id, title
        return None

    def itemSelected(self, item_name):
        if item_name is None:
            # clear the selected item: the Box tab explains how to select one
            self.ui.tableWidget_boxes.clearSelection()
            self.boxSettingsUiHandler.showField(None)
            self.updateFieldActions()
            return
        # select the item in the tableWidget_boxes (and only it: the list is
        # single-selection, but setSelected() doesn't deselect the others)
        item = self.boxNameItem(item_name)
        if item is None:
            return
        self.ui.tableWidget_boxes.setCurrentItem(item)
        self.listItemClicked(item)

    def fourCornersApplied(self, corners):
        # a correction was restored or picked
        self.updateFourCornerUi()

    def sourceSelectionSucessful(self):
        if self.ui.comboBox_camera_source.currentIndex() == 0:
            return

        if self.ui.comboBox_camera_source.currentIndex() == 1:
            if self.source_name is None or not path.exists(self.source_name):
                logger.error("No file selected")
                self.ui.comboBox_camera_source.setCurrentIndex(0)
                return
            logger.info("Loading file selected: %s", self.source_name)
            camera_info = CameraInfo(
                self.source_name,
                self.source_name,
                self.source_name,
                CameraInfo.CameraType.FILE,
            )
        elif self.ui.comboBox_camera_source.currentIndex() == 2:
            if self.source_name is None or self.source_name == "":
                logger.error("No url entered")
                self.ui.comboBox_camera_source.setCurrentIndex(0)
                return
            logger.info("Loading url: %s", self.source_name)
            camera_info = CameraInfo(
                self.source_name,
                self.source_name,
                self.source_name,
                CameraInfo.CameraType.URL,
            )
        elif self.ui.comboBox_camera_source.currentIndex() == 3:
            if self.source_name is None:
                logger.error("No screen capture selected")
                self.ui.comboBox_camera_source.setCurrentIndex(0)
                return
            logger.info("Loading screen capture: %s", self.source_name)
            camera_info = CameraInfo(
                self.source_name,
                self.source_name,
                self.source_name,
                CameraInfo.CameraType.SCREEN_CAPTURE,
            )
        elif self.ui.comboBox_camera_source.currentIndex() == SOURCE_INDEX_PHONE:
            logger.info("Loading the phone camera")
            camera_info = source_bar.phone_camera_info()
        else:
            if self.ui.comboBox_camera_source.currentData() is None:
                return

            logger.info(
                "Loading camera: %s", self.ui.comboBox_camera_source.currentText()
            )
            camera_info = self.ui.comboBox_camera_source.currentData()

        # remember the source (with its type) for the next start
        self.globalSettingsChanged("source_selected", self.sourceToStore(camera_info))

        # until its first frame (or its error)
        self.ui.frame_source_view.setEnabled(False)
        self.closeImageViewer()
        self.ui.frame_firstRun.hide()

        # set the pixmap to the image viewer
        self.image_viewer = ImageViewer(
            camera_info,
            self.fourCornersApplied,
            self.detectionTargetsStorage,
            self.itemSelected,
            start=False,
        )
        # its labels say HELD for the held values
        self.image_viewer.setHeldValues(self.heldValues.values())
        # a new capture plays at x1, without Binary View and stabilization
        self.ui.toolButton_speed.setText(source_bar.speed_text(1))
        self.ui.pushButton_binary.setChecked(False)
        self.ui.pushButton_stabilize.setChecked(False)
        self.image_viewer.first_frame_received_signal.connect(
            self.cameraConnectedEnableUI
        )
        self.image_viewer.error_signal.connect(self.updateError)
        # connected before the capture starts: the first readings are often the
        # only Success of a box whose value doesn't change (later ones are
        # SameNoChange), and vMix and UNO only send Success unless "Also resend unchanged values"
        self.connectViewer()
        self.applyOcrModel(opening_source=True)

        # in the first-run card's place (frame_for_source_view_label's grid)
        self.ui.frame_for_source_view_label.layout().addWidget(self.image_viewer, 0, 0)
        self.updateSourceBar()
        self.updateSourceBanner()
        self.updateFourCornerUi()
        self.updateFirstRunCard()
        self.image_viewer.startCapture()

    def connectViewer(self):
        """Connect the main window to the current image viewer and its capture
        thread. Each viewer is connected only once (the first frame is signalled
        again after e.g. a video settings change), or every result would be
        handled twice."""
        if self.image_viewer is None or self.connected_viewer is self.image_viewer:
            return
        self.disconnectViewer()
        self.connected_viewer = self.image_viewer
        viewer = self.image_viewer
        self.ui.pushButton_binary.clicked.connect(viewer.toggleBinary)
        viewer.four_corner_changed.connect(self.updateFourCornerUi)
        viewer.zoom_changed.connect(self.updateZoomReadout)
        # drawing boxes and the crop on the picture, a box's menu
        viewer.box_drawn.connect(self.boxDrawn)
        viewer.place_requested.connect(self.placeFieldAt)
        viewer.box_menu_requested.connect(self.showBoxContextMenu)
        viewer.crop_drawn.connect(self.cropDrawn)
        viewer.crop_selection_changed.connect(self.updateCropUi)
        # Del (Remove from picture) and F2 (Rename) on the selected box
        for action in (self.ui.actionRemoveFromPicture, self.ui.actionRenameField):
            viewer.addAction(action)
        self.updateFieldActions()
        if self.image_viewer.timerThread:
            self.image_viewer.timerThread.ocr_result_signal.connect(self.ocrResult)
            self.image_viewer.timerThread.update_error.connect(self.updateError)

    def cameraConnectedEnableUI(self):
        if self.image_viewer is None:
            self.updateError("Image viewer is None")
            return
        self.connectViewer()

        # enable groupBox_sb_info
        self.ui.groupBox_sb_info.setEnabled(True)
        self.ui.tableWidget_boxes.setEnabled(True)
        self.ui.frame_source_view.setEnabled(True)
        self.setViewToolsEnabled(True)

        # The boxes are not reloaded from scoresight.json here: they were loaded
        # at startup and the in-memory boxes may have newer, unsaved edits.
        self.sourceError = None
        self.updateSourceBanner()
        self.updateZoomReadout()
        self.updateCropWarning()
        self.refreshLiveStatus()

    def updateError(self, error):
        """The source failed: the source error banner says so (with Retry),
        and the view tools are disabled until it works again."""
        if not error:
            return
        logger.error(error)
        self.sourceError = error
        self.ui.frame_source_view.setEnabled(True)
        self.setViewToolsEnabled(False)
        self.updateSourceBanner()
        if hasattr(self, "statusBarWidgets"):
            self.refreshLiveStatus()

    # --- the viewer: source bar, view tools, picture adjustments, first run -------

    def setupViewer(self):
        """Connect the viewer column's controls: the source bar, the view tools,
        the Adjust picture row, the banners over the picture and the first-run
        card."""
        ui = self.ui
        # the item index when the source list was opened: picking the open
        # file, stream or screen again asks for another one
        self.sourceIndexAtPopup = None
        # what the source's dot and the first-run card's steps show
        self.sourceHealthLook = None
        self.firstRunLook = None
        self.lastOutputStatuses: list[DestinationStatus] = []
        combo = ui.comboBox_camera_source
        combo.activated.connect(self.sourceActivated)
        combo.view().installEventFilter(self)
        # the open source's name is elided to the combo box's width
        combo.installEventFilter(self)
        ui.toolButton_speed.clicked.connect(self.toggleSpeed)
        ui.toolButton_speed.hide()

        # view tools
        ui.toolButton_zoomReset.clicked.connect(self.resetZoom)
        ui.actionZoomIn.triggered.connect(self.zoomIn)
        ui.actionZoomOut.triggered.connect(self.zoomOut)
        show_osd = self.storedShowOsd()
        ui.toolButton_osd.setChecked(show_osd)
        ui.actionStatsOverlay.setChecked(show_osd)
        ui.toolButton_osd.toggled.connect(self.toggleOSD)
        ui.actionStatsOverlay.toggled.connect(
            lambda checked: ui.toolButton_osd.setChecked(checked)
        )
        # View > Smooth preview: the capture thread follows the setting
        ui.actionSmoothPreview.setChecked(
            fetch_data("scoresight.json", SMOOTH_PREVIEW_SETTING, False) is True
        )
        ui.actionSmoothPreview.toggled.connect(
            lambda checked: self.globalSettingsChanged(
                SMOOTH_PREVIEW_SETTING, bool(checked)
            )
        )
        # "400%": the readout doesn't change the row's width as it changes
        ui.label_zoom.setMinimumWidth(
            QFontMetrics(ui.label_zoom.font()).horizontalAdvance(
                source_bar.zoom_text(4.0)
            )
            + 4
        )

        # Adjust picture
        ui.pushButton_fourCorner.clicked.connect(self.fourCornerClicked)
        ui.pushButton_cancelFourCorner.clicked.connect(self.cancelFourCornerSelection)
        ui.frame_fourCornerBanner.hide()
        ui.toolButton_dragCrop.clicked.connect(self.dragCropClicked)
        ui.toolButton_resetCrop.clicked.connect(self.resetCrop)
        ui.pushButton_cancelCrop.clicked.connect(self.cancelCropSelection)
        ui.frame_cropBanner.hide()
        ui.label_cropWarning.hide()
        # the row's hint hides when the buttons need its room
        ui.widget_viewTools.installEventFilter(self)
        ui.label_adjustHint.setForegroundRole(QPalette.ColorRole.PlaceholderText)

        # the source error banner (System Settings: macOS only)
        ui.frame_sourceError.hide()
        ui.pushButton_openScreenSettings.hide()
        ui.pushButton_retrySource.clicked.connect(self.retrySource)
        ui.pushButton_chooseSource.clicked.connect(self.chooseAnotherSource)
        ui.pushButton_sourceTroubleshooting.clicked.connect(
            lambda: QDesktopServices.openUrl(
                QUrl(source_bar.SOURCE_TROUBLESHOOTING_URL)
            )
        )
        ui.pushButton_openScreenSettings.clicked.connect(
            lambda: QDesktopServices.openUrl(
                QUrl(source_bar.MACOS_SCREEN_RECORDING_SETTINGS_URL)
            )
        )

        # Tools > Collect OCR training data, and its status bar chip
        ui.actionCollectTrainingData.setChecked(
            bool(fetch_data("scoresight.json", COLLECT_TRAINING_DATA_SETTING, False))
        )
        ui.actionCollectTrainingData.toggled.connect(self.toggleTrainingData)
        self.statusBarWidgets.training_data_clicked.connect(
            self.openOCRTrainingDataDialog
        )

        # the first-run card
        self.firstRunCameraMenu = QMenu(ui.pushButton_firstRunCamera)
        ui.pushButton_firstRunCamera.setMenu(self.firstRunCameraMenu)
        for button, index in (
            (ui.pushButton_firstRunFile, SOURCE_INDEX_FILE),
            (ui.pushButton_firstRunUrl, SOURCE_INDEX_URL),
            (ui.pushButton_firstRunScreen, SOURCE_INDEX_SCREEN_CAPTURE),
        ):
            button.clicked.connect(
                lambda checked=False, index=index: self.chooseSource(index)
            )
        for label in (ui.label_firstRunBoxesHint, ui.label_firstRunOutputsHint):
            label.setForegroundRole(QPalette.ColorRole.PlaceholderText)
        # ✨ Auto crop and ✨ Auto layout
        self.autoLayoutUi = AutoLayoutUI(self)
        self.compactRows = []
        self.applyViewerStyles()
        # A narrow viewer column (at least VIEWER_MIN_WIDTH): the view tools
        # show their icons only, then go under the source; the Adjust picture
        # row drops its label; the first-run card's buttons take two lines.
        self.sourceBarRow = source_bar.CompactToolRow(
            ui.widget_4,
            buttons=[ui.pushButton_binary, ui.toolButton_osd, ui.toolButton_zoomReset],
            labels=[ui.label, ui.label_boxDisplayStyle],
            wraps=[
                (
                    ui.widget_viewOptions,
                    (0, 2),
                    (1, 0, 1, 3, Qt.AlignmentFlag.AlignRight),
                )
            ],
        )
        self.compactRows = [
            self.sourceBarRow,
            source_bar.CompactToolRow(
                ui.widget_viewTools,
                labels=[ui.label_adjustPicture],
                ignore=[ui.label_adjustHint],
                icon_buttons=[ui.toolButton_autoCrop, ui.toolButton_autoLayout],
            ),
            # Drag to crop and Reset crop go under the values
            source_bar.CompactToolRow(
                ui.widget_cropPanel,
                wraps=[
                    (
                        ui.widget_cropActions,
                        (0, 0),
                        (1, 1, 1, 8, Qt.AlignmentFlag.AlignLeft),
                    )
                ],
            ),
            source_bar.CompactToolRow(
                ui.frame_firstRun,
                wraps=[
                    (ui.pushButton_firstRunCamera, (0, 0), (0, 0)),
                    (ui.pushButton_firstRunFile, (0, 1), (0, 1)),
                    (ui.pushButton_firstRunUrl, (0, 2), (1, 0)),
                    (ui.pushButton_firstRunScreen, (0, 3), (1, 1)),
                ],
                area=ui.frame_for_source_view_label,
            ),
        ]

    def storedShowOsd(self) -> bool:
        """Whether the statistics overlay is on. Off for new settings (the
        status bar shows the same numbers); settings of a version without the
        choice keep it on, as it was then."""
        stored = fetch_data("scoresight.json", SHOW_OSD_SETTING)
        if isinstance(stored, bool):
            return stored
        show = any(
            fetch_data("scoresight.json", key) is not None
            for key in ("boxes", "source_selected")
        )
        self.globalSettingsChanged(SHOW_OSD_SETTING, show)
        return show

    def applyViewerTexts(self):
        """The viewer column's texts that are made at runtime."""
        self.updateSourceBar()
        self.updateRotateText()
        self.updateZoomReadout()
        self.updateFourCornerUi()
        self.autoLayoutUi.applyTexts()
        self.updateSourceBanner()
        self.ui.label_firstRunQuickstart.setText(
            source_bar.quickstart_link() + "<br>" + source_bar.community_link()
        )
        for row in self.compactRows:
            # the texts' widths changed
            row.refresh()
        self.updateFirstRunCameraMenu()
        self.firstRunLook = None
        self.updateFirstRunCard()
        self.updateCropWarning()
        if self.image_viewer is not None:
            # "Drag over the numbers to place ..."
            self.image_viewer.updatePlacementHint()

    def applyViewerStyles(self):
        """The colours of the viewer column's controls, from the palette (again
        when it changes, e.g. File > Appearance)."""
        if not hasattr(self, "sourceHealthLook"):
            return
        ui = self.ui
        palette = self.palette()
        # a checked toggle (Binary View, Stats, Crop, 4-corner, Stabilize) is
        # filled: on and off are told apart at a glance
        style = theme.tool_button_style(palette)
        # the AI features' buttons in their own colour
        auto_style = style + self.autoLayoutUi.styleSheet(palette)
        for row, row_style in (
            (ui.widget_4, style),
            (ui.widget_viewTools, auto_style),
            (ui.widget_cropPanel, style),
        ):
            if row.styleSheet() != row_style:
                row.setStyleSheet(row_style)
        self.autoLayoutUi.applyStyle(palette)
        icon_color = theme.button_text_color(palette)
        for button, kind in (
            (ui.pushButton_refresh_sources, "reload"),
            (ui.toolButton_videoSettings, "settings"),
            (ui.pushButton_binary, "binary"),
            (ui.toolButton_osd, "stats"),
            (ui.toolButton_zoomReset, "fit"),
        ):
            button.setIcon(theme.tool_icon(kind, icon_color))
        red = theme.color("empty", palette).name()
        ui.frame_sourceError.setStyleSheet(
            "QFrame#frame_sourceError {"
            f" background-color: {theme.tint('empty', palette).name()};"
            f" border: 1px solid {red}; border-left: 4px solid {red}; }}"
        )
        highlight = palette.color(QPalette.ColorRole.Highlight)
        for banner in (ui.frame_fourCornerBanner, ui.frame_cropBanner):
            banner.setStyleSheet(
                f"QFrame#{banner.objectName()} {{"
                f" background-color: rgba({highlight.red()}, {highlight.green()},"
                f" {highlight.blue()}, 40);"
                f" border: 1px solid {highlight.name()};"
                f" border-left: 4px solid {highlight.name()}; }}"
            )
        ui.label_cropWarning.setStyleSheet(
            f"color: {theme.color('rejected', palette).name()};"
        )
        # the Fields footer's flat buttons: in the link colour, so that they
        # still look clickable
        link = palette.color(QPalette.ColorRole.Link)
        for button in (ui.pushButton_makeBox, ui.pushButton_removeBox):
            button_palette = button.palette()
            if button_palette.color(QPalette.ColorRole.ButtonText) != link:
                # (disabled, it is greyed out as usual)
                for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive):
                    button_palette.setColor(group, QPalette.ColorRole.ButtonText, link)
                button.setPalette(button_palette)
        ui.frame_firstRun.setStyleSheet(
            "QFrame#frame_firstRun {"
            f" background-color: {palette.color(QPalette.ColorRole.Base).name()};"
            f" border: 1px solid {palette.color(QPalette.ColorRole.Mid).name()};"
            " border-radius: 8px; }"
        )
        # drawn again in the new colours
        self.sourceHealthLook = None
        self.firstRunLook = None
        self.updateFirstRunCard()

    def setViewToolsEnabled(self, enabled: bool):
        """The view tools, the Adjust picture row and the crop values work only
        while the source delivers frames."""
        for widget in (
            self.ui.widget_viewOptions,
            self.ui.widget_viewTools,
            self.ui.widget_cropPanel,
        ):
            widget.setEnabled(enabled)

    def triggerBinaryView(self):
        """View > Binary View (Ctrl+B), through the button."""
        self.ui.pushButton_binary.click()
        # the button does nothing while it's disabled: the action shows its state
        self.ui.actionBinaryView.setChecked(self.ui.pushButton_binary.isChecked())

    # the source bar

    def fitSourceList(self):
        """The source combo box is kept narrow (long camera names don't widen
        the window); its list shows the whole names."""
        view = self.ui.comboBox_camera_source.view()
        view.setMinimumWidth(
            view.sizeHintForColumn(0) + view.verticalScrollBar().sizeHint().width()
        )

    def updateSourceBar(self):
        """The source combo box shows the open file, stream or screen ("Video
        file: game.mp4", the full path in its tooltip). Video settings are for
        cameras only, the playback speed for video files only."""
        ui = self.ui
        combo = ui.comboBox_camera_source
        viewer = self.image_viewer
        camera_info = viewer.getCameraInfo() if viewer is not None else None
        current = combo.currentIndex()
        open_text = source_bar.source_combo_text(camera_info, self.sourceWindowTitle)
        full_name = source_bar.source_full_name(camera_info, self.sourceWindowTitle)
        for index, text in enumerate(source_bar.chooser_texts()):
            if index >= combo.count():
                break
            is_open = bool(open_text) and index == current
            if is_open:
                text = self.elidedSourceText(open_text)
            if combo.itemText(index) != text:
                combo.setItemText(index, text)
            combo.setItemData(
                index, full_name if is_open else None, Qt.ItemDataRole.ToolTipRole
            )
        tooltip = QCoreApplication.translate(
            "MainWindow",
            "The video source: a camera, capture card or NDI source, a video file, "
            "a stream URL or a screen capture",
        )
        combo.setToolTip(f"{full_name}\n{tooltip}" if full_name else tooltip)

        camera = (
            camera_info is not None and camera_info.type == CameraInfo.CameraType.OPENCV
        )
        ui.toolButton_videoSettings.setEnabled(camera)
        ui.toolButton_videoSettings.setToolTip(
            QCoreApplication.translate(
                "MainWindow",
                "Video settings: the resolution, frame rate and format of the "
                "camera or capture card",
            )
            if camera
            else QCoreApplication.translate(
                "MainWindow",
                "Video settings: only for cameras and capture cards",
            )
        )
        ui.toolButton_speed.setVisible(
            camera_info is not None and camera_info.type == CameraInfo.CameraType.FILE
        )

    def elidedSourceText(self, text: str) -> str:
        """text shortened in the middle to fit the source combo box (its tooltip
        has it in full)."""
        combo = self.ui.comboBox_camera_source
        option = QStyleOptionComboBox()
        combo.initStyleOption(option)
        field = combo.style().subControlRect(
            QStyle.ComplexControl.CC_ComboBox,
            option,
            QStyle.SubControl.SC_ComboBoxEditField,
            combo,
        )
        if field.width() <= 0:
            return text
        return combo.fontMetrics().elidedText(
            text, Qt.TextElideMode.ElideMiddle, field.width() - 2
        )

    def sourceActivated(self, index: int):
        """An item of the source list was picked. Picking the open video file,
        stream or screen capture again asks for another one (Cancel keeps the
        open one); picking another item is handled by sourceChanged."""
        reopened = index == self.sourceIndexAtPopup
        self.sourceIndexAtPopup = None
        if not reopened or index not in CHOOSER_SOURCE_INDEXES:
            return
        chosen = self.askSourceValue(index)
        if chosen is None:
            return
        self.source_name, self.sourceWindowTitle = chosen
        self.sourceSelectionSucessful()

    def chooseSource(self, index: int):
        """Pick a source item (e.g. from the first-run card), as in the source
        combo box."""
        combo = self.ui.comboBox_camera_source
        if not combo.isEnabled() or not 0 <= index < combo.count():
            return
        if combo.currentIndex() == index:
            self.sourceChanged(index)
        else:
            combo.setCurrentIndex(index)

    def chooseAnotherSource(self):
        combo = self.ui.comboBox_camera_source
        combo.setFocus(Qt.FocusReason.OtherFocusReason)
        combo.showPopup()

    def retrySource(self):
        """Open the failed source again."""
        if self.ui.comboBox_camera_source.currentIndex() == SOURCE_INDEX_NONE:
            return
        logger.info("Opening the source again")
        self.sourceSelectionSucessful()

    def updateSourceBanner(self):
        """The red banner over the picture: why the source can't be read and
        what to do (Retry, Choose another source, Troubleshooting), or that
        macOS doesn't let ScoreSight record the screen."""
        ui = self.ui
        viewer = self.image_viewer
        camera_info = viewer.getCameraInfo() if viewer is not None else None
        permission_missing = bool(
            camera_info is not None
            and camera_info.type == CameraInfo.CameraType.SCREEN_CAPTURE
            and source_bar.screen_recording_allowed() is False
        )
        if self.sourceError:
            headline, hint = source_bar.source_error_text(
                camera_info, self.sourceWindowTitle
            )
        elif permission_missing:
            headline, hint = source_bar.screen_recording_permission_text()
        else:
            ui.frame_sourceError.hide()
            return
        text = f"<b>{html.escape(headline, quote=False)}</b>"
        if hint:
            text += f" {html.escape(hint, quote=False)}"
        ui.label_sourceError.setText(text)
        ui.label_sourceError.setAccessibleName(f"{headline} {hint}".strip())
        ui.pushButton_retrySource.setVisible(bool(self.sourceError))
        ui.pushButton_openScreenSettings.setVisible(permission_missing)
        ui.frame_sourceError.show()

    def updateSourceHealth(self, state: str):
        """The dot before the source: green while frames arrive, amber while the
        source opens, is slow, stalls or reconnects, red when it fails (its
        shape tells the same without colour)."""
        label = self.ui.label_sourceHealth
        shape, color_name = source_look(state)
        palette = self.palette()
        color = (
            theme.color(color_name, palette)
            if color_name
            else theme.muted_color(palette)
        )
        look = (state, color.name())
        if look != self.sourceHealthLook:
            self.sourceHealthLook = look
            label.setPixmap(
                theme.state_icon(shape, color, 10).pixmap(
                    QSize(10, 10), self.devicePixelRatioF()
                )
            )
            description = source_state_description(state)
            label.setToolTip(description)
            label.setAccessibleName(description)

    # the view tools

    def updateZoomReadout(self, *_):
        """The zoom readout ("100%"): the size of a picture pixel on screen."""
        viewer = self.image_viewer
        text = ""
        if viewer is not None and getattr(viewer, "firstFrameReceived", False):
            text = source_bar.zoom_text(viewer.zoomLevel())
        self.ui.label_zoom.setText(text)

    def zoomIn(self):
        if self.image_viewer is not None and self.ui.widget_viewOptions.isEnabled():
            self.image_viewer.zoomIn()

    def zoomOut(self):
        if self.image_viewer is not None and self.ui.widget_viewOptions.isEnabled():
            self.image_viewer.zoomOut()

    # Adjust picture

    def updateRotateText(self, rotation=None):
        if rotation is None:
            rotation = fetch_data("scoresight.json", "rotation", 0)
        self.ui.toolButton_rotate.setText(source_bar.rotate_text(rotation))

    def fourCornerClicked(self):
        """4-corner never removes a correction silently: with one in place it
        offers to redo the corners or (after a confirmation) to remove it.
        While picking, it cancels the picking."""
        viewer = self.image_viewer
        if viewer is not None:
            if viewer.fourCornerSelectionMode:
                viewer.cancelFourCornerSelection()
            elif viewer.hasFourCornerCorrection():
                choice = self.askFourCornerAction()
                if choice == "redo":
                    viewer.startFourCornerSelection()
                elif choice == "remove" and self.confirmRemoveFourCornerCorrection():
                    viewer.removeFourCornerCorrection()
            else:
                viewer.startFourCornerSelection()
        # a click toggled the button: it shows the state again
        self.updateFourCornerUi()

    def askFourCornerAction(self) -> str | None:
        """The 4-corner button's menu when a correction is in place: "redo",
        "remove" or None (Cancel)."""
        menu = QMenu(self)
        redo = menu.addAction(QCoreApplication.translate("MainWindow", "Redo corners…"))
        remove = menu.addAction(
            QCoreApplication.translate("MainWindow", "Remove correction…")
        )
        menu.addSeparator()
        menu.addAction(QCoreApplication.translate("MainWindow", "Cancel"))
        button = self.ui.pushButton_fourCorner
        chosen = menu.exec(button.mapToGlobal(button.rect().bottomLeft()))
        menu.deleteLater()
        if chosen is redo:
            return "redo"
        if chosen is remove:
            return "remove"
        return None

    def confirmRemoveFourCornerCorrection(self) -> bool:
        answer = QMessageBox.question(
            self,
            QCoreApplication.translate("MainWindow", "Remove the 4-corner correction?"),
            QCoreApplication.translate(
                "MainWindow",
                "The picture will no longer be corrected. The boxes were placed on "
                "the corrected picture, so they may have to be moved.",
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        return answer == QMessageBox.StandardButton.Yes

    def cancelFourCornerSelection(self):
        if self.image_viewer is not None:
            self.image_viewer.cancelFourCornerSelection()
        self.updateFourCornerUi()

    def updateFourCornerUi(self, *_):
        """The 4-corner button is checked while a correction is in place (or
        corners are picked); while picking, the banner counts the corners."""
        ui = self.ui
        viewer = self.image_viewer
        picking = bool(viewer is not None and viewer.fourCornerSelectionMode)
        if viewer is not None:
            corrected = viewer.hasFourCornerCorrection()
        else:
            corrected = bool(fetch_data("scoresight.json", "four_corners"))
        button = ui.pushButton_fourCorner
        button.setChecked(picking or corrected)
        if picking:
            tooltip = QCoreApplication.translate(
                "MainWindow",
                "Picking the corners: click the 4 corners of the scoreboard. Click "
                "here or press Esc to cancel.",
            )
        elif corrected:
            tooltip = QCoreApplication.translate(
                "MainWindow",
                "The perspective is corrected. Click to redo the corners or to "
                "remove the correction.",
            )
        else:
            tooltip = QCoreApplication.translate(
                "MainWindow",
                "Correct the perspective: click the 4 corners of the scoreboard",
            )
        button.setToolTip(tooltip)
        ui.frame_fourCornerBanner.setVisible(picking)
        if picking:
            ui.label_fourCornerBanner.setText(
                source_bar.four_corner_banner_text(
                    viewer.fourCornersPicked(), corrected
                )
            )

    # Drag to crop

    def dragCropClicked(self):
        """Drag to crop: pick the crop on the whole picture (again: stop)."""
        viewer = self.image_viewer
        if viewer is not None:
            if viewer.cropSelectionMode:
                viewer.cancelCropSelection()
            else:
                # (it stops picking 4-corner points)
                viewer.startCropSelection()
        # a click toggled the button: it shows the state again
        self.updateCropUi()

    def cancelCropSelection(self):
        if self.image_viewer is not None:
            self.image_viewer.cancelCropSelection()
        self.updateCropUi()

    def updateCropUi(self, *_):
        """Drag to crop is checked, and the banner shown, while the crop is
        picked."""
        viewer = self.image_viewer
        picking = bool(viewer is not None and viewer.cropSelectionMode)
        self.ui.toolButton_dragCrop.setChecked(picking)
        self.ui.frame_cropBanner.setVisible(picking)

    def cropDrawn(self, rect: QRectF, frame: QSizeF):
        """A crop dragged on the whole picture (Drag to crop): the crop's
        values, the crop on, and the whole cropped picture shown. The boxes
        move with the crop (cropChanged)."""
        ui = self.ui
        left = max(0, round(rect.left()))
        top = max(0, round(rect.top()))
        right = max(0, round(frame.width() - rect.right()))
        bottom = max(0, round(frame.height() - rect.bottom()))
        logger.info(
            "Crop dragged: left %d, top %d, right %d, bottom %d",
            left,
            top,
            right,
            bottom,
        )
        for spin_box, value in (
            (ui.spinBox_leftCrop, left),
            (ui.spinBox_topCrop, top),
            (ui.spinBox_rightCrop, right),
            (ui.spinBox_bottomCrop, bottom),
        ):
            spin_box.setValue(value)
        if not ui.toolButton_topCrop.isChecked():
            ui.toolButton_topCrop.setChecked(True)
            self.cropMode()
        self.updateCropUi()
        if self.image_viewer is not None:
            # Fit (the cropped picture is fitted again when it arrives, if its
            # size changed)
            self.image_viewer.resetZoom()

    # ✨ Auto crop and ✨ Auto layout (auto_layout_ui)

    def applyAutoCrop(self, rect: QRectF, frame: QSizeF):
        """Auto crop found the scoreboard: the crop around it (rect, on the
        whole rotated picture of size frame), as if it was dragged."""
        logger.info("Auto crop: cropping to the scoreboard")
        self.cropDrawn(rect, frame)

    def applyAutoLayout(self, fields: dict[str, QRectF]):
        """Auto layout found fields (name: box on the picture): the fields
        without a box get it; those with one are moved there if the user
        says so."""
        storage = self.detectionTargetsStorage
        placed = [name for name in fields if storage.find_item_by_name(name)]
        move = False
        if placed:
            move = self.askAutoLayoutMove(list(fields), placed)
            if move is None:
                return
        changed = []
        for name, rect in fields.items():
            box = storage.find_item_by_name(name)
            if box is None:
                if self.placeFieldBox(name, rect):
                    changed.append(name)
            elif move and not (box.settings or {}).get("templatefield"):
                box.setRect(rect.x(), rect.y(), rect.width(), rect.height())
                storage.edit_item(name, box)
                changed.append(name)
        logger.info("Auto layout placed: %s", ", ".join(changed) or "nothing")

    def askAutoLayoutMove(self, found: list[str], placed: list[str]) -> bool | None:
        """Auto layout found fields of which some have boxes already: True to
        move those boxes too, False to keep them, None to place nothing."""
        box = QMessageBox(
            QMessageBox.Icon.Question,
            QCoreApplication.translate("MainWindow", "Move the boxes?"),
            QCoreApplication.translate(
                "MainWindow",
                "Auto layout found {found}. Some of them have boxes on the "
                "picture already ({placed}): move those boxes to what it found?",
            ).format(found=", ".join(found), placed=", ".join(placed)),
            parent=self,
        )
        move = box.addButton(
            QCoreApplication.translate("MainWindow", "Move them"),
            QMessageBox.ButtonRole.AcceptRole,
        )
        keep = box.addButton(
            QCoreApplication.translate("MainWindow", "Keep them"),
            QMessageBox.ButtonRole.RejectRole,
        )
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(move)
        box.exec()
        clicked = box.clickedButton()
        box.deleteLater()
        if clicked is move:
            return True
        if clicked is keep:
            return False
        return None

    def resetCrop(self):
        """Reset crop (after asking): the crop's values back to 0 and the crop
        off, so the whole picture is read again. The boxes move with the crop
        (cropChanged), so they stay over the same digits."""
        if not self.confirm(
            QCoreApplication.translate("MainWindow", "Reset the crop?"),
            QCoreApplication.translate(
                "MainWindow",
                "The whole picture will be read again, and the crop's values "
                "set to 0. The boxes move with it, so they stay over the same "
                "digits.",
            ),
            QCoreApplication.translate("MainWindow", "Reset crop"),
        ):
            return
        ui = self.ui
        logger.info(
            "Crop reset (it was: left %d, top %d, right %d, bottom %d)",
            *self.cropValues(),
        )
        for spin_box in (
            ui.spinBox_leftCrop,
            ui.spinBox_topCrop,
            ui.spinBox_rightCrop,
            ui.spinBox_bottomCrop,
        ):
            spin_box.setValue(0)
        if ui.toolButton_topCrop.isChecked():
            # (it stops Drag to crop too)
            ui.toolButton_topCrop.setChecked(False)
            self.cropMode()
        if self.image_viewer is not None:
            # Fit (the whole picture is fitted again when it arrives)
            self.image_viewer.resetZoom()

    # Tools > Collect OCR training data

    def toggleTrainingData(self, collecting: bool):
        logger.info(
            "OCR training data collection %s", "started" if collecting else "stopped"
        )
        self.globalSettingsChanged(COLLECT_TRAINING_DATA_SETTING, bool(collecting))
        self.refreshLiveStatus()

    # the first-run card

    def updateFirstRunCameraMenu(self):
        """The first-run card's Camera menu: the cameras, capture cards and NDI
        sources found."""
        menu = self.firstRunCameraMenu
        menu.clear()
        combo = self.ui.comboBox_camera_source
        for index in range(FIRST_CAMERA_SOURCE_INDEX, combo.count()):
            action = menu.addAction(combo.itemText(index))
            action.triggered.connect(
                lambda checked=False, index=index: self.chooseSource(index)
            )
        if menu.isEmpty():
            none = menu.addAction(
                QCoreApplication.translate("MainWindow", "No camera found")
            )
            none.setEnabled(False)
        menu.addSeparator()
        phone = menu.addAction(combo.itemText(SOURCE_INDEX_PHONE))
        phone.triggered.connect(lambda: self.chooseSource(SOURCE_INDEX_PHONE))
        menu.addSeparator()
        menu.addAction(self.ui.actionReloadSources)

    def firstRunSteps(self) -> tuple[bool, bool, bool]:
        """Which of the first-run card's steps are done: a source is open, a
        box is on the picture, an output is on (the HTTP server always is)."""
        source_open = self.image_viewer is not None
        # a box drawn (or placed) on the picture: a field that has one
        box_placed = any(
            not (box.settings or {}).get("templatefield")
            and box.width() > 0
            and box.height() > 0
            for box in self.detectionTargetsStorage.get_data()
        )
        output_on = any(
            status.enabled and status.switchable for status in self.lastOutputStatuses
        )
        return source_open, box_placed, output_on

    def updateFirstRunCard(self, outputs: list[DestinationStatus] | None = None):
        """The card shown while no source is open: three steps, each with a
        check mark once done."""
        ui = self.ui
        if outputs is not None:
            self.lastOutputStatuses = list(outputs)
        visible = self.image_viewer is None
        ui.frame_firstRun.setVisible(visible)
        if not visible:
            return
        steps = self.firstRunSteps()
        if steps != self.firstRunLook:
            self.firstRunLook = steps
            palette = self.palette()
            for number, (label, done) in enumerate(
                zip(
                    (
                        ui.label_firstRunStep1,
                        ui.label_firstRunStep2,
                        ui.label_firstRunStep3,
                    ),
                    steps,
                ),
                start=1,
            ):
                label.setPixmap(theme.step_pixmap(number, done, palette))
                label.setAccessibleName(
                    (
                        QCoreApplication.translate("MainWindow", "Step {number}: done")
                        if done
                        else QCoreApplication.translate("MainWindow", "Step {number}")
                    ).format(number=number)
                )
        # the sources can be picked once they were looked for
        enabled = ui.comboBox_camera_source.isEnabled()
        for button in (
            ui.pushButton_firstRunCamera,
            ui.pushButton_firstRunFile,
            ui.pushButton_firstRunUrl,
            ui.pushButton_firstRunScreen,
        ):
            button.setEnabled(enabled)

    def ocrResult(self, results: list[TextDetectionTargetWithResult]):
        # Hold value: the held fields' readings are replaced by their held
        # values (and a released field's next good reading is new), before the
        # template fields are filled in, so the templates and every output get
        # them. The OCR's own readings are still shown in the boxes list.
        readings = results
        results = self.heldValues.apply(results)
        # Plausibility holds: with a sport chosen, a change the sport doesn't
        # allow (21 -> 81) is held back (the outputs keep their value) until
        # the game counts it. Not a held or a template field: the operator's
        # value goes out as it is, and a template is built from what is sent.
        followed = results
        held_back = self.gameEngine.held_back(
            results,
            skip={
                result.name
                for result in results
                if result.name in self.heldValues or is_template_field(result)
            },
        )
        results = self.plausibilityHolds.apply(results, held_back)
        # fill in the template fields from the boxes' last good readings; a
        # template is Success when its text changed, SameNoChange otherwise
        # (in place: followed has the same template results)
        apply_template_fields(results)
        self.heldValues.finish_released(results)
        # the game follows the readings (held values and templates too, not
        # the plausibility holds), also while the outputs are paused
        events = self.gameEngine.update(followed)
        if events:
            self.gameUiHandler.eventsHappened(events)

        # The boxes list: each box's last good reading (a SameNoChange is its
        # last good reading), and the state of its latest one (a rejected or
        # empty reading is shown, but doesn't replace the value)
        now = time.monotonic()
        for reading, sent in zip(readings, results):
            if sent is not reading and is_template_field(reading):
                # a held template field isn't filled in: it keeps its text
                continue
            # (a template field was filled in in place)
            item = self.boxValueItem(reading.name)
            if item is not None:
                record_reading(item, reading.result_state, reading.result, now)

        if not self.updateOCRResults:
            # the outputs are paused (the readings above keep updating)
            return

        update_http_server(results)
        update_game_state(self.gameEngine.state())

        if self.ui.checkBox_enableOutAPI.isChecked():
            update_out_api(results)

        # update vMix, UNO and the TCP / UDP output. After a pause they also get
        # the boxes' unchanged values (which may have changed while the outputs
        # were paused), once per box: until the box's first good reading since
        resend = frozenset(self.resendAfterPause)
        if resend:
            self.resendAfterPause -= {
                result.name
                for result in results
                if result.result_state
                in (
                    TextDetectionTargetWithResult.ResultState.Success,
                    TextDetectionTargetWithResult.ResultState.SameNoChange,
                )
            }
        if self.vmixUiHandler.vmixUpdater is not None:
            self.vmixUiHandler.vmixUpdater.update_vmix(results, resend_unchanged=resend)
        if self.unoUiHandler.unoUpdater is not None:
            self.unoUiHandler.unoUpdater.update_uno(results, resend_unchanged=resend)
        self.tcpUiHandler.output.update(results, resend_unchanged=resend)

        # OBS text sources don't depend on the output folder (#30)
        self.updateObsTextSources(results)

        # files: remember the readings, write them at the "Save / s" rate
        self.fileOutput.record(results)
        self.scheduleFileOutputFlush()

    def updateObsTextSources(self, results: list[TextDetectionTargetWithResult]):
        """Send each box's good reading to its OBS text source when it differs
        from what was last sent there."""
        if self.obs_websocket_client is None:
            return
        for targetWithResult in results:
            if not file_output.is_good_reading(targetWithResult):
                continue
            source_name = (targetWithResult.settings or {}).get("obs_source_name")
            if not source_name:
                # custom boxes have no OBS source unless one is set
                continue
            if self.obs_last_sent.get(source_name) == targetWithResult.result:
                continue
            update_text_source(
                self.obs_websocket_client, source_name, targetWithResult.result
            )
            self.obs_last_sent[source_name] = targetWithResult.result

    def scheduleFileOutputFlush(self):
        """Flush the file outputs now, or when the "Save / s" throttle opens, so
        the latest values always reach the files (#6)."""
        if self.out_folder is None:
            return
        interval = 1.0 / max(1, self.ui.horizontalSlider_aggsPerSecond.value())
        delay = self.fileOutput.seconds_until_flush(interval)
        if delay <= 0:
            self.flushFileOutputs()
        elif not self.fileOutputTimer.isActive():
            self.fileOutputTimer.start(math.ceil(delay * 1000))

    def flushFileOutputs(self):
        self.fileOutputTimer.stop()
        if self.out_folder is None:
            return
        if not path.isdir(path.abspath(self.out_folder)):
            logger.warning("Output folder does not exist: %s", self.out_folder)
            # the Text files destination says so until a folder is chosen
            self.outputFolderLost = self.out_folder
            self.out_folder = None
            self.ui.lineEdit_folder.setText("")
            remove_data("scoresight.json", "output_folder")
            return
        self.fileOutput.flush(
            self.out_folder,
            self.ui.comboBox_appendMethod.currentIndex(),
            self.ui.checkBox_saveCsv.isChecked(),
            self.ui.checkBox_saveXML.isChecked(),
            self.ui.checkBox_saveJson.isChecked(),
            self.ui.checkBox_saveKeyValue.isChecked(),
        )

    def addBox(self):
        # add a new box to the tableWidget_boxes
        # find the number of custom boxes
        custom_boxes = []
        for i in range(self.ui.tableWidget_boxes.rowCount()):
            item = self.ui.tableWidget_boxes.item(i, 0)
            if item.text() not in [o["name"] for o in default_boxes]:
                custom_boxes.append(item.text())

        i = len(custom_boxes)
        new_box_name = f"Custom {i + 1}"
        custom_boxes_names = fetch_data("scoresight.json", "custom_boxes_names", [])
        # find if the name already exists
        while new_box_name in custom_boxes or new_box_name in custom_boxes_names:
            i += 1
            new_box_name = f"Custom {i + 1}"

        store_custom_box_name(new_box_name)
        item = self.appendBoxRow(new_box_name)
        self.setFieldPlacement(item, NOT_PLACED)
        # selected, ready to be placed or renamed
        self.ui.tableWidget_boxes.scrollToItem(item)
        self.itemSelected(new_box_name)

    def removeCustomBox(self):
        item = self.ui.tableWidget_boxes.currentItem()
        if not item:
            logger.info("No item selected")
            return
        if item.column() != 0:
            item = self.ui.tableWidget_boxes.item(item.row(), 0)
        # only allow removing custom boxes (before anything is removed: a default
        # box keeps its placement and settings)
        if item.text() in [o["name"] for o in default_boxes]:
            logger.info("Cannot remove default box")
            return
        self.removeBox()
        remove_custom_box_name_in_storage(item.text())
        # remove the selected item from the tableWidget_boxes
        self.ui.tableWidget_boxes.removeRow(item.row())
        # (the next row became the current one, but isn't selected)
        self.itemSelected(None)

    def fieldNameTaken(self, name: str, except_row: int = -1) -> bool:
        """Whether another field has this name. Names that differ only in case
        are the same: their text files would be the same file on Windows and
        macOS."""
        table = self.ui.tableWidget_boxes
        return any(
            table.item(row, 0).text().casefold() == name.casefold()
            for row in range(table.rowCount())
            if row != except_row
        )

    def editBoxName(self, item):
        # a double-click on a reading renames its box
        item = self.nameItemOfRow(item)
        if item is None:
            return
        if item.text() in [o["name"] for o in default_boxes]:
            # dont allow editing default boxes
            return
        old_name = item.text()
        title = QCoreApplication.translate("MainWindow", "Rename field")
        proposed = old_name
        while True:
            new_name, ok = QInputDialog.getText(
                self,
                title,
                QCoreApplication.translate("MainWindow", "New name:"),
                text=proposed,
            )
            new_name = new_name.strip()
            if not ok or new_name == "" or new_name == old_name:
                return
            if not self.fieldNameTaken(new_name, except_row=item.row()):
                break
            logger.info("Name '%s' already exists", new_name)
            QMessageBox.warning(
                self,
                title,
                QCoreApplication.translate(
                    "MainWindow",
                    "There is already a field named “{name}”. Choose another name.",
                ).format(name=new_name),
            )
            # ask again, with the name typed
            proposed = new_name
        # rename the item in the tableWidget_boxes
        rename_custom_box_name_in_storage(old_name, new_name)
        item.setText(new_name)
        item.setToolTip(
            self.fieldToolTip(new_name, item.data(Qt.ItemDataRole.UserRole))
        )
        # a held value stays held under the new name
        self.heldValues.rename(old_name, new_name)
        # rename the item in the detectionTargetsStorage (a box that isn't
        # made yet isn't there). The row was renamed in place above, and
        # detectionTargetsChanged keeps its icon and role.
        if not self.detectionTargetsStorage.rename_item(old_name, new_name):
            logger.info("Error renaming item in application storage")
        self.updateHeldUi()
        if item.isSelected():
            # the Box tab shows the new name
            self.listItemClicked(item)

    def makeBox(self, rect: QRectF | None = None) -> bool:
        """The selected field's box: at rect (picture pixels), or at its
        default size in the middle of the picture shown, with the field's
        default settings. Returns False if it has a box already."""
        item = self.nameItemOfRow(self.ui.tableWidget_boxes.currentItem())
        if not item:
            return False
        if self.detectionTargetsStorage.find_item_by_name(item.text()) is not None:
            # it has a box (or is a template) already: never two with one name
            logger.info("'%s' is already on the picture", item.text())
            return False
        if rect is None:
            rect = self.defaultBoxRect(item.text())
        # change the list icon to green checkmark
        self.setFieldPlacement(item, PLACED)

        # the field's default settings
        info = default_info_for_box_name(item.text())

        self.detectionTargetsStorage.add_item(
            TextDetectionTarget(
                rect.x(),
                rect.y(),
                rect.width(),
                rect.height(),
                item.text(),
                normalize_settings_dict({}, info),
            )
        )
        # the new box's settings (and the box selected on the picture)
        self.listItemClicked(item)
        return True

    def removeBox(self):
        item = self.ui.tableWidget_boxes.currentItem()
        if not item:
            return
        item = self.nameItemOfRow(item)
        # change the list icon to red x
        self.setFieldPlacement(item, NOT_PLACED)
        # it isn't read any more: don't show its last reading as current
        clear_reading(self.ui.tableWidget_boxes.item(item.row(), 1))
        # nor sent: a held value ends with it
        self.heldValues.forget(item.text())
        self.detectionTargetsStorage.remove_item(item.text())
        self.updateHeldUi()
        self.listItemClicked(item)

    def makeTemplateField(self, toggled: bool):
        item = self.nameItemOfRow(self.ui.tableWidget_boxes.currentItem())
        if not item:
            return
        role = item.data(Qt.ItemDataRole.UserRole)

        if not toggled:
            if role == TEMPLATE:
                self.removeBox()
            return
        if role != NOT_PLACED or not self.isCustomField(item.text()):
            # only a custom field without a box can be built from other fields
            logger.info("'%s' can't be a template field", item.text())
            self.listItemClicked(item)  # shows its real state again
            return

        # a template field: no box on the picture
        self.setFieldPlacement(item, TEMPLATE)

        self.detectionTargetsStorage.add_item(
            TextDetectionTarget(
                0,
                0,
                0,
                0,
                item.text(),
                normalize_settings_dict({"templatefield": True}, None),
            )
        )

        self.listItemClicked(item)

    def createOBSScene(self):
        """Create OBS Scene: make the scene, or with Recreate off, keep a scene
        of that name that exists already. The page says which happened."""
        scene_name = self.ui.lineEdit_sceneName.text()
        outcome = create_obs_scene_from_export(
            self.obs_websocket_client,
            scene_name,
            recreate=self.ui.checkBox_recreate.isChecked(),
        )
        self.obsSceneOutcome = (outcome, scene_name)
        self.updateObsSceneStatus()
        # the new text sources show the scene's placeholder texts (and updates
        # sent before they existed failed): send every current value again
        self.obs_last_sent.clear()

    def updateObsSceneStatus(self):
        """Under the scene's name: what Create OBS Scene did last."""
        label = self.ui.label_obsSceneStatus
        if self.obsSceneOutcome is None:
            label.hide()
            return
        outcome, name = self.obsSceneOutcome
        texts = {
            SCENE_CREATED: QCoreApplication.translate(
                "MainWindow", "Created the scene “{name}” in OBS."
            ),
            SCENE_RECREATED: QCoreApplication.translate(
                "MainWindow",
                "Made the scene “{name}” again: its sources were replaced.",
            ),
            SCENE_KEPT: QCoreApplication.translate(
                "MainWindow",
                "OBS already has a scene “{name}”: it was kept as it is. Tick "
                "Recreate to make it again.",
            ),
            SCENE_FAILED: QCoreApplication.translate(
                "MainWindow",
                "Couldn't create the scene “{name}”. Tools > View log has the details.",
            ),
        }
        label.setText(texts.get(outcome, texts[SCENE_FAILED]).format(name=name))
        problem = outcome in (SCENE_KEPT, SCENE_FAILED)
        color = theme.color(
            "empty" if outcome == SCENE_FAILED else "rejected", self.palette()
        )
        label.setStyleSheet(f"color: {color.name()};" if problem else "")
        label.show()

    def closeConfirmed(self) -> bool:
        """Whether to go on closing. With File > Ask before closing, closing
        while a source is open asks first, because it stops the reading and
        the outputs (discussion #140: the window closed by accident during a
        broadcast). A quit signal and Update now close without asking
        (close_without_asking), and so do an offscreen app (nobody could
        answer) and the end of the user's session."""
        if (
            self.closing
            or self.close_without_asking
            or self.image_viewer is None
            or not self.ui.actionAskBeforeClosing.isChecked()
            or not self.canAskBeforeClosing()
        ):
            return True
        close, ask_again = self.askToClose()
        if not close:
            logger.info("Closing cancelled")
        elif not ask_again:
            self.ui.actionAskBeforeClosing.setChecked(False)
        return close

    def canAskBeforeClosing(self) -> bool:
        app = QGuiApplication.instance()
        return QGuiApplication.platformName() != "offscreen" and not (
            app is not None and app.isSavingSession()
        )

    def askToClose(self) -> tuple[bool, bool]:
        """Ask whether to close ScoreSight: (close, ask again next time)."""
        question = QCoreApplication.translate("MainWindow", "Close ScoreSight?")
        # the question in the text too: macOS doesn't show the title
        box = QMessageBox(QMessageBox.Icon.Question, question, question, parent=self)
        box.setInformativeText(
            QCoreApplication.translate(
                "MainWindow",
                "Reading stops, and vMix, OBS, the overlays and the other "
                "outputs are no longer updated.",
            )
        )
        close = box.addButton(
            QCoreApplication.translate("MainWindow", "Close"),
            QMessageBox.ButtonRole.DestructiveRole,
        )
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        dont_ask = QCheckBox(
            QCoreApplication.translate("MainWindow", "Don't ask again")
        )
        box.setCheckBox(dont_ask)
        box.exec()
        answer = box.clickedButton() is close, not dont_ask.isChecked()
        box.deleteLater()
        return answer

    # on destroy, close the OBS connection
    def closeEvent(self, event):
        if not self.closeConfirmed():
            event.ignore()
            return
        logger.info("Closing")
        self.closing = True
        self.statusTimer.stop()
        self.saveSplitterState()
        self.closeImageViewer()

        if self.log_dialog:
            self.log_dialog.close()
            self.log_dialog = None
        # dialogs without a parent would keep the app running
        for dialog in (self.video_settings_dialog, self.obs_connect_modal):
            if dialog is not None:
                dialog.close()

        # write pending file outputs and store the boxes to scoresight.json
        self.flushFileOutputs()
        self.saveBoxes()
        # ignore OBS connection attempts that are still running
        self.obs_connect_attempt += 1
        if self.obs_websocket_client:
            self.closeObsClient(self.obs_websocket_client)
            self.obs_websocket_client = None
        # store a template being typed, close the TCP connection
        self.tcpUiHandler.close()

        super().closeEvent(event)
