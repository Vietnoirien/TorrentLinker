"""The Tracker Series catalogue Médias shows: tabs, owned seasons, Age Rating, releases."""

from __future__ import annotations

import json
import sqlite3
import threading
from types import SimpleNamespace

import pytest

from torrentlinker import tracker_series_view as view
from torrentlinker.accounts import OWNER_ACTOR, Actor, Permission


def release(name, pack, seasons=(), season=0, episode=0, seeders=5, tracker="c411"):
    return {
        "infohash": name.lower(), "name": name, "size": 10**9, "seeders": seeders,
        "tracker": tracker, "pack": pack, "seasons": tuple(seasons), "season": season,
        "episode": episode, "kind": "series",
    }  # fmt: skip


def entry(identifier, title, releases, kind="series", rating="12", tmdb="1"):
    return {
        "id": identifier, "tmdb": tmdb, "title": title, "kind": kind, "releases": releases,
        "meta": {"year": "2020", "rating": rating, "genres": json.dumps(["Drame"]),
                 "overview": "Synopsis", "poster": "", "status": "Ended"},
    }  # fmt: skip


@pytest.fixture
def media():
    db = sqlite3.connect(":memory:", check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.executescript(
        """
        CREATE TABLE media_items (id TEXT, client TEXT, path TEXT, body TEXT);
        CREATE TABLE series_season (tmdb TEXT, season INTEGER, name TEXT, episodes INTEGER);
        CREATE TABLE series_episode (tmdb TEXT, season INTEGER, episode INTEGER, title TEXT,
            overview TEXT);
        INSERT INTO series_season VALUES ('1', 1, 'S1', 2), ('1', 2, 'S2', 2), ('1', 3, 'S3', 2);
        INSERT INTO series_episode VALUES ('1', 3, 1, 'Un', 'o1'), ('1', 3, 2, 'Deux', 'o2'),
            ('1', 1, 1, 'A', 'a'), ('1', 1, 2, 'B', 'b'), ('1', 2, 1, 'C', 'c'),
            ('1', 2, 2, 'D', 'd');
        INSERT INTO media_items VALUES ('m1', 'c', '/lib/s1e1.mkv',
            '{"kind": "video", "series": "Show", "season": 1, "tmdb_id": "1"}');
        """
    )
    series = [
        entry(
            "a",
            "Show",
            [
                release("Show.S01.MULTi", "season", (1,)),
                release("Show.S03E01", "episode", (3,), 3, 1),
                release("Show.S03E02", "episode", (3,), 3, 2),
            ],
        ),
        entry("b", "Anime One", [release("Anime.S01", "season", (1,))], kind="anime", tmdb="2"),
        entry("c", "Unrated", [release("Unrated.S01", "season", (1,))], rating=None, tmdb="3"),
        entry("d", "Unknown", [release("Unknown.S01", "season", (1,))], tmdb=""),
    ]
    return SimpleNamespace(db=db, lock=threading.RLock(), series_index=lambda: series)


def member(limit=None):
    return Actor("anna", frozenset({Permission.SERIES}), age_limit=limit)


def titles(cards):
    return [c["title"] for c in cards]


def test_the_series_tab_and_the_anime_tab_list_their_own_series(media):
    assert titles(view.catalogue(media, "c", OWNER_ACTOR, "series")) == [
        "Show",
        "Unrated",
        "Unknown",
    ]
    assert titles(view.catalogue(media, "c", OWNER_ACTOR, "anime")) == ["Anime One"]


def test_a_member_sees_identified_series_under_their_age_limit_and_not_the_fully_owned(media):
    assert titles(view.catalogue(media, "c", member(), "series")) == ["Show", "Unrated"]
    assert titles(view.catalogue(media, "c", member(1), "series")) == []  # 12 and none: hidden
    assert titles(view.catalogue(media, "c", member(2), "series")) == ["Show"]  # unrated: hidden
    for identifier, season in (("m2", 2), ("m3", 3)):
        body = json.dumps({"kind": "video", "series": "Show", "season": season})
        media.db.execute("INSERT INTO media_items VALUES (?, 'c', '/x', ?)", (identifier, body))
    assert "Show" not in titles(view.catalogue(media, "c", member(), "series"))  # all three owned
    owner = {c["title"]: c for c in view.catalogue(media, "c", OWNER_ACTOR, "series")}
    assert owner["Show"]["in_library"] and owner["Show"]["owned_seasons"] == [1, 2, 3]


def test_the_panel_marks_owned_seasons_and_greys_a_season_with_episodes_only(media):
    panel = view.detail(media, "c", "a", member())
    one, two, three = panel["seasons"]
    assert one["owned"] and not one["askable"]  # in the Library
    assert two["state"] == "none" and not two["askable"]
    assert three["state"] == "episodes" and not three["askable"]  # a Member cannot ask for it
    assert [e["on_tracker"] for e in three["episodes"]] == [True, True]
    assert all("releases" not in s for s in panel["seasons"])  # never a release for a Member


def test_a_pack_can_be_asked_for_and_the_owner_sees_every_release(media):
    media.db.execute("DELETE FROM media_items")
    panel = view.detail(media, "c", "a", member())
    assert panel["seasons"][0]["state"] == "pack" and panel["seasons"][0]["askable"]
    owner = view.detail(media, "c", "a", OWNER_ACTOR)
    assert [r["name"] for r in owner["seasons"][2]["releases"]] == ["Show.S03E01", "Show.S03E02"]
    assert owner["seasons"][0]["releases"][0]["kind"] == "season"


def test_a_hidden_series_is_as_missing_as_an_unknown_one(media):
    with pytest.raises(KeyError):
        view.detail(media, "c", "d", member())  # unidentified
    with pytest.raises(KeyError):
        view.detail(media, "c", "nope", OWNER_ACTOR)


def test_the_landing_has_the_tracker_row_then_a_row_per_genre(media):
    landing = view.landing(view.catalogue(media, "c", member(), "series"))
    assert [r["key"] for r in landing["rows"]] == ["tracker", "genre"]
    assert landing["rows"][1]["title"] == "Drame"
    page = view.grid(
        view.catalogue(media, "c", member(), "series"), ["Drame"], "title", "unr", 0, 10
    )
    assert titles(page["rows"]) == ["Unrated"] and page["total"] == 1
