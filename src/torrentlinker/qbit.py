"""qBittorrent port and its WebUI adapter.

Paths crossing this boundary are in qBittorrent's view; translation to the app's
view happens in the caller through Path Mappings.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Protocol

import qbittorrentapi

from torrentlinker.domain import Torrent
from torrentlinker.torrent_meta import read_torrent


class Qbit(Protocol):
    def torrents(self, tag: str | None = None) -> list[Torrent]: ...
    def torrent(self, hash: str) -> Torrent | None: ...
    def add(self, data: bytes, save_path: str, tags: list[str]) -> str:
        """Add stopped, with automatic management off and the original layout; return hash."""
        ...

    def rename_file(self, hash: str, old: str, new: str) -> None:
        """Rename a file inside the torrent (paths relative to the save path)."""
        ...

    def set_file_priority(self, hash: str, indexes: list[int], priority: int) -> None: ...
    def recheck(self, hash: str) -> None: ...
    def piece_states(self, hash: str) -> list[int]:
        """Per piece: 0 missing, 1 downloading, 2 verified."""
        ...

    def start(self, hash: str) -> None: ...
    def remove(self, hash: str) -> None:
        """Remove the torrent from qBittorrent. Never deletes its files."""
        ...

    def add_tags(self, hash: str, tags: list[str]) -> None: ...
    def remove_tags(self, hash: str, tags: list[str]) -> None: ...


class QbitApi:
    """Adapter over qBittorrent's WebUI API (4.5+ and 5.x)."""

    def __init__(self, host: str, username: str, password: str) -> None:
        self._client = qbittorrentapi.Client(
            host=host,
            username=username,
            password=password,
            VERIFY_WEBUI_CERTIFICATE=False,
            REQUESTS_ARGS={"timeout": (5, 30)},
        )

    def check(self) -> str:
        """Log in and return the qBittorrent version; raises on failure."""
        self._client.auth_log_in()
        return str(self._client.app_version())

    def torrents(self, tag: str | None = None) -> list[Torrent]:
        return [self._torrent(t) for t in self._client.torrents_info(tag=tag)]

    def torrent(self, hash: str) -> Torrent | None:
        found = self._client.torrents_info(torrent_hashes=hash)
        return self._torrent(found[0]) if found else None

    def _torrent(self, t: qbittorrentapi.TorrentDictionary) -> Torrent:
        files = {f.name: int(f.size) for f in self._client.torrents_files(t.hash)}
        return Torrent(
            hash=t.hash,
            name=t.name,
            save_path=Path(t.save_path),
            files=files,
            tags=frozenset(x.strip() for x in t.tags.split(",") if x.strip()),
            progress=float(t.progress),
            state=str(t.state),
        )

    def add(self, data: bytes, save_path: str, tags: list[str]) -> str:
        h = read_torrent(data).infohash
        result = self._client.torrents_add(
            torrent_files=data,
            save_path=save_path,
            is_stopped=True,
            use_auto_torrent_management=False,
            content_layout="Original",
            tags=tags,
        )
        if str(result).strip().lower().startswith("fail"):
            raise RuntimeError("qBittorrent refused the torrent")
        for _ in range(50):  # the add is asynchronous inside qBittorrent
            if self._client.torrents_info(torrent_hashes=h):
                return h
            time.sleep(0.2)
        raise RuntimeError("Torrent did not appear in qBittorrent")

    def rename_file(self, hash: str, old: str, new: str) -> None:
        self._client.torrents_rename_file(torrent_hash=hash, old_path=old, new_path=new)

    def set_file_priority(self, hash: str, indexes: list[int], priority: int) -> None:
        self._client.torrents_file_priority(torrent_hash=hash, file_ids=indexes, priority=priority)

    def recheck(self, hash: str) -> None:
        self._client.torrents_recheck(torrent_hashes=hash)

    def piece_states(self, hash: str) -> list[int]:
        return [int(s) for s in self._client.torrents_piece_states(torrent_hash=hash)]

    def start(self, hash: str) -> None:
        self._client.torrents_start(torrent_hashes=hash)

    def remove(self, hash: str) -> None:
        self._client.torrents_delete(delete_files=False, torrent_hashes=hash)

    def add_tags(self, hash: str, tags: list[str]) -> None:
        self._client.torrents_add_tags(tags=tags, torrent_hashes=hash)

    def remove_tags(self, hash: str, tags: list[str]) -> None:
        self._client.torrents_remove_tags(tags=tags, torrent_hashes=hash)
