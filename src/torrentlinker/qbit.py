"""qBittorrent port and its WebUI adapter.

Paths crossing this boundary are in qBittorrent's view; translation to the app's
view happens in the caller through Path Mappings.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

import qbittorrentapi

from torrentlinker.domain import Torrent


class Qbit(Protocol):
    def torrents(self) -> list[Torrent]: ...


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

    def torrents(self) -> list[Torrent]:
        result = []
        for t in self._client.torrents_info():
            files = {f.name: int(f.size) for f in self._client.torrents_files(t.hash)}
            result.append(
                Torrent(
                    hash=t.hash,
                    name=t.name,
                    save_path=Path(t.save_path),
                    files=files,
                    tags=frozenset(x.strip() for x in t.tags.split(",") if x.strip()),
                    progress=float(t.progress),
                    state=str(t.state),
                )
            )
        return result
