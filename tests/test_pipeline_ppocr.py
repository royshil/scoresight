"""The PP-OCR engine (src/ppocr_engine.py) and how TextDetector reads with it
(src/tesseract.py).

The decoding, batching and pipeline tests use a fake onnxruntime session or a
fake recognizer, so they need neither onnxruntime nor the models. The `ppocr`
tests use the real models (python scripts/fetch_models.py); they are skipped
without them unless SCORESIGHT_REQUIRE_PPOCR is set (CI).
"""

import subprocess
import sys
import threading
import time
from pathlib import Path

import cv2
import numpy as np
import pytest

pytest.importorskip("tesserocr")

import ocr_models  # noqa: E402
import ppocr_engine  # noqa: E402
import tesseract  # noqa: E402
from defaults import CHAR_WHITELISTS, GENERAL_CHAR_WHITELIST, FieldType  # noqa: E402
from synthetic_images import hershey, seven_segment  # noqa: E402
from tesseract import TextDetector  # noqa: E402
from text_detection_target import TextDetectionTargetWithResult  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"

State = TextDetectionTargetWithResult.ResultState
NUMBER = CHAR_WHITELISTS[FieldType.NUMBER]
TIME = CHAR_WHITELISTS[FieldType.TIME]

# a small dictionary: blank, digits, ":", ".", letters, a full-width 1, space
CHARACTERS = ["", *"0123456789:.ABCHOMEl", "１", " "]


def onehot_steps(classes: list[int], steps: int = 40, size=len(CHARACTERS)):
    """(steps, size) probabilities: classes[t] wins at step t, the blank after."""
    probs = np.full((steps, size), 0.01 / (size - 1), np.float32)
    probs[:, 0] = 0.99
    for t, cls in enumerate(classes):
        probs[t] = 0.01 / (size - 1)
        probs[t, cls] = 0.99
    return probs


# --- decoding ---------------------------------------------------------------------


def test_ctc_greedy_merges_repeats_and_drops_blanks():
    one = CHARACTERS.index("1")
    two = CHARACTERS.index("2")
    probs = onehot_steps([one, one, 0, one, two, two])
    text, confidence, kept = ppocr_engine.ctc_greedy(probs, CHARACTERS)
    assert text == "112"
    assert confidence == pytest.approx(0.99)
    assert list(kept) == [one, one, two]
    # nothing kept: no confidence
    assert ppocr_engine.ctc_greedy(onehot_steps([]), CHARACTERS)[:2] == ("", None)


def test_the_whitelist_limits_the_characters():
    # an "l" (a letter) wins over "1" at the first step; a box of digits
    # reads it as the best digit instead
    probs = onehot_steps([])
    ell, one, five = CHARACTERS.index("l"), CHARACTERS.index("1"), CHARACTERS.index("5")
    probs[0] = 0.0
    probs[0, ell], probs[0, one], probs[0, 0] = 0.6, 0.3, 0.1
    probs[2] = 0.0
    probs[2, five], probs[2, 0] = 0.9, 0.1
    recognizer = ppocr_engine.Recognizer(ppocr_engine.SMALL)
    assert recognizer.decode(probs, CHARACTERS, None)[0] == "l5"
    text, confidence = recognizer.decode(probs, CHARACTERS, NUMBER)
    assert text == "15"
    # the confidence is the kept characters' (grouped) probability
    assert confidence == pytest.approx((0.3 + 0.9) / 2)


def test_nfkc_equal_characters_count_as_one():
    # the full-width １ adds to "1" under a digits-only whitelist
    groups = ppocr_engine.class_groups(CHARACTERS, NUMBER)
    one = CHARACTERS.index("1")
    full_width = CHARACTERS.index("１")
    assert "1" in groups.labels
    probs = onehot_steps([])
    probs[0] = 0.0
    probs[0, 0], probs[0, one], probs[0, full_width] = 0.4, 0.35, 0.25
    reduced = groups.reduce(probs)
    assert reduced[0, groups.labels.index("1")] == pytest.approx(0.6)
    text, _, _ = ppocr_engine.ctc_greedy(reduced, groups.labels)
    assert text == "1"


def test_a_whitelist_without_any_of_the_models_characters_is_an_error():
    with pytest.raises(ValueError):
        ppocr_engine.class_groups(CHARACTERS, "xyz")


def test_time_whitelist_keeps_separators():
    groups = ppocr_engine.class_groups(CHARACTERS, TIME)
    assert {":", "."} <= set(groups.labels)
    assert "A" not in groups.labels


def test_preprocessing_matches_paddleocr():
    # 48 px high keeping the aspect ratio, [-1, 1], padded on the right
    crop = np.full((24, 40, 3), 255, np.uint8)
    out = ppocr_engine.resize_normalize(crop, 48, 320)
    assert out.shape == (3, 48, 320) and out.dtype == np.float32
    assert np.allclose(out[:, :, :80], 1.0)
    assert np.allclose(out[:, :, 80:], 0.0)
    assert ppocr_engine.padded_width(24, 40, 48, 320) == 320
    assert ppocr_engine.padded_width(10, 100, 48, 320) == 480


def test_crops_of_any_kind_become_bgr():
    gray = np.full((5, 6), 7, np.uint8)
    assert ppocr_engine.to_model_input(gray, rgb=False).shape == (5, 6, 3)
    bgra = np.zeros((5, 6, 4), np.uint8)
    bgra[..., 0] = 9
    out = ppocr_engine.to_model_input(bgra, rgb=False)
    assert out.shape == (5, 6, 3) and out[0, 0, 0] == 9
    assert ppocr_engine.to_model_input(bgra, rgb=True)[0, 0, 2] == 9


def test_character_lists_are_read_line_by_line(tmp_path):
    path = tmp_path / "characters.txt"
    # a character that str.splitlines() would split on stays one character
    path.write_bytes("0\n1\n \n　\n".encode("utf-8"))
    assert ppocr_engine.read_characters(str(path)) == ["", "0", "1", " ", "　", " "]
    path.write_bytes(b"0\n\n1\n")
    with pytest.raises(ValueError):
        ppocr_engine.read_characters(str(path))


# --- batching (a fake onnxruntime session) ------------------------------------------


class FakeSession:
    """Reads each crop's text from its gray level: a crop filled with value v
    reads as str(v); records the batch shapes it was given."""

    def __init__(self):
        self.batches = []

    def run(self, outputs, feeds):
        [batch] = feeds.values()
        self.batches.append(batch.shape)
        out = []
        for image in batch:
            value = int(round((float(image[0, 0, 0]) / 2 + 0.5) * 255))
            steps = []
            for char in str(value):
                steps += [CHARACTERS.index(char), 0]
            out.append(onehot_steps(steps, steps=batch.shape[3] // 8))
        return [np.stack(out)]


def fake_recognizer(model_id=ppocr_engine.SMALL):
    recognizer = ppocr_engine.Recognizer(model_id, threads=1)
    recognizer._session = FakeSession()
    recognizer._input_name = "x"
    recognizer._characters = CHARACTERS
    recognizer.state = ppocr_engine.READY
    recognizer._done.set()
    return recognizer


def crop(value, width=60, height=40):
    return np.full((height, width, 3), value, np.uint8)


def test_a_frames_boxes_are_read_in_one_run():
    recognizer = fake_recognizer()
    crops = [crop(v) for v in (12, 45, 7, 99)]
    reads = recognizer.recognize(crops, [NUMBER] * 4)
    assert [text for text, _ in reads] == ["12", "45", "7", "99"]
    assert recognizer._session.batches == [(4, 3, 48, 320)]


def test_crops_wider_than_the_minimum_are_run_by_width():
    # a crop's reading never depends on the other crops: one run per padded
    # width (here 320 and 480)
    recognizer = fake_recognizer()
    crops = [crop(12), crop(34, width=200, height=20), crop(56)]
    reads = recognizer.recognize(crops, [NUMBER] * 3)
    assert [text for text, _ in reads] == ["12", "34", "56"]
    assert sorted(recognizer._session.batches) == [(1, 3, 48, 480), (2, 3, 48, 320)]


def test_a_crop_reads_the_same_alone_and_in_a_batch():
    recognizer = fake_recognizer()
    alone = recognizer.recognize([crop(21)], [NUMBER])
    batched = recognizer.recognize([crop(9), crop(21), crop(3)], [NUMBER] * 3)
    assert batched[1] == alone[0]


def test_large_frames_are_split_into_batches(monkeypatch):
    monkeypatch.setattr(ppocr_engine, "MAX_BATCH", 3)
    recognizer = fake_recognizer()
    reads = recognizer.recognize([crop(v) for v in range(10, 17)], [NUMBER] * 7)
    assert [text for text, _ in reads] == [str(v) for v in range(10, 17)]
    assert [shape[0] for shape in recognizer._session.batches] == [3, 3, 1]


def test_empty_crops_read_nothing():
    recognizer = fake_recognizer()
    reads = recognizer.recognize([np.zeros((0, 5, 3), np.uint8), crop(8)], None)
    assert reads == [("", None), ("8", pytest.approx(0.99))]


def test_an_unloaded_model_can_not_read():
    with pytest.raises(RuntimeError):
        ppocr_engine.Recognizer(ppocr_engine.TINY).recognize([crop(1)])


# --- availability and the lazy load --------------------------------------------------


def test_missing_models_and_runtime(monkeypatch, tmp_path):
    monkeypatch.setattr(
        ppocr_engine, "resource_path", lambda *p: str(tmp_path.joinpath(*p))
    )
    assert ppocr_engine.missing(ppocr_engine.SMALL) == ppocr_engine.MISSING_MODELS
    assert ppocr_engine.missing(ppocr_engine.AUTO) == ppocr_engine.MISSING_MODELS
    assert "fetch_models.py" in ppocr_engine.unavailable_reason(ppocr_engine.TINY)
    for info in ppocr_engine.MODELS.values():
        folder = tmp_path / "ocr_models" / "ppocr" / info.folder
        folder.mkdir(parents=True)
        for name in ("inference.onnx", "characters.txt", "config.json"):
            (folder / name).write_text("x")
    monkeypatch.setattr(ppocr_engine, "_runtime_installed", False)
    assert ppocr_engine.missing(ppocr_engine.AUTO) == ppocr_engine.MISSING_RUNTIME
    assert ppocr_engine.unavailable_reason(ppocr_engine.SMALL) == (
        "onnxruntime is not installed"
    )
    monkeypatch.setattr(ppocr_engine, "_runtime_installed", True)
    assert ppocr_engine.missing(ppocr_engine.AUTO) is None
    assert ppocr_engine.unavailable_reason("ppocr:huge").startswith("unknown")


def test_onnxruntime_is_not_imported_at_startup():
    # the window's modules import ppocr_engine; onnxruntime is imported when a
    # PP-OCR model loads, on a background thread
    code = (
        "import sys; sys.path.insert(0, %r); import mainwindow, camera_thread, main; "
        "print('onnxruntime' in sys.modules)" % str(SRC_DIR)
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=120
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip().splitlines()[-1] == "False"


def test_a_failed_load_is_reported(monkeypatch):
    monkeypatch.setattr(ppocr_engine, "unavailable_reason", lambda model: "no models")
    recognizer = ppocr_engine.Recognizer(ppocr_engine.SMALL)
    assert recognizer.wait(0) is False  # not started
    recognizer.start_loading()
    assert recognizer.wait(10) is False
    assert recognizer.state == ppocr_engine.FAILED
    assert "no models" in recognizer.error
    # a failure is final
    recognizer.start_loading()
    assert recognizer.state == ppocr_engine.FAILED


def test_loading_runs_on_a_background_thread(monkeypatch):
    started = threading.Event()
    release = threading.Event()
    threads = []

    def slow_load(self):
        threads.append(threading.current_thread())
        started.set()
        assert release.wait(10)
        self._session = FakeSession()
        self._characters = CHARACTERS
        self._input_name = "x"

    monkeypatch.setattr(ppocr_engine.Recognizer, "_load", slow_load)
    recognizer = ppocr_engine.Recognizer(ppocr_engine.SMALL)
    recognizer.start_loading()
    assert started.wait(10)
    assert recognizer.state == ppocr_engine.LOADING
    assert threads[0] is not threading.current_thread()
    recognizer.start_loading()  # already loading: no second thread
    release.set()
    assert recognizer.wait(10)
    assert len(threads) == 1


# --- TextDetector with PP-OCR (a fake recognizer) ------------------------------------


class FakeChoice:
    """Stands in for a Recognizer: reads each crop as scripted (by the crop's
    gray level, as FakeSession) and records the calls."""

    def __init__(self, model_id=ppocr_engine.SMALL, state=ppocr_engine.READY):
        self.model_id = model_id
        self.state = state
        self.error = None
        self.calls = []
        self.records = []
        self.confidence = 0.97

    def start_loading(self):
        pass

    def active(self):
        return self

    def wait(self, timeout=None):
        return self.state == ppocr_engine.READY

    def record(self, model_id, boxes, seconds, interval_ms):
        self.records.append((model_id, boxes, interval_ms))

    def recognize(self, crops, whitelists=None):
        self.calls.append(([c.copy() for c in crops], list(whitelists)))
        return [(str(int(c[0, 0, 0])), self.confidence) for c in crops]


@pytest.fixture
def ppocr_detector(monkeypatch):
    """A TextDetector reading with a FakeChoice (and FakeApi for Tesseract)."""
    from test_pipeline_ocr import FakeApi

    FakeApi.instances = []
    FakeApi.fail_next_init = False
    monkeypatch.setattr(tesseract, "PyTessBaseAPI", FakeApi)
    choice = FakeChoice()
    monkeypatch.setattr(ppocr_engine, "unavailable_reason", lambda model: None)
    monkeypatch.setattr(ppocr_engine, "create_choice", lambda model: choice)
    detector = TextDetector(ppocr_engine.SMALL)
    detector.choice = choice
    return detector


def scoreboard(values):
    """A colour frame with a box per value: box i is filled with value i (its
    top left pixel, which FakeChoice reads) and has a bright stroke whose
    place depends on the value, so it isn't blank and its picture changes
    with the value."""
    color = np.zeros((100, 400, 3), np.uint8)
    rects = []
    for i, value in enumerate(values):
        x = 10 + i * 90
        color[20:80, x : x + 80] = value
        stroke = x + 10 + value % 40
        color[40:70, stroke : stroke + 20] = (value + 128) % 256
        rects.append((x, 20, 80, 60))
    return color, cv2.cvtColor(color, cv2.COLOR_BGR2GRAY), rects


def test_ppocr_reads_every_box_in_one_batch_from_the_colour_frame(
    ppocr_detector, make_target
):
    color, gray, rects = scoreboard([12, 45, 7])
    color[20:80, 10:90, 2] = 200  # a red tint gray would lose
    boxes = [
        make_target("Home Score", rect=rects[0]),
        make_target("Time", rect=rects[1], format_regex=".*"),
        make_target("Custom", rect=rects[2], type=FieldType.TEXT, format_regex=".*"),
    ]
    results = ppocr_detector.detect_multi_text(None, gray, boxes, color=color)
    assert [(r.text, r.state) for r in results] == [
        ("12", State.Success),
        ("45", State.Success),
        ("7", State.Success),
    ]
    [(crops, whitelists)] = ppocr_detector.choice.calls
    # the colour crops, untouched by the boxes' Image cleanup settings
    assert crops[0].shape == (60, 80, 3) and crops[0][5, 5, 2] == 200
    assert whitelists == [NUMBER, TIME, GENERAL_CHAR_WHITELIST]
    assert results[0].extra["confidence"] == pytest.approx(97.0)
    # the batch's time goes to PP-OCR (automatic)
    assert ppocr_detector.choice.records == [(ppocr_engine.SMALL, 3, None)]


def test_ppocr_result_states(ppocr_detector, make_target):
    color, gray, rects = scoreboard([12, 45, 0])
    boxes = [
        # the format: a 2-digit score fails "Period 1-4"
        make_target("Period", rect=rects[0], ordinal_indicator=False),
        # the confidence threshold (fraction of the 0-1 confidence)
        make_target("Away Score", rect=rects[1], conf_thresh=0.98),
        # a blank box: nothing to read
        make_target("Time", rect=(300, 0, 50, 10)),
    ]
    results = ppocr_detector.detect_multi_text(None, gray, boxes, color=color)
    assert [(r.text, r.state) for r in results] == [
        ("12", State.FailedFilter),
        ("45", State.FailedFilter),
        ("", State.Empty),
    ]
    boxes[1].settings["conf_thresh"] = 0.9
    results = ppocr_detector.detect_multi_text(None, gray, boxes, color=color)
    assert results[1].state == State.Success


def test_ppocr_keeps_the_post_filters(ppocr_detector, make_target):
    color, gray, rects = scoreboard([3, 7])
    boxes = [
        make_target("Period", rect=rects[0]),  # ordinal suffix
        make_target(
            "Home Score",
            rect=rects[1],
            remove_leading_zeros=True,
            smoothing=True,
        ),
    ]
    results = ppocr_detector.detect_multi_text(None, gray, boxes, color=color)
    assert [r.text for r in results] == ["3rd", "7"]


def test_ppocr_skips_unchanged_boxes(ppocr_detector, make_target):
    color, gray, rects = scoreboard([12])
    box = make_target("Home Score", rect=rects[0], skip_similar_image=True)
    [first] = ppocr_detector.detect_multi_text(None, gray, [box], color=color)
    assert first.state == State.Success
    [second] = ppocr_detector.detect_multi_text(None, gray, [box], color=color)
    assert second.state == State.SameNoChange and second.unchanged_image
    assert len(ppocr_detector.choice.calls) == 1
    # a rejected reading isn't remembered: the box is read again
    color, gray, _ = scoreboard([99])
    box.settings["format_regex"] = "^\\d$"
    [third] = ppocr_detector.detect_multi_text(None, gray, [box], color=color)
    assert third.state == State.FailedFilter
    [fourth] = ppocr_detector.detect_multi_text(None, gray, [box], color=color)
    assert fourth.state == State.FailedFilter
    assert len(ppocr_detector.choice.calls) == 3


def test_the_dot_counter_works_with_ppocr(ppocr_detector, make_target):
    gray = np.zeros((60, 200), np.uint8)
    for x in (20, 60, 100):
        cv2.circle(gray, (x, 30), 8, 255, -1)
    box = make_target("Dots", rect=(0, 0, 200, 60), dot_detector=True)
    [result] = ppocr_detector.detect_multi_text(
        None, gray, [box], color=cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    )
    assert (result.text, result.state) == ("3", State.Success)
    assert ppocr_detector.choice.calls == []


def test_boxes_have_no_reading_while_ppocr_loads(ppocr_detector, make_target):
    ppocr_detector.choice.state = ppocr_engine.LOADING
    color, gray, rects = scoreboard([12])
    box = make_target("Home Score", rect=rects[0])
    [result] = ppocr_detector.detect_multi_text(None, gray, [box], color=color)
    assert result.state == State.Empty
    assert ppocr_detector.choice.calls == []
    assert ppocr_detector.engine_status().ppocr_state == ppocr_engine.LOADING


def test_a_ppocr_that_failed_to_load_falls_back_to_tesseract(
    ppocr_detector, make_target
):
    ppocr_detector.choice.state = ppocr_engine.FAILED
    ppocr_detector.choice.error = "RuntimeError: broken"
    gray = seven_segment("45")
    box = make_target("Home Score", rect=(0, 0, gray.shape[1], gray.shape[0]))
    [result] = ppocr_detector.detect_multi_text(None, gray, [box])
    # read by Tesseract (FakeApi reads "12")
    assert (result.text, result.state) == ("12", State.Success)
    assert ppocr_detector.api.lang == "scoreboard_general"
    assert ppocr_detector.choice.calls == []
    status = ppocr_detector.engine_status()
    assert status.fallback and status.ppocr_error == "RuntimeError: broken"


def test_a_failed_batch_reads_empty(ppocr_detector, make_target):
    def broken(crops, whitelists=None):
        raise RuntimeError("onnxruntime error")

    ppocr_detector.choice.recognize = broken
    color, gray, rects = scoreboard([12])
    box = make_target("Home Score", rect=rects[0])
    [result] = ppocr_detector.detect_multi_text(None, gray, [box], color=color)
    assert result.state == State.Empty


def test_the_binary_view_shows_what_ppocr_reads(ppocr_detector, make_target):
    color, gray, rects = scoreboard([120])
    box = make_target("Home Score", rect=rects[0])
    display = np.zeros_like(gray)
    ppocr_detector.detect_multi_text(None, gray, [box], color=color, display=display)
    x, y, w, h = rects[0]
    assert np.array_equal(display[y : y + h, x : x + w], gray[y : y + h, x : x + w])
    view = tesseract.render_binary_view(np.zeros_like(gray), gray, [box], ppocr=True)
    assert np.array_equal(view[y : y + h, x : x + w], gray[y : y + h, x : x + w])


def test_a_model_switch_keeps_the_tesseract_api_as_fallback(ppocr_detector):
    assert ppocr_detector.uses_ppocr()
    assert ppocr_detector.setOcrModel(TextDetector.OcrModelIndex.GENERAL_ENGLISH)
    assert not ppocr_detector.uses_ppocr()
    assert ppocr_detector.model == TextDetector.OcrModelIndex.GENERAL_ENGLISH
    api = ppocr_detector.api
    assert ppocr_detector.setOcrModel(ppocr_engine.SMALL)
    assert ppocr_detector.api is api and ppocr_detector.uses_ppocr()


def test_an_unavailable_ppocr_model_falls_back_to_general_scoreboard(monkeypatch):
    from test_pipeline_ocr import FakeApi

    FakeApi.instances = []
    FakeApi.fail_next_init = False
    monkeypatch.setattr(tesseract, "PyTessBaseAPI", FakeApi)
    monkeypatch.setattr(
        ppocr_engine, "unavailable_reason", lambda model: "the model files are missing"
    )
    detector = TextDetector(ppocr_engine.AUTO)
    assert not detector.uses_ppocr()
    assert detector.model == TextDetector.OcrModelIndex.SCOREBOARD_GENERAL
    assert detector.api.lang == "scoreboard_general"
    # the stored choice is the default; what reads is Tesseract
    assert ocr_models.stored_model() == ppocr_engine.AUTO
    assert ocr_models.effective_model(ppocr_engine.AUTO) == ocr_models.FALLBACK_MODEL


# --- PP-OCR (automatic) ----------------------------------------------------------------


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def chooser(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(ppocr_engine, "_recognizers", {})
    chooser = ppocr_engine.AutoChooser(clock=clock)
    for recognizer in (chooser.accurate, chooser.fast):
        recognizer.state = ppocr_engine.READY
    chooser.clock = clock
    return chooser


def feed(chooser, model, ms_per_frame, seconds, interval_ms=200, boxes=10, step=0.2):
    """Report frames of ms_per_frame for `seconds`, one every `step`."""
    end = chooser.clock.now + seconds
    while chooser.clock.now < end:
        chooser.record(model, boxes, ms_per_frame / 1000, interval_ms)
        chooser.clock.now += step


def test_automatic_starts_with_accurate_and_keeps_it_while_it_keeps_up(chooser):
    assert chooser.active() is chooser.accurate
    assert chooser.status() == (ppocr_engine.SMALL, ppocr_engine.AUTO_STARTING, None)
    feed(chooser, ppocr_engine.SMALL, 90, 30)
    assert chooser.active() is chooser.accurate
    model, reason, accurate_ms = chooser.status()
    assert (model, reason) == (ppocr_engine.SMALL, ppocr_engine.AUTO_KEEPS_UP)
    assert accurate_ms == pytest.approx(90)


def test_automatic_switches_to_fast_after_a_few_slow_seconds(chooser):
    # 150 ms of a 200 ms cycle is over 70%: not at once, after 3 s
    feed(chooser, ppocr_engine.SMALL, 150, 2.5)
    assert chooser.active() is chooser.accurate
    feed(chooser, ppocr_engine.SMALL, 150, 1.0)
    assert chooser.active() is chooser.fast
    assert chooser.status()[:2] == (ppocr_engine.TINY, ppocr_engine.AUTO_TOO_SLOW)


def test_a_slow_moment_doesnt_switch(chooser):
    for _ in range(5):
        feed(chooser, ppocr_engine.SMALL, 180, 1.0)
        feed(chooser, ppocr_engine.SMALL, 60, 2.0)
    assert chooser.active() is chooser.accurate


def test_automatic_goes_back_to_accurate_when_it_would_fit(chooser):
    feed(chooser, ppocr_engine.SMALL, 150, 4)
    assert chooser.active() is chooser.fast
    # 15 ms per box: 10 boxes at 5/s don't fit; 4 boxes (60 ms) would
    feed(chooser, ppocr_engine.TINY, 30, 20)
    assert chooser.active() is chooser.fast
    # hysteresis: fitting under 70% isn't enough, it must fit under 50%
    feed(chooser, ppocr_engine.TINY, 12, 20, boxes=9)  # 135 ms of 200
    assert chooser.active() is chooser.fast
    feed(chooser, ppocr_engine.TINY, 6, 9, boxes=4)  # 60 ms of 200
    assert chooser.active() is chooser.fast
    feed(chooser, ppocr_engine.TINY, 6, 2, boxes=4)
    assert chooser.active() is chooser.accurate
    assert chooser.status()[:2] == (ppocr_engine.SMALL, ppocr_engine.AUTO_KEEPS_UP)


def test_lowering_detections_per_second_brings_accurate_back(chooser):
    feed(chooser, ppocr_engine.SMALL, 150, 4)
    assert chooser.active() is chooser.fast
    # 1 detection per second: 150 ms of 1000
    feed(chooser, ppocr_engine.TINY, 30, 11, interval_ms=1000, step=1.0)
    assert chooser.active() is chooser.accurate


def test_automatic_uses_fast_when_accurate_fails(chooser):
    chooser.accurate.state = ppocr_engine.FAILED
    assert chooser.active() is chooser.fast
    assert chooser.status()[:2] == (ppocr_engine.TINY, ppocr_engine.AUTO_UNAVAILABLE)
    # and doesn't go back
    feed(chooser, ppocr_engine.TINY, 1, 30)
    assert chooser.active() is chooser.fast


def test_automatic_needs_the_time_between_detections(chooser):
    feed(chooser, ppocr_engine.SMALL, 500, 10, interval_ms=None)
    assert chooser.active() is chooser.accurate


def test_switches_are_logged(chooser, caplog):
    with caplog.at_level("INFO", logger="sc_logging"):
        feed(chooser, ppocr_engine.SMALL, 150, 4)
    assert "PP-OCR automatic: reading with fast" in caplog.text


def test_textdetector_reports_what_automatic_reads_with(monkeypatch, make_target):
    from test_pipeline_ocr import FakeApi

    monkeypatch.setattr(tesseract, "PyTessBaseAPI", FakeApi)
    monkeypatch.setattr(ppocr_engine, "unavailable_reason", lambda model: None)
    monkeypatch.setattr(ppocr_engine, "_recognizers", {})
    detector = TextDetector(ppocr_engine.AUTO)
    chooser = detector.ppocr
    assert isinstance(chooser, ppocr_engine.AutoChooser)
    small, tiny = FakeChoice(ppocr_engine.SMALL), FakeChoice(ppocr_engine.TINY)
    small.records = tiny.records = None
    chooser.accurate, chooser.fast = small, tiny
    detector.cycle_interval_ms = 100.0
    color, gray, rects = scoreboard([12, 34])
    boxes = [make_target("Home Score", rect=r) for r in rects]
    detector.detect_multi_text(None, gray, boxes, color=color)
    status = detector.engine_status()
    assert status.auto_model == ppocr_engine.SMALL
    assert status.auto_interval_ms == 100.0
    assert len(small.calls) == 1 and tiny.calls == []


# --- after the code review ----------------------------------------------------------


def lcd(text, fg=120, bg=80):
    """A dim display: 7-segment digits 40 gray levels above the background."""
    gray = seven_segment(text, fg=fg, bg=bg)
    return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR), gray


def test_skip_similar_sees_a_change_on_a_dim_display(ppocr_detector, make_target):
    # the gray crops differ by only 40 levels where a digit changed, which a
    # comparison made for binarized patches (64 levels) took for no change
    color, gray = lcd("12")
    box = make_target(
        "Home Score",
        rect=(0, 0, gray.shape[1], gray.shape[0]),
        skip_similar_image=True,
    )
    [first] = ppocr_detector.detect_multi_text(None, gray, [box], color=color)
    assert first.state == State.Success
    [same] = ppocr_detector.detect_multi_text(None, gray, [box], color=color)
    assert same.unchanged_image
    color, gray = lcd("13")
    [changed] = ppocr_detector.detect_multi_text(None, gray, [box], color=color)
    assert not changed.unchanged_image
    assert len(ppocr_detector.choice.calls) == 2


def test_a_box_without_contrast_isnt_read(ppocr_detector, make_target):
    # a switched-off display filmed by a camera: noise, nothing to read
    rng = np.random.default_rng(0)
    gray = np.clip(rng.normal(40, 3, (60, 120)), 0, 255).astype(np.uint8)
    box = make_target("Home Score", rect=(0, 0, 120, 60))
    [result] = ppocr_detector.detect_multi_text(
        None, gray, [box], color=cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    )
    assert result.state == State.Empty
    assert ppocr_detector.choice.calls == []
    assert tesseract.has_contrast(seven_segment("8", fg=120, bg=80))
    # the unlit LEDs of a dot-matrix display (a handball penalty timer, #140)
    unlit = np.full((100, 230), 44, np.uint8)
    for dy in (0, 1):
        for dx in (0, 1):
            unlit[2 + dy :: 6, 2 + dx :: 6] = 64
    assert not tesseract.has_contrast(unlit)


def test_a_failed_ppocr_no_longer_counts_as_reading(ppocr_detector):
    assert ppocr_detector.uses_ppocr()
    ppocr_detector.choice.state = ppocr_engine.FAILED
    # Tesseract reads: Binary view and Image cleanup are Tesseract's again
    assert not ppocr_detector.uses_ppocr()


def test_a_fallback_that_fails_is_tried_once(ppocr_detector, make_target, monkeypatch):
    attempts = []

    def broken(folder, model):
        attempts.append(model)
        raise RuntimeError("no tessdata")

    ppocr_detector.api = None
    monkeypatch.setattr(ppocr_detector, "_create_api", broken)
    ppocr_detector.choice.state = ppocr_engine.FAILED
    gray = seven_segment("4")
    box = make_target("Home Score", rect=(0, 0, gray.shape[1], gray.shape[0]))
    for _ in range(3):
        [result] = ppocr_detector.detect_multi_text(None, gray, [box])
        assert result.state == State.Empty
    assert attempts == ["scoreboard_general"]


def test_automatic_goes_back_to_accurate_if_fast_fails(chooser):
    feed(chooser, ppocr_engine.SMALL, 150, 4)
    assert chooser.active() is chooser.fast
    chooser.fast.state = ppocr_engine.FAILED
    assert chooser.active() is chooser.accurate
    # and doesn't try fast again (no switch, no log every 3 s)
    feed(chooser, ppocr_engine.SMALL, 150, 10)
    assert chooser.current == ppocr_engine.SMALL


# --- the real models ---------------------------------------------------------------


@pytest.fixture(scope="module")
def real_detectors():
    detectors = {}

    def get(model):
        if model not in detectors:
            detector = TextDetector(model)
            assert detector.model == model
            assert detector.wait_for_engine(120), detector.engine_status()
            detectors[model] = detector
        return detectors[model]

    return get


def box_for(make_target, image, name, **settings):
    return make_target(name, rect=(0, 0, image.shape[1], image.shape[0]), **settings)


@pytest.mark.ppocr
@pytest.mark.parametrize("model", [ppocr_engine.SMALL, ppocr_engine.TINY])
@pytest.mark.parametrize("text", ["0", "3", "12", "45", "88", "105", "199"])
def test_real_models_read_seven_segment_scores(
    real_detectors, make_target, model, text
):
    gray = seven_segment(text)
    box = box_for(make_target, gray, "Home Score")
    [result] = real_detectors(model).detect_multi_text(
        None, gray, [box], color=cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    )
    assert (result.text, result.state) == (text, State.Success)
    assert result.extra["confidence"] > 80


@pytest.mark.ppocr
@pytest.mark.parametrize("model", [ppocr_engine.SMALL, ppocr_engine.TINY])
@pytest.mark.parametrize("text", ["12:34", "0:59", "9.5", "45.1"])
def test_real_models_read_clocks(real_detectors, make_target, model, text):
    gray = seven_segment(text)
    box = box_for(make_target, gray, "Time")
    [result] = real_detectors(model).detect_multi_text(
        None, gray, [box], color=cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    )
    assert (result.text, result.state) == (text, State.Success)


@pytest.mark.ppocr
@pytest.mark.parametrize("model", [ppocr_engine.SMALL, ppocr_engine.TINY])
def test_real_models_read_text_and_dark_on_light(real_detectors, make_target, model):
    detector = real_detectors(model)
    text = hershey("HOME")
    box = box_for(make_target, text, "Custom", type=FieldType.TEXT, format_regex=".*")
    [result] = detector.detect_multi_text(
        None, text, [box], color=cv2.cvtColor(text, cv2.COLOR_GRAY2BGR)
    )
    assert result.text == "HOME"
    # an LCD: dark digits on a light background, read as they are
    lcd = seven_segment("27", fg=30, bg=200)
    box = box_for(make_target, lcd, "Home Score")
    [result] = detector.detect_multi_text(
        None, lcd, [box], color=cv2.cvtColor(lcd, cv2.COLOR_GRAY2BGR)
    )
    assert result.text == "27"


@pytest.mark.ppocr
def test_real_batch_reads_like_single_crops(real_detectors):
    recognizer = real_detectors(ppocr_engine.SMALL).ppocr.active()
    crops = [
        cv2.cvtColor(seven_segment(t), cv2.COLOR_GRAY2BGR)
        for t in ("1", "23", "456", "12:00")
    ] + [cv2.cvtColor(hershey("SCORESIGHT HOME"), cv2.COLOR_GRAY2BGR)]
    whitelists = [NUMBER, NUMBER, NUMBER, TIME, GENERAL_CHAR_WHITELIST]
    batched = recognizer.recognize(crops, whitelists)
    alone = [recognizer.recognize([c], [w])[0] for c, w in zip(crops, whitelists)]
    # the same texts; the confidences may differ in the last float digits
    # (onnxruntime's kernels sum in another order for another batch size)
    assert [text for text, _ in batched] == [text for text, _ in alone]
    assert [conf for _, conf in batched] == pytest.approx(
        [conf for _, conf in alone], abs=1e-4
    )
    assert [text for text, _ in batched[:4]] == ["1", "23", "456", "12:00"]


@pytest.mark.ppocr
def test_real_automatic_reads_with_accurate_on_a_fast_frame(
    real_detectors, make_target
):
    detector = real_detectors(ppocr_engine.AUTO)
    detector.cycle_interval_ms = 10_000.0
    gray = seven_segment("42")
    box = box_for(make_target, gray, "Home Score")
    for _ in range(3):
        [result] = detector.detect_multi_text(
            None, gray, [box], color=cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
        )
    assert result.text == "42"
    status = detector.engine_status()
    assert status.auto_model == ppocr_engine.SMALL
    assert status.auto_reason == ppocr_engine.AUTO_KEEPS_UP
    assert status.auto_accurate_ms is not None and status.auto_accurate_ms > 0


@pytest.mark.ppocr
def test_real_load_is_quick_and_logged(caplog):
    recognizer = ppocr_engine.Recognizer(ppocr_engine.TINY)
    started = time.perf_counter()
    with caplog.at_level("INFO", logger="sc_logging"):
        assert recognizer.load()
    assert time.perf_counter() - started < 30
    assert "PP-OCR: loaded PP-OCRv6_tiny_rec" in caplog.text
    assert recognizer.runtime_version
    recognizer.close()
    assert recognizer.state == ppocr_engine.NOT_LOADED
