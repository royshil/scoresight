"""Field types, display technologies and their mapping to ScoreSight's boxes.

A dataset row's field_type says what kind of value the crop shows. Each one maps
to the box ScoreSight would use for it (defaults.py), which gives the box
settings the Tesseract adapter reads it with and the character whitelist and
format regex of the "ScoreSight post-filter" scoring. Where a row also has a
role (commons_scoreboards: home_score, shot_clock, ...) that one of
ScoreSight's preset boxes is for, the crop is read with that preset instead,
as a user would box it (ROLE_BOXES), as long as the preset reads the same kind
of value (a period that shows "4TH" is a text field, read as text).
"""

import re

from ocr_eval._src import import_defaults

FIELD_TYPES = ("score", "clock", "period", "number", "text", "other")
DISPLAY_TECHS = (
    "led7",  # 7-segment LED or LCD-style segment digits (lit segments)
    "dotmatrix",  # LED/bulb dot matrix or pixel display
    "lcd",  # reflective LCD (dark segments on a light background)
    "bulb",  # incandescent bulb grid
    "flip",  # flip cards, roll signs, hand-hung numbers
    "broadcast",  # rendered TV/stream graphics
    "printed",  # painted, printed or vinyl text
    "unknown",
)
LABEL_SOURCES = ("human", "model-assisted-unverified", "synthetic")
SPLITS = ("train", "dev", "test")

# field_type -> the ScoreSight box preset whose defaults it is read with; None
# means a custom box (defaults.default_custom_box_info).
_BOX_NAMES = {
    "score": "Home Score",
    "clock": "Time",
    "period": "Period",
    "number": None,
    "text": None,
    "other": None,
}

# A row's role (without a numbered suffix such as "_2") -> the ScoreSight
# preset box for it. The other roles (timeouts, downs, cricket counts, names,
# ...) have no preset: they are read with their field type's box.
ROLE_BOXES = {
    "home_score": "Home Score",
    "away_score": "Away Score",
    "clock": "Time",
    "period": "Period",
    "home_fouls": "Home Fouls",
    "away_fouls": "Away Fouls",
    "shot_clock": "Shot Clock",
}

# Settings that change between frames or only format the output: an evaluation
# reads every crop once, as a fresh box, and scores what was recognized.
EVAL_SETTING_OVERRIDES = {
    "smoothing": False,
    "skip_similar_image": False,
    "ordinal_indicator": False,
    "remove_leading_zeros": False,
    "templatefield": False,
    "composite_box": False,
}


def scoresight_field_type(field_type: str) -> int:
    """The defaults.FieldType a field type is read as (NUMBER, TIME or TEXT)."""
    FieldType = import_defaults().FieldType
    if field_type == "clock":
        return FieldType.TIME
    if field_type in ("score", "period", "number"):
        return FieldType.NUMBER
    return FieldType.TEXT


def role_box(field_type: str, role: str | None) -> str | None:
    """The preset box for a crop's role (ROLE_BOXES), or None when the role has
    none or its preset reads another kind of value than the field type (a
    TIME preset for a number, a NUMBER preset for a text)."""
    name = ROLE_BOXES.get(re.sub(r"_\d+$", "", role or ""))
    if name is None:
        return None
    preset = import_defaults().default_info_for_box_name(name)
    if preset["type"] != scoresight_field_type(field_type):
        return None
    return name


def box_name(field_type: str, role: str | None = None) -> str:
    return (
        role_box(field_type, role) or _BOX_NAMES.get(field_type) or f"Eval {field_type}"
    )


def box_settings(field_type: str, role: str | None = None, **overrides) -> dict:
    """The normalized settings of the box ScoreSight would read this field type
    (and role) with: the role's preset (role_box()) or the field type's (a
    custom box for number/text/other, with type TEXT and the "Any text" format
    for text/other), plus EVAL_SETTING_OVERRIDES and overrides."""
    if field_type not in FIELD_TYPES:
        raise ValueError(f"unknown field type {field_type!r}")
    defaults = import_defaults()
    name = role_box(field_type, role) or _BOX_NAMES[field_type]
    info = dict(defaults.default_info_for_box_name(name or ""))
    settings = {}
    if field_type in ("text", "other"):
        settings["type"] = defaults.FieldType.TEXT
        settings["format_regex"] = defaults.format_prefixes[11]  # Any text
    settings = defaults.normalize_settings_dict(settings, info)
    settings.update(EVAL_SETTING_OVERRIDES)
    settings.update(overrides)
    return settings


def whitelist(field_type: str) -> str:
    defaults = import_defaults()
    return defaults.CHAR_WHITELISTS.get(
        scoresight_field_type(field_type), defaults.GENERAL_CHAR_WHITELIST
    )


def format_regex(field_type: str, role: str | None = None) -> str | None:
    return box_settings(field_type, role).get("format_regex")


def scoresight_postfilter(text: str, field_type: str, role: str | None = None) -> str:
    """What ScoreSight would publish for this reading in a box of this field
    type (and role): the text stripped, without characters outside the field
    type's whitelist (Tesseract can't output them; other engines can), or "" if
    it doesn't fully match the box's format regex (the app rejects the reading
    and keeps the box's previous value; for a single crop that is no
    reading)."""
    allowed = whitelist(field_type)
    filtered = "".join(char for char in (text or "").strip() if char in allowed)
    filtered = filtered.strip()
    pattern = format_regex(field_type, role)
    if pattern:
        try:
            if not re.fullmatch(pattern, filtered):
                return ""
        except re.error:
            pass
    return filtered


def guess_field_type(text: str) -> str:
    """A field type for a ground-truth text when nothing better is known:
    clock for MM:SS / M:SS / SS.D, number for digits only, text otherwise."""
    value = text.strip()
    if re.fullmatch(r"\d{1,2}:\d{2}|\d{1,2}\.\d", value):
        return "clock"
    if re.fullmatch(r"\d+", value):
        return "number"
    return "text"
