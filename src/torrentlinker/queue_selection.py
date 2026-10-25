"""Immutable queue snapshots, with deterministic order and exact metadata totals."""

from __future__ import annotations

import hashlib
import json
import time
from collections import defaultdict
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from torrentlinker.category_tags import category_path
from torrentlinker.download_queue import entries


class QueueCriteria(BaseModel):
    model_config = ConfigDict(extra="forbid")
    categories: list[int] = Field(default_factory=list, max_length=100)
    include_descendants: bool = True
    query: str = Field(default="", max_length=500)
    exclude_terms: list[str] = Field(default_factory=list, max_length=100)
    min_size_bytes: int = Field(default=0, ge=0)
    max_size_bytes: int | None = Field(default=None, ge=0)
    min_seeders: int | None = Field(default=None, ge=0)
    max_seeders: int | None = Field(default=None, ge=0)
    descending: bool = False
    count: int = Field(default=100, ge=1, le=1000)
    offset: int = Field(default=0, ge=0, le=1_000_000)
    statuses: list[Literal["queued", "sending", "sent", "refused", "failed", "uncertain"]] = Field(
        default=["queued"], max_length=6
    )
    added_after: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    added_before: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    sort_by: Literal["size", "seeders", "title", "added_at", "priority"] = "added_at"


def fingerprint(rows: list[dict]) -> str:
    return hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()


def size_totals(rows: list[dict]) -> dict:
    known = sum(row["size"] for row in rows if row["size"] > 0)
    unknown = sum(row["size"] <= 0 for row in rows)
    return {
        "total_size_bytes": None if unknown else known,
        **({"known_size_bytes": known, "unknown_size_count": unknown} if unknown else {}),
    }


def statistics(rows: list[dict]) -> dict:
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        groups[str(row.get("category"))].append(row)
    return {
        "count": len(rows),
        **size_totals(rows),
        "by_category": {
            category: {"count": len(group), **size_totals(group)}
            for category, group in groups.items()
        },
    }


def snapshot(
    rows: list[dict], source: str, criteria: dict, eligible_count: int | None = None
) -> dict:
    totals = size_totals(rows)
    total = totals["total_size_bytes"]
    return {
        "source": source,
        "criteria": criteria,
        "snapshot_at": time.time(),
        "selection_fingerprint": fingerprint(rows),
        "rows": rows,
        "selected_count": len(rows),
        "eligible_count": len(rows) if eligible_count is None else eligible_count,
        **totals,
        "total_size_display": "Unknown total size"
        if total is None
        else f"{total / 1024**3:.2f} GiB / {total / 10**9:.2f} GB",
        "statistics": statistics(rows),
        "coverage": "Exact for the saved metadata; not a reservation.",
    }


def queue_rows(setup) -> list[dict[str, Any]]:
    return [
        {
            "key": e.key,
            "hash": e.candidate.infohash,
            "title": e.candidate.title,
            "size": e.candidate.size,
            "seeders": e.candidate.seeders,
            "category": max(
                e.candidate.categories,
                key=lambda c: len(category_path(c, setup.settings.indexer_categories)),
                default=None,
            ),
            "categories": list(e.candidate.categories),
            "folder": str(e.folder),
            "indexer_url": e.indexer_url,
            "status": e.status,
            "priority": e.priority,
            "added_at": e.added_at,
            "retry_safe": e.retry_safe,
        }
        for e in entries(setup.store)
    ]


def select_queue(setup, criteria: QueueCriteria) -> dict:
    eligible = []
    for row in queue_rows(setup):
        title = row["title"].casefold()
        category_ids = (
            set(category_path(row["category"], setup.settings.indexer_categories))
            if criteria.include_descendants
            else {row["category"]}
        )
        if (
            row["status"] not in criteria.statuses
            or (criteria.categories and not category_ids.intersection(criteria.categories))
            or criteria.query.strip().casefold() not in title
            or any(t.strip().casefold() in title for t in criteria.exclude_terms if t.strip())
            or row["size"] < criteria.min_size_bytes
            or (criteria.max_size_bytes is not None and row["size"] > criteria.max_size_bytes)
            or (criteria.min_seeders is not None and row["seeders"] < criteria.min_seeders)
            or (criteria.max_seeders is not None and row["seeders"] > criteria.max_seeders)
            or (criteria.added_after is not None and row["added_at"] < criteria.added_after)
            or (criteria.added_before is not None and row["added_at"] > criteria.added_before)
        ):
            continue
        eligible.append(row)
    eligible.sort(key=lambda r: (r["added_at"], r["key"]))
    eligible.sort(
        key=lambda r: r["title"].casefold() if criteria.sort_by == "title" else r[criteria.sort_by],
        reverse=criteria.descending,
    )
    rows = eligible[criteria.offset : criteria.offset + criteria.count]
    result = snapshot(rows, "queue", criteria.model_dump(), len(eligible))
    result["shortfall"] = max(0, criteria.count - len(rows))
    return result


def validate_snapshot(setup, rows: list[dict], expected: str) -> None:
    keys = {row["key"] for row in rows}
    current = {row["key"]: row for row in queue_rows(setup) if row["key"] in keys}
    if len(current) != len(rows) or fingerprint([current[r["key"]] for r in rows]) != expected:
        raise ValueError("Queue selection changed. Select and review it again.")


def validate_catalogue_subset(setup, rows: list[dict]) -> None:
    current = {r.infohash: r for r in setup.store.catalogue([row["hash"] for row in rows])}
    for row in rows:
        item = current.get(row["hash"])
        if item is None or any(
            getattr(item, key) != row[key]
            for key in ("title", "size", "seeders", "category", "source")
        ):
            raise ValueError("Catalogue subset changed. Select and review it again.")
