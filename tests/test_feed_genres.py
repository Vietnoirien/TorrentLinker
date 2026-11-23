"""The RSS genre filter: synthetic releases, TMDb and the Trackers faked, no network."""

import importlib.util
import json
from pathlib import Path

import pytest

from torrentlinker.feed_genres import FALLBACK_GENRES, FeedGenres
from torrentlinker.feeds import FeedService, Preferences, Subscription, evaluate
from torrentlinker.indexer import Candidate
from torrentlinker.media_ratings import TMDB_RETRY

HORROR, SCI_FI, DRAMA = 27, 878, 18
GENRE_NAMES = {HORROR: "Horreur", SCI_FI: "Science-Fiction", DRAMA: "Drame"}


class FakeTmdb:
    """TMDb answers by id; counts every request so the cache is visible."""

    def __init__(self, genres=None, down=False):
        self.genres = genres or {}
        self.down = down
        self.details_calls: list[tuple[str, str]] = []
        self.list_calls: list[tuple[str, str]] = []

    def __call__(self, key):  # the client factory
        assert key == "fake-tmdb-key"
        return self

    def details(self, tmdb_id, media_type):
        if self.down:
            raise OSError("TMDb is down")
        self.details_calls.append((media_type, tmdb_id))
        from torrentlinker.tmdb import TmdbInfo

        found = self.genres.get(tmdb_id, [])
        return TmdbInfo(
            tmdb_id,
            media_type,
            "T",
            "T",
            "2024",
            "",
            {"genres": [{"id": g, "name": "x"} for g in found]},
        )

    def genre_list(self, media_type, language):
        if self.down:
            raise OSError("TMDb is down")
        self.list_calls.append((media_type, language))
        base = {"fr-FR": GENRE_NAMES, "en-US": {HORROR: "Horror", SCI_FI: "Science Fiction"}}
        return [{"id": i, "name": n} for i, n in base[language].items()]


class FakeC411:
    def __init__(self, media):
        self.media = media
        self.read: list[str] = []

    def torrent_json(self, infohash):
        self.read.append(infohash)
        return {"name": "x", "metadata": {"tmdbData": self.media}}


class FakeReader:
    can_read = True

    def __init__(self, media):
        self.media = media
        self.paths: list[str] = []

    def read_json(self, path, timeout=60.0):
        self.paths.append(path)
        return {"name": "x", "slug": path.rsplit("/", 1)[-1], **self.media}


class Clock:
    now = 1_000_000.0

    def __call__(self):
        return self.now


def make(tmp_path, *, tmdb=None, c411=None, reader=None, key="fake-tmdb-key", clock=None):
    service = FeedService(tmp_path / "feeds.sqlite", lambda: None)
    genres = FeedGenres(
        service.genre_cache,
        key=lambda: key,
        c411=lambda: c411,
        reader=lambda: reader,
        tmdb=tmdb or FakeTmdb(),
        clock=clock or Clock(),
    )
    return service, genres


def c411_row(hash="a", **metadata):
    return Candidate(
        "Film.2024.2160p",
        6 * 1024**3,
        "",
        infohash=hash * 40,
        categories=(2045,),
        metadata=metadata,
    )


def tr4ker_row(slug="film-2024", **metadata):
    return Candidate(
        "Film 2024",
        6 * 1024**3,
        "",
        infohash=f"tr4ker:{slug}",
        metadata={"tracker": "tr4ker", "slug": slug, **metadata},
    )


def test_unknown_genre_never_passes_and_never_fails_not_even_excluded():
    required = Preferences(required={"genre": [str(HORROR)]})
    avoided = Preferences(excluded={"genre": [str(HORROR)]})
    for unknown in (c411_row(), c411_row(genre=[])):
        for prefs in (required, avoided):
            result = evaluate(unknown, prefs)
            assert result["unknown"] == ["genre"]
            assert result["excluded"] == []
            assert result["eligible"] is False  # an Excluded rule does not clear it either
    assert evaluate(c411_row(genre=[HORROR, SCI_FI]), required)["eligible"] is True
    assert evaluate(c411_row(genre=[DRAMA]), required)["excluded"] == ["required genre"]


def test_excluded_genre_rejects_a_known_genre_and_passes_the_others():
    avoided = Preferences(excluded={"genre": [str(HORROR)]})
    rejected = evaluate(c411_row(genre=[HORROR, DRAMA]), avoided)
    assert rejected["excluded"] == ["excluded genre"] and not rejected["eligible"]
    assert evaluate(c411_row(genre=[DRAMA]), avoided)["eligible"] is True


def test_old_subscriptions_read_with_no_genre_and_a_genre_is_never_preferred(tmp_path):
    old = {"name": "Old", "preferences": {"required": {"quality": ["1080p"]}}}
    feed = Subscription.model_validate(old)
    assert "genre" not in feed.preferences.required
    assert "genre" not in feed.preferences.excluded
    service = FeedService(tmp_path / "feeds.sqlite", lambda: None)
    with service.db:
        service.db.execute(
            "INSERT INTO subscriptions(id,payload) VALUES('x',?)", (json.dumps(old),)
        )
    assert service.get("x").preferences.excluded == {}
    with pytest.raises(ValueError, match="never preferred"):
        Preferences(preferred={"genre": ["27"]})
    with pytest.raises(ValueError, match="ranking"):
        Preferences(priorities=["genre"])


def test_c411_names_map_to_tmdb_ids_and_a_unknown_name_is_not_guessed(tmp_path):
    _, genres = make(tmp_path, key="")  # no key: the built-in list
    assert genres.map_names(["Horreur", "Science-Fiction"]) == [HORROR, SCI_FI]
    assert genres.map_names(["science fiction", "HORREUR"]) == [SCI_FI, HORROR]
    assert genres.map_names(["Horreur", "Gore"]) is None
    assert genres.map_names([]) is None


def test_c411_detail_gives_genres_and_tmdb_id(tmp_path):
    c411 = FakeC411({"id": 945961, "type": "movie", "genres": ["Horreur", "Science-Fiction"]})
    tmdb = FakeTmdb()
    _, genres = make(tmp_path, tmdb=tmdb, c411=c411)
    found = genres.resolve(c411_row())
    assert found["genre"] == [HORROR, SCI_FI]
    assert (found["tmdbid"], found["kind"]) == ("945961", "movie")
    assert tmdb.details_calls == []  # the names were enough
    assert c411.read == ["a" * 40]
    # the answer is kept: asked once
    assert genres.cached(c411_row()) == found


def test_c411_name_unknown_to_tmdb_falls_back_to_tmdb_genres_of_the_detail_id(tmp_path):
    c411 = FakeC411({"id": 77, "type": "movie", "genres": ["Horreur", "Gore"]})
    tmdb = FakeTmdb({"77": [HORROR, DRAMA]})
    _, genres = make(tmp_path, tmdb=tmdb, c411=c411)
    assert genres.resolve(c411_row())["genre"] == [HORROR, DRAMA]
    # without a TMDb id the item stays unknown
    bare = FakeC411({"genres": ["Gore"]})
    _, genres = make(tmp_path / "other", tmdb=tmdb, c411=bare)
    assert "genre" not in genres.resolve(c411_row("b"))


def test_tr4ker_torznab_tmdbid_attr_gives_genres(tmp_path):
    tmdb = FakeTmdb({"693134": [SCI_FI, DRAMA]})
    _, genres = make(tmp_path, tmdb=tmdb)
    row = Candidate(
        "Film",
        1,
        "",
        infohash="b" * 40,
        categories=(2040,),
        metadata={"tracker": "tr4ker", "tmdbid": "693134"},
    )
    found = genres.resolve(row)
    assert found["genre"] == [SCI_FI, DRAMA]
    assert tmdb.details_calls == [("movie", "693134")]


def test_tr4ker_passkey_feed_item_reads_the_native_detail_first(tmp_path):
    tmdb = FakeTmdb({"945961": [HORROR, SCI_FI]})
    reader = FakeReader({"tmdb_id": 945961, "tmdb_type": "movie", "year": 2024})
    _, genres = make(tmp_path, tmdb=tmdb, reader=reader)
    found = genres.resolve(tr4ker_row("alien-romulus-2024"))
    assert reader.paths == ["/api/torrents/alien-romulus-2024"]
    assert found["genre"] == [HORROR, SCI_FI]
    assert (found["tmdbid"], found["kind"]) == ("945961", "movie")


def test_tr4ker_without_companion_tmdb_key_or_tmdb_id_stays_unknown(tmp_path):
    reader = FakeReader({"tmdb_id": 5, "tmdb_type": "tv"})
    unpaired = make(tmp_path / "a", reader=None)[1].resolve(tr4ker_row("x"))
    assert "genre" not in unpaired
    no_key = make(tmp_path / "b", reader=reader, key="")[1].resolve(tr4ker_row("x"))
    assert "genre" not in no_key and no_key["tmdbid"] == "5"
    no_id = make(tmp_path / "c", reader=FakeReader({}))[1].resolve(tr4ker_row("x"))
    assert "genre" not in no_id
    down = make(tmp_path / "d", reader=reader, tmdb=FakeTmdb(down=True))[1].resolve(tr4ker_row("x"))
    assert "genre" not in down


def test_tmdb_answers_are_cached_per_title_and_retried_after_a_week(tmp_path):
    clock = Clock()
    tmdb = FakeTmdb({"1": [HORROR]})
    _, genres = make(tmp_path, tmdb=tmdb, clock=clock)
    assert genres.ids("movie", "1") == [HORROR]
    assert genres.ids("movie", "1") == [HORROR]
    assert tmdb.details_calls == [("movie", "1")]
    # a title TMDb gave no genre to is asked again only after a week
    assert genres.ids("movie", "2") is None
    assert genres.ids("movie", "2") is None
    assert len(tmdb.details_calls) == 2
    clock.now += TMDB_RETRY + 1
    tmdb.genres["2"] = [DRAMA]
    assert genres.ids("movie", "2") == [DRAMA]
    assert len(tmdb.details_calls) == 3
    assert genres.ids("movie", "1") == [HORROR]  # a known genre list is kept
    assert len(tmdb.details_calls) == 3


def test_a_read_that_failed_is_asked_again_within_the_hour_not_the_week(tmp_path):
    class Broken:
        def torrent_json(self, infohash):
            raise OSError("c411 is down")

    clock = Clock()
    _, genres = make(tmp_path, c411=Broken(), clock=clock)
    row = c411_row()
    found = genres.resolve(row)
    assert "genre" not in found
    assert genres.cached(row) is not None
    clock.now += 3601
    assert genres.cached(row) is None


def test_genre_names_follow_the_ui_language_from_tmdb_once_with_a_built_in_fallback(tmp_path):
    tmdb = FakeTmdb()
    _, genres = make(tmp_path, tmdb=tmdb)
    assert {g["id"]: g["name"] for g in genres.options("fr-FR")}[HORROR] == "Horreur"
    assert {g["id"]: g["name"] for g in genres.options("en")}[HORROR] == "Horror"
    genres.options("fr")
    genres.options("en-US")
    assert tmdb.list_calls == [
        ("movie", "fr-FR"),
        ("tv", "fr-FR"),
        ("movie", "en-US"),
        ("tv", "en-US"),
    ]
    _, offline = make(tmp_path / "off", tmdb=FakeTmdb(down=True))
    listed = {g["id"]: g["name"] for g in offline.options("fr")}
    assert listed == {g[0]: g[1] for g in FALLBACK_GENRES}
    assert {g["id"]: g["name"] for g in offline.options("en-US")}[SCI_FI] == "Science Fiction"
    _, keyless = make(tmp_path / "keyless", key="")
    assert len(keyless.options("fr")) == len(FALLBACK_GENRES)


class Source:
    url = "https://c411.org/api"

    def __init__(self, rows):
        self.rows = rows

    def search(self, query, *, cached):
        return self.rows

    def redact(self, value):
        return value


def test_a_refresh_reads_genres_once_and_the_inbox_row_keeps_them(tmp_path):
    c411 = FakeC411({"id": 1, "type": "movie", "genres": ["Horreur"]})
    source = Source([c411_row("a")])
    service = FeedService(tmp_path / "feeds.sqlite", lambda: source)
    service.genres = FeedGenres(
        service.genre_cache,
        key=lambda: "",
        c411=lambda: c411,
        reader=lambda: None,
    )
    feed = service.save(
        Subscription(
            name="Horreur 4K",
            categories=[2045],
            preferences=Preferences(required={"genre": [str(HORROR)]}),
        )
    )
    service.refresh(feed.id, now=100)
    source.rows = [c411_row("a"), c411_row("b")]
    result = service.refresh(feed.id, now=200)
    assert c411.read == ["a" * 40, "b" * 40]  # "a" was read once, by the first refresh
    inbox = {row["infohash"][0]: row for row in service.inbox()}
    assert inbox["a"]["metadata"]["genre"] == [HORROR]
    assert all(e["eligible"] for e in result["evaluations"].values())


def test_an_item_without_a_genre_waits_in_review_in_the_queue_modes(tmp_path):
    from torrentlinker.store import Store

    source = Source([])
    store = Store(tmp_path / "catalogue.sqlite")
    service = FeedService(tmp_path / "feeds.sqlite", lambda: source)
    prefs = Preferences(excluded={"genre": [str(DRAMA)]})
    feed = service.save(
        Subscription(
            name="No drama",
            mode="app_queue",
            folder=str(tmp_path),
            include_current=True,
            categories=[2045],
            preferences=prefs,
        )
    )
    service.refresh(feed.id, now=100)
    source.rows = [
        c411_row("a", kind="movie", tmdbid="1"),
        c411_row("b", kind="movie", tmdbid="2", genre=[DRAMA]),
        c411_row("c", kind="movie", tmdbid="3", genre=[HORROR]),
    ]
    service.refresh(feed.id, now=200)
    decisions = {
        r["infohash"][0]: r for r in service.process(feed.id, store, present_hashes=set(), now=201)
    }
    assert decisions["a"]["status"] == "review"
    assert "Genre unknown" in decisions["a"]["reason"]
    assert decisions["b"]["status"] == "blocked"  # known and excluded: rejected, not in review
    assert decisions["c"]["status"] == "queued"


def load_script():
    path = Path(__file__).parent.parent / "scripts" / "add_rss_subscriptions.py"
    spec = importlib.util.spec_from_file_location("add_rss_subscriptions", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_subscription_script_adds_five_once_through_the_feed_workspace(tmp_path, monkeypatch):
    script = load_script()
    previewed = []

    def preview(self, subscription, **kwargs):  # no Indexer or tr4ker feed is read
        previewed.append((subscription.name, subscription.tracker))
        return {"rows": []}

    monkeypatch.setattr(FeedService, "preview", preview)
    monkeypatch.setattr(FeedService, "has_preview", lambda self, feed: True)
    first_added, first_skipped = script.add(tmp_path)
    assert len(first_added) == 5 and first_skipped == []
    second_added, second_skipped = script.add(tmp_path)
    assert second_added == [] and len(second_skipped) == 5
    assert len(previewed) == 5

    from torrentlinker.feed_workspace import FeedWorkspace
    from torrentlinker.web.app import create_app

    control = create_app(
        tmp_path, password=None, trusted_proxies=(script.ip_network("127.0.0.1/32"),)
    ).state.agent_service.feed_control
    saved = {(s["name"], s["tracker"]): s for s in FeedWorkspace(control).request("feeds")}
    assert set(saved) == {
        ("Horreur 4K", "c411"),
        ("Horreur 4K", "tr4ker"),
        ("Science-fiction 4K", "c411"),
        ("Science-fiction 4K", "tr4ker"),
        ("tr4ker freeleech", "tr4ker"),
    }
    assert {s["mode"] for s in saved.values()} == {"review_only"}
    horror = saved[("Horreur 4K", "tr4ker")]
    assert horror["feed_category"] == "films-film" and horror["categories"] == []
    assert horror["preferences"]["required"] == {"quality": ["2160p"], "genre": ["27"]}
    assert (horror["preferences"]["min_size"], horror["preferences"]["max_size"]) == (
        4 * 1024**3,
        8 * 1024**3,
    )
    assert saved[("Science-fiction 4K", "c411")]["preferences"]["required"]["genre"] == ["878"]
    assert saved[("Horreur 4K", "c411")]["categories"] == [2045]
    free = saved[("tr4ker freeleech", "tr4ker")]
    assert free["freeleech"] is True and free["feed_category"] == ""
