from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsView,
    QGraphicsScene,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QLabel,
)
from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtGui import QColor, QImage, QPixmap, QPainter, QTransform
from PySide6.QtCore import Signal

import warnings

import numpy as np
import cv2

from camera_info import CameraInfo
from storage import (
    TextDetectionTargetMemoryStorage,
    fetch_data,
    subscribe_to_data,
    unsubscribe_from_data,
)
from sc_logging import logger
from camera_thread import STOP_TIMEOUT_MS, TimerThread

# A four-corner selection must cover at least this many square pixels.
MIN_FOUR_CORNER_AREA = 100.0

# Around the picture (the viewer is dark in light and dark themes, like the
# picture it shows)
VIEWER_BACKGROUND = QColor("#16181C")
# The statistics overlay: a pill at the viewer's top-left, the same size at
# every zoom
OSD_STYLE = (
    "QLabel { background-color: rgba(11, 11, 11, 218); color: #F0F0F0;"
    " border: 1px solid rgba(255, 255, 255, 50); border-radius: 5px;"
    " padding: 3px 7px; }"
)
OSD_MARGIN_PX = 8
# A message over the picture (e.g. an invalid four-corner selection)
MESSAGE_COLOR = QColor("#FF7B72")
MESSAGE_BACKGROUND = QColor(11, 11, 11, 218)
MESSAGE_FONT_PX = 14
# the show_osd setting
SHOW_OSD_SETTING = "show_osd"


def osd_text(fps, ups, pps, width, height) -> str:
    """The statistics overlay's lines."""
    return QCoreApplication.translate(
        "CameraView",
        "Frames/s: {fps}\nUpdates/s: {ups}\nPreviews/s: {pps}\n"
        "Resolution: {width}×{height}",
    ).format(
        fps=f"{fps:.1f}",
        ups=f"{ups:.1f}",
        pps=f"{pps:.1f}",
        width=int(width),
        height=int(height),
    )


def compute_four_corner_homography(corners) -> np.ndarray | None:
    """The homography that maps the quad given by four (x, y) corners (in
    clockwise order, starting top-left) onto its bounding rectangle, or None if
    the corners don't form a usable quad: repeated or collinear points, a
    self-intersecting or concave shape, or a tiny area would make every frame
    garbage."""
    if corners is None or len(corners) != 4:
        return None
    try:
        corners_as_array = np.array(corners, dtype=np.float32).reshape(4, 2)
    except (TypeError, ValueError):
        return None
    if not np.all(np.isfinite(corners_as_array)):
        return None
    if not cv2.isContourConvex(corners_as_array):
        return None
    # Calculate bounding rectangle
    x, y, w, h = cv2.boundingRect(corners_as_array)
    area = abs(cv2.contourArea(corners_as_array))
    # a sliver (nearly collinear points) would be stretched to a whole rectangle
    if area < MIN_FOUR_CORNER_AREA or area < 0.1 * w * h:
        return None
    # Destination points (corners of the bounding rectangle)
    dst_points = np.array(
        [[x, y], [x + w, y], [x + w, y + h], [x, y + h]], dtype=np.float32
    )
    # calculate the homography from the corners to the rect
    homography, _ = cv2.findHomography(corners_as_array, dst_points)
    if homography is None or not np.all(np.isfinite(homography)):
        return None
    if abs(np.linalg.det(homography)) < 1e-6:
        return None
    return homography


class CameraView(QGraphicsView):
    first_frame_received_signal = Signal()
    error_signal = Signal(str)
    # the zoom level changed: screen pixels per picture pixel (1.0 = 100 %)
    zoom_changed = Signal(float)

    def __init__(
        self,
        camera_index: CameraInfo,
        detectionTargetsStorage: TextDetectionTargetMemoryStorage | None = None,
        start: bool = True,
    ):
        """start=False leaves the capture thread stopped until startCapture(),
        so that a caller can connect to its signals first: a reading the thread
        emits before a slot is connected never reaches that slot."""
        super().__init__()
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setBackgroundBrush(VIEWER_BACKGROUND)
        self.camera_info = camera_index
        self.timerThread = TimerThread(camera_index, detectionTargetsStorage)
        self.timerThread.update_signal.connect(self.update_pixmap)
        self.timerThread.update_error.connect(self.error_event)
        self.timerThread.processing_error.connect(self.show_error_text)
        self._capture_started = False
        self.scenePixmapItem = None
        self.detectionTargetsStorage = detectionTargetsStorage
        self.firstFrameReceived = False
        self.error_text = None
        self.camera_width = 0
        self.camera_height = 0
        self._zoom = None
        # the whole picture is shown (it is fitted again when the view resizes)
        self.fitted = True
        # the statistics overlay: a child of the view, not of its viewport, so
        # it stays at the top-left when the picture is scrolled
        self.osd = QLabel(self)
        self.osd.setObjectName("label_osd")
        self.osd.setStyleSheet(OSD_STYLE)
        self.osd.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.osd.setVisible(False)
        self.showOSD = bool(fetch_data("scoresight.json", SHOW_OSD_SETTING, False))
        subscribe_to_data("scoresight.json", "video_settings", self.resetFrame)
        subscribe_to_data("scoresight.json", SHOW_OSD_SETTING, self.toggleOSD)
        if start:
            self.startCapture()

    def startCapture(self):
        """Start the capture thread (once)."""
        if self.timerThread is None or self._capture_started:
            return
        self._capture_started = True
        self.timerThread.start()

    def resetFrame(self, data):
        self.firstFrameReceived = False

    def getCameraCapture(self):
        if self.timerThread is None:
            return None
        return self.timerThread.video_capture

    def getCameraInfo(self):
        return self.camera_info

    def setUpdateOnChange(self, updateOnChange):
        if self.timerThread is not None:
            self.timerThread.updateOnChange = updateOnChange

    def toggleOSD(self, state):
        self.showOSD = bool(state)
        # shown once there are statistics to show
        self.osd.setVisible(self.showOSD and bool(self.osd.text()))

    def zoomLevel(self) -> float:
        """Screen pixels per picture pixel (1.0 = 100 %)."""
        return abs(self.transform().m11())

    def emitZoom(self):
        """Signal the zoom level if it changed (after scaling or fitting)."""
        zoom = self.zoomLevel()
        if zoom != self._zoom:
            self._zoom = zoom
            self.zoom_changed.emit(zoom)

    def fitPicture(self):
        """Show the whole picture."""
        self.resetTransform()
        self.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        self.fitted = True
        self.emitZoom()

    def placeOSD(self):
        viewport = self.viewport().geometry()
        self.osd.adjustSize()
        self.osd.move(viewport.left() + OSD_MARGIN_PX, viewport.top() + OSD_MARGIN_PX)
        self.osd.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.placeOSD()

    def update_pixmap(self, frame):
        if self.timerThread is None:
            return
        # the capture thread sends the next preview once this one has arrived
        self.timerThread.previewShown()

        # check if frame is not contiguous
        if not frame.flags["C_CONTIGUOUS"]:
            frame = np.ascontiguousarray(frame)

        # Create a QImage from the frame data
        image = QImage(
            frame.data,
            frame.shape[1],
            frame.shape[0],
            frame.strides[0],
            (
                QImage.Format.Format_Grayscale8
                if frame.ndim == 2
                else (
                    QImage.Format.Format_BGR888
                    if frame.shape[2] == 3
                    else QImage.Format.Format_RGBA8888
                )
            ),
        )

        # Create a QPixmap from the QImage
        pixmap = QPixmap.fromImage(image)

        if self.scenePixmapItem is None:
            self.scenePixmapItem = QGraphicsPixmapItem(pixmap)
            self.scene.addItem(self.scenePixmapItem)
            self.scenePixmapItem.setZValue(0)
            # the scene is the picture (the boxes' labels never widen it)
            self.scene.setSceneRect(0, 0, pixmap.width(), pixmap.height())
            self.fitPicture()
        else:
            refit = False
            # check if the pixmap is the same size as the current one
            if self.scenePixmapItem.pixmap().size() != pixmap.size():
                logger.info(f"scene size: {self.scene.sceneRect()}")
                refit = True
            self.scenePixmapItem.setPixmap(pixmap)
            if refit:
                self.scene.setSceneRect(0, 0, pixmap.width(), pixmap.height())
                logger.info(f"scene size: {self.scene.sceneRect()}")
                logger.info(f"Refitting view to new pixmap size: {pixmap.size()}")
                self.fitPicture()
                self.centerOn(self.scenePixmapItem)

        # the source's resolution, as read by the capture thread (asking the
        # capture would wait for its current read)
        self.camera_width, self.camera_height = self.timerThread.frame_size

        if not self.firstFrameReceived:
            self.firstFrameReceived = True
            self.first_frame_received_signal.emit()

        # the statistics overlay (translated; the same size at every zoom)
        if self.showOSD:
            self.osd.setText(
                osd_text(
                    self.timerThread.fps,
                    self.timerThread.ups,
                    self.timerThread.pps,
                    self.camera_width,
                    self.camera_height,
                )
            )
            self.placeOSD()
        self.osd.setVisible(self.showOSD)

    def show_error_text(self, error):
        """Show an error message at the bottom of the view (None clears it),
        without reporting it through error_signal: for messages that don't mean
        the source failed, e.g. an invalid four-corner selection or an error
        processing a frame."""
        if self.error_text is not None:
            self.scene.removeItem(self.error_text)
            self.error_text = None
        if error is not None:
            # at the picture's bottom left, the same size at every zoom, on a
            # dark background
            self.error_text = self.scene.addText(f"⚠ {error}")
            self.error_text.setDefaultTextColor(MESSAGE_COLOR)
            font = self.error_text.font()
            font.setPixelSize(MESSAGE_FONT_PX)
            font.setBold(True)
            self.error_text.setFont(font)
            self.error_text.setFlag(
                QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations
            )
            self.error_text.setZValue(20)
            text_rect = self.error_text.boundingRect()
            background = QGraphicsRectItem(text_rect, self.error_text)
            background.setFlag(QGraphicsItem.GraphicsItemFlag.ItemStacksBehindParent)
            background.setBrush(MESSAGE_BACKGROUND)
            background.setPen(Qt.PenStyle.NoPen)
            picture = self.scene.sceneRect()
            self.error_text.setPos(picture.left(), picture.bottom())
            # above the anchor, in screen pixels
            self.error_text.setTransform(
                QTransform.fromTranslate(
                    OSD_MARGIN_PX, -text_rect.height() - OSD_MARGIN_PX
                )
            )

    def error_event(self, error):
        """A source error (e.g. it can't be played): reported through
        error_signal. The main window shows it in its source error banner (with
        Retry) and disables the view tools; the in-scene text
        (show_error_text) is for messages that aren't source failures."""
        if error is not None:
            logger.error("Error: %s", error)
            self.error_signal.emit(error)

    def setFourCornersForHomography(self, corners: list[tuple[int]]) -> bool:
        """Warp the frames so the quad given by four corners becomes a rectangle.
        Returns False (and turns the warp off) if corners is None or isn't a
        usable quad."""
        homography = None
        if corners is not None and len(corners) == 4:
            homography = compute_four_corner_homography(corners)
            if homography is None:
                logger.warning("Ignoring an invalid four-corner selection: %s", corners)
        if self.timerThread is not None:
            self.timerThread.homography = homography
        return homography is not None

    def stopCapture(self):
        """Stop the capture thread and disconnect from it and from the settings.
        Waits up to STOP_TIMEOUT_MS; a thread still blocked on its source after
        that finishes in the background, disconnected from the UI."""
        thread = self.timerThread
        if thread is None:
            return
        self.timerThread = None
        unsubscribe_from_data("scoresight.json", "video_settings", self.resetFrame)
        unsubscribe_from_data("scoresight.json", SHOW_OSD_SETTING, self.toggleOSD)
        # nothing a stopping thread still emits may reach the UI
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            for signal in (
                thread.update_signal,
                thread.update_error,
                thread.processing_error,
                thread.ocr_result_signal,
            ):
                try:
                    signal.disconnect()
                except (RuntimeError, TypeError):
                    pass
        thread.cleanup()
        thread.stop(STOP_TIMEOUT_MS)

    def closeEvent(self, event):
        logger.debug("Close")
        self.stopCapture()

        # Call the base class closeEvent method
        super().closeEvent(event)
