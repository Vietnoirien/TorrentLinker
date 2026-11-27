"""A Member asks for seasons of a Tracker Series; the Approver chooses; Suivre la série follows."""

import json
import time

import pytest
from fastapi.testclient import TestClient

from tests.test_members_signin import member, sign_in
from tests.test_web_jobs import login
from torrentlinker.accounts import Permission
from torrentlinker.web.app import create_app

GB = 10**9
TKEY = '["severance", "2022"]'


def add(db, number, name, pack, seasons, season=0, episode=0, size=30 * GB, seeders=20):
    db.execute(
        "INSERT OR REPLACE INTO series_release (tracker, infohash, name, size, seeders, category,"
        " kind, position, tkey, title, year, pack, seasons, season, episode)"
        " VALUES ('c411', ?, ?, ?, ?, 5000, 'series', 0, ?, 'Severance', '2022', ?, ?, ?, ?)",
        (f"{number:040x}", name, size, seeders, TKEY, pack, json.dumps(seasons), season, episode),
    )


@pytest.fixture
def server(tmp_path):
    app = create_app(
        tmp_path, members_enabled=True, password="test-password-long", monitor_verifications=False
    )
    media = app.state.agent_service.media
    with media.lock, media.db:
        db = media.db
        add(db, 1, "Severance.S01.MULTi.1080p", "season", [1])
        add(db, 2, "Severance.S02.MULTi.1080p", "season", [2])
        add(db, 3, "Severance.S03E01.MULTi.1080p", "episode", [3], 3, 1)
        db.execute(
            "INSERT OR REPLACE INTO series_title VALUES (?, '95396', 0, ?)", (TKEY, time.time())
        )
        db.execute(
            "INSERT OR REPLACE INTO series_meta (tmdb, title, original_title, year, overview,"
            " genres, status, rating, poster, fetched) VALUES ('95396', 'Severance', 'Severance',"
            " '2022', 'x', '[\"Drame\"]', 'Returning Series', '12', '', 0)"
        )
        for n in (1, 2, 3):
            db.execute(
                "INSERT OR REPLACE INTO series_season VALUES ('95396', ?, ?, 2)", (n, f"S{n}")
            )
            for e in (1, 2):
                db.execute(
                    "INSERT OR REPLACE INTO series_episode VALUES ('95396', ?, ?, 'T', 'o')", (n, e)
                )
    with TestClient(app) as browser:
        browser.headers["X-TorrentLinker"] = "1"
        yield app, browser


def lea(app, browser):
    member(app, "lea", Permission.SERIES, Permission.REQUEST)
    assert sign_in(browser, "lea").status_code == 200


def test_a_member_asks_for_two_seasons_and_never_for_the_episodes_only_one(server):
    app, browser = server
    lea(app, browser)
    panel = browser.get("/api/media/tracker-series/tv-95396").json()
    assert [s["askable"] for s in panel["seasons"]] == [True, True, False]
    quote = browser.post(
        "/api/media/tracker-series/tv-95396/quote", json={"seasons": [1, 2, 3]}
    ).json()
    assert quote["seasons"] == [1, 2] and quote["size"] == 60 * GB and not quote["integrale"]
    made = browser.post("/api/requests/series", json={"series": "tv-95396", "seasons": [1, 2, 3]})
    assert made.status_code == 200 and len(made.json()["requests"]) == 2
    rows = browser.get("/api/requests").json()["requests"]
    assert sorted(r["film"] for r in rows) == ["tv-95396:1", "tv-95396:2"]
    again = browser.post("/api/requests/series", json={"series": "tv-95396", "seasons": [1]})
    assert again.status_code == 409  # already asked for
    only = browser.post("/api/requests/series", json={"series": "tv-95396", "seasons": [3]})
    assert only.status_code == 409  # episodes only


def test_the_approver_gets_the_packs_and_the_preselection_for_each_season(server):
    app, browser = server
    lea(app, browser)
    browser.post("/api/requests/series", json={"series": "tv-95396", "seasons": [1, 2]})
    browser.cookies.clear()
    login(browser)
    rows = browser.get("/api/requests/review").json()["requests"]
    by_key = {r["film"]: r for r in rows}
    one = by_key["tv-95396:1"]
    assert one["preselected"] == f"{1:040x}" and [r["name"] for r in one["releases"]] == [
        "Severance.S01.MULTi.1080p"
    ]
    assert by_key["tv-95396:2"]["preselected"] == f"{2:040x}"


def test_following_a_series_asks_for_each_new_pack_and_notifies_the_member(server):
    app, browser = server
    lea(app, browser)
    assert browser.post(
        "/api/requests/series/follow", json={"series": "tv-95396", "on": True}
    ).json()["following"] == ["tv-95396"]
    media = app.state.agent_service.media
    assert app.state.series_follows.tick("default") == 0  # nothing new yet
    with media.lock, media.db:
        add(media.db, 4, "Severance.S03.MULTi.1080p", "season", [3])
    media._series_changed()  # the index is built once per revision
    assert app.state.series_follows.tick("default") == 1
    assert app.state.series_follows.tick("default") == 0  # once per pack
    [row] = browser.get("/api/requests").json()["requests"]
    assert row["film"] == "tv-95396:3" and row["state"] == "pending" and row["unread"]
    browser.post("/api/requests/series/follow", json={"series": "tv-95396", "on": False})
    assert browser.get("/api/requests").json()["following"] == []


def test_anime_series_are_listed_only_in_the_anime_tab_under_the_anime_permission(server):
    app, browser = server
    media = app.state.agent_service.media
    # The index is seeded by hand: a fresh sync keeps the landing from rebuilding it.
    media._series_stamp("series-sync:default")
    with media.lock, media.db:
        media.db.execute(
            "INSERT OR REPLACE INTO series_release (tracker, infohash, name, size, seeders,"
            " category, kind, position, tkey, title, year, pack, seasons, season, episode)"
            " VALUES ('c411', ?, 'Frieren.S01', ?, 9, 5070, 'anime', 0, '[\"frieren\", \"2023\"]',"
            " 'Frieren', '2023', 'season', '[1]', 0, 0)",
            (f"{9:040x}", 20 * GB),
        )
        media.db.execute(
            "INSERT OR REPLACE INTO series_title VALUES ('[\"frieren\", \"2023\"]', '209867', 0, 0)"
        )
        media.db.execute(
            "INSERT OR REPLACE INTO series_meta (tmdb, title, original_title, year, overview,"
            " genres, status, rating, poster, fetched) VALUES ('209867', 'Frieren', 'Sousou no"
            " Frieren', '2023', 'x', '[\"Animation\"]', 'Ended', 'TP', '', 0)"
        )
        media.db.execute("INSERT OR REPLACE INTO series_season VALUES ('209867', 1, 'S1', 2)")
    member(app, "ani", Permission.ANIME, Permission.REQUEST)
    assert sign_in(browser, "ani").status_code == 200
    anime = browser.get("/api/media/tracker-series/landing?scope=anime").json()
    assert [c["title"] for r in anime["rows"][:1] for c in r["rows"]] == ["Frieren"]
    assert browser.get("/api/media/tracker-series/landing?scope=series").status_code == 403
    panel = browser.get("/api/media/tracker-series/tv-209867").json()
    assert panel["series_kind"] == "anime" and panel["seasons"][0]["askable"]
    asked = browser.post("/api/requests/series", json={"series": "tv-209867", "seasons": [1]})
    assert asked.status_code == 200
    # A Séries-only Member sees neither the anime in their tab nor its panel.
    member(app, "ser", Permission.SERIES, Permission.REQUEST)
    assert sign_in(browser, "ser").status_code == 200
    assert browser.get("/api/media/tracker-series/tv-209867").status_code == 403
