"""Trackers (ADR-0025): per-Tracker storage, recognition by announce host, Tracker order."""

import json
import sqlite3
from pathlib import Path

import pytest

from torrentlinker.config import Settings
from torrentlinker.domain import Torrent
from torrentlinker.reseed import TAG
from torrentlinker.seeding import indexer_torrents
from torrentlinker.store import CatalogueRow, CrawlState, FeedState, Store
from torrentlinker.trackers import TR4KER, TRACKERS, tracker, tracker_of_url, valid_order
from torrentlinker.zen import is_indexer_torrent

C411_URL = "https://c411.org/api/torznab"
TR4KER_URL = "https://tr4ker.net/api"
HASH = "ab" * 20

OLD_SCHEMA = """
CREATE TABLE catalogue (infohash TEXT PRIMARY KEY, title TEXT NOT NULL, size INTEGER NOT NULL,
  seeders INTEGER NOT NULL, category INTEGER, download_url TEXT NOT NULL,
  details_url TEXT NOT NULL, seen_at REAL NOT NULL, source TEXT NOT NULL DEFAULT 'indexer',
  root INTEGER);
CREATE INDEX catalogue_by_size ON catalogue(size);
CREATE TABLE catalogue_crawl (category INTEGER PRIMARY KEY, next_offset INTEGER NOT NULL DEFAULT 0,
  complete INTEGER NOT NULL DEFAULT 0, updated_at REAL, limited INTEGER NOT NULL DEFAULT 0);
CREATE TABLE unavailable_torrent (infohash TEXT PRIMARY KEY, seen_at REAL NOT NULL);
CREATE TABLE catalogue_feed (name TEXT PRIMARY KEY, next_page INTEGER NOT NULL DEFAULT 1,
  updated_at REAL, count INTEGER NOT NULL DEFAULT 0, limited INTEGER NOT NULL DEFAULT 0,
  head_hashes TEXT NOT NULL DEFAULT '[]', started_at REAL);
CREATE TABLE category_options (subcategory INTEGER PRIMARY KEY, body TEXT NOT NULL,
  fetched_at REAL NOT NULL);
CREATE TABLE profile_history (account TEXT NOT NULL, day TEXT NOT NULL, payload TEXT NOT NULL,
  PRIMARY KEY (account, day));
CREATE TABLE download_queue (id TEXT PRIMARY KEY, payload TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'queued', reason TEXT NOT NULL DEFAULT '',
  added_at REAL NOT NULL, priority INTEGER NOT NULL DEFAULT 0,
  retry_safe INTEGER NOT NULL DEFAULT 0);
"""


def row(title="Film", category=2000, seeders=3) -> CatalogueRow:
    return CatalogueRow(HASH, title, 100, seeders, category, "u", "d", 1.0, "indexer", 1)


def test_a_database_from_before_trackers_ends_up_entirely_under_c411(tmp_path: Path) -> None:
    path = tmp_path / "s.db"
    with sqlite3.connect(path) as db:
        db.executescript(OLD_SCHEMA)
        db.execute(
            "INSERT INTO catalogue VALUES (?,?,?,?,?,?,?,?,?,?)",
            (HASH, "Film", 100, 3, 2000, "u", "d", 1.0, "indexer", 1),
        )
        db.execute("INSERT INTO catalogue_crawl VALUES (2000, 300, 0, 5.0, 1)")
        db.execute("INSERT INTO unavailable_torrent VALUES ('cd', 7.0)")
        db.execute("INSERT INTO catalogue_feed (name, next_page) VALUES ('c411-latest:x', 4)")
        db.execute("INSERT INTO category_options VALUES (5, '{}', 9.0)")
        db.execute("INSERT INTO profile_history VALUES ('acc', '2026-11-01', '{\"up\": 1}')")
        db.execute("INSERT INTO download_queue (id, payload, added_at) VALUES ('k', '{}', 1.0)")

    store = Store(path)

    assert store.catalogue() == [row()]
    assert store.crawl_state(2000) == CrawlState(2000, 300, False, 5.0, True)
    assert store.known_hashes(["cd"]) == {"cd"}
    assert store.feed_state("c411-latest:x").next_page == 4
    assert store.cached_options(5) == ("{}", 9.0)
    assert store.profile_day("acc", "2026-11-01") == {"up": 1}
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT tracker FROM download_queue").fetchall() == [("c411",)]
        assert db.execute("SELECT DISTINCT tracker FROM catalogue").fetchall() == [("c411",)]
    # Nothing leaks to tr4ker, and the migration runs once.
    other = store.for_tracker(TR4KER)
    assert other.catalogue() == [] and other.crawl_state(2000) == CrawlState(2000)
    assert other.known_hashes(["cd"]) == set() and other.profile_day("acc", "2026-11-01") is None
    assert Store(path).catalogue() == [row()]
    with sqlite3.connect(path) as db:  # the size index survived the rebuild
        names = {r[1] for r in db.execute("PRAGMA index_list(catalogue)")}
    assert "catalogue_by_size" in names


def test_the_same_hash_and_category_on_both_trackers_never_overwrite(tmp_path: Path) -> None:
    c411 = Store(tmp_path / "s.db")
    tr4ker_store = c411.for_tracker(TR4KER)
    c411.save_catalogue([row("c411 title", 2000, seeders=5)])
    tr4ker_store.save_catalogue([row("tr4ker title", 2000, seeders=9)])
    assert [r.title for r in c411.catalogue()] == ["c411 title"]
    assert [r.title for r in tr4ker_store.catalogue()] == ["tr4ker title"]
    assert c411.catalogue_row(HASH).seeders == 5  # type: ignore[union-attr]
    tr4ker_store.save_crawl_state(CrawlState(2000, 100, True, 2.0))
    c411.save_crawl_state(CrawlState(2000, 0, False, 1.0))
    assert tr4ker_store.crawl_state(2000).next_offset == 100
    assert c411.crawl_state(2000).next_offset == 0
    c411.save_feed_state(FeedState("page", 3))
    assert tr4ker_store.feed_state("page").next_page == 1
    c411.cache_options(7, "c", 1.0)
    tr4ker_store.cache_options(7, "t", 2.0)
    assert c411.cached_options(7) == ("c", 1.0) and tr4ker_store.cached_options(7) == ("t", 2.0)
    c411.save_profile_day("acc", "d", {"v": 1})
    tr4ker_store.save_profile_day("acc", "d", {"v": 2})
    assert c411.profile_day("acc", "d") == {"v": 1}
    assert tr4ker_store.profile_day("acc", "d") == {"v": 2}


def test_an_unavailable_torrent_is_unavailable_on_one_tracker_only(tmp_path: Path) -> None:
    c411 = Store(tmp_path / "s.db")
    other = c411.for_tracker(TR4KER)
    c411.save_catalogue([row()])
    other.save_catalogue([row()])
    c411.drop_unavailable_torrent(HASH)
    assert c411.catalogue() == [] and len(other.catalogue()) == 1
    c411.save_catalogue([row()])
    assert c411.catalogue() == []  # a refresh does not restore it on c411
    other.save_catalogue([row("again")])
    assert other.catalogue_row(HASH).title == "again"  # type: ignore[union-attr]


def test_queued_downloads_remember_their_tracker(tmp_path: Path) -> None:
    store = Store(tmp_path / "s.db")
    store.enqueue_download("a", {"title": "A"})
    store.for_tracker(TR4KER).enqueue_download("b", {"title": "B"})
    with sqlite3.connect(tmp_path / "s.db") as db:
        assert dict(db.execute("SELECT id, tracker FROM download_queue")) == {
            "a": "c411",
            "b": "tr4ker",
        }


def test_an_unknown_tracker_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        Store(tmp_path / "s.db").for_tracker("nope")


def torrent(hash_: str, announce: str, *more: str, tags=frozenset()) -> Torrent:
    from dataclasses import replace

    base = Torrent(hash_, hash_, Path("/d"), tracker=announce, tags=tags)
    return replace(base, trackers=tuple(more)) if more else base


C411_ANNOUNCE = "https://tracker.c411.org/announce/secret-not-stored"
C411_ALT = "https://tk.c411.tw/announce/x"
TR4KER_ANNOUNCE = "https://tr4ker.net/announce/x"


def test_a_torrent_announcing_to_one_tracker_is_not_the_other_s() -> None:
    assert is_indexer_torrent(TR4KER_ANNOUNCE, TR4KER_URL)
    assert not is_indexer_torrent(TR4KER_ANNOUNCE, C411_URL)
    assert is_indexer_torrent(C411_ANNOUNCE, C411_URL) and is_indexer_torrent(C411_ALT, C411_URL)
    assert not is_indexer_torrent(C411_ANNOUNCE, TR4KER_URL)
    assert not is_indexer_torrent("https://evil-tr4ker.net/announce", TR4KER_URL)
    assert not is_indexer_torrent("https://tr4ker.net.evil.test/announce", TR4KER_URL)


def test_indexer_torrents_keep_each_tracker_apart_even_with_a_tag_or_known_hash() -> None:
    mine = torrent("c1", C411_ANNOUNCE)
    theirs = torrent("t1", TR4KER_ANNOUNCE)
    tagged = torrent("t2", TR4KER_ANNOUNCE, tags=frozenset({TAG}))
    both = torrent("b1", TR4KER_ANNOUNCE, C411_ANNOUNCE)
    untracked = torrent("u1", "", tags=frozenset({TAG}))
    everything = [mine, theirs, tagged, both, untracked]
    assert indexer_torrents(everything, C411_URL, known={"t1"}) == [mine, both, untracked]
    assert indexer_torrents(everything, TR4KER_URL, known={"c1"}) == [
        theirs,
        tagged,
        both,
        untracked,
    ]


def test_trackers_have_their_own_hosts_tags_and_secret_names() -> None:
    assert tracker_of_url(C411_ALT) is TRACKERS["c411"]
    assert tracker_of_url(TR4KER_ANNOUNCE) is TRACKERS["tr4ker"]
    assert tracker_of_url("https://example.org/announce") is None
    assert tracker("c411").source == "C411" and tracker("tr4ker").source == "TR4KER"
    assert tracker("c411").api_key_secret == "indexer-api-key"  # unchanged
    assert tracker("tr4ker").api_key_secret == Settings.indexer_secret("tr4ker")
    assert tracker("tr4ker").api_key_secret == "indexer-key-tr4ker"
    secrets = {t.api_key_secret for t in TRACKERS.values()} | {
        t.passkey_secret for t in TRACKERS.values()
    }
    assert len(secrets) == 4
    assert tracker("c411").announce_secret == "announce-url"
    assert not tracker("tr4ker").has("zen")  # unavailable on tr4ker, not faked


def test_tracker_order_defaults_to_c411_first_and_heals_bad_values() -> None:
    assert Settings().tracker_order == ["c411", "tr4ker"]
    assert valid_order(["tr4ker"]) == ["tr4ker", "c411"]
    assert valid_order(["tr4ker", "tr4ker", "x", 3, "c411"]) == ["tr4ker", "c411"]
    assert valid_order("nonsense") == ["c411", "tr4ker"]


def test_the_tracker_order_survives_a_save_and_never_holds_a_secret(tmp_path: Path) -> None:
    settings = Settings()
    settings.tracker_order = ["tr4ker", "c411"]
    path = tmp_path / "settings.json"
    settings.save(path)
    assert Settings.load(path).tracker_order == ["tr4ker", "c411"]
    text = path.read_text()
    assert json.loads(text)["tracker_order"] == ["tr4ker", "c411"]
    for name in ("indexer-key-tr4ker", "indexer-passkey-tr4ker", "announce-url", "apikey"):
        assert name not in text
    old = json.loads(text)
    del old["tracker_order"]  # a file from before Trackers
    path.write_text(json.dumps(old))
    assert Settings.load(path).tracker_order == ["c411", "tr4ker"]


def test_c411_stays_the_default_tracker_indexer() -> None:
    settings = Settings()
    assert settings.tracker_indexer("c411") is settings.indexer
    with pytest.raises(ValueError):
        settings.tracker_indexer("tr4ker")  # not added yet: nothing is faked
    with pytest.raises(ValueError):
        settings.tracker_indexer("nope")
