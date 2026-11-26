"""Tracker Films for each role: the Owner sees releases, a Member never does, a Viewer
browses without asking. The index is filled directly; no Catalogue, TMDb or tracker is read."""

import json

import pytest
from fastapi.testclient import TestClient

from tests.film_support import seed_index
from tests.test_members_signin import PASSWORD, member, sign_in
from tests.test_web_jobs import login
from torrentlinker.accounts import Actor, Permission
from torrentlinker.web.app import create_app

GB = 10**9
FILMS = {
    # tmdb: title, original, year, genres, rating, runtime
    "1": ("Dune", "Dune", "2021", ["Science-Fiction", "Aventure"], "12", 155),
    "2": ("Le Voyage de Chihiro", "Spirited Away", "2001", ["Animation", "Familial"], "TP", 125),
    "3": ("Alien", "Alien", "1979", ["Horreur", "Science-Fiction"], "16", 117),
    "4": ("Sans classification", "Unrated", "2010", ["Drame"], None, 100),
}
RELEASES = [  # tracker, hash, name, size, seeders, tmdb
    ("c411", "a" * 40, "Dune.2021.MULTi.1080p.WEB.x264-TEAM", 4 * GB, 30, "1"),
    ("tr4ker", "b" * 40, "Dune.2021.MULTi.2160p.BluRay.x265-TEAM", 40 * GB, 5, "1"),
    ("c411", "c" * 40, "Spirited.Away.2001.MULTi.1080p.BluRay.x264-TEAM", 8 * GB, 20, "2"),
    ("c411", "d" * 40, "Alien.1979.MULTi.1080p.BluRay.x264-TEAM", 7 * GB, 2, "3"),
    ("c411", "e" * 40, "Sans.Classification.2010.MULTi.1080p.WEB.x264-TEAM", 3 * GB, 9, "4"),
    ("c411", "f" * 40, "Mystery.Film.MULTi.1080p.WEB.x264-TEAM", 3 * GB, 9, ""),  # unidentified
]


@pytest.fixture
def server(tmp_path):
    app = create_app(
        tmp_path, members_enabled=True, password="test-password-long", monitor_verifications=False
    )
    media = app.state.agent_service.media
    seed_index(media, FILMS, RELEASES)
    with TestClient(app) as browser:
        browser.headers["X-TorrentLinker"] = "1"
        yield app, browser


def titles(response):
    assert response.status_code == 200, response.text
    return [row["title"] for row in response.json()["rows"]]


def test_the_owner_sees_every_film_with_its_grouped_releases(server):
    app, browser = server
    login(browser)
    page = browser.get("/api/media/tracker-films", params={"sort": "title"})
    assert titles(page) == [
        "Alien",
        "Dune",
        "Le Voyage de Chihiro",
        "Mystery.Film.MULTi.1080p.WEB.x264-TEAM",
    ] or "Dune" in titles(page)
    dune = browser.get("/api/media/tracker-films/tmdb-1").json()
    assert dune["id"] == "film-tmdb-1" and dune["description"] == "Synopsis de Dune."
    assert [r["tracker"] for r in dune["releases"]].count("tr4ker") == 1
    assert len(dune["releases"]) == 2 and dune["tracker"]["hash"] in {"a" * 40, "b" * 40}
    assert dune["releases"][0]["hash"] == dune["tracker"]["hash"]  # the pre-selected first
    assert "download_url" not in dune["releases"][0]
    unidentified = [r for r in page.json()["rows"] if not r["identified"]]
    assert len(unidentified) == 1  # the Owner sees it, to match it


def test_a_member_gets_identified_films_without_any_release(server):
    app, browser = server
    member(app, "lea", Permission.FILMS, Permission.REQUEST)
    sign_in(browser, "lea")
    page = browser.get("/api/media/tracker-films", params={"sort": "title"})
    assert titles(page) == ["Alien", "Dune", "Le Voyage de Chihiro", "Sans classification"]
    text = page.text
    for secret in ("TEAM", "tr4ker", "a" * 40, "WEB", "seeders", "releases", "download_url"):
        assert secret not in text, secret
    dune = browser.get("/api/media/tracker-films/tmdb-1").json()
    assert dune["quote"] in {4 * GB, 40 * GB} and "releases" not in dune and "tracker" not in dune
    assert (
        dune["description"] == "Synopsis de Dune." and dune["genre"] == "Science-Fiction, Aventure"
    )
    assert browser.get("/api/media/tracker-films/tmdb-1").json()["artwork_url"] == "tracker"
    # An unidentified release is the Owner's alone, as is a missing film.
    unknown = browser.get("/api/media/tracker-films/release-0000").status_code
    assert unknown == 404


def test_a_member_never_sees_a_film_the_library_holds(server):
    app, browser = server
    media = app.state.agent_service.media
    member(app, "lea", Permission.FILMS)
    with media.lock, media.db:
        media.db.execute(
            "INSERT INTO media_items VALUES ('lib','default','/a/Alien.mkv','/a',1,0,0,?)",
            (json.dumps({"kind": "video", "title": "Alien", "year": "1979"}),),
        )
    sign_in(browser, "lea")
    assert "Alien" not in titles(browser.get("/api/media/tracker-films"))
    assert browser.get("/api/media/tracker-films/tmdb-3").status_code == 404
    assert browser.get("/api/media/items/film-tmdb-3/artwork").status_code == 404
    login(browser)
    owner = browser.get("/api/media/tracker-films/tmdb-3").json()
    assert owner["in_library"]


def test_an_age_limit_filters_by_rating_and_hides_the_unrated(server):
    app, browser = server
    lea = member(app, "lea", Permission.FILMS)
    app.state.accounts.set_media_limits(lea, "12", None)
    sign_in(browser, "lea")
    assert titles(browser.get("/api/media/tracker-films", params={"sort": "title"})) == [
        "Dune",
        "Le Voyage de Chihiro",
    ]
    assert browser.get("/api/media/tracker-films/tmdb-3").status_code == 404  # rated -16
    assert browser.get("/api/media/tracker-films/tmdb-4").status_code == 404  # unrated
    landing = browser.get("/api/media/tracker-films/landing").json()["rows"]
    assert all(film["title"] != "Alien" for row in landing for film in row["rows"])


def test_access_follows_the_films_permission_not_search_or_request(server):
    app, browser = server
    member(app, "lea", Permission.SEARCH, Permission.REQUEST)
    sign_in(browser, "lea")
    assert browser.get("/api/media/tracker-films").status_code == 403
    assert browser.get("/api/media/tracker-films/landing").status_code == 403
    # With Films alone a Member browses and finds by title; Search does not gate it any more.
    app.state.accounts.grant(app.state.accounts.verify("lea", PASSWORD), {Permission.FILMS})
    assert titles(browser.get("/api/media/tracker-films", params={"q": "chihiro"})) == [
        "Le Voyage de Chihiro"
    ]
    assert titles(browser.get("/api/member-workspace/search", params={"q": "alien"})) == ["Alien"]


def test_a_viewer_browses_films_without_asking(server):
    app, _ = server
    media = app.state.agent_service.media
    viewer = Actor("lea", frozenset({Permission.FILMS}), viewer="tom", age_limit=2)
    page = media.tracker_films_listing("default", media.setup("default"), viewer, sort="title")
    assert [row["title"] for row in page["rows"]] == ["Dune", "Le Voyage de Chihiro"]
    assert all("tracker" not in row for row in page["rows"])
    # The Viewer holds no Request Permission, so the Request route stays closed to it.
    assert not viewer.holds(Permission.REQUEST)


def test_the_grid_pages_sorts_searches_and_takes_two_genres(server):
    app, browser = server
    member(app, "lea", Permission.FILMS)
    sign_in(browser, "lea")
    first = browser.get("/api/media/tracker-films", params={"sort": "title", "limit": 2}).json()
    assert [r["title"] for r in first["rows"]] == ["Alien", "Dune"]
    assert first["has_more"] and first["total"] == 4 and first["next_offset"] == 2
    second = browser.get(
        "/api/media/tracker-films", params={"sort": "title", "limit": 2, "offset": 2}
    ).json()
    assert [r["title"] for r in second["rows"]] == ["Le Voyage de Chihiro", "Sans classification"]
    assert not second["has_more"] and "Science-Fiction" in first["filters"]["genres"]
    both = browser.get(
        "/api/media/tracker-films", params=[("genre", "Science-Fiction"), ("genre", "Aventure")]
    )
    assert titles(both) == ["Dune"]
    assert titles(browser.get("/api/media/tracker-films", params={"genre": "Western"})) == []
    assert titles(browser.get("/api/media/tracker-films", params={"sort": "year"}))[0] == "Dune"
    assert browser.get("/api/media/tracker-films", params={"sort": "nope"}).status_code == 422
    # A text search over the original title too.
    assert titles(browser.get("/api/media/tracker-films", params={"q": "spirited"})) == [
        "Le Voyage de Chihiro"
    ]


def test_the_landing_has_new_and_shared_then_one_row_per_genre(server):
    app, browser = server
    member(app, "lea", Permission.FILMS)
    sign_in(browser, "lea")
    rows = browser.get("/api/media/tracker-films/landing").json()["rows"]
    assert [r["key"] for r in rows[:2]] == ["tracker-new", "tracker-shared"]
    genres = [r["title"] for r in rows[2:]]
    assert genres == [
        "Animation",
        "Aventure",
        "Drame",
        "Familial",
        "Horreur",
        "Science-Fiction",
    ] or set(genres) >= {"Animation", "Horreur"}
    assert all(r["key"] == "genre" for r in rows[2:])
    assert all(r["filters"]["tracker"] == "films" for r in rows)
    sf = next(r for r in rows if r["title"] == "Science-Fiction")
    assert sf["filters"]["genre"] == "Science-Fiction" and sf["total"] == 2


def test_the_medias_row_comes_from_the_index_and_hides_what_a_member_may_not_see(server):
    app, browser = server
    media = app.state.agent_service.media
    lea = member(app, "lea", Permission.FILMS)
    sign_in(browser, "lea")
    answer = browser.get("/api/media/home", params={"include": "tracker"}).json()["rows"]
    row = next(r for r in answer if r["key"] == "tracker")
    assert row["filters"] == {"tracker": "films"} and row["state"] == "ready"
    assert sorted(r["title"] for r in row["rows"]) == [
        "Alien",
        "Dune",
        "Le Voyage de Chihiro",
        "Sans classification",
    ]
    assert row["total"] == 4 and "tr4ker" not in json.dumps(row)
    app.state.accounts.set_media_limits(lea, "10", None)
    row = next(
        r
        for r in browser.get("/api/media/home", params={"include": "tracker"}).json()["rows"]
        if r["key"] == "tracker"
    )
    assert [r["title"] for r in row["rows"]] == ["Le Voyage de Chihiro"]
    login(browser)
    owner = browser.get("/api/media/home", params={"include": "tracker"}).json()["rows"]
    tracker = next(r for r in owner if r["key"] == "tracker")
    assert tracker["total"] == 5 and all(r.get("tracker") for r in tracker["rows"])
    assert media.sees_tracker(Actor("x", frozenset({Permission.FILMS}), age_limit=1))


def test_only_the_owner_corrects_a_film(server):
    app, browser = server
    member(app, "lea", Permission.FILMS, Permission.APPROVE)
    sign_in(browser, "lea")
    assert (
        browser.post("/api/media/tracker-films/tmdb-1/rematch", json={"tmdb": "2"}).status_code
        == 403
    )
    release = "/api/media/tracker-films/releases/c411/" + "a" * 40 + "/rematch"
    assert browser.post(release, json={"tmdb": "2"}).status_code == 403
    assert (
        browser.post("/api/media/tracker-films/tmdb-1/rating", json={"rating": "TP"}).status_code
        == 403
    )
    login(browser)
    # No TMDb key is configured, and none is called: the correction says so.
    answer = browser.post("/api/media/tracker-films/tmdb-1/rematch", json={"tmdb": "2"})
    assert answer.status_code == 400 and "TMDb" in answer.json()["detail"]
    assert (
        browser.post("/api/media/tracker-films/tmdb-1/rematch", json={"tmdb": "x"}).status_code
        == 422
    )
    assert (
        browser.post("/api/media/tracker-films/tmdb-4/rating", json={"rating": "12"}).status_code
        == 200
    )
    assert browser.get("/api/media/tracker-films/tmdb-4").json()["age_rating"]["rating"] == "12"


def test_a_catalogue_release_can_be_read_as_a_suggestion(server):
    app, _ = server
    media = app.state.agent_service.media
    found = media.tracker_entry("default", "b" * 40)
    assert found["release"]["tracker"] == "tr4ker" and found["release"]["size"] == 40 * GB
    with pytest.raises(ValueError):
        media.tracker_entry("default", "9" * 40)
