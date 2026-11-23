"""Read a .torrent's name, info hash and file tree."""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass

import torf
from torf import _flatbencode


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
        infohash=_infohash(t, files),
        files=files,
        data=data,
        piece_length=int(t.piece_size),
    )


def _infohash(t: torf.Torrent, files: dict[str, int]) -> str:
    try:
        return str(t.infohash)
    except torf.MetainfoError as exc:
        info = t.metainfo["info"]
        piece_length = info.get("piece length")
        if (
            not isinstance(piece_length, int)
            or isinstance(piece_length, bool)
            or piece_length <= 0
            or info.get("meta version") == 2
            or str(exc) != f"Invalid metainfo: ['info']['piece length'] is invalid: {piece_length}"
        ):
            raise

        # BEP 3 permits a positive v1 piece length that is not a 16 KiB multiple.
        # torf requires the multiple when validating, so check the original piece
        # count and validate the other fields with a temporary conforming length.
        pieces = info.get("pieces")
        size = sum(files.values())
        expected_count = (size + piece_length - 1) // piece_length
        if not isinstance(pieces, bytes) or len(pieces) != expected_count * 20:
            raise torf.MetainfoError(
                f"Expected {expected_count} pieces but there are "
                f"{len(pieces) // 20 if isinstance(pieces, bytes) else 0}"
            ) from exc

        valid_length = ((piece_length + 16_383) // 16_384) * 16_384
        info["piece length"] = valid_length
        info["pieces"] = b"\0" * (20 * ((size + valid_length - 1) // valid_length))
        try:
            t.validate()
        finally:
            info["piece length"] = piece_length
            info["pieces"] = pieces

        return hashlib.sha1(_flatbencode.encode(t.convert()[b"info"])).hexdigest()


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
