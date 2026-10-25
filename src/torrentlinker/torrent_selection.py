"""Deterministic selection of a refreshed Torrent Client snapshot."""

from __future__ import annotations

import math
import time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from torrentlinker.reseed import VERIFYING
from torrentlinker.torrent_management import tracker_group


class SelectionCriteria(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: str = Field(default="Ebook", max_length=200)
    tracker: str = Field(default="", max_length=253)
    status: Literal["seeding", "paused", "downloading", "any"] = "seeding"
    ranking: Literal[
        "lowest_note_largest_size",
        "highest_note",
        "largest_size",
        "smallest_size",
        "lowest_zen_per_gib",
        "highest_zen_per_gib",
    ] = "lowest_note_largest_size"
    count: int = Field(default=1000, ge=1, le=1000)
    query: str = Field(default="", max_length=500)
    min_size_bytes: int = Field(default=0, ge=0)
    max_size_bytes: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def valid_size_range(self):
        if self.max_size_bytes is not None and self.min_size_bytes > self.max_size_bytes:
            raise ValueError("Minimum size must not exceed maximum size.")
        return self

    @field_validator("tracker")
    @classmethod
    def tracker_host(cls, value: str) -> str:
        value = value.strip().lower().rstrip(".")
        if value and (any(c in value for c in "/:@?# ") or "." not in value):
            raise ValueError("Use a tracker hostname, not a private announce URL.")
        return tracker_group(value)


RANKINGS = {
    "lowest_note_largest_size": "Note ascending, size descending, hash ascending",
    "largest_size": "Size descending, hash ascending",
    "smallest_size": "Size ascending, hash ascending",
    "highest_note": "Note descending, size descending, hash ascending",
    "lowest_zen_per_gib": "Estimated Zen/day per GiB ascending, size descending, hash ascending",
    "highest_zen_per_gib": "Estimated Zen/day per GiB descending, size descending, hash ascending",
}


def select_rows(rows: list[dict[str, Any]], criteria: SelectionCriteria) -> dict[str, Any]:
    """Select over all rows, never a display page; unknown metrics never become zero."""
    category = criteria.category.strip().casefold()
    eligible = []
    excluded = {"filters": 0, "verifying": 0, "unknown_metric": 0, "provisional": 0}
    seen = set()
    for row in rows:
        if row["hash"] in seen:
            continue
        seen.add(row["hash"])
        paths = [" / ".join(path).casefold() for path in row["categories"]]
        if (
            (criteria.status != "any" and row["status"] != criteria.status)
            or (criteria.query.strip().casefold() not in row.get("name", "").casefold())
            or row["size"] < criteria.min_size_bytes
            or (criteria.max_size_bytes is not None and row["size"] > criteria.max_size_bytes)
            or (
                category and not any(p == category or p.startswith(category + " / ") for p in paths)
            )
            or (
                criteria.tracker
                and criteria.tracker not in {tracker_group(h) for h in row["trackers"]}
            )
        ):
            excluded["filters"] += 1
            continue
        if VERIFYING in row["tags"] or row["status"] == "checking":
            excluded["verifying"] += 1
            continue
        if criteria.ranking == "smallest_size" and row["size"] <= 0:
            excluded["unknown_metric"] += 1
            continue
        metric = (
            "note" if criteria.ranking in {"lowest_note_largest_size", "highest_note"} else "zen"
        )
        if criteria.ranking not in {"largest_size", "smallest_size"}:
            value = row[metric]
            if (
                value is None
                or not math.isfinite(value)
                or row["size"] <= 0
                or not row["ranking_metrics_known"]
            ):
                excluded["unknown_metric"] += 1
                continue
            if row["provisional"]:
                excluded["provisional"] += 1
                continue
        eligible.append(row)

    def order(row):
        if criteria.ranking == "lowest_note_largest_size":
            return row["note"], -row["size"], row["hash"]
        if criteria.ranking == "highest_note":
            return -row["note"], -row["size"], row["hash"]
        if criteria.ranking in {"lowest_zen_per_gib", "highest_zen_per_gib"}:
            direction = -1 if criteria.ranking == "highest_zen_per_gib" else 1
            return direction * row["zen"] / (row["size"] / 1024**3), -row["size"], row["hash"]
        if criteria.ranking == "smallest_size":
            return row["size"], row["hash"]
        return -row["size"], row["hash"]

    chosen = sorted(eligible, key=order)[: criteria.count]
    known_zen = [row["zen"] for row in chosen if row["zen"] is not None]
    return {
        "criteria": criteria.model_dump(),
        "ranking": RANKINGS[criteria.ranking],
        "snapshot_at": time.time(),
        "requested_count": criteria.count,
        "scanned_count": len(seen),
        "eligible_count": len(eligible),
        "selected_count": len(chosen),
        "shortfall": max(0, criteria.count - len(chosen)),
        "excluded": excluded,
        "total_size_bytes": sum(row["size"] for row in chosen),
        "estimated_zen_per_day": sum(known_zen),
        "unknown_zen_count": len(chosen) - len(known_zen),
        "estimates_are_provisional": True,
        "space_note": (
            "Pausing keeps files and frees no disk space. Sizes may include shared files."
        ),
        "rows": chosen,
    }
