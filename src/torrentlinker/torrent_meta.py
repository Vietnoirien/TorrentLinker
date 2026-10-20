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


def pieces_inside(meta: TorrentMeta, absent: set[str]) -> list[tuple[int, int]]:
    """Ranges [start, end) of pieces made only of files present locally.

    When some files are absent, these are the pieces Verification can and must check:
    a piece shared with an absent file can never verify.
    """
    if meta.piece_length <= 0:
        return []
    spans = []
    offset = 0
    for path, size in meta.files.items():
        if size:
            spans.append((offset, offset + size, path not in absent))
        offset += size
    ranges: list[tuple[int, int]] = []
    for index, piece_start in enumerate(range(0, offset, meta.piece_length)):
        piece_end = min(piece_start + meta.piece_length, offset)
        present = [p for s, e, p in spans if s < piece_end and e > piece_start]
        if present and all(present):
            if ranges and ranges[-1][1] == index:
                ranges[-1] = (ranges[-1][0], index + 1)
            else:
                ranges.append((index, index + 1))
    return ranges
