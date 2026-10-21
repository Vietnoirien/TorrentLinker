"""In-memory qBittorrent implementing the Qbit port."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

from torrentlinker.domain import Torrent
from torrentlinker.torrent_meta import read_torrent

CHECKING = "checkingUP"


@dataclass
class FakeQbit:
    by_hash: dict[str, Torrent] = field(default_factory=dict)
    priorities: dict[str, dict[int, int]] = field(default_factory=dict)
    removed: list[tuple[str, bool]] = field(default_factory=list)
    started: list[str] = field(default_factory=list)
    rechecked: list[str] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)
    pieces: dict[str, list[int]] = field(default_factory=dict)
    downloads: list[str] = field(default_factory=list)

    # Qbit port ---------------------------------------------------------------

    def torrents(self, tag: str | None = None, with_files: bool = True) -> list[Torrent]:
        return [t for t in self.by_hash.values() if tag is None or tag in t.tags]

    def torrent(self, hash: str) -> Torrent | None:
        return self.by_hash.get(hash)

    def add(self, data: bytes, save_path: str, tags: list[str]) -> str:
        meta = read_torrent(data)
        self.by_hash[meta.infohash] = Torrent(
            meta.infohash,
            meta.name,
            Path(save_path),
            dict(meta.files),
            frozenset(tags),
            0.0,
            "stoppedDL",
        )
        return meta.infohash

    def download(self, data: bytes, save_path: str, tags: list[str]) -> str:
        h = self.add(data, save_path, tags)
        self._set(h, state="downloading")
        self.downloads.append(h)
        return h

    def rename_file(self, hash: str, old: str, new: str) -> None:
        self.calls.append(f"rename {old} -> {new}")
        files = dict(self.by_hash[hash].files)
        files[new] = files.pop(old)
        self._set(hash, files=files)

    def set_file_priority(self, hash: str, indexes: list[int], priority: int) -> None:
        self.calls.append(f"priority {indexes} = {priority}")
        self.priorities.setdefault(hash, {}).update({i: priority for i in indexes})

    def recheck(self, hash: str) -> None:
        self.calls.append("recheck")
        self.rechecked.append(hash)
        self._set(hash, state=CHECKING)

    def start(self, hash: str) -> None:
        self.started.append(hash)
        self._set(hash, state="uploading")

    def remove(self, hash: str) -> None:
        self.removed.append((hash, False))
        del self.by_hash[hash]

    def add_tags(self, hash: str, tags: list[str]) -> None:
        t = self.by_hash[hash]
        self._set(hash, tags=t.tags | set(tags))

    def remove_tags(self, hash: str, tags: list[str]) -> None:
        t = self.by_hash[hash]
        self._set(hash, tags=t.tags - set(tags))

    # Test controls -----------------------------------------------------------

    def piece_states(self, hash: str) -> list[int]:
        return self.pieces.get(hash, [])

    def finish_check(self, hash: str, progress: float, pieces: list[int] | None = None) -> None:
        if pieces is not None:
            self.pieces[hash] = pieces
        self._set(hash, progress=progress, state="stoppedUP" if progress == 1 else "stoppedDL")

    def _set(self, hash: str, **changes: object) -> None:
        self.by_hash[hash] = replace(self.by_hash[hash], **changes)  # type: ignore[arg-type]
