"""Genres of a feed release, as TMDb genre ids, for the RSS genre filter.

A genre is held by its TMDb id, which is the same in every language. It comes from one of two
verified sources and from nothing else (never a title, tag or description):

- c411: the detail's `media.genres` names, mapped to ids through TMDb's French genre list;
  a name the list does not know is not guessed, TMDb's own genres of the detail `tmdbId` stand in.
- tr4ker: the TMDb id of the Torznab `tmdbid` attr or of the native detail (read through the
  companion, as Search does), then TMDb's genres of that id.

A release with neither is `unknown` for the genre: it never passes and never fails a rule.
TMDb answers are cached like the Age Ratings (`media_ratings`): one key per title, asked again a
week later when TMDb gave nothing, only with a TMDb key.
"""

from __future__ import annotations

import json
import re
import threading
import time
import unicodedata
from collections.abc import Callable
from typing import Any

from torrentlinker.indexer import Candidate
from torrentlinker.media_ratings import TMDB_RETRY, default_tmdb

LIST_REFRESH = 30 * 86400  # TMDb's genre lists change rarely: asked again after a month
ERROR_RETRY = 3600  # a release whose source could not be read is asked again an hour later

# TMDb's genre lists (film and series merged by id), used when TMDb cannot be reached.
# (id, French name, English name); TMDb's series-only genres keep its English labels.
FALLBACK_GENRES: list[tuple[int, str, str]] = [
    (28, "Action", "Action"),
    (12, "Aventure", "Adventure"),
    (16, "Animation", "Animation"),
    (35, "Comédie", "Comedy"),
    (80, "Crime", "Crime"),
    (99, "Documentaire", "Documentary"),
    (18, "Drame", "Drama"),
    (10751, "Familial", "Family"),
    (14, "Fantastique", "Fantasy"),
    (36, "Histoire", "History"),
    (27, "Horreur", "Horror"),
    (10402, "Musique", "Music"),
    (9648, "Mystère", "Mystery"),
    (10749, "Romance", "Romance"),
    (878, "Science-Fiction", "Science Fiction"),
    (10770, "Téléfilm", "TV Movie"),
    (53, "Thriller", "Thriller"),
    (10752, "Guerre", "War"),
    (37, "Western", "Western"),
    (10759, "Action & Adventure", "Action & Adventure"),
    (10762, "Kids", "Kids"),
    (10763, "News", "News"),
    (10764, "Reality", "Reality"),
    (10765, "Sci-Fi & Fantasy", "Sci-Fi & Fantasy"),
    (10766, "Soap", "Soap"),
    (10767, "Talk", "Talk"),
    (10768, "War & Politics", "War & Politics"),
]


class GenreCache:
    """The cache table of the feed database (key -> JSON), like Age Ratings' `media_options`."""

    def __init__(self, db: Any, lock: threading.RLock):
        self.db, self.lock = db, lock
        with self.lock, self.db:
            self.db.execute(
                "CREATE TABLE IF NOT EXISTS genre_cache (key TEXT PRIMARY KEY, body TEXT)"
            )

    def get(self, key: str) -> Any:
        with self.lock:
            row = self.db.execute("SELECT body FROM genre_cache WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, key: str, body: Any) -> None:
        with self.lock, self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO genre_cache VALUES (?,?)", (key, json.dumps(body))
            )


def _fold(name: str) -> str:
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[\s\-_]+", " ", plain).strip().casefold()


def category_kind(category: int) -> str:
    """`movie` for a Torznab film category (2xxx), `tv` for a series one (5xxx), else empty."""
    return {2: "movie", 5: "tv"}.get(category // 1000, "")


def kind_of(row: Candidate, hint: str = "") -> str:
    """`movie` or `tv` from what the release carries: Torznab categories, else the feed's own."""
    return next((k for c in row.categories if (k := category_kind(c))), hint)


class FeedGenres:
    def __init__(
        self,
        cache: GenreCache,
        *,
        key: Callable[[], str],
        c411: Callable[[], Any],
        reader: Callable[[], Any],
        tmdb: Callable[[str], Any] = default_tmdb,
        clock: Callable[[], float] = time.time,
    ):
        self.cache, self.key, self.c411, self.reader = cache, key, c411, reader
        self.tmdb, self.clock = tmdb, clock

    def options(self, language: str) -> list[dict[str, Any]]:
        """Every TMDb genre as `{id, name}`, named in `fr-FR` or `en-US`; the list is fetched once
        and kept, and the built-in one stands in when TMDb is unreachable."""
        language = "fr-FR" if language.startswith("fr") else "en-US"
        name = 1 if language == "fr-FR" else 2
        fallback = [{"id": g[0], "name": g[name]} for g in FALLBACK_GENRES]
        cache = f"tmdb-genre-list:{language}"
        saved = self.cache.get(cache)
        if saved and self.clock() - saved["at"] < LIST_REFRESH:
            return saved["genres"]
        key = self.key()
        if not key:
            return saved["genres"] if saved else fallback
        try:
            tmdb = self.tmdb(key)
            merged: dict[int, str] = {}
            for media_type in ("movie", "tv"):
                for genre in tmdb.genre_list(media_type, language):
                    merged.setdefault(genre["id"], genre["name"])
        except Exception:
            return saved["genres"] if saved else fallback
        if not merged:
            return saved["genres"] if saved else fallback
        genres = [{"id": i, "name": n} for i, n in merged.items()]
        self.cache.put(cache, {"genres": genres, "at": self.clock()})
        return genres

    def map_names(self, names: tuple[str, ...] | list[str]) -> list[int] | None:
        """c411's French genre names as TMDb ids; None unless every name is known."""
        known = {_fold(g["name"]): g["id"] for g in self.options("fr")}
        known.update({_fold(g[1]): g[0] for g in FALLBACK_GENRES})
        ids = [known.get(_fold(n)) for n in names]
        return [i for i in ids if i is not None] if ids and None not in ids else None

    def ids(self, kind: str, tmdb_id: str) -> list[int] | None:
        """TMDb's genres of a film or series by its id, cached; None when TMDb cannot say."""
        if kind not in {"movie", "tv"}:
            return None
        cache = f"tmdb-genres:{kind}:{tmdb_id}"
        saved = self.cache.get(cache)
        if saved is not None and (saved["genres"] or self.clock() - saved["at"] <= TMDB_RETRY):
            return saved["genres"] or None
        key = self.key()
        if not key:
            return None
        try:
            info = self.tmdb(key).details(tmdb_id, kind)
        except Exception:
            return None
        genres = [
            int(g["id"])
            for g in ((info.raw.get("genres") if info else None) or [])
            if isinstance(g, dict) and isinstance(g.get("id"), int)
        ]
        self.cache.put(cache, {"genres": genres, "at": self.clock()})
        return genres or None

    def due(self, facts: dict) -> bool:
        """Whether a release's genre is still to be looked up (or looked up again)."""
        if facts.get("genre"):
            return False
        checked = facts.get("genre_checked_at")
        return not checked or self.clock() - checked > TMDB_RETRY

    def applies(self, row: Candidate, hint: str = "") -> bool:
        """c411 rows are looked up when they are films or series; tr4ker's detail says."""
        return (row.metadata.get("tracker") or "c411") == "tr4ker" or bool(kind_of(row, hint))

    def cached(self, row: Candidate) -> dict | None:
        saved = self.cache.get(f"genre-item:{row.infohash}")
        return saved if saved is not None and not self.due(saved) else None

    def resolve(self, row: Candidate, hint: str = "") -> dict:
        """The verified facts to add to a release: `genre` (TMDb ids) when known, the TMDb id and
        kind it came with, and when it was looked up. Reads the Tracker once, then TMDb."""
        facts = row.metadata
        found: dict[str, Any] = {"genre_checked_at": self.clock()}
        tmdb_id = str(facts.get("tmdbid") or "")
        kind = facts.get("kind") if facts.get("kind") in {"movie", "tv"} else ""
        names: tuple[str, ...] = ()
        try:
            if (facts.get("tracker") or "c411") == "tr4ker":
                reader = self.reader()
                if not tmdb_id and facts.get("slug") and reader is not None:
                    from torrentlinker.tr4ker_native import read_detail

                    media = read_detail(reader, str(facts["slug"]))["info"].get("media") or {}
                    tmdb_id = str(media.get("tmdb_id") or "")
                    kind = media.get("kind") if media.get("kind") in {"movie", "tv"} else kind
            elif row.infohash:
                from torrentlinker.torrent_details import parse_details

                media = parse_details(self.c411().torrent_json(row.infohash)).media
                if media:
                    names, tmdb_id = media.genres, media.tmdb_id or tmdb_id
                    kind = media.kind if media.kind in {"movie", "tv"} else kind
        except Exception:
            # Not read: asked again in an hour, not in a week.
            found["genre_checked_at"] = self.clock() - TMDB_RETRY + ERROR_RETRY
            self.cache.put(f"genre-item:{row.infohash}", found)
            return found
        if tmdb_id.isdigit():
            found["tmdbid"] = tmdb_id
            if kind:
                found["kind"] = kind
        genres = self.map_names(names) if names else None
        if genres is None and tmdb_id.isdigit():
            genres = self.ids(kind or kind_of(row, hint), tmdb_id)
        if genres:
            found["genre"] = genres
        self.cache.put(f"genre-item:{row.infohash}", found)
        return found
