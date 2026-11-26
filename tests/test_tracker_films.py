"""The Tracker Film index: seeded film releases grouped by film, identified in the
background, and queried by genre, sort and text. Every Catalogue and TMDb answer is fake."""

import threading
from types import SimpleNamespace

import pytest

from tests.test_media_tracker import library, setup_with  # noqa: F401  (the library fixture)
from torrentlinker.store import CatalogueRow, Store
from torrentlinker.tmdb import TmdbInfo

GB = 1024**3
STOP = threading.Event


class FakeTmdb:
    """TMDb as it answers for a few films; it counts what it was asked."""

    FILMS = {
        "1": ("Dune", "Dune", "2021", "Un jeune duc.", ["Science-Fiction", "Aventure"], 155, "12"),
        "2": (
            "Le Voyage de Chihiro",
            "千と千尋の神隠し",
            "2001",
            "Une fillette.",
            ["Animation", "Familial"],
            125,
            "",
        ),
        "3": (
            "Alien",
            "Alien",
            "1979",
            "Dans l'espace.",
            ["Horreur", "Science-Fiction"],
            117,
            "16",
        ),
        "9": ("Autre", "Other", "2021", "Un autre film.", ["Drame"], 90, "TP"),
    }
    LOOKUP = {("dune", 2021): "1", ("spirited away", 2001): "2", ("alien", 1979): "3"}

    def __init__(self):
        self.lookups, self.detailed = [], []
        self.failing = False

    def lookup(self, title, year, kind):
        if self.failing:
            raise RuntimeError("TMDb is down")
        self.lookups.append((title, year))
        return self.LOOKUP.get((title.lower(), year))

    def details(self, tmdb_id, media_type):
        self.detailed.append(tmdb_id)
        if tmdb_id not in self.FILMS:
            return None
        title, original, year, overview, genres, runtime, _ = self.FILMS[tmdb_id]
        raw = {
            "genres": [{"id": n, "name": g} for n, g in enumerate(genres)],
            "runtime": runtime,
            "poster_path": f"/p{tmdb_id}.jpg",
        }
        return TmdbInfo(tmdb_id, "movie", title, original, year, overview, raw)

    def certifications(self, tmdb_id, media_type):
        rating = self.FILMS[tmdb_id][6]
        return [("FR", rating)] if rating else [("US", "R")]


def row(name, size, seeders=20, category=2030, seen=0.0):
    return CatalogueRow(f"{abs(hash(name)):040x}"[:40], name, size, seeders, category, "", "", seen)


def build(tmp_path, c411=(), tr4ker=()):
    store = Store(tmp_path / "films.db")
    store.save_catalogue(list(c411))
    store.for_tracker("tr4ker").save_catalogue(list(tr4ker))
    setup = setup_with(store)
    setup.secrets = SimpleNamespace(get=lambda name: "tmdb-key")
    return setup


CATALOGUE = [
    row("Dune.2021.MULTi.1080p.WEB.x264-TEAM", 4 * GB, seeders=30),
    row("Dune.2021.MULTi.2160p.BluRay.x265-TEAM", 40 * GB, seeders=5),
    row("Spirited.Away.2001.MULTi.1080p.BluRay.x264-TEAM", 8 * GB),
    row("Alien.1979.MULTi.1080p.BluRay.x264-TEAM", 7 * GB, seeders=2),
    row("Dune.2021.MULTi.1080p.WEB.x264-NOSEED", 4 * GB, seeders=0),
    row("Mystery.Film.MULTi.1080p.WEB.x264-TEAM", 4 * GB),  # no year
    row("Some.Show.S01E01.MULTi.1080p.WEB.x264-TEAM", 2 * GB, category=2000),  # series
    row("Hot.Film.2020.MULTi.1080p.WEB.x264-TEAM", 2 * GB, category=6030),  # adult
]


@pytest.fixture
def films(library, tmp_path):  # noqa: F811
    library.tmdb = FakeTmdb()
    library.tmdb_client = lambda key: library.tmdb
    library.setup_for_test = build(tmp_path, CATALOGUE)
    return library


def run(films, **kwargs):
    setup = films.setup_for_test
    films.films_sync("default", setup)
    return films.films_identify("default", setup, STOP(), pause=0, **kwargs)


def titles(page):
    return [film["title"] for film in page["rows"]]


def query(films, **kwargs):
    return films.tracker_films("default", films.setup_for_test, **kwargs)


def test_only_seeded_releases_of_film_categories_are_indexed_and_grouped(films):
    films.films_sync("default", films.setup_for_test)
    page = query(films)
    # Dune's two seeded releases are one film; the unseeded one, the series and the adult
    # category are not listed; the release with no year stays under its release name.
    by_title = {film["title"]: film for film in page["rows"]}
    assert page["total"] == 4
    assert by_title["Dune"]["release_count"] == 2
    assert "Mystery Film" in by_title and not by_title["Mystery Film"]["identified"]
    assert not any("Some" in t or "Hot" in t for t in by_title)


def test_a_tr4ker_release_is_listed_only_once_identified(library, tmp_path):  # noqa: F811
    tmdb = FakeTmdb()
    library.tmdb_client = lambda key: tmdb
    setup = build(
        tmp_path,
        tr4ker=[
            row("Dune.2021.MULTi.1080p.WEB.x264-TEAM", 4 * GB, category=2000),
            row("Revue.Mensuelle.2021.PDF", 1 * GB, category=2040),
        ],
    )
    library.films_sync("default", setup)
    assert library.tracker_films("default", setup)["total"] == 0
    library.films_identify("default", setup, STOP(), pause=0)
    page = library.tracker_films("default", setup)
    assert titles(page) == ["Dune"] and page["rows"][0]["identified"]


def test_identification_fills_poster_synopsis_genres_runtime_and_rating(films):
    assert run(films) == "complete"
    dune = next(f for f in query(films)["rows"] if f["title"] == "Dune")
    assert dune["id"] == "tmdb-1" and dune["identified"] and dune["poster"]
    assert dune["overview"] == "Un jeune duc."
    assert dune["genres"] == ["Science-Fiction", "Aventure"]
    assert dune["runtime"] == 155 and dune["rating"] == "12"
    # A film TMDb has no French rating for is unrated; the foreign one is only a suggestion.
    chihiro = next(f for f in query(films)["rows"] if f["id"] == "tmdb-2")
    assert chihiro["rating"] is None


def test_each_title_is_asked_once_and_new_catalogue_entries_only_afterwards(films):
    run(films)
    asked = len(films.tmdb.lookups)
    assert asked == 3 and sorted(set(films.tmdb.detailed)) == ["1", "2", "3"]
    run(films)
    assert len(films.tmdb.lookups) == asked  # nothing new to ask
    films.setup_for_test.store.save_catalogue([row("Dune.2021.MULTi.720p.WEB.x264-TEAM", 2 * GB)])
    run(films)
    assert len(films.tmdb.lookups) == asked  # a new release of a known title costs no request
    assert next(f for f in query(films)["rows"] if f["id"] == "tmdb-1")["release_count"] == 3


def test_identification_resumes_after_its_budget_and_after_tmdb_fails(films):
    films.films_sync("default", films.setup_for_test)
    assert films.films_identify("default", films.setup_for_test, STOP(), budget=-1) == "limit"
    assert films.tmdb.lookups == []
    films.tmdb.failing = True
    assert films.films_identify("default", films.setup_for_test, STOP(), pause=0) == "unavailable"
    films.tmdb.failing = False
    assert films.films_identify("default", films.setup_for_test, STOP(), pause=0) == "complete"
    assert query(films, identified_only=True)["total"] == 3
    assert films.films_identify("default", films.setup_for_test, STOP(), pause=0) == "complete"


def test_the_index_answers_while_identification_has_not_run(films):
    films.films_sync("default", films.setup_for_test)
    page = query(films)
    assert page["total"] == 4 and not any(f["identified"] for f in page["rows"])
    assert query(films, identified_only=True)["total"] == 0


def test_a_missing_tmdb_key_leaves_the_index_unidentified(films):
    films.setup_for_test.secrets = SimpleNamespace(get=lambda name: "")
    films.films_sync("default", films.setup_for_test)
    assert films.films_identify("default", films.setup_for_test, STOP(), pause=0) == "off"
    assert films.tmdb.lookups == []


def test_queries_filter_by_genres_and_search_the_titles_and_release_names(films):
    run(films)
    assert titles(query(films, genres=("Science-Fiction",), sort="title")) == ["Alien", "Dune"]
    assert titles(query(films, genres=("Science-Fiction", "Aventure"))) == ["Dune"]
    assert titles(query(films, genres=("Western",))) == []
    # The French title, the original title and a release name all match.
    assert titles(query(films, q="chihiro")) == ["Le Voyage de Chihiro"]
    assert titles(query(films, q="千と千尋")) == ["Le Voyage de Chihiro"]  # the original title
    assert titles(query(films, q="spirited away")) == ["Le Voyage de Chihiro"]
    assert titles(query(films, q="dune 2160p")) == ["Dune"]


def test_queries_sort_and_page(films):
    run(films)
    assert titles(query(films, sort="title", identified_only=True)) == [
        "Alien",
        "Dune",
        "Le Voyage de Chihiro",
    ]
    assert titles(query(films, sort="year", identified_only=True)) == [
        "Dune",
        "Le Voyage de Chihiro",
        "Alien",
    ]
    # Most seeders first: Dune has two seeded releases, 35 sources.
    assert titles(query(films, sort="shared", identified_only=True))[0] == "Dune"
    first = query(films, sort="title", identified_only=True, limit=2)
    assert titles(first) == ["Alien", "Dune"] and first["has_more"]
    assert first["next_offset"] == 2 and first["total"] == 3
    last = query(films, sort="title", identified_only=True, offset=2, limit=2)
    assert titles(last) == ["Le Voyage de Chihiro"] and not last["has_more"]


def test_new_sorts_by_publication_then_by_catalogue_order(films):
    films.films_sync("default", films.setup_for_test)
    # The listing of c411's latest releases knows when a release was published.
    films._tracker_save(
        "default",
        "tracker-new",
        "alien",
        {
            "title": "Alien",
            "year": "1979",
            "facts": {},
            "releases": [
                {
                    "hash": row("Alien.1979.MULTi.1080p.BluRay.x264-TEAM", 0).infohash,
                    "name": "x",
                    "size": 1,
                    "seeders": 1,
                    "published_at": 1.8e9,
                }
            ],
        },
    )
    films.films_sync("default", films.setup_for_test)
    assert titles(query(films))[0] == "Alien"


def test_a_member_sees_no_library_film_and_an_age_limit_filters_by_rating(films):
    run(films)
    assert titles(query(films, age_limit=1, identified_only=True, sort="title")) == []
    # Rated 12 and 16, TP unrated: a limit of -12 (rank 2) keeps only Dune.
    assert titles(query(films, age_limit=2, identified_only=True)) == ["Dune"]
    assert titles(query(films, age_limit=4, identified_only=True, sort="title")) == [
        "Alien",
        "Dune",
    ]
    # Dune is in the Library: the Owner sees it flagged, a Member does not see it.
    with films.lock, films.db:
        row_ = films.db.execute("SELECT id, body FROM media_items").fetchone()
        import json

        body = json.loads(row_["body"]) | {"title": "Dune", "year": "2021"}
        films.db.execute("UPDATE media_items SET body=? WHERE id=?", (json.dumps(body), row_["id"]))
    owner = {f["title"]: f for f in query(films)["rows"]}
    assert owner["Dune"]["in_library"] and not owner["Alien"]["in_library"]
    assert "Dune" not in titles(query(films, hide_library=True))


def test_the_preselected_release_follows_the_profile_then_tracker_order_then_seeders(films):
    run(films)
    page = query(films, choose=True, sort="title", identified_only=True)
    dune = next(f for f in page["rows"] if f["id"] == "tmdb-1")
    assert [r["size"] for r in dune["releases"]][0] == dune["preselected"]["size"]
    assert dune["preselected"]["score"] is not None
    assert dune["releases"][0] is not dune["releases"][1]
    assert not dune["below_threshold"]
    # A Member's rows never carry releases.
    plain_row = query(films, identified_only=True)["rows"][0]
    assert "releases" not in plain_row and "preselected" not in plain_row


def test_a_film_with_no_release_above_the_threshold_is_flagged_below_it(films):
    run(films)
    films.setup_for_test.settings.release_score = {"threshold": 100, "active": "HDLight 1080p"}
    dune = query(films, choose=True, identified_only=True)["rows"]
    assert all(film["below_threshold"] for film in dune)
    assert all(film["preselected"] for film in dune)  # still pre-selected


def test_ties_go_to_the_tracker_first_in_the_owners_order(library, tmp_path):  # noqa: F811
    tmdb = FakeTmdb()
    library.tmdb_client = lambda key: tmdb
    name = "Dune.2021.MULTi.1080p.WEB.x264-TEAM"
    setup = build(
        tmp_path,
        c411=[row(name, 4 * GB, seeders=3)],
        tr4ker=[row(name + "B", 4 * GB, seeders=50, category=2000)],
    )
    library.films_sync("default", setup)
    library.films_identify("default", setup, STOP(), pause=0)
    film = library.tracker_films("default", setup, choose=True)["rows"][0]
    assert film["release_count"] == 2
    assert film["preselected"]["tracker"] == "c411"
    setup.settings.tracker_order = ["tr4ker", "c411"]
    film = library.tracker_films("default", setup, choose=True)["rows"][0]
    assert film["preselected"]["tracker"] == "tr4ker"


def test_a_film_correction_survives_reidentification(films):
    run(films)
    setup = films.setup_for_test
    # TMDb matched Alien to the wrong film; the Owner re-matches it to film 9.
    films.film_rematch("default", setup, "tmdb-3", "9")
    assert {f["id"] for f in query(films)["rows"]} >= {"tmdb-9"}
    assert next(f for f in query(films)["rows"] if f["id"] == "tmdb-9")["title"] == "Autre"
    # New releases and a full re-identification keep it.
    with films.lock, films.db:
        films.db.execute("UPDATE film_title SET checked = 0 WHERE manual = 0")
    run(films)
    assert "tmdb-3" not in {f["id"] for f in query(films)["rows"]}
    with pytest.raises(ValueError):
        films.film_rematch("default", setup, "tmdb-9", "404")


def test_one_release_can_move_to_another_film(films):
    run(films)
    setup = films.setup_for_test
    dune = next(f for f in query(films, choose=True)["rows"] if f["id"] == "tmdb-1")
    wrong = dune["releases"][-1]
    films.release_rematch(wrong["tracker"], wrong["hash"], setup, "9")
    assert next(f for f in query(films)["rows"] if f["id"] == "tmdb-1")["release_count"] == 1
    assert next(f for f in query(films)["rows"] if f["id"] == "tmdb-9")["release_count"] == 1
    run(films)
    assert next(f for f in query(films)["rows"] if f["id"] == "tmdb-9")["release_count"] == 1


def test_a_rating_set_by_hand_is_kept(films):
    run(films)
    films.film_rating("tmdb-2", "TP", "default", films.setup_for_test)
    assert next(f for f in query(films)["rows"] if f["id"] == "tmdb-2")["rating"] == "TP"
    films._fetch_meta(films.tmdb, "2")  # a refetch does not replace a person's rating
    assert next(f for f in query(films)["rows"] if f["id"] == "tmdb-2")["rating"] == "TP"
