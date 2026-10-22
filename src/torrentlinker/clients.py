"""Connect to the Torrent Client the user chose (ADR-0009)."""

from __future__ import annotations

from torrentlinker.deluge import DelugeApi
from torrentlinker.domain import TorrentClient
from torrentlinker.qbit import ClientApi, QbitApi


def connect(
    client: TorrentClient, host: str, username: str, password: str, api_key: str = ""
) -> ClientApi:
    """The client's adapter; Deluge's Web UI has a password and no username."""
    if client is TorrentClient.DELUGE:
        return DelugeApi(host, password)
    return QbitApi(host, username, password, api_key)
