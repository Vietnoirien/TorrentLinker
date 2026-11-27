"""The Tracker Series index: releases classified as season packs, Intégrales or episodes,
grouped per series, identified in the background and checked against TMDb's seasons."""

import threading
from types import SimpleNamespace

import pytest

from tests.test_media_tracker import library, setup_with  # noqa: F401  (the library fixture)
from torrentlinker.store import CatalogueRow, Store
from torrentlinker.tmdb import TmdbInfo
from torrentlinker.tracker_series import SeriesRelease, parse_series_release

GB = 1024**3


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        (
            "Wonderboys.2024.S01.MULTI.VFF.1080p.WEBRip.EAC3.5.1.AV1-TAW",
            SeriesRelease("Wonderboys", "2024", "season", (1,)),
        ),
        (
            "Stargate.Universe.S02E05.MULTI.VFF.1080p.WEB.DDP.5.1.H265-CHiLL",
            SeriesRelease("Stargate Universe", "", "episode", (2,), 2, 5),
        ),
        (
            "Arrow.S01-S08.INTEGRALE.MULTi.1080p-X",
            SeriesRelease("Arrow", "", "complete", tuple(range(1, 9))),
        ),
        (
            "Game.of.Thrones.Integrale.MULTi.1080p",
            SeriesRelease("Game of Thrones", "", "complete", ()),
        ),
        ("Friends.Complete.Series.1080p", SeriesRelease("Friends", "", "complete", ())),
        (
            "The.Wire.S01.S02.S03.COMPLETE.1080p",
            SeriesRelease("The Wire", "", "complete", (1, 2, 3)),
        ),
        (
            "Breaking Bad Saisons 1 à 5 FRENCH 720p",
            SeriesRelease("Breaking Bad", "", "complete", (1, 2, 3, 4, 5)),
        ),
        ("Show.S03.COMPLETE.1080p", SeriesRelease("Show", "", "season", (3,))),
        ("Dark.S01E01E02.MULTI", SeriesRelease("Dark", "", "episode", (1,), 1, 1)),
        ("Les touristes - Mission pompiers HDTV 720p", SeriesRelease("Les touristes", "", "", ())),
    ],
)
def test_a_release_name_is_a_season_pack_an_integrale_or_an_episode(name, expected):
    assert parse_series_release(name) == expected


class FakeTmdb:
    """TMDb as it answers for two series; it counts what it was asked."""

    SERIES = {
        "10": ("Arrow", "Arrow", "2012", [("1", 3), ("2", 2)]),
        "20": ("Naruto", "Naruto", "2002", [("1", 2)]),
    }
    LOOKUP = {("arrow", None): "10", ("naruto", None): "20", ("wonderboys", 2024): ""}

    def __init__(self):
        self.lookups, self.kinds = [], []

    def lookup(self, title, year, kind):
        self.lookups.append((title, year))
        self.kinds.append(str(kind))
        return self.LOOKUP.get((title.lower(), year))

    def details(self, tmdb_id, media_type):
        assert media_type == "tv"
        title, original, year, seasons = self.SERIES[tmdb_id]
        raw = {
            "genres": [{"id": 1, "name": "Action"}],
            "poster_path": f"/s{tmdb_id}.jpg",
            "status": "Returning Series",
            "seasons": [{"season_number": 0, "name": "Épisodes spéciaux", "episode_count": 1}]
            + [
                {"season_number": int(n), "name": f"Saison {n}", "episode_count": c}
                for n, c in seasons
            ],
        }
        return TmdbInfo(tmdb_id, "tv", title, original, year, f"Synopsis de {title}.", raw)

    def certifications(self, tmdb_id, media_type):
        return [("FR", "12")]

    def tv_season(self, tmdb_id, season):
        count = dict((int(n), c) for n, c in self.SERIES[tmdb_id][3])[season]
        return {
            "episodes": [
                {"episode_number": e, "name": f"Épisode {e}", "overview": f"Résumé {e}"}
                for e in range(1, count + 1)
            ]
        }


def row(name, size, seeders=20, category=5000):
    return CatalogueRow(f"{abs(hash(name)):040x}"[:40], name, size, seeders, category, "", "", 0.0)


CATALOGUE = [
    row("Arrow.S01.MULTi.1080p.WEB.x264-TEAM", 30 * GB),
    row("Arrow.S02.MULTi.1080p.WEB.x264-TEAM", 20 * GB),
    row("Arrow.S01-S02.INTEGRALE.MULTi.1080p.WEB.x264-TEAM", 50 * GB),
    row("Arrow.S02E05.MULTi.1080p.WEB.x264-OTHER", 2 * GB),
    row("Arrow.S09E01.MULTi.1080p.WEB.x264-OTHER", 2 * GB),  # TMDb has no season 9
    row("Naruto.S01E01.VOSTFR.1080p.x265-TLC", GB, category=5070),
    row("Naruto.S01E02.VOSTFR.1080p.x265-TLC", GB, category=5070),
    row("Naruto.S01E02.VOSTFR.1080p.x265-NOSEED", GB, seeders=0, category=5070),
    row("Some.Show.2020.S01.MULTi.1080p-TEAM", GB, category=5080),  # Émission TV: never
    row("Dune.2021.MULTi.1080p.WEB.x264-TEAM", GB, category=2030),  # a film
]
TR4KER = [
    row("Arrow.S03.FRENCH.720p-TR", 10 * GB, category=5040),
    row("Les.Touristes.Mission.Pompiers.HDTV.720p", GB, category=5000),
]


@pytest.fixture
def series(library, tmp_path):  # noqa: F811
    library.tmdb = FakeTmdb()
    library.tmdb_client = lambda key: library.tmdb
    store = Store(tmp_path / "series.db")
    store.save_catalogue(CATALOGUE)
    store.for_tracker("tr4ker").save_catalogue(TR4KER)
    setup = setup_with(store)
    setup.secrets = SimpleNamespace(get=lambda name: "tmdb-key")
    library.setup_for_test = setup
    return library


def run(series):
    setup = series.setup_for_test
    series.series_sync("default", setup)
    return series.series_identify("default", setup, threading.Event(), pause=0)


def test_only_seeded_series_categories_are_indexed(series):
    series.series_sync("default", series.setup_for_test)
    names = {r["name"] for r in series.db.execute("SELECT name FROM series_release")}
    assert not any("Some.Show" in n or "Dune" in n or "NOSEED" in n for n in names)
    assert "Naruto.S01E01.VOSTFR.1080p.x265-TLC" in names


def test_releases_group_under_their_series_with_packs_integrales_and_episodes(series):
    run(series)
    index = {e["title"]: e for e in series.series_index()}
    assert set(index) == {"Arrow", "Naruto"}  # tr4ker's unidentified TV show stays out
    arrow = index["Arrow"]
    assert arrow["tmdb"] == "10" and arrow["kind"] == "series"
    assert {r["pack"] for r in arrow["releases"]} == {"season", "complete", "episode"}
    # c411 and tr4ker releases of one series share the entry once TMDb identified it
    assert {r["tracker"] for r in arrow["releases"]} == {"c411", "tr4ker"}
    assert index["Naruto"]["kind"] == "anime"


def test_coverage_is_checked_against_tmdbs_seasons_and_episodes(series):
    run(series)
    arrow = next(e for e in series.series_index() if e["title"] == "Arrow")
    states = {n: c["state"] for n, c in arrow["coverage"].items()}
    # S01 has its own pack, S02 too; the Intégrale covers both, and S03 (tr4ker) is unknown to TMDb.
    assert states == {1: "pack", 2: "pack"}
    naruto = next(e for e in series.series_index() if e["title"] == "Naruto")
    assert naruto["coverage"][1]["state"] == "episodes"
    assert naruto["coverage"][1]["episodes"] == {1, 2}


def test_an_integrale_covers_the_seasons_without_a_pack_of_their_own(series):
    series.db.execute("DELETE FROM series_release")
    series.db.commit()
    with series.lock, series.db:
        series.db.execute(
            "INSERT INTO series_release (tracker, infohash, name, size, seeders, category, kind,"
            " position, tkey, title, pack, seasons) VALUES ('c411', 'a', 'x', 1, 5, 5000, 'series',"
            " 0, '[\"arrow\", \"\"]', 'Arrow', 'complete', '[]')"
        )
        series.db.execute("INSERT INTO series_title VALUES ('[\"arrow\", \"\"]', '10', 0, 0)")
    series._series_fetch_meta(series.tmdb, "10")
    arrow = series.series_index()[0]
    assert {n: c["state"] for n, c in arrow["coverage"].items()} == {1: "complete", 2: "complete"}


def test_identification_stores_poster_french_synopsis_genres_age_rating_and_episodes(series):
    run(series)
    meta = series.db.execute("SELECT * FROM series_meta WHERE tmdb='10'").fetchone()
    assert meta["overview"] == "Synopsis de Arrow." and meta["rating"] == "12"
    assert meta["poster"].endswith("/s10.jpg") and meta["genres"] == '["Action"]'
    episode = series.db.execute(
        "SELECT title, overview FROM series_episode WHERE tmdb='10' AND season=1 AND episode=3"
    ).fetchone()
    assert (episode["title"], episode["overview"]) == ("Épisode 3", "Résumé 3")
    assert all("SERIES" in k.upper() for k in series.tmdb.kinds)


def test_after_the_first_run_only_new_catalogue_entries_are_asked(series):
    run(series)
    asked = len(series.tmdb.lookups)
    run(series)
    assert len(series.tmdb.lookups) == asked
    series.setup_for_test.store.save_catalogue(
        [row("Naruto.S02E01.VOSTFR.1080p-TLC", GB, category=5070)]
    )
    run(series)
    assert len(series.tmdb.lookups) == asked  # the same series key is not asked again
