"""What MediaInfo says about a video file, as the facts c411's video rules and names need.

pymediainfo wraps libmediainfo: bundled in its Windows and macOS wheels, a system library
on Linux (ADR-0012). `available()` says whether it can be loaded; reading touches the disk,
so callers run it off the GUI thread (a profile's `inspect`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

from pymediainfo import MediaInfo

LOSSLESS_AUDIO = ("TRUEHD", "DTS.HD.MA", "DTSX", "LPCM", "FLAC")
GPU_ENCODER_RE = re.compile(r"nvenc|nvidia|\bqsv\b|quick ?sync|\bamf\b|\bvce\b", re.IGNORECASE)
FRENCH_CODES = ("fr", "fre", "fra")
DV_PROFILE_RE = re.compile(r"dv(?:he|h1|av1)\.(\d\d)", re.IGNORECASE)


@dataclass(frozen=True)
class AudioTrack:
    codec: str  # as a release name spells it: AC3, EAC3, DTS.HD.MA, TRUEHD, AAC…
    channels: int
    language: str  # ISO 639-1 (`fr`), empty if unknown
    variant: str  # for French: VFF, VFQ or VFB
    atmos: bool
    bitrate: int  # kb/s

    @property
    def lossless(self) -> bool:
        return self.codec in LOSSLESS_AUDIO

    @property
    def french(self) -> bool:
        return self.language in FRENCH_CODES

    @property
    def layout(self) -> str:
        """`5.1`, `2.0`…"""
        return f"{self.channels - 1}.1" if self.channels >= 6 else f"{self.channels}.0"


@dataclass(frozen=True)
class SubtitleTrack:
    format: str
    language: str
    forced: bool
    sdh: bool

    @property
    def full_french(self) -> bool:
        return self.language in FRENCH_CODES and not self.forced


@dataclass(frozen=True)
class MediaFacts:
    container: str
    duration: float  # seconds
    bitrate: int  # overall, kb/s
    width: int
    height: int
    video_codec: str  # AVC, HEVC, AV1, VC1, MPEG2, XVID, MPEG4
    video_bitrate: int  # kb/s, 0 when unknown
    encoder: str  # x264, x265, or the writing library as is; empty when none shows
    gpu_encoder: str  # NVENC, QSV or AMF when the encode settings name one
    dv_profile: int  # 0 when not Dolby Vision
    hdr10: bool
    hdr10plus: bool
    hlg: bool
    audio: tuple[AudioTrack, ...]
    subtitles: tuple[SubtitleTrack, ...]
    text: str  # MediaInfo's own text output, as c411's NFO wants it

    @property
    def resolution(self) -> str:
        """The resolution tag by the frame's size: 2160p, 1080p, 720p, or SD."""
        if self.width >= 3000 or self.height >= 1800:
            return "2160p"
        if self.width >= 1700 or self.height >= 900:
            return "1080p"
        if self.width >= 1200 or self.height >= 650:
            return "720p"
        return "SD"


@cache
def available() -> bool:
    """Probe the installed library once per process, not for every upload row."""
    try:
        return bool(MediaInfo.can_parse())
    except Exception:  # noqa: BLE001 - a broken install is "not available"
        return False


def read_media(path: Path) -> MediaFacts | None:
    """The facts of a file; None when MediaInfo cannot read it."""
    try:
        info = MediaInfo.parse(path)
        text = MediaInfo.parse(path, output="", full=False)
    except Exception:  # noqa: BLE001
        return None
    return facts_from(info, str(text), path.name)


def facts_from(info: MediaInfo, text: str, name: str = "") -> MediaFacts | None:
    """None when the file has no video track."""
    if not info.video_tracks:
        return None
    video = info.video_tracks[0]
    general = info.general_tracks[0] if info.general_tracks else None
    everything = " ".join(str(v) for v in video.to_data().values())
    library = str(video.writing_library or "")
    settings = str(video.encoding_settings or "")
    gpu = GPU_ENCODER_RE.search(f"{library} {settings} {everything}")
    hdr = f"{video.hdr_format or ''} / {video.hdr_format_compatibility or ''}".lower()
    profile = DV_PROFILE_RE.search(str(video.hdr_format_profile or ""))
    return MediaFacts(
        container=str(general.format) if general and general.format else "",
        duration=float(general.duration or 0) / 1000 if general else 0.0,
        bitrate=_kbps(general.overall_bit_rate if general else None),
        width=int(video.width or 0),
        height=int(video.height or 0),
        video_codec=_video_codec(video),
        video_bitrate=_kbps(video.bit_rate),
        encoder=_encoder(library),
        gpu_encoder=_gpu_name(gpu.group(0)) if gpu else "",
        dv_profile=int(profile.group(1)) if profile else (1 if "dolby vision" in hdr else 0),
        hdr10="2086" in hdr or "hdr10" in hdr or str(video.transfer_characteristics) == "PQ",
        hdr10plus="2094" in hdr or "hdr10+" in hdr,
        hlg="HLG" in str(video.transfer_characteristics or ""),
        audio=tuple(_audio(t) for t in info.audio_tracks),
        subtitles=tuple(_subtitle(t) for t in info.text_tracks),
        text=with_file_name(text, name),
    )


def _kbps(value: Any) -> int:
    try:
        return round(float(value) / 1000)
    except (TypeError, ValueError):
        return 0


def _video_codec(track: Any) -> str:
    codec = str(track.format or "")
    if codec.lower() == "xvid" or "xvid" in str(track.codec_id or "").lower():
        return "XVID"
    if codec == "MPEG Video":
        return "MPEG2"
    if codec == "VC-1":
        return "VC1"
    if codec == "MPEG-4 Visual":
        return "XVID" if "xvid" in str(track.format_profile or "").lower() else "MPEG4"
    return codec.upper().replace("-", "") if codec else ""


def _encoder(library: str) -> str:
    lowered = library.lower()
    for name in ("x264", "x265"):
        if name in lowered:
            return name
    return library.strip()


def _gpu_name(found: str) -> str:
    lowered = found.lower()
    if "nv" in lowered:
        return "NVENC"
    if "qsv" in lowered or "sync" in lowered:
        return "QSV"
    return "AMF"


def _language(track: Any) -> str:
    return str(track.language or "").lower().split("-")[0]


def _audio(track: Any) -> AudioTrack:
    fmt = str(track.format or "")
    commercial = str(track.commercial_name or track.format_commercial_if_any or "")
    features = str(track.format_additionalfeatures or "")
    atmos = "atmos" in commercial.lower() or "JOC" in features
    codec = {
        "AC-3": "AC3",
        "AAC": "AAC",
        "FLAC": "FLAC",
        "PCM": "LPCM",
        "Opus": "OPUS",
        "MPEG Audio": "MP3",
        "Vorbis": "OGG",
    }.get(fmt, fmt.upper().replace("-", ""))
    if fmt == "E-AC-3":
        codec = "EAC3"
    elif fmt == "DTS":
        codec = "DTSX" if "XLL X" in features else "DTS.HD.MA" if "XLL" in features else "DTS"
    elif fmt.startswith("MLP"):
        codec = "TRUEHD"
    language = str(track.language or "").lower()
    title = str(track.title or "").lower()
    variant = ""
    if language.split("-")[0] in FRENCH_CODES:
        if language.endswith("ca") or "vfq" in title or re.search(r"qu[eé]b|canad", title):
            variant = "VFQ"
        elif language.endswith("be") or "vfb" in title:
            variant = "VFB"
        else:
            variant = "VFF"
    return AudioTrack(
        codec=codec,
        channels=int(track.channel_s or 0),
        language=_language(track),
        variant=variant,
        atmos=atmos,
        bitrate=_kbps(track.bit_rate),
    )


def _subtitle(track: Any) -> SubtitleTrack:
    title = str(track.title or "").lower()
    return SubtitleTrack(
        format=str(track.format or ""),
        language=_language(track),
        forced=str(track.forced or "").lower() == "yes",
        sdh="sdh" in title or "malentendant" in title,
    )


def with_file_name(text: str, name: str) -> str:
    """MediaInfo's text shows where the file is on this computer; c411 gets the name the
    file has in the torrent."""
    return re.sub(
        r"^(Complete name\s*:\s*).*$",
        lambda m: m.group(1) + (name or "").strip(),
        text,
        count=1,
        flags=re.MULTILINE,
    )
