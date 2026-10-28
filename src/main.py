"""ScoreSight entry point.

Command-line options:
  --profile NAME  use the settings file scoresight-NAME.json (SCORESIGHT_PROFILE)
  --port N        serve the HTTP API on port N (default 18099)
  --self-test     check the installation headlessly, print SELF-TEST OK, exit 0

Qt's own options (for example -platform offscreen or -style fusion) are passed
through to QApplication.

The app modules are imported only after --profile has been applied: some of them
read (and subscribe to) settings when they are imported.

Startup is timed from here on (startup_timing, imported first): the log gets a
"Startup: ..." line once the app is ready.
"""

# first: the time it is imported is "main.py started"
import startup_timing

import argparse
import importlib
import os
import platform
import signal
import sys
import traceback

DEFAULT_HTTP_PORT = 18099
DEFAULT_LOCALE = "en_US"

# Every app module, imported by --self-test. The frozen app has no src/ folder
# to list, so this is explicit (tests/test_app_main.py keeps it complete). The
# platform-specific modules are imported through screen_capture_source.
SELF_TEST_MODULES = (
    "api_output",
    "api_ui_handler",
    "app_update",
    "app_update_ui",
    "auto_layout",
    "auto_layout_ui",
    "base_video_capture",
    "box_settings_ui_handler",
    "camera_info",
    "camera_thread",
    "camera_view",
    "defaults",
    "destinations_view",
    "file_output",
    "frame_stabilizer",
    "game_state",
    "game_ui_handler",
    "get_camera_info",
    "gui_garbage_collector",
    "held_values",
    "http_server",
    "keyboard_shortcuts",
    "log_view",
    "mainwindow",
    "ndi",
    "obs_ui_handler",
    "obs_websocket",
    "ocr_models",
    "ocr_training_data",
    "output_status",
    "output_worker",
    "overlay_feed",
    "overlay_ui_handler",
    "overlays",
    "phone_camera",
    "plausibility_holds",
    "ppocr_engine",
    "readings_view",
    "resizable_rect",
    "resource_path",
    "sc_logging",
    "screen_capture_source",
    "source_bar",
    "source_view",
    "sports",
    "startup_timing",
    "status_bar",
    "storage",
    "tcp_output",
    "tcp_ui_handler",
    "template_fields",
    "tesseract",
    "text_detection_target",
    "theme",
    "training_dojo",
    "ui_about",
    "ui_connect_obs",
    "ui_log_view",
    "ui_mainwindow",
    "ui_ocr_training_data_dialog",
    "ui_screen_capture",
    "ui_tcp_output",
    "ui_training_dojo",
    "ui_update_available",
    "ui_url_source",
    "ui_video_settings",
    "uno_output",
    "uno_ui_handler",
    "update_check",
    "version",
    "video_settings",
    "vmix_output",
    "vmix_ui_handler",
)

# Bundled files the app can't work without (relative to resource_path()).
SELF_TEST_RESOURCES = (
    ("tesseract", "tessdata", "daktronics.traineddata"),
    ("tesseract", "tessdata", "scoreboard_general.traineddata"),
    ("tesseract", "tessdata", "eng.traineddata"),
    ("tesseract", "tessdata", "scoreboard_general_large.traineddata"),
    # the PP-OCR models' license (the models themselves: see _self_test_ocr)
    ("ocr_models", "ppocr", "LICENSE"),
    ("ocr_models", "ppocr", "NOTICE"),
    ("translations", f"scoresight_{DEFAULT_LOCALE}.qm"),
    ("icons", "circle-check.svg"),
    ("icons", "circle-x.svg"),
    ("icons", "template-field.svg"),
    ("obs_data", "Scoresight_OBS_scene_collection.json"),
    ("casparcg", "scoresight_scorebug.html"),
    ("overlays", "client.js"),
    ("overlays", "client-worker.js"),
    ("overlays", "overlay.css"),
    ("overlays", "example.html"),
)

SELF_TEST_TEXT = "45"


def _port(value: str) -> int:
    try:
        port = int(value)
    except ValueError:
        port = 0
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError(f"invalid port: {value!r} (use 1-65535)")
    return port


def _profile(value: str) -> str:
    value = value.strip()
    if not value:
        raise argparse.ArgumentTypeError("the profile name can't be empty")
    return value


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scoresight",
        description="ScoreSight: real-time scoreboard OCR.",
        epilog="Qt options such as -platform offscreen are passed on to Qt.",
    )
    parser.add_argument(
        "--profile",
        metavar="NAME",
        type=_profile,
        help="use the settings file scoresight-NAME.json instead of scoresight.json",
    )
    parser.add_argument(
        "--port",
        metavar="N",
        type=_port,
        default=DEFAULT_HTTP_PORT,
        help=f"HTTP server port (default {DEFAULT_HTTP_PORT})",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="check the installation without opening a window, then exit",
    )
    return parser


def parse_args(argv: list[str]) -> tuple[argparse.Namespace, list[str]]:
    """Parse ScoreSight's options from argv (without the program name). Returns
    the options and the remaining arguments, which are meant for Qt."""
    return build_arg_parser().parse_known_args(argv)


def apply_profile(profile: str | None):
    """Select the settings profile. Must run before storage-dependent modules
    are imported."""
    if profile:
        os.environ["SCORESIGHT_PROFILE"] = profile


def find_translation_file(locale_names, translations_dir: str) -> str | None:
    """The best scoresight_<locale>.qm in translations_dir for the first locale
    name that has one, e.g. "de_AT" or "de-AT" -> scoresight_de_DE.qm.

    An exact match wins; otherwise a translation for the same language is used
    (preferring the language's "home" region, so pt_AO -> pt_PT).
    """
    try:
        file_names = os.listdir(translations_dir)
    except OSError:
        return None
    available = {
        name[len("scoresight_") : -len(".qm")]: name
        for name in file_names
        if name.startswith("scoresight_") and name.endswith(".qm")
    }
    for locale_name in locale_names:
        if not locale_name:
            continue
        locale_name = locale_name.replace("-", "_")
        if locale_name in available:
            return os.path.join(translations_dir, available[locale_name])
        language = locale_name.split("_")[0].lower()
        same_language = sorted(
            code for code in available if code.split("_")[0].lower() == language
        )
        if same_language:
            home = f"{language}_{language.upper()}"
            best = home if home in same_language else same_language[0]
            return os.path.join(translations_dir, available[best])
    return None


def load_translator(app, stored_language: str | None):
    """Install the translation for the Language menu choice, or else the system
    locale, falling back to English."""
    from PySide6.QtCore import QLocale, QTranslator

    from resource_path import resource_path

    system_locale = QLocale.system()
    candidates = [stored_language, *system_locale.uiLanguages(), system_locale.name()]
    translations_dir = resource_path("translations")
    locale_file = find_translation_file(candidates, translations_dir)
    if locale_file is None:
        locale_file = os.path.join(translations_dir, f"scoresight_{DEFAULT_LOCALE}.qm")
    translator = QTranslator(app)
    if translator.load(locale_file):
        app.installTranslator(translator)
    return translator


def close_splash_screen():
    # The PyInstaller splash screen (only the Windows build has one) stays up
    # until closed. Its bootloader passes the connection in _PYI_SPLASH_IPC;
    # importing pyi_splash without it (it is bundled in the other builds too)
    # logs a warning with a traceback.
    if "_PYI_SPLASH_IPC" not in os.environ:
        return
    try:
        import pyi_splash  # type: ignore

        pyi_splash.close()
    except ImportError:
        pass


# Signals that close the app like closing its window: Ctrl+C in a terminal,
# `kill`/service stop on macOS and Linux, Ctrl+Break on Windows.
QUIT_SIGNALS = ("SIGINT", "SIGTERM", "SIGBREAK")
# How often Qt's event loop lets the interpreter run pending signal handlers.
SIGNAL_POLL_MS = 250


def install_quit_signal_handlers(app, window):
    """Make QUIT_SIGNALS close window, so the usual shutdown runs (boxes saved,
    capture thread, HTTP server and outputs stopped). Python runs signal
    handlers only when it gets control, which Qt's event loop doesn't give it
    by itself, so a timer wakes it up. Returns the timer."""
    from PySide6.QtCore import QTimer

    def close_window(signum, frame):
        # without File > Ask before closing's question (MainWindow)
        window.close_without_asking = True
        # queued: the handler may run in the middle of another Python slot
        QTimer.singleShot(0, window.close)
        # a dialog without a parent (Video Settings, Connect to OBS, a modal
        # source dialog) is a window of its own and would otherwise keep the
        # event loop running after the main window closed
        QTimer.singleShot(0, app.quit)

    for name in QUIT_SIGNALS:
        signum = getattr(signal, name, None)
        if signum is not None:
            signal.signal(signum, close_window)
    timer = QTimer(app)
    timer.timeout.connect(lambda: None)
    timer.start(SIGNAL_POLL_MS)
    return timer


# console control handlers registered by attach_console_for_quit_signals (a
# reference keeps each ctypes callback alive)
_console_ctrl_handlers = []


def attach_console_for_quit_signals(app) -> bool:
    """On Windows, let Ctrl+C and Ctrl+Break stop a headless (offscreen)
    instance of the windowed build. That build has no console, so console
    control events never reached it, and offscreen it has no window to close:
    it could only be killed. Attach it to the console of the program that
    started it, if there is one (AttachConsole fails harmlessly when the
    process already has a console or the parent has none). A visible window is
    closed as usual, so this is only done offscreen. Returns whether it
    attached."""
    if sys.platform != "win32" or app.platformName() != "offscreen":
        return False
    import _thread
    import ctypes

    ATTACH_PARENT_PROCESS = -1
    CTRL_C_EVENT, CTRL_BREAK_EVENT = 0, 1
    try:
        kernel32 = ctypes.WinDLL("kernel32")
        if not kernel32.AttachConsole(ATTACH_PARENT_PROCESS):
            return False
    except (AttributeError, OSError):
        return False
    from ctypes import wintypes

    # Attaching drops the C runtime's console control handler, which turns
    # Ctrl+C and Ctrl+Break into SIGINT and SIGBREAK (the console's default
    # handler would end the process right away): forward them again.
    signals = {CTRL_C_EVENT: signal.SIGINT, CTRL_BREAK_EVENT: signal.SIGBREAK}

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)
    def forward(event):
        signum = signals.get(event)
        if signum is None:
            return False  # e.g. the console is closing: the default handling
        _thread.interrupt_main(signum)
        return True

    kernel32.SetConsoleCtrlHandler(forward, True)
    _console_ctrl_handlers.append(forward)
    return True


# How long after the first event loop pass the startup timing waits for the
# background startup work (video source discovery) before it is logged.
STARTUP_REPORT_WAIT_S = 5.0
STARTUP_REPORT_POLL_MS = 100


def report_startup_when_ready(app):
    """Mark the first event loop pass, then log the startup timing (and write
    the SCORESIGHT_STARTUP_REPORT file) once the background startup work is
    done, or STARTUP_REPORT_WAIT_S later. Never blocks. Returns the timer."""
    import time

    from PySide6.QtCore import QTimer

    timer = QTimer(app)
    timer.setInterval(STARTUP_REPORT_POLL_MS)
    deadline = 0.0

    def poll():
        if startup_timing.background_done() or time.monotonic() >= deadline:
            timer.stop()
            startup_timing.finish()

    def idle():
        nonlocal deadline
        startup_timing.mark("event_loop_idle")
        deadline = time.monotonic() + STARTUP_REPORT_WAIT_S
        if startup_timing.background_done():
            startup_timing.finish()
        else:
            timer.start()

    timer.timeout.connect(poll)
    QTimer.singleShot(0, idle)
    return timer


def run_app(args: argparse.Namespace, qt_args: list[str]) -> int:
    from PySide6.QtWidgets import QApplication

    from gui_garbage_collector import GuiThreadGarbageCollector
    from http_server import stop_http_server
    from mainwindow import MainWindow, apply_color_scheme
    from output_worker import stop_all_workers
    from sc_logging import enable_crash_traces, logger
    from storage import fetch_data

    enable_crash_traces()
    startup_timing.mark("modules_imported")
    app = QApplication([sys.argv[0], *qt_args])
    startup_timing.mark("qapplication_created")
    # before any background thread starts: collect reference cycles only on the
    # GUI thread, where finalizing Qt objects is safe (kept until the app ends)
    garbage_collector = GuiThreadGarbageCollector(app)  # noqa: F841
    apply_color_scheme(fetch_data("scoresight.json", "color_scheme"))
    translator = load_translator(app, fetch_data("scoresight.json", "language"))

    main_window = MainWindow(translator, app, http_port=args.port)
    startup_timing.mark("main_window_created")
    main_window.show()
    startup_timing.mark("window_shown")
    if attach_console_for_quit_signals(app):
        logger.info("Attached to the parent console: Ctrl+C or Ctrl+Break quits")
    install_quit_signal_handlers(app, main_window)
    report_startup_when_ready(app)

    exit_code = app.exec()
    # quit before the startup timing was logged
    startup_timing.finish()
    logger.info("Exiting...")
    stop_http_server()
    phone_camera = sys.modules.get("phone_camera")
    if phone_camera is not None:
        phone_camera.stop_server()
    # The output threads are daemons and never block the exit; give a send in
    # flight (vMix, UNO, OBS, outbound API) a moment to finish.
    stop_all_workers(timeout=2)
    return exit_code


# --- self-test --------------------------------------------------------------------


def _attach_parent_console():
    # A windowed (no console) Windows build has no stdout. Attach to the console
    # of the shell that started it, so that the self-test result is visible.
    if sys.platform != "win32" or sys.stdout is not None:
        return
    import ctypes

    if ctypes.windll.kernel32.AttachConsole(-1):  # ATTACH_PARENT_PROCESS
        sys.stdout = open("CONOUT$", "w", encoding="utf-8", errors="replace")
        sys.stderr = sys.stdout


def _render_text_image(text: str):
    """A white-on-black grayscale image of text in OpenCV's Hershey font."""
    import cv2
    import numpy as np

    font, scale, thickness, pad = cv2.FONT_HERSHEY_SIMPLEX, 3, 6, 20
    (width, height), baseline = cv2.getTextSize(text, font, scale, thickness)
    image = np.zeros((height + baseline + 2 * pad, width + 2 * pad), np.uint8)
    cv2.putText(
        image, text, (pad, pad + height), font, scale, 255, thickness, cv2.LINE_AA
    )
    return image


# How long the self-test waits for a PP-OCR model to load (it takes well under
# a second; a cold start of a frozen app on a slow disk takes longer).
SELF_TEST_PPOCR_LOAD_TIMEOUT_S = 60
# the PP-OCR choices the self-test reads with (ppocr_engine.SMALL, TINY, AUTO)
PPOCR_SELF_TEST_MODELS = ("ppocr:small", "ppocr:tiny", "ppocr:auto")


def _self_test_ocr(frozen: bool = False) -> str:
    """OCR SELF_TEST_TEXT with every bundled model: the Tesseract ones and,
    where they are installed, the PP-OCR ones (a frozen build must have them;
    from source they need scripts/fetch_models.py)."""
    import cv2

    import ppocr_engine
    from defaults import default_info_for_box_name, normalize_settings_dict
    from tesseract import TextDetector
    from text_detection_target import TextDetectionTarget

    gray = _render_text_image(SELF_TEST_TEXT)
    color = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    box_name = "Home Score"
    target = TextDetectionTarget(
        0,
        0,
        gray.shape[1],
        gray.shape[0],
        box_name,
        normalize_settings_dict({}, default_info_for_box_name(box_name)),
        [],
    )
    models = {
        "daktronics": TextDetector.OcrModelIndex.DAKTRONICS,
        "scoreboard_general": TextDetector.OcrModelIndex.SCOREBOARD_GENERAL,
        "scoreboard_general_large": TextDetector.OcrModelIndex.SCOREBOARD_GENERAL_LARGE,
        "eng": TextDetector.OcrModelIndex.GENERAL_ENGLISH,
    }
    detector = TextDetector(TextDetector.OcrModelIndex.SCOREBOARD_GENERAL)
    reads = {}
    skipped = []
    try:
        for name, index in models.items():
            # setOcrModel keeps the previous model when one fails to load
            if not detector.setOcrModel(index):
                raise RuntimeError(f"the OCR model {name!r} did not load")
            results = detector.detect_multi_text(binary, gray, [target])
            if len(results) != 1:
                raise RuntimeError(f"OCR with {name!r} returned {len(results)} results")
            reads[name] = results[0].text
        for model_id in PPOCR_SELF_TEST_MODELS:
            reason = ppocr_engine.unavailable_reason(model_id)
            if reason is not None:
                if frozen:
                    raise RuntimeError(f"PP-OCR model {model_id}: {reason}")
                skipped.append(f"{model_id} ({reason})")
                continue
            if not detector.setOcrModel(model_id) or not detector.wait_for_engine(
                SELF_TEST_PPOCR_LOAD_TIMEOUT_S
            ):
                error = detector.engine_status().ppocr_error
                raise RuntimeError(f"the OCR model {model_id!r} did not load: {error}")
            results = detector.detect_multi_text(binary, gray, [target], color=color)
            if len(results) != 1:
                raise RuntimeError(
                    f"OCR with {model_id!r} returned {len(results)} results"
                )
            reads[model_id] = results[0].text
    finally:
        if detector.api is not None:
            detector.api.End()
            detector.api = None
    # The scoreboard models are trained on LED/LCD digits; the general English
    # model and PP-OCR must read the rendered font exactly.
    for name in ("eng", *PPOCR_SELF_TEST_MODELS):
        if name in reads and reads[name] != SELF_TEST_TEXT:
            raise RuntimeError(
                f"OCR with {name!r} read {reads[name]!r} instead of {SELF_TEST_TEXT!r}"
            )
    text = ", ".join(f"{name}={text!r}" for name, text in reads.items())
    if skipped:
        text += f"; WARNING: not installed: {', '.join(skipped)}"
    return text


def _self_test_steps():
    """Yield a line per completed check; raise on the first failure."""
    # The self-test never shows a window, so it doesn't need a display.
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    frozen = bool(getattr(sys, "frozen", False))

    from version import __version__

    yield (
        f"ScoreSight {__version__} self-test: Python {platform.python_version()}, "
        f"{platform.platform()}{' (frozen)' if frozen else ''}"
    )

    for module_name in SELF_TEST_MODULES:
        importlib.import_module(module_name)
    yield f"imported {len(SELF_TEST_MODULES)} modules"

    from sc_logging import log_file_path
    from storage import get_storage_path

    yield f"settings file: {get_storage_path('scoresight.json')}"
    yield f"log file: {log_file_path}"

    from resource_path import resource_path

    missing = [
        os.path.join(*parts)
        for parts in SELF_TEST_RESOURCES
        if not os.path.isfile(resource_path(*parts))
    ]
    if missing:
        raise RuntimeError(f"missing bundled files: {', '.join(missing)}")
    yield f"bundled files present in {resource_path()}"

    from PySide6 import __version__ as pyside_version
    from PySide6.QtCore import QTranslator, qVersion
    from PySide6.QtWidgets import QApplication, QMainWindow

    from ui_mainwindow import Ui_MainWindow

    app = QApplication.instance() or QApplication([sys.argv[0]])
    window = QMainWindow()
    Ui_MainWindow().setupUi(window)
    window.deleteLater()
    translator = QTranslator()
    if not translator.load(resource_path("translations", "scoresight_de_DE.qm")):
        raise RuntimeError("the translations don't load")
    yield (
        f"Qt {qVersion()} (PySide6 {pyside_version}, platform "
        f"{app.platformName()}): main window UI and translations load"
    )

    yield f"OCR with every bundled model: {_self_test_ocr(frozen)}"

    import uvicorn

    async def asgi_app(scope, receive, send):
        pass

    # resolves uvicorn's dynamically imported protocol/loop modules
    uvicorn.Config(asgi_app, loop="asyncio", ws="none", log_config=None).load()
    yield f"HTTP server (uvicorn {uvicorn.__version__}) loads"

    import tempfile
    from pathlib import Path

    import phone_camera

    with tempfile.TemporaryDirectory() as directory:
        yield f"phone camera: {phone_camera.self_test(Path(directory))}"

    from get_camera_info import get_camera_info

    try:
        sources = get_camera_info()
    except Exception as e:
        # From source the native camera enumerator is optional (it has to be
        # built); a frozen build must include it.
        if frozen:
            raise
        yield f"WARNING: video source discovery failed: {e!r}"
    else:
        yield f"video source discovery found {len(sources)} source(s)"


def run_self_test() -> int:
    _attach_parent_console()
    from sc_logging import enable_crash_traces

    enable_crash_traces()
    try:
        for line in _self_test_steps():
            print(line, flush=True)
    except Exception as e:
        traceback.print_exc()
        print(f"SELF-TEST FAILED: {e}", flush=True)
        return 1
    print("SELF-TEST OK", flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    args, qt_args = parse_args(sys.argv[1:] if argv is None else argv)
    apply_profile(args.profile)
    startup_timing.mark("args_parsed")
    close_splash_screen()
    if args.self_test:
        return run_self_test()
    return run_app(args, qt_args)


if __name__ == "__main__":
    sys.exit(main())
