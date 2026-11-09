"""TextDetector.detect_multi_text and its preprocessing (src/tesseract.py).

Most tests swap tesserocr's PyTessBaseAPI for FakeApi, which records the
patches it is given and returns a scripted read, so they check the pipeline
around Tesseract deterministically. The `ocr` tests use the real models.
"""

import threading

import numpy as np
import pytest

pytest.importorskip("tesserocr")

import tesseract  # noqa: E402
from defaults import FieldType, format_prefixes  # noqa: E402
from synthetic_images import binarize, seven_segment  # noqa: E402
from tesseract import TextDetector  # noqa: E402
from text_detection_target import TextDetectionTargetWithResult  # noqa: E402

SUCCESS = TextDetectionTargetWithResult.ResultState.Success
FAILED = TextDetectionTargetWithResult.ResultState.FailedFilter
EMPTY = TextDetectionTargetWithResult.ResultState.Empty
Binarization = TextDetector.BinarizationMethod


class FakeIterator:
    """Duck-types tesserocr's result iterator over RIL.SYMBOL."""

    def __init__(self, symbols):
        self.symbols = symbols  # [(char, (x0, y0, x1, y1), confidence)]
        self.index = 0

    def Next(self, level):
        self.index += 1
        return self.index < len(self.symbols)

    def GetUTF8Text(self, level):
        return self.symbols[self.index][0]

    def BoundingBox(self, level):
        return self.symbols[self.index][1]

    def Confidence(self, level):
        return self.symbols[self.index][2]


class FakeApi:
    """Stands in for PyTessBaseAPI. Every instance created is kept in
    `instances`; set `lock` to assert each call runs under the detector's lock."""

    instances = []
    fail_next_init = False

    def __init__(self, path=None, lang=None):
        if FakeApi.fail_next_init:
            FakeApi.fail_next_init = False
            raise RuntimeError("Failed to init API, possibly an invalid tessdata path")
        self.lang = lang
        self.text = "12"
        self.mean_conf = 90
        self.symbol_conf = 90.0
        self.images = []
        self.variables = {}
        self.lock = None
        self.ended = False
        FakeApi.instances.append(self)

    def _check_lock(self):
        assert not self.ended, "used after End()"
        if self.lock is not None:
            assert self.lock.locked(), "Tesseract called without the API lock"

    def SetPageSegMode(self, mode):
        pass

    def SetVariable(self, name, value):
        self._check_lock()
        self.variables[name] = value

    def SetImage(self, image):
        self._check_lock()
        self.images.append(np.array(image))

    def GetUTF8Text(self):
        self._check_lock()
        return self.text + "\n"

    def GetIterator(self):
        self._check_lock()
        if not self.text:
            return None
        symbols = [
            (char, (10 * i, 0, 10 * i + 8, 16), self.symbol_conf)
            for i, char in enumerate(self.text)
        ]
        return FakeIterator(symbols)

    def MeanTextConf(self):
        self._check_lock()
        return self.mean_conf

    def End(self):
        self.ended = True


@pytest.fixture
def fake_api(monkeypatch):
    FakeApi.instances = []
    FakeApi.fail_next_init = False
    monkeypatch.setattr(tesseract, "PyTessBaseAPI", FakeApi)
    return FakeApi


@pytest.fixture
def detector(fake_api):
    detector = TextDetector(TextDetector.OcrModelIndex.SCOREBOARD_GENERAL)
    detector.api.lock = detector.api_lock
    return detector


def digits_frame(text="12", size=(240, 320), at=(40, 60)):
    """A gray frame with 7-segment digits pasted at `at` (x, y) and their box."""
    gray = np.zeros(size, np.uint8)
    digits = seven_segment(text)
    x, y = at
    gray[y : y + digits.shape[0], x : x + digits.shape[1]] = digits
    return gray, (x, y, digits.shape[1], digits.shape[0])


def test_box_past_the_frame_edge_is_read_and_not_mutated(detector, make_target):
    gray, _ = digits_frame()
    # sticks out on all four sides of the 320x240 frame
    box = make_target("Home Score", rect=(-30, -20, 400, 300))
    detector.detect_multi_text(binarize(gray), gray, [box])
    # the user's box (shared with the UI and saved to disk) is untouched
    assert (box.x(), box.y(), box.width(), box.height()) == (-30, -20, 400, 300)
    # the part inside the frame was read (at 35 px height after rescale_patch)
    [image] = detector.api.images
    assert image.shape[0] == 35
    assert image.shape[1] == round(320 * 35 / 240)


def test_box_partly_past_the_left_edge_is_not_empty(detector, make_target):
    gray, (x, y, w, h) = digits_frame(at=(0, 60))
    box = make_target("Home Score", rect=(-2, y, w + 2, h))
    [result] = detector.detect_multi_text(binarize(gray), gray, [box])
    assert (result.text, result.state) == ("12", SUCCESS)
    # per-character boxes stay relative to the box, not the clipped patch
    assert result.extra["boxes"][0]["x"] == 2


def test_box_outside_the_frame_is_empty(detector, make_target):
    gray, _ = digits_frame()
    box = make_target("Home Score", rect=(400, 10, 50, 50))
    [result] = detector.detect_multi_text(binarize(gray), gray, [box])
    assert result.state == EMPTY
    assert detector.api.images == []
    assert (box.x(), box.width()) == (400, 50)


@pytest.mark.parametrize(
    "method", [Binarization.LOCAL, Binarization.ADAPTIVE, Binarization.NO_BINARIZATION]
)
def test_dilation_reaches_the_ocr_with_every_binarization(
    detector, make_target, method
):
    gray, rect = digits_frame()
    thin = make_target(
        "Home Score",
        rect=rect,
        binarization_method=method,
        dilate=0,
        rescale_patch=False,
    )
    thick = make_target(
        "Home Score",
        rect=rect,
        binarization_method=method,
        dilate=3,
        rescale_patch=False,
    )
    detector.detect_multi_text(None, gray, [thin, thick])
    thin_image, thick_image = detector.api.images
    assert thick_image.shape == thin_image.shape
    # dilation grows the bright pixels
    assert np.count_nonzero(thick_image > 127) > np.count_nonzero(thin_image > 127)


def test_frame_images_are_not_modified(detector, make_target):
    gray, rect = digits_frame()
    binary = binarize(gray)
    gray_before, binary_before = gray.copy(), binary.copy()
    boxes = [
        make_target("Home Score", rect=rect, dilate=3, cleanup_thresh=1.0, vscale=5),
        make_target(
            "Away Score", rect=rect, dilate=2, binarization_method=Binarization.LOCAL
        ),
        make_target("Time", rect=rect, skew=10),
    ]
    detector.detect_multi_text(binary, gray, boxes)
    assert np.array_equal(gray, gray_before)
    assert np.array_equal(binary, binary_before)


def test_overlapping_boxes_do_not_affect_each_other(detector, make_target):
    gray, (x, y, w, h) = digits_frame()
    inner = make_target("Away Score", rect=(x, y, w // 2, h), rescale_patch=False)
    outer = make_target("Home Score", rect=(x, y, w, h), dilate=4, rescale_patch=False)
    detector.detect_multi_text(binarize(gray), gray, [inner])
    alone = detector.api.images[-1]
    detector.detect_multi_text(binarize(gray), gray, [outer, inner])
    after_outer = detector.api.images[-1]
    assert np.array_equal(alone, after_outer)


def test_display_shows_the_preprocessed_patches(detector, make_target):
    gray, rect = digits_frame()
    binary = binarize(gray)
    display = binary.copy()
    box = make_target("Home Score", rect=rect, dilate=3)
    detector.detect_multi_text(binary, gray, [box], display=display)
    x, y, w, h = rect
    assert np.count_nonzero(display[y : y + h, x : x + w]) > np.count_nonzero(
        binary[y : y + h, x : x + w]
    )
    # render_binary_view (used for previews between OCR passes) draws the same
    assert np.array_equal(tesseract.render_binary_view(binary, gray, [box]), display)


def test_global_binarization_is_computed_only_when_needed(
    detector, make_target, monkeypatch
):
    calls = []
    real = tesseract.global_binarization
    monkeypatch.setattr(
        tesseract,
        "global_binarization",
        lambda gray: calls.append(1) or real(gray),
    )
    gray, rect = digits_frame()
    local = make_target("Home Score", rect=rect, binarization_method=Binarization.LOCAL)
    detector.detect_multi_text(None, gray, [local])
    assert calls == []
    global_box = make_target("Away Score", rect=rect)
    [first, second] = detector.detect_multi_text(None, gray, [global_box, global_box])
    assert calls == [1]  # once per frame, shared by the boxes
    assert first.state == SUCCESS


@pytest.mark.parametrize("rows", [1, 2, 8, 9])
def test_vertical_scale_on_a_short_patch(detector, make_target, rows):
    gray, (x, y, w, h) = digits_frame()
    box = make_target("Home Score", rect=(x, y + h // 2, w, rows), vscale=1)
    [result] = detector.detect_multi_text(binarize(gray), gray, [box])
    assert result.state in (SUCCESS, EMPTY, FAILED)


def test_preprocess_vscale_keeps_the_patch_size():
    gray, (x, y, w, h) = digits_frame()
    for vscale in (1, 5, 9, 10, 12):
        patch = tesseract.preprocess_patch(
            {"vscale": vscale, "binarization_method": Binarization.NO_BINARIZATION},
            (x, y, x + w, y + h),
            gray,
            None,
        )
        assert patch.shape == (h, w)


# --- blank patches (#30) ------------------------------------------------------------


@pytest.mark.parametrize("value", [0, 255])
def test_blank_patch_is_empty_without_ocr(detector, make_target, value):
    blank = np.full((120, 200), value, np.uint8)
    box = make_target("Home Score", rect=(10, 10, 100, 60))
    [result] = detector.detect_multi_text(blank, blank, [box])
    assert (result.text, result.state) == ("", EMPTY)
    assert detector.api.images == []


@pytest.mark.parametrize("value", [0, 40, 255])
@pytest.mark.parametrize(
    "method", [Binarization.GLOBAL, Binarization.LOCAL, Binarization.ADAPTIVE]
)
def test_blank_patch_still_counts_zero_dots(detector, make_target, value, method):
    # Local and Adaptive binarization turn a uniform area all white, which has
    # one contour (the whole patch): it was counted as one dot
    blank = np.full((120, 200), value, np.uint8)
    box = make_target(
        "Home Score",
        rect=(10, 10, 100, 60),
        dot_detector=True,
        binarization_method=method,
    )
    [result] = detector.detect_multi_text(blank, blank, [box])
    assert (result.text, result.state) == ("0", SUCCESS)


def test_dot_counter_with_skip_similar_image_reads_dots_after_a_blank_box(
    detector, make_target
):
    # "0" from a blank box is an accepted read, so the comparison image must be
    # the blank one: otherwise the dots coming back would look unchanged and be
    # published as the box's last reading, "0". (A blank box is counted every
    # time; it costs nothing.)
    dots = np.zeros((60, 120), np.uint8)
    for x in (20, 60, 100):
        dots[25:35, x - 5 : x + 5] = 255
    blank = np.zeros_like(dots)
    box = make_target(
        "Home Score", rect=(0, 0, 120, 60), dot_detector=True, skip_similar_image=True
    )

    def read(image):
        [result] = detector.detect_multi_text(image, image, [box])
        return "unchanged" if result.unchanged_image else result.text

    assert [read(dots), read(dots), read(blank), read(blank), read(dots)] == [
        "3",
        "unchanged",
        "0",
        "0",
        "3",
    ]


@pytest.mark.ocr
@pytest.mark.parametrize(
    "model", ["DAKTRONICS", "SCOREBOARD_GENERAL", "SCOREBOARD_GENERAL_LARGE"]
)
def test_scoreboard_models_read_a_blank_box_as_empty(make_target, model):
    # these models hallucinate digits (e.g. "34") on an all-background patch
    detector = TextDetector(TextDetector.OcrModelIndex.SCOREBOARD_GENERAL)
    try:
        assert detector.setOcrModel(getattr(TextDetector.OcrModelIndex, model))
        blank = np.zeros((60, 120), np.uint8)
        box = make_target("Home Score", rect=(0, 0, 120, 60))
        [result] = detector.detect_multi_text(binarize(blank), blank, [box])
        assert (result.text, result.state) == ("", EMPTY)
    finally:
        detector.api.End()


# --- confidence threshold ------------------------------------------------------------


@pytest.mark.parametrize(
    ("mean_conf", "conf_thresh", "state"),
    [
        (40, 0.5, FAILED),
        (60, 0.5, SUCCESS),
        (89, 0.9, FAILED),
        (90, 0.9, SUCCESS),
        (12, 0.0, SUCCESS),
        # a percentage in a hand-edited settings file
        (40, 50, FAILED),
    ],
)
def test_conf_thresh_is_a_fraction_of_tesseracts_percentage(
    detector, make_target, mean_conf, conf_thresh, state
):
    detector.api.mean_conf = mean_conf
    gray, rect = digits_frame()
    box = make_target("Home Score", rect=rect, conf_thresh=conf_thresh)
    [result] = detector.detect_multi_text(binarize(gray), gray, [box])
    assert (result.text, result.state) == ("12", state)


@pytest.mark.parametrize(("symbol_conf", "state"), [(95.0, SUCCESS), (30.0, FAILED)])
def test_zero_mean_conf_falls_back_to_the_character_confidences(
    detector, make_target, symbol_conf, state
):
    # MeanTextConf() bottoms out at 0 on some correct reads
    detector.api.mean_conf = 0
    detector.api.symbol_conf = symbol_conf
    gray, rect = digits_frame()
    box = make_target("Home Score", rect=rect, conf_thresh=0.5)
    [result] = detector.detect_multi_text(binarize(gray), gray, [box])
    assert result.state == state


@pytest.mark.ocr
def test_real_confidence_threshold_extremes(make_target):
    detector = TextDetector(TextDetector.OcrModelIndex.SCOREBOARD_GENERAL)
    try:
        gray, rect = digits_frame("45")
        lenient = make_target("Home Score", rect=rect, conf_thresh=0.0)
        strict = make_target("Away Score", rect=rect, conf_thresh=1.0)
        [ok, rejected] = detector.detect_multi_text(
            binarize(gray), gray, [lenient, strict]
        )
        assert (ok.text, ok.state) == ("45", SUCCESS)
        # nothing is 100% confident
        assert (rejected.text, rejected.state) == ("45", FAILED)
    finally:
        detector.api.End()


# --- whitelist, filters ----------------------------------------------------------------


def test_whitelist_follows_the_field_type(detector, make_target):
    gray, rect = digits_frame()
    for field_type, whitelist in [
        (FieldType.NUMBER, "0123456789"),
        (FieldType.TIME, "0123456789:."),
        (FieldType.TEXT, tesseract.GENERAL_CHAR_WHITELIST),
    ]:
        box = make_target("Custom", rect=rect, type=field_type)
        detector.detect_multi_text(binarize(gray), gray, [box])
        assert detector.api.variables["tessedit_char_whitelist"] == whitelist


def test_remove_leading_zeros_keeps_a_failed_read_empty(detector, make_target):
    detector.api.text = ""
    gray, rect = digits_frame()
    box = make_target("Home Score", rect=rect, remove_leading_zeros=True)
    [result] = detector.detect_multi_text(binarize(gray), gray, [box])
    assert (result.text, result.state) == ("", EMPTY)
    detector.api.text = "007"
    [result] = detector.detect_multi_text(binarize(gray), gray, [box])
    assert result.text == "7"


def test_shot_clock_reads_its_last_ten_seconds(detector, make_target):
    # A shot clock shows 9, 8, ... 0 without a leading zero; its default
    # format (Shotclock 0-39) once took exactly two digits, so those readings
    # failed the filter and the outputs stayed at 10.
    gray, rect = digits_frame()
    box = make_target("Shot Clock", rect=rect)
    states = {}
    for text in ["24", "10", "9", "8", "0", "08", "40"]:
        detector.api.text = text
        [result] = detector.detect_multi_text(binarize(gray), gray, [box])
        states[text] = result.state
    assert states == {
        "24": SUCCESS,
        "10": SUCCESS,
        "9": SUCCESS,
        "8": SUCCESS,
        "0": SUCCESS,
        "08": SUCCESS,
        "40": FAILED,
    }


@pytest.mark.parametrize(
    "text, last_text, expected",
    [
        ("236", "2:38", "2:36"),
        ("1204", "12:05", "12:04"),
        ("9000", "89:59", "90:00"),
        ("225", "23.6", "22.5"),  # tenths: one digit after the dot
        ("597", "59:8", "59:7"),  # tenths after a colon
        ("59", "1:00", None),  # no digit left before the colon
        ("236", None, None),  # no good reading yet: no guess
        ("236", "", None),  # cleared
        ("236", "24", None),  # the last good reading has no separator
        ("2:36", "2:38", None),  # not only digits
        ("2a36", "2:38", None),
        ("", "2:38", None),
        # a race time's two separators (#194's swim board): one or both missing
        ("128.5", "1:28.0", "1:28.5"),
        ("1285", "1:28.0", "1:28.5"),
        ("1:2245", "1:22.45", "1:22.45"),
        ("12:245", "1:22.45", None),  # a colon where the last reading had none
        ("1:22.45", "1:22.45", None),  # nothing missing
        # tenths while the clock runs, hundredths at the finish: 12245 after
        # 1:22.5 could be 1:22.45 or 12:24.5
        ("12245", "1:22.5", None),
        ("1:2245", "1:22.5", None),
    ],
)
def test_restore_separator(text, last_text, expected):
    assert tesseract.restore_separator(text, last_text) == expected


def test_a_clock_read_without_its_colon_gets_it_back(detector, make_target):
    # A board that lights a third dot in its colon when the clock stops reads
    # as 236 (discussion #167): the separator of the box's last good reading
    # is put back where it was, if the box's format then takes the reading.
    gray, rect = digits_frame()
    box = make_target("Time", rect=rect)  # Time mm:ss.d

    def read(text, last_text):
        box.last_text = last_text
        detector.api.text = text
        [result] = detector.detect_multi_text(binarize(gray), gray, [box])
        return result.text, result.state

    assert read("236", "2:38") == ("2:36", SUCCESS)
    assert read("225", "23.6") == ("22.5", SUCCESS)
    # 236 could be 2:36 or 23.6: without a good reading, it isn't guessed
    assert read("236", None) == ("236", FAILED)
    # restored, it must still match the format: 5:96 isn't a time
    assert read("596", "1:00") == ("596", FAILED)
    # a reading that matches the format is left alone
    assert read("2:35", "2:38") == ("2:35", SUCCESS)


def test_a_race_time_read_without_its_colon_gets_it_back(detector, make_target):
    # #194's swim board: the running clock 1:28.0 read as 128.0
    gray, rect = digits_frame()
    box = make_target(
        "Lane 1 Time", rect=rect, type=FieldType.TIME, format_regex=format_prefixes[13]
    )

    def read(text, last_text):
        box.last_text = last_text
        detector.api.text = text
        [result] = detector.detect_multi_text(binarize(gray), gray, [box])
        return result.text, result.state

    assert read("128.0", "1:27.5") == ("1:28.0", SUCCESS)
    assert read("1:22.45", "1:22.4") == ("1:22.45", SUCCESS)
    assert read("12245", "1:22.4") == ("12245", FAILED)


def test_one_failing_box_does_not_stop_the_others(detector, make_target):
    gray, rect = digits_frame()
    broken = make_target("Home Score", rect=rect)
    broken.settings = {"binarization_method": "bogus", "vscale": "x"}
    good = make_target("Away Score", rect=rect)
    [bad, ok] = detector.detect_multi_text(binarize(gray), gray, [broken, good])
    assert bad.state == EMPTY
    assert (ok.text, ok.state) == ("12", SUCCESS)


# --- skip similar image ----------------------------------------------------------------


def test_skip_similar_image_detects_a_one_digit_change(detector, make_target):
    box = make_target("Home Score", rect=(0, 0, 1, 1), skip_similar_image=True)
    reads = []
    for value in ["18", "18", "19", "19", "88"]:
        gray, rect = digits_frame(value)
        box.setRect(*rect)
        [result] = detector.detect_multi_text(binarize(gray), gray, [box])
        reads.append(
            (result.text, result.state.name)
            if not result.unchanged_image
            else "unchanged"
        )
    # FakeApi always reads "12"; an unchanged image isn't read again (the
    # capture thread reports the box's last good reading as SameNoChange)
    assert reads == [
        ("12", "Success"),
        "unchanged",
        ("12", "Success"),
        "unchanged",
        ("12", "Success"),
    ]


def test_skip_similar_image_reads_a_rejected_or_empty_image_again(
    detector, make_target
):
    # The comparison image is the last accepted read's. Remembering a rejected
    # read's image made every later frame "unchanged", which the capture thread
    # publishes as the box's previous value (SameNoChange), so the box kept
    # showing the old score until the board changed again.
    box = make_target(
        "Home Score", rect=(0, 0, 1, 1), skip_similar_image=True, conf_thresh=0.5
    )
    api = detector.api

    def read(value, text="12", confidence=90):
        api.text = text
        api.mean_conf = confidence
        api.symbol_conf = float(confidence)
        gray, rect = digits_frame(value)
        box.setRect(*rect)
        [result] = detector.detect_multi_text(binarize(gray), gray, [box])
        return "unchanged" if result.unchanged_image else result.state.name

    assert read("12") == "Success"
    assert read("12") == "unchanged"
    # the board changes to 13, and its first reads fall under the threshold
    assert read("13", "13", confidence=20) == "FailedFilter"
    assert read("13", "13", confidence=20) == "FailedFilter"
    # or are empty
    assert read("13", "") == "Empty"
    assert read("13", "13") == "Success"
    assert read("13", "13") == "unchanged"
    # the board goes back to 12: not like the last accepted image (13)
    assert read("12") == "Success"


def test_patches_similar_ignores_a_few_noisy_pixels():
    patch = binarize(seven_segment("188"))
    noisy = patch.copy()
    noisy[0, :3] = 255 - noisy[0, :3]
    assert tesseract.patches_similar(patch, noisy)
    # one segment of one digit (8 -> 9) is a change
    assert not tesseract.patches_similar(patch, binarize(seven_segment("189")))
    # a different size (the box was resized) is never similar
    assert not tesseract.patches_similar(patch, patch[:, 1:])
    assert not tesseract.patches_similar(None, patch)


# --- smoothing and width/height normalization --------------------------------------------


def test_smoothing_ignores_rejected_and_empty_reads(detector, make_target):
    gray, rect = digits_frame()
    box = make_target("Home Score", rect=rect, smoothing=True)
    outputs = []
    for text in ["12", "12", "", "799", "9", "9", "9"]:
        detector.api.text = text
        [result] = detector.detect_multi_text(binarize(gray), gray, [box])
        outputs.append((result.text, result.state))
    assert outputs == [
        ("12", SUCCESS),
        ("12", SUCCESS),
        ("", EMPTY),
        ("799", FAILED),  # fails the score regex: not smoothed, not remembered
        ("12", SUCCESS),
        ("9", SUCCESS),  # tie 12/9: the most recent wins
        ("9", SUCCESS),
    ]


def test_wh_ratio_is_a_rolling_median_reset_by_settings_changes(detector, make_target):
    gray, rect = digits_frame()
    box = make_target("Home Score", rect=rect, normalize_wh_ratio=True)
    detector.detect_multi_text(binarize(gray), gray, [box])
    # FakeApi's characters are 8x16 (ratio 0.5) in the 35 px rescaled patch,
    # i.e. measured in the box's own pixels
    first = box.median_wh_ratio(tesseract._wh_ratio_key(box.settings))
    assert first == pytest.approx(0.5, rel=0.1)
    assert "median_wh_ratio" not in box.settings  # runtime state, not a setting
    # a preprocessing change starts over
    box.settings = dict(box.settings, vscale=5)
    assert box.median_wh_ratio(tesseract._wh_ratio_key(box.settings)) is None
    # only the last WH_RATIO_WINDOW ratios count
    key = tesseract._wh_ratio_key(box.settings)
    box.add_wh_ratios(key, [5.0] * 10)
    box.add_wh_ratios(key, [0.4] * box.WH_RATIO_WINDOW)
    assert box.median_wh_ratio(key) == pytest.approx(0.4)


# --- OCR model changes ---------------------------------------------------------------------


def test_model_swap_waits_for_the_recognition_in_progress(detector, make_target):
    old_api = detector.api
    gray, rect = digits_frame()
    box = make_target("Home Score", rect=rect, conf_thresh=0.5)
    in_ocr = threading.Event()
    release = threading.Event()
    original = old_api.GetUTF8Text

    def slow_read():
        in_ocr.set()
        assert release.wait(5)
        return original()

    old_api.GetUTF8Text = slow_read
    results = []
    worker = threading.Thread(
        target=lambda: results.extend(
            detector.detect_multi_text(binarize(gray), gray, [box])
        )
    )
    worker.start()
    assert in_ocr.wait(5)
    swapper = threading.Thread(
        target=detector.setOcrModel, args=(TextDetector.OcrModelIndex.GENERAL_ENGLISH,)
    )
    swapper.start()
    swapper.join(0.2)
    # the swap is blocked until the box's whole Tesseract sequence is done
    assert swapper.is_alive()
    assert detector.api is old_api and not old_api.ended
    release.set()
    worker.join(5)
    swapper.join(5)
    assert [r.state for r in results] == [SUCCESS]
    assert old_api.ended and detector.api is not old_api
    assert detector.api.lang == "eng"


def test_failed_model_load_keeps_the_current_model(detector, fake_api, tmp_path):
    current = detector.api
    bad = tmp_path / "broken.traineddata"
    bad.write_bytes(b"not a model")
    fake_api.fail_next_init = True
    assert detector.setOcrModel(str(bad)) is False
    assert detector.api is current and not current.ended
    assert detector.setOcrModel(str(tmp_path / "missing.traineddata")) is False
    assert detector.setOcrModel(None) is False
    assert detector.api is current


def test_detector_loads_the_stored_model(fake_api):
    from storage import store_data

    store_data(
        "scoresight.json", "ocr_model", TextDetector.OcrModelIndex.GENERAL_ENGLISH
    )
    assert TextDetector().api.lang == "eng"
    store_data("scoresight.json", "ocr_model", "C:/no/such/model.traineddata")
    assert TextDetector().api.lang == "scoreboard_general"


def test_no_model_loaded_reads_empty(detector, make_target):
    detector.api = None
    gray, rect = digits_frame()
    box = make_target("Home Score", rect=rect)
    [result] = detector.detect_multi_text(binarize(gray), gray, [box])
    assert result.state == EMPTY


@pytest.mark.ocr
def test_invalid_custom_model_keeps_the_real_model(tmp_path, make_target):
    detector = TextDetector(TextDetector.OcrModelIndex.SCOREBOARD_GENERAL)
    try:
        bad = tmp_path / "broken.traineddata"
        bad.write_bytes(b"not a model")
        assert detector.setOcrModel(str(bad)) is False
        gray, rect = digits_frame("45")
        [result] = detector.detect_multi_text(
            binarize(gray), gray, [make_target("Home Score", rect=rect)]
        )
        assert (result.text, result.state) == ("45", SUCCESS)
    finally:
        detector.api.End()
