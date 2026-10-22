"""Category Options: the choices c411 asks for beyond the category (language, genre, format…).

`GET /api/categories/{subId}/options` lists them per subcategory; a Draft's `options`
carries the chosen values keyed by option type id (docs/research/upload-rules.md).
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from torrentlinker.store import Store

OPTIONS_MAX_AGE = 7 * 24 * 3600  # c411's options change rarely: refreshed weekly

# What the user (or a profile) chose: the value ids, by option type id.
Chosen = dict[int, list[int]]


@dataclass(frozen=True)
class OptionValue:
    id: int
    label: str  # as c411 spells it, in French


@dataclass(frozen=True)
class OptionType:
    id: int
    name: str
    multiple: bool  # several values may be chosen
    required: bool
    values: tuple[OptionValue, ...]


def parse_options(payload: dict[str, Any]) -> list[OptionType]:
    """The option types of a response, in c411's display order."""
    raw = sorted(payload.get("data") or [], key=lambda o: o.get("sortOrder", 0))
    return [
        OptionType(
            o["id"],
            o["name"],
            bool(o.get("allowsMultiple")),
            bool(o.get("isRequired")),
            tuple(
                OptionValue(v["id"], v["value"])
                for v in sorted(o.get("values") or [], key=lambda v: v.get("sortOrder", 0))
            ),
        )
        for o in raw
    ]


def options_body(types: list[OptionType], chosen: Chosen) -> dict[str, Any]:
    """The Draft's `options`: a list of value ids for a multiple choice, the id for a
    single one. Empty and unknown option types are left out."""
    body: dict[str, Any] = {}
    for t in types:
        values = chosen.get(t.id) or []
        if values:
            body[str(t.id)] = list(values) if t.multiple else values[0]
    return body


def fresh_options(
    store: Store, subcategory: int, now: Callable[[], float] = time.time
) -> list[OptionType] | None:
    """The kept options of a subcategory, unless older than a week or never fetched."""
    kept = store.cached_options(subcategory)
    if kept is None or now() - kept[1] > OPTIONS_MAX_AGE:
        return None
    return parse_options(json.loads(kept[0]))


def category_options(
    store: Store,
    fetch: Callable[[int], dict[str, Any]],
    subcategory: int,
    *,
    refresh: bool = False,
    now: Callable[[], float] = time.time,
) -> list[OptionType]:
    """A subcategory's options from the store, fetched from c411 (and kept) when missing,
    older than a week, or `refresh` is asked."""
    if not refresh and (kept := fresh_options(store, subcategory, now)) is not None:
        return kept
    payload = fetch(subcategory)
    types = parse_options(payload)  # a malformed answer is never kept
    store.cache_options(subcategory, json.dumps(payload), now())
    return types
