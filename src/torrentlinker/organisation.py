"""Organisation's naming: the Jellyfin layout, from a template per organised library (ADR-0029).

A template per library and kind (film, series) names where each video goes:
`Titre (Année) [tmdbid-N]/Titre (Année) [tmdbid-N].ext` for a film, and
`Série (Année)/Saison 01/Série S01E01.ext` for a series. The board (`ranger.py`) uses it to
move and rename each item in one pass.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from guessit import guessit

TOKENS = (
    "{titre}", "{année}", "{tmdbid}", "{résolution}", "{codec}", "{source}", "{langue}",
    "{saison}", "{épisode}", "{groupe}",
)  # fmt: skip
DEFAULTS = {
    "film": "{titre} ({année}) [tmdbid-{tmdbid}]/{titre} ({année}) [tmdbid-{tmdbid}]",
    "series": "{titre} ({année})/Saison {saison}/{titre} S{saison}E{épisode}",
}
SIDECARS = {".srt", ".nfo", ".jpg", ".png", ".vtt", ".ass", ".sub"}
SAMPLE = {
    "film": {"titre": "Dune", "année": "2021", "tmdbid": "438631", "résolution": "1080p",
             "codec": "x265", "source": "BluRay", "langue": "MULTI", "groupe": "GRP",
             "saison": "01", "épisode": "01"},
    "series": {"titre": "Severance", "année": "2022", "tmdbid": "95396", "résolution": "1080p",
               "codec": "x265", "source": "WEB-DL", "langue": "MULTI", "groupe": "GRP",
               "saison": "01", "épisode": "03"},
}  # fmt: skip


def template_error(template: str) -> str:
    unknown = [t for t in re.findall(r"\{[^}]*\}", template) if t not in TOKENS]
    if unknown:
        return f"Unknown token: {', '.join(unknown)}"
    if "{titre}" not in template:
        return "The template must contain {titre}."
    if ".." in template or template.startswith("/") or template.endswith("/"):
        return "Invalid path: no “..”, and no slash at the start or the end."
    if len(template.split("/")) > 3:
        return "Three levels at most."
    return ""


def clean(segment: str) -> str:
    segment = re.sub(r"\s*:\s*", " - ", segment)
    return re.sub(r"\s+", " ", re.sub(r'[<>"\\|?*]', "", segment)).strip(" .")


def fill(template: str, facts: dict[str, str]) -> list[str]:
    """The template's path segments. A bracket group whose token is empty (a film with no
    TMDb id) disappears with it."""
    for token in TOKENS:
        if not facts.get(token[1:-1]):
            template = re.sub(r"\s*\[[^\]]*" + re.escape(token) + r"[^\]]*\]", "", template)
            template = re.sub(r"\s*\([^)]*" + re.escape(token) + r"[^)]*\)", "", template)
    template = re.sub(r"\{[^}]*\}", lambda m: str(facts.get(m.group(0)[1:-1], "")), template)
    return [clean(part) for part in template.split("/")]


def facts_of(body: dict[str, Any], filename: str) -> dict[str, str]:
    """What the tokens say about a video: Médias' own facts, then the file's name."""
    guessed = guessit(filename)
    languages = guessed.get("language") or []
    languages = languages if isinstance(languages, list) else [languages]
    series = bool(body.get("series"))
    season = body.get("season") or guessed.get("season") or 1
    episode = body.get("episode") or guessed.get("episode")
    if not episode:  # "tenjo.tenge.e01m", "oav02": a number guessit misses
        from torrentlinker.library_items import EPISODE

        found = EPISODE.search(Path(filename).stem)
        episode = int(found.group(1)) if found else 1
        if found and re.search(r"o[av]{2}", found.group(0), re.I):
            season = 0  # an OAV is a special: season 0, as Jellyfin files them
    return {
        "titre": str(
            (body.get("series") if series else body.get("title")) or guessed.get("title") or ""
        ),
        "année": str(body.get("year") or guessed.get("year") or ""),
        "tmdbid": str(body.get("tmdb_id") or ""),
        "résolution": str(guessed.get("screen_size") or ""),
        "codec": str(guessed.get("video_codec") or ""),
        "source": str(guessed.get("source") or ""),
        "langue": "MULTI" if any(getattr(x, "alpha3", "") == "mul" for x in languages)
        else "".join(str(x) for x in languages[:1]),
        "saison": f"{int(season):02d}" if str(season).isdigit() else "01",
        "épisode": f"{int(episode):02d}" if str(episode).isdigit() else "01",
        "groupe": str(guessed.get("release_group") or ""),
    }  # fmt: skip


def example(template: str, kind: str) -> str:
    if template_error(template):
        return ""
    return " / ".join(fill(template, SAMPLE[kind])) + ".mkv"


class Organisation:
    """The naming templates, one per organised library and kind."""

    def __init__(self, storage) -> None:
        self.storage = storage

    def template(self, folder: Path, kind: str) -> str:
        return self.storage.templates().get(str(folder), {}).get(kind) or DEFAULTS[kind]
