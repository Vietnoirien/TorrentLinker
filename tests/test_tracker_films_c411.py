"""Without a TMDb key c411 fills the film index (decision 26): the facts the suggestions already
cached, the films on screen, then c411's listing walked page by page. c411 and TMDb are fake."""

# ruff: noqa: F811  (the `films` fixture is imported, then used as an argument)

import threading
from io import BytesIO
from types import SimpleNamespace

from PIL import Image

from tests.film_support import seed_index
from tests.test_media_desktop_films import service  # noqa: F401
from tests.test_media_tracker import FakeIndexer, library  # noqa: F401
from tests.test_tracker_films import STOP, films, query  # noqa: F401
from torrentlinker.indexer import Candidate, KeyRefused, RateLimited
from torrentlinker.media_tracker import film_key
from torrentlinker.torrent_search import ListingRow
from torrentlinker.tracker_films import film_id

POSTER = "https://image.tmdb.org/t/p/w500/{}.jpg"


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
        rows=candidates, details={known[t]: row for t, row in rows}, has_more=more
    )


def c411(films, monkeypatch, pages):
    """c411's film listing: `pages` by number; a search by name answers `pages["name"]`."""
    calls = []

    def search(indexer, params, page=1):
        calls.append((params.get("name"), page))
        answer = pages["name" if "name" in params else page]
        if isinstance(answer, Exception):
            raise answer
        return answer

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
    assert [c[1] for c in calls] == [1, 2] and stop.asked == [10.0]
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
