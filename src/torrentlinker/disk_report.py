"""Disques: the space of each disk, what fills it, and where the next download goes (#205).

A disk is what a storage root sits on, identified by its device (`st_dev`). The numbers come
from `statvfs`. What the library, the downloads and the Corbeille hold is measured by walking
their folders within a time budget, and remembered for a few minutes. The placement rule:
keep a film's versions and a series' episodes on the disk they already share, otherwise use
the disk with the most free space above the margin.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from torrentlinker.file_storage import FileStorage

MARGIN = 0.10
CACHE_SECONDS = 600.0
WALK_BUDGET = 5.0  # seconds one folder may be walked; the rest is reported as partial


@dataclass(frozen=True)
class Usage:
    total: int
    used: int
    free: int

    @property
    def margin(self) -> int:
        return int(self.total * MARGIN)

    @property
    def usable(self) -> int:
        """What a download may still take without crossing the margin."""
        return max(0, self.free - self.margin)


def usage(path: Path) -> Usage:
    stat = os.statvfs(path)
    total = stat.f_blocks * stat.f_frsize
    free = stat.f_bavail * stat.f_frsize
    return Usage(total, total - stat.f_bfree * stat.f_frsize, free)


_walked: dict[str, tuple[float, int, bool]] = {}


def tree_size(path: Path, budget: float = WALK_BUDGET, now=time.monotonic) -> tuple[int, bool]:
    """The bytes under `path` and whether the walk was cut short; never follows links."""
    key = str(path)
    cached = _walked.get(key)
    if cached and now() - cached[0] < CACHE_SECONDS:
        return cached[1], cached[2]
    started, total, partial, pending = now(), 0, False, [path]
    while pending:
        if now() - started > budget:
            partial = True
            break
        try:
            with os.scandir(pending.pop()) as entries:
                for entry in entries:
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            pending.append(Path(entry.path))
                        else:
                            total += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue
    _walked[key] = (now(), total, partial)
    return total, partial


def _under(path: Path, folders: Iterable[Path]) -> bool:
    return any(path == f or path.is_relative_to(f) for f in folders)


def disk_cards(
    storage: FileStorage,
    library: list[Path],
    downloads: list[Path],
    films_in: Callable[[Path], int] = lambda _: 0,
    library_bytes: Callable[[Path], int] | None = None,
    health: Callable[[list[Path]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """One card per disk, and the configured folders the application cannot see."""
    cards: list[dict[str, Any]] = []
    seen: list[Path] = []
    for disk in storage.disks():
        try:
            u = usage(disk.roots[0])
        except OSError as error:
            cards.append({"id": disk.id, "name": disk.name, "error": str(error)})
            continue
        lib_folders = [f for f in library if _under(f, disk.roots)]
        dl_folders = [f for f in downloads if _under(f, disk.roots)]
        seen += lib_folders + dl_folders
        measure = library_bytes or (lambda f: tree_size(f)[0])
        lib = sum(measure(f) for f in lib_folders)
        trash, trash_partial = tree_size(disk.trash) if disk.trash.exists() else (0, False)
        # The trash may sit inside a Download Folder: it is counted once, as the trash.
        dl = sum(
            max(0, tree_size(f)[0] - (trash if _under(disk.trash, [f]) else 0))
            for f in dl_folders
            if not _under(f, lib_folders)
        )
        other = max(0, u.used - lib - dl - trash)
        cards.append(
            {
                "id": disk.id, "name": disk.name, "roots": [str(r) for r in disk.roots],
                "total": u.total, "used": u.used, "free": u.free, "margin": u.margin,
                "usable": u.usable, "below_margin": u.free < u.margin,
                "library": lib, "downloads": dl, "trash": trash, "other": other,
                "partial": trash_partial,
                "films": sum(films_in(f) for f in lib_folders),
                "writable": disk.writable, "reason": disk.reason,
                "health": health(list(disk.roots)) if health else {"unavailable": "disabled"},
            }
        )  # fmt: skip
    missing = sorted(
        {str(f) for f in [*library, *downloads] if not f.exists() or not _under(f, storage.roots)}
    )
    return {"disks": cards, "missing": missing, "margin": MARGIN}


def place(
    cards: list[dict[str, Any]], size: int, together_with: Path | None = None
) -> dict[str, Any]:
    """The disk the next download goes to, and why (the placement rule)."""
    live = [c for c in cards if "error" not in c and c["writable"]]
    if together_with is not None:
        for card in live:
            if any(
                together_with == Path(r) or together_with.is_relative_to(r) for r in card["roots"]
            ):
                if card["usable"] >= size:
                    return {"disk": card["id"], "name": card["name"], "why": "together"}
                break  # it shares a disk that is full: the free-space rule applies
    fits = [c for c in live if c["usable"] >= size]
    if not fits:
        return {"disk": None, "name": "", "why": "none"}
    best = max(fits, key=lambda c: c["usable"])
    why = "most-free" if together_with is None else "together-full"
    return {"disk": best["id"], "name": best["name"], "why": why}
