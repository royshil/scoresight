"""CameraView / ImageViewer (src/camera_view.py, src/source_view.py): stopping
the capture thread, teardown and the four-corner homography."""

import threading
import time

import numpy as np
import pytest

pytest.importorskip("tesserocr")  # the views run the OCR pipeline

import camera_thread  # noqa: E402
import camera_view  # noqa: E402
import storage  # noqa: E402
from camera_info import CameraInfo  # noqa: E402
from camera_view import CameraView, compute_four_corner_homography  # noqa: E402
from storage import fetch_data, store_data  # noqa: E402

pytestmark = pytest.mark.qt


# --- four-corner homography ---------------------------------------------------------------

VALID_QUAD = [(100, 100), (500, 120), (480, 400), (90, 380)]


def test_valid_four_corners_give_a_homography():
    homography = compute_four_corner_homography(VALID_QUAD)
    assert homography is not None
    assert abs(np.linalg.det(homography)) > 1e-3


@pytest.mark.parametrize(
    "corners",
    [
        None,
        [],
        VALID_QUAD[:3],
        # the same corner clicked twice
        [(100, 100), (100, 100), (480, 400), (90, 380)],
        # four points along one edge
        [(100, 100), (200, 100), (300, 100), (400, 100)],
        # nearly collinear: a diagonal sliver that would be stretched to a square
        [(100, 100), (102, 98), (500, 500), (498, 502)],
        # self-intersecting (corners out of order)
        [(100, 100), (480, 400), (500, 120), (90, 380)],
        # concave
        [(100, 100), (500, 100), (300, 120), (100, 400)],
        # tiny
        [(10, 10), (14, 10), (14, 14), (10, 14)],
        [(0, 0), (1, float("nan")), (2, 2), (3, 3)],
    ],
)
def test_unusable_four_corners_are_rejected(corners):
    assert compute_four_corner_homography(corners) is None


# --- stopping the capture thread ----------------------------------------------------------


class BlockingCapture:
    """A source whose read() blocks (like a stalled network stream) until
    `unblock` is set."""

    def __init__(self):
        self.reading = threading.Event()
        self.unblock = threading.Event()
        self.released = False

    def isOpened(self):
        return True

    def read(self):
        self.reading.set()
        self.unblock.wait(10)
        return True, np.zeros((48, 64, 3), np.uint8)

    def get(self, prop):
        return 0.0

    def set(self, prop, value):
        pass

    def release(self):
        self.released = True


class FrameCapture(BlockingCapture):
    def read(self):
        time.sleep(0.01)
        return True, np.full((48, 64, 3), 200, np.uint8)


@pytest.fixture
def capture_factory(monkeypatch):
    """Make the views' capture threads use the given capture object."""
    captures = []

    def install(capture):
        captures.append(capture)
        monkeypatch.setattr(
            camera_thread.TimerThread, "_create_video_capture", lambda self: capture
        )
        return capture

    yield install
    for capture in captures:
        capture.unblock.set()


def file_source(name="stub"):
    return CameraInfo(name, name, name, CameraInfo.CameraType.FILE)


def test_close_does_not_wait_forever_for_a_blocked_capture(
    qtbot, monkeypatch, memory_storage, capture_factory
):
    monkeypatch.setattr(camera_view, "STOP_TIMEOUT_MS", 200)
    capture = capture_factory(BlockingCapture())
    view = CameraView(file_source(), memory_storage)
    thread = view.timerThread
    assert capture.reading.wait(5)

    started = time.monotonic()
    view.close()
    assert time.monotonic() - started < 2
    assert view.timerThread is None
    # the thread is kept alive until it finishes, and no longer reaches the UI
    assert thread.isRunning() and thread in camera_thread._active_threads
    assert storage.data_subscribers == {}

    capture.unblock.set()
    qtbot.waitUntil(lambda: thread not in camera_thread._active_threads, timeout=5000)
    assert capture.released


def test_close_stops_a_running_capture(qtbot, memory_storage, capture_factory):
    capture = capture_factory(FrameCapture())
    view = CameraView(file_source(), memory_storage)
    with qtbot.waitSignal(view.first_frame_received_signal, timeout=5000):
        pass
    thread = view.timerThread
    view.close()
    assert thread.isFinished()
    assert capture.released
    assert thread not in camera_thread._active_threads
    assert storage.data_subscribers == {}


def test_capture_starts_on_start_capture(qtbot, memory_storage, capture_factory):
    # so that a caller can connect to the thread's signals before it emits
    capture_factory(FrameCapture())
    view = CameraView(file_source(), memory_storage, start=False)
    try:
        assert not view.timerThread.isRunning()
        with qtbot.waitSignal(view.first_frame_received_signal, timeout=5000):
            view.startCapture()
        view.startCapture()  # starts it once
    finally:
        view.close()


def test_a_viewer_that_never_started_closes(memory_storage, capture_factory):
    capture = capture_factory(FrameCapture())
    view = make_viewer(memory_storage, start=False)
    view.close()
    assert view.timerThread is None
    assert not capture.released  # never opened
    assert storage.data_subscribers == {}


def test_first_frame_uses_the_threads_frame_size(
    qtbot, memory_storage, capture_factory
):
    capture_factory(FrameCapture())
    view = CameraView(file_source(), memory_storage)
    try:
        with qtbot.waitSignal(view.first_frame_received_signal, timeout=5000):
            pass
        assert (view.camera_width, view.camera_height) == (64, 48)
    finally:
        view.close()


# --- ImageViewer -----------------------------------------------------------------------------


def make_viewer(memory_storage, applied=None, start=True):
    from source_view import ImageViewer

    return ImageViewer(
        file_source(),
        applied.append if applied is not None else (lambda corners: None),
        memory_storage,
        lambda name: None,
        start=start,
    )


def test_closed_viewer_is_disconnected(qtbot, memory_storage, capture_factory):
    from PySide6.QtCore import QMetaMethod

    capture_factory(FrameCapture())
    viewer = make_viewer(memory_storage)
    data_changed = QMetaMethod.fromSignal(memory_storage.data_changed)
    assert memory_storage.isSignalConnected(data_changed)
    viewer.close()
    assert not memory_storage.isSignalConnected(data_changed)
    assert storage.data_subscribers == {}


def test_invalid_stored_four_corners_are_dropped(
    qtbot, memory_storage, capture_factory
):
    capture_factory(FrameCapture())
    store_data(
        "scoresight.json",
        "four_corners",
        [(100, 100), (100, 100), (480, 400), (90, 380)],
    )
    applied = []
    viewer = make_viewer(memory_storage, applied)
    try:
        assert viewer.timerThread.homography is None
        assert applied == []
        assert fetch_data("scoresight.json", "four_corners") is None
    finally:
        viewer.close()


def test_valid_stored_four_corners_are_applied(qtbot, memory_storage, capture_factory):
    capture_factory(FrameCapture())
    store_data("scoresight.json", "four_corners", VALID_QUAD)
    applied = []
    viewer = make_viewer(memory_storage, applied)
    try:
        assert viewer.timerThread.homography is not None
        assert len(applied) == 1
    finally:
        viewer.close()


def click(viewer, x, y):
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    position = QPointF(x, y)
    viewer.mousePressEvent(
        QMouseEvent(
            QEvent.Type.MouseButtonPress,
            position,
            position,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
    )


def test_an_invalid_four_corner_selection_is_not_a_source_error(
    qtbot, memory_storage, capture_factory
):
    # error_signal makes the main window disable the view tools (with the
    # four-corner button) until the source is reopened
    capture_factory(FrameCapture())
    viewer = make_viewer(memory_storage)
    errors = []
    viewer.error_signal.connect(errors.append)
    try:
        with qtbot.waitSignal(viewer.first_frame_received_signal, timeout=5000):
            pass
        viewer.startFourCornerSelection()
        # the same corner clicked twice
        for x, y in [(50, 50), (50, 50), (400, 300), (40, 290)]:
            click(viewer, x, y)
        assert "Invalid four-corner selection" in viewer.error_text.toPlainText()
        assert errors == []
        # the selection starts over
        assert viewer.fourCornerSelectionMode
        assert viewer.fourCorners == []
        assert viewer.timerThread.homography is None

        for x, y in [(50, 50), (400, 60), (390, 300), (40, 290)]:
            click(viewer, x, y)
        assert viewer.timerThread.homography is not None
        assert viewer.error_text is None
        assert errors == []
    finally:
        viewer.close()


def test_a_frame_processing_error_is_shown_but_not_a_source_error(
    qtbot, memory_storage, capture_factory
):
    capture_factory(FrameCapture())
    view = CameraView(file_source(), memory_storage)
    errors = []
    view.error_signal.connect(errors.append)
    try:
        view.timerThread.processing_error.emit("Error: unable to process the frame")
        assert "unable to process" in view.error_text.toPlainText()
        assert errors == []
        # a source error is still reported
        view.timerThread.update_error.emit("Error: Unable to play video stream")
        assert errors == ["Error: Unable to play video stream"]
    finally:
        view.close()


# --- the viewer: four-corner picking, nudging, zoom, labels, overlay -----------------


def press(viewer, key, modifiers=None):
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent

    event = QKeyEvent(
        QEvent.Type.KeyPress, key, modifiers or Qt.KeyboardModifier.NoModifier
    )
    viewer.keyPressEvent(event)
    return event.isAccepted()


def scene_rect(rect):
    from PySide6.QtCore import QRectF

    return QRectF(rect.x(), rect.y(), rect.width(), rect.height())


VALID_CLICKS = [(50, 50), (400, 60), (390, 300), (40, 290)]


class LargeFrames(FrameCapture):
    def read(self):
        time.sleep(0.01)
        return True, np.full((480, 640, 3), 200, np.uint8)


@pytest.fixture
def running_viewer(qtbot, memory_storage, capture_factory):
    """An ImageViewer that received its first frame (640x480)."""
    capture_factory(LargeFrames())
    viewer = make_viewer(memory_storage)
    viewer.resize(800, 600)
    with qtbot.waitSignal(viewer.first_frame_received_signal, timeout=5000):
        pass
    yield viewer
    viewer.close()


def test_four_corner_picking_keeps_the_correction_until_the_fourth_click(
    qtbot, memory_storage, capture_factory
):
    # Clicking 4-corner cleared the correction at once: every box, placed on
    # the corrected picture, was misplaced, without a way back.
    from PySide6.QtCore import Qt

    capture_factory(FrameCapture())
    store_data("scoresight.json", "four_corners", VALID_QUAD)
    viewer = make_viewer(memory_storage)
    changes = []
    viewer.four_corner_changed.connect(
        lambda: changes.append(viewer.fourCornersPicked())
    )
    try:
        with qtbot.waitSignal(viewer.first_frame_received_signal, timeout=5000):
            pass
        thread = viewer.timerThread
        previous = thread.homography
        assert viewer.hasFourCornerCorrection()

        viewer.startFourCornerSelection()
        # the corners are clicked on the picture without the correction, which
        # stays in effect (also for the OCR) meanwhile
        assert thread.preview_uncorrected
        assert thread.homography is previous
        for x, y in VALID_CLICKS[:3]:
            click(viewer, x, y)
        assert changes == [0, 1, 2, 3]
        assert thread.homography is previous
        assert fetch_data("scoresight.json", "four_corners") == [
            list(corner) for corner in VALID_QUAD
        ]

        # Esc cancels and keeps it
        assert press(viewer, Qt.Key.Key_Escape)
        assert not viewer.fourCornerSelectionMode
        assert viewer.fourCorners == []
        assert thread.homography is previous
        assert not thread.preview_uncorrected
        assert viewer.hasFourCornerCorrection()

        # an invalid 4th click starts the picking over, the correction stays
        viewer.startFourCornerSelection()
        for x, y in [(50, 50), (50, 50), (400, 300), (40, 290)]:
            click(viewer, x, y)
        assert viewer.fourCornerSelectionMode
        assert viewer.fourCornersPicked() == 0
        assert thread.homography is previous
        assert "Invalid four-corner selection" in viewer.error_text.toPlainText()

        # the 4th valid click replaces it
        for x, y in VALID_CLICKS:
            click(viewer, x, y)
        assert not viewer.fourCornerSelectionMode
        assert thread.homography is not None
        assert thread.homography is not previous
        assert not thread.preview_uncorrected
        assert viewer.error_text is None
        stored = fetch_data("scoresight.json", "four_corners")
        assert len(stored) == 4 and stored[0] != list(VALID_QUAD[0])

        viewer.removeFourCornerCorrection()
        assert thread.homography is None
        assert not viewer.hasFourCornerCorrection()
        assert fetch_data("scoresight.json", "four_corners") is None
    finally:
        viewer.close()


def test_the_boxes_hide_while_corners_are_picked(
    running_viewer, memory_storage, make_target
):
    memory_storage.add_item(make_target("Home Score", rect=(100, 100, 120, 80)))
    [box] = running_viewer.boxItems()
    running_viewer.startFourCornerSelection()
    assert not box.isVisible()
    # a box added meanwhile too
    memory_storage.add_item(make_target("Away Score", rect=(300, 100, 120, 80)))
    assert not any(item.isVisible() for item in running_viewer.boxItems())
    running_viewer.cancelFourCornerSelection()
    assert all(item.isVisible() for item in running_viewer.boxItems())


def test_the_preview_skips_the_correction_while_corners_are_picked(
    memory_storage,
):
    # the preview is the adjusted (rotated, cropped) frame, the OCR reads the
    # corrected one
    thread = camera_thread.TimerThread(file_source(), memory_storage)
    try:
        previews = []
        thread.update_signal.connect(previews.append)
        frame = np.zeros((48, 64, 3), np.uint8)
        frame[:, 32:] = 255
        thread.homography = np.array([[1, 0, 16], [0, 1, 0], [0, 0, 1]], np.float64)
        thread.preview_uncorrected = True
        thread.process_frame(frame.copy())
        assert np.array_equal(previews[-1], frame)
        thread.preview_uncorrected = False
        thread.requestPreview()
        thread.process_frame(frame.copy())
        assert not np.array_equal(previews[-1], frame)
    finally:
        thread.cleanup()


def test_arrow_keys_nudge_the_selected_box(running_viewer, memory_storage, make_target):
    from PySide6.QtCore import Qt

    memory_storage.add_item(make_target("Home Score", rect=(100, 100, 120, 80)))
    box = memory_storage.find_item_by_name("Home Score")
    # nothing selected: the arrow keys scroll as usual
    press(running_viewer, Qt.Key.Key_Right)
    assert (box.x(), box.y()) == (100, 100)

    running_viewer.selectBox("Home Score")
    assert press(running_viewer, Qt.Key.Key_Right)
    assert press(running_viewer, Qt.Key.Key_Down, Qt.KeyboardModifier.ShiftModifier)
    assert press(running_viewer, Qt.Key.Key_Left)
    assert (box.x(), box.y(), box.width(), box.height()) == (100, 110, 120, 80)
    [item] = running_viewer.boxItems()
    assert item.sceneBoxRect() == scene_rect(box)

    # within the picture (640x480)
    for _ in range(80):
        press(running_viewer, Qt.Key.Key_Right, Qt.KeyboardModifier.ShiftModifier)
    assert box.right() == 640

    # Esc deselects: the arrows don't move it any more
    assert press(running_viewer, Qt.Key.Key_Escape)
    assert running_viewer.selectedBoxName is None
    press(running_viewer, Qt.Key.Key_Left)
    assert box.right() == 640


def test_nudged_rect_stays_in_the_picture():
    from PySide6.QtCore import QRectF

    from source_view import nudged_rect

    picture = QRectF(0, 0, 640, 480)
    assert nudged_rect(QRectF(10, 10, 50, 50), -20, 5, picture) == QRectF(0, 15, 50, 50)
    assert nudged_rect(QRectF(600, 10, 50, 50), 10, 0, picture).right() == 640
    # larger than the picture: it stays where it is on that axis
    assert nudged_rect(QRectF(-5, 0, 700, 50), 10, 0, picture).left() == -5
    # no picture yet
    assert nudged_rect(QRectF(0, 0, 5, 5), -3, 0, QRectF()) == QRectF(-3, 0, 5, 5)


def test_zoom_and_fit(running_viewer):
    from source_view import MAX_ZOOM, MIN_ZOOM

    zooms = []
    running_viewer.zoom_changed.connect(zooms.append)
    fitted = running_viewer.zoomLevel()
    assert running_viewer.zoomIn()
    assert running_viewer.zoomLevel() == pytest.approx(fitted * 1.25)
    assert zooms[-1] == pytest.approx(fitted * 1.25)
    for _ in range(30):
        running_viewer.zoomIn()
    assert running_viewer.zoomLevel() == pytest.approx(MAX_ZOOM)
    assert not running_viewer.zoomIn()
    for _ in range(40):
        running_viewer.zoomOut()
    assert running_viewer.zoomLevel() == pytest.approx(min(MIN_ZOOM, fitted))
    running_viewer.resetZoom()
    assert running_viewer.zoomLevel() == pytest.approx(fitted)
    assert zooms[-1] == pytest.approx(fitted)


def test_labels_cover_no_other_box(running_viewer, memory_storage, make_target):
    from resizable_rect import LABEL_BELOW_LEFT

    # two boxes one above the other: the upper one's label can't go below it
    memory_storage.add_item(make_target("Home Score", rect=(100, 100, 120, 60)))
    memory_storage.add_item(make_target("Home Fouls", rect=(100, 170, 120, 60)))
    items = {item.name: item for item in running_viewer.boxItems()}
    scale = running_viewer.zoomLevel()
    upper = items["Home Score"]
    lower = items["Home Fouls"]
    assert lower.label.placement == LABEL_BELOW_LEFT
    assert upper.label.placement != LABEL_BELOW_LEFT
    upper_label = upper.labelRectInScene(upper.label.placement, scale)
    lower_label = lower.labelRectInScene(lower.label.placement, scale)
    assert not upper_label.intersects(lower.sceneBoxRect())
    assert not upper_label.intersects(upper.sceneBoxRect())
    assert not upper_label.intersects(lower_label)


def test_the_statistics_overlay_follows_its_setting(running_viewer, qtbot):
    # off by default; fixed size at the viewer's top-left, translated
    running_viewer.show()
    assert not running_viewer.osd.isVisible()
    store_data("scoresight.json", "show_osd", True)
    qtbot.waitUntil(lambda: "Frames/s" in running_viewer.osd.text(), timeout=5000)
    qtbot.waitUntil(running_viewer.osd.isVisible, timeout=5000)
    assert "Resolution: 640×480" in running_viewer.osd.text()
    position = running_viewer.osd.pos()
    running_viewer.zoomIn()
    assert running_viewer.osd.pos() == position  # not moved by the zoom
    store_data("scoresight.json", "show_osd", False)
    assert not running_viewer.osd.isVisible()


def test_smooth_preview_refreshes_the_picture_many_times_a_second(
    qtbot, memory_storage, capture_factory
):
    store_data("scoresight.json", "smooth_preview", True)
    capture_factory(FrameCapture())
    viewer = make_viewer(memory_storage)
    try:
        with qtbot.waitSignal(viewer.first_frame_received_signal, timeout=5000):
            pass
        shown = []
        viewer.timerThread.update_signal.connect(shown.append)
        qtbot.wait(1000)
        # about 1 a second without it; the viewer says when each one arrived
        assert len(shown) >= 5
        assert viewer.timerThread._preview_shown is not None
        store_data("scoresight.json", "smooth_preview", False)
        qtbot.wait(100)
        shown.clear()
        qtbot.wait(1000)
        assert len(shown) <= 2
    finally:
        viewer.close()


def test_a_source_error_is_not_drawn_over_the_picture(running_viewer):
    errors = []
    running_viewer.error_signal.connect(errors.append)
    running_viewer.timerThread.update_error.emit("Error: Unable to play video stream")
    assert errors == ["Error: Unable to play video stream"]
    # the main window's source banner says it
    assert running_viewer.error_text is None


def test_a_resize_keeps_the_zoom_unless_the_picture_is_fitted(running_viewer, qapp):
    running_viewer.show()
    qapp.processEvents()
    fitted = running_viewer.zoomLevel()
    # fitted: a smaller viewer fits it again
    running_viewer.resize(400, 300)
    smaller = running_viewer.zoomLevel()
    assert smaller < fitted
    # zoomed in: a banner over the viewer (a resize) keeps the zoom
    running_viewer.zoomIn()
    qapp.processEvents()  # the zoom is done
    zoomed = running_viewer.zoomLevel()
    running_viewer.resize(400, 260)
    assert running_viewer.zoomLevel() == pytest.approx(zoomed)
    running_viewer.resetZoom()
    running_viewer.resize(800, 600)
    assert running_viewer.zoomLevel() == pytest.approx(fitted)
