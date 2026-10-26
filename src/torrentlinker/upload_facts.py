"""Structured, read-only file facts with explicit extraction provenance."""

from __future__ import annotations

import posixpath
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import asdict
from pathlib import Path


def epub_metadata(path):
    result = {"title": [], "author": [], "languages": [], "artwork": []}
    try:
        with zipfile.ZipFile(path) as book:

            def xml(name):
                if book.getinfo(name).file_size > 1_048_576:
                    raise ValueError("EPUB metadata exceeds limit")
                return ET.fromstring(book.read(name))

            root = xml("META-INF/container.xml").find(".//{*}rootfile")
            if root is None:
                return result
            package_path = root.attrib["full-path"]
            package = xml(package_path)
            for target, name in (
                ("title", "title"),
                ("author", "creator"),
                ("languages", "language"),
            ):
                result[target] = [
                    node.text.strip()
                    for node in package.findall(f".//{{http://purl.org/dc/elements/1.1/}}{name}")
                    if node.text and node.text.strip()
                ]
            cover = next(
                (
                    n.get("content")
                    for n in package.findall(".//{*}meta")
                    if n.get("name") == "cover"
                ),
                None,
            )
            for item in package.findall(".//{*}manifest/{*}item"):
                if item.get("id") == cover or "cover-image" in item.get("properties", "").split():
                    name = posixpath.normpath(
                        posixpath.join(posixpath.dirname(package_path), item.get("href", ""))
                    )
                    if book.getinfo(name).file_size <= 8_000_000:
                        result["artwork"].append(name)
    except (OSError, KeyError, ValueError, RuntimeError, zipfile.BadZipFile, ET.ParseError):
        pass
    return result


def collect(request):
    from torrentlinker.upload import PROFILES

    profile = PROFILES[request.category]
    evidence = {
        "file_count": len(request.files),
        "size_bytes": sum(f.size for f in request.files),
        "ebooks": [],
        "audio": [],
        "video": [],
        "inventory": [],
        "provenance": {"kind": "extracted", "source": "local_files"},
        "rip_source": {
            "value": None,
            "kind": "unknown",
            "reason": "Codec and filenames do not establish rip provenance.",
        },
    }
    for file in request.files:
        path = request.item.save_path / file.local_path
        suffix = path.suffix.lower()
        evidence["inventory"].append(
            {"file": file.local_path, "size_bytes": file.size, "format": suffix.removeprefix(".")}
        )
        if request.category == 2 and suffix == ".epub":
            evidence["ebooks"].append(
                {"file": file.local_path, "format": "EPUB", **epub_metadata(path)}
            )
        if request.category in {2, 3} and hasattr(profile, "tags"):
            tags = profile.tags.get(file.local_path, file.size)
            if tags:
                evidence["audio"].append(
                    {"file": file.local_path, **asdict(tags), "measured_bitrate_kbps": tags.bitrate}
                )
        if request.category == 1 and hasattr(profile, "facts"):
            facts = profile.facts.get((file.local_path, file.size))
            if facts:
                row = asdict(facts)
                row.pop("text", None)
                evidence["video"].append({"file": file.local_path, **row})
    return evidence


def known_fields(request, evidence):
    from torrentlinker.upload import human_size
    from torrentlinker.upload_audio import _clock

    fields = {
        "title": request.title,
        "files": str(evidence["file_count"]),
        "size": human_size(evidence["size_bytes"]),
    }

    def common(rows, source, target, suffix=""):
        values = sorted({str(row[source]) for row in rows if row.get(source)})
        if values:
            fields[target] = "; ".join(value + suffix for value in values)

    if request.category == 2 and evidence["ebooks"]:
        books = evidence["ebooks"]
        for source, target in (("author", "author"), ("languages", "language")):
            values = sorted({value for book in books for value in book[source]})
            if values:
                fields[target] = "; ".join(values)
        fields["format"] = "; ".join(sorted({row["format"] for row in evidence["inventory"]}))
    audio = evidence["audio"]
    if audio:
        for source, target, unit in (
            ("artist", "artist", ""),
            ("album", "album", ""),
            ("year", "year", ""),
            ("codec", "codec", ""),
            ("bitrate", "bitrate", " kbps"),
            ("sample_rate", "sample_rate", " Hz"),
            ("bits", "bit_depth", " bits"),
        ):
            common(audio, source, target, unit)
        fields["tracks"] = str(len(audio))
        fields["duration"] = _clock(sum(row["duration"] for row in audio))
        fields["tracklist"] = "\n".join(
            f"{index:02}. {row['title'] or Path(row['file']).stem} ({_clock(row['duration'])})"
            for index, row in enumerate(sorted(audio, key=lambda x: (x["track"], x["file"])), 1)
        )
    videos = evidence["video"]
    if videos:
        for source, target, unit in (
            ("container", "format", ""),
            ("video_codec", "video_codec", ""),
            ("video_bitrate", "video_bitrate", " kbps"),
        ):
            common(videos, source, target, unit)
        fields["duration"] = "; ".join(_clock(row["duration"]) for row in videos)
        fields["video_resolution"] = "; ".join(f"{r['width']}x{r['height']}" for r in videos)
        tracks = [track for row in videos for track in row["audio"]]
        for source, target, unit in (
            ("codec", "audio_codec", ""),
            ("bitrate", "audio_bitrate", " kbps"),
            ("channels", "audio_channels", ""),
            ("language", "audio_languages", ""),
        ):
            if not tracks:
                fields[target] = "Aucun"
            elif all(track.get(source) for track in tracks):
                fields[target] = "; ".join(
                    f"{i}: {r[source]}{unit}" for i, r in enumerate(tracks, 1)
                )
        subtitles = [track for row in videos for track in row["subtitles"]]
        fields["subtitles"] = "Présents" if subtitles else "Aucun"
        if subtitles:
            for source, target in (
                ("format", "subtitle_formats"),
                ("language", "subtitle_languages"),
            ):
                if all(row.get(source) for row in subtitles):
                    fields[target] = "; ".join(
                        f"{i}: {r[source]}" for i, r in enumerate(subtitles, 1)
                    )
            fields["subtitle_types"] = "; ".join(
                f"{i}: {'forced' if r['forced'] else 'SDH' if r['sdh'] else 'full'}"
                for i, r in enumerate(subtitles, 1)
            )
    if request.category == 10:
        fields["format"] = "; ".join(sorted({row["format"] for row in evidence["inventory"]}))
        fields["contents"] = "\n".join(row["file"] for row in evidence["inventory"])
    return fields
