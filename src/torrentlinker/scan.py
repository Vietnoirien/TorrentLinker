"""Scan: walk a Library Folder and list its Local Items."""

from __future__ import annotations

import os
from pathlib import Path

from torrentlinker.domain import LibraryFolder, LocalItem


def scan(folder: LibraryFolder) -> list[LocalItem]:
    return [_local_item(p) for p in _entries_at_depth(folder.path, folder.depth)]


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


def _local_item(path: Path) -> LocalItem:
    base = path.parent
    if path.is_file():
        return LocalItem(path, {path.name: path.stat().st_size})
    files: dict[str, int] = {}
    for dirpath, _dirs, names in os.walk(path):
        for name in names:
            f = Path(dirpath) / name
            files[f.relative_to(base).as_posix()] = f.stat().st_size
    return LocalItem(path, dict(sorted(files.items())))
