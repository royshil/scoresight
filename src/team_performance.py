"""Team Performance's timing payloads (no independent or interpolated clock)."""

import re
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class TimingConfig:
    enabled: bool = False
    scoreboard_field: str = "Time"
    shot_clock_field: str = "Shot Clock"


def scoreboard_time(raw: str) -> dict[str, int]:
    """Read mm:ss[.d], sub-minute ss[.d], or ScoreSight's ss:d format.

    Team Performance takes integer seconds; tenths are discarded, not rounded.
    """
    raw = raw.strip().replace(",", ".")
    match = re.fullmatch(r"([0-9]{1,3}):([0-5][0-9](?:\.[0-9]+)?)", raw)
    if match:
        return {"minute": int(match[1]), "second": int(Decimal(match[2]))}
    if re.fullmatch(r"[0-9]{1,2}:[0-9]", raw):
        raw = raw.replace(":", ".")
    if not re.fullmatch(r"[0-9]{1,2}(?:\.[0-9]+)?", raw):
        raise ValueError("Expected mm:ss or sub-minute seconds")
    seconds = Decimal(raw)
    if seconds >= 60:
        raise ValueError("Sub-minute seconds must be below 60")
    return {"minute": 0, "second": int(seconds)}


def shot_clock_time(raw: str) -> dict[str, int | float]:
    """Keep fractional shot-clock seconds; accept the bridge's 0–99 range."""
    raw = raw.strip().replace(",", ".")
    if re.fullmatch(r"[0-9]{1,2}:[0-9]", raw):
        raw = raw.replace(":", ".")
    if not re.fullmatch(r"[0-9]{1,2}(?:\.[0-9]+)?", raw):
        raise ValueError("Expected shot-clock seconds")
    seconds = Decimal(raw)
    if seconds > 99:
        raise ValueError("Shot clock must be between 0 and 99")
    return {"time": int(seconds) if seconds == int(seconds) else float(seconds)}
