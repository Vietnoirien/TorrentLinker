"""The Tracker Film index: every seeded film on the Trackers, one entry per film.

A Tracker Film is a Film (one title and year, identified by its TMDb id when known) with at
least one seeded release on a Tracker. The index is built from the per-Tracker Catalogues, so
it holds old films too, not only what the listing of c411's latest releases shows. Releases
are read once (`film_release`) and grouped by TMDb id; until a release is identified it groups
by its title and year. A background job identifies each title once (`film_title`, then
`film_meta` for the poster, French synopsis, genres, runtime and Age Rating) and only the new
Catalogue entries afterwards. The Owner's corrections (`manual`) survive re-identification.

Mixed into MediaLibrary, which provides db and lock.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from datetime import date
from typing import Any

from guessit import guessit

from torrentlinker import age_ratings
from torrentlinker.media_ratings import AgeRatings
from torrentlinker.media_tracker import TrackerRows, film_key, plain
from torrentlinker.trackers import DEFAULT_TRACKER, valid_order

# The Catalogue categories that hold films (decision 18); the 6000s (adult) never count. A
# tr4ker category holds non-films too (PDF magazines, series, albums): its releases are listed
# only once TMDb identifies them as a film.
FILM_CATEGORIES = {"c411": (2030, 2060, 2070, 2080, 2090), "tr4ker": (2000, 2040)}
IDENTIFIED_ONLY = frozenset({"tr4ker"})
# TMDb's French film genres (decision 16), in TMDb's order.
GENRES = (
    "Action",
    "Aventure",
    "Animation",
    "Comédie",
    "Crime",
    "Documentaire",
    "Drame",
    "Familial",
    "Fantastique",
    "Histoire",
    "Horreur",
    "Musique",
    "Mystère",
    "Romance",
    "Science-Fiction",
    "Téléfilm",
    "Thriller",
    "Guerre",
    "Western",
)
SORTS = ("new", "shared", "year", "title")
POSTER_BASE = "https://image.tmdb.org/t/p/w500"
RUN_INTERVAL = 600  # seconds between two refreshes of the index
IDENTIFY_BUDGET = 120.0  # seconds one refresh may spend asking TMDb; the rest waits
IDENTIFY_PAUSE = 0.25  # seconds between two TMDb requests
HIDDEN = {"tkey", "position", "download_url"}  # the index's own columns, never sent out
NOT_FOUND_RETRY = 7 * 86400  # a title TMDb did not know is asked again a week later
IDENTIFY_BATCH = 10  # titles the on-demand job asks per batch, then looks at the focus again
UNAVAILABLE_PAUSE = 60.0  # seconds before a page may start the job again after TMDb failed
WALK_PAUSE = 10.0  # seconds between two pages of c411's film listing (decision 26)
FOCUS_PAUSE = 2.0  # seconds between two searches for the films on screen
LIMIT_PAUSE = 3600.0  # seconds c411 is left alone after it asked to wait
FILM_ROOT = "1"  # c411's native root of the films; its children are the film categories
SLICE_CAP = 10_000  # releases c411 reports for one search; it answers no page deeper than this
FIRST_YEAR = 1900  # the oldest year c411's `year` filter takes
RECENT_YEARS = 3  # years a finished walk reads again, newest pages only


def film_id(tmdb: str, tkey: str, tracker: str, infohash: str) -> str:
    """A film's identifier: its TMDb id, else its parsed title and year, else its one release."""
    if tmdb:
        return "tmdb-" + tmdb
    if tkey:
        return "title-" + hashlib.sha1(tkey.encode()).hexdigest()[:16]
    return "release-" + hashlib.sha1(f"{tracker}:{infohash}".encode()).hexdigest()[:16]


def parse_release(name: str) -> tuple[str, str]:
    """The title and year a release name says; the year is empty when it names none."""
    guessed = guessit(name, {"type": "movie"})
    return str(guessed.get("title") or "").strip(), str(guessed.get("year") or "")


class TrackerFilms(TrackerRows, AgeRatings):
    """Mixed into MediaLibrary, which provides db and lock; the rows' tracker helpers and
    the ratings' `tmdb_client` come from the classes it builds on."""

    db: Any
    lock: Any

    def create_films(self) -> None:
        self._films_generation = int(time.time())  # a restart never repeats a revision
        self._films_focus: dict[str, frozenset[str]] = {}
        self._films_status: tuple[int, tuple[int, int]] | None = None
        self._films_resting: dict[str, float] = {}
        self._films_working = threading.Lock()  # one identification at a time
        self._films_asked: set[str] = set()  # titles searched on c411 since the start
        self._films_cache: tuple[int, list[dict[str, Any]]] | None = None
        self._films_choices: tuple[int, dict[tuple[str, str], dict[str, Any]]] = (-1, {})
        self._films_sources: dict[str, str] = {}  # film key: the release its c411 facts came from
        with self.db:
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS film_release
                    (tracker TEXT, infohash TEXT, name TEXT, size INTEGER, seeders INTEGER,
                    category INTEGER, published REAL NOT NULL DEFAULT 0, position INTEGER,
                    tkey TEXT NOT NULL DEFAULT '', title TEXT NOT NULL DEFAULT '',
                    year TEXT NOT NULL DEFAULT '', manual TEXT NOT NULL DEFAULT '',
                    download_url TEXT NOT NULL DEFAULT '', PRIMARY KEY(tracker, infohash));
                CREATE INDEX IF NOT EXISTS film_release_tkey ON film_release(tkey);
                CREATE TABLE IF NOT EXISTS film_title
                    (tkey TEXT PRIMARY KEY, tmdb TEXT NOT NULL, manual INTEGER NOT NULL DEFAULT 0,
                    checked REAL);
                CREATE TABLE IF NOT EXISTS film_meta
                    (tmdb TEXT PRIMARY KEY, title TEXT, original_title TEXT, year TEXT,
                    overview TEXT, genres TEXT, runtime INTEGER, rating TEXT, rating_by TEXT
                    NOT NULL DEFAULT '', suggestion TEXT, poster TEXT, artwork TEXT, fetched REAL);
                CREATE TABLE IF NOT EXISTS film_c411
                    (tkey TEXT PRIMARY KEY, title TEXT, original_title TEXT, year TEXT,
                    overview TEXT, genres TEXT, runtime INTEGER, poster TEXT, artwork TEXT,
                    fetched REAL);
            """)

    def _films_changed(self) -> None:
        self._films_generation += 1

    # -- Reading the Catalogues ------------------------------------------------------------

    def films_sync(self, client_id, setup, stop: threading.Event | None = None) -> bool:
        """Bring `film_release` up to the Catalogues' seeded film releases: parse the new
        ones, drop the vanished, follow seeders and sizes. True when anything changed."""
        stop = stop or threading.Event()
        listed = {
            r["hash"]: (entry, r)
            for entry in self._tracker_cache(client_id, "tracker-new").values()
            for r in entry.get("releases") or []
        }
        # `changed` reports any change; `shown` only what changes the films a page draws. A
        # seeder count or a size moves with every Catalogue refresh: a page following the
        # index must not fetch and reorder its cards for that.
        changed = shown = False
        for site in self._catalogue_trackers(setup):
            categories = FILM_CATEGORIES.get(site)
            if not categories:
                continue
            current = {
                row.infohash.lower(): (row, order)
                for row, order in self._site_store(setup, site).catalogue_seeded(categories)
            }
            with self.lock:
                known = {
                    r["infohash"]: (r["size"], r["seeders"], r["published"])
                    for r in self.db.execute(
                        "SELECT infohash, size, seeders, published FROM film_release"
                        " WHERE tracker=?",
                        (site,),
                    )
                }
            gone = [(site, h) for h in known.keys() - current.keys()]
            if gone:
                with self.lock, self.db:
                    self.db.executemany(
                        "DELETE FROM film_release WHERE tracker=? AND infohash=?", gone
                    )
                changed = shown = True
            inserts, updates = [], []
            for infohash, (row, order) in current.items():
                entry, release = listed.get(infohash, ({}, {}))
                published = float(release.get("published_at") or 0)
                if infohash not in known:
                    if stop.is_set():
                        break
                    # c411's own listing already read the title and year of what it returned.
                    title, year = (
                        (str(entry.get("title") or ""), str(entry.get("year") or ""))
                        if entry.get("title")
                        else parse_release(row.title)
                    )
                    tkey = film_key(title, year) if title and year else ""
                    inserts.append(
                        (
                            site,
                            infohash,
                            row.title,
                            row.size,
                            row.seeders,
                            row.category,
                            published,
                            order,
                            tkey,
                            title,
                            year,
                            row.download_url,
                        )
                    )
                elif known[infohash] != (row.size, row.seeders, published or known[infohash][2]):
                    updates.append(
                        (row.size, row.seeders, published or known[infohash][2], site, infohash)
                    )
                    # A new publication date moves the film in "new"; seeders do not count.
                    shown = shown or bool(published and published != known[infohash][2])
            with self.lock, self.db:
                self.db.executemany(
                    "INSERT OR REPLACE INTO film_release (tracker, infohash, name, size, seeders,"
                    " category, published, position, tkey, title, year, download_url)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    inserts,
                )
                self.db.executemany(
                    "UPDATE film_release SET size=?, seeders=?, published=?"
                    " WHERE tracker=? AND infohash=?",
                    updates,
                )
            changed = changed or bool(inserts or updates)
            shown = shown or bool(inserts)
        if shown:
            self._films_changed()
            self._film_index()  # rebuilt by the scan, not by the next page that asks
        if not stop.is_set():
            self._films_stamp("films-sync:" + client_id)
        return changed

    def _films_stamp(self, key: str) -> None:
        with self.lock, self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO media_options VALUES (?,?)", (key, json.dumps(time.time()))
            )

    def _films_fresh(self, key: str) -> bool:
        with self.lock:
            saved = self.db.execute("SELECT body FROM media_options WHERE key=?", (key,)).fetchone()
        return bool(saved) and time.time() - json.loads(saved[0]) < RUN_INTERVAL

    # -- Identification --------------------------------------------------------------------

    def _fetch_meta(self, tmdb, tmdb_id: str) -> bool:
        """Store a film's French facts from TMDb; False when TMDb does not know the id."""
        info = tmdb.details(tmdb_id, "movie")
        if info is None:
            return False
        raw = info.raw
        try:
            found = age_ratings.from_tmdb(tmdb.certifications(tmdb_id, "movie"))
        except Exception:
            found = None  # the facts are worth keeping without a rating
        with self.lock, self.db:
            kept = self.db.execute(
                "SELECT rating, rating_by FROM film_meta WHERE tmdb=?", (tmdb_id,)
            ).fetchone()
            rating = found.rating if found and found.french else None
            by = "tmdb" if rating else ""
            if kept and kept["rating_by"] == "person":  # a person's rating is never replaced
                rating, by = kept["rating"], "person"
            self.db.execute(
                "INSERT OR REPLACE INTO film_meta (tmdb, title, original_title, year, overview,"
                " genres, runtime, rating, rating_by, suggestion, poster, artwork, fetched)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,"
                " (SELECT artwork FROM film_meta WHERE tmdb=?),?)",
                (
                    tmdb_id,
                    info.title,
                    info.original_title,
                    info.year,
                    info.overview,
                    json.dumps(
                        [str(g["name"]) for g in raw.get("genres") or [] if g.get("name")],
                        ensure_ascii=False,
                    ),
                    int(raw.get("runtime") or 0),
                    rating,
                    by,
                    json.dumps(found.suggestion("tmdb")) if found and not rating else None,
                    POSTER_BASE + raw["poster_path"] if raw.get("poster_path") else "",
                    tmdb_id,
                    time.time(),
                ),
            )
        return True

    def films_identify(
        self,
        client_id,
        setup,
        stop: threading.Event,
        *,
        budget: float = IDENTIFY_BUDGET,
        pause: float = IDENTIFY_PAUSE,
        limit: int | None = None,
    ) -> str:
        """Ask TMDb for what the index does not know yet, within `budget` seconds.

        Each title is asked once (a week later when TMDb did not know it), with the facts of
        its film as soon as it is known. The titles on screen (`films_focus`) go first, then
        the newest, then the most shared. Everything is saved as it arrives, so a later run
        resumes where this stopped, and the index answers meanwhile with what it has. Returns
        "off" without a TMDb key, "limit" when the budget ran out, "batch" when `limit` titles
        were asked and more wait, "unavailable" when TMDb stops answering, "cancelled" or
        "complete".
        """
        from torrentlinker.domain import ContentKind

        secrets = getattr(setup, "secrets", None)
        key = secrets.get("tmdb-api-key") if secrets is not None else ""
        if not key:
            return "off"
        tmdb = self.tmdb_client(key)
        started, failures = time.monotonic(), 0
        with self.lock:
            titles = self.db.execute(
                "SELECT r.tkey, MIN(r.title) AS title, MIN(r.year) AS year FROM film_release r"
                " LEFT JOIN film_title t ON t.tkey = r.tkey WHERE r.tkey <> ''"
                " AND (t.tkey IS NULL OR (t.tmdb = '' AND t.manual = 0 AND t.checked < ?))"
                " GROUP BY r.tkey ORDER BY MAX(r.published) DESC, SUM(r.seeders) DESC",
                (time.time() - NOT_FOUND_RETRY,),
            ).fetchall()
            have = {r[0] for r in self.db.execute("SELECT tmdb FROM film_meta")}
        focus = self._films_focus.get(client_id, frozenset())
        titles.sort(key=lambda row: row["tkey"] not in focus)  # stable: the order stays inside

        def spent() -> str:
            if stop.is_set():
                return "cancelled"
            return "limit" if time.monotonic() - started > budget else ""

        asked = 0
        for row in titles:
            if stopped := spent():
                return stopped
            if limit is not None and asked >= limit:
                return "batch"
            asked += 1
            try:
                found = tmdb.lookup(row["title"], int(row["year"]), ContentKind.MOVIE) or ""
            except Exception:
                failures += 1
                if failures >= 3:
                    return "unavailable"
                continue
            failures = 0
            with self.lock, self.db:
                self.db.execute(
                    "INSERT OR REPLACE INTO film_title VALUES (?,?,0,?)",
                    (row["tkey"], found, time.time()),
                )
            if found and found not in have:
                try:
                    self._fetch_meta(tmdb, found)
                    have.add(found)
                except Exception:
                    failures += 1
                    if failures >= 3:
                        return "unavailable"
            self._films_changed()
            time.sleep(pause)
        with self.lock:
            wanted = [
                r[0]
                for r in self.db.execute(
                    "SELECT tmdb FROM film_title WHERE tmdb <> '' UNION"
                    " SELECT manual FROM film_release WHERE manual <> ''"
                )
            ]
        for tmdb_id in wanted:
            if tmdb_id in have:
                continue
            if stopped := spent():
                return stopped
            try:
                self._fetch_meta(tmdb, tmdb_id)
            except Exception:
                failures += 1
                if failures >= 3:
                    return "unavailable"
                continue
            failures = 0
            self._films_changed()
            time.sleep(pause)
        return "complete"

    def films_refresh(self, client_id, setup, stop: threading.Event, **identify) -> str:
        """Read the Catalogues, then identify; at most once per RUN_INTERVAL, resumable."""
        if self._films_fresh("films-run:" + client_id):
            return "waiting"
        if not self._films_working.acquire(blocking=False):
            return "waiting"  # the on-demand job is filling the index
        try:
            self.films_sync(client_id, setup, stop)
            status = self.films_identify(client_id, setup, stop, **identify)
        finally:
            self._films_working.release()
        if status == "off":
            # No TMDb key: what c411 already told us. c411's listing is the index job's to
            # walk, so this run is not recorded: it would hold that job off (`films_behind`).
            self._films_from_cache(client_id)
        if status == "complete":
            self._films_stamp("films-run:" + client_id)
        return status

    # -- Filling on demand (decision 25) -----------------------------------------------------

    def films_progress(self) -> tuple[int, int]:
        """(identified, total) titles of the index; a title TMDb answered counts as identified,
        found or not. Kept until something changes."""
        cached = self._films_status
        if cached is not None and cached[0] == self._films_generation:
            return cached[1]
        generation = self._films_generation
        with self.lock:
            total = self.db.execute(
                "SELECT COUNT(DISTINCT tkey) FROM film_release WHERE tkey <> ''"
            ).fetchone()[0]
            identified = self.db.execute(
                "SELECT COUNT(*) FROM (SELECT DISTINCT r.tkey FROM film_release r"
                " LEFT JOIN film_title t ON t.tkey = r.tkey"
                " LEFT JOIN film_meta m ON m.tmdb = t.tmdb"
                " LEFT JOIN film_c411 c ON c.tkey = r.tkey"
                " WHERE r.tkey <> '' AND (c.tkey IS NOT NULL OR (t.tkey IS NOT NULL"
                " AND (t.tmdb = '' OR m.tmdb IS NOT NULL))))"
            ).fetchone()[0]
        progress = (identified, total)
        if generation == self._films_generation:
            self._films_status = (generation, progress)
        return progress

    def films_behind(self, client_id, setup) -> bool:
        """Whether the index needs its job: the Catalogues were not read for a while, or titles
        wait for TMDb (which needs a key), else for c411's listing. Cheap; asked by every page
        that shows films."""
        if time.monotonic() < self._films_resting.get(client_id, 0.0):
            return False
        if not self._films_fresh("films-sync:" + client_id):
            return True
        identified, total = self.films_progress()
        if identified >= total or self._films_fresh("films-run:" + client_id):
            return False  # a run that ended is not repeated for a title TMDb has no facts for
        return True  # with a TMDb key, TMDb; without, c411's listing (decision 26)

    def films_index(
        self,
        client_id,
        setup,
        stop: threading.Event,
        progress,
        *,
        pause: float = IDENTIFY_PAUSE,
        walk_pause: float = WALK_PAUSE,
    ) -> str:
        """The index job: read the Catalogues, then identify in throttled batches until done.
        Each batch looks at what the user is looking at again. Without a TMDb key c411 fills
        the index instead (`films_c411`)."""
        if not self._films_working.acquire(blocking=False):
            return "busy"
        try:
            progress({"phase": "sync"})
            self.films_sync(client_id, setup, stop)
            while True:
                status = self.films_identify(
                    client_id, setup, stop, budget=float("inf"), pause=pause, limit=IDENTIFY_BATCH
                )
                done, total = self.films_progress()
                progress({"phase": "identify", "identified": done, "total": total})
                if status != "batch":
                    break
            if status == "off":
                status = self.films_c411(client_id, setup, stop, progress, walk_pause=walk_pause)
        finally:
            self._films_working.release()
        if status in {"complete", "off"}:
            self._films_stamp("films-run:" + client_id)
        elif status == "unavailable":
            self._films_resting[client_id] = time.monotonic() + UNAVAILABLE_PAUSE
        elif status == "limit":
            self._films_resting[client_id] = time.monotonic() + LIMIT_PAUSE
        return status

    # -- c411 fills the index without a TMDb key (decision 26) ---------------------------------

    def films_c411(
        self,
        client_id,
        setup,
        stop: threading.Event,
        progress,
        *,
        walk_pause: float = WALK_PAUSE,
    ) -> str:
        """Fill the index from c411, which names no TMDb id: what the suggestions already
        cached at once, then the films on screen (one search each), then c411's film listing
        walked page by page, newest first, until all of it is read; later runs only read the
        new pages. Returns "off" when c411 is not the Indexer, "limit" when c411 asks to wait
        (or refuses the key), "unavailable" after three failures, "cancelled" or "complete".
        """
        from torrentlinker.indexer import KeyRefused, RateLimited

        self._films_from_cache(client_id)
        self._films_from_details()
        self._films_stored()
        try:
            indexer = setup.indexer()
        except Exception:
            return "off"
        if not indexer.is_c411:
            return "off"
        walk_key = "films-years:" + client_id  # per-year slices; "films-walk:" was one capped walk
        with self.lock:
            row = self.db.execute("SELECT body FROM media_options WHERE key=?", (walk_key,))
            saved = row.fetchone()
        walk = json.loads(saved[0]) if saved else self._films_slices(FIRST_YEAR)
        # A finished walk starts again at the newest years, each read up to the first page that
        # adds nothing; that pass is not saved.
        fresh = walk["done"]
        if fresh:
            walk = self._films_slices(date.today().year + 2 - RECENT_YEARS, walk["capped"])
        children: list[int] | None = None
        failures = 0
        with indexer.background(stop):
            while True:
                if stop.is_set():
                    return "cancelled"
                wanted = self._films_unasked(client_id)
                try:
                    if wanted:
                        self._films_search(indexer, *wanted)
                        wait = min(walk_pause, FOCUS_PAUSE)
                    else:
                        if children is None:
                            children = self._films_children(indexer)
                        more = self._films_step(indexer, walk, children, fresh)
                        self._film_index()  # rebuilt here, not by the next page that asks
                        done, total = self.films_progress()
                        progress(
                            {
                                "phase": "c411",
                                "identified": done,
                                "total": total,
                                "capped": len(walk["capped"]),
                            }
                        )
                        if not more:
                            walk["done"] = True
                            self._films_walk(walk_key, walk)
                            return "complete"
                        if not fresh:
                            self._films_walk(walk_key, walk)
                        wait = walk_pause
                except (RateLimited, KeyRefused):
                    return "limit"
                except Exception:
                    failures += 1
                    if failures >= 3:
                        return "unavailable"
                    wait = walk_pause
                else:
                    failures = 0
                if stop.wait(wait):
                    return "cancelled"

    @staticmethod
    def _films_slices(floor: int, capped=()) -> dict[str, Any]:
        """A walk's cursor: the year (newest first, down to `floor`), the slices of that year
        still to read (`todo`), the page and order of the one being read, how many releases the
        newest end gave (`first`) and this end `seen`, and the slices both ends could not cover."""
        return {
            "year": date.today().year + 1,
            "floor": floor,
            "todo": [],
            "order": "desc",
            "page": 1,
            "first": 0,
            "seen": 0,
            "capped": list(capped),
            "done": False,
        }

    @staticmethod
    def _films_children(indexer) -> list[int]:
        """c411's native film categories, read from its own tree, not from Torznab ids."""
        from torrentlinker.catalogue_sync import SUBCATS
        from torrentlinker.torrent_search import parse_tree

        tree = parse_tree(indexer.search_categories(), adult=False)
        children = sorted(
            -key
            for key, category in tree.categories.items()
            if key < 0
            and str(category.parent) == FILM_ROOT
            and SUBCATS[int(FILM_ROOT)].get(-key) in FILM_CATEGORIES["c411"]
        )
        if not children:
            raise ValueError("c411 lists no film category.")
        return children

    def _films_step(self, indexer, walk: dict[str, Any], children: list[int], fresh: bool) -> bool:
        """One c411 request of the walk: a page of one year's slice of the film categories.
        c411 answers no page past SLICE_CAP releases, so a year with more is read per category,
        and a category still with more is read from the newest end, then from the oldest until
        the two meet (a slice they do not cover is flagged in `capped`). `fresh` only reads each
        year's newest pages. False once every year is read."""
        from torrentlinker.torrent_search import native_search

        if not walk["todo"]:
            if walk["year"] < walk["floor"]:
                return False
            walk["todo"] = [",".join(str(child) for child in children)]
        subcat = walk["todo"][0]
        params = {
            "category": FILM_ROOT,
            "subcat": subcat,
            "year": str(walk["year"]),
            "sortBy": "createdAt",
            "sortOrder": walk["order"],
        }
        page = native_search(indexer, params, walk["page"])
        changed = self._films_read(page)
        walk["seen"] += len(page.rows)
        if not fresh and walk["page"] == 1 and walk["order"] == "desc" and page.total > SLICE_CAP:
            if "," in subcat:  # too many for one search: one per film category
                walk["todo"][:1] = subcat.split(",")
                walk["seen"] = 0
                return True
        if walk["order"] == "asc":
            covered = walk["first"] + walk["seen"] >= page.total
        else:
            covered = walk["seen"] >= page.total
        if page.has_more and not covered and (changed or not fresh):
            walk["page"] += 1
            return True
        if not fresh and not covered and walk["order"] == "desc":
            walk.update(order="asc", page=1, first=walk["seen"], seen=0)
            return True
        if not covered and not fresh:
            walk["capped"].append(f"{walk['year']}:{subcat}")
        walk.update(order="desc", page=1, first=0, seen=0)
        walk["todo"].pop(0)
        if not walk["todo"]:
            walk["year"] -= 1
        return True

    def _films_walk(self, key: str, walk: dict[str, Any]) -> None:
        with self.lock, self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO media_options VALUES (?,?)", (key, json.dumps(walk))
            )

    @staticmethod
    def _c411_facts(listing) -> dict[str, Any]:
        return {
            "title": listing.title,
            "original_title": listing.original_title,
            "year": str(listing.year or ""),
            "overview": listing.overview,
            "genres": list(listing.genres),
            "runtime": listing.runtime or 0,
            "poster": listing.poster_url,
        }

    def _films_from_cache(self, client_id) -> None:
        """The facts c411's latest pages left in the suggestions, without a request."""
        found: dict[str, dict[str, Any]] = {}
        # The new releases are c411's own listing; the library's upgrades only fill what is missing.
        for kind in ("tracker-upgrade", "tracker-new"):
            for entry in self._tracker_cache(client_id, kind).values():
                facts = entry.get("facts") or {}
                title, year = facts.get("title") or "", str(facts.get("year") or "")
                if title and year:
                    found[film_key(title, year)] = {
                        "title": title,
                        "original_title": facts.get("original_title") or "",
                        "year": year,
                        "overview": facts.get("overview") or "",
                        "genres": list(facts.get("genres") or []),
                        "runtime": facts.get("runtime") or 0,
                        "poster": facts.get("poster_url") or "",
                    }
        self._films_save(found, replace=False)

    def _films_from_details(self) -> None:
        """The TMDb ids c411 already gave in the Library's cached release details: a film of
        the index with the same title and year as one of them takes that id."""
        with self.lock:
            bodies = [
                r[0]
                for r in self.db.execute(
                    "SELECT body FROM media_options WHERE key LIKE 'c411-details:%'"
                )
            ]
            open_keys = {
                r[0]
                for r in self.db.execute(
                    "SELECT DISTINCT tkey FROM film_release WHERE tkey <> ''"
                    " AND tkey NOT IN (SELECT tkey FROM film_title)"
                )
            }
        found: dict[str, str] = {}
        for body in bodies:
            details = json.loads(body)
            tmdb, year = str(details.get("id") or ""), str(details.get("year") or "")
            if not tmdb.isdigit() or not year:
                continue
            for title in (details.get("title"), details.get("originalTitle")):
                if title and (tkey := film_key(str(title), year)) in open_keys:
                    found[tkey] = tmdb
        if not found:
            return
        with self.lock, self.db:
            self.db.executemany(
                "INSERT OR IGNORE INTO film_title VALUES (?,?,0,?)",
                [(tkey, tmdb, time.time()) for tkey, tmdb in found.items()],
            )
        self._films_changed()

    def _films_read(self, page) -> bool:
        """Keep the facts of the films a listing page names; True when any film's changed.
        A release the index holds says which film key it belongs to, whatever it parsed to."""
        hashes = [c.infohash for c in page.rows if c.infohash]
        with self.lock:
            keyed = {
                r[0]: r[1]
                for r in self.db.execute(
                    "SELECT infohash, tkey FROM film_release WHERE tkey <> '' AND infohash IN"
                    f" ({','.join('?' * len(hashes))})",
                    hashes,
                )
            }
        found: dict[str, dict[str, Any]] = {}
        origin: dict[str, str] = {}
        for infohash in hashes:
            listing = page.details.get(infohash)
            if listing is None or listing.kind != "movie" or not listing.title:
                continue
            facts = self._c411_facts(listing)
            tkeys = [film_key(listing.title, facts["year"])] if listing.year else []
            tkeys += [keyed[infohash]] if infohash in keyed else []
            for tkey in tkeys:
                if tkey not in found:
                    found[tkey], origin[tkey] = facts, infohash
        return self._films_save(found, origin=origin)

    def _films_save(
        self,
        found: dict[str, dict[str, Any]],
        replace: bool = True,
        origin: dict[str, str] | None = None,
    ) -> bool:
        """Store facts by film key; `replace` False keeps the film's facts when it has some.
        The revision moves only when what a card draws changed.

        `origin` names the release each film's facts came from. Two releases of one film may
        list slightly different facts: once one wrote them, the other does not overwrite them,
        or a walk would rewrite them page after page and move the revision each time."""
        if not found:
            return False
        origin = origin or {}
        sources = self._films_sources
        entries = [
            (tkey, facts, replace and sources.get(tkey, origin.get(tkey)) == origin.get(tkey))
            for tkey, facts in found.items()
        ]
        entries += [(tkey, facts, False) for tkey, facts in self._films_by_original(found).items()]
        kept = self._films_kept([tkey for tkey, _, _ in entries])
        changed = False
        with self.lock, self.db:
            for tkey, facts, overwrite in entries:
                drawn = (
                    facts["title"],
                    facts["original_title"],
                    facts["year"],
                    facts["overview"],
                    json.dumps(facts["genres"], ensure_ascii=False),
                    facts["runtime"],
                    facts["poster"],
                )
                if kept.get(tkey) == drawn or (tkey in kept and not overwrite):
                    continue
                kept[tkey] = drawn
                if tkey in origin:
                    sources[tkey] = origin[tkey]
                self.db.execute(
                    "INSERT OR REPLACE INTO film_c411 (tkey, title, original_title, year,"
                    " overview, genres, runtime, poster, artwork, fetched)"
                    " VALUES (?,?,?,?,?,?,?,?,"
                    " (SELECT artwork FROM film_c411 WHERE tkey=? AND poster=?),?)",
                    (tkey, *drawn, tkey, facts["poster"], time.time()),
                )
                changed = True
        if changed:
            self._films_changed()
        return changed

    def _films_kept(self, tkeys: list[str]) -> dict[str, tuple]:
        """The stored facts of these films, as `_films_save` compares them."""
        kept: dict[str, tuple] = {}
        with self.lock:
            for start in range(0, len(tkeys), 500):
                chunk = tkeys[start : start + 500]
                for r in self.db.execute(
                    "SELECT tkey, title, original_title, year, overview, genres, runtime, poster"
                    f" FROM film_c411 WHERE tkey IN ({','.join('?' * len(chunk))})",
                    chunk,
                ):
                    kept[r[0]] = tuple(r[1:])
        return kept

    def _films_by_original(self, found: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """c411 names a film by its French title; another tracker's release may name it by the
        original one. The index's films keyed that way take the same facts."""
        aliases = {
            film_key(facts["original_title"], facts["year"]): facts
            for facts in found.values()
            if facts["original_title"] and facts["year"]
        }
        keys = [tkey for tkey in aliases if tkey not in found]
        held: set[str] = set()
        with self.lock:
            for start in range(0, len(keys), 500):
                chunk = keys[start : start + 500]
                held.update(
                    r[0]
                    for r in self.db.execute(
                        "SELECT DISTINCT tkey FROM film_release WHERE tkey IN"
                        f" ({','.join('?' * len(chunk))})",
                        chunk,
                    )
                )
        return {tkey: aliases[tkey] for tkey in keys if tkey in held}

    def _films_stored(self) -> None:
        """Facts stored before the original-title keys existed take those keys too."""
        with self.lock:
            found = {
                r["tkey"]: {
                    "title": r["title"],
                    "original_title": r["original_title"] or "",
                    "year": r["year"] or "",
                    "overview": r["overview"],
                    "genres": json.loads(r["genres"] or "[]"),
                    "runtime": r["runtime"],
                    "poster": r["poster"],
                }
                for r in self.db.execute("SELECT * FROM film_c411")
            }
        self._films_save(found, replace=False)

    def _films_unasked(self, client_id) -> tuple[str, str, str] | None:
        """The next film on screen c411 has no facts for and was not searched yet:
        (film key, title, year)."""
        pending = self._films_focus.get(client_id, frozenset()) - self._films_asked
        if not pending:
            return None
        with self.lock:
            for tkey in sorted(pending):
                if self.db.execute("SELECT 1 FROM film_c411 WHERE tkey=?", (tkey,)).fetchone():
                    continue
                row = self.db.execute(
                    "SELECT MIN(title) AS title, MIN(year) AS year FROM film_release WHERE tkey=?",
                    (tkey,),
                ).fetchone()
                if row and row["title"]:
                    return tkey, row["title"], row["year"]
        self._films_asked |= pending
        return None

    def _films_search(self, indexer, tkey: str, title: str, year: str) -> None:
        """One c411 search by the film's title and year, falling back to the title alone; the
        listing rows read are matched to the index by infohash or film key."""
        from torrentlinker.torrent_search import native_search

        self._films_asked.add(tkey)
        for name in (f"{title} {year}".strip(), title):
            self._films_read(native_search(indexer, {"category": "1", "name": name}, 1))
            with self.lock:
                if self.db.execute("SELECT 1 FROM film_c411 WHERE tkey=?", (tkey,)).fetchone():
                    return
            if name == title:
                return

    def films_focus(self, client_id, identifiers) -> None:
        """The films the panel shows that are not identified yet: the next batch takes them
        first. Each call replaces the last one."""
        wanted = set(list(identifiers)[:200])
        titles: set[str] = set()
        if wanted:
            for film in self._film_index():
                if film["id"] in wanted and not film["identified"]:
                    titles.update(r["tkey"] for r in film["releases"] if r["tkey"])
        self._films_focus[client_id] = frozenset(titles)

    def films_revision(self, client_id, running: bool, owner: bool) -> dict[str, Any]:
        """What the panel polls: changes whenever the index does. Only the Owner gets counts."""
        answer: dict[str, Any] = {"revision": self._films_generation, "running": running}
        if owner:
            answer["identified"], answer["total"] = self.films_progress()
        return answer

    # -- Corrections (decisions 19 and 23) -------------------------------------------------

    def _known_tmdb(self, setup, tmdb_id: str) -> str:
        """A TMDb id the Owner typed, checked against TMDb and read into `film_meta`."""
        tmdb_id = str(tmdb_id).strip()
        if not tmdb_id.isdigit():
            raise ValueError("Give a TMDb film number.")
        secrets = getattr(setup, "secrets", None)
        key = secrets.get("tmdb-api-key") if secrets is not None else ""
        if not key:
            raise ValueError("Add a TMDb key in Settings to correct a film.")
        if not self._fetch_meta(self.tmdb_client(key), tmdb_id):
            raise ValueError("TMDb does not know this film.")
        return tmdb_id

    def film_rematch(self, client_id, setup, identifier: str, tmdb_id: str) -> None:
        """The Owner re-matches a film to another TMDb film; kept across re-identification."""
        film = self._film_by_id(client_id, setup, identifier)
        tmdb_id = self._known_tmdb(setup, tmdb_id)
        with self.lock, self.db:
            for release in film["releases"]:
                if release["tkey"]:
                    self.db.execute(
                        "INSERT OR REPLACE INTO film_title VALUES (?,?,1,?)",
                        (release["tkey"], tmdb_id, time.time()),
                    )
                else:
                    self._manual(release["tracker"], release["hash"], tmdb_id)
        self._films_changed()

    def release_rematch(self, tracker: str, infohash: str, setup, tmdb_id: str) -> None:
        """ "Wrong film": one release moves to another TMDb film."""
        tmdb_id = self._known_tmdb(setup, tmdb_id)
        with self.lock, self.db:
            if not self.db.execute(
                "SELECT 1 FROM film_release WHERE tracker=? AND infohash=?", (tracker, infohash)
            ).fetchone():
                raise KeyError(infohash)
            self._manual(tracker, infohash, tmdb_id)
        self._films_changed()

    def _manual(self, tracker: str, infohash: str, tmdb_id: str) -> None:
        self.db.execute(
            "UPDATE film_release SET manual=? WHERE tracker=? AND infohash=?",
            (tmdb_id, tracker, infohash),
        )

    def film_rating(self, identifier: str, rating: str, client_id, setup) -> None:
        """The Owner sets a film's Age Rating by hand; a re-identification keeps it."""
        if age_ratings.rank(rating) is None:
            raise ValueError("Choose Tous publics, −10, −12, −16 or −18.")
        film = self._film_by_id(client_id, setup, identifier)
        if not film["tmdb"]:
            raise ValueError("Identify this film before rating it.")
        with self.lock, self.db:
            self.db.execute(
                "UPDATE film_meta SET rating=?, rating_by='person', suggestion=NULL WHERE tmdb=?",
                (rating, film["tmdb"]),
            )
        self._films_changed()

    # -- The index -------------------------------------------------------------------------

    def _film_index(self) -> list[dict[str, Any]]:
        """Every film with its releases, grouped; kept until something changes."""
        cached = self._films_cache
        if cached is not None and cached[0] == self._films_generation:
            return cached[1]
        generation = self._films_generation
        with self.lock:
            releases = self.db.execute("SELECT * FROM film_release").fetchall()
            titles = {r[0]: r[1] for r in self.db.execute("SELECT tkey, tmdb FROM film_title")}
            metas = {r["tmdb"]: r for r in self.db.execute("SELECT * FROM film_meta")}
            c411s = {r["tkey"]: r for r in self.db.execute("SELECT * FROM film_c411")}
        films: dict[str, dict[str, Any]] = {}
        for row in releases:
            tmdb = row["manual"] or titles.get(row["tkey"], "")
            if not tmdb and row["tracker"] in IDENTIFIED_ONLY:
                continue
            identifier = film_id(tmdb, row["tkey"], row["tracker"], row["infohash"])
            film = films.get(identifier)
            if film is None:
                # TMDb's facts, when it identified the film, take precedence over c411's.
                meta = metas.get(tmdb)
                facts = meta or c411s.get(row["tkey"])
                genres = json.loads(facts["genres"] or "[]") if facts else []
                film = films[identifier] = {
                    "id": identifier,
                    "tmdb": tmdb if meta else "",
                    "c411": "" if meta or not facts else row["tkey"],
                    "identified": bool(facts),
                    "title": (facts["title"] if facts else "") or row["title"] or row["name"],
                    "original_title": (facts["original_title"] if facts else "") or "",
                    "year": (facts["year"] if facts else "") or row["year"],
                    "overview": (facts["overview"] if facts else "") or "",
                    "genres": genres,
                    "runtime": (facts["runtime"] if facts else 0) or 0,
                    "rating": meta["rating"] if meta else None,
                    "poster": (facts["poster"] if facts else "") or "",
                    "releases": [],
                }
            film["releases"].append(
                {
                    "tracker": row["tracker"],
                    "hash": row["infohash"],
                    "name": row["name"],
                    "size": row["size"],
                    "seeders": row["seeders"],
                    "category": row["category"],
                    "published_at": row["published"] or None,
                    "position": row["position"],
                    "tkey": row["tkey"],
                    "download_url": row["download_url"],
                }
            )
        for film in films.values():
            members = film["releases"]
            film["published_at"] = max((r["published_at"] or 0 for r in members), default=0)
            film["seeders"] = sum(r["seeders"] for r in members)
            film["position"] = max(r["position"] for r in members)
            text = " ".join([film["title"], film["original_title"], *(r["name"] for r in members)])
            film["search"], film["raw"] = plain(text), text.casefold()
            # What `_held` looks up and the genre filter matches, once per index, not per page.
            film["keys"] = frozenset(
                film_key(title, film["year"])
                for title in (film["title"], film["original_title"])
                if title
            )
            film["genre_set"] = frozenset(film["genres"])
        index = list(films.values())
        if generation == self._films_generation:
            self._films_cache = (generation, index)
        return index

    def _film_by_id(self, client_id, setup, identifier: str) -> dict[str, Any]:
        for film in self._film_index():
            if film["id"] == identifier:
                return film
        raise KeyError(identifier)

    def _in_library(self, client_id) -> set[str]:
        """The film keys the library holds, by French and original title."""
        return set(self._library_films(client_id))

    @staticmethod
    def _held(film: dict[str, Any], library: set[str]) -> bool:
        return not library.isdisjoint(film["keys"])

    def _choose(self, setup, film: dict[str, Any]) -> dict[str, Any]:
        """The film's releases scored with the Owner's active profile, best first.

        The pre-selected one is ReleaseScore's best, a tie going to the Tracker first in the
        Owner's order, then to the better seeded release (ADR-0025). A release ReleaseScore
        cannot read ranks after those it can; a film with none readable still pre-selects
        its best seeded release, below the threshold.
        """
        preferences = setup.settings.release_score
        order = getattr(setup.settings, "tracker_order", None)
        # A film's choice holds until the index or the Owner's profile changes: a page shows
        # a film in several rows, and every page asks again.
        key = (film["id"], json.dumps([preferences, order], sort_keys=True, default=str))
        if self._films_choices[0] != self._films_generation:
            self._films_choices = (self._films_generation, {})
        choices = self._films_choices[1]
        if key not in choices:
            choices[key] = self._choose_fresh(preferences, order, film)
        return choices[key]

    def _choose_fresh(self, preferences, order, film: dict[str, Any]) -> dict[str, Any]:
        from torrentlinker.release_score.preferences import Preferences

        threshold = Preferences.model_validate(preferences).threshold
        rank = {t: i for i, t in enumerate(valid_order(order))}
        facts = {
            "title": film["title"],
            "year": film["year"],
            "runtime": film["runtime"],
            "kind": "movie",
            "tags": [],
            "genres": film["genres"],
            "rating": film["rating"],
            "overview": film["overview"],
        }
        scored = []
        for release in film["releases"]:
            result = self._score(preferences, release["name"], release["size"], facts)
            scored.append(
                {**release, "score": result.get("score"), "color": result.get("color", "")}
            )

        def preference(release: dict[str, Any]) -> tuple[float, int, int]:
            return (
                -1 if release["score"] is None else release["score"],
                -rank.get(release["tracker"], len(rank)),
                release["seeders"],
            )

        scored.sort(key=preference, reverse=True)
        chosen = scored[0]
        return {
            "releases": scored,
            "preselected": chosen,
            "below_threshold": chosen["score"] is None or chosen["score"] < threshold,
            "threshold": threshold,
        }

    def tracker_films(
        self,
        client_id,
        setup,
        *,
        genres: tuple[str, ...] = (),
        sort: str = "new",
        q: str = "",
        offset: int = 0,
        limit: int = 60,
        identified_only: bool = False,
        hide_library: bool = False,
        age_limit: int | None = None,
        choose: bool = False,
        within: list[tuple[dict[str, Any], bool]] | None = None,
    ) -> dict[str, Any]:
        """One page of Tracker Films: filtered by genres (all of them), a text search over the
        French and original title and the release names, and the Member's rules; sorted new
        (newest on the Trackers), shared (most seeders), year or title. `within` is the films
        to filter, with whether the library holds each; the whole index when None.

        Each row carries `in_library` and the release count. With `choose` it also carries the
        pre-selected release, the scored `releases` and `below_threshold`, which a Member
        never gets."""
        found = self._films_found(
            client_id,
            genres=genres,
            q=q,
            identified_only=identified_only,
            hide_library=hide_library,
            age_limit=age_limit,
            within=within,
        )
        keys = {
            "new": lambda item: (-item[0]["published_at"], -item[0]["position"]),
            "shared": lambda item: (-item[0]["seeders"], -item[0]["position"]),
            "year": lambda item: (-int(item[0]["year"] or 0), plain(item[0]["title"])),
            "title": lambda item: (plain(item[0]["title"]), item[0]["year"]),
        }
        found.sort(key=keys.get(sort, keys["new"]))
        page = found[offset : offset + limit]
        return {
            "rows": [self._film_row(setup, film, held, choose) for film, held in page],
            "total": len(found),
            "has_more": offset + limit < len(found),
            "next_offset": offset + limit if offset + limit < len(found) else None,
        }

    def _films_found(
        self,
        client_id,
        *,
        genres: tuple[str, ...] = (),
        q: str = "",
        identified_only: bool = False,
        hide_library: bool = False,
        age_limit: int | None = None,
        within: list[tuple[dict[str, Any], bool]] | None = None,
    ) -> list[tuple[dict[str, Any], bool]]:
        """The films that pass the filters, each with whether the library holds it."""
        if within is None:
            library = self._in_library(client_id)
            within = [(film, self._held(film, library)) for film in self._film_index()]
        words = plain(q).split()
        found = []
        for film, held in within:
            if identified_only and not film["identified"]:
                continue
            if not film["genre_set"].issuperset(genres):
                continue
            if age_limit is not None:
                rank = age_ratings.rank(film["rating"])
                if rank is None or rank > age_limit:
                    continue
            if words and not all(w in film["search"] for w in words):
                continue
            if q.strip() and not words and q.strip().casefold() not in film["raw"]:
                continue  # a title in a script `plain` folds away is read as it is
            if hide_library and held:
                continue
            found.append((film, held))
        return found

    def tracker_film(self, client_id, setup, identifier: str, *, choose: bool = False) -> dict:
        film = self._film_by_id(client_id, setup, identifier)
        held = self._held(film, self._in_library(client_id))
        return self._film_row(setup, film, held, choose)

    def _film_row(self, setup, film: dict[str, Any], held: bool, choose: bool) -> dict[str, Any]:
        row = {
            key: film[key]
            for key in (
                "id",
                "title",
                "original_title",
                "year",
                "overview",
                "genres",
                "runtime",
                "rating",
                "identified",
                "published_at",
                "seeders",
            )
        }
        row.update(
            poster=bool(film["poster"]),
            in_library=held,
            release_count=len(film["releases"]),
        )
        if choose:
            chosen = self._choose(setup, film)
            row.update(
                chosen,
                releases=[
                    {k: v for k, v in r.items() if k not in HIDDEN} for r in chosen["releases"]
                ],
                preselected={
                    k: v for k, v in chosen["preselected"].items() if k not in {"tkey", "position"}
                },
            )
        return row

    # -- What each role is shown -----------------------------------------------------------

    @staticmethod
    def _rules(actor) -> dict[str, Any]:
        """Which films an actor sees (decisions 11, 14 and 21): the Owner every one, with its
        releases; a Member identified films only, none already in the Library, and under an
        Age Rating limit only those rated at or under it."""
        if actor.owner:
            return {"choose": True}
        return {"identified_only": True, "hide_library": True, "age_limit": actor.age_limit}

    @staticmethod
    def _film_card(film: dict[str, Any], owner: bool) -> dict[str, Any]:
        """A film as a Médias row. The Owner's carries the pre-selected release, as a tracker
        suggestion does; a Member's only the size their quota is checked against."""
        card: dict[str, Any] = {
            "id": "film-" + film["id"],
            "kind": "video",
            "film": film["id"],
            "title": film["title"],
            "year": film["year"],
            # The Age Rating, as a library item's: the panel draws it before the year.
            "age_rating": {"rating": film["rating"], "source": "tmdb", "by": "", "suggestion": None}
            if film["rating"]
            else None,
            "genre": ", ".join(film["genres"]),
            "description": film["overview"],
            "duration": film["runtime"] * 60,
            "artwork_url": "tracker" if film["poster"] else "",
            "available": True,
            "identified": film["identified"],
        }
        chosen = film.get("preselected")
        if owner and chosen:
            card.update(
                in_library=film["in_library"],
                release_count=film["release_count"],
                below_threshold=film["below_threshold"],
                tracker={
                    **({"site": chosen["tracker"]} if chosen["tracker"] != "c411" else {}),
                    "hash": chosen["hash"],
                    "name": chosen["name"],
                    "size": chosen["size"],
                    "seeders": chosen["seeders"],
                    "score": chosen["score"],
                    "color": chosen["color"],
                    "published_at": chosen["published_at"],
                },
            )
        elif not owner:
            card["quote"] = film.get("quote")
        return card

    def _seen(self, client_id, setup, actor, **query: Any) -> dict[str, Any]:
        """A page of films for this actor. A Member's rows never name a release: they carry
        the size of the pre-selected one, which their quota is checked against."""
        rules = self._rules(actor)
        page = self.tracker_films(client_id, setup, **query, **{**rules, "choose": True})
        for film in page["rows"]:
            film["quote"] = film["preselected"]["size"]
            if not actor.owner:
                for name in ("preselected", "releases", "below_threshold", "threshold"):
                    film.pop(name, None)
        page["rows"] = [self._film_card(film, actor.owner) for film in page["rows"]]
        return page

    def films_row(self, client_id, actor, waiting: dict[str, Any]) -> dict[str, Any]:
        """Médias' "On the tracker" row, from the same index, grouping and rules as the grid
        (decision 22). While the index holds no film it keeps the state `waiting` says."""
        from torrentlinker.media_tracker import ROW_LIMIT

        page = self._seen(client_id, self.setup(client_id), actor, limit=ROW_LIMIT)  # type: ignore[attr-defined]
        if not page["rows"]:
            state = "loading" if waiting["state"] == "ready" else waiting["state"]
            return {
                **waiting,
                "rows": [],
                "total": 0,
                "state": state,
                "filters": {"tracker": "films"},
            }
        return {
            **waiting,
            "filters": {"tracker": "films"},
            "total": page["total"],
            "rows": page["rows"],
            "state": "ready",
            "reason": "",
        }

    def tracker_films_listing(
        self, client_id, setup, actor, *, genres=(), sort="new", q="", offset=0, limit=60
    ) -> dict[str, Any]:
        """The one-genre grid: paged, sorted and searched on the server. At most two genres."""
        genres = tuple(g for g in genres if g in GENRES)[:2]
        page = self._seen(
            client_id,
            setup,
            actor,
            genres=genres,
            sort=sort if sort in SORTS else "new",
            q=q,
            offset=offset,
            limit=limit,
        )
        return {**page, "filters": {"genres": list(GENRES)}}

    def tracker_films_landing(self, client_id, setup, actor, limit: int = 20) -> dict[str, Any]:
        """The landing page: what is new and most shared, then one row per genre. A grid is
        always of one genre, opened from its row, so only genre rows can be seen in full."""
        rows = []
        # The actor's films, read from the index once and split by genre for every row.
        rules = {k: v for k, v in self._rules(actor).items() if k != "choose"}
        within = self._films_found(client_id, **rules)
        by_genre: dict[str, list[tuple[dict[str, Any], bool]]] = {genre: [] for genre in GENRES}
        for item in within:
            for genre in item[0]["genre_set"] & by_genre.keys():
                by_genre[genre].append(item)
        wanted = [("tracker-new", "", {"sort": "new"}), ("tracker-shared", "", {"sort": "shared"})]
        wanted += [("genre", genre, {"genre": genre}) for genre in GENRES]
        for key, title, filters in wanted:
            genres = (filters["genre"],) if "genre" in filters else ()
            page = self._seen(
                client_id,
                setup,
                actor,
                genres=genres,
                sort=filters.get("sort", "new"),
                limit=limit,
                within=by_genre[genres[0]] if genres else within,
            )
            if page["rows"]:
                rows.append(
                    {
                        "key": key,
                        "title": title,
                        "filters": {"tracker": "films", **filters},
                        "total": page["total"],
                        "rows": page["rows"],
                    }
                )
        return {"rows": rows}

    @staticmethod
    def _may_see(film: dict[str, Any], held: bool, actor) -> bool:
        if actor.owner:
            return True
        rank = age_ratings.rank(film["rating"])
        return (
            film["identified"]
            and not held
            and (actor.age_limit is None or rank is not None and rank <= actor.age_limit)
        )

    def film_visible(self, client_id, identifier: str, actor) -> bool:
        """Whether the actor may see this film's poster: as for its page, a hidden film is as
        missing as an unknown one."""
        try:
            film = self._film_by_id(client_id, self.setup(client_id), identifier)  # type: ignore[attr-defined]
        except KeyError:
            return False
        return self._may_see(film, self._held(film, self._in_library(client_id)), actor)

    def tracker_film_detail(self, client_id, setup, actor, identifier: str) -> dict[str, Any]:
        """One film. A film a Member may not see is as missing as an unknown one. The Owner
        also gets every grouped release, the pre-selected first."""
        film = self._film_by_id(client_id, setup, identifier)
        held = self._held(film, self._in_library(client_id))
        if not self._may_see(film, held, actor):
            raise KeyError(identifier)
        row = self._film_row(setup, film, held, True)
        row["quote"] = row["preselected"]["size"]
        if not actor.owner:
            for name in ("preselected", "releases", "below_threshold", "threshold"):
                row.pop(name, None)
        card = self._film_card(row, actor.owner)
        if actor.owner:
            card["releases"] = row["releases"]
        return card

    def film_release(self, infohash: str) -> dict[str, Any] | None:
        """A Catalogue release the index holds, shaped as a tracker suggestion's entry so the
        Owner's download and an Approver's choice read it as they read one."""
        with self.lock:
            found = self.db.execute(
                "SELECT * FROM film_release WHERE infohash=? ORDER BY published DESC", (infohash,)
            ).fetchone()
        if found is None:
            return None
        release = {
            "hash": found["infohash"],
            "name": found["name"],
            "size": found["size"],
            "seeders": found["seeders"],
            "category": found["category"],
            "published_at": found["published"] or None,
        }
        if found["tracker"] != DEFAULT_TRACKER:
            release.update(tracker=found["tracker"], download_url=found["download_url"])
        return {"title": found["title"], "year": found["year"], "release": release}

    def film_artwork(self, client_id, identifier: str):
        """A film's TMDb poster, downloaded once and kept as the other posters are. A film only
        c411 knows has c411's poster, which is TMDb-hosted too: no key is needed to load it."""
        from torrentlinker import media_artwork

        film = self._film_by_id(client_id, self.setup(client_id), identifier)  # type: ignore[attr-defined]
        if not film["poster"].startswith("https://image.tmdb.org/"):
            return None
        if film["tmdb"]:
            table, column, wanted = "film_meta", "tmdb", film["tmdb"]
        elif film["c411"]:
            table, column, wanted = "film_c411", "tkey", film["c411"]
        else:
            return None
        with media_artwork.download_lock(f"film:{wanted}"):
            with self.lock:
                image = self.db.execute(
                    f"SELECT artwork FROM {table} WHERE {column}=?", (wanted,)
                ).fetchone()["artwork"]
            if not image:
                from torrentlinker.assistant.images import fetch_image

                data, _ = fetch_image(film["poster"])
                image = self.cache_artwork(data)  # type: ignore[attr-defined]
                with self.lock, self.db:
                    self.db.execute(
                        f"UPDATE {table} SET artwork=? WHERE {column}=?", (image, wanted)
                    )
        if not re.fullmatch(r"asset:[a-f0-9]{64}\.(png|webp)", image):
            return None
        return self.agent.setup.path.parent / "media-artwork" / image[6:]  # type: ignore[attr-defined]

    def film_of_release(self, infohash: str) -> str:
        """The identifier of the film a release belongs to, "" when the index holds none."""
        index = self._film_index()
        cached = getattr(self, "_release_films", None)
        if cached is None or cached[0] is not index:
            cached = self._release_films = (
                index,
                {r["hash"]: film["id"] for film in index for r in film["releases"]},
            )
        return cached[1].get(infohash, "")

    def film_for(self, client_id, title: str, year: str) -> str:
        """The index's identifier of the film a title and year name, "" when it holds none."""
        wanted = film_key(title, year)
        for film in self._film_index():
            if any(r["tkey"] == wanted for r in film["releases"]):
                return film["id"]
        return ""
