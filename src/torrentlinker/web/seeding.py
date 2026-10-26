"""Bounded, read-only Seeding pages using the desktop's Zen calculation."""

from __future__ import annotations

from typing import Any

from torrentlinker.category_tags import category_path
from torrentlinker.seeding import Seeding
from torrentlinker.zen import ZenProfile, compare_classes


def seeding_page(
    view: Seeding,
    profile: ZenProfile,
    uploads: int,
    *,
    query: str = "",
    group: str = "",
    sort: str = "zen",
    descending: bool = True,
    offset: int = 0,
    limit: int = 100,
) -> dict[str, Any]:
    """Return category aggregates and at most one page of a category's own torrents.

    Parent totals include descendants. Unfiltered account totals and class estimates
    are independent of pagination and text filters. No private tracker URLs are exposed.
    """
    groups: dict[str, dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []
    matched = 0
    for row in view.rows:
        torrent = row.torrent
        path = category_path(row.category, view.categories)
        keys = [path[:n] for n in range(1, len(path) + 1)] or [()]
        names = [view.categories[cid].name if cid in view.categories else str(cid) for cid in path]
        if query.strip().casefold() not in " ".join([torrent.name, *names]).casefold():
            continue
        matched += 1
        parent = ""
        for key in keys:
            identity = "/".join(map(str, key)) if key else "unknown"
            info = view.categories.get(key[-1]) if key else None
            summary = groups.setdefault(
                identity,
                {
                    "id": identity,
                    "parent": parent,
                    "category": key[-1] if key else None,
                    "name": info.name if info else "",
                    "count": 0,
                    "direct_count": 0,
                    "size": 0,
                    "zen": 0.0,
                    "note_sum": 0.0,
                    "note_count": 0,
                },
            )
            summary["count"] += 1
            summary["size"] += torrent.total_size
            summary["zen"] += row.zen or 0
            if row.note is not None:
                summary["note_sum"] += row.note
                summary["note_count"] += 1
            parent = identity
        groups[parent]["direct_count"] += 1
        if parent == group:
            rows.append(
                {
                    "hash": torrent.hash,
                    "name": torrent.name,
                    "size": torrent.total_size,
                    "seeders": torrent.swarm_seeders if torrent.swarm_seeders >= 0 else None,
                    "seed_days": torrent.seeding_time / 86400,
                    "zen": row.zen,
                    "note": row.note,
                    "provisional_category": row.provisional_category,
                    "seeding": torrent.is_seeding,
                }
            )
    for summary in groups.values():
        count = summary.pop("note_count")
        total = summary.pop("note_sum")
        summary["note"] = total / count if count else None
    # Unknown metrics sort last in either direction, never as known zeros.
    known = [r for r in rows if r[sort] is not None]
    unknown = [r for r in rows if r[sort] is None]
    known.sort(key=lambda r: r["hash"])
    known.sort(
        key=lambda r: r[sort].casefold() if isinstance(r[sort], str) else r[sort],
        reverse=descending,
    )
    rows = known + sorted(unknown, key=lambda r: r["hash"])
    return {
        "groups": list(groups.values()),
        "rows": rows[offset : offset + limit],
        "total": len(rows),
        "offset": offset,
        "matched": matched,
        "summary": {
            "count": view.count,
            "total": len(view.rows),
            "daily": view.day.total,
            "paid": view.day.paid,
        },
        "classes": [
            {"id": cls.value, "daily": day.total, "current": cls == profile.zen_class}
            for cls, day in compare_classes(profile, view.active, uploads).items()
        ],
        "uploads": uploads,
    }
