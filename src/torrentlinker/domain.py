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

    @property
    def has_external_ids(self) -> bool:
        """Whether items of this kind can be identified by IMDb/TMDb ids."""
        return self in (ContentKind.MOVIE, ContentKind.SERIES)


@dataclass(frozen=True)
class PathMapping:
    """Maps a path prefix as this app sees it to the same location as qBittorrent sees it.

    One list of them applies to every path exchanged with qBittorrent: Library Folders,
    Download Folders and Reseeds alike (ADR-0006).
    """

    local: str
    qbit: str


@dataclass(frozen=True)
class LibraryFolder:
    path: Path
    depth: int = 1
    kind: ContentKind = ContentKind.OTHER


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
    tracker: str = ""  # the current tracker's URL
    swarm_seeders: int = -1  # tracker-reported seeders, user included; -1 = not yet known
    seeding_time: float = 0.0  # seconds this client has seeded it
    size: int = 0  # total size, also known when files were not fetched

    @property
    def total_size(self) -> int:
        return self.size or sum(self.files.values())

    @property
    def is_seeding(self) -> bool:
        return self.progress >= 1.0 and self.state in SEEDING_STATES


SEEDING_STATES = {"uploading", "stalledUP", "forcedUP", "queuedUP", "checkingUP"}
