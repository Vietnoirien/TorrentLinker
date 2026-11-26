"""Without a TMDb key c411 fills the film index (decision 26): the facts the suggestions already
cached, the films on screen, then c411's listing walked page by page. c411 and TMDb are fake."""

# ruff: noqa: F811  (the `films` fixture is imported, then used as an argument)

import hashlib
import json
import threading
from datetime import date
from io import BytesIO
from types import SimpleNamespace

from PIL import Image

from tests.film_support import seed_index
from tests.test_media_desktop_films import service  # noqa: F401
from tests.test_media_tracker import FakeIndexer, library  # noqa: F401
from tests.test_tracker_films import STOP, films, query  # noqa: F401
from torrentlinker import tracker_films
from torrentlinker.indexer import Candidate, KeyRefused, RateLimited
from torrentlinker.media_tracker import film_key
from torrentlinker.torrent_search import ListingRow
from torrentlinker.tracker_films import film_id

POSTER = "https://image.tmdb.org/t/p/w500/{}.jpg"
YEAR = date.today().year
# c411's tree: root 1 with its film children (6, 1, 3: Torznab 2030, 2060, 2090) and others.
TREE = {
    "data": [
        {
            "id": 1,
            "name": "Films & Séries",
            "subcategories": [{"id": n, "name": f"Sous {n}"} for n in (1, 2, 3, 6, 57)],
        },
        {"id": 2, "name": "Musique", "subcategories": [{"id": 11, "name": "Sous 11"}]},
    ]
}


class Waits(threading.Event):
    """A stop event that never sleeps, and remembers how long it was asked to."""

    def __init__(self):
        super().__init__()
        self.asked = []

    def wait(self, timeout=None):
        self.asked.append(timeout)
        return self.is_set()


def no_key(films):
    setup = films.setup_for_test
    setup.secrets = SimpleNamespace(get=lambda name: "")
    films.films_sync("default", setup)
    with films.lock, films.db:  # the scan's own run is not fresh
        films.db.execute("DELETE FROM media_options WHERE key LIKE 'films-run%'")
    return setup


def listing(title, year, **facts):
    return ListingRow(
        title=title,
        year=year,
        kind="movie",
        original_title=facts.get("original", title),
        overview=f"Synopsis de {title}.",
        genres=facts.get("genres", ("Drame",)),
        runtime=100,
        poster_url=POSTER.format(title.replace(" ", "")),
    )


def hashes(films):
    with films.lock:
        return {r["name"]: r["infohash"] for r in films.db.execute("SELECT * FROM film_release")}


def page_of(films, *rows, more=True):
    """A listing page: (release title in the index, c411's listing of its film)."""
    known = hashes(films)
    candidates = [Candidate(t, 1, "", 1, known[t], "") for t, _ in rows]
    return SimpleNamespace(
        rows=candidates,
        details={known[t]: row for t, row in rows},
        has_more=more,
        total=len(rows) + (100 if more else 0),
    )


EMPTY = SimpleNamespace(rows=[], details={}, has_more=False, total=0)


def c411(films, monkeypatch, pages):
    """c411's film listing: `pages` by number, for this year's slice only (every other year is
    empty); a search by name answers `pages["name"]`. `calls` holds those two kinds."""
    calls = []

    def search(indexer, params, page=1):
        if "name" not in params and params["year"] != str(YEAR):
            return EMPTY
        calls.append((params.get("name"), page))
        answer = pages["name" if "name" in params else page]
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(FakeIndexer, "search_categories", lambda self: TREE, raising=False)
    monkeypatch.setattr("torrentlinker.torrent_search.native_search", search)
    return calls


def facts_of(films, title):
    return next(f for f in query(films)["rows"] if f["title"] == title)


def test_the_facts_the_suggestions_already_cached_fill_the_index_at_once(films):
    setup = no_key(films)
    entry = {
        "title": "Dune",
        "year": "2021",
        "facts": {
            "title": "Dune",
            "year": 2021,
            "overview": "Un jeune duc.",
            "genres": ["Science-Fiction"],
            "runtime": 155,
            "poster_url": POSTER.format("dune"),
        },
        "releases": [],
    }
    films._tracker_save("default", "tracker-new", film_key("Dune", "2021"), entry)
    assert films.films_refresh("default", setup, STOP()) == "off"
    dune = facts_of(films, "Dune")
    assert dune["identified"] and dune["poster"] and dune["genres"] == ["Science-Fiction"]
    assert dune["overview"] == "Un jeune duc." and films.tmdb.lookups == []
    # Reading the same facts again leaves what a page draws, and so its revision, alone.
    revision = films._films_generation
    films._films_from_cache("default")
    assert films._films_generation == revision
    assert facts_of(films, "Alien")["identified"] is False
    # The Media scan's refresh runs every minute: without a key it must not hold off the index
    # job, which walks c411's listing for what is left.
    assert films.films_behind("default", setup) is True


def test_a_release_named_by_the_original_title_takes_the_facts_c411_filed_in_french(
    films, monkeypatch
):
    setup = no_key(films)
    chihiro = {
        "title": "Le Voyage de Chihiro",
        "original_title": "Spirited Away",
        "year": 2001,
        "overview": "Chihiro, dix ans.",
        "genres": ["Animation"],
        "runtime": 125,
        "poster_url": POSTER.format("chihiro"),
    }
    entry = {"title": chihiro["title"], "year": "2001", "facts": chihiro, "releases": []}
    films._tracker_save("default", "tracker-new", film_key(chihiro["title"], "2001"), entry)
    films.films_refresh("default", setup, STOP())
    found = facts_of(films, "Le Voyage de Chihiro")
    assert found["id"] == film_id("", film_key("Spirited Away", "2001"), "", "")
    assert found["overview"] == "Chihiro, dix ans."
    # Facts stored before that key existed take it on the next walk; a film not in the index
    # gets no row of its own.
    with films.lock, films.db:
        films.db.execute("DELETE FROM film_c411 WHERE tkey=?", (film_key("Spirited Away", "2001"),))
        films.db.execute("DELETE FROM media_options WHERE key LIKE 'tracker-%'")
        films.db.execute(
            "INSERT INTO film_c411 VALUES"
            " (?, 'Inconnu', 'Unknown', '1950', '', '[]', 0, '', NULL, 0)",
            (film_key("Inconnu", "1950"),),
        )
    c411(films, monkeypatch, {1: EMPTY})
    films.films_c411("default", setup, STOP(), lambda _: None, walk_pause=0)
    assert facts_of(films, "Le Voyage de Chihiro")["overview"] == "Chihiro, dix ans."
    with films.lock:
        held = {r[0] for r in films.db.execute("SELECT tkey FROM film_c411")}
    assert film_key("Unknown", "1950") not in held


def test_the_films_on_screen_are_searched_first_and_matched_by_release(films, monkeypatch):
    setup = no_key(films)
    chihiro = listing("Le Voyage de Chihiro", 2001, genres=("Animation", "Familial"))
    spirited = hashes(films)["Spirited.Away.2001.MULTi.1080p.BluRay.x264-TEAM"]
    calls = c411(
        films,
        monkeypatch,
        {
            "name": SimpleNamespace(
                rows=[Candidate("x", 1, "", 1, spirited, "")],
                details={spirited: chihiro},
                has_more=False,
            ),
            1: page_of(
                films,
                ("Alien.1979.MULTi.1080p.BluRay.x264-TEAM", listing("Alien", 1979)),
                more=False,
            ),
        },
    )
    films.films_focus("default", [f["id"] for f in query(films)["rows"] if f["title"][0] == "S"])
    assert films.films_c411("default", setup, STOP(), lambda _: None, walk_pause=0) == "complete"
    # The search came before the walk, by title and year; the release said which film it was.
    assert calls[0] == ("Spirited Away 2001", 1) and calls[1] == (None, 1)
    found = facts_of(films, "Le Voyage de Chihiro")
    assert found["identified"] and found["genres"] == ["Animation", "Familial"]
    assert found["id"] == film_id("", film_key("Spirited Away", "2001"), "", "")
    assert len([c for c in calls if c[0]]) == 1  # the others were not on screen
    assert not facts_of(films, "Mystery Film")["identified"]


def test_the_walk_reads_a_page_every_ten_seconds_and_resumes_after_c411_asks_to_wait(
    films, monkeypatch
):
    setup = no_key(films)
    alien = ("Alien.1979.MULTi.1080p.BluRay.x264-TEAM", listing("Alien", 1979))
    dune = ("Dune.2021.MULTi.1080p.WEB.x264-TEAM", listing("Dune", 2021))
    pages = {1: page_of(films, alien), 2: RateLimited(60), 3: page_of(films, dune, more=False)}
    calls = c411(films, monkeypatch, pages)
    stop, seen = Waits(), []
    assert films.films_index("default", setup, stop, seen.append) == "limit"
    assert [c[1] for c in calls] == [1, 2] and stop.asked == [10.0, 10.0]  # 2027 was empty
    assert seen[-1]["phase"] == "c411" and seen[-1]["identified"] == 1
    assert facts_of(films, "Alien")["identified"] and not facts_of(films, "Dune")["identified"]
    # c411 is left alone for an hour; then the page that failed is read again, not the first.
    assert not films.films_behind("default", setup)
    films._films_resting.clear()
    assert films.films_behind("default", setup)
    pages[2] = page_of(films, dune)
    calls.clear()
    assert films.films_index("default", setup, Waits(), seen.append) == "complete"
    assert [c[1] for c in calls] == [2, 3]
    assert query(films, identified_only=True)["total"] == 2
    # The whole listing read, only the newest pages are read again, up to one that adds nothing.
    calls.clear()
    films._films_stamp("films-run:default")
    assert not films.films_behind("default", setup)
    assert films.films_c411("default", setup, STOP(), lambda _: None, walk_pause=0) == "complete"
    assert [c[1] for c in calls] == [1]


class CappedC411:
    """c411's film listing as it is: `SLICE` releases per (year, film category), two to a page,
    and no page past CAP releases of a search, whatever its total."""

    CAP = 5
    SLICE = {(YEAR, 6): 7, (YEAR, 1): 2, (YEAR - 1, 3): 3, (YEAR - 2, 6): 12}

    def __init__(self, fail_at=None):
        self.calls, self.fail_at = [], fail_at

    def release(self, year, child, n):
        return f"Film {year} {child} {n}", hashlib.sha1(f"{year}.{child}.{n}".encode()).hexdigest()

    def __call__(self, indexer, params, page=1):
        self.calls.append((params["year"], params["subcat"], params["sortOrder"], page))
        if len(self.calls) == self.fail_at:
            raise RateLimited(60)
        wanted = [int(c) for c in params["subcat"].split(",")]
        found = [
            (n, child)
            for child in wanted
            for n in range(self.SLICE.get((int(params["year"]), child), 0))
        ]
        found.sort(reverse=params["sortOrder"] == "desc")
        reachable = found[: self.CAP]
        rows = reachable[(page - 1) * 2 : page * 2]
        names = [self.release(int(params["year"]), child, n) for n, child in rows]
        return SimpleNamespace(
            rows=[Candidate(t, 1, "", 1, h, "") for t, h in names],
            details={h: listing(t, int(params["year"])) for t, h in names},
            has_more=page * 2 < len(reachable),
            total=len(found),
        )


def test_the_walk_reads_each_year_under_c411s_paging_cap_and_flags_what_it_cannot(
    films, monkeypatch
):
    setup = no_key(films)
    monkeypatch.setattr(tracker_films, "SLICE_CAP", CappedC411.CAP)
    monkeypatch.setattr(FakeIndexer, "search_categories", lambda self: TREE, raising=False)
    fake = CappedC411()
    monkeypatch.setattr("torrentlinker.torrent_search.native_search", fake)
    films_c411 = lambda: films.films_c411(  # noqa: E731
        "default", setup, Waits(), lambda _: None, walk_pause=0
    )
    assert films_c411() == "complete"
    with films.lock:
        reached = films.db.execute("SELECT COUNT(*) FROM film_c411").fetchone()[0]
        walk = films.db.execute(
            "SELECT body FROM media_options WHERE key=?", ("films-years:default",)
        )
        state = json.loads(walk.fetchone()[0])
    # Year by year, newest first, down to 1900 (an empty year costs one request); a year with
    # more than the cap is read per film category; a category over it from both ends.
    years = [int(c[0]) for c in fake.calls]
    assert years[0] == YEAR + 1 and years == sorted(years, reverse=True) and years[-1] == 1900
    assert (str(YEAR), "1,3,6", "desc", 1) in fake.calls
    assert (str(YEAR), "6", "asc", 1) in fake.calls
    assert (str(YEAR - 1), "1,3,6", "desc", 2) in fake.calls  # under the cap: one slice
    assert (str(YEAR - 1), "3", "desc", 1) not in fake.calls
    # Every release was reached but the two c411 hides in the middle of the year's 12; those
    # are flagged, and the walk is done only then.
    assert reached == 7 + 2 + 3 + 10 and state["done"] and state["capped"] == [f"{YEAR - 2}:6"]
    # A finished walk reads the newest years again, up to a page that adds nothing.
    fake.calls.clear()
    assert films_c411() == "complete"
    assert [c[0] for c in fake.calls] == [str(YEAR + 1), str(YEAR), str(YEAR - 1)]
    assert [c[3] for c in fake.calls] == [1, 1, 1]


def test_the_walk_resumes_in_the_slice_where_c411_asked_it_to_wait(films, monkeypatch):
    setup = no_key(films)
    monkeypatch.setattr(tracker_films, "SLICE_CAP", CappedC411.CAP)
    monkeypatch.setattr(FakeIndexer, "search_categories", lambda self: TREE, raising=False)
    fake = CappedC411(fail_at=8)  # the oldest end of this year's category 6
    monkeypatch.setattr("torrentlinker.torrent_search.native_search", fake)
    assert films.films_c411("default", setup, Waits(), lambda _: None, walk_pause=0) == "limit"
    asked = fake.calls[-1]
    assert asked[2] == "asc"
    with films.lock:
        saved = films.db.execute("SELECT body FROM media_options WHERE key='films-years:default'")
        assert not json.loads(saved.fetchone()[0])["done"]
    fake.calls.clear()
    fake.fail_at = None
    assert films.films_c411("default", setup, Waits(), lambda _: None, walk_pause=0) == "complete"
    assert fake.calls[0] == asked  # the page that failed, not the year's first
    with films.lock:
        assert films.db.execute("SELECT COUNT(*) FROM film_c411").fetchone()[0] == 22


def test_the_tmdb_ids_c411_gave_in_the_library_details_go_to_the_films(films):
    no_key(films)
    details = {"id": 438631, "title": "Dune", "originalTitle": "Dune", "year": 2021}
    with films.lock, films.db:
        films.db.execute(
            "INSERT INTO media_options VALUES (?,?)",
            ("c411-details:" + "a" * 40, json.dumps(details)),
        )
    films._films_from_details()
    with films.lock:
        got = films.db.execute(
            "SELECT tmdb FROM film_title WHERE tkey=?", (film_key("Dune", "2021"),)
        )
        assert got.fetchone()[0] == "438631"
        assert films.db.execute("SELECT COUNT(*) FROM film_title").fetchone()[0] == 1


def test_a_refused_key_stops_the_walk_like_a_limit_and_other_failures_after_three(
    films, monkeypatch
):
    setup = no_key(films)
    c411(films, monkeypatch, {1: KeyRefused(401)})
    assert films.films_c411("default", setup, STOP(), lambda _: None, walk_pause=0) == "limit"
    c411(films, monkeypatch, {1: RuntimeError("down")})
    assert films.films_c411("default", setup, STOP(), lambda _: None, walk_pause=0) == (
        "unavailable"
    )
    # Stopping the job stops the walk between two pages.
    stop = STOP()
    stop.set()
    assert films.films_c411("default", setup, stop, lambda _: None) == "cancelled"


def test_c411_is_left_alone_when_it_is_not_the_indexer(films):
    setup = no_key(films)
    setup.indexer = lambda: SimpleNamespace(is_c411=False)
    assert films.films_c411("default", setup, STOP(), lambda _: None) == "off"


def test_the_revision_moves_only_when_a_drawn_fact_changes(films, monkeypatch):
    setup = no_key(films)
    row = ("Alien.1979.MULTi.1080p.BluRay.x264-TEAM", listing("Alien", 1979))
    c411(films, monkeypatch, {1: page_of(films, row, more=False)})
    films.films_c411("default", setup, STOP(), lambda _: None, walk_pause=0)
    revision = films._films_generation
    films.films_c411("default", setup, STOP(), lambda _: None, walk_pause=0)
    assert films._films_generation == revision
    c411(
        films,
        monkeypatch,
        {1: page_of(films, (row[0], listing("Alien", 1979, genres=("Horreur",))), more=False)},
    )
    films.films_c411("default", setup, STOP(), lambda _: None, walk_pause=0)
    assert films._films_generation > revision and facts_of(films, "Alien")["genres"] == ["Horreur"]


def test_a_poster_loads_without_a_tmdb_key_and_is_downloaded_once(films, monkeypatch):
    setup = no_key(films)
    c411(
        films,
        monkeypatch,
        {
            1: page_of(
                films,
                ("Alien.1979.MULTi.1080p.BluRay.x264-TEAM", listing("Alien", 1979)),
                more=False,
            )
        },
    )
    films.films_c411("default", setup, STOP(), lambda _: None, walk_pause=0)
    picture, fetched = BytesIO(), []
    Image.new("RGB", (600, 900), "#335577").save(picture, "PNG")
    monkeypatch.setattr(
        "torrentlinker.assistant.images.fetch_image",
        lambda url: fetched.append(url) or (picture.getvalue(), "image/png"),
    )
    film = facts_of(films, "Alien")["id"]
    first = films.film_artwork("default", film)
    assert first is not None and first.exists() and films.film_artwork("default", film) == first
    assert fetched == [POSTER.format("Alien")]
    assert films.film_artwork("default", facts_of(films, "Mystery Film")["id"]) is None


def test_the_scan_downloads_the_posters_the_landing_opens_on(films, monkeypatch):
    setup = no_key(films)
    alien = ("Alien.1979.MULTi.1080p.BluRay.x264-TEAM", listing("Alien", 1979))
    c411(films, monkeypatch, {1: page_of(films, alien, more=False)})
    films.films_c411("default", setup, STOP(), lambda _: None, walk_pause=0)
    picture, fetched = BytesIO(), []
    Image.new("RGB", (600, 900), "#335577").save(picture, "PNG")
    monkeypatch.setattr(
        "torrentlinker.assistant.images.fetch_image",
        lambda url: fetched.append(url) or (picture.getvalue(), "image/png"),
    )
    film = facts_of(films, "Alien")["id"]
    assert films.film_poster_entries("default") == [{"film": film}]
    films.prefetch_posters("default", STOP(), lambda _: None)
    assert fetched == [POSTER.format("Alien")]
    # Downloaded once: the next scan asks for nothing.
    assert films.film_poster_entries("default") == []


def library_body(films):
    with films.lock:
        row = films.db.execute("SELECT id, body FROM media_items").fetchone()
    return row["id"], json.loads(row["body"])


def test_library_films_and_the_index_share_film_facts_both_ways(films):
    identifier, body = library_body(films)
    assert (body["title"], body["year"]) == ("The Revenant", "2015")
    asset = "asset:" + "a" * 64 + ".webp"
    tkey = film_key("The Revenant", "2015")
    with films.lock, films.db:
        films.db.execute(
            "INSERT INTO film_c411 VALUES (?, 'The Revenant', 'The Revenant', '2015',"
            " 'Un trappeur.', '[\"Aventure\"]', 156, ?, ?, 0)",
            (tkey, POSTER.format("revenant"), asset),
        )
    # c411's release details described nothing: the index's facts fill it, its poster too.
    films.library_facts("default")
    _, body = library_body(films)
    assert body["description"] == "Un trappeur." and body["genre"] == "Aventure"
    assert body["remote_artwork"] == POSTER.format("revenant") and body["artwork"] == asset
    # A film c411's release details described gives its facts to a film the index lacks.
    described = body | {
        "title": "Heat",
        "year": "1995",
        "release_details": "e" * 40,
        "description": "Un braquage.",
        "genre": "Crime, Drame",
        "remote_artwork": POSTER.format("heat"),
    }
    with films.lock, films.db:
        films.db.execute(
            "UPDATE media_items SET body=? WHERE id=?", (json.dumps(described), identifier)
        )
    films.library_facts("default")
    with films.lock:
        heat = films.db.execute(
            "SELECT overview, genres, poster FROM film_c411 WHERE tkey=?",
            (film_key("Heat", "1995"),),
        ).fetchone()
    assert tuple(heat) == ("Un braquage.", '["Crime", "Drame"]', POSTER.format("heat"))


def test_a_tmdb_key_added_later_takes_over_and_keeps_the_owners_corrections(films, monkeypatch):
    setup = no_key(films)
    pages = [
        ("Dune.2021.MULTi.1080p.WEB.x264-TEAM", listing("Dune", 2021)),
        ("Alien.1979.MULTi.1080p.BluRay.x264-TEAM", listing("Alien", 1979)),
        ("Spirited.Away.2001.MULTi.1080p.BluRay.x264-TEAM", listing("Chihiro", 2001)),
    ]
    c411(films, monkeypatch, {1: page_of(films, *pages, more=False)})
    films.films_c411("default", setup, STOP(), lambda _: None, walk_pause=0)
    assert facts_of(films, "Dune")["id"].startswith("title-") and not films.tmdb.lookups
    setup.secrets = SimpleNamespace(get=lambda name: "tmdb-key")
    # The Owner corrects Alien by hand before TMDb is asked.
    alien = facts_of(films, "Alien")["id"]
    films.film_rematch("default", setup, alien, "9")
    assert films.films_identify("default", setup, STOP(), pause=0) == "complete"
    dune = next(f for f in query(films)["rows"] if f["id"] == "tmdb-1")
    assert dune["title"] == "Dune" and dune["rating"] == "12"  # TMDb's age rating, not c411's
    assert any(f["id"] == "tmdb-9" and f["title"] == "Autre" for f in query(films)["rows"])
    assert [t for t, _ in films.tmdb.lookups] == ["Dune", "Spirited Away"]  # Alien kept as set


def test_two_releases_of_a_film_listing_other_facts_do_not_rewrite_them_page_after_page(
    films, monkeypatch
):
    setup = no_key(films)
    first = ("Dune.2021.MULTi.1080p.WEB.x264-TEAM", listing("Dune", 2021))
    other = ("Dune.2021.MULTi.2160p.BluRay.x265-TEAM", listing("Dune", 2021, genres=("Action",)))
    c411(films, monkeypatch, {1: page_of(films, first, more=False)})
    films.films_c411("default", setup, STOP(), lambda _: None, walk_pause=0)
    revision = films._films_generation
    for _ in range(3):
        c411(films, monkeypatch, {1: page_of(films, other, more=False)})
        films.films_c411("default", setup, STOP(), lambda _: None, walk_pause=0)
        c411(films, monkeypatch, {1: page_of(films, first, more=False)})
        films.films_c411("default", setup, STOP(), lambda _: None, walk_pause=0)
    assert films._films_generation == revision
    assert facts_of(films, "Dune")["genres"] == ["Drame"]


def test_the_desktop_router_serves_the_films_c411_filled(service):
    desktop, media = service
    seed_index(media, {}, [("c411", "d" * 40, "Heat.1995.MULTi.1080p.WEB.x264-TEAM", GB, 9, "")])
    tkey = film_key("Heat", "1995")
    with media.lock, media.db:
        media.db.execute(
            "UPDATE film_release SET tkey=?, year='1995' WHERE infohash=?", (tkey, "d" * 40)
        )
    media._films_save(
        {tkey: {**media._c411_facts(listing("Heat", 1995)), "overview": "Un braquage."}}
    )
    page = desktop.request("media/tracker-films?client_id=default&q=heat")
    assert [(r["title"], r["identified"], r["artwork_url"]) for r in page["rows"]] == [
        ("Heat", True, "tracker")
    ]
    identifier = film_id("", tkey, "c411", "d" * 40)
    assert desktop.request(f"media/tracker-films/{identifier}")["description"] == "Un braquage."


GB = 10**9
