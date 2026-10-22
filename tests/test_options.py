import json
from pathlib import Path

import pytest

from torrentlinker.options import (
    OPTIONS_MAX_AGE,
    OptionType,
    OptionValue,
    category_options,
    fresh_options,
    options_body,
    parse_options,
)
from torrentlinker.store import Store

FIXTURES = Path(__file__).parent / "fixtures"  # recorded from c411, never fetched by tests


def recorded(sub: int) -> dict[str, object]:
    return json.loads((FIXTURES / f"c411_options_{sub}.json").read_text(encoding="utf-8"))


def test_a_film_has_a_required_multiple_language_and_optional_genre_and_type() -> None:
    langue, genre, kind = parse_options(recorded(6))

    assert (langue.id, langue.name, langue.multiple, langue.required) == (1, "Langue", True, True)
    assert OptionValue(2, "Français (VFF/TrueFrench)") in langue.values
    assert (genre.id, genre.multiple, genre.required) == (5, True, False)
    assert (kind.id, kind.multiple, kind.required) == (4, False, False)
    assert [v.label for v in kind.values] == ["2D", "3D FSBS", "3D", "3D HSBS"]


def test_options_come_in_c411s_order_and_3d_has_none() -> None:
    assert [t.id for t in parse_options(recorded(18))] == [15, 16, 17, 18]
    assert [t.required for t in parse_options(recorded(18))] == [True, True, True, False]
    assert parse_options(recorded(51)) == []


def test_the_draft_gets_a_value_per_single_choice_and_a_list_per_multiple_choice() -> None:
    types = parse_options(recorded(6))

    body = options_body(types, {1: [2], 5: [39, 44], 4: [35]})

    assert body == {"1": [2], "5": [39, 44], "4": 35}


def test_an_option_left_empty_or_unknown_is_not_sent() -> None:
    types = parse_options(recorded(6))

    assert options_body(types, {1: [2], 5: [], 99: [1]}) == {"1": [2]}
    assert options_body([], {1: [2]}) == {}


def test_a_single_choice_keeps_only_its_first_value() -> None:
    kind = OptionType(4, "Type", False, False, (OptionValue(35, "2D"), OptionValue(38, "3D")))

    assert options_body([kind], {4: [38, 35]}) == {"4": 38}


def test_options_are_fetched_once_then_kept_for_a_week(tmp_path: Path) -> None:
    store, calls = Store(tmp_path / "s.db"), []

    def fetch(sub: int) -> dict[str, object]:
        calls.append(sub)
        return recorded(6)

    first = category_options(store, fetch, 6, now=lambda: 1000.0)
    again = category_options(store, fetch, 6, now=lambda: 1000.0 + OPTIONS_MAX_AGE - 1)
    assert calls == [6] and again == first and len(first) == 3

    category_options(store, fetch, 6, now=lambda: 1000.0 + OPTIONS_MAX_AGE + 1)
    assert calls == [6, 6]


def test_options_are_fetched_again_on_demand(tmp_path: Path) -> None:
    store, calls = Store(tmp_path / "s.db"), []

    def fetch(sub: int) -> dict[str, object]:
        calls.append(sub)
        return recorded(6)

    category_options(store, fetch, 6, now=lambda: 1.0)
    category_options(store, fetch, 6, refresh=True, now=lambda: 2.0)

    assert calls == [6, 6]


def test_each_subcategory_has_its_own_options(tmp_path: Path) -> None:
    store = Store(tmp_path / "s.db")

    category_options(store, lambda sub: recorded(sub), 18, now=lambda: 1.0)

    assert fresh_options(store, 18, now=lambda: 2.0) is not None
    assert fresh_options(store, 6, now=lambda: 2.0) is None


def test_options_survive_the_store_being_reopened(tmp_path: Path) -> None:
    category_options(Store(tmp_path / "s.db"), lambda sub: recorded(sub), 14, now=lambda: 1.0)

    kept = fresh_options(Store(tmp_path / "s.db"), 14, now=lambda: 2.0)

    assert [t.id for t in kept or []] == [12, 13, 14, 29]


def test_a_failed_fetch_keeps_nothing(tmp_path: Path) -> None:
    store = Store(tmp_path / "s.db")

    def fetch(sub: int) -> dict[str, object]:
        raise OSError("offline")

    with pytest.raises(OSError):
        category_options(store, fetch, 6, now=lambda: 1.0)
    assert fresh_options(store, 6, now=lambda: 1.0) is None
