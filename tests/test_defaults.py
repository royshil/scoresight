import re

import pytest

from defaults import (
    FieldType,
    default_boxes,
    default_custom_box_info,
    default_info_for_box_name,
    format_prefixes,
    normalize_settings_dict,
)

CANONICAL_SETTINGS = {
    "is_custom": True,
    "obs_source_name": "",
    "format_regex": format_prefixes[12],
    "type": FieldType.NUMBER,
    "smoothing": False,
    "clear_value": "never",
    "conf_thresh": 0.0,
    "cleanup_thresh": 0,
    "dilate": 1,
    "skew": 0,
    "vscale": 10,
    "autocrop": False,
    "skip_similar_image": False,
    "remove_leading_zeros": False,
    "rescale_patch": True,
    "normalize_wh_ratio": False,
    "invert_patch": False,
    "dot_detector": False,
    "binarization_method": 0,
    "ordinal_indicator": False,
    "templatefield": False,
    "templatefield_text": "",
    "composite_box": False,
}


@pytest.mark.parametrize("settings", [{}, None])
def test_normalize_settings_defaults(settings):
    assert normalize_settings_dict(settings, None) == CANONICAL_SETTINGS


def test_normalize_settings_uses_box_info_for_missing_keys():
    period = normalize_settings_dict({}, default_info_for_box_name("Period"))
    assert period["is_custom"] is False
    assert period["ordinal_indicator"] is True
    assert period["format_regex"] == format_prefixes[8]
    assert period["obs_source_name"] == "Period"
    assert period["type"] == FieldType.NUMBER

    clock = normalize_settings_dict({}, default_info_for_box_name("Time"))
    assert clock["type"] == FieldType.TIME
    assert clock["format_regex"] == format_prefixes[0]


def test_normalize_settings_keeps_user_values():
    user = {
        "type": FieldType.TEXT,
        "conf_thresh": 0.9,
        "ordinal_indicator": False,
        "format_regex": "^x$",
        "dilate": 0,
    }
    result = normalize_settings_dict(user, default_info_for_box_name("Period"))
    for key, value in user.items():
        assert result[key] == value
    # missing keys still get defaults
    assert result["vscale"] == 10
    # the input dict is not modified
    assert set(user) == {
        "type",
        "conf_thresh",
        "ordinal_indicator",
        "format_regex",
        "dilate",
    }


def test_normalize_settings_drops_unknown_and_runtime_keys():
    result = normalize_settings_dict(
        {"median_wh_ratio": 0.5, "no_such_setting": 1}, None
    )
    assert set(result) == set(CANONICAL_SETTINGS)


def test_default_info_for_box_name():
    names = [box["name"] for box in default_boxes]
    assert names == [
        "Home Score",
        "Away Score",
        "Time",
        "Period",
        "Home Fouls",
        "Away Fouls",
        "Shot Clock",
    ]
    for box in default_boxes:
        assert default_info_for_box_name(box["name"]) is box
        assert box["is_custom"] is False
        # every key normalize_settings_dict reads from box info is present
        assert {"type", "obs_source_name", "format_regex", "ordinal_indicator"} <= set(
            box
        )
    assert default_info_for_box_name("Team Name") is default_custom_box_info
    assert default_custom_box_info["is_custom"] is True


def test_format_prefixes_compile():
    assert len(format_prefixes) == 14
    for pattern in format_prefixes:
        re.compile(pattern)


@pytest.mark.parametrize(
    ("index", "text", "matches"),
    [
        (0, "12:34", True),
        (0, "9.5", True),
        (0, "60:00", False),
        # a colon then one digit: tenths, only in Time MM:ss and ss:m
        (0, "59:8", False),
        (1, "59:8", True),
        (1, "8:9", True),
        (1, "59.8", True),
        (1, "1:00", True),
        (1, "12:34", True),
        (1, "60:0", False),
        (1, "1:0:0", False),
        (1, "1:", False),
        (2, "5:07", True),
        (2, "5.7", False),
        (3, "59.9", True),
        (4, "07", True),
        # clocks show 7, not 07
        (4, "7", True),
        (4, "60", False),
        (4, "007", False),
        (5, "39", True),
        (5, "8", True),
        (5, "08", True),
        (5, "0", True),
        (5, "40", False),
        (5, "", False),
        (5, "100", False),
        (6, "199", True),
        (6, "200", False),
        (7, "999", True),
        (8, "4", True),
        (8, "5", False),
        (9, "7", True),
        (10, "Home1", True),
        (10, "Home 1", False),
        (11, "anything at all", True),
        (12, "", True),
        (12, "12a", False),
    ],
)
def test_format_prefix_presets(index, text, matches):
    assert (re.fullmatch(format_prefixes[index], text) is not None) == matches


@pytest.mark.parametrize(
    ("text", "matches"),
    [("24", True), ("10", True), ("9", True), ("8", True), ("0", True), ("40", False)],
)
def test_shot_clock_accepts_a_single_digit(text, matches):
    # A shot clock shows 9, 8, ... 0 in its last ten seconds, not 09: a format
    # of exactly two digits rejected them and the outputs stayed at 10.
    shot_clock = normalize_settings_dict({}, default_info_for_box_name("Shot Clock"))
    assert shot_clock["format_regex"] == format_prefixes[5]
    assert (re.fullmatch(shot_clock["format_regex"], text) is not None) == matches
