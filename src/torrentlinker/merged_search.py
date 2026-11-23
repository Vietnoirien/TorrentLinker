"""Merged Search (ADR-0025): c411 and tr4ker rows side by side, each badged with its Tracker.

The same release on both Trackers stays two rows: their info hashes differ (c411 adds `C411`,
tr4ker `tr4ker` to `info.source`). Sorting and filtering happen here, on the rows both
Trackers returned, because tr4ker cannot sort by seeders, size, title or leechers itself.
"""

from __future__ import annotations

from typing import Any

from torrentlinker.indexer import Candidate
from torrentlinker.trackers import TR4KER, tracker


def tr4ker_row(key: str, candidate: Candidate, seen_at: float) -> dict[str, Any]:
    """A Search row for a tr4ker Candidate, shaped like c411's, with its Tracker badge."""
    meta = candidate.metadata
    origin = tracker(TR4KER).origin
    return {
        "hash": key,
        "title": candidate.title,
        "size": candidate.size,
        "seeders": candidate.seeders,
        "published_at": candidate.published_at,
        "native_category_label": meta.get("category") or None,
        "revival": None,
        "website": candidate.details_url if candidate.details_url.startswith(origin) else "",
        "zen": None,  # c411's schedule does not apply (ADR-0027)
        "note": None,
        "categories": candidate.categories,
        "category": None,
        "source": "indexer",
        "seen_at": seen_at,
        "tracker": TR4KER,
        "leechers": meta.get("leechers"),
        "completions": meta.get("completions"),
        "freeleech": meta.get("freeleech") is True,
        "slug": meta.get("slug"),
    }


def sort_merged(rows: list[dict[str, Any]], by: str) -> list[dict[str, Any]]:
    """Both Trackers' rows in one order. `recent` and unknown sorts use the publication time.
    Every sort is stable, so a tie keeps c411 first (the default Tracker order)."""
    keys = {
        "seeders": lambda r: r.get("seeders") or 0,
        "size": lambda r: r.get("size") or 0,
        "leechers": lambda r: r.get("leechers") or 0,
        "completed": lambda r: r.get("completions") or 0,
        "title": lambda r: str(r.get("title") or "").casefold(),
    }
    key = keys.get(by, lambda r: r.get("published_at") or 0.0)
    return sorted(rows, key=key, reverse=by != "title")


def filter_tracker(rows: list[dict[str, Any]], trackers: list[str]) -> list[dict[str, Any]]:
    return [r for r in rows if r.get("tracker", "c411") in trackers]
