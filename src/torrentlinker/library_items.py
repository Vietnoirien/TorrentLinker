"""What a folder holds, as items to range (ADR-0029, #223).

An item is what a person calls one thing: a film (a file, or the folder of its release) or a
series (the folder holding its episodes). A folder that only groups several unrelated films
(a "Science Fiction" folder) is not an item: its content is. An item whose title cannot be read
from its name ("IMG_3310.mov", "movie.mkv") is "to check": it is never moved before the Owner
gives it a title or keeps it as it is.
"""

from __future__ import annotations

import bisect
import functools
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from guessit import guessit

from torrentlinker.media import VIDEO

SAMPLE_RATIO = 0.1  # a video this much smaller than the main one is a sample
GENERIC = re.compile(
    r"^(vid|img|dsc|dscn|pxl|mov|mvi|untitled|movie|video|film|clip|test|capture|"
    r"screenrecording|screen recording|sans titre|new folder|nouveau dossier|"
    r"nouveau document|copie de)\b[\s\d_.()-]*$",
    re.IGNORECASE,
)


@dataclass
class Item:
    """One film or series found in a folder."""

    path: str
    name: str  # relative to the scanned folder, as shown ("film sonia/IMG_3310.mov")
    kind: str  # film | series
    size: int
    videos: list[tuple[str, int]] = field(default_factory=list)
    title: str = ""
    recognised: bool = False
    torrents: list[dict[str, Any]] = field(default_factory=list)  # who seeds it, by hash
    group: str = ""  # the grouping folder it was found in

    def as_json(self) -> dict[str, Any]:
        return {
            "path": self.path, "name": self.name, "kind": self.kind, "size": self.size,
            "title": self.title, "recognised": self.recognised, "group": self.group,
            "torrents": [t["hash"] for t in self.torrents],
        }  # fmt: skip


def _videos(path: str) -> list[tuple[str, int]]:
    """Every video under a folder, never through a symbolic link."""
    found: list[tuple[str, int]] = []
    pending = [path]
    while pending:
        try:
            with os.scandir(pending.pop()) as entries:
                for entry in entries:
                    if entry.name.startswith("."):
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        pending.append(entry.path)
                    elif (
                        entry.is_file(follow_symlinks=False)
                        and Path(entry.name).suffix.lower() in VIDEO
                    ):
                        found.append((entry.path, entry.stat(follow_symlinks=False).st_size))
        except OSError:
            continue
    return sorted(found)


def _main(videos: list[tuple[str, int]]) -> list[tuple[str, int]]:
    """The videos that are not samples of the biggest one."""
    biggest = max(size for _, size in videos)
    return [
        v for v in videos
        if v[1] >= biggest * SAMPLE_RATIO and "sample" not in Path(v[0]).stem.lower()
    ]  # fmt: skip


# One film cut in parts: "CD1.avi", "Film.Disc2.mkv", "partie 3".
PART = re.compile(
    r"(?:^|[ ._-])(?:cd|disc|disque|dvd|part|partie|pt)[ ._-]?(\d{1,2})(?=$|[ ._-])", re.I
)


def part_number(name: str) -> int | None:
    found = PART.search(Path(name).stem)
    return int(found.group(1)) if found else None


# What only a series' release spells out: S01E02, S01, 1x02, "Saison 2", "Season 2", an
# Intégrale. guessit alone reads "1080" as S10E80, "[40-45]" or "20 Years" as episodes.
SERIES_MARK = re.compile(
    r"(?:^|[ ._\[(-])(?:S\d{1,2}(?:[ ._-]?E\d{1,3})?|\d{1,2}x\d{2,3}|(?:saison|season|series)"
    r"[ ._-]?\d{1,2}|int[ée]grale|complete[ ._-]series)(?=$|[ ._\])-])",
    re.I,
)
# An episode's number in a name guessit misses: "tenjo.tenge.e01m", "oav02", "Session 05".
# Never the word "Episode" alone: films carry it ("Episode 50", "Star Wars Episode 6").
EPISODE = re.compile(
    r"(?:^|[ ._-])(?:s\d{1,2})?(?:e|ep|oav|ova|session)[ ._-]?#?(\d{1,3})"
    r"(?=[a-z]?(?:$|[ ._-]))",
    re.I,
)


@functools.lru_cache(maxsize=4096)
def embedded_title(path: str) -> str:
    """The title a video carries inside it ("Cowboy Bebop Collector - Session #12"): what
    tells an episode when its file name was lost. Empty when MediaInfo cannot read it."""
    try:
        from pymediainfo import MediaInfo

        general = MediaInfo.parse(path).general_tracks
    except Exception:  # noqa: BLE001 - no MediaInfo, or an unreadable file: nothing to tell
        return ""
    return str((general[0].title or general[0].movie_name or "") if general else "")


def episode_number(path: str) -> int | None:
    """An episode's number from its name, else from the title the video carries."""
    for text in (Path(path).stem, embedded_title(path)):
        found = EPISODE.search(text)
        if found:
            return int(found.group(1))
    return None


# A season folder named only by its number, inside a series' folder.
SEASON_ONLY = re.compile(r"^(?:saison|season|s)[ ._-]?\d{1,2}$", re.I)


def _is_release(path: str, videos: list[tuple[str, int]]) -> bool:
    """A folder that is one item (a film and its extras, a film cut in parts, a series or one
    of its seasons) rather than a folder that groups several."""
    name = Path(path).name
    main = _main(videos)
    if len(main) <= 1:
        return True
    # Parts lie side by side in the film's own folder; a folder above them groups films.
    if all(part_number(p) is not None and Path(p).parent.name == name for p, _ in main):
        return True
    # A folder holding releases of their own ("Futurama S01", "MONTY…-Saison 2-…") groups
    # them; only bare "Saison 2" folders belong to the series around them.
    depths = [Path(p).relative_to(path).parts for p, _ in main]
    inner = {parts[0] for parts in depths if len(parts) > 1}
    if any(SERIES_MARK.search(f" {sub}") and not SEASON_ONLY.match(sub) for sub in inner):
        return False
    # Files that each carry an episode number side by side are one series' episodes.
    if not inner and all(EPISODE.search(Path(p).stem) for p, _ in main):
        return True
    guesses = [guessit(Path(p).name) for p, _ in main]
    if all(g.get("type") == "episode" for g in guesses):
        # Episodes named after themselves ("Saison 03 - Episode 01 - La Voiture Garoute") in a
        # folder that names the season are that season, whatever their titles.
        if SERIES_MARK.search(f" {name}") and not inner:
            return True
        return len({str(g.get("title", "")).casefold() for g in guesses}) == 1
    return False


def kind_of(path: str, videos: list[tuple[str, int]], series_folder: bool = False) -> str:
    """A film, or a series: in a folder of series guessit's word is enough; elsewhere the
    name must also spell out a season or an episode."""
    main = _main(videos) if videos else []
    first = Path(main[0][0]).name if main else Path(path).name
    named = f"{Path(path).name}/{first}" if main and Path(path).is_dir() else first
    guessed = guessit(named)
    marked = any(SERIES_MARK.search(Path(part).stem) for part in named.split("/"))
    numbered = (len(main) > 1 or bool(main and EPISODE.search(Path(main[0][0]).stem))) and all(
        episode_number(p) is not None for p, _ in main
    )
    episode = guessed.get("type") == "episode" and (marked or series_folder)
    return "series" if episode or numbered else "film"


def readable(name: str, guessed: dict[str, Any]) -> bool:
    """Whether a name tells which film or series it is."""
    title = str(guessed.get("title") or "").strip()
    plain = re.sub(r"[._]+", " ", Path(name).stem if Path(name).suffix.lower() in VIDEO else name)
    if len(re.findall(r"[^\W\d_]", title)) < 2 or GENERIC.match(plain.strip()):
        return False
    if PART.fullmatch(" " + plain.strip()):  # "CD1" names a part, never a film
        return False
    technical = any(
        guessed.get(k)
        for k in ("year", "screen_size", "source", "video_codec", "release_group", "season")
    )
    # A short mix of letters and digits with nothing else ("a8f3k2") is a machine's name.
    if not technical and re.fullmatch(r"[a-z0-9]{4,10}", title, re.IGNORECASE):
        return not (re.search(r"\d", title) and re.search(r"[a-z]", title, re.IGNORECASE))
    return True


def fixed_kind(name: str) -> str:
    """A name the Owner gave a title to is a film, unless it spells out a season and an episode
    (S01E02): "IMG_3310" must not become the 33rd season."""
    return "series" if re.search(r"\bS\d{1,2}[ ._-]?E\d{1,3}\b", name, re.IGNORECASE) else "film"


def _item(path: str, base: str, videos, bodies, titles, series_folder: bool = False) -> Item:
    kind = fixed_kind(Path(path).name) if path in titles else kind_of(path, videos, series_folder)
    main = _main(videos)
    files = [Path(p) for p, _ in main] or [Path(path)]
    guessed = guessit(
        f"{Path(path).name}/{files[0].name}" if Path(path).is_dir() else files[0].name
    )
    body = next((bodies[str(f)] for f in files if str(f) in bodies), None)
    fixed = titles.get(path, "")
    known = body and (body.get("series") if kind == "series" else body.get("title"))
    # A series' folder names it: its episodes may each carry their own title.
    named = (
        guessit(Path(path).name).get("title") if kind == "series" and Path(path).is_dir() else ""
    )
    guessed_title = str(guessed.get("title") or "")
    # "1 - La Grande Aventure de Bender", "1 – …": a number in a list, then the title.
    numbered = re.match(r"^\s*\d{1,3}\s*[-–]\s+(\S.*)$", files[0].stem)
    if guessed_title.isdigit() or (numbered and guessed_title.startswith(files[0].stem[:2])):
        stem = numbered.group(1) if numbered else files[0].stem
        guessed_title = str(guessit(stem).get("title") or stem)
    title = fixed or str(known or "") or str(named or guessed_title)
    if kind == "series" and not (fixed or known):
        # "tenjo tenge e01m", "Cowboy Bebop Session": the series' name stops at the episode.
        title = EPISODE.split(f" {title}", maxsplit=1)[0].strip() or title
        title = re.sub(r"\s+(?:session|episode|ep)$", "", title, flags=re.I) or title
    folder_guess = guessit(Path(path).name) if Path(path).is_dir() else guessed
    ok = (
        bool(fixed or known)
        or readable(Path(path).name, folder_guess)
        or readable(files[0].name, guessit(files[0].name))
    )
    relative = Path(path).relative_to(base).as_posix()
    group = relative.split("/")[0] if "/" in relative else ""
    return Item(path, relative, kind, sum(s for _, s in videos), videos, title, ok, group=group)


def one(path: Path, bodies=None, titles=None, series_folder: bool = False) -> Item | None:
    """The item at a path (a video file, or a folder holding one film or one series)."""
    bodies, titles = bodies or {}, titles or {}
    if path.is_dir():
        videos = _videos(str(path))
    else:
        try:
            videos = [(str(path), path.stat().st_size)] if path.suffix.lower() in VIDEO else []
        except OSError:
            videos = []
    if not videos:
        return None
    return _item(str(path), str(path.parent), videos, bodies, titles, series_folder)


def discover(
    folder: Path,
    bodies: dict[str, dict[str, Any]] | None = None,
    titles: dict[str, str] | None = None,
    *,
    base: str = "",
    cancelled=lambda: False,
    series_folder: bool = False,
) -> list[Item]:
    """The items under a folder: a video file, a folder holding one film (or one series), and
    what a grouping folder holds."""
    bodies, titles, base = bodies or {}, titles or {}, base or str(folder)
    items: list[Item] = []
    try:
        entries = sorted(os.scandir(folder), key=lambda e: e.name.casefold())
    except OSError:
        return items
    for entry in entries:
        if cancelled() or entry.name.startswith("."):
            continue
        if entry.is_file(follow_symlinks=False):
            if Path(entry.name).suffix.lower() in VIDEO:
                size = entry.stat(follow_symlinks=False).st_size
                items.append(
                    _item(entry.path, base, [(entry.path, size)], bodies, titles, series_folder)
                )
        elif entry.is_dir(follow_symlinks=False):
            videos = _videos(entry.path)
            if not videos:
                continue
            if _is_release(entry.path, videos):
                items.append(_item(entry.path, base, videos, bodies, titles, series_folder))
            else:
                items.extend(
                    discover(
                        Path(entry.path),
                        bodies,
                        titles,
                        base=base,
                        cancelled=cancelled,
                        series_folder=series_folder,
                    )  # fmt: skip
                )
    return items


class SeedIndex:
    """The torrents seeding a path, looked up fast: a path is related to a torrent's content
    when it is that content, inside it or holds it."""

    def __init__(self, seeds: list[tuple[Path, dict[str, Any]]]) -> None:
        self.by_top: dict[str, list[dict[str, Any]]] = {}
        for top, info in seeds:
            self.by_top.setdefault(str(top), []).append(info)
        self.sorted = sorted(self.by_top)

    def under(self, path: str) -> list[dict[str, Any]]:
        found: dict[str, dict[str, Any]] = {}
        for candidate in (path, *map(str, Path(path).parents)):
            for info in self.by_top.get(candidate, []):
                found[info["hash"]] = info
        prefix = path.rstrip("/") + "/"
        at = bisect.bisect_left(self.sorted, prefix)
        while at < len(self.sorted) and self.sorted[at].startswith(prefix):
            for info in self.by_top[self.sorted[at]]:
                found[info["hash"]] = info
            at += 1
        return list(found.values())
