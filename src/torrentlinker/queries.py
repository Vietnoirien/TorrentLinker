"""Query building: turn a Local Item into Indexer search parameters."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from guessit import guessit

from torrentlinker.domain import ContentKind, LocalItem
from torrentlinker.indexer import SearchQuery

MODE_BY_KIND = {
    ContentKind.MOVIE: "movie",
    ContentKind.SERIES: "tvsearch",
    ContentKind.MUSIC: "music",
    ContentKind.EBOOK: "book",
}
IMDB_RE = re.compile(r"\b(tt\d{7,9})\b")
TMDB_RE = re.compile(r"tmdb(?:id)?[-=: ]?(\d+)", re.IGNORECASE)
NFO_MAX_BYTES = 256 * 1024


@dataclass(frozen=True)
class MediaIds:
    imdb: str | None = None  # with its "tt" prefix
    tmdb: str | None = None


def is_single_file(item: LocalItem) -> bool:
    return list(item.files) == [item.path.name]


def name_query(item: LocalItem) -> str:
    name = item.path.stem if is_single_file(item) else item.path.name
    name = re.sub(r"\[[^\]]*\]|\{[^}]*\}|[()]", " ", name)
    name = re.sub(r"[._\-\s]+", " ", name)
    return name.strip()


def find_ids(item: LocalItem) -> MediaIds:
    """IMDb/TMDb ids from the item's name (e.g. `{imdb-tt0211915}`) or its .nfo files."""
    texts = [item.path.name]
    for rel in item.files:
        if rel.lower().endswith(".nfo") and item.files[rel] <= NFO_MAX_BYTES:
            try:
                texts.append((item.save_path / rel).read_text(encoding="utf-8", errors="replace"))
            except OSError:
                pass
    imdb = tmdb = None
    for text in texts:
        if imdb is None and (m := IMDB_RE.search(text)):
            imdb = m.group(1)
        if tmdb is None and (m := TMDB_RE.search(text)):
            tmdb = m.group(1)
    return MediaIds(imdb, tmdb)


def parse_release(item: LocalItem) -> dict[str, Any]:
    name = item.path.name
    name = re.sub(r"\{[^}]*\}", " ", name)  # Radarr/Sonarr id tags confuse guessit
    return dict(guessit(name))


def build_queries(
    item: LocalItem,
    kind: ContentKind,
    categories: tuple[int, ...],
    ids: MediaIds,
    caps_modes: dict[str, set[str]] | None,
    override: str | None = None,
) -> list[SearchQuery]:
    """Searches to try in order: by ID first when possible, then by name."""
    mode = MODE_BY_KIND.get(kind, "search")
    supported = caps_modes if caps_modes is not None else None

    def allows(m: str, param: str) -> bool:
        return supported is None or param in supported.get(m, set())

    if supported is not None and mode not in supported:
        mode = "search"

    season = episode = None
    title = name_query(item)
    if kind in (ContentKind.MOVIE, ContentKind.SERIES):
        info = parse_release(item)
        title = str(info.get("title") or title)
        if kind is ContentKind.MOVIE and info.get("year"):
            title = f"{title} {info['year']}"
        if kind is ContentKind.SERIES:
            season = _single_int(info.get("season"))
            episode = _single_int(info.get("episode"))
    if override:
        title = override

    queries: list[SearchQuery] = []
    s_param = season if allows(mode, "season") else None
    e_param = episode if allows(mode, "ep") else None
    if not override and mode in ("movie", "tvsearch"):
        by_id = None
        if ids.imdb and allows(mode, "imdbid"):
            by_id = {"imdbid": ids.imdb.removeprefix("tt")}  # Torznab wants it without "tt"
        elif ids.tmdb and allows(mode, "tmdbid"):
            by_id = {"tmdbid": ids.tmdb}
        if by_id:
            queries.append(
                SearchQuery(mode=mode, categories=categories, season=s_param, ep=e_param, **by_id)
            )
    if mode == "search":
        s_param = e_param = None
    queries.append(
        SearchQuery(q=title, mode=mode, categories=categories, season=s_param, ep=e_param)
    )
    return queries


def _single_int(value: Any) -> int | None:
    if isinstance(value, list):
        return None  # multi-season / multi-episode packs: search the whole show
    return int(value) if isinstance(value, int) else None


# Newznab standard category ranges; the Indexer's caps say which ids actually exist.
CATEGORY_RANGES: dict[ContentKind, list[range]] = {
    ContentKind.MOVIE: [range(2000, 3000)],
    ContentKind.SERIES: [range(5000, 6000)],
    ContentKind.MUSIC: [range(3000, 4000)],
    ContentKind.EBOOK: [range(7000, 8000)],
    ContentKind.GAME: [range(1000, 2000), range(4050, 4060)],
}


def default_categories(caps_categories: dict[int, str]) -> dict[ContentKind, list[int]]:
    return {
        kind: sorted(c for c in caps_categories for r in CATEGORY_RANGES.get(kind, []) if c in r)
        for kind in ContentKind
    }
