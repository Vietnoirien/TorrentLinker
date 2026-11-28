"""Reattach torrents whose data left for the organised libraries (#223).

Before 2ab3e67, Ranger read a snapshot of the client without file lists, took every seeded file
for a free one, copied it into its library and sent the original to the trash: the torrent was
left pointing at files that are gone. Each copy was verified, so the data is in the library
under its new name. This finds it again, by exact size, and points the torrent at it: paused,
re-pointed (nothing to move, the old place is empty), each file renamed inside the client to
its library name, rechecked, and resumed only at 100 %. Nothing is written to the files.

Only clients that rename files inside a torrent (qBittorrent) are repaired here.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from torrentlinker.domain import Torrent


@dataclass
class Repair:
    """What reattaching one torrent does."""

    hash: str
    name: str
    save_path: Path  # where the torrent will point: the library root that holds its data
    left: list[Path] = field(default_factory=list)  # what it fetched again at the old place
    renames: list[tuple[str, str]] = field(default_factory=list)  # old → new, relative
    unmatched: list[str] = field(default_factory=list)  # small files the library lacks


def missing(torrent: Torrent) -> bool:
    """A torrent whose largest file is not whole where it points: gone, or being fetched
    again by the client that found it gone (it re-downloads what the library holds)."""
    if not torrent.files:
        return False
    main = max(torrent.files, key=lambda name: torrent.files[name])
    path = Path(torrent.save_path) / main
    try:
        whole = path.stat().st_size == torrent.files[main] and torrent.progress >= 1.0
    except OSError:
        return True
    return not whole


def library_index(roots: Iterable[Path]) -> dict[int, list[Path]]:
    """Every file of the organised libraries, by exact size."""
    index: dict[int, list[Path]] = {}
    for root in roots:
        for folder, _, names in os.walk(root):
            if "/." in folder:  # the trash and the Link Folder are not the library
                continue
            for name in names:
                path = Path(folder) / name
                try:
                    index.setdefault(path.stat().st_size, []).append(path)
                except OSError:
                    continue
    return index


def plan(torrent: Torrent, index: dict[int, list[Path]], roots: list[Path]) -> Repair | None:
    """Where each of the torrent's files is in the library, or None when its main file is
    not found there (or found twice: nothing is guessed)."""
    main = max(torrent.files, key=lambda name: torrent.files[name])
    found = index.get(torrent.files[main], [])
    if len(found) != 1:
        return None
    root = next((r for r in roots if found[0].is_relative_to(r)), None)
    if root is None:
        return None
    home = found[0].parent
    tops = {Path(torrent.save_path) / PurePosixPath(n).parts[0] for n in torrent.files}
    repair = Repair(torrent.hash, torrent.name, root, [p for p in sorted(tops) if p.exists()])
    used = {found[0]}
    for name, size in sorted(torrent.files.items()):
        if name == main:
            target = found[0]
        else:
            near = [p for p in index.get(size, []) if p not in used and p.is_relative_to(home)]
            if len(near) != 1:  # an nfo or a subtitle the library does not hold: fetched again
                repair.unmatched.append(name)
                target = home / PurePosixPath(name).name
            else:
                target = near[0]
        used.add(target)
        new = target.relative_to(root).as_posix()
        if new != name:
            repair.renames.append((name, new))
    return repair


def apply(
    client: Any,
    repair: Repair,
    *,
    wait: Callable[[float], None] = time.sleep,
    timeout: float = 3600.0,
) -> str:
    """Point the torrent at its library copy and check it: "seeding", "partial" (paused,
    some pieces to fetch again) or "failed: …". The files themselves are never written."""
    client.pause(repair.hash)
    client.set_location(repair.hash, str(repair.save_path))
    for old, new in repair.renames:
        client.rename_file(repair.hash, old, new)
    for old, new in repair.renames:  # the names point at files that are really there
        if not (repair.save_path / new).exists() and old not in repair.unmatched:
            return f"failed: {new} is not in the library"
    client.recheck(repair.hash)
    # Right after the request the client may still report the old 100 %: the check has to be
    # seen starting (or the progress to drop) before its end is trusted.
    waited, started = 0.0, False
    while True:
        wait(2.0)
        waited += 2.0
        torrent = client.torrent(repair.hash, with_files=False)
        if torrent is None:
            return "failed: the torrent left the client"
        busy = "check" in torrent.state.lower() or "moving" in torrent.state.lower()
        # A small torrent may be checked between two looks: after a while its state is it.
        started = started or busy or torrent.progress < 1.0 or waited >= 20.0
        if started and not busy:
            break
        if waited > timeout:
            return "failed: the check did not end"
    if torrent.progress >= 0.9999:
        client.start(repair.hash)
        return "seeding"
    if torrent.progress >= 0.99:
        # The videos are whole; an nfo or a subtitle the library lacks is fetched again.
        client.start(repair.hash)
        return "partial"
    return "paused"  # too much missing to trust the match: left paused for the Owner
