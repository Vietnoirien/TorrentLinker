"""Domain types. Vocabulary follows CONTEXT.md."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class ContentKind(StrEnum):
    MOVIE = "movie"
    SERIES = "series"
    MUSIC = "music"
    EBOOK = "ebook"
    GAME = "game"
    MODEL_3D = "3d-model"
    OTHER = "other"


@dataclass(frozen=True)
class PathMapping:
    """Maps a path prefix as this app sees it to the same location as qBittorrent sees it."""

    local: str
    qbit: str


@dataclass(frozen=True)
class LibraryFolder:
    path: Path
    depth: int = 1
    kind: ContentKind = ContentKind.OTHER
    mapping: PathMapping | None = None


@dataclass(frozen=True)
class LocalItem:
    """One entry of a Library Folder at its scan depth.

    `files` maps each file's path, relative to the item's parent folder and using
    forward slashes (the convention qBittorrent uses under a save path), to its size.
    """

    path: Path
    files: dict[str, int] = field(default_factory=dict)

    @property
    def size(self) -> int:
        return sum(self.files.values())

    @property
    def save_path(self) -> Path:
        return self.path.parent


class ItemState(StrEnum):
    SEEDED = "seeded"
    PARTIALLY_SEEDED = "partially-seeded"
    ORPHAN = "orphan"


@dataclass(frozen=True)
class Torrent:
    """A torrent in qBittorrent, with paths in this app's view (after Path Mapping).

    `files` maps each file's path relative to `save_path` to its size.
    """

    hash: str
    name: str
    save_path: Path
    files: dict[str, int] = field(default_factory=dict)
    tags: frozenset[str] = frozenset()
    progress: float = 1.0
    state: str = ""
