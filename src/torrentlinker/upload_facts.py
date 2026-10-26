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
        "unreadable_audio": [],
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
        if (
            request.category in {2, 3}
            and hasattr(profile, "tags")
            and suffix
            in {
                ".flac",
                ".m4a",
                ".m4b",
                ".wav",
                ".wv",
                ".aif",
                ".aiff",
                ".mp3",
                ".ogg",
                ".wma",
                ".aac",
                ".opus",
                ".ape",
                ".ac3",
                ".dts",
            }
        ):
            tags = profile.tags.get(file.local_path, file.size)
            if tags:
                evidence["audio"].append(
                    {"file": file.local_path, **asdict(tags), "measured_bitrate_kbps": tags.bitrate}
                )
            else:
                evidence["unreadable_audio"].append(
                    {"file": file.local_path, "reason": "Audio metadata unavailable."}
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
    unreadable = evidence.get("unreadable_audio", [])
    if audio or unreadable:
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
        fields["tracks"] = str(len(audio) + len(unreadable))
        if not unreadable and all(row["duration"] > 0 for row in audio):
            fields["duration"] = _clock(sum(row["duration"] for row in audio))
        ordered = [
            *sorted(audio, key=lambda x: (x["track"], x["file"])),
            *[{"file": row["file"], "title": "", "duration": 0} for row in unreadable],
        ]
        fields["tracklist"] = "\n".join(
            f"{index:02}. {row['title'] or Path(row['file']).stem} "
            f"({_clock(row['duration']) if row['duration'] > 0 else 'duration unknown'})"
            for index, row in enumerate(ordered, 1)
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


def prepare_presentation(
    request, form, assets, *, generated_description=False, generated_nfo=False
):
    """One preparation path for preview and saved desktop/web/MCP Local Drafts."""
    from dataclasses import replace

    from torrentlinker.upload_presentation import _normal, _values, update_fields

    form = dict(form)
    evidence = collect(request)
    attached = list(form.get("assets", []))
    if not attached:
        attached = [asset["asset_id"] for asset in assets.extract(request, evidence)]
    selected_pieces, covered_pieces = set(), set()

    def local_name(value):
        path = Path(value)
        if path.is_absolute():
            try:
                return path.relative_to(request.item.save_path).as_posix()
            except ValueError:
                return value
        return path.as_posix()

    for asset_id in attached:
        metadata = assets.describe(asset_id, str(request.item.path))["metadata"]
        if metadata.get("origin") == "model_render":
            selected_pieces.update(local_name(name) for name in metadata.get("selection", []))
            covered_pieces.update(local_name(piece["file"]) for piece in metadata.get("pieces", []))
    evidence["image_coverage"] = {
        "selected": len(selected_pieces),
        "covered": len(covered_pieces),
        "missing": sorted(selected_pieces - covered_pieces),
    }
    form["assets"] = evidence["assets"] = attached
    facts = known_fields(request, evidence)
    description, nfo = request.description, request.nfo
    if request.category in {1, 3}:
        if generated_description:
            description = update_fields(description, {"source": ""})
        if generated_nfo:
            nfo = update_fields(nfo, {"source": ""}, bbcode=False)
    # Explicit owner/research edits survive extraction; show their conflicts instead
    # of silently replacing them. Files/count/codec contradictions still block review.
    declared = form.get("field_provenance", {})
    chosen = _values(description)
    overrides = {
        key
        for key, source in declared.items()
        if source.get("kind") in {"research", "user_supplied"} and chosen.get(key)
    }
    evidence["fields"] = {}
    evidence["conflicting_fields"] = []
    technical = {
        "files",
        "size",
        "format",
        "duration",
        "tracks",
        "codec",
        "bitrate",
        "sample_rate",
        "bit_depth",
        "video_codec",
        "video_bitrate",
        "video_resolution",
        "audio_codec",
        "audio_bitrate",
        "audio_channels",
        "audio_languages",
        "subtitles",
        "subtitle_languages",
        "subtitle_formats",
        "subtitle_types",
    }
    for key, value in facts.items():
        if key in overrides:
            different = _normal(chosen[key]) != _normal(value)
            evidence["fields"][key] = {
                **declared[key],
                "value": chosen[key],
                "extracted_value": value,
                "conflict": different,
            }
            if different:
                evidence["conflicting_fields"].append(
                    {
                        "field": f"description.{key}",
                        "extracted_value": value,
                        "declared_value": chosen[key],
                        "blocks_review": key in technical,
                    }
                )
        else:
            evidence["fields"][key] = {"value": value, "kind": "extracted", "source": "local_files"}
    evidence["fields"].update({key: value for key, value in declared.items() if key not in facts})
    updates = {key: value for key, value in facts.items() if key not in overrides}
    description = update_fields(description, updates)
    origin = form.get("nfo_origin") or ("generated" if generated_nfo else "original")
    if generated_nfo or origin == "generated":
        nfo = update_fields(
            nfo,
            {**updates, **{key: chosen[key] for key in overrides if key in facts}},
            bbcode=False,
        )
    form.update(description=description, nfo=nfo, nfo_origin=origin)
    return replace(request, description=description, nfo=nfo), form, evidence
