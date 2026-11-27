"""Organisation: rename the library to a Jellyfin layout, one proposal per release (ADR-0029, #211).

A template per Library Folder and kind (films, series) names where each video goes:
`Titre (Année) [tmdbid-N]/Titre (Année) [tmdbid-N].ext` for a film, and
`Série (Année)/Saison 01/Série S01E01.ext` for a series. A proposal is only a preview: the
Owner confirms rows, and each confirmed row becomes rename tasks, so a seeded file is renamed
inside its Torrent Client. A row the client cannot follow is flagged "needs a Link Folder" and
skipped.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from guessit import guessit

from torrentlinker.file_annotations import seeds_under
from torrentlinker.media import VIDEO

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
    episode = body.get("episode") or guessed.get("episode") or 1
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
    """Proposals for the Library Folders, from Médias' items."""

    def __init__(self, storage, media, library_folders, seeds, client_of) -> None:
        self.storage, self.media = storage, media
        self.library_folders, self.seeds, self.client_of = library_folders, seeds, client_of

    def template(self, folder: Path, kind: str) -> str:
        return self.storage.templates().get(str(folder), {}).get(kind) or DEFAULTS[kind]

    def _items(self, client_id: str, folder: Path) -> list[tuple[Path, dict[str, Any]]]:
        prefix = str(folder.absolute()).rstrip("/") + "/"
        with self.media.lock:
            rows = self.media.db.execute(
                "SELECT path, body FROM media_items WHERE client=? AND substr(path, 1, ?) = ?",
                (client_id, len(prefix), prefix),
            ).fetchall()
        found = []
        for row in rows:
            body = json.loads(row["body"])
            if body.get("kind") == "video" and Path(row["path"]).suffix.lower() in VIDEO:
                found.append((Path(row["path"]), body))
        return found

    def folders(self, client_id: str) -> list[dict[str, Any]]:
        """Each Library Folder with its templates, examples and proposals."""
        cards = []
        for entry in self.library_folders():
            folder = Path(entry.path)
            releases = self._releases(client_id, folder)
            kinds = {"movie": ["film"], "series": ["series"]}.get(str(entry.kind.value), None)
            kinds = kinds or sorted({r["kind"] for r in releases}) or ["film"]
            cards.append(
                {
                    "path": str(folder), "name": folder.name,
                    "templates": [
                        {"kind": k, "template": self.template(folder, k), "default": DEFAULTS[k],
                         "error": template_error(self.template(folder, k)),
                         "example": example(self.template(folder, k), k)}
                        for k in kinds
                    ],
                    "rows": [r for r in releases if r["kind"] in kinds],
                }
            )  # fmt: skip
        return cards

    def _releases(self, client_id: str, folder: Path) -> list[dict[str, Any]]:
        tops: dict[str, list[tuple[Path, dict[str, Any]]]] = {}
        for path, body in self._items(client_id, folder):
            tops.setdefault(path.relative_to(folder).parts[0], []).append((path, body))
        seeds = self.seeds(folder)
        return [
            self._release(folder, name, sorted(items, key=lambda x: str(x[0])), seeds)
            for name, items in sorted(tops.items(), key=lambda kv: kv[0].casefold())
        ]

    def _release(self, folder: Path, name: str, items, seeds) -> dict[str, Any]:
        top = folder / name
        series = any(body.get("series") for _, body in items)
        kind = "series" if series else "film"
        template = self.template(folder, kind)
        error = template_error(template)
        maps: list[dict[str, str]] = []
        if not error:
            for index, (path, body) in enumerate(items):
                segments = fill(template, facts_of(body, path.name))
                if len(items) > 1 and not series:
                    segments[-1] += f" - part{index + 1}"
                segments[-1] += path.suffix.lower()
                target = folder.joinpath(*segments)
                maps.append({"from": str(path), "to": str(target)})
            if kind == "film" and len(items) == 1 and top.is_dir():
                maps.extend(self._extras(top, items[0][0], Path(maps[0]["to"])))
        # What is already right needs no rename.
        maps = [m for m in maps if m["from"] != m["to"]]
        seed, problem, link = self._seed(top, maps, seeds)
        return {
            "key": name, "kind": kind, "current": name,
            "title": items[0][1].get("series") or items[0][1].get("title") or name,
            "proposed": (Path(maps[0]["to"]).relative_to(folder).as_posix() if maps else ""),
            "more": max(0, len(items) - 1) if series else 0,
            "same": not maps and not error, "error": error, "maps": maps,
            "seed": seed, "needs_link": link, "problem": problem,
        }  # fmt: skip

    @staticmethod
    def _extras(top: Path, video: Path, target: Path) -> list[dict[str, str]]:
        """A film's subtitles and notes follow it, under its new name."""
        found = []
        for other in sorted(top.rglob("*")):
            if other == video or other.is_dir() or other.suffix.lower() not in SIDECARS:
                continue
            if other.stem.startswith(video.stem):
                suffix = other.name[len(video.stem) :]
                found.append(
                    {"from": str(other), "to": str(target.with_name(target.stem + suffix))}
                )
            else:
                found.append({"from": str(other), "to": str(target.parent / other.name)})
        return found

    def _seed(self, top: Path, maps, seeds) -> tuple[dict[str, Any] | None, str, bool]:
        """The torrent seeding a release, and why or whether it can be renamed."""
        found = seeds_under(top, seeds)
        if not found:
            return None, "", False
        if len(found) > 1:
            return found[0][1], "Several torrents share this folder.", False
        torrent_top, info = found[0]
        client = self.client_of(info["client_id"])
        native = client is not None and getattr(client, "repoint", None) is None
        seed = {"client": info["client"], "hash": info["hash"], "ratio": info["ratio"],
                "native": native}  # fmt: skip
        if info.get("verifying"):
            return seed, "This torrent is being checked.", False
        save = Path(info["save_path"])
        for move in maps:
            new, old = Path(move["to"]), Path(move["from"])
            if not new.is_relative_to(save):
                return seed, "The new name leaves the torrent's own folder.", False
            if not native:
                before, after = old.relative_to(save).parts, new.relative_to(save).parts
                if len(before) != len(after) or before[1:] != after[1:]:
                    return seed, "", True
        return seed, "", False
