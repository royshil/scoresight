"""Synthetic scoreboard images for OCR tests (grayscale uint8 numpy arrays).

Not a test module; import it from tests (pytest puts tests/ on sys.path).
"""

from pathlib import Path

import cv2
import numpy as np

# segments lit per digit: a=top, b=top right, c=bottom right, d=bottom,
# e=bottom left, f=top left, g=middle
_SEGMENTS = {
    "0": "abcdef",
    "1": "bc",
    "2": "abged",
    "3": "abgcd",
    "4": "fgbc",
    "5": "afgcd",
    "6": "afgedc",
    "7": "abc",
    "8": "abcdefg",
    "9": "abcdfg",
}


def seven_segment(
    text: str, height: int = 80, fg: int = 255, bg: int = 0, pad: int = 20
):
    """Render digits, ':' and '.' as a 7-segment LED/LCD display."""
    width = height // 2
    thickness = max(4, height // 9)
    gap = width // 2
    image = np.full(
        (height + 2 * pad, 2 * pad + len(text) * (width + gap)), bg, np.uint8
    )
    x0 = pad
    for char in text:
        if char == ":":
            for y in (pad + height // 3, pad + 2 * height // 3):
                cv2.rectangle(
                    image,
                    (x0, y - thickness // 2),
                    (x0 + thickness, y + thickness // 2),
                    fg,
                    -1,
                )
            x0 += thickness + gap
            continue
        if char == ".":
            cv2.rectangle(
                image,
                (x0, pad + height - thickness),
                (x0 + thickness, pad + height),
                fg,
                -1,
            )
            x0 += thickness + gap
            continue
        y0, mid, t = pad, height // 2, thickness
        corners = {
            "a": ((x0 + t, y0), (x0 + width - t, y0 + t)),
            "d": ((x0 + t, y0 + height - t), (x0 + width - t, y0 + height)),
            "g": ((x0 + t, y0 + mid - t // 2), (x0 + width - t, y0 + mid + t // 2)),
            "f": ((x0, y0 + t), (x0 + t, y0 + mid - t // 2)),
            "b": ((x0 + width - t, y0 + t), (x0 + width, y0 + mid - t // 2)),
            "e": ((x0, y0 + mid + t // 2), (x0 + t, y0 + height - t)),
            "c": ((x0 + width - t, y0 + mid + t // 2), (x0 + width, y0 + height - t)),
        }
        for segment in _SEGMENTS[char]:
            cv2.rectangle(image, *corners[segment], fg, -1)
        x0 += width + gap
    return image


# OpenCV 5 draws its "Hershey" fonts with a bold outline font, so the thin
# Hershey strokes the tests read are committed as images rendered by OpenCV 4.14
# (python tests/synthetic_images.py writes them, under OpenCV 4)
HERSHEY_DIR = Path(__file__).resolve().parent / "hershey"
HERSHEY_TEXTS = [
    *["0", "3", "7", "12", "45", "88", "105", "199"],
    *["12:34", "0:59", "9.5", "45.1"],
    *["HOME", "GUEST", "SCORESIGHT HOME"],
]


def _hershey_path(text: str) -> Path:
    name = text.replace(":", "colon").replace(".", "dot").replace(" ", "_")
    return HERSHEY_DIR / f"{name}.png"


def render_hershey(text: str):
    """Render text with OpenCV's FONT_HERSHEY_SIMPLEX (scale 3, thickness 6, 20 px
    of padding), white on black."""
    font, scale, thickness, pad = cv2.FONT_HERSHEY_SIMPLEX, 3, 6, 20
    (text_width, text_height), baseline = cv2.getTextSize(text, font, scale, thickness)
    image = np.zeros((text_height + baseline + 2 * pad, text_width + 2 * pad), np.uint8)
    cv2.putText(
        image, text, (pad, pad + text_height), font, scale, 255, thickness, cv2.LINE_AA
    )
    return image


def hershey(text: str):
    """text in OpenCV 4's Hershey font, white on black (one of HERSHEY_TEXTS)."""
    image = cv2.imread(str(_hershey_path(text)), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise FileNotFoundError(
            f"no image of {text!r}: add it to HERSHEY_TEXTS and run "
            "python tests/synthetic_images.py under OpenCV 4"
        )
    return image


def binarize(gray):
    """The capture thread's global Otsu binarization."""
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return binary


if __name__ == "__main__":
    if not cv2.__version__.startswith("4."):
        raise SystemExit(f"OpenCV {cv2.__version__}: render the images with OpenCV 4")
    HERSHEY_DIR.mkdir(exist_ok=True)
    for text in HERSHEY_TEXTS:
        cv2.imwrite(str(_hershey_path(text)), render_hershey(text))
    print(f"wrote {len(HERSHEY_TEXTS)} images to {HERSHEY_DIR}")
