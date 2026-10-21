"""Download Folders: where a Plan's torrents are downloaded, per Indexer category.

A subcategory uses its own folder, else its category's, else the default; a category
left without any is excluded from Plans. A Download Folder may lie inside a Library
Folder: a Plan torrent only ever creates its own files (ADR-0004).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class IndexerCategory:
    name: str
    parent: int | None = None  # the category of a subcategory


@dataclass
class DownloadFolders:
    by_category: dict[int, str] = field(default_factory=dict)
    default: str = ""

    def resolve(self, category: int, categories: Mapping[int, IndexerCategory]) -> Path | None:
        """The Download Folder of a category or subcategory, or None if it has none."""
        seen: set[int] = set()
        current: int | None = category
        while current is not None and current not in seen:
            seen.add(current)
            if folder := self.by_category.get(current, "").strip():
                return Path(folder)
            known = categories.get(current)
            current = known.parent if known else None
        return Path(self.default) if self.default.strip() else None

    def excluded(self, categories: Mapping[int, IndexerCategory]) -> list[int]:
        """Categories that resolve to no Download Folder, so Plans leave them out."""
        return sorted(c for c in categories if self.resolve(c, categories) is None)
