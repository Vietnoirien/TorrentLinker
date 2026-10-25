"""Exact, deterministic queries over cached Catalogue metadata, independent of Plans."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Iterable, Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from torrentlinker.category_tags import category_path
from torrentlinker.downloads import IndexerCategory
from torrentlinker.store import CatalogueRow


class CatalogueCriteria(BaseModel):
    model_config = ConfigDict(extra="forbid")
    categories: list[int] = Field(default_factory=list, max_length=100)
    include_descendants: bool = True
    exclude_queued: bool = False
    exclude_seeded: bool = False
    exclude_hashes: list[str] = Field(default_factory=list, max_length=1000)
    query: str = Field(default="", max_length=500)
    exclude_terms: list[str] = Field(default_factory=list, max_length=100)
    min_size_bytes: int = Field(default=0, ge=0)
    max_size_bytes: int | None = Field(default=None, ge=0)
    min_seeders: int | None = Field(default=None, ge=0)
    max_seeders: int | None = Field(default=None, ge=0)
    sort_by: Literal["size", "seeders", "title", "seen_at"] = "size"
    descending: bool = False
    count: int = Field(default=100, ge=1, le=1000)
    offset: int = Field(default=0, ge=0, le=1_000_000)

    @model_validator(mode="after")
    def valid_ranges(self):
        if self.max_size_bytes is not None and self.min_size_bytes > self.max_size_bytes:
            raise ValueError("Minimum size must not exceed maximum size.")
        if self.min_seeders is not None and self.max_seeders is not None:
            if self.min_seeders > self.max_seeders:
                raise ValueError("Minimum seeders must not exceed maximum seeders.")
        return self


def select_catalogue_rows(
    rows: Iterable[CatalogueRow],
    categories: Mapping[int, IndexerCategory],
    criteria: CatalogueCriteria,
) -> dict[str, Any]:
    wanted = set(criteria.categories)
    query = criteria.query.strip().casefold()
    excluded_terms = [term.strip().casefold() for term in criteria.exclude_terms if term.strip()]
    paths: dict[int | None, set[int | None]] = {}
    eligible = []
    seen = set()
    for row in rows:
        if row.infohash in seen:
            continue
        seen.add(row.infohash)
        if row.category not in paths:
            paths[row.category] = (
                set(category_path(row.category, categories))
                if criteria.include_descendants
                else {row.category}
            )
        title = row.title.casefold()
        if (
            row.infohash in criteria.exclude_hashes
            or (wanted and not wanted.intersection(paths[row.category]))
            or (query and query not in title)
            or any(term in title for term in excluded_terms)
            or row.size <= 0
            or row.size < criteria.min_size_bytes
            or (criteria.max_size_bytes is not None and row.size > criteria.max_size_bytes)
            or (criteria.min_seeders is not None and row.seeders < criteria.min_seeders)
            or (
                criteria.max_seeders is not None
                and (row.seeders < 0 or row.seeders > criteria.max_seeders)
            )
            or (criteria.sort_by == "seeders" and row.seeders < 0)
        ):
            continue
        eligible.append(row)
    # Hash order stays ascending even when reversing the requested sort field.
    eligible.sort(key=lambda row: row.infohash)
    eligible.sort(
        key=lambda row: (
            row.title.casefold() if criteria.sort_by == "title" else getattr(row, criteria.sort_by)
        ),
        reverse=criteria.descending,
    )
    chosen = eligible[criteria.offset : criteria.offset + criteria.count]
    result_rows = [
        {
            "hash": row.infohash,
            "title": row.title,
            "size": row.size,
            "seeders": row.seeders,
            "category": row.category,
            "source": row.source,
            "seen_at": row.seen_at,
        }
        for row in chosen
    ]
    # Seen timestamps can change without altering the selected data or its order.
    fingerprint = hashlib.sha256(
        json.dumps(
            [{k: v for k, v in row.items() if k != "seen_at"} for row in result_rows],
            sort_keys=True,
        ).encode()
    ).hexdigest()
    total_size = sum(row.size for row in chosen)
    return {
        "source": "catalogue",
        "criteria": criteria.model_dump(),
        "snapshot_at": time.time(),
        "selection_fingerprint": fingerprint,
        "scanned_count": len(seen),
        "eligible_count": len(eligible),
        "requested_count": criteria.count,
        "selected_count": len(chosen),
        "shortfall": max(0, criteria.count - len(chosen)),
        "total_size_bytes": total_size,
        "total_size_display": f"{total_size / 1024**3:.2f} GiB / {total_size / 10**9:.2f} GB",
        "min_size_bytes": min((row.size for row in chosen), default=None),
        "max_size_bytes": max((row.size for row in chosen), default=None),
        "eligible_size_bytes": sum(row.size for row in eligible),
        "rows": result_rows,
        "coverage": (
            "Exact for cached metadata only; not proof of complete or current tracker coverage. "
            "Unknown or zero sizes are excluded. "
            "No folder, free-space or Plan exclusions are applied."
        ),
    }
