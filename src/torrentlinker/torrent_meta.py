"""Read a .torrent's name, info hash and file tree."""

from __future__ import annotations

import io
from dataclasses import dataclass

import torf


@dataclass(frozen=True)
class TorrentMeta:
    name: str
    infohash: str
    files: dict[str, int]  # in torrent order, which is also qBittorrent's file index order
    data: bytes
    piece_length: int = 0


def read_torrent(data: bytes) -> TorrentMeta:
    t = torf.Torrent.read_stream(io.BytesIO(data), validate=False)
    files = {"/".join(f.parts): int(f.size) for f in t.files}
    return TorrentMeta(
        name=str(t.name),
        infohash=str(t.infohash),
        files=files,
        data=data,
        piece_length=int(t.piece_size),
    )


def expected_progress(meta: TorrentMeta, unwanted: set[str]) -> float:
    """Best Verification progress reachable when `unwanted` files are absent.

    A piece shared by a wanted and an unwanted file cannot verify, so the wanted
    bytes inside such boundary pieces are lost to the check.
    """
    if not unwanted or meta.piece_length <= 0:
        return 1.0
    spans = []
    offset = 0
    for path, size in meta.files.items():
        spans.append((offset, offset + size, path not in unwanted))
        offset += size
    wanted_total = sum(e - s for s, e, w in spans if w)
    if not wanted_total:
        return 1.0
    lost = 0
    for piece_start in range(0, offset, meta.piece_length):
        piece_end = min(piece_start + meta.piece_length, offset)
        overlaps = [
            (max(s, piece_start), min(e, piece_end), w)
            for s, e, w in spans
            if s < piece_end and e > piece_start
        ]
        if any(w for *_, w in overlaps) and not all(w for *_, w in overlaps):
            lost += sum(e - s for s, e, w in overlaps if w)
    return 1 - lost / wanted_total
