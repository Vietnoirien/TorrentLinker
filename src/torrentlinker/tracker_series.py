"""The Tracker Series index: every seeded series on the Trackers, one entry per series.

Built like the Tracker Film index (`tracker_films.py`, ADR-0028), from the per-Tracker
Catalogues, seeded releases only. A series is made of seasons and episodes, so a release is
first classified from its name as a **season pack**, an **Intégrale** (every season, or
several of them) or an **episode**, and grouped by series: by TMDb TV id once identified,
until then by its title and year. A background job identifies each series once (poster,
French synopsis, genres, Age Rating, and its seasons and episodes) and only the new Catalogue
entries afterwards. Coverage is then checked against TMDb's season and episode list.

The Catalogue categories that hold series, read from the Owner's Catalogues on 2026-11-27
(see ADR-0030):

    c411    5000 Séries TV, 5070 Animation série (anime), 2000 Séries documentaires
    tr4ker  5000 and 5040 Séries TV, 5070 anime series

c411's 5080 (Émission TV) and 5060 (sport), and the 6000s (adult), never count. tr4ker's 5000
also holds TV shows, so its releases are listed only once TMDb identifies them as a series.

Mixed into MediaLibrary, which provides db and lock.
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from guessit import guessit

from torrentlinker import age_ratings
from torrentlinker.media_ratings import AgeRatings
from torrentlinker.media_tracker import TrackerRows, plain

# The first sync parses every series release of the Catalogues (~200,000 names, ~9 ms each):
# it saves them in batches and pauses between batches, so pages keep answering meanwhile.
SYNC_BATCH = 500
SYNC_PAUSE = 0.05
# Below this many names, parsing in this process is quicker than starting another.
POOL_FROM = 200
# While it fills, the index's revision moves at most this often (seconds).
REVISION_EVERY = 10.0

# Catalogue category -> the kind of series it holds, per Tracker.
SERIES_KINDS: dict[str, dict[int, str]] = {
    "c411": {5000: "series", 5070: "anime", 2000: "documentary"},
    "tr4ker": {5000: "series", 5040: "series", 5070: "anime"},
}
IDENTIFIED_ONLY = frozenset({"tr4ker"})
POSTER_BASE = "https://image.tmdb.org/t/p/w500"
RUN_INTERVAL = 600
IDENTIFY_BUDGET = 120.0
IDENTIFY_PAUSE = 0.25
NOT_FOUND_RETRY = 7 * 86400
UNAVAILABLE_PAUSE = 60.0  # seconds before a page may start the index job again after TMDb failed
LIMIT_PAUSE = 3600.0

SEASON_RANGE = re.compile(
    r"\bsaisons?[ ._-]*(\d{1,2})[ ._-]*(?:a|à|to|-|&|et)[ ._-]*(\d{1,2})\b", re.IGNORECASE
)
COMPLETE = re.compile(r"\b(int[eé]grale|compl[eè]te?s?|complete[ ._-]series|collection)\b", re.I)


@dataclass(frozen=True)
class SeriesRelease:
    """What a release name says of its series."""

    title: str
    year: str
    pack: str  # "season", "complete" (an Intégrale or several seasons), "episode" or "" (unknown)
    seasons: tuple[int, ...]  # the seasons a pack covers; empty for every season of a complete
    season: int = 0  # an episode's season
    episode: int = 0  # an episode's number


def series_key(title: str, year: str) -> str:
    """A series without its TMDb id is grouped by its plain title and year."""
    return json.dumps([plain(title), str(year or "")])


def series_id(tmdb: str, tkey: str, tracker: str, infohash: str) -> str:
    import hashlib

    if tmdb:
        return "tv-" + tmdb
    if tkey:
        return "title-" + hashlib.sha1(tkey.encode()).hexdigest()[:16]
    return "release-" + hashlib.sha1(f"{tracker}:{infohash}".encode()).hexdigest()[:16]


def _numbers(value: Any) -> tuple[int, ...]:
    if value is None:
        return ()
    return tuple(int(v) for v in (value if isinstance(value, list) else [value]))


def parse_series_release(name: str) -> SeriesRelease:
    """Classify a release name: `S01` a season pack, `S01E02` an episode, `INTEGRALE`,
    `COMPLETE` or several seasons an Intégrale."""
    guessed = guessit(name, {"type": "episode"})
    title = str(guessed.get("title") or "").strip()
    year = str(guessed.get("year") or "")
    seasons, episodes = _numbers(guessed.get("season")), _numbers(guessed.get("episode"))
    if span := SEASON_RANGE.search(name):  # "Saisons 1 à 5": guessit reads it as S01E05
        low, high = int(span.group(1)), int(span.group(2))
        if low < high:
            seasons, episodes = tuple(range(low, high + 1)), ()
            title = title or ""
    complete = bool(COMPLETE.search(name)) or guessed.get("other") == "Complete"
    if episodes and len(seasons) == 1:
        return SeriesRelease(title, year, "episode", (seasons[0],), seasons[0], episodes[0])
    if len(seasons) > 1:
        return SeriesRelease(title, year, "complete", seasons)
    if len(seasons) == 1:
        return SeriesRelease(title, year, "season", seasons)
    if complete:
        return SeriesRelease(title, year, "complete", ())
    return SeriesRelease(title, year, "", ())


def parse_many(names: list[str]) -> list[SeriesRelease]:
    return [parse_series_release(name) for name in names]


@contextmanager
def parser_pool(count: int) -> Iterator[Callable[[list[str]], list[SeriesRelease]]]:
    """Parse names in a worker process when there are many, here when there are few."""
    if count < POOL_FROM:
        yield parse_many
        return
    import multiprocessing
    from concurrent.futures import ProcessPoolExecutor

    with ProcessPoolExecutor(1, mp_context=multiprocessing.get_context("spawn")) as pool:
        yield lambda names: pool.submit(parse_many, names).result()


def coverage(
    releases: list[dict[str, Any]], seasons: dict[int, int], episodes: dict[int, set[int]]
) -> dict[int, dict[str, Any]]:
    """For each TMDb season (specials, season 0, aside): whether the Trackers hold a full
    pack, an Intégrale that covers it, episodes only, or nothing, and which episodes exist.

    `seasons` maps a season number to its episode count and `episodes` to its episode numbers
    as TMDb lists them; a release outside that list never counts, so a mislabelled episode
    cannot make a season look complete."""
    result: dict[int, dict[str, Any]] = {
        n: {"state": "none", "episodes": set(), "episode_count": count}
        for n, count in seasons.items()
        if n > 0
    }
    for release in releases:
        pack, covered = release["pack"], release["seasons"]
        if pack == "complete":
            for n in covered or tuple(result):
                if n in result and result[n]["state"] != "pack":
                    result[n]["state"] = "complete"
        elif pack == "season":
            for n in covered:
                if n in result:
                    result[n]["state"] = "pack"
        elif pack == "episode":
            n = release["season"]
            known = episodes.get(n)
            if n in result and (not known or release["episode"] in known):
                result[n]["episodes"].add(release["episode"])
    for entry in result.values():
        if entry["state"] == "none" and entry["episodes"]:
            entry["state"] = "episodes"
    return result


class TrackerSeries(TrackerRows, AgeRatings):
    """Mixed into MediaLibrary, which provides db and lock."""

    db: Any
    lock: Any

    def create_series(self) -> None:
        self._series_generation = int(time.time())
        self._series_bumped = 0.0
        self._series_working = threading.Lock()  # one identification at a time
        self._series_resting: dict[str, float] = {}
        with self.db:
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS series_release
                    (tracker TEXT, infohash TEXT, name TEXT, size INTEGER, seeders INTEGER,
                    category INTEGER, kind TEXT, position INTEGER, tkey TEXT NOT NULL DEFAULT '',
                    title TEXT NOT NULL DEFAULT '', year TEXT NOT NULL DEFAULT '',
                    pack TEXT NOT NULL DEFAULT '', seasons TEXT NOT NULL DEFAULT '[]',
                    season INTEGER NOT NULL DEFAULT 0, episode INTEGER NOT NULL DEFAULT 0,
                    manual TEXT NOT NULL DEFAULT '', download_url TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(tracker, infohash));
                CREATE INDEX IF NOT EXISTS series_release_tkey ON series_release(tkey);
                CREATE TABLE IF NOT EXISTS series_title
                    (tkey TEXT PRIMARY KEY, tmdb TEXT NOT NULL, manual INTEGER NOT NULL DEFAULT 0,
                    checked REAL);
                CREATE TABLE IF NOT EXISTS series_meta
                    (tmdb TEXT PRIMARY KEY, title TEXT, original_title TEXT, year TEXT,
                    overview TEXT, genres TEXT, status TEXT, rating TEXT,
                    rating_by TEXT NOT NULL DEFAULT '', poster TEXT, fetched REAL);
                CREATE TABLE IF NOT EXISTS series_artwork (tmdb TEXT PRIMARY KEY, artwork TEXT);
                CREATE TABLE IF NOT EXISTS series_season
                    (tmdb TEXT, season INTEGER, name TEXT, episodes INTEGER,
                    PRIMARY KEY(tmdb, season));
                CREATE TABLE IF NOT EXISTS series_episode
                    (tmdb TEXT, season INTEGER, episode INTEGER, title TEXT, overview TEXT,
                    PRIMARY KEY(tmdb, season, episode));
            """)

    def _series_changed(self) -> None:
        self._series_generation += 1
        self._series_bumped = time.monotonic()

    def series_revision(self) -> int:
        return self._series_generation

    # -- The Catalogues ---------------------------------------------------------------------

    def series_sync(self, client_id, setup, stop: threading.Event | None = None) -> bool:
        """Bring `series_release` up to the Catalogues' seeded series releases: parse the new
        ones, drop the vanished, follow seeders and sizes. True when anything changed."""
        stop = stop or threading.Event()
        changed = False
        for site in self._catalogue_trackers(setup):
            kinds = SERIES_KINDS.get(site)
            if not kinds:
                continue
            current = {
                row.infohash.lower(): (row, order)
                for row, order in self._site_store(setup, site).catalogue_seeded(tuple(kinds))
            }
            with self.lock:
                known = {
                    r["infohash"]: (r["size"], r["seeders"])
                    for r in self.db.execute(
                        "SELECT infohash, size, seeders FROM series_release WHERE tracker=?",
                        (site,),
                    )
                }
            gone = [(site, h) for h in known.keys() - current.keys()]
            updates = [
                (row.size, row.seeders, site, h)
                for h, (row, _) in current.items()
                if h in known and known[h] != (row.size, row.seeders)
            ]
            new = [(h, row, order) for h, (row, order) in current.items() if h not in known]
            changed = changed or bool(gone or new or updates)
            self._series_save(site, gone, [], updates)
            # Parsing a name costs ~9 ms of regular expressions that hold the interpreter: the
            # names are parsed in another process, a batch at a time, and each batch is saved
            # so the page shows the series as they come while the server keeps answering.
            with parser_pool(len(new)) as parse:
                for start in range(0, len(new), SYNC_BATCH):
                    if stop.is_set():
                        break
                    batch = new[start : start + SYNC_BATCH]
                    inserts = []
                    for (infohash, row, order), parsed in zip(
                        batch, parse([row.title for _, row, _ in batch]), strict=True
                    ):
                        tkey = series_key(parsed.title, parsed.year) if parsed.title else ""
                        inserts.append(
                            (
                                site, infohash, row.title, row.size, row.seeders, row.category,
                                kinds.get(row.category or 0, "series"), order, tkey, parsed.title,
                                parsed.year, parsed.pack, json.dumps(list(parsed.seasons)),
                                parsed.season, parsed.episode, row.download_url,
                            )
                        )  # fmt: skip
                    self._series_save(site, [], inserts, [])
                    stop.wait(SYNC_PAUSE)
        if changed:
            self._series_changed()
        return changed

    def _series_save(self, site: str, gone, inserts, updates) -> None:
        with self.lock, self.db:
            self.db.executemany("DELETE FROM series_release WHERE tracker=? AND infohash=?", gone)
            self.db.executemany(
                "INSERT OR REPLACE INTO series_release (tracker, infohash, name, size,"
                " seeders, category, kind, position, tkey, title, year, pack, seasons,"
                " season, episode, download_url) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                inserts,
            )
            self.db.executemany(
                "UPDATE series_release SET size=?, seeders=? WHERE tracker=? AND infohash=?",
                updates,
            )
        if (gone or inserts) and time.monotonic() - self._series_bumped >= REVISION_EVERY:
            # Pages poll the revision and rebuild the index on a change: once in a while is
            # enough while the first sync fills it; the sync bumps it again when done.
            self._series_changed()

    # -- Identification ---------------------------------------------------------------------

    def _series_fetch_meta(self, tmdb, tmdb_id: str) -> bool:
        """Store a series' French facts, seasons and episodes from TMDb; False when unknown."""
        info = tmdb.details(tmdb_id, "tv")
        if info is None:
            return False
        raw = info.raw
        try:
            found = age_ratings.from_tmdb(tmdb.certifications(tmdb_id, "tv"))
        except Exception:
            found = None
        seasons = [s for s in raw.get("seasons") or [] if isinstance(s.get("season_number"), int)]
        episodes: list[tuple[str, int, int, str, str]] = []
        for season in seasons:
            if season["season_number"] <= 0:
                continue
            try:
                data = tmdb.tv_season(tmdb_id, season["season_number"])
            except Exception:
                continue  # the season stays; its episodes come with a later run
            for e in data.get("episodes") or []:
                episodes.append(
                    (tmdb_id, season["season_number"], int(e.get("episode_number") or 0),
                     str(e.get("name") or ""), str(e.get("overview") or ""))
                )  # fmt: skip
        with self.lock, self.db:
            kept = self.db.execute(
                "SELECT rating, rating_by FROM series_meta WHERE tmdb=?", (tmdb_id,)
            ).fetchone()
            rating = found.rating if found and found.french else None
            by = "tmdb" if rating else ""
            if kept and kept["rating_by"] == "person":
                rating, by = kept["rating"], "person"
            self.db.execute(
                "INSERT OR REPLACE INTO series_meta VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    tmdb_id, info.title, info.original_title, info.year, info.overview,
                    json.dumps(
                        [str(g["name"]) for g in raw.get("genres") or [] if g.get("name")],
                        ensure_ascii=False,
                    ),
                    str(raw.get("status") or ""), rating, by,
                    POSTER_BASE + raw["poster_path"] if raw.get("poster_path") else "",
                    time.time(),
                ),
            )  # fmt: skip
            self.db.execute("DELETE FROM series_season WHERE tmdb=?", (tmdb_id,))
            self.db.executemany(
                "INSERT INTO series_season VALUES (?,?,?,?)",
                [
                    (tmdb_id, s["season_number"], str(s.get("name") or ""),
                     int(s.get("episode_count") or 0))
                    for s in seasons
                ],
            )  # fmt: skip
            if episodes:
                self.db.execute("DELETE FROM series_episode WHERE tmdb=?", (tmdb_id,))
                self.db.executemany(
                    "INSERT OR REPLACE INTO series_episode VALUES (?,?,?,?,?)", episodes
                )
        return True

    def series_identify(
        self,
        client_id,
        setup,
        stop: threading.Event,
        *,
        budget: float = IDENTIFY_BUDGET,
        pause: float = IDENTIFY_PAUSE,
    ) -> str:
        """Ask TMDb for the series the index does not know yet, newest and most shared first,
        each once (a week later when TMDb did not know it). Returns "off" without a TMDb key,
        "limit", "unavailable", "cancelled" or "complete"."""
        from torrentlinker.domain import ContentKind

        secrets = getattr(setup, "secrets", None)
        key = secrets.get("tmdb-api-key") if secrets is not None else ""
        if not key:
            return "off"
        tmdb = self.tmdb_client(key)
        started, failures = time.monotonic(), 0
        with self.lock:
            titles = self.db.execute(
                "SELECT r.tkey, MIN(r.title) AS title, MIN(r.year) AS year FROM series_release r"
                " LEFT JOIN series_title t ON t.tkey = r.tkey WHERE r.tkey <> ''"
                " AND (t.tkey IS NULL OR (t.tmdb = '' AND t.manual = 0 AND t.checked < ?))"
                " GROUP BY r.tkey ORDER BY SUM(r.seeders) DESC",
                (time.time() - NOT_FOUND_RETRY,),
            ).fetchall()
            have = {r[0] for r in self.db.execute("SELECT tmdb FROM series_meta")}
        for row in titles:
            if stop.is_set():
                return "cancelled"
            if time.monotonic() - started > budget:
                return "limit"
            try:
                found = (
                    tmdb.lookup(row["title"], int(row["year"]) if row["year"] else None,
                                ContentKind.SERIES) or ""
                )  # fmt: skip
            except Exception:
                failures += 1
                if failures >= 3:
                    return "unavailable"
                continue
            failures = 0
            with self.lock, self.db:
                self.db.execute(
                    "INSERT OR REPLACE INTO series_title VALUES (?,?,0,?)",
                    (row["tkey"], found, time.time()),
                )
            if found and found not in have:
                try:
                    self._series_fetch_meta(tmdb, found)
                    have.add(found)
                except Exception:
                    failures += 1
                    if failures >= 3:
                        return "unavailable"
            self._series_changed()
            time.sleep(pause)
        return "complete"

    def series_refresh(self, client_id, setup, stop: threading.Event, **identify) -> str:
        """Read the Catalogues, then identify; at most once per RUN_INTERVAL, resumable."""
        key = "series-run:" + client_id
        with self.lock:
            saved = self.db.execute("SELECT body FROM media_options WHERE key=?", (key,)).fetchone()
        if saved and time.time() - json.loads(saved[0]) < RUN_INTERVAL:
            return "waiting"
        with self.lock:
            filled = self.db.execute("SELECT 1 FROM series_release LIMIT 1").fetchone()
        if not filled:
            # The first fill parses every series of the Catalogues for half an hour: it is the
            # series job's (its own lane), never the Médias refresh's, which holds settings.
            return "waiting"
        if not self._series_working.acquire(blocking=False):
            return "waiting"
        try:
            self.series_sync(client_id, setup, stop)
            status = self.series_identify(client_id, setup, stop, **identify)
        finally:
            self._series_working.release()
        if status == "complete":
            with self.lock, self.db:
                self.db.execute(
                    "INSERT OR REPLACE INTO media_options VALUES (?,?)",
                    (key, json.dumps(time.time())),
                )
        return status

    # -- The index job, on demand (as the film index) ----------------------------------------

    def _series_fresh(self, key: str) -> bool:
        with self.lock:
            saved = self.db.execute("SELECT body FROM media_options WHERE key=?", (key,)).fetchone()
        return bool(saved) and time.time() - json.loads(saved[0]) < RUN_INTERVAL

    def _series_stamp(self, key: str) -> None:
        with self.lock, self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO media_options VALUES (?,?)", (key, json.dumps(time.time()))
            )

    def series_progress(self) -> tuple[int, int]:
        """(identified, total) series titles of the index."""
        with self.lock:
            total = self.db.execute(
                "SELECT COUNT(DISTINCT tkey) FROM series_release WHERE tkey <> ''"
            ).fetchone()[0]
            identified = self.db.execute(
                "SELECT COUNT(DISTINCT r.tkey) FROM series_release r JOIN series_title t"
                " ON t.tkey = r.tkey WHERE t.tmdb <> ''"
            ).fetchone()[0]
        return identified, total

    def series_behind(self, client_id, setup) -> bool:
        """Whether the index needs its job: the Catalogues were not read for a while, or titles
        wait for TMDb (which needs a key). Cheap; asked by every page that shows series."""
        if time.monotonic() < self._series_resting.get(client_id, 0.0):
            return False
        if not self._series_fresh("series-sync:" + client_id):
            return True
        secrets = getattr(setup, "secrets", None)
        if not (secrets.get("tmdb-api-key") if secrets is not None else ""):
            return False
        identified, total = self.series_progress()
        return identified < total and not self._series_fresh("series-run:" + client_id)

    def series_index_job(
        self, client_id, setup, stop: threading.Event, progress, *, pause: float = IDENTIFY_PAUSE
    ) -> str:
        """The job a page starts: read the Catalogues, then identify until done."""
        if not self._series_working.acquire(blocking=False):
            return "busy"
        try:
            progress({"phase": "sync"})
            self.series_sync(client_id, setup, stop)
            self._series_stamp("series-sync:" + client_id)
            status = self.series_identify(client_id, setup, stop, budget=float("inf"), pause=pause)
            done, total = self.series_progress()
            progress({"phase": "identify", "identified": done, "total": total})
        finally:
            self._series_working.release()
        if status in {"complete", "off"}:
            self._series_stamp("series-run:" + client_id)
        elif status == "unavailable":
            self._series_resting[client_id] = time.monotonic() + UNAVAILABLE_PAUSE
        elif status == "limit":
            self._series_resting[client_id] = time.monotonic() + LIMIT_PAUSE
        return status

    def series_revision_info(self, running: bool, owner: bool) -> dict[str, Any]:
        """What the panel polls: changes whenever the index does. Only the Owner gets counts."""
        answer: dict[str, Any] = {"revision": self._series_generation, "running": running}
        if owner:
            answer["identified"], answer["total"] = self.series_progress()
        return answer

    # -- Reading the index ------------------------------------------------------------------

    def series_index(self) -> list[dict[str, Any]]:
        """One entry per series with its releases grouped by season. A tr4ker release counts
        only once TMDb identified its series; the rest of a series' kinds never mix. Built once
        per revision: pages ask for it on every request, and it reads every release."""
        cached = getattr(self, "_series_built", None)
        if cached and cached[0] == self._series_generation:
            return cached[1]
        generation = self._series_generation
        built = self._series_build()
        self._series_built = (generation, built)
        return built

    def _series_build(self) -> list[dict[str, Any]]:
        with self.lock:
            releases = [dict(r) for r in self.db.execute("SELECT * FROM series_release")]
            ids = {r["tkey"]: r["tmdb"] for r in self.db.execute("SELECT * FROM series_title")}
            metas = {r["tmdb"]: dict(r) for r in self.db.execute("SELECT * FROM series_meta")}
            seasons: dict[str, dict[int, int]] = {}
            for r in self.db.execute("SELECT tmdb, season, episodes FROM series_season"):
                seasons.setdefault(r["tmdb"], {})[r["season"]] = r["episodes"]
            episodes: dict[str, dict[int, set[int]]] = {}
            for r in self.db.execute("SELECT tmdb, season, episode FROM series_episode"):
                episodes.setdefault(r["tmdb"], {}).setdefault(r["season"], set()).add(r["episode"])
        groups: dict[str, dict[str, Any]] = {}
        for r in releases:
            tmdb = r["manual"] or ids.get(r["tkey"], "")
            if r["tracker"] in IDENTIFIED_ONLY and not tmdb:
                continue
            identifier = series_id(tmdb, r["tkey"], r["tracker"], r["infohash"])
            group = groups.setdefault(
                identifier, {"id": identifier, "tmdb": tmdb, "title": r["title"], "releases": []}
            )
            r["seasons"] = tuple(json.loads(r["seasons"]))
            group["releases"].append(r)
        result = []
        for group in groups.values():
            tmdb = group["tmdb"]
            meta = metas.get(tmdb)
            kinds = {r["kind"] for r in group["releases"]}
            entry = {
                **group,
                "kind": "anime" if "anime" in kinds else (
                    "documentary" if kinds == {"documentary"} else "series"
                ),
                "meta": meta,
                "coverage": coverage(
                    group["releases"], seasons.get(tmdb, {}), episodes.get(tmdb, {})
                ),
            }  # fmt: skip
            if meta:
                entry["title"] = meta["title"] or entry["title"]
            result.append(entry)
        return sorted(result, key=lambda e: plain(e["title"]))

    # -- Posters and visibility -------------------------------------------------------------

    def series_visible(self, client_id, identifier: str, actor) -> bool:
        """Whether the actor may see this series' poster: as for its panel, a hidden series is
        as missing as an unknown one."""
        from torrentlinker import tracker_series_view as view

        try:
            view.detail(self, client_id, identifier, actor)
        except KeyError:
            return False
        return True

    def series_artwork(self, client_id, identifier: str):
        """A series' TMDb poster, downloaded once and kept as the other posters are."""
        import re

        from torrentlinker import media_artwork

        entry = next((e for e in self.series_index() if e["id"] == identifier), None)
        poster = ((entry or {}).get("meta") or {}).get("poster") or ""
        if not poster.startswith(POSTER_BASE):
            return None
        tmdb = entry["tmdb"]  # type: ignore[index]
        with media_artwork.download_lock(f"series:{tmdb}"):
            with self.lock:
                row = self.db.execute(
                    "SELECT artwork FROM series_artwork WHERE tmdb=?", (tmdb,)
                ).fetchone()
            image = row["artwork"] if row else ""
            if not image:
                from torrentlinker.assistant.images import fetch_image

                data, _ = fetch_image(poster)
                image = self.cache_artwork(data)  # type: ignore[attr-defined]
                with self.lock, self.db:
                    self.db.execute(
                        "INSERT OR REPLACE INTO series_artwork VALUES (?,?)", (tmdb, image)
                    )
        if not re.fullmatch(r"asset:[a-f0-9]{64}\.(png|webp)", image):
            return None
        return self.agent.setup.path.parent / "media-artwork" / image[6:]  # type: ignore[attr-defined]

    def series_release_entry(self, infohash: str) -> dict[str, Any] | None:
        """A series release as the download queue reads a tracker suggestion: the release, and
        its series' title and year as facts."""
        with self.lock:
            row = self.db.execute(
                "SELECT * FROM series_release WHERE infohash=? LIMIT 1", (infohash,)
            ).fetchone()
        if row is None:
            return None
        release = {
            "hash": row["infohash"], "name": row["name"], "size": row["size"],
            "seeders": row["seeders"], "category": row["category"], "tracker": row["tracker"],
            "download_url": row["download_url"] or "",
        }  # fmt: skip
        return {
            "title": row["title"], "year": row["year"],
            "facts": {"title": row["title"], "year": row["year"]}, "releases": [release],
            "release": release,
        }  # fmt: skip

    def series_score(self, client_id):
        """ReleaseScore of a series release by the Owner's profile (0 when unreadable)."""
        preferences = self.setup(client_id).settings.release_score  # type: ignore[attr-defined]

        def score(release: dict[str, Any]) -> dict[str, Any]:
            try:
                found = self._score(preferences, release["name"], release["size"], {})
            except Exception:  # noqa: BLE001 - an unreadable name has no score
                return {}
            return {"score": found.get("score"), "color": found.get("color", "")}

        return score

    def series_order(self, client_id) -> list[str]:
        return list(self.setup(client_id).settings.tracker_order)  # type: ignore[attr-defined]
