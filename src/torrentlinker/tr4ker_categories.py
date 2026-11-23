"""tr4ker's category tree, for choosing a feed category (ADR-0025, issue 180).

The feed's `cat=` takes a slug, so the tree is tr4ker's own (`/api/public/categories`), kept
apart from Torznab categories. It is read in the paired tr4ker tab when that answers, and
otherwise the snapshot shipped with the app stands in. Either way the editor gets the same
flat records: `{id, slug, name, parent, order}`.
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import Callable
from importlib import resources
from typing import Any, Protocol

CATEGORIES_PATH = "/api/public/categories"
FRESH = 86400.0  # a day: the tree changes when tr4ker adds a category
SLUG = re.compile(r"[a-z0-9][a-z0-9-]{0,59}")


class Reader(Protocol):
    @property
    def can_read(self) -> bool: ...

    def read_json(self, path: str, timeout: float = 60.0) -> dict[str, Any]: ...


def parse(body: Any) -> list[dict[str, Any]]:
    """Flat category records from tr4ker's answer; anything malformed is left out."""
    if isinstance(body, dict):
        body = next((v for v in body.values() if isinstance(v, list)), [])
    rows: list[dict[str, Any]] = []
    for item in body if isinstance(body, list) else []:
        if not isinstance(item, dict):
            continue
        slug, name, ident = item.get("slug"), item.get("name"), item.get("id")
        if not (isinstance(slug, str) and SLUG.fullmatch(slug) and isinstance(name, str) and name):
            continue
        if not isinstance(ident, int) or isinstance(ident, bool):
            continue
        parent = item.get("parent_id", item.get("parent"))
        order = item.get("sort_order", item.get("order", 0))
        rows.append(
            {
                "id": ident,
                "slug": slug,
                "name": name[:80],
                "parent": parent
                if isinstance(parent, int) and not isinstance(parent, bool)
                else None,
                "order": order if isinstance(order, int) and not isinstance(order, bool) else 0,
            }
        )
    return rows


def snapshot() -> list[dict[str, Any]]:
    text = (resources.files("torrentlinker") / "assets" / "tr4ker-categories.json").read_text(
        encoding="utf-8"
    )
    return parse(json.loads(text))


class Tr4kerCategories:
    """The tree, read at most once a day, and never a reason for the editor to fail."""

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self.clock = clock
        self.lock = threading.Lock()
        self.rows: list[dict[str, Any]] = []
        self.read_at = 0.0

    def get(self, session: Reader | None) -> list[dict[str, Any]]:
        with self.lock:
            if self.rows and self.clock() - self.read_at < FRESH:
                return self.rows
            if session is not None and session.can_read:
                try:
                    found = parse(session.read_json(CATEGORIES_PATH, timeout=8.0))
                except Exception:  # noqa: BLE001 - the snapshot answers instead
                    found = []
                if found:
                    self.rows, self.read_at = found, self.clock()
                    return found
            return self.rows or snapshot()
