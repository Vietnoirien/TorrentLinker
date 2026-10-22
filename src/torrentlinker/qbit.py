"""qBittorrent port and its WebUI adapter.

Paths crossing this boundary are in qBittorrent's view; translation to the app's
view happens in the caller through Path Mappings.
"""

from __future__ import annotations

import re
import threading
import time
from pathlib import Path
from typing import Any, Protocol

import qbittorrentapi

from torrentlinker.domain import Torrent
from torrentlinker.torrent_meta import read_torrent


class Qbit(Protocol):
    def torrents(self, tag: str | None = None, with_files: bool = True) -> list[Torrent]:
        """Torrents, optionally without their file lists (much faster)."""
        ...

    def torrent(self, hash: str) -> Torrent | None: ...
    def add(self, data: bytes, save_path: str, tags: list[str]) -> str:
        """Add stopped, with automatic management off and the original layout; return hash."""
        ...

    def rename_file(self, hash: str, old: str, new: str) -> None:
        """Rename a file inside the torrent (paths relative to the save path)."""
        ...

    def download(self, data: bytes, save_path: str, tags: list[str]) -> str:
        """Add started, to download into `save_path` with the original layout and
        automatic management off; return hash."""
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


API_KEY_PATTERN = re.compile(r"^qbt_[A-Za-z0-9]{28}$")


def is_api_key(text: str) -> bool:
    """Whether `text` looks like a qBittorrent WebUI API key (qBittorrent 5.2+)."""
    return bool(API_KEY_PATTERN.match(text))


class _SharedLogin:
    """qbittorrent-api calls that share one login, safe when several threads start at once.

    Left alone, every thread that finds no session logs in by itself, the logins replace
    each other's session cookie and requests in between are refused with 403.
    """

    def __init__(self, client: qbittorrentapi.Client) -> None:
        self._client = client
        self._lock = threading.Lock()
        self._logged_in = False

    def log_in(self) -> None:
        with self._lock:
            self._client.auth_log_in()
            self._logged_in = True

    def __getattr__(self, name: str) -> Any:
        attribute = getattr(self._client, name)
        if not callable(attribute) or name.startswith("auth_"):
            return attribute

        def call(*args: Any, **kwargs: Any) -> Any:
            if not self._logged_in:
                with self._lock:
                    if not self._logged_in:
                        self._client.auth_log_in()
                        self._logged_in = True
            try:
                return attribute(*args, **kwargs)
            except qbittorrentapi.Forbidden403Error:
                self.log_in()  # the session expired or was replaced: once more
                return attribute(*args, **kwargs)

        return call


class QbitApi:
    """Adapter over qBittorrent's WebUI API (4.5+ and 5.x).

    With an API key (qBittorrent 5.2+) every request carries `Authorization: Bearer`
    and there is no login; otherwise the username and password open one session that
    every thread shares.
    """

    def __init__(self, host: str, username: str, password: str, api_key: str = "") -> None:
        client = qbittorrentapi.Client(
            host=host,
            username=None if api_key else username,
            password=None if api_key else password,
            api_key=api_key or None,
            VERIFY_WEBUI_CERTIFICATE=False,
            REQUESTS_ARGS={"timeout": (5, 30)},
        )
        self._client: Any = client if api_key else _SharedLogin(client)

    def check(self) -> str:
        """Log in (or validate the API key) and return the qBittorrent version."""
        self._client.auth_log_in()
        return str(self._client.app_version())

    def default_save_path(self) -> str:
        """qBittorrent's own download folder, as qBittorrent sees it."""
        return str(self._client.app_default_save_path())

    def rotate_api_key(self) -> str:
        """Ask qBittorrent (5.2+) for a new API key, replacing any previous one."""
        return str(self._client.app_rotate_api_key()["apiKey"])

    def delete_api_key(self) -> None:
        self._client.app_delete_api_key()

    def torrents(self, tag: str | None = None, with_files: bool = True) -> list[Torrent]:
        return [self._torrent(t, with_files) for t in self._client.torrents_info(tag=tag)]

    def torrent(self, hash: str) -> Torrent | None:
        found = self._client.torrents_info(torrent_hashes=hash)
        return self._torrent(found[0]) if found else None

    def _torrent(self, t: qbittorrentapi.TorrentDictionary, with_files: bool = True) -> Torrent:
        files = (
            {f.name: int(f.size) for f in self._client.torrents_files(t.hash)} if with_files else {}
        )
        return Torrent(
            hash=t.hash,
            name=t.name,
            save_path=Path(t.save_path),
            files=files,
            tags=frozenset(x.strip() for x in t.tags.split(",") if x.strip()),
            progress=float(t.progress),
            state=str(t.state),
            tracker=str(t.get("tracker", "")),
            swarm_seeders=max(int(str(t.get("num_complete", -1))), -1),
            seeding_time=float(str(t.get("seeding_time", 0))),
            size=int(str(t.get("total_size", 0) or t.get("size", 0))),
        )

    def add(self, data: bytes, save_path: str, tags: list[str]) -> str:
        return self._add(data, save_path, tags, stopped=True)

    def download(self, data: bytes, save_path: str, tags: list[str]) -> str:
        return self._add(data, save_path, tags, stopped=False)

    def _add(self, data: bytes, save_path: str, tags: list[str], stopped: bool) -> str:
        h = read_torrent(data).infohash
        result = self._client.torrents_add(
            torrent_files=data,
            save_path=save_path,
            is_stopped=stopped,
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
