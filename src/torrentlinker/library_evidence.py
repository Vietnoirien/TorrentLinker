"""Read-only evidence for Library inspection and upload preparation.

Claims are editable metadata, never proof of source, team or authorship.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Callable
from pathlib import Path

from torrentlinker.domain import LocalItem
from torrentlinker.media_info import MediaFacts, read_media

VIDEO_EXTENSIONS = {".mkv", ".m4v", ".mp4", ".avi", ".m2ts", ".ts", ".mov", ".webm"}


def consistency(name: str, facts: MediaFacts, nfo: str = "") -> list[dict[str, str]]:
    rows = []
    claims = [("filename", name), ("embedded-title", facts.title), ("nfo", nfo)]
    video_aliases = {"H264": "AVC", "X264": "AVC", "H265": "HEVC", "X265": "HEVC"}
    audio_aliases = {"DDP": "EAC3", "DD": "AC3", "EAC3": "EAC3", "AC3": "AC3"}
    for source, claim in claims:
        if not claim:
            continue
        values: list[tuple[str, str, str]] = []
        resolutions = set(re.findall(r"(?i)\b(2160p|1080p|720p|480p|576p)\b", claim))
        if len(resolutions) == 1 and facts.width and facts.height:
            expected = next(iter(resolutions)).lower()
            actual = facts.resolution
            if expected != actual and not (actual == "SD" and expected in {"480p", "576p"}):
                values.append(("resolution", expected, actual))
        codecs = set(re.findall(r"(?i)(?<!\w)(H[.]?26[45]|X26[45]|HEVC|AVC|AV1)(?!\w)", claim))
        normalized = {video_aliases.get(c.upper().replace(".", ""), c.upper()) for c in codecs}
        if len(normalized) == 1 and facts.video_codec and facts.video_codec not in normalized:
            values.append(("video-codec", next(iter(normalized)), facts.video_codec))
        audio = re.findall(
            r"(?i)(?<!\w)(E[.-]?AC[.-]?3|AC[.-]?3|DDP|DD|AAC|FLAC|TRUEHD)(?=\d|\W|$)", claim
        )
        expected_audio = {
            audio_aliases.get(re.sub(r"[.-]", "", c.upper()), c.upper()) for c in audio
        }
        observed_audio = {t.codec for t in facts.audio if t.codec}
        if expected_audio and observed_audio and expected_audio.isdisjoint(observed_audio):
            values.append(
                (
                    "audio-codec",
                    ", ".join(sorted(expected_audio)),
                    ", ".join(sorted(observed_audio)),
                )
            )
        # Codec and channels belong to a single track; do not merge unrelated tracks.
        channel_claims = re.findall(
            r"(?i)(?<!\w)(E[.-]?AC[.-]?3|AC[.-]?3|DDP|DD|AAC|FLAC|TRUEHD)"
            r"[ ._-]*([1257])[.]([01])(?!\d)",
            claim,
        )
        for codec, whole, lfe in channel_claims:
            codec = audio_aliases.get(re.sub(r"[.-]", "", codec.upper()), codec.upper())
            channels = int(whole) + int(lfe)
            tracks = [t for t in facts.audio if t.codec == codec and t.channels]
            if tracks and not any(t.channels == channels for t in tracks):
                values.append(
                    (
                        "audio-channels",
                        f"{codec} {channels}",
                        ", ".join(f"{t.codec} {t.channels}" for t in tracks),
                    )
                )
        hdr_claims = [
            (r"(?i)\b(?:DV|DOLBY[ .]VISION)\b", "Dolby Vision", bool(facts.dv_profile)),
            (r"(?i)\bHDR10\+", "HDR10+", facts.hdr10plus),
            (r"(?i)\bHDR10(?!\+|\w)", "HDR10", facts.hdr10 or facts.hdr10plus),
            (r"(?i)\bHLG\b", "HLG", facts.hlg),
            (
                r"(?i)\bHDR\b",
                "HDR",
                bool(facts.hdr10 or facts.hdr10plus or facts.hlg or facts.dv_profile),
            ),
        ]
        observed_hdr = (
            ", ".join(
                label
                for label, present in (
                    ("Dolby Vision", facts.dv_profile),
                    ("HDR10+", facts.hdr10plus),
                    ("HDR10", facts.hdr10),
                    ("HLG", facts.hlg),
                )
                if present
            )
            or "No HDR reported by MediaInfo"
        )
        for pattern, label, present in hdr_claims:
            if re.search(pattern, claim) and not present:
                values.append(("hdr", label, observed_hdr))
        for field, expected, actual in values:
            rows.append(
                dict(
                    file=name,
                    source=source,
                    field=field,
                    claim=expected,
                    observed=actual,
                    confidence="review" if field == "hdr" else "measured",
                )
            )
    if "handbrake" in facts.writing_application.lower():
        rows.append(
            dict(
                file=name,
                source="writing-application",
                field="processing",
                claim="",
                observed=facts.writing_application,
                confidence="hint",
            )
        )
    return rows


def inspect_item(
    item: LocalItem, stop: threading.Event, reader: Callable[[Path], MediaFacts | None] = read_media
) -> dict:
    rows, unreadable = [], []
    for relative in item.files:
        if stop.is_set():
            raise ValueError("Inspection cancelled.")
        path = item.save_path / relative
        if path.suffix.lower() not in VIDEO_EXTENSIONS:
            continue
        facts = reader(path)
        if facts is None:
            unreadable.append(relative)
            continue
        nfo = sidecar_claim(path)
        rows.extend(consistency(relative, facts, nfo))
    return {"observations": rows, "unreadable": unreadable}


def sidecar_claim(path: Path) -> str:
    """Read a bounded adjacent NFO without following links."""
    sidecar = path.with_suffix(".nfo")
    if sidecar.is_file() and not sidecar.is_symlink() and sidecar.stat().st_size <= 256_000:
        return sidecar.read_text(errors="replace")
    return ""
