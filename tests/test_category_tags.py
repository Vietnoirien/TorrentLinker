from dataclasses import replace
from pathlib import Path

from tests.fake_qbit import FakeQbit
from torrentlinker.category_tags import (
    CATEGORY_TAG_PREFIX,
    category_path,
    category_tag,
    sync_category_tags,
)
from torrentlinker.domain import Torrent
from torrentlinker.downloads import IndexerCategory
from torrentlinker.paths import MappedQbit, PathMapper
from torrentlinker.seeding import seeding
from torrentlinker.store import CatalogueRow
from torrentlinker.zen import ZenProfile

CATEGORIES = {7000: IndexerCategory("Books"), 7010: IndexerCategory("Comics", 7000)}


def test_categories_follow_the_catalogue_and_preserve_coarse_snapshot_assignments():
    torrents = [
        Torrent(h, h, Path("/data"), tracker="https://c411.org/a", state="uploading")
        for h in ("a", "b", "c")
    ]
    catalogue = {
        "a": CatalogueRow("a", "A", 1, 3, 7010, "u", "d", 0),
        "b": CatalogueRow("b", "B", 1, 3, 7000, "u", "d", 0, "zen-lab"),
    }
    view = seeding(
        ZenProfile(), torrents, "https://c411.org", catalogue=catalogue, categories=CATEGORIES
    )
    assert [r.category for r in view.rows] == [7010, 7000, None]
    assert [r.provisional_category for r in view.rows] == [False, True, False]
    assert view.categories == CATEGORIES
    assert category_path(7010, view.categories) == (7000, 7010)


def test_sync_is_additive_idempotent_and_replaces_only_its_own_old_category_tags():
    old = CATEGORY_TAG_PREFIX + "Old name"
    torrents = [
        Torrent(
            "a", "A", Path("/data"), tags=frozenset({"personal", "torrentlinker:verifying", old})
        ),
        Torrent("b", "B", Path("/data"), tags=frozenset({"keep"})),
        Torrent("c", "C", Path("/data"), tags=frozenset({"unclassified"})),
    ]
    client = FakeQbit({t.hash: t for t in torrents})
    mapped = MappedQbit(client, PathMapper([]))
    result = sync_category_tags(mapped, zip(torrents, (7010, 7000, None), strict=True), CATEGORIES)
    assert (result.updated, result.unknown, result.failed) == (2, 1, 0)
    assert client.by_hash["a"].tags == {
        "personal",
        "torrentlinker:verifying",
        CATEGORY_TAG_PREFIX + "Books / Comics",
    }
    assert client.by_hash["b"].tags == {"keep", CATEGORY_TAG_PREFIX + "Books"}
    assert client.by_hash["c"] == torrents[2]
    again = sync_category_tags(
        mapped, [(client.by_hash["a"], 7010), (client.by_hash["b"], 7000)], CATEGORIES
    )
    assert (again.updated, again.unchanged) == (0, 2)


def test_unsupported_client_and_unknown_category_never_mutate_tags():
    client = FakeQbit()
    client.supports_category_tags = False
    assert not sync_category_tags(
        client, [(Torrent("missing", "A", Path("/")), 7010)], CATEGORIES
    ).supported
    client.supports_category_tags = True
    result = sync_category_tags(client, [(Torrent("missing", "A", Path("/")), 7010)], {})
    assert result.unknown == 1
    assert (
        category_tag(1, {1: IndexerCategory("Audio, books")})
        == CATEGORY_TAG_PREFIX + "Audio · books"
    )
    assert category_path(1, {1: IndexerCategory("A", 2), 2: IndexerCategory("B", 1)}) == (2, 1)


def test_failed_add_does_not_remove_the_previous_tag_and_is_reported():
    class Refused(FakeQbit):
        def add_tags_many(self, hashes, tags):
            raise RuntimeError("Client unavailable")

    torrent = Torrent("a", "A", Path("/"), tags=frozenset({CATEGORY_TAG_PREFIX + "Old"}))
    client = Refused({"a": torrent})
    report = sync_category_tags(client, [(torrent, 7010)], CATEGORIES)
    assert report.failed == 1 and report.errors == ["Client unavailable"]
    assert client.by_hash["a"] == torrent


def test_equal_tags_are_batched_and_other_tracker_torrents_are_excluded():
    class Recording(FakeQbit):
        batches = []

        def add_tags_many(self, hashes, tags):
            self.batches.append((hashes, tags))
            super().add_tags_many(hashes, tags)

    torrent = Torrent("a", "A", Path("/"), tracker="https://c411.org/a")
    other = replace(torrent, hash="other", tracker="https://other.example/a")
    torrents = [torrent, replace(torrent, hash="b"), other]
    client = Recording({t.hash: t for t in torrents})
    catalogue = {
        t.hash: CatalogueRow(t.hash, t.name, 1, 2, 7010, "u", "d", 0) for t in torrents[:2]
    }
    view = seeding(
        ZenProfile(), torrents, "https://c411.org", catalogue=catalogue, categories=CATEGORIES
    )
    sync_category_tags(client, ((r.torrent, r.category) for r in view.rows), view.categories)
    assert client.batches == [(["a", "b"], [CATEGORY_TAG_PREFIX + "Books / Comics"])]
    assert client.by_hash["other"] == other


def test_transmission_sync_preserves_each_torrents_labels():
    from tests.test_transmission_unit import FakeRpc, api_for

    rpc = FakeRpc()
    rpc.torrents = {
        "a": {
            "hashString": "a",
            "name": "A",
            "downloadDir": "/data",
            "labels": ["personal", "torrentlinker:verifying"],
        },
        "b": {"hashString": "b", "name": "B", "downloadDir": "/data", "labels": ["other"]},
    }
    client = api_for(rpc)
    torrents = client.torrents(with_files=False)
    report = sync_category_tags(client, [(t, 7010) for t in torrents], CATEGORIES)
    assert report.updated == 2
    assert rpc.torrents["a"]["labels"] == [
        "personal",
        "torrentlinker:verifying",
        CATEGORY_TAG_PREFIX + "Books / Comics",
    ]
    assert rpc.torrents["b"]["labels"] == ["other", CATEGORY_TAG_PREFIX + "Books / Comics"]
    assert all(call in {"torrent-get", "torrent-set"} for call in rpc.calls)


def test_qbittorrent_batches_only_the_requested_torrents():
    from torrentlinker.qbit import QbitApi

    class Client:
        def __init__(self):
            self.tags = {"a": {"personal"}, "b": {"torrentlinker:verifying"}, "other": {"keep"}}
            self.requests = 0

        def torrents_add_tags(self, *, tags, torrent_hashes):
            self.requests += 1
            for hash in torrent_hashes:
                self.tags[hash].update(tags)

    api = QbitApi.__new__(QbitApi)
    client = Client()
    api._client = client
    rows = [
        (Torrent(h, h, Path("/data"), tags=frozenset(client.tags[h])), 7010) for h in ("a", "b")
    ]
    report = sync_category_tags(api, rows, CATEGORIES)
    assert report.updated == 2 and client.requests == 1
    assert client.tags == {
        "a": {"personal", CATEGORY_TAG_PREFIX + "Books / Comics"},
        "b": {"torrentlinker:verifying", CATEGORY_TAG_PREFIX + "Books / Comics"},
        "other": {"keep"},
    }
