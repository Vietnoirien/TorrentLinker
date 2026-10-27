"""Human units for RSS subscriptions, shared by the desktop and web editors.

The stored model keeps bytes and UTC hours. These helpers convert at the edge and
return plain values, never translated text: each front end words them itself.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from torrentlinker.feeds import MetadataField, Preferences

MIB = 1024**2
GIB = 1024**3
SizeUnit = Literal["MiB", "GiB"]
ChipState = Literal["none", "prefer", "must", "avoid"]

# Fields the editor shows as chips; the others stay under "More criteria".
COMMON_FIELDS: tuple[MetadataField, ...] = ("quality", "codec", "audio", "subtitles")
INTERVALS = (15, 30, 60, 120, 360, 720, 1440)
NIGHT_HOURS = (1, 2, 3, 4, 5, 6)


def size_to_bytes(value: float, unit: SizeUnit) -> int:
    return round(value * (GIB if unit == "GiB" else MIB))


def bytes_to_size(size: int) -> tuple[float, SizeUnit]:
    """GiB when the size is a whole number of tenths of a GiB, else MiB."""
    tenths = round(size / GIB * 10)
    if size >= GIB and round(tenths * GIB / 10) == size:
        return tenths / 10, "GiB"
    return round(size / MIB, 1), "MiB"


def format_size(size: int) -> str:
    """Compact size text; unknown or zero sizes show a dash."""
    if size <= 0:
        return "—"
    if size >= GIB:
        return f"{size / GIB:.1f} GiB"
    if size >= MIB:
        return f"{size / MIB:.0f} MiB"
    return f"{size / 1024:.0f} KiB"


def local_offset_minutes(now: datetime | None = None) -> int:
    """The machine's UTC offset in minutes, for the given moment (daylight saving aware)."""
    offset = (now or datetime.now()).astimezone().utcoffset()
    return round(offset.total_seconds() / 60) if offset else 0


def utc_to_local_hours(hours: list[int], offset_minutes: int) -> list[int]:
    """Whole local hours. A half-hour offset rounds each hour down."""
    return sorted({((h * 60 + offset_minutes) // 60) % 24 for h in hours})


def local_to_utc_hours(hours: list[int], offset_minutes: int) -> list[int]:
    return sorted({((h * 60 - offset_minutes) // 60) % 24 for h in hours})


def hour_ranges(hours: list[int]) -> list[tuple[int, int]]:
    """Runs of consecutive hours as (start, end), end exclusive; over midnight, end < start."""
    values = sorted(set(hours))
    if not values:
        return []
    if len(values) == 24:
        return [(0, 24)]
    runs: list[list[int]] = []
    for hour in values:
        if runs and runs[-1][1] == hour:
            runs[-1][1] = hour + 1
        else:
            runs.append([hour, hour + 1])
    if len(runs) > 1 and runs[0][0] == 0 and runs[-1][1] == 24:
        start = runs.pop()[0]
        runs[0] = [start, runs[0][1]]
    return [(a, b) for a, b in runs]


def hours_preset(local_hours: list[int]) -> Literal["any", "night", "custom"]:
    values = tuple(sorted(set(local_hours)))
    if len(values) == 24:
        return "any"
    if values == NIGHT_HOURS:
        return "night"
    return "custom"


def chip_state(prefs: Preferences, field: MetadataField, value: str) -> ChipState:
    if value in prefs.excluded.get(field, []):
        return "avoid"
    if value in prefs.required.get(field, []):
        return "must"
    if value in prefs.preferred.get(field, []):
        return "prefer"
    return "none"


def chip_values(prefs: Preferences, field: MetadataField) -> list[str]:
    """Every value of a field, preferred ones first in their ranking order."""
    seen: list[str] = []
    for group in (prefs.preferred, prefs.required, prefs.excluded):
        for value in group.get(field, []):
            if value not in seen:
                seen.append(value)
    return seen


NEXT_CHIP: dict[ChipState, ChipState] = {
    "none": "prefer",
    "prefer": "must",
    "must": "avoid",
    "avoid": "none",
}


def set_chip(prefs: Preferences, field: MetadataField, value: str, state: ChipState) -> Preferences:
    """A new Preferences with one value moved to the state. Other values are untouched.

    "must" keeps the value in its ranking, so a required value can still be preferred.
    """
    groups = {
        name: {k: list(v) for k, v in getattr(prefs, name).items()}
        for name in ("required", "preferred", "excluded")
    }

    def drop(*names: str) -> None:
        for name in names:
            values = groups[name].get(field, [])
            if value in values:
                values.remove(value)
            if not values:
                groups[name].pop(field, None)

    def add(name: str) -> None:
        values = groups[name].setdefault(field, [])
        if value not in values:
            values.append(value)

    if state == "none":
        drop("required", "preferred", "excluded")
    elif state == "prefer":
        drop("required", "excluded")
        add("preferred")
    elif state == "must":
        drop("excluded")
        add("required")
    else:
        drop("required", "preferred")
        add("excluded")
    return Preferences.model_validate({**prefs.model_dump(), **groups})


def when(timestamp: float, now: datetime | None = None) -> tuple[str, datetime]:
    """("today" | "yesterday" | "date", local datetime) for a Unix timestamp."""
    moment = datetime.fromtimestamp(timestamp)
    today = (now or datetime.now()).date()
    days = (today - moment.date()).days
    return ("today" if days == 0 else "yesterday" if days == 1 else "date"), moment


def age(seconds: float) -> tuple[int, Literal["minute", "hour", "day"]]:
    """Elapsed time as a rounded count and a unit; under a minute counts as one minute."""
    seconds = max(0.0, seconds)
    if seconds < 3600:
        return max(1, round(seconds / 60)), "minute"
    if seconds < 86400:
        return round(seconds / 3600), "hour"
    return round(seconds / 86400), "day"
