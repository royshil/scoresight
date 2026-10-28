from PySide6.QtCore import QThread, Signal, Slot

import atexit
import ctypes
import math
import os
import re
import platform
import sys
import time
import cv2
import threading

from base_video_capture import BaseVideoCapture
from camera_info import CameraInfo
from defaults import CLEAR_AFTER_SECONDS, CLEAR_BLANK_OR_ZERO, CLEAR_NEVER
from storage import (
    SETTINGS_FILE,
    TextDetectionTargetMemoryStorage,
    fetch_data,
    subscribe_to_data,
    unsubscribe_from_data,
)
from tesseract import TextDetector, global_binarization, render_binary_view
from text_detection_target import TextDetectionTargetWithResult
from sc_logging import logger
from frame_stabilizer import FrameStabilizer
from ocr_training_data import ocr_training_data_options, snapshot_training_samples

ResultState = TextDetectionTargetWithResult.ResultState

# "Detections / s" (detection_cadence): the default, and the lowest rate the
# capture thread accepts (one detection every 10 s); 0 or less is clamped to it.
DEFAULT_DETECTION_CADENCE = 5
MIN_DETECTION_CADENCE = 0.1
MAX_UPDATE_FRAME_INTERVAL_MS = 1000.0 / MIN_DETECTION_CADENCE

# Open and read timeouts for URL (network stream) sources, so that a stalled
# stream can't block the capture thread (and closing it) for FFmpeg's default
# 30 s per call.
URL_CAPTURE_TIMEOUT_MS = 5000
URL_CAPTURE_PARAMS = [
    cv2.CAP_PROP_OPEN_TIMEOUT_MSEC,
    URL_CAPTURE_TIMEOUT_MS,
    cv2.CAP_PROP_READ_TIMEOUT_MSEC,
    URL_CAPTURE_TIMEOUT_MS,
]

FFMPEG_CAPTURE_OPTIONS_ENV = "OPENCV_FFMPEG_CAPTURE_OPTIONS"
# RTSP over TCP first, falling back to UDP for a server that refuses TCP (461
# Unsupported Transport). "rtsp_transport;tcp" would be TCP only.
DEFAULT_FFMPEG_CAPTURE_OPTIONS = "rtsp_flags;prefer_tcp"

# How long closing a source waits for its capture thread to stop before letting
# it finish in the background.
STOP_TIMEOUT_MS = 3000

# A frame processing error that repeats on every frame is reported at most this often.
ERROR_REPORT_INTERVAL_S = 5.0

# How long stopping the capture waits for the OCR cycle in progress.
OCR_STOP_TIMEOUT_S = 2.0


def set_process_env(name: str, value: str | None):
    """Set (or with None, remove) an environment variable for this process,
    including for OpenCV's FFmpeg backend."""
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value
    if sys.platform == "win32":
        # OpenCV's FFmpeg plugin (opencv_videoio_ffmpeg*.dll) reads its options
        # with getenv() from msvcrt.dll, which keeps its own copy of the
        # environment that os.environ (the UCRT's) doesn't update.
        try:
            ctypes.cdll.msvcrt._putenv(f"{name}={value or ''}".encode())
        except (OSError, AttributeError):
            logger.debug("Unable to set %s for msvcrt", name, exc_info=True)


def ensure_ffmpeg_capture_options():
    """Have URL sources try RTSP over TCP first (UDP fails behind NAT,
    firewalls and VPNs) and fall back to UDP for cameras that only offer it.
    This is what OpenCV does when the variable is unset; setting it makes the
    default explicit. A user-provided OPENCV_FFMPEG_CAPTURE_OPTIONS (e.g.
    rtsp_transport;udp to force UDP) is left alone."""
    if os.environ.get(FFMPEG_CAPTURE_OPTIONS_ENV) is not None:
        return
    set_process_env(FFMPEG_CAPTURE_OPTIONS_ENV, DEFAULT_FFMPEG_CAPTURE_OPTIONS)


def cadence_to_interval_ms(cadence) -> float:
    """The time between detections, in ms, for a detection_cadence in detections
    per second (clamped to at least MIN_DETECTION_CADENCE)."""
    try:
        cadence = float(cadence)
    except (TypeError, ValueError):
        cadence = DEFAULT_DETECTION_CADENCE
    if math.isnan(cadence):
        cadence = DEFAULT_DETECTION_CADENCE
    return 1000.0 / max(cadence, MIN_DETECTION_CADENCE)


def _clamp_interval_ms(interval_ms) -> float:
    try:
        interval_ms = float(interval_ms)
    except (TypeError, ValueError):
        return cadence_to_interval_ms(DEFAULT_DETECTION_CADENCE)
    if math.isnan(interval_ms):
        return cadence_to_interval_ms(DEFAULT_DETECTION_CADENCE)
    return min(max(interval_ms, 0.0), MAX_UPDATE_FRAME_INTERVAL_MS)


def _clamp_margin(value, limit: int) -> int:
    try:
        value = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, min(value, limit))


def crop_margins(width, height, top, bottom, left, right):
    """The crop margins (top, bottom, left, right) that crop_frame cuts off a
    frame of this size: clamped so at least one row and column remain."""
    top = _clamp_margin(top, height - 1)
    bottom = _clamp_margin(bottom, height - 1 - top)
    left = _clamp_margin(left, width - 1)
    right = _clamp_margin(right, width - 1 - left)
    return top, bottom, left, right


def crop_frame(frame, top, bottom, left, right):
    """Crop the given margins off the frame. The margins are clamped to the
    frame so at least one row and column remain, e.g. when a crop set for a
    larger source is applied to a smaller (or rotated) one."""
    height, width = frame.shape[:2]
    top, bottom, left, right = crop_margins(width, height, top, bottom, left, right)
    return frame[top : height - bottom, left : width - right]


def to_gray(frame):
    if frame.ndim == 2:
        return frame
    if frame.shape[2] == 4:
        return cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY)
    return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)


def fourcc_code(fourcc) -> int | None:
    """The FOURCC int for a stored 4-character code, or None if it isn't one."""
    if not isinstance(fourcc, str) or len(fourcc) != 4 or fourcc == "NULL":
        return None
    return cv2.VideoWriter_fourcc(*fourcc)


def _positive(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(value) or value <= 0:
        return None
    return value


# Function to set the resolution
def set_resolution(cap, width, height):
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)


# Function to get the resolution
def get_resolution(cap):
    width = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
    height = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
    return width, height


# Function to set the camera to the highest resolution
def set_camera_highest_resolution(cap):
    # List of common resolutions to try
    resolutions = [(1920, 1080), (1280, 720), (1024, 768), (800, 600), (640, 480)]

    # grab one frame to make sure the camera is initialized
    ret, _ = cap.read()
    if not ret:
        logger.warning("Error: camera not initialized")
        return

    # grab the current resolution
    width, height = get_resolution(cap)

    # If the current resolution is already the highest, return
    if width >= resolutions[0][0] and height >= resolutions[0][1]:
        logger.info(
            "Camera is already at the highest resolution: %d x %d", width, height
        )
        return

    # Try each resolution and select the highest one that works
    highest_res = resolutions[0]
    for resolution in resolutions:
        logger.debug("Trying camera resolution: %d x %d", resolution[0], resolution[1])
        set_resolution(cap, *resolution)
        test_width, test_height = get_resolution(cap)
        logger.debug("Found camera resolution: %d x %d", test_width, test_height)
        # if found resolution is within close range of the target resolution, use it
        if (
            abs(test_width - resolution[0]) < 100
            and abs(test_height - resolution[1]) < 100
        ):
            logger.debug(
                "Camera highest resolution set to: %d x %d", test_width, test_height
            )
            highest_res = (test_width, test_height)
            break

    # Set the highest resolution
    logger.info("Setting camera resolution to: %d x %d", highest_res[0], highest_res[1])
    set_resolution(cap, *highest_res)


# a reading of zero: 0, 00, 0:00, 0.0 (with "When blank": blank or zero)
_ZERO_TEXT = re.compile(r"[0:.,'\s]*0[0:.,'\s]*")


def is_zero_text(text: str) -> bool:
    return _ZERO_TEXT.fullmatch(text) is not None


class FrameCropAndRotation:
    def __init__(self):
        self.isCropSet = fetch_data(SETTINGS_FILE, "crop_mode", False)
        self.cropTop = fetch_data(SETTINGS_FILE, "top_crop", 0)
        self.cropBottom = fetch_data(SETTINGS_FILE, "bottom_crop", 0)
        self.cropLeft = fetch_data(SETTINGS_FILE, "left_crop", 0)
        self.cropRight = fetch_data(SETTINGS_FILE, "right_crop", 0)
        self.rotation = fetch_data(SETTINGS_FILE, "rotation", 0)
        self._subscriptions = [
            ("crop_mode", self.setCropMode),
            ("top_crop", self.setCropTop),
            ("bottom_crop", self.setCropBottom),
            ("left_crop", self.setCropLeft),
            ("right_crop", self.setCropRight),
            ("rotation", self.setRotation),
        ]
        for document_name, callback in self._subscriptions:
            subscribe_to_data(SETTINGS_FILE, document_name, callback)

    def close(self):
        """Stop following the crop and rotation settings."""
        for document_name, callback in self._subscriptions:
            unsubscribe_from_data(SETTINGS_FILE, document_name, callback)

    def setCropMode(self, crop_mode):
        self.isCropSet = crop_mode

    def setCropTop(self, crop_top):
        self.cropTop = crop_top

    def setCropBottom(self, crop_bottom):
        self.cropBottom = crop_bottom

    def setCropLeft(self, crop_left):
        self.cropLeft = crop_left

    def setCropRight(self, crop_right):
        self.cropRight = crop_right

    def setRotation(self, rotation):
        self.rotation = rotation


class OpenCVVideoCaptureWithSettings(BaseVideoCapture):
    """A cv2.VideoCapture shared by the capture thread (read) and the GUI thread
    (the Video Settings dialog), guarded by video_capture_mutex.

    With apply_video_settings (camera devices), the stored Video Settings are
    used when the device opens: its backend, then FOURCC, resolution and fps.
    A stored backend that can't open the device falls back to the default one.
    When they change later (stored from the dialog, on the GUI thread) they are
    applied by the capture thread right before its next read(), so the GUI
    thread never reopens the device. release() stops following the settings.
    """

    def __init__(
        self,
        capture_id: int | str,
        capture_backend: int = cv2.CAP_ANY,
        params: list[int] | None = None,
        apply_video_settings: bool = False,
    ):
        super().__init__(capture_id, capture_backend)
        self.video_capture_mutex = threading.Lock()
        self.params = list(params) if params else []
        self.apply_video_settings = apply_video_settings
        self.default_backend = capture_backend
        self.backend = capture_backend
        self.fps = None
        self.width = None
        self.height = None
        self.fourcc = None
        self._reopen_requested = False
        self._apply_requested = False
        self._subscriptions = []
        if apply_video_settings:
            self.fps = fetch_data(SETTINGS_FILE, "fps", None)
            self.width = fetch_data(SETTINGS_FILE, "width", None)
            self.height = fetch_data(SETTINGS_FILE, "height", None)
            self.fourcc = fetch_data(SETTINGS_FILE, "fourcc", None)
            self.backend = self._effective_backend(
                fetch_data(SETTINGS_FILE, "backend", None)
            )
            self._subscriptions = [
                ("fps", self.setFps),
                ("width", self.setWidth),
                ("height", self.setHeight),
                ("fourcc", self.setFourcc),
                ("backend", self.setBackend),
            ]
            for document_name, callback in self._subscriptions:
                subscribe_to_data(SETTINGS_FILE, document_name, callback)
        with self.video_capture_mutex:
            self.video_capture = self._open()

    def _effective_backend(self, backend) -> int:
        # A stored backend of "Auto" (CAP_ANY) or none means the platform default.
        try:
            backend = int(backend)
        except (TypeError, ValueError):
            return self.default_backend
        return backend if backend != cv2.CAP_ANY else self.default_backend

    def _create_capture(self, backend):
        if self.params:
            return cv2.VideoCapture(self.capture_id, backend, self.params)
        return cv2.VideoCapture(self.capture_id, backend)

    def _open(self):
        capture = self._create_capture(self.backend)
        if not capture.isOpened() and self.backend != self.default_backend:
            # e.g. a backend this OpenCV build doesn't have: falling back keeps
            # the camera (and the Video Settings dialog, to undo the choice)
            # usable
            logger.warning(
                "Unable to open capture %s with backend %s; using the default backend",
                self.capture_id,
                self.backend,
            )
            capture.release()
            self.backend = self.default_backend
            capture = self._create_capture(self.backend)
        if self.apply_video_settings and capture.isOpened():
            self._apply_settings(capture, opening=True)
        return capture

    def _apply_settings(self, capture, opening: bool):
        # FOURCC first: e.g. MJPG is what unlocks the high resolutions and frame
        # rates on many USB cameras.
        code = fourcc_code(self.fourcc)
        if code is not None:
            capture.set(cv2.CAP_PROP_FOURCC, code)
        width = _positive(self.width)
        height = _positive(self.height)
        if width is not None and height is not None:
            set_resolution(capture, int(width), int(height))
        elif opening:
            set_camera_highest_resolution(capture)
        fps = _positive(self.fps)
        if fps is not None:
            capture.set(cv2.CAP_PROP_FPS, fps)

    def _apply_pending_changes(self):
        # called by the reading thread with the mutex held
        if self._reopen_requested:
            self._reopen_requested = False
            self._apply_requested = False
            logger.info(
                "Reopening capture %s with backend %s", self.capture_id, self.backend
            )
            self.video_capture.release()
            self.video_capture = self._open()
        elif self._apply_requested:
            self._apply_requested = False
            self._apply_settings(self.video_capture, opening=False)

    def setFps(self, fps):
        self.fps = fps
        self._apply_requested = True

    def setWidth(self, width):
        self.width = width
        self._apply_requested = True

    def setHeight(self, height):
        self.height = height
        self._apply_requested = True

    def setFourcc(self, fourcc: str):
        self.fourcc = fourcc
        self._apply_requested = True

    def setBackend(self, backend):
        backend = self._effective_backend(backend)
        if backend == self.backend:
            return
        self.backend = backend
        self._reopen_requested = True

    def isOpened(self):
        with self.video_capture_mutex:
            return self.video_capture.isOpened()

    def read(self):
        with self.video_capture_mutex:
            self._apply_pending_changes()
            return self.video_capture.read()

    def release(self):
        for document_name, callback in self._subscriptions:
            unsubscribe_from_data(SETTINGS_FILE, document_name, callback)
        self._subscriptions = []
        with self.video_capture_mutex:
            self.video_capture.release()

    def set(self, propId, value):
        with self.video_capture_mutex:
            self.video_capture.set(propId, value)

    def get(self, propId):
        with self.video_capture_mutex:
            return self.video_capture.get(propId)

    def run_locked(self, function):
        """Call function(cv2.VideoCapture) with the mutex held, e.g. to get or
        set many properties while waiting for the reading thread only once."""
        with self.video_capture_mutex:
            return function(self.video_capture)


# Capture threads that were started and haven't finished. Holding them here
# keeps a running QThread from being garbage collected (which aborts the
# process) when its view lets go of it without waiting for it to stop.
_active_threads: set["TimerThread"] = set()


def _stop_active_threads_at_exit():
    threads = list(_active_threads)
    for thread in threads:
        thread.should_stop = True
    deadline = time.monotonic() + STOP_TIMEOUT_MS / 1000.0
    for thread in threads:
        remaining_ms = max(0, int((deadline - time.monotonic()) * 1000))
        if not thread.wait(remaining_ms):
            logger.warning("Camera thread is still running at exit")


atexit.register(_stop_active_threads_at_exit)


class OcrWorker:
    """Reads the boxes of a TimerThread's frames on a thread of its own, so
    that the capture loop keeps reading frames while the OCR runs. It holds
    at most one frame: the capture loop hands it a frame only when it is
    idle (see TimerThread.process_frame), so the OCR always reads the latest
    frame and never a queue of stale ones."""

    def __init__(self, owner: "TimerThread"):
        self.owner = owner
        self._condition = threading.Condition()
        self._pending = None
        self._busy = False
        self._stopping = False
        self._thread = threading.Thread(target=self._run, name="ocr", daemon=True)

    def start(self):
        self._thread.start()

    def idle(self) -> bool:
        """Whether it can take a frame now (no frame waiting or being read)."""
        with self._condition:
            return self._pending is None and not self._busy and not self._stopping

    def submit(self, frame, frame_time: float):
        with self._condition:
            self._pending = (frame, frame_time)
            self._condition.notify()

    def stop(self, timeout: float | None = None) -> bool:
        """Stop after the cycle in progress (up to timeout seconds); returns
        whether the thread ended."""
        with self._condition:
            self._stopping = True
            self._pending = None
            self._condition.notify()
        if self._thread.is_alive() and self._thread is not threading.current_thread():
            self._thread.join(timeout)
        return not self._thread.is_alive()

    def _run(self):
        while True:
            with self._condition:
                while self._pending is None and not self._stopping:
                    self._condition.wait()
                if self._stopping:
                    return
                frame, frame_time = self._pending
                self._pending = None
                self._busy = True
            try:
                self.owner.run_ocr_cycle(frame, frame_time)
            except Exception:
                # run_ocr_cycle reports its own errors; this is a last resort
                logger.exception("OCR cycle failed")
            finally:
                with self._condition:
                    self._busy = False


class TimerThread(QThread):
    update_signal = Signal(object)
    # the source failed (can't be opened or read): it is stopping
    update_error = Signal(object)
    # a frame couldn't be processed; the capture keeps running
    processing_error = Signal(object)
    ocr_result_signal = Signal(list)

    def __init__(
        self,
        camera_info: CameraInfo,
        detectionTargetsStorage: TextDetectionTargetMemoryStorage,
    ):
        super().__init__()
        self.camera_info = camera_info
        self.homography = None
        self.detectionTargetsStorage = detectionTargetsStorage
        self.textDetector = TextDetector()  # initialize tesseract
        self.show_binary = False
        self.retry_count = 0
        self.retry_count_max = 50
        self.retry_high_water_mark = 25
        self.stabilizationEnabled = False
        self.framestabilizer = FrameStabilizer()
        self.video_capture: BaseVideoCapture | None = None
        self.should_stop = False
        # monotonic clock (seconds); replaceable in tests
        self._clock = time.monotonic
        self.frame_interval = 30
        self.update_frame_interval = cadence_to_interval_ms(
            fetch_data(SETTINGS_FILE, "detection_cadence", DEFAULT_DETECTION_CADENCE)
        )
        subscribe_to_data(
            SETTINGS_FILE, "detection_cadence", self.setUpdateFrameInterval
        )
        self.preview_frame_interval = 1000
        self.fps = 1000 / self.frame_interval  # frames per second
        self.pps = 1000 / self.preview_frame_interval  # previews per second
        self.ups = 1000 / max(self.update_frame_interval, 1)  # updates per second
        self.fps_alpha = 0.1  # Smoothing factor
        self.updateOnChange = True
        self.crop = FrameCropAndRotation()
        self.speed = 1
        # (width, height) of the last frame read from the source
        self.frame_size = (0, 0)
        # the source's own frame rate (capped at what the loop reads), None if
        # it doesn't tell: the window compares fps with it
        self.nominal_fps: float | None = None
        # While new four-corner points are picked the preview shows the picture
        # without the four-corner correction (the corners are clicked on it).
        # The OCR keeps reading the corrected picture until the new correction
        # replaces it.
        self.preview_uncorrected = False
        # While a crop is dragged (Drag to crop) the preview shows the whole
        # rotated frame, without the crop and the corrections after it. The OCR
        # keeps reading the cropped picture until the new crop replaces it.
        self.preview_uncropped = False
        # When the boxes last moved with the crop (boxesMoved), on _clock
        self.boxes_moved_at: float | None = None
        # The last frame transformed (at least once a second), as read and as
        # the boxes see it (rotated, cropped, stabilized and corrected): what
        # Auto crop and Auto layout look at (latestRotatedFrame, latestPicture)
        self.latest_source = None
        self.latest_picture = None
        self.last_frame_timestamp = None
        self.last_update_timestamp = None
        self.last_emit_time = None
        # the OCR's thread while the capture runs (None: OCR on the caller's)
        self._ocr_worker: OcrWorker | None = None
        # seconds from reading a frame to publishing its boxes' readings: the
        # last one, and smoothed
        self.last_reading_latency: float | None = None
        self.reading_latency: float | None = None
        self._iteration_start = None
        self._last_error_report = None
        self.finished.connect(self._on_finished)

    @property
    def update_frame_interval(self) -> float:
        """Time between OCR passes in ms (1000 / detection_cadence)."""
        return self._update_frame_interval

    @update_frame_interval.setter
    def update_frame_interval(self, interval_ms):
        # also set directly by the main window when the cadence slider moves
        self._update_frame_interval = _clamp_interval_ms(interval_ms)

    def getSpeed(self):
        return self.speed

    def setSpeed(self, speed):
        self.speed = speed

    def setUpdateFrameInterval(self, cadence):
        self.update_frame_interval = cadence_to_interval_ms(cadence)

    def start(self, *args, **kwargs):
        _active_threads.add(self)
        super().start(*args, **kwargs)

    @Slot()
    def _on_finished(self):
        # Queued to the thread that owns this object (the GUI thread) after
        # run() returned.
        self.wait()
        _active_threads.discard(self)

    def stop(self, timeout_ms: int = STOP_TIMEOUT_MS) -> bool:
        """Ask the thread to stop and wait up to timeout_ms for it. Returns False
        if it is still busy (e.g. blocked reading a stream); it then finishes in
        the background."""
        self.should_stop = True
        if self.wait(int(timeout_ms)):
            _active_threads.discard(self)
            return True
        logger.warning(
            "Camera thread for '%s' did not stop within %d ms; it will finish in "
            "the background",
            self.camera_info.description,
            timeout_ms,
        )
        return False

    def cleanup(self):
        """Stop following settings changes. Safe to call more than once, from
        any thread."""
        unsubscribe_from_data(
            SETTINGS_FILE, "detection_cadence", self.setUpdateFrameInterval
        )
        self.crop.close()

    def _create_video_capture(self) -> BaseVideoCapture:
        camera_type = self.camera_info.type
        if camera_type == CameraInfo.CameraType.NDI:
            # imported when first used (or by the source discovery): cyndilib
            # and the NDI library take a while to load
            from ndi import NDICapture

            return NDICapture(self.camera_info.uuid)
        if camera_type == CameraInfo.CameraType.SCREEN_CAPTURE:
            # imported when first used: it loads pywin32 / pyobjc's Quartz,
            # which would slow down every start
            from screen_capture_source import ScreenCapture

            return ScreenCapture(self.camera_info.id)
        if camera_type == CameraInfo.CameraType.PHONE:
            # imported when first used: it starts the phone's HTTPS server
            from phone_camera import PhoneCapture

            return PhoneCapture(interval_ms=lambda: self.update_frame_interval)
        if camera_type == CameraInfo.CameraType.URL:
            url = str(self.camera_info.id).strip()
            ensure_ffmpeg_capture_options()
            return OpenCVVideoCaptureWithSettings(
                url, cv2.CAP_FFMPEG, params=URL_CAPTURE_PARAMS
            )
        if camera_type == CameraInfo.CameraType.FILE:
            return OpenCVVideoCaptureWithSettings(self.camera_info.id)
        # a camera device: on windows use the dshow backend by default
        backend = cv2.CAP_DSHOW if platform.system() == "Windows" else cv2.CAP_ANY
        return OpenCVVideoCaptureWithSettings(
            self.camera_info.id, backend, apply_video_settings=True
        )

    def connect_video_capture(self) -> bool:
        try:
            self.video_capture = self._create_video_capture()
        except Exception:
            logger.exception("Error: unable to open the video source")
            self.video_capture = None
            self.update_error.emit("Error: Unable to play video stream")
            return False

        if self.retry_count != self.retry_high_water_mark:
            # at the high water mark this is a reconnect
            self.retry_count = 0

        if not self.video_capture.isOpened():
            logger.warning(
                "Error: unable to open camera. Check if the camera is connected."
            )
            self.update_error.emit("Error: Unable to play video stream")
            return False

        self.nominal_fps = self._read_nominal_fps()
        return True

    def _read_nominal_fps(self) -> float | None:
        """The frame rate the source reports (a camera's mode, a file's or a
        stream's rate), capped at the capture loop's own rate; None if it
        reports none or a bogus one (screen captures and NDI report 0, some
        streams 90000)."""
        try:
            fps = float(self.video_capture.get(cv2.CAP_PROP_FPS))
        except Exception:
            return None
        if not math.isfinite(fps) or fps <= 0 or fps > 1000:
            return None
        return min(fps, 1000.0 / self.frame_interval)

    def requestPreview(self):
        """Emit the next frame as the preview, without waiting for the preview
        interval (e.g. right after the four-corner picking started)."""
        self.last_emit_time = None

    def _release_capture(self):
        capture, self.video_capture = self.video_capture, None
        if capture is not None:
            try:
                capture.release()
            except Exception:
                logger.exception("Error releasing the video capture")

    def run(self):
        description_ascii = (
            self.camera_info.description.encode("ascii", errors="ignore").decode()
            if isinstance(self.camera_info.description, str)
            else str(self.camera_info.description)
        )
        logger.info("Starting camera thread for: '%s'", description_ascii)

        try:
            if not self.connect_video_capture():
                self.should_stop = True
                return
            self._ocr_worker = OcrWorker(self)
            self._ocr_worker.start()
            while not self.should_stop:
                self.run_once()
        except Exception:
            logger.exception("Camera thread failed")
            self.update_error.emit("Error: Unable to play video stream")
        finally:
            worker, self._ocr_worker = self._ocr_worker, None
            if worker is not None and not worker.stop(OCR_STOP_TIMEOUT_S):
                logger.warning("The OCR cycle in progress did not finish in time")
            self._release_capture()
            self.cleanup()
            logger.info("Camera thread stopped")

    def run_once(self):
        """One iteration of the capture loop: read a frame (reconnecting or
        giving up after repeated failures) and process it."""
        self._iteration_start = self._clock()
        if self.video_capture is None:
            logger.warning("Error: video capture is None")
            self.should_stop = True
            return

        if self.retry_count == self.retry_high_water_mark:
            logger.warning("Error: retry high water mark exceeded")
            # reconnect the video cap
            self._release_capture()
            if not self.connect_video_capture():
                self.should_stop = True
                return
            self.sleep_fps_target()
            self.retry_count += 1
            return
        if self.retry_count > self.retry_count_max:
            logger.warning("Error: retry count exceeded")
            self.should_stop = True
            self.update_error.emit("Error: Unable to play video stream")
            return

        # Read the frame from the camera
        ret, frame_rgb = None, None
        try:
            ret, frame_rgb = self.video_capture.read()
        except Exception as e:
            self.retry_count += 1
            logger.exception(
                "Error: unable to read frame from camera (retry count: %d), exception %s",
                self.retry_count,
                e,
            )
            self.sleep_fps_target()
            return

        if self.camera_info.type == CameraInfo.CameraType.FILE:
            if self.speed != 1:
                self.video_capture.set(
                    cv2.CAP_PROP_POS_FRAMES,
                    self.video_capture.get(cv2.CAP_PROP_POS_FRAMES) + self.speed,
                )

        if not ret or frame_rgb is None or frame_rgb.size == 0:
            self.retry_count += 1
            if self.camera_info.type == CameraInfo.CameraType.FILE:
                logger.debug("Restarting video file")
                self.video_capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
                self.sleep_fps_target()
                return
            logger.warning(
                "Error: unable to read frame from camera, return value False (retry count: %d)",
                self.retry_count,
            )
            self.sleep_fps_target()
            return

        self.retry_count = 0  # good frame, reset the retry count
        try:
            self.process_frame(frame_rgb)
        except Exception as e:
            self._report_processing_error(e)
        self.sleep_fps_target()

    def _report_processing_error(self, error):
        # Called from an except block. Keeps the thread (and the capture) alive;
        # an error that repeats on every frame is reported once in a while.
        now = self._clock()
        if (
            self._last_error_report is not None
            and now - self._last_error_report < ERROR_REPORT_INTERVAL_S
        ):
            return
        self._last_error_report = now
        logger.exception("Error: unable to process the video frame")
        self.processing_error.emit(f"Error: unable to process the video frame: {error}")

    def process_frame(self, frame_rgb):
        """Process a frame read from the source: on the detection cadence read
        its boxes (OCR), and about once a second emit it as the preview. The
        two are independent, so the preview (and with it the first-frame signal
        that enables the UI) comes at any detection cadence.

        While the capture runs (run()), the OCR runs on its own thread
        (OcrWorker), so a slow OCR cycle never holds up reading frames: a live
        source's frames don't go stale in its buffer and a video file plays at
        the loop's rate. A frame is handed to the OCR only when it is idle, so
        it always reads the latest frame and the frames read meanwhile are
        dropped (they may still be previewed). Without a running capture (the
        tests) the OCR runs here, on the calling thread."""
        now = self._clock()
        if getattr(self.video_capture, "showing_placeholder", False):
            # the phone camera's waiting picture: shown as it is, never read
            self._preview_placeholder(frame_rgb, now)
            return
        self.frame_size = (frame_rgb.shape[1], frame_rgb.shape[0])

        # calculate the frame rate
        if self.last_frame_timestamp is not None:
            time_diff_ms = (now - self.last_frame_timestamp) * 1000.0
            if time_diff_ms > 0:
                self.fps = (
                    self.fps_alpha * (1000 / time_diff_ms)
                    + (1.0 - self.fps_alpha) * self.fps
                )
        self.last_frame_timestamp = now

        # check that enough time has passed since the last update and preview,
        # and that the OCR is free to take this frame
        worker = self._ocr_worker
        update_due = (
            self.last_update_timestamp is None
            or (now - self.last_update_timestamp) * 1000.0 >= self.update_frame_interval
        ) and (worker is None or worker.idle())
        preview_due = (
            self.last_emit_time is None
            or (now - self.last_emit_time) * 1000.0 >= self.preview_frame_interval
        )
        if not update_due and not preview_due:
            # dump this frame since not enough time has passed
            return

        source = frame_rgb
        adjusted = self.adjust_frame(frame_rgb)
        frame_rgb = self.correct_frame(adjusted)
        self.latest_source = source
        self.latest_picture = frame_rgb
        show_binary = self.show_binary
        targets = None
        gray = None
        display = None

        if update_due:
            if self.last_update_timestamp is not None:
                time_diff_ms = (now - self.last_update_timestamp) * 1000.0
                if time_diff_ms > 0:
                    self.ups = (
                        self.fps_alpha * (1000 / time_diff_ms)
                        + (1.0 - self.fps_alpha) * self.ups
                    )
            self.last_update_timestamp = now
            if worker is not None:
                worker.submit(frame_rgb, now)
            else:
                targets, gray, display = self.run_ocr_cycle(
                    frame_rgb, now, want_display=show_binary and preview_due
                )

        if preview_due:
            if self.last_emit_time is not None:
                time_diff_ms = (now - self.last_emit_time) * 1000.0
                if time_diff_ms > 0:
                    self.pps = (
                        self.fps_alpha * (1000 / time_diff_ms)
                        + (1.0 - self.fps_alpha) * self.pps
                    )
            self.last_emit_time = now
            if self.preview_uncropped:
                # a new crop is being dragged on the whole picture
                self.update_signal.emit(self.rotate_frame(source))
            elif self.preview_uncorrected:
                # new four-corner points are being picked on this picture
                self.update_signal.emit(adjusted)
            elif show_binary:
                if display is None:
                    if gray is None:
                        gray = to_gray(frame_rgb)
                    if targets is None:
                        targets = self._snapshot_targets()
                    uses_ppocr = getattr(self.textDetector, "uses_ppocr", None)
                    display = render_binary_view(
                        global_binarization(gray),
                        gray,
                        targets,
                        ppocr=bool(uses_ppocr and uses_ppocr()),
                    )
                self.update_signal.emit(display)
            else:
                self.update_signal.emit(frame_rgb)

    def _preview_placeholder(self, picture, now):
        """Show a picture that isn't the source's (not rotated, cropped or
        corrected, and not read) about once per preview interval."""
        self.last_frame_timestamp = None
        if (
            self.last_emit_time is not None
            and (now - self.last_emit_time) * 1000.0 < self.preview_frame_interval
        ):
            return
        self.last_emit_time = now
        self.update_signal.emit(picture)

    def latestRotatedFrame(self):
        """The last frame transformed, rotated only (the picture Drag to crop
        shows), or None before one."""
        source = self.latest_source
        return None if source is None else self.rotate_frame(source)

    def latestPicture(self):
        """The last picture the boxes were read from, or None before one."""
        return self.latest_picture

    def boxesMoved(self):
        """The boxes were moved to stay on the same part of the picture,
        because the crop's corner moved. A frame read until now was cropped
        as before: read with the boxes' new places, it would give readings of
        other pixels, so they are dropped (the OCR worker may hold one)."""
        self.boxes_moved_at = self._clock()

    def readBeforeBoxesMoved(self, frame_time) -> bool:
        moved = self.boxes_moved_at
        return moved is not None and frame_time is not None and frame_time <= moved

    def run_ocr_cycle(self, frame_rgb, frame_time, want_display=False):
        """Read the boxes of a (transformed) frame read at frame_time and
        publish the results. Returns (the boxes, the gray frame, the binary
        view with what the OCR read drawn in, if want_display or OCR training
        data is collected; else None)."""
        # One snapshot of the boxes per frame: the GUI thread may add or
        # remove boxes while the OCR runs.
        targets = self._snapshot_targets()
        if not targets or self.readBeforeBoxesMoved(frame_time):
            return [], None, None
        gray = to_gray(frame_rgb)
        binary = None
        display = None
        if want_display or ocr_training_data_options.save_ocr_training_data:
            binary = global_binarization(gray)
            display = binary.copy()
        try:
            # what PP-OCR (automatic) keeps its reading time under
            self.textDetector.cycle_interval_ms = self.update_frame_interval
            # binary=None: the OCR computes the global binarization only if a
            # box uses it; PP-OCR reads the colour frame
            texts = self.textDetector.detect_multi_text(
                binary, gray, targets, display=display, color=frame_rgb
            )
            self._publish_results(targets, texts, display, gray, frame_time)
        except Exception as e:
            # the preview is still emitted
            self._report_processing_error(e)
        return targets, gray, display

    def _snapshot_targets(self):
        if self.detectionTargetsStorage is None:
            return []
        return list(self.detectionTargetsStorage.get_data())

    def _published_reading(self, target, result) -> tuple[str, ResultState]:
        """The (text, state) to publish for a box's OCR result.

        SameNoChange always means "the same as the box's last good reading"
        (target.last_text, which only a Success reading sets):
        - with "update on change", a Success reading equal to the last good one;
        - a box whose OCR was skipped because its image hasn't changed (skip
          similar image). Without a good reading yet, that box is Empty.
        So a rejected reading (FailedFilter, e.g. text that fails the box's
        format) is never repeated as SameNoChange, which the outputs treat as
        a good reading.

        With "When blank" set (clear_value), a box that has been blank (or
        zero) for CLEAR_AFTER_SECONDS is read as an empty good reading: a
        Success "" once, then SameNoChange "" while it stays blank.
        """
        cleared = self._cleared_reading(target, result)
        if cleared is not None:
            return cleared
        if result.unchanged_image:
            if target.last_text is None:
                return "", ResultState.Empty
            return target.last_text, ResultState.SameNoChange
        if result.state != ResultState.Success:
            return result.text, result.state
        if self.updateOnChange and result.text == target.last_text:
            return result.text, ResultState.SameNoChange
        target.last_text = result.text
        return result.text, ResultState.Success

    def _cleared_reading(self, target, result) -> tuple[str, ResultState] | None:
        """The empty reading of a box that "When blank" clears, or None to
        publish the reading as usual. A blank box is one read as Empty (or,
        with CLEAR_BLANK_OR_ZERO, as zero); a box blank for less than
        CLEAR_AFTER_SECONDS (a flicker, a hand in front of the board) keeps
        its value."""
        clear = (target.settings or {}).get("clear_value", CLEAR_NEVER)
        if clear == CLEAR_NEVER:
            target.blank_since = None
            return None
        blank = not result.unchanged_image and (
            result.state == ResultState.Empty
            or (
                clear == CLEAR_BLANK_OR_ZERO
                and result.state == ResultState.Success
                and is_zero_text(result.text)
            )
        )
        if not blank:
            target.blank_since = None
            return None
        now = self._clock()
        if target.blank_since is None:
            target.blank_since = now
        if target.last_text == "":
            # cleared already
            return "", ResultState.SameNoChange
        if now - target.blank_since < CLEAR_AFTER_SECONDS:
            return None
        target.last_text = ""
        # the value cleared is forgotten: when the board shows it again, it is
        # read (skip similar image would repeat the empty value) and isn't
        # smoothed with the readings before
        target.last_image = None
        target.ocrResultPerCharacterSmoother.clear()
        return "", ResultState.Success

    def _publish_results(self, targets, texts, display, gray, frame_time=None):
        if len(texts) == 0 or len(targets) != len(texts):
            return
        if self.readBeforeBoxesMoved(frame_time):
            # the boxes moved with the crop while this frame was read
            return
        # augment the text detection targets with the results
        results = []
        for target, result in zip(targets, texts):
            text, state = self._published_reading(target, result)
            results.append(
                TextDetectionTargetWithResult(
                    target, text, state, result.rect, result.extra
                )
            )

        # The GUI thread edits the results (template fields) once they are
        # emitted, so the training data is snapshotted first.
        samples = None
        if ocr_training_data_options.save_ocr_training_data and display is not None:
            samples = snapshot_training_samples(results)

        if frame_time is not None:
            latency = max(0.0, self._clock() - frame_time)
            self.last_reading_latency = latency
            self.reading_latency = (
                latency
                if self.reading_latency is None
                else self.fps_alpha * latency
                + (1.0 - self.fps_alpha) * self.reading_latency
            )
        self.ocr_result_signal.emit(results)

        if samples:
            # save the image patches and the texts
            ocr_training_data_options.save_ocr_results_to_folder(display, gray, samples)

    def transform_frame(self, frame_rgb):
        """Apply the rotation, crop, stabilization and four-corner homography."""
        return self.correct_frame(self.adjust_frame(frame_rgb))

    def rotate_frame(self, frame_rgb):
        """Apply the rotation."""
        rotation = self.crop.rotation
        if rotation != 0:
            # use cv2.rotate to rotate the frame
            rotateCode = (
                cv2.ROTATE_90_CLOCKWISE
                if rotation == 90
                else (
                    cv2.ROTATE_90_COUNTERCLOCKWISE
                    if rotation == 270
                    else cv2.ROTATE_180
                )
            )
            frame_rgb = cv2.rotate(frame_rgb, rotateCode)
        return frame_rgb

    def adjust_frame(self, frame_rgb):
        """Apply the rotation, crop and stabilization."""
        crop = self.crop
        frame_rgb = self.rotate_frame(frame_rgb)

        # apply top-level crop if set
        if crop.isCropSet:
            frame_rgb = crop_frame(
                frame_rgb, crop.cropTop, crop.cropBottom, crop.cropLeft, crop.cropRight
            )

        # Stabilize the frame
        if self.stabilizationEnabled:
            frame_rgb = self.framestabilizer.stabilize_frame(frame_rgb)
        return frame_rgb

    def correct_frame(self, frame_rgb):
        """Apply the four-corner homography (the perspective correction)."""
        homography = self.homography
        if homography is not None:
            frame_rgb = cv2.warpPerspective(
                frame_rgb, homography, (frame_rgb.shape[1], frame_rgb.shape[0])
            )
        return frame_rgb

    def sleep_fps_target(self):
        # cap the loop at about 1000 / frame_interval iterations per second
        if self._iteration_start is None:
            return
        time_diff_ms = (self._clock() - self._iteration_start) * 1000.0
        if time_diff_ms < self.frame_interval:
            time.sleep((self.frame_interval - time_diff_ms) / 1000.0)

    def toggleStabilization(self, state):
        self.stabilizationEnabled = state
        if not state:
            self.framestabilizer.reset()
