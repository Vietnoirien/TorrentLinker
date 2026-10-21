"""Plan: which Catalogue torrents to download and seed for the most Zen.

A greedy fill under each disk's free space and the torrent cap, tried over several
orderings, keeping the best total (as Zen Lab does). Not optimal, but close and fast.
Reseeds come first: they cost no download (ADR-0004).
"""

from __future__ import annotations

import math
import os
import shutil
from collections.abc import Callable, Hashable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from torrentlinker.downloads import DownloadFolders, IndexerCategory
from torrentlinker.store import CatalogueRow
from torrentlinker.zen import GB, ZenProfile, ZenTorrent, added_values, estimate

DEFAULT_MARGIN = 0.10  # share of each disk kept free


@dataclass(frozen=True)
class PlanCandidate:
    infohash: str
    title: str
    size: int
    seeders: int  # the swarm without the user
    category: int | None
    folder: Path | None  # Download Folder; None for a Reseed
    disk: Hashable = None
    reseed: bool = False
    source: object = field(default=None, compare=False)  # CatalogueRow, or the Reseed's data

    @property
    def download_size(self) -> int:
        return 0 if self.reseed else self.size

    def as_zen(self) -> ZenTorrent:
        return ZenTorrent(self.size, self.seeders + 1, 0.0, self.category)


@dataclass(frozen=True)
class PlanItem:
    candidate: PlanCandidate
    zen: float  # ≈ Zen/day it adds


@dataclass(frozen=True)
class Plan:
    items: list[PlanItem] = field(default_factory=list)
    zen_added: float = 0.0  # ≈ Zen/day the whole Plan adds to current seeding

    @property
    def download_size(self) -> int:
        return sum(i.candidate.download_size for i in self.items)

    @property
    def payback_days(self) -> float | None:
        """Days of the added Zen to pay the download back (1 Zen buys 1 Go)."""
        if self.zen_added <= 0:
            return None
        return self.download_size / GB / self.zen_added


ORDERINGS: dict[str, Callable[[PlanCandidate, float], float]] = {
    "zen per GB": lambda c, v: v / max(c.size / GB, 1e-9),
    "zen": lambda c, v: v,
    "zen per √GB": lambda c, v: v / math.sqrt(max(c.size / GB, 1e-9)),
}


def make_plan(
    profile: ZenProfile,
    candidates: Sequence[PlanCandidate],
    budgets: Mapping[Hashable, int],
    seeding: Sequence[ZenTorrent] = (),
    slots: int | None = None,
) -> Plan:
    """Choose candidates within each disk's budget (bytes) and `slots` more torrents."""
    values = added_values(profile, [c.as_zen() for c in candidates], seeding)
    valued = [(c, v) for c, v in zip(candidates, values, strict=True) if v > 0]
    reseeds = sorted((cv for cv in valued if cv[0].reseed), key=lambda cv: -cv[1])
    downloads = [cv for cv in valued if not cv[0].reseed]
    room = slots if slots is not None else len(candidates)
    first = reseeds[:room]
    base = estimate(profile, seeding).total
    best = Plan()
    for rank in ORDERINGS.values():
        ordered = sorted(downloads, key=lambda cv, r=rank: -r(cv[0], cv[1]))  # type: ignore[misc]
        chosen = first + _fill(ordered, dict(budgets), room - len(first))
        torrents = [*seeding, *(c.as_zen() for c, _ in chosen)]
        day = estimate(profile, torrents)
        plan = Plan(
            [
                PlanItem(c, z)
                for (c, _), z in zip(chosen, day.per_torrent[len(seeding) :], strict=True)
            ],
            day.total - base,
        )
        if plan.zen_added > best.zen_added:
            best = plan
    return best


def _fill(
    ordered: list[tuple[PlanCandidate, float]], budgets: dict[Hashable, int], room: int
) -> list[tuple[PlanCandidate, float]]:
    chosen: list[tuple[PlanCandidate, float]] = []
    for c, v in ordered:
        if len(chosen) >= room:
            break
        if budgets.get(c.disk, 0) >= c.size:
            budgets[c.disk] -= c.size
            chosen.append((c, v))
    return chosen


def catalogue_candidates(
    rows: Iterable[CatalogueRow],
    folders: DownloadFolders,
    categories: Mapping[int, IndexerCategory],
    in_client: set[str],
    disk_of: Callable[[Path], Hashable],
) -> list[PlanCandidate]:
    """Catalogue torrents a Plan may download: not in qBittorrent, alive, and in a
    category that has a Download Folder."""
    resolved: dict[int | None, Path | None] = {}
    disks: dict[Path, Hashable] = {}
    result = []
    for r in rows:
        if r.infohash.lower() in in_client or r.seeders < 1 or r.category is None:
            continue
        if r.category not in resolved:
            resolved[r.category] = folders.resolve(r.category, categories)
        folder = resolved[r.category]
        if folder is None:
            continue
        if folder not in disks:
            disks[folder] = disk_of(folder)
        result.append(
            PlanCandidate(
                r.infohash.lower(),
                r.title,
                r.size,
                r.seeders,
                r.category,
                folder,
                disks[folder],
                source=r,
            )
        )
    return result


# Disks ------------------------------------------------------------------------


def existing_ancestor(path: Path) -> Path:
    """The folder itself, or its nearest parent that exists (it is created on download)."""
    for p in (path, *path.parents):
        if p.exists():
            return p
    return Path(path.anchor or ".")


def disk_of(path: Path) -> int:
    return os.stat(existing_ancestor(path)).st_dev


def disk_budgets(
    folders: Iterable[Path],
    margin: float = DEFAULT_MARGIN,
    usage: Callable[[Path], tuple[int, int, int]] = shutil.disk_usage,
    disk: Callable[[Path], Hashable] = disk_of,
) -> dict[Hashable, int]:
    """Bytes a Plan may use on each disk holding Download Folders: free space minus a
    margin of the disk's size kept free."""
    budgets: dict[Hashable, int] = {}
    for folder in folders:
        d = disk(folder)
        if d in budgets:
            continue
        total, _used, free = usage(existing_ancestor(folder))
        budgets[d] = max(0, int(free - margin * total))
    return budgets
