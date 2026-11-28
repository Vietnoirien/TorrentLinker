"""Without a TMDb key c411 identifies the series: its listing walked a page at a time, the
series on screen first, between the sync's batches. c411 and TMDb are fake."""

# ruff: noqa: F811  (the `series` fixture is imported, then used as an argument)

import json
import threading
from types import SimpleNamespace

from tests.test_media_tracker import library  # noqa: F401  (the series fixture needs it)
from tests.test_tracker_series import series  # noqa: F401
from torrentlinker import tracker_series
from torrentlinker import tracker_series_view as view
from torrentlinker.accounts import Actor, Permission
from torrentlinker.indexer import Candidate, RateLimited
from torrentlinker.torrent_search import ListingRow

POSTER = "https://image.tmdb.org/t/p/w500/{}.jpg"
TREE = {
    "data": [
        {
            "id": 1,
            "name": "Films & Séries",
            "subcategories": [{"id": n, "name": f"Sous {n}"} for n in (1, 2, 6, 7, 57)],
        }
    ]
}
EMPTY = SimpleNamespace(rows=[], details={}, has_more=False, total=0)


class Waits(threading.Event):
    def wait(self, timeout=None):
        return self.is_set()


def listing(title, year, **facts):
    return ListingRow(
        title=title,
        year=year,
        kind=facts.get("kind", "tv"),
        original_title=facts.get("original", title),
        overview=f"Synopsis de {title}.",
        genres=("Drame",),
        poster_url=POSTER.format(title.replace(" ", "")),
    )


def no_key(series):
    setup = series.setup_for_test
    setup.secrets = SimpleNamespace(get=lambda name: "")
    series.series_sync("default", setup)
    with series.lock, series.db:
        series.db.execute("DELETE FROM media_options WHERE key LIKE 'series-%'")
    return setup


def hash_of(series, start):
    with series.lock:
        return next(
            r[0]
            for r in series.db.execute("SELECT infohash, name FROM series_release")
            if r[1].startswith(start)
        )


def page_of(series, *rows, more=False):
    candidates = [Candidate(n, 1, "", 1, hash_of(series, n), "") for n, _ in rows]
    return SimpleNamespace(
        rows=candidates,
        details={hash_of(series, n): row for n, row in rows},
        has_more=more,
        total=len(rows),
    )


def c411(monkeypatch, pages, by_name=None):
    calls = []

    def search(indexer, params, page=1):
        if "name" in params:
            calls.append(("name", params["name"]))
            return by_name or EMPTY
        calls.append(("year", params["year"], page))
        answer = pages.get((params["year"], page), EMPTY)
        if isinstance(answer, Exception):
            raise answer
        return answer

    from tests.test_media_tracker import FakeIndexer

    monkeypatch.setattr(FakeIndexer, "search_categories", lambda self: TREE, raising=False)
    monkeypatch.setattr("torrentlinker.torrent_search.native_search", search)
    return calls


def year():
    from datetime import date

    return str(date.today().year)


def member():
    return Actor("anna", frozenset({Permission.SERIES}), age_limit=None)


def by_title(series, title):
    return next(e for e in series.series_index(fresh=True) if e["title"] == title)


def test_c411_identifies_series_without_a_key_with_poster_synopsis_genres_and_named_seasons(
    series, monkeypatch
):
    setup = no_key(series)
    arrow = listing("Arrow", 2012)
    page = page_of(series, ("Arrow.S01.MULTi", arrow))
    calls = c411(monkeypatch, {(year(), 1): page})
    status = series.series_c411("default", setup, Waits(), lambda _: None, walk_pause=0)
    assert status == "complete" and calls and series.tmdb.lookups == []
    found = by_title(series, "Arrow")
    assert found["tmdb"] == "" and found["c411"]
    assert found["meta"]["overview"] == "Synopsis de Arrow."
    assert found["meta"]["poster"].endswith("/Arrow.jpg") and found["meta"]["genres"] == '["Drame"]'
    # Members see it, with the seasons its releases name; Naruto, not listed, stays hidden.
    cards = {c["title"]: c for c in view.catalogue(series, "default", member(), "series")}
    assert set(cards) == {"Arrow"} and cards["Arrow"]["identified"] is True
    panel = view.detail(series, "default", found["id"], member())
    assert [s["n"] for s in panel["seasons"]] == [1, 2, 3, 9]
    assert {s["n"]: s["state"] for s in panel["seasons"]}[1] == "pack"
    assert series.series_progress() == (1, 3)


def test_a_listing_names_a_series_by_its_title_with_or_without_the_year(series, monkeypatch):
    setup = no_key(series)
    c411(monkeypatch, {(year(), 1): page_of(series, ("Arrow.S01.MULTi", listing("Flèche", 2012)))})
    series.series_c411("default", setup, Waits(), lambda _: None, walk_pause=0)
    assert by_title(series, "Flèche")["c411"]  # matched by release hash
    # A movie in the listing never becomes a series.
    movie = listing("Dune", 2021, kind="movie")
    c411(monkeypatch, {(year(), 1): page_of(series, ("Naruto.S01E01", movie))})
    series.series_c411("default", setup, Waits(), lambda _: None, walk_pause=0)
    assert not by_title(series, "Naruto")["c411"]


def test_the_series_on_screen_are_searched_first(series, monkeypatch):
    setup = no_key(series)
    naruto = by_title(series, "Naruto")
    series.series_focus("default", [naruto["id"]])
    found = page_of(series, ("Naruto.S01E01", listing("Naruto", 2002)))
    calls = c411(monkeypatch, {}, by_name=found)
    series.series_c411("default", setup, Waits(), lambda _: None, walk_pause=0)
    assert calls[0] == ("name", "Naruto")
    assert by_title(series, "Naruto")["c411"]
    # Asked once: a second run does not search it again.
    series.series_focus("default", [by_title(series, "Naruto")["id"]])
    assert [c for c in calls if c[0] == "name"] == [("name", "Naruto")]


def test_c411_asking_to_wait_stops_the_job_for_an_hour(series, monkeypatch):
    setup = no_key(series)
    c411(monkeypatch, {(year(), 1): RateLimited(30)})
    assert series.series_index_job("default", setup, Waits(), lambda _: None) == "limit"
    assert series._series_resting["default"] > 0
    assert not series.series_behind("default", setup)


def test_the_walk_is_resumable_and_a_finished_one_only_reads_the_new_pages(series, monkeypatch):
    setup = no_key(series)
    calls = c411(monkeypatch, {})
    assert series.series_c411("default", setup, Waits(), lambda _: None, walk_pause=0) == "complete"
    first = len(calls)
    assert first > 70  # every year since FIRST_YEAR, one request each
    saved = json.loads(
        series.db.execute(
            "SELECT body FROM media_options WHERE key='series-years:default'"
        ).fetchone()[0]
    )
    assert saved["done"] is True
    calls.clear()
    series.series_c411("default", setup, Waits(), lambda _: None, walk_pause=0)
    assert 0 < len(calls) <= 6  # only the newest years


def test_series_are_identified_between_the_sync_batches(series, monkeypatch):
    setup = no_key(series)
    with series.lock, series.db:
        series.db.execute("DELETE FROM series_release")
    monkeypatch.setattr(tracker_series, "SYNC_BATCH", 3)
    seen = []
    original = series.series_sync

    def sync(client_id, setup, stop=None, between=None):
        def hook():
            seen.append(series.db.execute("SELECT COUNT(*) FROM series_release").fetchone()[0])
            between()

        return original(client_id, setup, stop, hook)

    series.series_sync = sync

    # c411 answers a page listing the first release of the sync.
    def search(indexer, params, page=1):
        with series.lock:
            row = series.db.execute(
                "SELECT infohash, name FROM series_release WHERE name LIKE 'Arrow.S01.%'"
            ).fetchone()
        if row is None or "name" in params or params["year"] != year() or page != 1:
            return EMPTY
        return SimpleNamespace(
            rows=[Candidate(row[1], 1, "", 1, row[0], "")],
            details={row[0]: listing("Arrow", 2012)},
            has_more=False,
            total=1,
        )

    from tests.test_media_tracker import FakeIndexer

    monkeypatch.setattr(FakeIndexer, "search_categories", lambda self: TREE, raising=False)
    monkeypatch.setattr("torrentlinker.torrent_search.native_search", search)
    status = series.series_index_job("default", setup, Waits(), lambda _: None, walk_pause=0)
    assert status == "complete" and len(seen) >= 2 and seen[0] < seen[-1]
    assert by_title(series, "Arrow")["c411"]


def test_series_are_identified_between_the_sync_batches_with_a_tmdb_key(series, monkeypatch):
    with series.lock, series.db:
        series.db.execute("DELETE FROM series_release")
        series.db.execute("DELETE FROM series_title")
    monkeypatch.setattr(tracker_series, "SYNC_BATCH", 3)
    held = []
    original = series.series_identify

    def identify(*args, **kwargs):
        held.append(kwargs.get("limit"))
        return original(*args, **kwargs)

    series.series_identify = identify
    series.series_index_job(
        "default", series.setup_for_test, threading.Event(), lambda _: None, pause=0
    )
    assert tracker_series.SYNC_IDENTIFY in held  # asked during the sync, a few at a time
    assert by_title(series, "Arrow")["tmdb"] == "10"


def test_a_key_set_later_takes_over_and_an_id_c411_gave_is_kept(series, monkeypatch):
    setup = no_key(series)
    c411(monkeypatch, {(year(), 1): page_of(series, ("Arrow.S01.MULTi", listing("Arrow", 2012)))})
    series.series_c411("default", setup, Waits(), lambda _: None, walk_pause=0)
    # The Library's cached c411 details gave Naruto's TMDb id.
    with series.lock, series.db:
        series.db.execute(
            "INSERT INTO media_options VALUES ('c411-details:abc', ?)",
            (json.dumps({"id": 20, "type": "tv", "title": "Naruto", "year": 2002}),),
        )
        series.db.execute(
            "INSERT INTO media_options VALUES ('c411-details:def', ?)",
            (json.dumps({"id": 99, "type": "movie", "title": "Dune", "year": 2021}),),
        )
    series._series_from_details()
    assert by_title(series, "Naruto")["tmdb"] == "20"
    # The key arrives: TMDb's facts replace c411's, the id c411 gave stays.
    setup.secrets = SimpleNamespace(get=lambda name: "tmdb-key")
    stop = threading.Event()
    assert series.series_identify("default", setup, stop, pause=0) == "complete"
    arrow, naruto = by_title(series, "Arrow"), by_title(series, "Naruto")
    assert arrow["tmdb"] == "10" and arrow["c411"] == "" and arrow["meta"]["rating"] == "12"
    assert naruto["tmdb"] == "20" and naruto["meta"]["overview"] == "Synopsis de Naruto."
    assert series.tmdb.lookups == [("Arrow", None)] or ("Naruto", None) not in series.tmdb.lookups


def test_names_spelling_one_series_two_ways_are_one_series_once_c411_knows_it(series):
    """'Dexter Resurrection 2025' and 'Dexter: Résurrection' are one series, once c411 gave
    both the same facts: one card, its releases together, and a stable id."""
    with series.lock, series.db:
        for n, (name, title, year) in enumerate(
            (("Dexter.Resurrection.2025.S01.1080p", "Dexter Resurrection", "2025"),
             ("Dexter.Resurrection.S01E02.1080p", "Dexter Résurrection", ""))
        ):  # fmt: skip
            tkey = tracker_series.series_key(title, year)
            series.db.execute(
                "INSERT INTO series_release (tracker, infohash, name, size, seeders, category,"
                " kind, position, tkey, title, year, pack, seasons, season, episode)"
                " VALUES ('c411', ?, ?, 1, 5, 5000, 'series', ?, ?, ?, ?, 'season', '[1]', 0, 0)",
                (f"{n:040x}", name, n, tkey, title, year),
            )
            series.db.execute(
                "INSERT INTO series_c411 (tkey, title, original_title, year, overview, genres,"
                " poster, fetched) VALUES (?, 'Dexter - Résurrection', '', '2025', '', '[]', ?, 0)",
                (tkey, POSTER.format("dexter")),
            )
    series._series_changed()
    dexter = [e for e in series.series_index(fresh=True) if "Dexter" in e["title"]]
    assert len(dexter) == 1 and len(dexter[0]["releases"]) == 2
    assert dexter[0]["id"] == min(
        tracker_series.series_id("", tracker_series.series_key(t, y), "", "")
        for t, y in (("Dexter Resurrection", "2025"), ("Dexter Résurrection", ""))
    )
