class FieldType:
    # Enum for the type of the field
    NUMBER = 0
    TIME = 1
    TEXT = 2


# The characters Tesseract may output for a box, by its field type (TEXT boxes
# use GENERAL_CHAR_WHITELIST). Here rather than in tesseract.py so tools such as
# the OCR evaluation harness (ocr_eval/) can apply them without importing
# Tesseract.
CHAR_WHITELISTS = {
    FieldType.NUMBER: "0123456789",
    FieldType.TIME: "0123456789:.",
}
GENERAL_CHAR_WHITELIST = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ .,;:!?-_()[]{}<>@#$%^&*+=|\\~`\"'"

# "When blank" (the box setting clear_value): what the outputs get once the box
# has been blank (or, with CLEAR_BLANK_OR_ZERO, has shown zero: 0, 00, 0:00)
# for CLEAR_AFTER_SECONDS: its last value (CLEAR_NEVER) or an empty value. In
# the order of comboBox_clearValue's items.
CLEAR_NEVER = "never"
CLEAR_BLANK = "blank"
CLEAR_BLANK_OR_ZERO = "blank_or_zero"
CLEAR_VALUES = (CLEAR_NEVER, CLEAR_BLANK, CLEAR_BLANK_OR_ZERO)
CLEAR_AFTER_SECONDS = 2.0


# 0 - Time MM:ss and ss.m
# 1 - Time MM:ss and ss:m
# 2 - Time MM:ss
# 3 - Time ss.m
# 4 - Time 0-59
# 5 - Shotclock 0-39
# 6 - Score 1dd
# 7 - Score ddd
# 8 - Period 1-4
# 9 - Period d
# 10 - Alphanumeric
# 11 - Any text
# 12 - Any number
# 13 - Custom
# The minutes of the MM:ss presets take up to three digits, for clocks that
# count up past an hour (soccer's 2nd half and extra time). Up to 0.4.2 they
# took 0-59, so a soccer clock froze at 59:59; storage.migrate_boxes updates the
# boxes that stored those.
format_prefixes = [
    "^(?:(?:\\d{1,3}:[0-5]\\d)|(?:[0-5]?\\d\\.\\d))$",  # Time MM:ss and ss.m
    # for boards that show the tenths after a colon below a minute (59:8): one
    # digit after the colon is tenths, as a minutes clock always shows two. Not
    # in the preset above: Tesseract drops a digit of a clock (12:04 -> 12:0)
    # often enough that it would let those misreads through.
    "^(?:(?:\\d{1,3}:[0-5]\\d)|(?:[0-5]?\\d[.:]\\d))$",  # Time MM:ss and ss:m
    "^\\d{1,3}:[0-5]\\d$",  # Time MM:ss
    "^[0-5]?\\d\\.\\d$",  # Time ss.m
    # one or two digits: clocks show 9, not 09 (up to 0.3.0 these took exactly
    # two; storage.migrate_boxes updates the boxes that stored those)
    "^[0-5]?\\d$",  # Time 0-59
    "^[0-3]?\\d$",  # Shotclock 0-39
    "^1?\\d{1,2}$",  # Score 1dd
    "^\\d{1,3}$",  # Score ddd
    "^[1-4]{1}$",  # Period 1-4
    "^\\d{1}$",  # Period d
    "^[A-Za-z0-9]*$",  # Alphanumeric
    "^.*$",  # Any text
    "^\\d*$",  # Any number
    "^.*$",  # Custom
]


# Default values for the scoreboard
default_boxes = [
    {
        "name": "Home Score",
        "type": FieldType.NUMBER,
        "x": 0,
        "y": 0,
        "width": 120,
        "height": 100,
        "obs_source_name": "Home score",
        "format_regex": format_prefixes[6],
        "ordinal_indicator": False,
        "is_custom": False,
    },
    {
        "name": "Away Score",
        "type": FieldType.NUMBER,
        "x": 0,
        "y": 0,
        "width": 120,
        "height": 100,
        "obs_source_name": "Away score",
        "format_regex": format_prefixes[6],
        "ordinal_indicator": False,
        "is_custom": False,
    },
    {
        "name": "Time",
        "type": FieldType.TIME,
        "x": 0,
        "y": 0,
        "width": 170,
        "height": 100,
        "obs_source_name": "Clock",
        "format_regex": format_prefixes[0],
        "ordinal_indicator": False,
        "is_custom": False,
    },
    {
        "name": "Period",
        "type": FieldType.NUMBER,
        "x": 0,
        "y": 0,
        "width": 50,
        "height": 80,
        "obs_source_name": "Period",
        "format_regex": format_prefixes[8],
        "ordinal_indicator": True,
        "is_custom": False,
    },
    {
        "name": "Home Fouls",
        "type": FieldType.NUMBER,
        "x": 0,
        "y": 0,
        "width": 80,
        "height": 80,
        "obs_source_name": "#Home Fouls",
        "format_regex": format_prefixes[12],
        "ordinal_indicator": False,
        "is_custom": False,
    },
    {
        "name": "Away Fouls",
        "type": FieldType.NUMBER,
        "x": 0,
        "y": 0,
        "width": 80,
        "height": 80,
        "obs_source_name": "#Away Fouls",
        "format_regex": format_prefixes[12],
        "ordinal_indicator": False,
        "is_custom": False,
    },
    {
        "name": "Shot Clock",
        "type": FieldType.NUMBER,
        "x": 0,
        "y": 0,
        "width": 150,
        "height": 100,
        "obs_source_name": "shotclock",
        "format_regex": format_prefixes[5],
        "ordinal_indicator": False,
        "is_custom": False,
    },
]
default_custom_box_info = {
    "type": FieldType.NUMBER,
    "x": 0,
    "y": 0,
    "width": 150,
    "height": 100,
    "obs_source_name": "",
    "format_regex": format_prefixes[12],
    "ordinal_indicator": False,
    "is_custom": True,
}


def default_info_for_box_name(name):
    # Get the info for a box name
    for box in default_boxes:
        if box["name"] == name:
            return box
    return default_custom_box_info


def normalize_settings_dict(settings, box_info):
    # Normalize the settings dict with default values if they are not present
    if not settings:
        settings = {}
    if not box_info:
        box_info = {
            "obs_source_name": "",
            "format_regex": format_prefixes[12],
            "type": FieldType.NUMBER,
            "ordinal_indicator": False,
            "is_custom": True,
        }
    return {
        "is_custom": (
            settings["is_custom"] if "is_custom" in settings else box_info["is_custom"]
        ),
        "obs_source_name": (
            settings["obs_source_name"]
            if "obs_source_name" in settings
            else box_info["obs_source_name"]
        ),
        "format_regex": (
            settings["format_regex"]
            if "format_regex" in settings
            else box_info["format_regex"]
        ),
        "type": (settings["type"] if "type" in settings else box_info["type"]),
        "smoothing": (settings["smoothing"] if "smoothing" in settings else False),
        "clear_value": (
            settings["clear_value"]
            if settings.get("clear_value") in CLEAR_VALUES
            else CLEAR_NEVER
        ),
        # minimum Tesseract confidence, as a fraction (slider % / 100); 0 = off
        "conf_thresh": (settings["conf_thresh"] if "conf_thresh" in settings else 0.0),
        "cleanup_thresh": (
            settings["cleanup_thresh"] if "cleanup_thresh" in settings else 0
        ),
        "dilate": (settings["dilate"] if "dilate" in settings else 1),
        "skew": (settings["skew"] if "skew" in settings else 0),
        "vscale": (settings["vscale"] if "vscale" in settings else 10),
        "autocrop": (settings["autocrop"] if "autocrop" in settings else False),
        "skip_similar_image": (
            settings["skip_similar_image"]
            if "skip_similar_image" in settings
            else False
        ),
        "remove_leading_zeros": (
            settings["remove_leading_zeros"]
            if "remove_leading_zeros" in settings
            else False
        ),
        "rescale_patch": (
            settings["rescale_patch"] if "rescale_patch" in settings else True
        ),
        "normalize_wh_ratio": (
            settings["normalize_wh_ratio"]
            if "normalize_wh_ratio" in settings
            else False
        ),
        "invert_patch": (
            settings["invert_patch"] if "invert_patch" in settings else False
        ),
        "dot_detector": (
            settings["dot_detector"] if "dot_detector" in settings else False
        ),
        "binarization_method": (
            settings["binarization_method"] if "binarization_method" in settings else 0
        ),
        "ordinal_indicator": (
            settings["ordinal_indicator"]
            if "ordinal_indicator" in settings
            else box_info["ordinal_indicator"]
        ),
        "templatefield": (
            settings["templatefield"] if "templatefield" in settings else False
        ),
        "templatefield_text": (
            settings["templatefield_text"] if "templatefield_text" in settings else ""
        ),
        "composite_box": (
            settings["composite_box"] if "composite_box" in settings else False
        ),
    }
