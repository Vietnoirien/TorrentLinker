"""What audio files say about themselves: tags, codec, bitrate, sample rate, bit depth.

Read with mutagen, which touches the disk: callers run it off the GUI thread (a
profile's `inspect`) and keep the answers in a TagCache until the next rule check.
"""

from __future__ import annotations

import struct
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import mutagen
from mutagen.mp3 import BitrateMode

from torrentlinker.domain import LocalItem

LOSSLESS = ("FLAC", "ALAC", "WAV", "WV", "AIFF")
# Tag names by format family: easy (Vorbis, easy ID3/MP4), raw ID3, ASF.
KEYS = {
    "artist": ("artist", "TPE1", "Author"),
    "album": ("album", "TALB", "WM/AlbumTitle"),
    "title": ("title", "TIT2", "Title"),
    "date": ("date", "TDRC", "WM/Year"),
    "track": ("tracknumber", "TRCK", "WM/TrackNumber"),
}


@dataclass(frozen=True)
class AudioTags:
    artist: str
    album: str
    title: str
    year: str  # four digits, or empty
    track: int  # 0 when untagged
    duration: float  # seconds
    codec: str  # FLAC, ALAC, WAV, WV, AIFF (lossless); MP3, AAC, OGG, WMA (lossy)
    bitrate: int  # kbps
    constant: bool  # False for a variable bitrate (an MP3 VBR)
    sample_rate: int  # Hz
    bits: int  # per sample; 0 for a lossy codec
    channels: int

    @property
    def lossless(self) -> bool:
        return self.codec in LOSSLESS


def read_tags(path: Path) -> AudioTags | None:
    """None when mutagen cannot read the file."""
    try:
        audio = mutagen.File(path, easy=True)
    except Exception:  # noqa: BLE001 - a damaged file is "unreadable", not a crash
        return None
    if audio is None or audio.info is None:
        return None
    info = audio.info
    tags: Any = audio.tags or {}

    def text(field: str) -> str:
        for key in KEYS[field]:
            try:
                value = tags.get(key)
            except Exception:  # noqa: BLE001 - odd tag containers
                value = None
            if isinstance(value, list | tuple):
                value = value[0] if value else None
            if value is not None and str(value).strip():
                return str(value).strip()
        return ""

    codec = _codec(audio)
    track = text("track").split("/")[0].strip()
    return AudioTags(
        artist=text("artist"),
        album=text("album"),
        title=text("title"),
        year=text("date")[:4] if text("date")[:4].isdigit() else "",
        track=int(track) if track.isdigit() else 0,
        duration=float(getattr(info, "length", 0.0) or 0.0),
        codec=codec,
        bitrate=round((getattr(info, "bitrate", 0) or 0) / 1000),
        constant=getattr(info, "bitrate_mode", None) != BitrateMode.VBR,
        sample_rate=int(getattr(info, "sample_rate", 0) or 0),
        bits=int(getattr(info, "bits_per_sample", 0) or 0) if codec in LOSSLESS else 0,
        channels=int(getattr(info, "channels", 0) or 0),
    )


def _codec(audio: Any) -> str:
    kind = type(audio).__name__
    if kind in ("MP4", "EasyMP4"):
        return "ALAC" if getattr(audio.info, "codec", "") == "alac" else "AAC"
    return {
        "FLAC": "FLAC",
        "MP3": "MP3",
        "EasyMP3": "MP3",
        "WAVE": "WAV",
        "WavPack": "WV",
        "AIFF": "AIFF",
        "OggVorbis": "OGG",
        "ASF": "WMA",
    }.get(kind, kind.upper())


class TagCache:
    """Tags read per file, found again by the file's path under the item and its size
    (a NFO is built from UploadFiles, which do not know where the item lives)."""

    def __init__(self, reader: Callable[[Path], AudioTags | None] = read_tags) -> None:
        self.reader = reader
        self.known: dict[tuple[str, int], AudioTags] = {}

    def inspect(self, item: LocalItem, paths: Iterable[str]) -> None:
        """Read these files (relative to the item's parent) that are not yet known."""
        for path in paths:
            key = (path, item.files[path])
            if key not in self.known and (tags := self.reader(item.save_path / path)):
                self.known[key] = tags  # an unreadable file is tried again next time

    def get(self, path: str, size: int) -> AudioTags | None:
        return self.known.get((path, size))

    def of(self, files: dict[str, int]) -> list[tuple[str, AudioTags]]:
        """The tags of those files read so far, in path order."""
        found = [(p, self.get(p, s)) for p, s in sorted(files.items())]
        return [(p, t) for p, t in found if t is not None]


def image_size(path: Path) -> tuple[int, int] | None:
    """(width, height) of a JPEG or PNG without an imaging library; None if unknown."""
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
        width, height = struct.unpack(">II", data[16:24])
        return width, height
    if data[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                height, width = struct.unpack(">HH", data[i + 5 : i + 9])
                return width, height
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                i += 2
                continue
            i += 2 + struct.unpack(">H", data[i + 2 : i + 4])[0]
    return None
