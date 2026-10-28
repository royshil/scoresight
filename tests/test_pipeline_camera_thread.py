"""The capture thread (src/camera_thread.py): detection cadence, preview,
frame transforms, capture settings and teardown."""

import os
import time
import threading
import sys

import cv2
import numpy as np
import pytest

pytest.importorskip("tesserocr")  # camera_thread imports the OCR pipeline

import camera_thread  # noqa: E402
import screen_capture_source  # noqa: E402
import storage  # noqa: E402
from camera_info import CameraInfo  # noqa: E402
from camera_thread import (  # noqa: E402
    OpenCVVideoCaptureWithSettings,
    TimerThread,
    cadence_to_interval_ms,
    crop_frame,
    is_zero_text,
)
from storage import store_data  # noqa: E402
from synthetic_images import seven_segment  # noqa: E402
from text_detection_target import (  # noqa: E402
    TextDetectionResult,
    TextDetectionTargetWithResult,
)

SUCCESS = TextDetectionTargetWithResult.ResultState.Success


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class FakeDetector:
    """Stands in for TextDetector: reads each box as its name."""

    def __init__(self):
        self.calls = []
        self.on_call = None

    def detect_multi_text(self, binary, gray, rects, display=None, color=None):
        self.calls.append((binary, gray, list(rects), display))
        if self.on_call is not None:
            self.on_call()
        return [TextDetectionResult(rect.name, SUCCESS) for rect in rects]


@pytest.fixture
def make_thread(memory_storage):
    """make_thread(cadence=None) -> a TimerThread that isn't started, with a
    fake clock and OCR, and lists of what it emits."""
    threads = []

    def _make(cadence=None, camera_type=CameraInfo.CameraType.FILE, camera_id="x"):
        if cadence is not None:
            store_data("scoresight.json", "detection_cadence", cadence)
        thread = TimerThread(
            CameraInfo("test", "test", camera_id, camera_type), memory_storage
        )
        thread._clock = FakeClock()
        thread.textDetector = FakeDetector()
        thread.previews, thread.results, thread.errors = [], [], []
        thread.processing_errors = []
        thread.update_signal.connect(thread.previews.append)
        thread.ocr_result_signal.connect(thread.results.append)
        thread.update_error.connect(thread.errors.append)
        thread.processing_error.connect(thread.processing_errors.append)
        threads.append(thread)
        return thread

    yield _make
    for thread in threads:
        thread.cleanup()


def color_frame(height=240, width=320):
    frame = np.zeros((height, width, 3), np.uint8)
    frame[height // 4 : height // 2, width // 4 : width // 2] = 255
    return frame


def run_frames(thread, seconds, fps=30):
    frame = color_frame()
    for i in range(int(seconds * fps)):
        thread._clock.now = 1000.0 + i / fps
        thread.process_frame(frame)


# --- detection cadence (#53) -------------------------------------------------------------


def test_cadence_of_one_per_second_processes_frames(make_thread, make_target):
    thread = make_thread(cadence=1)
    thread.detectionTargetsStorage.add_item(make_target("Home Score"))
    run_frames(thread, 3.5)
    # OCR and preview at t = 0, 1, 2, 3 s
    assert len(thread.results) == 4
    assert len(thread.previews) == 4
    assert thread.ups == pytest.approx(1.0, abs=0.2)


@pytest.mark.parametrize("cadence", [2, 5, 15])
def test_cadence_sets_the_ocr_rate(make_thread, make_target, cadence):
    thread = make_thread(cadence=cadence)
    thread.detectionTargetsStorage.add_item(make_target("Home Score"))
    run_frames(thread, 4, fps=60)
    # a pass is due on the first frame at least 1/cadence after the last one
    assert 3 * cadence <= len(thread.results) <= 4 * cadence + 1
    # the preview stays at about one per second
    assert len(thread.previews) == pytest.approx(4, abs=1)


def test_preview_does_not_wait_for_the_ocr_cadence(make_thread, make_target):
    thread = make_thread(cadence=0.1)  # one detection every 10 s
    thread.detectionTargetsStorage.add_item(make_target("Home Score"))
    thread._clock.now = 1000.0
    thread.process_frame(color_frame())
    # the first frame is previewed (this enables the UI) and read right away
    assert len(thread.previews) == 1
    assert len(thread.results) == 1
    run_frames(thread, 5)
    assert len(thread.results) == 1
    assert len(thread.previews) >= 5


def test_long_gaps_are_measured_in_full(make_thread, make_target):
    # a gap of more than 1 s (e.g. slow OCR) must not wrap around to < 1 s
    thread = make_thread(cadence=1)
    thread.detectionTargetsStorage.add_item(make_target("Home Score"))
    for now in (1000.0, 1001.5, 1003.0, 1003.2):
        thread._clock.now = now
        thread.process_frame(color_frame())
    assert len(thread.results) == 3
    assert thread.fps < 1.5 * 30


@pytest.mark.parametrize(
    ("cadence", "interval_ms"),
    [
        (5, 200.0),
        (1, 1000.0),
        (0.5, 2000.0),
        (0, 10000.0),
        (-3, 10000.0),
        (None, 200.0),
    ],
)
def test_cadence_is_clamped(cadence, interval_ms):
    assert cadence_to_interval_ms(cadence) == pytest.approx(interval_ms)


def test_interval_set_directly_is_clamped(make_thread):
    thread = make_thread()
    thread.update_frame_interval = 1000 / 3
    assert thread.update_frame_interval == pytest.approx(333.33, abs=0.01)
    thread.update_frame_interval = -1
    assert thread.update_frame_interval == 0
    thread.update_frame_interval = float("inf")
    assert thread.update_frame_interval == camera_thread.MAX_UPDATE_FRAME_INTERVAL_MS
    thread.update_frame_interval = float("nan")
    assert thread.update_frame_interval == 200.0
    store_data("scoresight.json", "detection_cadence", 0)
    assert thread.update_frame_interval == 10000.0


# --- frame transforms ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("margins", "shape"),
    [
        ((10, 20, 30, 40), (210, 250)),
        ((300, 300, 0, 0), (1, 320)),  # used to give an empty frame
        ((400, 500, 0, 0), (1, 320)),
        ((0, 0, 999, 999), (240, 1)),
        ((-5, "x", None, 0), (240, 320)),
    ],
)
def test_crop_is_clamped_to_the_frame(margins, shape):
    assert crop_frame(color_frame(), *margins).shape[:2] == shape


def test_crop_larger_than_the_frame_keeps_the_thread_working(make_thread, make_target):
    thread = make_thread()
    thread.detectionTargetsStorage.add_item(make_target("Home Score"))
    thread.crop.isCropSet = True
    thread.crop.cropTop, thread.crop.cropBottom = 300, 300
    thread.process_frame(color_frame())
    assert thread.previews[0].shape[:2] == (1, 320)
    assert len(thread.results) == 1


def test_rotation_and_binary_preview(make_thread, make_target):
    thread = make_thread(cadence=0.1)
    thread.detectionTargetsStorage.add_item(make_target("Home Score"))
    thread.crop.rotation = 90
    thread.show_binary = True
    run_frames(thread, 2.1)
    # the OCR frame's preview comes from the OCR pass, the others are rendered
    assert [p.shape for p in thread.previews] == [(320, 240)] * 3
    assert len(thread.textDetector.calls) == 1
    assert thread.textDetector.calls[0][3] is thread.previews[0]
    assert thread.frame_size == (320, 240)  # the source frame, before rotation


def test_full_frame_binarization_only_when_needed(make_thread, make_target):
    thread = make_thread()
    thread.detectionTargetsStorage.add_item(make_target("Home Score"))
    thread.process_frame(color_frame())
    binary, gray, _, display = thread.textDetector.calls[0]
    # the OCR computes the global binarization itself if a box uses it
    assert binary is None and display is None
    assert gray.ndim == 2


def test_no_boxes_no_ocr(make_thread):
    thread = make_thread()
    run_frames(thread, 1.5)
    assert thread.textDetector.calls == []
    assert len(thread.previews) == 2


def test_boxes_are_snapshotted_per_frame(make_thread, make_target):
    thread = make_thread()
    storage_ = thread.detectionTargetsStorage
    for name in ("Home Score", "Away Score", "Period", "Time"):
        storage_.add_item(make_target(name))
    # the user deletes a box while the OCR runs (GUI thread)
    thread.textDetector.on_call = lambda: storage_.remove_item("Home Score")
    thread.process_frame(color_frame())
    [results] = thread.results
    assert [(r.name, r.result) for r in results] == [
        (name, name) for name in ("Home Score", "Away Score", "Period", "Time")
    ]


def test_update_on_change_marks_repeated_reads(make_thread, make_target):
    thread = make_thread(cadence=15)
    thread.detectionTargetsStorage.add_item(make_target("Home Score"))
    run_frames(thread, 0.2)
    states = [r[0].result_state for r in thread.results]
    assert states[0] == SUCCESS
    assert set(states[1:]) == {TextDetectionTargetWithResult.ResultState.SameNoChange}


class ScriptedDetector:
    """Stands in for TextDetector: returns the next scripted result for the one
    box, a (text, state name) pair or "unchanged" (skip similar image)."""

    def __init__(self, script):
        self.script = list(script)

    def detect_multi_text(self, binary, gray, rects, display=None, color=None):
        step = self.script.pop(0)
        if step == "unchanged":
            return [
                TextDetectionResult(
                    "",
                    TextDetectionTargetWithResult.ResultState.SameNoChange,
                    unchanged_image=True,
                )
            ]
        text, state = step
        return [
            TextDetectionResult(text, TextDetectionTargetWithResult.ResultState[state])
        ]


def published(thread, make_target, script, update_on_change=True, **settings):
    """What the box publishes for each scripted reading, one second apart."""
    thread.textDetector = ScriptedDetector(script)
    thread.updateOnChange = update_on_change
    thread.detectionTargetsStorage.clear()
    thread.detectionTargetsStorage.add_item(make_target("Home Score", **settings))
    for _ in script:
        thread._clock.now += 1.0
        thread.process_frame(color_frame())
    return [(r[0].result, r[0].result_state.name) for r in thread.results]


def test_a_rejected_reading_is_never_repeated_as_unchanged(make_thread, make_target):
    # template-uses-failed-results / api-simple-kv-sends-failed-values: the
    # last text of every reading was remembered, so a repeated rejected
    # reading came back as SameNoChange, which the outputs treat as good.
    script = [
        ("12", "Success"),
        ("8B", "FailedFilter"),
        ("8B", "FailedFilter"),
        ("", "Empty"),
        ("12", "Success"),
        ("13", "Success"),
    ]
    assert published(make_thread(), make_target, script) == [
        ("12", "Success"),
        ("8B", "FailedFilter"),
        ("8B", "FailedFilter"),
        ("", "Empty"),
        ("12", "SameNoChange"),  # same as the last good reading
        ("13", "Success"),
    ]


def test_an_unchanged_image_repeats_the_last_good_reading(make_thread, make_target):
    # skip similar image used to publish "SIM" as a FailedFilter reading, and
    # then as SameNoChange on the next skip
    script = [
        "unchanged",
        ("8B", "FailedFilter"),
        "unchanged",
        ("12", "Success"),
        "unchanged",
        ("9", "FailedFilter"),
        "unchanged",
    ]
    expected = [
        ("", "Empty"),  # no good reading yet
        ("8B", "FailedFilter"),
        ("", "Empty"),
        ("12", "Success"),
        ("12", "SameNoChange"),
        ("9", "FailedFilter"),
        ("12", "SameNoChange"),
    ]
    assert published(make_thread(), make_target, script) == expected
    # the same without "update on change"
    assert published(make_thread(), make_target, script, False) == expected


def test_a_box_blank_for_2_seconds_is_cleared(make_thread, make_target):
    # discussion #140: a handball penalty timer goes out at the end of the
    # penalty, and vMix kept showing its last value
    script = [
        ("0:01", "Success"),
        ("", "Empty"),  # blank since now
        ("", "Empty"),  # for 1 s: a flicker, the value is kept
        ("", "Empty"),  # for 2 s: cleared
        ("", "Empty"),
        ("8B", "FailedFilter"),
        ("", "Empty"),
        ("2:00", "Success"),
    ]
    expected = [
        ("0:01", "Success"),
        ("", "Empty"),
        ("", "Empty"),
        ("", "Success"),  # the outputs get the empty value once
        ("", "SameNoChange"),  # and then as the unchanged good reading
        ("8B", "FailedFilter"),
        ("", "SameNoChange"),  # still cleared
        ("2:00", "Success"),
    ]
    assert published(make_thread(), make_target, script, clear_value="blank") == (
        expected
    )
    assert (
        published(make_thread(), make_target, script, False, clear_value="blank")
        == expected
    )


def test_a_short_blank_keeps_the_value(make_thread, make_target):
    script = [
        ("12", "Success"),
        ("", "Empty"),
        ("12", "Success"),
        ("", "Empty"),
        ("", "Empty"),
        "unchanged",  # not blank
        ("", "Empty"),
        ("", "Empty"),
        ("12", "Success"),
    ]
    assert [
        state
        for _, state in published(
            make_thread(), make_target, script, clear_value="blank"
        )
    ] == [
        "Success",
        "Empty",
        "SameNoChange",
        "Empty",
        "Empty",
        "SameNoChange",
        "Empty",
        "Empty",
        "SameNoChange",
    ]


def test_keep_the_last_value_never_clears(make_thread, make_target):
    script = [("12", "Success")] + [("", "Empty")] * 5
    assert (
        published(make_thread(), make_target, script)
        == [("12", "Success")] + [("", "Empty")] * 5
    )


def test_also_at_zero_clears_a_timer_at_zero(make_thread, make_target):
    script = [
        ("0:01", "Success"),
        ("0:00", "Success"),
        ("0:00", "Success"),
        ("0:00", "Success"),
        ("0:00", "Success"),
        ("", "Empty"),
        ("2:00", "Success"),
    ]
    assert published(
        make_thread(), make_target, script, clear_value="blank_or_zero"
    ) == [
        ("0:01", "Success"),
        ("0:00", "Success"),  # zero goes on air first
        ("0:00", "SameNoChange"),
        ("", "Success"),  # zero for 2 s: cleared
        ("", "SameNoChange"),
        ("", "SameNoChange"),
        ("2:00", "Success"),
    ]
    # without "also at zero", zero is a value like any other
    assert published(make_thread(), make_target, script[:5], clear_value="blank") == [
        ("0:01", "Success"),
        ("0:00", "Success"),
        ("0:00", "SameNoChange"),
        ("0:00", "SameNoChange"),
        ("0:00", "SameNoChange"),
    ]


def test_clearing_forgets_the_image_and_the_smoothing(make_thread, make_target):
    thread = make_thread()
    thread.textDetector = ScriptedDetector([("", "Empty")] * 3)
    target = make_target("Home Score", clear_value="blank")
    target.last_text = "5"
    target.last_image = np.zeros((4, 4), np.uint8)
    target.ocrResultPerCharacterSmoother.get_smoothed_result("5")
    thread.detectionTargetsStorage.add_item(target)
    for _ in range(3):
        thread._clock.now += 1.0
        thread.process_frame(color_frame())
    assert [r[0].result_state.name for r in thread.results][-1] == "Success"
    # the board showing 5 again is read, and isn't smoothed with the old 5s
    assert target.last_text == ""
    assert target.last_image is None
    assert not target.ocrResultPerCharacterSmoother.history


@pytest.mark.parametrize(
    ("text", "zero"),
    [
        ("0", True),
        ("00", True),
        ("0:00", True),
        ("00:00", True),
        ("0.0", True),
        (":00", True),  # 00:00 without its leading zeros
        ("", False),
        ("10", False),
        ("0:01", False),
        ("O", False),
    ],
)
def test_is_zero_text(text, zero):
    assert is_zero_text(text) is zero


def test_training_data_is_snapshotted_before_the_results_are_emitted(
    make_thread, make_target, monkeypatch
):
    from ocr_training_data import OCRTrainingSample, ocr_training_data_options

    saved = []
    monkeypatch.setattr(ocr_training_data_options, "save_ocr_training_data", True)
    monkeypatch.setattr(
        ocr_training_data_options,
        "save_ocr_results_to_folder",
        lambda binary, gray, samples: saved.append(samples),
    )
    thread = make_thread()
    thread.detectionTargetsStorage.add_item(make_target("Home Score"))

    def edit_in_gui_thread(results):
        # MainWindow.ocrResult rewrites results (template fields) in place
        for result in results:
            result.result = "edited"

    thread.ocr_result_signal.connect(edit_in_gui_thread)
    thread.process_frame(color_frame())
    [[sample]] = saved
    assert isinstance(sample, OCRTrainingSample)
    assert (sample.name, sample.text) == ("Home Score", "Home Score")


# --- the capture loop -----------------------------------------------------------------------


class FakeCapture:
    def __init__(self, frames=None):
        self.frames = frames
        self.reads = 0
        self.released = False

    def isOpened(self):
        return True

    def read(self):
        self.reads += 1
        if self.frames is None:
            return True, color_frame()
        if self.frames:
            return True, self.frames.pop(0)
        return False, None

    def get(self, prop):
        return 0.0

    def set(self, prop, value):
        pass

    def release(self):
        self.released = True


def test_processing_errors_do_not_stop_the_loop(make_thread, make_target):
    thread = make_thread(cadence=15)
    thread.frame_interval = 0
    thread.detectionTargetsStorage.add_item(make_target("Home Score"))
    thread.video_capture = FakeCapture()

    def broken(*args, **kwargs):
        raise RuntimeError("Failed to recognize. No image set?")

    thread.textDetector.detect_multi_text = broken
    for i in range(20):
        thread._clock.now = 1000.0 + i / 10
        thread.run_once()
    assert not thread.should_stop
    assert thread.video_capture.reads == 20
    assert thread.retry_count == 0
    # reported, but not on every frame
    assert 1 <= len(thread.processing_errors) <= 2
    assert "No image set" in thread.processing_errors[0]
    # not as a source error, which would disable the view tools
    assert thread.errors == []
    assert len(thread.previews) >= 2


def test_failed_open_reports_an_error_and_cleans_up(qtbot, make_thread, tmp_path):
    thread = make_thread(camera_id=str(tmp_path / "missing.mp4"))
    thread.update_error.disconnect()
    with qtbot.waitSignal(thread.update_error, timeout=5000) as error:
        thread.start()
    assert thread.wait(5000)
    assert "Unable to play video stream" in error.args[0]
    assert thread.video_capture is None
    # nothing keeps the stopped thread (or its OCR engine) alive
    assert storage.data_subscribers == {}


def test_capture_that_raises_on_open_reports_an_error(make_thread, monkeypatch):
    thread = make_thread(camera_type=CameraInfo.CameraType.SCREEN_CAPTURE)

    def window_gone(window_id):
        raise ValueError(f"No window with ID {window_id} found")

    monkeypatch.setattr(screen_capture_source, "ScreenCapture", window_gone)
    assert thread.connect_video_capture() is False
    assert thread.errors == ["Error: Unable to play video stream"]


def test_stop_and_cleanup(make_thread):
    thread = make_thread()
    assert storage.data_subscribers != {}
    thread.cleanup()
    thread.cleanup()  # idempotent
    assert storage.data_subscribers == {}
    assert thread.stop(10) is True  # never started


# --- OpenCVVideoCaptureWithSettings ---------------------------------------------------------


class FakeVideoCapture:
    """Records how cv2.VideoCapture is used."""

    instances = []
    # backends this "OpenCV build" doesn't have: opening with them fails
    missing_backends = set()

    def __init__(self, capture_id, backend=cv2.CAP_ANY, params=None):
        self.capture_id = capture_id
        self.backend = backend
        self.params = params
        self.calls = []
        self.props = {
            cv2.CAP_PROP_FRAME_WIDTH: 640.0,
            cv2.CAP_PROP_FRAME_HEIGHT: 480.0,
            cv2.CAP_PROP_FPS: 30.0,
        }
        self.released = False
        FakeVideoCapture.instances.append(self)

    def isOpened(self):
        return self.backend not in FakeVideoCapture.missing_backends

    def read(self):
        self.calls.append("read")
        return True, color_frame()

    def set(self, prop, value):
        self.calls.append((prop, value))
        self.props[prop] = value
        return True

    def get(self, prop):
        return self.props.get(prop, 0.0)

    def release(self):
        self.released = True


@pytest.fixture
def fake_video_capture(monkeypatch):
    FakeVideoCapture.instances = []
    FakeVideoCapture.missing_backends = set()
    monkeypatch.setattr(cv2, "VideoCapture", FakeVideoCapture)
    return FakeVideoCapture


def store_video_settings(**settings):
    for name, value in settings.items():
        store_data("scoresight.json", name, value)


def test_stored_video_settings_are_applied_when_a_camera_opens(fake_video_capture):
    store_video_settings(fps=60, width=1280, height=720, fourcc="MJPG", backend=1400)
    capture = OpenCVVideoCaptureWithSettings(
        0, cv2.CAP_DSHOW, apply_video_settings=True
    )
    [device] = fake_video_capture.instances
    assert device.backend == 1400  # the stored backend (MSMF), not the default
    assert device.calls == [
        (cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG")),
        (cv2.CAP_PROP_FRAME_WIDTH, 1280),
        (cv2.CAP_PROP_FRAME_HEIGHT, 720),
        (cv2.CAP_PROP_FPS, 60.0),
    ]
    capture.release()


def test_without_a_stored_resolution_the_highest_is_selected(fake_video_capture):
    store_video_settings(width=-1, height=-1, backend=cv2.CAP_ANY, fourcc="NULL")
    OpenCVVideoCaptureWithSettings(0, cv2.CAP_DSHOW, apply_video_settings=True)
    [device] = fake_video_capture.instances
    assert device.backend == cv2.CAP_DSHOW  # "Auto" means the platform default
    assert device.calls[0] == "read"
    assert (cv2.CAP_PROP_FRAME_WIDTH, 1920) in device.calls


def test_files_and_urls_get_no_video_settings(fake_video_capture):
    store_video_settings(fps=60, width=1280, height=720, fourcc="MJPG", backend=1400)
    OpenCVVideoCaptureWithSettings("clip.mp4")
    [device] = fake_video_capture.instances
    assert device.backend == cv2.CAP_ANY
    assert device.calls == []
    assert storage.data_subscribers == {}


def test_settings_changes_are_applied_by_the_reading_thread(fake_video_capture):
    capture = OpenCVVideoCaptureWithSettings(
        0, cv2.CAP_DSHOW, apply_video_settings=True
    )
    [device] = fake_video_capture.instances
    device.calls.clear()
    # what VideoSettingsDialog.save_settings does on the GUI thread
    store_video_settings(width=1280, height=720, fourcc="MJPG")
    assert device.calls == []
    capture.read()
    assert device.calls == [
        (cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG")),
        (cv2.CAP_PROP_FRAME_WIDTH, 1280),
        (cv2.CAP_PROP_FRAME_HEIGHT, 720),
        "read",
    ]


def test_an_unchanged_backend_does_not_reopen_the_device(fake_video_capture):
    store_video_settings(width=1280, height=720)
    capture = OpenCVVideoCaptureWithSettings(
        0, cv2.CAP_DSHOW, apply_video_settings=True
    )
    store_video_settings(backend=cv2.CAP_DSHOW)
    store_video_settings(backend=cv2.CAP_ANY)  # Auto = the platform default
    capture.read()
    assert len(fake_video_capture.instances) == 1


def test_a_backend_change_reopens_on_the_reading_thread(fake_video_capture):
    store_video_settings(width=1280, height=720, fps=25)
    capture = OpenCVVideoCaptureWithSettings(
        0, cv2.CAP_DSHOW, apply_video_settings=True
    )
    store_video_settings(backend=cv2.CAP_MSMF)
    # not reopened by the thread that stored the setting
    assert len(fake_video_capture.instances) == 1
    capture.read()
    old, new = fake_video_capture.instances
    assert old.released and not new.released
    assert new.backend == cv2.CAP_MSMF
    # with the settings re-applied
    assert (cv2.CAP_PROP_FRAME_WIDTH, 1280) in new.calls
    assert (cv2.CAP_PROP_FPS, 25.0) in new.calls


def test_a_stored_backend_that_cannot_open_falls_back_to_the_default(
    fake_video_capture,
):
    # e.g. Windows Runtime, which the pip OpenCV wheels don't have: the camera
    # still opens, so the Video Settings dialog can undo the choice
    fake_video_capture.missing_backends = {cv2.CAP_WINRT}
    store_video_settings(width=1280, height=720, backend=cv2.CAP_WINRT)
    capture = OpenCVVideoCaptureWithSettings(
        0, cv2.CAP_DSHOW, apply_video_settings=True
    )
    failed, device = fake_video_capture.instances
    assert failed.backend == cv2.CAP_WINRT and failed.released
    assert device.backend == cv2.CAP_DSHOW
    assert capture.isOpened()
    assert (cv2.CAP_PROP_FRAME_WIDTH, 1280) in device.calls
    # the stored choice is left for the user to change
    assert storage.fetch_data("scoresight.json", "backend") == cv2.CAP_WINRT
    capture.release()


def test_a_backend_change_that_cannot_open_falls_back_to_the_default(
    fake_video_capture,
):
    fake_video_capture.missing_backends = {cv2.CAP_MSMF}
    capture = OpenCVVideoCaptureWithSettings(
        0, cv2.CAP_DSHOW, apply_video_settings=True
    )
    store_video_settings(backend=cv2.CAP_MSMF)
    ok, _ = capture.read()
    assert ok and capture.isOpened()
    original, failed, reopened = fake_video_capture.instances
    assert original.released and failed.released
    assert failed.backend == cv2.CAP_MSMF
    assert reopened.backend == cv2.CAP_DSHOW and not reopened.released
    # going back to Auto (the default) doesn't reopen it again
    store_video_settings(backend=cv2.CAP_ANY)
    capture.read()
    assert len(fake_video_capture.instances) == 3
    capture.release()


def test_a_failed_open_with_the_default_backend_is_not_retried(fake_video_capture):
    fake_video_capture.missing_backends = {cv2.CAP_DSHOW}
    capture = OpenCVVideoCaptureWithSettings(
        0, cv2.CAP_DSHOW, apply_video_settings=True
    )
    assert not capture.isOpened()
    assert len(fake_video_capture.instances) == 1
    capture.release()


def test_release_stops_following_the_settings(fake_video_capture):
    old = OpenCVVideoCaptureWithSettings(0, cv2.CAP_DSHOW, apply_video_settings=True)
    current = OpenCVVideoCaptureWithSettings(
        0, cv2.CAP_DSHOW, apply_video_settings=True
    )
    old.release()
    store_video_settings(backend=cv2.CAP_MSMF)
    old.read()
    current.read()
    # only the live capture reopens; the released one isn't brought back
    assert len(fake_video_capture.instances) == 3
    assert fake_video_capture.instances[2].backend == cv2.CAP_MSMF
    current.release()
    assert storage.data_subscribers == {}


# --- URL sources (#10) ----------------------------------------------------------------------


@pytest.fixture
def ffmpeg_env():
    name = camera_thread.FFMPEG_CAPTURE_OPTIONS_ENV
    original = os.environ.get(name)
    camera_thread.set_process_env(name, None)
    yield name
    camera_thread.set_process_env(name, original)


def test_url_sources_use_ffmpeg_with_timeouts_and_rtsp_tcp_first(
    make_thread, fake_video_capture, ffmpeg_env
):
    thread = make_thread(
        camera_type=CameraInfo.CameraType.URL, camera_id="  rtsp://10.0.1.200:554/11 \n"
    )
    assert thread.connect_video_capture()
    [stream] = fake_video_capture.instances
    assert stream.capture_id == "rtsp://10.0.1.200:554/11"
    assert stream.backend == cv2.CAP_FFMPEG
    assert stream.params == [
        cv2.CAP_PROP_OPEN_TIMEOUT_MSEC,
        5000,
        cv2.CAP_PROP_READ_TIMEOUT_MSEC,
        5000,
    ]
    # no Video Settings and no highest-resolution probing for streams
    assert stream.calls == []
    # TCP first with FFmpeg's fallback to UDP, not TCP only
    # ("rtsp_transport;tcp"), which fails with cameras that refuse TCP
    assert os.environ[ffmpeg_env] == "rtsp_flags;prefer_tcp"


def test_user_ffmpeg_options_are_kept(make_thread, fake_video_capture, ffmpeg_env):
    camera_thread.set_process_env(ffmpeg_env, "rtsp_transport;udp")
    thread = make_thread(
        camera_type=CameraInfo.CameraType.URL, camera_id="rtsp://camera/stream"
    )
    thread.connect_video_capture()
    assert os.environ[ffmpeg_env] == "rtsp_transport;udp"


def test_file_sources_skip_the_resolution_probe(make_thread, fake_video_capture):
    thread = make_thread(camera_id="clip.mp4")
    thread.connect_video_capture()
    [video] = fake_video_capture.instances
    assert video.calls == []


@pytest.mark.skipif(
    sys.platform != "win32", reason="msvcrt environment is Windows-only"
)
def test_ffmpeg_options_reach_opencvs_ffmpeg_backend(tmp_path, ffmpeg_env):
    # The FFmpeg plugin reads OPENCV_FFMPEG_CAPTURE_OPTIONS from msvcrt's copy of
    # the environment. A protocol whitelist without "file" makes a local file
    # fail to open only if the option arrives.
    path = str(tmp_path / "clip.avi")
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"MJPG"), 10, (64, 48))
    for _ in range(3):
        writer.write(np.zeros((48, 64, 3), np.uint8))
    writer.release()
    assert cv2.VideoCapture(path, cv2.CAP_FFMPEG).isOpened()
    camera_thread.set_process_env(ffmpeg_env, "protocol_whitelist;tcp")
    assert not cv2.VideoCapture(path, cv2.CAP_FFMPEG).isOpened()
    camera_thread.set_process_env(ffmpeg_env, None)
    assert cv2.VideoCapture(path, cv2.CAP_FFMPEG).isOpened()
    # the default options don't get in the way of other inputs
    camera_thread.ensure_ffmpeg_capture_options()
    assert cv2.VideoCapture(path, cv2.CAP_FFMPEG).isOpened()


# --- end to end: a video file through the real thread ---------------------------------------


def write_scoreboard_video(path, value="45", frames=30, size=(240, 320)):
    digits = seven_segment(value)
    frame = np.zeros((*size, 3), np.uint8)
    y, x = 40, 60
    frame[y : y + digits.shape[0], x : x + digits.shape[1]] = cv2.cvtColor(
        digits, cv2.COLOR_GRAY2BGR
    )
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 30, size[::-1])
    for _ in range(frames):
        writer.write(frame)
    writer.release()
    return (x, y, digits.shape[1], digits.shape[0])


@pytest.mark.ocr
@pytest.mark.qt
def test_video_file_at_one_detection_per_second(
    qtbot, tmp_path, memory_storage, make_target
):
    video = tmp_path / "scoreboard.avi"
    rect = write_scoreboard_video(video)
    memory_storage.add_item(make_target("Home Score", rect=rect))
    store_data("scoresight.json", "detection_cadence", 1)

    thread = TimerThread(
        CameraInfo(str(video), str(video), str(video), CameraInfo.CameraType.FILE),
        memory_storage,
    )
    previews, results = [], []
    thread.update_signal.connect(previews.append)
    thread.ocr_result_signal.connect(results.append)
    thread.start()
    try:
        qtbot.waitUntil(lambda: len(previews) >= 1, timeout=1500)
        qtbot.waitUntil(lambda: len(results) >= 2, timeout=4000)
    finally:
        assert thread.stop(5000)
    first = results[0][0]
    assert (first.name, first.result, first.result_state) == (
        "Home Score",
        "45",
        SUCCESS,
    )
    assert previews[0].shape == (240, 320, 3)
    assert thread not in camera_thread._active_threads
    assert storage.data_subscribers == {}


# --- the OCR worker: a slow OCR doesn't hold up the capture ----------------------------


class NumberedCapture(FakeCapture):
    """Frames numbered in their first pixel's channels; remembers the last."""

    def __init__(self):
        super().__init__()
        self.last = -1

    def read(self):
        self.reads += 1
        self.last += 1
        frame = color_frame()
        frame[0, 0] = (self.last & 255, (self.last >> 8) & 255, 0)
        return True, frame


def frame_number(frame):
    return int(frame[0, 0, 0]) + (int(frame[0, 0, 1]) << 8)


class SlowDetector:
    """Takes `seconds` per OCR cycle; records the thread, the frame number
    read and the capture's latest frame number at the start of the cycle."""

    def __init__(self, capture, seconds):
        self.capture = capture
        self.seconds = seconds
        self.cycles = []

    def detect_multi_text(self, binary, gray, rects, display=None, color=None):
        self.cycles.append(
            (threading.current_thread(), frame_number(color), self.capture.last)
        )
        time.sleep(self.seconds)
        return [TextDetectionResult(rect.name, SUCCESS) for rect in rects]


@pytest.mark.qt
def test_a_slow_ocr_does_not_hold_up_reading_frames(qtbot, make_thread, make_target):
    thread = make_thread(cadence=15)
    thread._clock = time.monotonic
    thread.detectionTargetsStorage.add_item(make_target("Home Score"))
    capture = NumberedCapture()
    thread._create_video_capture = lambda: capture
    detector = SlowDetector(capture, 0.5)
    thread.textDetector = detector
    thread.start()
    try:
        qtbot.waitUntil(lambda: len(thread.results) >= 3, timeout=8000)
        reads_before, cycles_before = capture.reads, len(detector.cycles)
        time.sleep(1.0)
        reads = capture.reads - reads_before
        cycles = len(detector.cycles) - cycles_before
        # the capture reads on while the OCR takes 500 ms: about 30 frames a
        # second (8 on a busy macOS runner, whose sleeps run long) against two
        # cycles. A capture held up by the OCR would read one frame a cycle.
        assert reads >= 2 * cycles + 2, (reads, cycles)
    finally:
        assert thread.stop(5000)
    cycles = list(detector.cycles)
    assert len(cycles) >= 3
    # the OCR runs on its own thread, never the capture thread
    assert all(t.name == "ocr" for t, _, _ in cycles)
    # each cycle reads the newest frame (the frames read meanwhile are dropped)
    numbers = [number for _, number, _ in cycles]
    assert all(b - a >= 2 for a, b in zip(numbers, numbers[1:]))
    assert all(latest - number <= 1 for _, number, latest in cycles)
    # from reading a frame to publishing its readings: about the OCR's time
    assert 0.2 <= thread.last_reading_latency < 1.0
    # stopping stopped the worker: no cycle after it
    count = len(detector.cycles)
    time.sleep(0.3)
    assert len(detector.cycles) == count
    assert thread._ocr_worker is None


def test_without_a_running_capture_the_ocr_runs_on_the_caller(make_thread, make_target):
    thread = make_thread(cadence=5)
    thread.detectionTargetsStorage.add_item(make_target("Home Score"))
    thread.process_frame(color_frame())
    assert len(thread.results) == 1
    assert thread.last_reading_latency == 0.0  # the fake clock didn't move


def test_the_worker_takes_a_frame_only_when_idle(make_thread):
    thread = make_thread()
    worker = camera_thread.OcrWorker(thread)
    assert worker.idle()
    worker.submit(color_frame(), 1.0)
    assert not worker.idle()
    assert worker.stop(1)  # never started: nothing to wait for
    assert not worker.idle()


def test_the_ocr_gets_the_detection_interval(make_thread, make_target):
    thread = make_thread(cadence=4)
    thread.detectionTargetsStorage.add_item(make_target("Home Score"))
    thread.process_frame(color_frame())
    assert thread.textDetector.cycle_interval_ms == 250.0


# --- the phone camera's waiting picture ------------------------------------------


class WaitingCapture:
    """A capture showing its waiting picture (phone_camera.PhoneCapture)."""

    showing_placeholder = True


def test_a_waiting_picture_is_previewed_but_never_read(make_thread, make_target):
    thread = make_thread(cadence=5)
    thread.detectionTargetsStorage.add_item(make_target("Home Score"))
    thread.crop.rotation = 90
    thread.video_capture = WaitingCapture()
    picture = color_frame()
    for i in range(90):
        thread._clock.now = 1000.0 + i / 30
        thread.process_frame(picture)
    # previewed about once a second, as it is (not rotated), and never read
    assert len(thread.previews) == 3
    assert all(preview is picture for preview in thread.previews)
    assert thread.results == []

    # the phone sends: its frames are read
    thread.video_capture.showing_placeholder = False
    for i in range(30):
        thread._clock.now = 1003.0 + i / 30
        thread.process_frame(color_frame())
    assert len(thread.results) == 5
