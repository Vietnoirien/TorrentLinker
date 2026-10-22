"""Plan: which Catalogue torrents to download and seed for Zen or their note.

A greedy fill under each disk's free space and the torrent cap, tried over several
orderings for Zen, or highest-note first for Note. It is a heuristic.
Reseeds come first: they cost no download (ADR-0004).
"""

from __future__ import annotations

import math
import os
import shutil
from collections.abc import Callable, Collection, Hashable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from torrentlinker.domain import ItemState
from torrentlinker.downloads import DownloadFolders, IndexerCategory
from torrentlinker.library import LibraryEntry
from torrentlinker.review import CheckedCandidate
from torrentlinker.store import CatalogueRow
from torrentlinker.zen import GB, ZenProfile, ZenTorrent, added_values, estimate, note, weight

DEFAULT_MARGIN = 0.10  # share of each disk kept free


class PlanGoal(StrEnum):
    ZEN = "zen"
    NOTE = "note"


@dataclass(frozen=True)
class PlanOptions:
    goal: PlanGoal = PlanGoal.ZEN
    max_download_bytes: int = 0  # 0 = no additional limit
    max_torrents: int | None = None  # additional torrents in this Plan, including Reseeds
    max_seeders: int | None = None  # current swarm, before the user joins


@dataclass(frozen=True)
class DiskSpace:
    disk: Hashable
    folder: Path  # one Download Folder representing the disk
    free: int
    reserved: int
    download: int = 0

    @property
    def available(self) -> int:
        return max(0, self.free - self.reserved)

    @property
    def after_plan(self) -> int:
        return self.free - self.download


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
    note: float | None = None


@dataclass(frozen=True)
class Plan:
    items: list[PlanItem] = field(default_factory=list)
    zen_added: float = 0.0  # ≈ Zen/day the whole Plan adds to current seeding
    goal: PlanGoal = PlanGoal.ZEN
    disk_spaces: tuple[DiskSpace, ...] = ()

    @property
    def average_note(self) -> float | None:
        values = [(i.note, weight(i.candidate.size)) for i in self.items if i.note is not None]
        return sum(n * w for n, w in values) / sum(w for _, w in values) if values else None

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
    *,
    options: PlanOptions = PlanOptions(),
    disk_spaces: Sequence[DiskSpace] = (),
) -> Plan:
    """Choose candidates within each disk's budget (bytes) and `slots` more torrents."""
    candidates = [
        c for c in candidates if options.max_seeders is None or c.seeders <= options.max_seeders
    ]
    values = added_values(profile, [c.as_zen() for c in candidates], seeding)
    notes = {
        c.infohash: note(profile.zen_class, c.as_zen())
        if profile.zen_class.paid_on_seeding
        else 0.0
        for c in candidates
    }
    valued = [
        (c, v)
        for c, v in zip(candidates, values, strict=True)
        if (v if options.goal is PlanGoal.ZEN else notes[c.infohash]) > 0
    ]
    reseeds = sorted(
        (cv for cv in valued if cv[0].reseed),
        key=lambda cv: -(notes[cv[0].infohash] if options.goal is PlanGoal.NOTE else cv[1]),
    )
    reseeded = {c.infohash for c, _ in reseeds}
    downloads = [cv for cv in valued if not cv[0].reseed and cv[0].infohash not in reseeded]
    room = slots if slots is not None else len(candidates)
    room = max(0, room)
    if options.max_torrents is not None:
        room = min(room, max(0, options.max_torrents))
    first = reseeds[:room]
    base = estimate(profile, seeding).total
    best = Plan(goal=options.goal, disk_spaces=tuple(disk_spaces))
    rankings = list(ORDERINGS.values())
    if options.goal is PlanGoal.NOTE:
        rankings = [lambda c, v: notes[c.infohash]]
        first.sort(key=lambda cv: -notes[cv[0].infohash])
    for rank in rankings:
        ordered = sorted(downloads, key=lambda cv, r=rank: -r(cv[0], cv[1]))  # type: ignore[misc]
        chosen = first + _fill(
            ordered, dict(budgets), room - len(first), options.max_download_bytes
        )
        torrents = [*seeding, *(c.as_zen() for c, _ in chosen)]
        day = estimate(profile, torrents)
        plan = Plan(
            [
                PlanItem(c, z, notes[c.infohash])
                for (c, _), z in zip(chosen, day.per_torrent[len(seeding) :], strict=True)
            ],
            day.total - base,
            options.goal,
            tuple(
                DiskSpace(
                    s.disk,
                    s.folder,
                    s.free,
                    s.reserved,
                    sum(c.download_size for c, _ in chosen if c.disk == s.disk),
                )
                for s in disk_spaces
            ),
        )
        if options.goal is PlanGoal.NOTE or plan.zen_added > best.zen_added:
            best = plan
    return best


def _fill(
    ordered: list[tuple[PlanCandidate, float]],
    budgets: dict[Hashable, int],
    room: int,
    max_download_bytes: int = 0,
) -> list[tuple[PlanCandidate, float]]:
    chosen: list[tuple[PlanCandidate, float]] = []
    remaining = max_download_bytes if max_download_bytes > 0 else None
    for c, v in ordered:
        if len(chosen) >= room:
            break
        if budgets.get(c.disk, 0) >= c.size and (remaining is None or c.download_size <= remaining):
            budgets[c.disk] -= c.size
            if remaining is not None:
                remaining -= c.download_size
            chosen.append((c, v))
    return chosen


@dataclass(frozen=True)
class ReseedSource:
    """What a Reseed row needs to run the Reseed flow (ADR-0002)."""

    entry: LibraryEntry
    checked: CheckedCandidate


def reseed_candidates(
    profile: ZenProfile,
    found: Iterable[tuple[LibraryEntry, Sequence[CheckedCandidate]]],
    in_client: set[str],
    seeding: Sequence[ZenTorrent] = (),
    *,
    goal: PlanGoal = PlanGoal.ZEN,
    max_seeders: int | None = None,
) -> list[PlanCandidate]:
    """One Reseed row per Orphan with a Full Match, chosen for the Plan's goal.

    Partial Matches are left out: after Verification they stay stopped and earn nothing.
    """
    result = []
    for entry, checked in found:
        if entry.state is not ItemState.ORPHAN:
            continue
        full = [
            v
            for v in checked
            if v.match is not None
            and v.match.is_full
            and v.meta is not None
            and v.meta.infohash.lower() not in in_client
            and (max_seeders is None or v.candidate.seeders <= max_seeders)
        ]
        if not full:
            continue
        rows = [_reseed_row(entry, v) for v in full]
        values = (
            added_values(profile, [r.as_zen() for r in rows], seeding)
            if goal is PlanGoal.ZEN
            else [note(profile.zen_class, r.as_zen()) for r in rows]
        )
        result.append(max(zip(values, rows, strict=True), key=lambda vr: vr[0])[1])
    return result


def _reseed_row(entry: LibraryEntry, v: CheckedCandidate) -> PlanCandidate:
    assert v.meta is not None
    c = v.candidate
    return PlanCandidate(
        v.meta.infohash.lower(),
        c.title,
        c.size,
        c.seeders,
        c.categories[0] if c.categories else None,
        None,
        None,
        reseed=True,
        source=ReseedSource(entry, v),
    )


def catalogue_candidates(
    rows: Iterable[CatalogueRow],
    folders: DownloadFolders,
    categories: Mapping[int, IndexerCategory],
    in_client: set[str],
    disk_of: Callable[[Path], Hashable],
    only: Collection[int] | None = None,
) -> list[PlanCandidate]:
    """Catalogue torrents a Plan may download: not in qBittorrent, alive, in a category
    that has a Download Folder and, if `only` is given, in one of those categories (a
    category includes its subcategories)."""
    resolved: dict[int | None, Path | None] = {}
    disks: dict[Path, Hashable] = {}
    result = []
    for r in rows:
        if r.infohash.lower() in in_client or r.seeders < 1 or r.category is None:
            continue
        category = r.category
        if only is not None and not _within(category, only, categories):
            continue
        if category not in resolved:
            resolved[category] = folders.resolve(category, categories)
        folder = resolved[category]
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
                category,
                folder,
                disks[folder],
                source=r,
            )
        )
    return result


def _within(
    category: int, chosen: Collection[int], categories: Mapping[int, IndexerCategory]
) -> bool:
    seen: set[int] = set()
    current: int | None = category
    while current is not None and current not in seen:
        if current in chosen:
            return True
        seen.add(current)
        known = categories.get(current)
        current = known.parent if known else None
    return False


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
    return {s.disk: s.available for s in disk_space(folders, margin, usage=usage, disk=disk)}


def disk_space(
    folders: Iterable[Path],
    margin: float = DEFAULT_MARGIN,
    usage: Callable[[Path], tuple[int, int, int]] = shutil.disk_usage,
    disk: Callable[[Path], Hashable] = disk_of,
) -> list[DiskSpace]:
    """One physical-space reading per disk, including disks without eligible torrents."""
    spaces: dict[Hashable, DiskSpace] = {}
    for folder in folders:
        d = disk(folder)
        if d in spaces:
            continue
        total, _used, free = usage(existing_ancestor(folder))
        spaces[d] = DiskSpace(d, folder, free, int(margin * total))
    return list(spaces.values())
