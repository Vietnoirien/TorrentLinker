"""Category presentation contracts shared by preview, cards and the final send.

Descriptions remain editable BBCode. Labelled technical facts and a synopsis section
make completeness deterministic, without trusting an LLM's assertion of readiness.
This is a completeness check, not a guarantee of tracker acceptance or factual truth.
"""

from __future__ import annotations

import html
import re
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from torrentlinker.upload import UploadRequest

from torrentlinker.assistant.images import image_url

SOURCE = "docs/research/upload-rules.md (c411 rules captured 2026-10-22)"
# Stable field IDs are returned to tools; labels also work in the existing BBCode editors.
FIELDS = {
    "title": ("Titre", "Title|Nom|Name"),
    "files": ("Fichiers", "Files|File count|Nombre de fichiers"),
    "size": ("Taille totale", "Total size|Size|Taille"),
    "author": ("Auteur", "Author|Auteurs"),
    "format": ("Format", "Formats|Conteneur|Container"),
    "language": ("Langue", "Language|Langues|Languages"),
    "duration": ("Durée", "Duration|Total duration"),
    "video_codec": ("Codec vidéo", "Video codec"),
    "video_bitrate": ("Débit vidéo", "Video bitrate"),
    "video_resolution": ("Résolution vidéo", "Video resolution"),
    "audio_codec": ("Codecs audio", "Audio codecs"),
    "audio_bitrate": ("Débits audio", "Audio bitrates"),
    "audio_channels": ("Canaux audio", "Audio channels"),
    "audio_languages": ("Langues audio", "Audio languages"),
    "audio": ("Audio", "Audio tracks|Pistes audio"),
    "subtitles": ("Sous-titres", "Subtitles"),
    "subtitle_formats": ("Formats des sous-titres", "Subtitle formats"),
    "subtitle_types": ("Types des sous-titres", "Subtitle types"),
    "subtitle_languages": ("Langues des sous-titres", "Subtitle languages"),
    "source": ("Source", ""),
    "platform": ("Plateforme VOD", "VOD platform"),
    "artist": ("Artiste", "Artist|Interprète"),
    "album": ("Album", "Émission|Programme|Program"),
    "year": ("Année", "Year|Date"),
    "tracks": ("Pistes", "Tracks|Track count"),
    "tracklist": ("Liste des pistes", "Tracklist|Chapitres|Chapters"),
    "codec": ("Codec", "Audio codec"),
    "bitrate": ("Débit", "Bitrate"),
    "sample_rate": ("Fréquence", "Sample rate|Fréquence d'échantillonnage"),
    "bit_depth": ("Profondeur", "Bit depth|Profondeur de bits"),
    "catalogue_number": ("Numéro de catalogue", "Catalogue number"),
    "release_link": ("Discogs / MusicBrainz", "Release link"),
    "install_size": ("Taille installée", "Install size|Installation size"),
    "version": ("Version", ""),
    "os": ("Système", "OS|Platform|Plateforme|Console"),
    "activation": ("Activation", "Crack|Firmware|Loader"),
    "requirements": ("Configuration requise", "System requirements|Configuration"),
    "installation": ("Installation", "Instructions d'installation|Install instructions"),
    "region": ("Région", "Region|Zone"),
    "resolution": ("Résolution des images", "Image resolution|Résolution moyenne"),
    "contents": ("Contenu", "Contents|File list|Liste des fichiers"),
    "narrator": ("Narrateur", "Narrator|Interprète"),
}
COMMON = ("title", "files", "size")
CATEGORY_FIELDS = {
    1: (
        "format",
        "duration",
        "source",
        "video_codec",
        "video_bitrate",
        "video_resolution",
        "audio_codec",
        "audio_bitrate",
        "audio_channels",
        "audio_languages",
        "subtitles",
    ),
    2: ("author", "format", "language"),
    3: (
        "artist",
        "album",
        "year",
        "source",
        "codec",
        "bitrate",
        "sample_rate",
        "tracks",
        "tracklist",
    ),
    4: (
        "version",
        "os",
        "year",
        "language",
        "region",
        "install_size",
        "activation",
        "requirements",
        "installation",
    ),
    5: (
        "version",
        "os",
        "year",
        "language",
        "region",
        "install_size",
        "activation",
        "requirements",
        "installation",
    ),
    6: ("version", "os", "language", "region", "installation"),
    7: (
        "version",
        "os",
        "year",
        "language",
        "region",
        "install_size",
        "activation",
        "requirements",
        "installation",
    ),
    10: ("format",),
}
PLACEHOLDERS = {
    "",
    "?",
    "-",
    "...",
    "…",
    "todo",
    "tbd",
    "unknown",
    "inconnu",
    "inconnue",
    "a completer",
    "a renseigner",
    "a verifier",
    "non renseigne",
    "non disponible",
    "n/a",
    "na",
    "none",
    "null",
    "placeholder",
}


def _normal(value: str) -> str:
    return " ".join(
        "".join(
            c
            for c in unicodedata.normalize("NFKD", value.casefold())
            if not unicodedata.combining(c)
        ).split()
    ).strip(" .:")


def _plain(value: str) -> str:
    value = re.sub(r"\[img(?:=[^]]*)?].*?\[/img]", "", value, flags=re.I | re.S)
    return html.unescape(re.sub(r"\[/?[a-z*][^]]*]|<[^>]*>", "", value, flags=re.I)).strip()


def _filled(value: str) -> bool:
    normalized = _normal(_plain(value))
    return normalized not in PLACEHOLDERS and not re.search(
        r"\b(todo|tbd|a completer|a renseigner)\b|\{[^}]+}|<[^>]+>", normalized
    )


def _values(description: str) -> dict[str, str]:
    aliases = {
        _normal(label): key
        for key, (name, others) in FIELDS.items()
        for label in (key, name, *others.split("|"))
        if label
    }
    result: dict[str, str] = {}
    for line in _plain(description).splitlines():
        label, sep, value = line.partition(":")
        key = aliases.get(_normal(label))
        if sep and key and _filled(value):
            result[key] = value.strip()
    for key, names in (
        ("synopsis", "Présentation|Synopsis|Description"),
        ("tracklist", "Liste des pistes|Tracklist|Chapitres"),
        ("contents", "Contenu|Contents|Liste des fichiers"),
    ):
        section = re.search(
            rf"\[h[1-6]](?:{names})\[/h[1-6]](.*?)(?=\[h[1-6]]|\Z)",
            description,
            re.I | re.S,
        ) or re.search(rf"\[spoiler=(?:{names})](.*?)\[/spoiler]", description, re.I | re.S)
        if section and _filled(section[1]):
            body = _plain(section[1])
            if key != "synopsis" or any(
                _filled(line) and _normal(line.partition(":")[0]) not in aliases
                for line in body.splitlines()
            ):
                result[key] = body
    lines = description.splitlines()
    for index, line in enumerate(lines):
        label, sep, value = _plain(line).partition(":")
        key = aliases.get(_normal(label))
        if not sep or key not in {"tracklist", "contents", "installation"}:
            continue
        section_lines = [value] if value.strip() else []
        for following in lines[index + 1 :]:
            if re.search(r"\[(?:h[1-6]|spoiler)[=\]]", following, re.I):
                break
            following = _plain(following)
            if ":" in following and _normal(following.partition(":")[0]) in aliases:
                break
            section_lines.append(following)
        text = "\n".join(section_lines).strip()
        if _filled(text) and not re.fullmatch(r"[\d\s.]+", text):
            if len(text) > len(result.get(key, "")):
                result[key] = text
    heading = re.search(r"\[h2](.*?)\[/h2]", description, re.I | re.S)
    if heading and _filled(heading[1]):
        result.setdefault("title", _plain(heading[1]))
    return result


def requirements(category: int, subcategory: int = 0, description: str = "") -> dict[str, Any]:
    from torrentlinker.upload import PROFILES

    if category not in CATEGORY_FIELDS:
        raise ValueError(
            "Use upload IDs, not Catalogue IDs: 1 Video, 2 Ebook, 3 Audio, 4 Apps, "
            "5 Games, 6 Emulation, 7 GPS, 10 3D. Call get_upload_requirements() to list them."
        )
    if subcategory and subcategory not in {s.id for s in PROFILES[category].subcategories}:
        raise ValueError("Choose a subcategory belonging to this Upload Category.")
    keys = [*COMMON, *CATEGORY_FIELDS[category]]
    values = _values(description)
    if (
        category == 1
        and values.get("subtitles")
        and _normal(values["subtitles"])
        not in {"aucun", "aucune", "no subtitles", "sans sous-titres"}
    ):
        keys += ["subtitle_formats", "subtitle_types", "subtitle_languages"]
    if category == 1 and "web" in values.get("source", "").casefold():
        keys.append("platform")
    if category == 2 and subcategory == 11:
        keys += ["narrator", "codec", "bitrate", "duration", "tracklist"]
    if category == 2 and re.search(r"\b(cbr|cbz|jpg|jpeg|png)\b", values.get("format", ""), re.I):
        keys.append("resolution")
    if category == 3 and re.search(
        r"\b(flac|alac|wav|wv|aif|aiff|lossless)\b", values.get("codec", ""), re.I
    ):
        keys.append("bit_depth")
    if category == 3 and re.search(r"\bcd\b", values.get("source", ""), re.I):
        keys += ["catalogue_number", "release_link"]
    if (
        category == 2
        and values.get("files", "1").strip().isdigit()
        and int(values.get("files", "1")) > 1
    ) or (category == 10 and subcategory == 53):
        keys.append("contents")
    fields = [{"id": key, "label": FIELDS[key][0], "path": f"description.{key}"} for key in keys]
    template = (
        "[center][img]IMAGE_URL[/img][/center]\n[h3]Présentation[/h3]\n\n[h3]Informations[/h3]\n"
    )
    template += "\n".join(f"[b]{field['label']} :[/b] " for field in fields)
    return {
        "category": category,
        "subcategory": subcategory,
        "fields": fields,
        "template": template,
        "nfo_template": "\n".join(
            f"{f['label']} : "
            for f in fields
            if f["id"] not in {"platform", "catalogue_number", "release_link"}
        ),
        "source": SOURCE,
        "instructions": "Fill Présentation with a synopsis and each labelled field with "
        "verified facts. "
        "Keep these labels in the BBCode. Unknowns and placeholders are "
        "incomplete. State Aucun explicitly "
        "only when a field truly does not apply (for example no "
        "subtitles). Never invent technical facts. "
        "Re-run upload-preview after editing for conditional fields. A "
        "hosted image and NFO are required.",
        "field_help": {
            "audio_codec": "List each audio track, using the same track numbering for codecs,"
            " bitrates, channels and languages.",
            "subtitles": "List every track with format, full/forced/SDH type and language; "
            "say Aucun if absent.",
            "tracklist": "Full track/chapter list with individual durations.",
            "installation": "French instructions; explain if portable and no installation is "
            "needed.",
        },
        "conditional_fields": {
            "video WEB source": ["platform"],
            "Ebook audiobook": ["narrator", "codec", "bitrate", "duration", "tracklist"],
            "Ebook image formats": ["resolution"],
            "Ebook pack": ["contents"],
            "lossless Audio": ["bit_depth"],
            "CD Audio": ["catalogue_number", "release_link"],
        },
    }


def assess(form: dict, evidence: dict | None = None) -> dict[str, Any]:
    """Recompute from content every time; never accept a saved 'reviewed' flag as evidence."""
    missing: list[dict[str, str]] = []

    def add(field: str, message: str):
        missing.append({"field": field, "message": message})

    category, subcategory = form.get("category") or 0, form.get("subcategory") or 0
    description = form.get("description") or ""
    try:
        contract = requirements(category, subcategory, description)
    except ValueError as error:
        return {
            "status": "incomplete",
            "missing_fields": [{"field": "category", "message": str(error)}],
        }
    values = _values(description)
    nfo = form.get("nfo") or ""
    nfo_values = _values(nfo)
    if category == 1:
        nfo_values.update(media_nfo_values(nfo))
    # Preserve original NFOs. A release header can supply the title; the remaining
    # facts use stable labels or recognized original MediaInfo sections.
    if _filled(form.get("title") or "") and form["title"] in nfo:
        nfo_values.setdefault("title", form["title"])
    if _filled(nfo):
        for field in contract["fields"]:
            if field["id"] not in {
                "platform",
                "catalogue_number",
                "release_link",
            } and not nfo_values.get(field["id"]):
                add(
                    f"nfo.{field['id']}",
                    f"NFO field missing: {field['label']}. "
                    f"For a generated NFO use '{field['label']} : value'. "
                    "Keep original release NFOs unaltered; obtain a complete original NFO.",
                )
    if not _filled(form.get("title") or ""):
        add("title", "Add the release title.")
    if not _filled(form.get("nfo") or ""):
        add("nfo", "Add the NFO describing these exact files.")
    artwork = re.findall(r"\[img(?:=[^]]*)?](.*?)\[/img]", description, re.I | re.S)
    if not any(image_url(url.strip()) for url in artwork):
        add(
            "description.image",
            "Add a public HTTP(S) cover/image inside the description: [img]URL[/img].",
        )
    if not values.get("synopsis"):
        add(
            "description.synopsis",
            "Fill the [h3]Présentation[/h3] section with a synopsis before [h3]Informations[/h3].",
        )
    for field in contract["fields"]:
        if not values.get(field["id"]):
            add(
                field["path"],
                f"Fill '{field['label']}' in the description: [b]{field['label']} :[/b] value.",
            )
    if (
        category == 2
        and values.get("language")
        and _normal(values["language"])
        not in {
            "fr",
            "fra",
            "fre",
            "french",
            "francais",
            "francais (fr)",
        }
    ):
        add(
            "description.language",
            "Ebooks require French content. Verify the file language; do not "
            "relabel foreign content.",
        )
    for prefix, facts in (("description", values), ("nfo", nfo_values)):
        if facts.get("tracklist"):
            for index, row in enumerate(facts["tracklist"].splitlines(), 1):
                if row.strip() and not re.search(
                    r"\b\d{1,3}:\d{2}(?::\d{2})?\b|\b\d+(?:[.,]\d+)?\s*(?:s|sec|seconds?|secondes?|min)\b",
                    row,
                    re.I,
                ):
                    add(
                        f"{prefix}.tracklist[{index}].duration",
                        "Add the duration of each track/chapter, for example 01. Title (03:42).",
                    )
    if evidence:
        if values.get("files") and values["files"].strip() != str(evidence["file_count"]):
            add("description.files", f"Use the actual file count: {evidence['file_count']}.")
        if category == 2:
            for file in evidence.get("ebooks", []):
                if file["languages"] and any(
                    lang.split("-")[0].lower() not in {"fr", "fra", "fre"}
                    for lang in file["languages"]
                ):
                    add(
                        "description.language",
                        f"{file['file']}: EPUB metadata declares {', '.join(file['languages'])}. "
                        "French content is required. Choose an eligible file, do not relabel it.",
                    )
    return {
        "status": "incomplete" if missing else "complete",
        "missing_fields": missing,
        "requirements": contract,
        "scope": "Presentation completeness only; category refusals and tracker "
        "review still apply.",
    }


def require_complete(form: dict, evidence: dict | None = None) -> None:
    result = assess(form, evidence)
    if result["missing_fields"]:
        raise ValueError(
            "Upload presentation incomplete. "
            + " ".join(
                f"{field['field']}: {field['message']}" for field in result["missing_fields"]
            )
        )


def request_form(request: UploadRequest) -> dict:
    return dict(
        category=request.category,
        subcategory=request.subcategory,
        title=request.title,
        description=request.description,
        nfo=request.nfo,
    )


def file_evidence(request: UploadRequest) -> dict:
    """Read bounded EPUB metadata; no network, extraction, or file mutation."""
    ebooks = []
    if request.category == 2:
        for file in request.files:
            path = request.item.save_path / file.local_path
            if path.suffix.lower() == ".epub":
                ebooks.append({"file": file.local_path, "languages": epub_languages(path)})
    return {
        "file_count": len(request.files),
        "size_bytes": sum(f.size for f in request.files),
        "ebooks": ebooks,
    }


def epub_languages(path: Path) -> list[str]:
    try:
        with zipfile.ZipFile(path) as book:

            def read_xml(name):
                if book.getinfo(name).file_size > 1024 * 1024:
                    raise ValueError("EPUB metadata too large")
                return ET.fromstring(book.read(name))

            container = read_xml("META-INF/container.xml")
            rootfile = container.find(".//{*}rootfile")
            if rootfile is None:
                return []
            package = read_xml(rootfile.attrib["full-path"])
            return sorted(
                {
                    node.text.strip()
                    for node in package.findall(".//{http://purl.org/dc/elements/1.1/}language")
                    if node.text and node.text.strip()
                }
            )
    except (OSError, KeyError, ValueError, RuntimeError, zipfile.BadZipFile, ET.ParseError):
        return []


def extend_template(category: int, subcategory: int, description: str) -> str:
    """Keep detected facts and expose missing labels when resetting an editor template."""
    contract = requirements(category, subcategory, description)
    labels = {_normal(line.partition(":")[0]) for line in _plain(description).splitlines()}
    for field in contract["fields"]:
        key = field["id"]
        name, others = FIELDS[key]
        if not labels.intersection(_normal(x) for x in (key, name, *others.split("|")) if x):
            description += f"\n[b]{name} :[/b] "
    return description


def media_nfo_values(nfo: str) -> dict[str, str]:
    """Recognize MediaInfo text without rewriting a release's original NFO."""
    blocks: dict[str, list[dict[str, str]]] = {}
    current: dict[str, str] | None = None
    for line in nfo.splitlines():
        header = re.fullmatch(r"(General|Video|Audio|Text)(?: #?\d+)?", line.strip(), re.I)
        if header:
            current = {}
            blocks.setdefault(header[1].lower(), []).append(current)
        elif current is not None:
            key, sep, value = line.partition(":")
            if sep and _filled(value):
                current[_normal(key)] = value.strip()
    if not blocks.get("general") or not blocks.get("video"):
        return {}
    result = {}
    general = blocks["general"][0]
    for target, source in (("format", "format"), ("duration", "duration"), ("size", "file size")):
        if general.get(source):
            result[target] = general[source]
    if source_match := re.search(
        r"\b(WEB(?:[ .-]?(?:DL|RIP))?|BluRay|DVD(?:Rip)?|HDTV)\b", nfo, re.I
    ):
        result["source"] = source_match[1]
    result["files"] = _values(nfo).get("files", str(len(blocks["general"])))
    for group, mappings in (
        (
            "video",
            {
                "video_codec": ("format",),
                "video_bitrate": ("bit rate",),
                "video_resolution": ("width", "height"),
            },
        ),
        (
            "audio",
            {
                "audio_codec": ("format",),
                "audio_bitrate": ("bit rate",),
                "audio_channels": ("channel(s)",),
                "audio_languages": ("language",),
            },
        ),
        (
            "text",
            {
                "subtitle_formats": ("format",),
                "subtitle_languages": ("language",),
                "subtitle_types": ("forced",),
            },
        ),
    ):
        tracks = blocks.get(group, [])
        for target, keys in mappings.items():
            if tracks and all(all(track.get(key) for key in keys) for track in tracks):
                result[target] = "; ".join(
                    " / ".join(track[key] for key in keys) for track in tracks
                )
            elif not tracks and group == "audio":
                result[target] = "Aucun"
    result["subtitles"] = "Présents" if blocks.get("text") else "Aucun"
    return result
