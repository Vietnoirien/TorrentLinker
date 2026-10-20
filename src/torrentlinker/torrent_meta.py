"""Read a .torrent's name, info hash and file tree."""

from __future__ import annotations

import io
from dataclasses import dataclass

import torf


@dataclass(frozen=True)
class TorrentMeta:
    name: str
    infohash: str
    files: dict[str, int]
    data: bytes


def read_torrent(data: bytes) -> TorrentMeta:
    t = torf.Torrent.read_stream(io.BytesIO(data), validate=False)
    files = {"/".join(f.parts): int(f.size) for f in t.files}
    return TorrentMeta(name=str(t.name), infohash=str(t.infohash), files=files, data=data)
