"""Scan: walk a Library Folder and list its Local Items."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from torrentlinker.domain import LibraryFolder, LocalItem

if TYPE_CHECKING:
    from torrentlinker.store import Store


def scan(folder: LibraryFolder, cache: Store | None = None) -> list[LocalItem]:
    return [_local_item(p, cache) for p in _entries_at_depth(folder.path, folder.depth)]


def _entries_at_depth(root: Path, depth: int) -> list[Path]:
    """Entries `depth` levels below root; a file met earlier is an entry on its own."""
    found: list[Path] = []
    level = [root]
    for remaining in range(depth, 0, -1):
        children: list[Path] = []
        for d in level:
            for child in sorted(d.iterdir()):
                if remaining == 1 or child.is_file():
                    found.append(child)
                else:
                    children.append(child)
        level = children
    return found


def _local_item(path: Path, cache: Store | None) -> LocalItem:
    base = path.parent
    if path.is_file():
        return LocalItem(path, {path.name: path.stat().st_size})
    # A folder whose directories all keep their mtime has the same entries, so its file
    # list is reused without stat-ing every file. A file rewritten in place under the
    # same name is not noticed; that is rare in a media library.
    signature = _signature(path) if cache else ""
    if cache and (files := cache.cached_scan(path, signature)) is not None:
        return LocalItem(path, files)
    walked: dict[str, int] = {}
    for dirpath, _dirs, names in os.walk(path):
        for name in names:
            f = Path(dirpath) / name
            walked[f.relative_to(base).as_posix()] = f.stat().st_size
    files = dict(sorted(walked.items()))
    if cache:
        cache.cache_scan(path, signature, files)
    return LocalItem(path, files)


def _signature(path: Path) -> str:
    parts = []
    for dirpath, dirs, _names in os.walk(path):
        dirs.sort()
        parts.append(f"{dirpath}:{os.stat(dirpath).st_mtime_ns}")
    return "|".join(parts)
