# ruff: noqa: F811
"""The tr4ker Catalogue: a paced, resumable crawl of its full feed (ADR-0025).

The feed is a fake over httpx's mock transport; nothing reaches tr4ker.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from types import SimpleNamespace

import httpx
import pytest

from tests.test_media_tracker import REVENANT_RELEASES, library, setup_with  # noqa: F401
from tests.test_torznab_indexers import Clock
from tests.test_tr4ker_torznab import KEY, feed, item
from torrentlinker import tr4ker_catalogue
from torrentlinker.store import CatalogueRow, Store
from torrentlinker.torznab import TorznabIndexer
from torrentlinker.trackers import TR4KER


@dataclass
class Feed:
    """`count` torrents, newest first, some without seeders; pages by `offset`."""

    count: int
    requests: list[httpx.Request] = field(default_factory=list)
    refuse: list[httpx.Response] = field(default_factory=list)

    def hash(self, n: int) -> str:
        return f"{n + 1:040x}"

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.refuse:
            return self.refuse.pop(0)
        offset = int(request.url.params.get("offset", "0"))
        limit = int(request.url.params.get("limit", "50"))
        stop = min(offset + limit, self.count)
        items = [
            item(n, f"Torrent.{n}", size=1000 + n, seeders=n % 2, hash_=self.hash(n))
            for n in range(offset, stop)
        ]
        return httpx.Response(200, text=feed(*items, offset=offset, total=self.count))


def indexer(source: Feed, clock: Clock | None = None) -> TorznabIndexer:
    clock = clock or Clock()
    return TorznabIndexer(
        "https://tr4ker.net/api",
        KEY,
        "tr4ker",
        http=httpx.Client(transport=httpx.MockTransport(source.handler)),
        clock=clock.time,
        sleep=clock.sleep,
        tracker="tr4ker",
    )


def test_the_crawl_pages_the_full_feed_by_offset_and_stores_every_torrent(tmp_path):
    source, store = Feed(250), Store(tmp_path / "s.db")
    outcome = tr4ker_catalogue.run(indexer(source), store)
    assert (outcome.status, outcome.pages, outcome.added, outcome.reached_end) == (
        "done",
        3,
        250,
        True,
    )
    assert [r.url.path for r in source.requests] == ["/api/torznab/all"] * 3
    assert [r.url.params["offset"] for r in source.requests] == ["0", "100", "200"]
    assert all(r.url.params["limit"] == "100" for r in source.requests)
    scoped = store.for_tracker(TR4KER)
    assert scoped.catalogue_size() == 250
    assert scoped.catalogue_row(source.hash(0)).seeders == 0  # type: ignore[union-attr]
    assert store.catalogue_size() == 0  # nothing leaks into c411's Catalogue
    assert tr4ker_catalogue.coverage(store) == {
        "tracker": "tr4ker",
        "items": 250,
        "pages": 3,
        "last_offset": 0,
        "reached_end": True,
        "updated_at": tr4ker_catalogue.coverage(store)["updated_at"],
        "measured": True,
    }


def test_an_interrupted_crawl_resumes_at_its_offset(tmp_path):
    source, store = Feed(250), Store(tmp_path / "s.db")
    stop = threading.Event()
    outcome = tr4ker_catalogue.run(
        indexer(source), store, stop, lambda p: stop.set() if p["pages"] == 1 else None
    )
    assert (outcome.status, outcome.pages, outcome.next_offset) == ("cancelled", 1, 100)
    assert tr4ker_catalogue.coverage(store)["reached_end"] is False
    assert tr4ker_catalogue.coverage(store)["last_offset"] == 100
    assert tr4ker_catalogue.due(store)
    # A new process: nothing is read twice.
    again = Feed(250)
    resumed = tr4ker_catalogue.run(indexer(again), Store(tmp_path / "s.db"))
    assert [r.url.params["offset"] for r in again.requests] == ["100", "200"]
    assert resumed.reached_end and store.for_tracker(TR4KER).catalogue_size() == 250
    assert tr4ker_catalogue.coverage(store)["pages"] == 3


def test_retry_after_is_honoured_then_a_persistent_limit_keeps_the_offset(tmp_path):
    clock, store = Clock(), Store(tmp_path / "s.db")
    source = Feed(150)
    source.refuse = [httpx.Response(429, headers={"Retry-After": "9"})]
    assert tr4ker_catalogue.run(indexer(source, clock), store).reached_end
    assert sum(clock.sleeps) >= 9 and len(source.requests) == 3
    limited = Feed(500)
    other = Store(tmp_path / "t.db")
    limited.refuse = [httpx.Response(429, headers={"Retry-After": "5"})] * 10
    outcome = tr4ker_catalogue.run(indexer(limited, Clock()), other)
    assert outcome.status == "rate_limited" and outcome.pages == 0
    assert other.for_tracker(TR4KER).crawl_state(0).next_offset == 0
    assert tr4ker_catalogue.due(other)  # still owed, will resume


@pytest.mark.parametrize(
    "response,status",
    [
        (httpx.Response(401), "refused"),
        (httpx.Response(403), "refused"),
        (httpx.Response(503, json={"error": "maintenance"}), "rate_limited"),
        (httpx.Response(500, text="boom"), "unreachable"),
    ],
)
def test_a_refusal_or_outage_stops_the_crawl_without_losing_state(tmp_path, response, status):
    source, store = Feed(300), Store(tmp_path / "s.db")

    def fail_after_the_first_page(progress):
        if progress["pages"] == 1:
            source.refuse = [response] * 20

    kept = tr4ker_catalogue.run(indexer(source), store, None, fail_after_the_first_page)
    assert (kept.status, kept.pages, kept.next_offset) == (status, 1, 100)
    assert store.for_tracker(TR4KER).catalogue_size() == 100
    assert tr4ker_catalogue.due(store)


def test_a_refresh_stops_at_the_first_page_with_nothing_new(tmp_path):
    store = Store(tmp_path / "s.db")
    tr4ker_catalogue.run(indexer(Feed(250)), store)
    grown = Feed(250)  # nothing new: one page is enough
    out = tr4ker_catalogue.run(indexer(grown), store)
    assert (out.status, out.pages, out.added) == ("done", 1, 0)
    refreshed = store.for_tracker(TR4KER).feed_state(tr4ker_catalogue.LATEST).updated_at
    assert refreshed is not None
    assert not tr4ker_catalogue.due(store, now=refreshed + 60)
    assert tr4ker_catalogue.due(store, now=refreshed + 5 * 3600)


def test_each_trackers_refresh_leaves_the_other_s_rows_alone(tmp_path):
    store = Store(tmp_path / "s.db")
    row = CatalogueRow(f"{1:040x}", "c411 copy", 5, 9, 2030, "u", "d", 1.0)
    store.save_catalogue([row])
    tr4ker_catalogue.run(indexer(Feed(3)), store)  # the same infohash 1 exists on tr4ker too
    assert store.catalogue() == [row]
    assert store.for_tracker(TR4KER).catalogue_row(f"{1:040x}").title == "Torrent.0"  # type: ignore[union-attr]
    store.save_catalogue([CatalogueRow(f"{1:040x}", "c411 renamed", 5, 1, 2030, "u", "d", 2.0)])
    assert store.for_tracker(TR4KER).catalogue_row(f"{1:040x}").title == "Torrent.0"  # type: ignore[union-attr]
    tr4ker_catalogue.run(indexer(Feed(3)), store)
    assert store.catalogue_row(f"{1:040x}").title == "c411 renamed"  # type: ignore[union-attr]


def test_the_api_key_is_never_stored_in_the_catalogue(tmp_path):
    store = Store(tmp_path / "s.db")
    tr4ker_catalogue.run(indexer(Feed(2)), store)
    rows = store.for_tracker(TR4KER).catalogue()
    assert rows and all(KEY not in r.download_url and "[secret]" in r.download_url for r in rows)
    import sqlite3

    with sqlite3.connect(tmp_path / "s.db") as db:
        dump = "\n".join(db.iterdump())
    assert KEY not in dump


# -- Media: both Catalogues, ReleaseScore first, then the Tracker order ---------------------


def upgrades(library, tmp_path, order, seeders):
    """The Revenant's upgrade row, when the given Trackers hold the same release."""
    name, size = REVENANT_RELEASES[0]
    hashes = {"c411": "c1" * 20, "tr4ker": "d4" * 20}
    store = Store(tmp_path / "media-store.db")
    for site, count in seeders.items():
        store.for_tracker(site).save_catalogue(
            [
                CatalogueRow(
                    hashes[site], name, size, count, 2040, "https://x/?apikey=[secret]", "", 1.0
                )
            ]
        )
    setup = setup_with(store)
    setup.settings.tracker_order = order
    with library.lock, library.db:
        library.db.execute("DELETE FROM media_options WHERE key LIKE 'tracker%'")
    library.tracker_refresh("default", setup, threading.Event())
    return hashes, library.tracker_rows("default", setup)["upgrades"]["rows"]


def test_a_tie_in_release_score_picks_the_first_tracker_in_the_order(
    library, tmp_path, monkeypatch
):
    empty = SimpleNamespace(rows=[], details={}, has_more=False)
    monkeypatch.setattr("torrentlinker.torrent_search.native_search", lambda *a, **k: empty)
    both = {"c411": 3, "tr4ker": 40}  # tr4ker is better seeded: the order still wins the tie
    for number, (order, winner) in enumerate(
        ((["c411", "tr4ker"], "c411"), (["tr4ker", "c411"], "tr4ker"))
    ):
        folder = tmp_path / str(number)
        folder.mkdir()
        hashes, rows = upgrades(library, folder, order, both)
        assert [r["tracker"]["hash"] for r in rows] == [hashes[winner]]
        assert ("site" in rows[0]["tracker"]) == (winner == "tr4ker")
    # c411 alone behaves as before: nothing is marked and no tr4ker row appears.
    alone = tmp_path / "alone"
    alone.mkdir()
    hashes, rows = upgrades(library, alone, ["c411", "tr4ker"], {"c411": 3})
    assert "site" not in rows[0]["tracker"] and rows[0]["tracker"]["hash"] == hashes["c411"]
