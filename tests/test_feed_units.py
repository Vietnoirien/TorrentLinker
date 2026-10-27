from datetime import datetime

import pytest

from torrentlinker import feed_units as u
from torrentlinker.feeds import Preferences, Subscription


@pytest.mark.parametrize(
    "size,expected",
    [
        (700 * u.MIB, (700.0, "MiB")),
        (10 * u.GIB, (10.0, "GiB")),
        (int(1.5 * u.GIB), (1.5, "GiB")),
        (u.GIB + u.MIB, (1025.0, "MiB")),
        (0, (0.0, "MiB")),
    ],
)
def test_size_units_round_trip(size, expected):
    value, unit = u.bytes_to_size(size)
    assert (value, unit) == expected
    assert u.size_to_bytes(value, unit) == size


def test_format_size_is_human():
    assert u.format_size(0) == "—"
    assert u.format_size(700 * u.MIB) == "700 MiB"
    assert u.format_size(3 * u.GIB) == "3.0 GiB"
    assert u.format_size(2048) == "2 KiB"


@pytest.mark.parametrize("offset", [-300, 0, 60, 120, 540])
def test_hours_round_trip_for_whole_hour_offsets(offset):
    utc = [0, 1, 2, 22, 23]
    assert u.local_to_utc_hours(u.utc_to_local_hours(utc, offset), offset) == utc


def test_local_hours_follow_the_offset():
    assert u.utc_to_local_hours([22, 23], 120) == [0, 1]
    assert u.local_to_utc_hours([1, 2], 120) == [0, 23]


def test_hour_ranges_wrap_midnight():
    assert u.hour_ranges([]) == []
    assert u.hour_ranges(list(range(24))) == [(0, 24)]
    assert u.hour_ranges([1, 2, 3, 9]) == [(1, 4), (9, 10)]
    assert u.hour_ranges([22, 23, 0, 1]) == [(22, 2)]


def test_hours_presets():
    assert u.hours_preset(list(range(24))) == "any"
    assert u.hours_preset(list(u.NIGHT_HOURS)) == "night"
    assert u.hours_preset([3]) == "custom"


def test_chip_cycle_and_state():
    prefs = Preferences()
    for state in ("prefer", "must", "avoid", "none"):
        assert u.NEXT_CHIP[u.chip_state(prefs, "quality", "1080p")] == state
        prefs = u.set_chip(prefs, "quality", "1080p", state)
        assert u.chip_state(prefs, "quality", "1080p") == state
    assert prefs.required == prefs.preferred == prefs.excluded == {}


def test_must_keeps_ranking_and_other_values():
    prefs = Preferences(
        required={"quality": ["1080p", "720p"]},
        preferred={"quality": ["1080p", "720p"], "codec": ["HEVC"]},
        excluded={"quality": ["CAM"]},
    )
    changed = u.set_chip(prefs, "quality", "720p", "avoid")
    assert changed.required == {"quality": ["1080p"]}
    assert changed.preferred == {"quality": ["1080p"], "codec": ["HEVC"]}
    assert changed.excluded == {"quality": ["CAM", "720p"]}
    assert prefs.required == {"quality": ["1080p", "720p"]}  # the input is not mutated
    assert u.chip_values(prefs, "quality") == ["1080p", "720p", "CAM"]


def test_preferred_chip_is_ranked_by_the_validator():
    prefs = u.set_chip(Preferences(), "format", "EPUB", "prefer")
    assert "format" in prefs.priorities


def test_chip_round_trip_keeps_subscription_valid():
    feed = Subscription(name="x", preferences=Preferences(preferred={"audio": ["fr"]}))
    prefs = u.set_chip(feed.preferences, "audio", "fr", "must")
    assert Subscription(**{**feed.model_dump(), "preferences": prefs.model_dump()})


def test_when_and_age():
    now = datetime(2026, 10, 27, 12, 0)
    assert u.when(datetime(2026, 10, 27, 8, 0).timestamp(), now)[0] == "today"
    assert u.when(datetime(2026, 10, 26, 23, 0).timestamp(), now)[0] == "yesterday"
    assert u.when(datetime(2026, 10, 1, 8, 0).timestamp(), now)[0] == "date"
    assert u.age(10) == (1, "minute")
    assert u.age(720) == (12, "minute")
    assert u.age(7200) == (2, "hour")
    assert u.age(3 * 86400) == (3, "day")
