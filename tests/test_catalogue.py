from pathlib import Path

import httpx

from tests.fake_torznab import FakeTorznab
from tests.test_indexer import FakeClock
from torrentlinker.catalogue import (
    PAGE,
    age,
    candidate,
    startup_categories,
    update_categories,
    update_category,
)
from torrentlinker.downloads import DownloadFolders, IndexerCategory
from torrentlinker.indexer import MIN_INTERVAL, Indexer
from torrentlinker.store import CatalogueRow, Store

CATEGORIES = {
    2000: IndexerCategory("Films"),
    2030: IndexerCategory("VO", 2000),
    7000: IndexerCategory("Ebook"),
}


def indexer(fake: FakeTorznab, clock: FakeClock | None = None) -> Indexer:
    clock = clock or FakeClock()
    return Indexer(
        "https://c411.example/api/torznab",
        "K",
        http=fake.client(),
        clock=clock.time,
        sleep=clock.sleep,
    )


def test_catalogue_keeps_size_seeders_category_hash_and_title_across_restarts(
    tmp_path: Path,
) -> None:
    fake = FakeTorznab()
    fake.add(7000, 3)
    update_category(indexer(fake), Store(tmp_path / "s.db"), 7000)

    rows = Store(tmp_path / "s.db").catalogue()  # a new Store, as after a restart

    assert len(rows) == 3
    row = next(r for r in rows if r.title == "T7000-0")
    assert (row.size, row.seeders, row.category) == (4_000_000_000, 50, 7000)
    assert len(row.infohash) == 40
    assert "apikey=K" not in row.download_url  # the API key is never stored


def test_requests_page_newest_first_through_search_with_category_and_limit(tmp_path: Path) -> None:
    fake = FakeTorznab()
    fake.add(7000, 250)

    update_category(indexer(fake), Store(tmp_path / "s.db"), 7000)

    params = [r.url.params for r in fake.requests]
    assert [p["offset"] for p in params] == ["0", "100", "200"]
    assert all(
        p["t"] == "search" and p["cat"] == "7000" and p["limit"] == str(PAGE) for p in params
    )
    assert all("q" not in p for p in params)


def test_an_update_stops_at_the_first_page_of_known_torrents(tmp_path: Path) -> None:
    fake, store = FakeTorznab(), Store(tmp_path / "s.db")
    fake.add(7000, 500)
    update_category(indexer(fake), store, 7000, max_pages=2)
    fake.add(7000, 30, start=500)  # 30 new torrents on top
    fake.requests.clear()

    update_category(indexer(fake), store, 7000)

    # page 0: 30 new + 70 known; page 1: all known → stop
    assert [r.url.params["offset"] for r in fake.requests] == ["0", "100"]
    assert store.catalogue_size() == 230


def test_startup_update_reads_a_bounded_number_of_pages(tmp_path: Path) -> None:
    fake = FakeTorznab()
    fake.add(2000, 5000)

    update_category(indexer(fake), Store(tmp_path / "s.db"), 2000, max_pages=3)

    assert len(fake.requests) == 3


def test_requests_respect_the_rate_limit(tmp_path: Path) -> None:
    fake, clock = FakeTorznab(), FakeClock()
    fake.add(7000, 300)
    sent: list[float] = []
    original = fake.handler

    def timed(request: httpx.Request) -> httpx.Response:
        sent.append(clock.now)
        return original(request)

    fake.handler = timed  # type: ignore[method-assign]
    update_category(indexer(fake, clock), Store(tmp_path / "s.db"), 7000)

    gaps = [b - a for a, b in zip(sent, sent[1:], strict=False)]
    assert gaps and min(gaps) >= MIN_INTERVAL


def test_a_subcategory_is_stored_when_the_indexer_lists_it(tmp_path: Path) -> None:
    fake, store = FakeTorznab(subcats={2030: 2000}), Store(tmp_path / "s.db")
    fake.add(2030, 2)

    update_category(indexer(fake), store, 2000, categories=CATEGORIES)

    assert {r.category for r in store.catalogue()} == {2030}


def test_startup_covers_categories_with_a_download_folder_and_those_of_seeded_torrents(
    tmp_path: Path,
) -> None:
    store = Store(tmp_path / "s.db")
    store.save_catalogue([CatalogueRow("aa" * 20, "Book", 1, 1, 7000, "u", "d", 0)])
    folders = DownloadFolders({2000: "/dl/films", 2030: "/dl/vo"}, default="/dl")

    wanted = startup_categories(folders, CATEGORIES, ["aa" * 20, "bb" * 20], store)

    assert wanted == [2000, 7000]  # 2030 comes with 2000; nothing else for the default


def test_nothing_is_requested_for_no_categories(tmp_path: Path) -> None:
    fake = FakeTorznab()
    update_categories(indexer(fake), Store(tmp_path / "s.db"), [])

    assert fake.requests == []


def test_a_catalogue_torrent_becomes_a_fetchable_candidate_with_the_key_restored(
    tmp_path: Path,
) -> None:
    fake, store = FakeTorznab(), Store(tmp_path / "s.db")
    fake.add(7000, 1)
    ix = indexer(fake)
    update_category(ix, store, 7000)

    [row] = store.catalogue()

    assert candidate(ix, row).download_url.endswith("?apikey=K")


def test_catalogue_age_reads_briefly() -> None:
    assert age(None, 100) is None
    assert age(0, 120) == (2, "min")
    assert age(0, 3 * 3600) == (3, "h")
    assert age(0, 4 * 86400) == (4, "d")


def test_full_crawl_pauses_and_resumes_where_it_stopped_even_after_a_restart(
    tmp_path: Path,
) -> None:
    fake = FakeTorznab()
    fake.add(2000, 450)
    pages = []

    def pause_after_two() -> bool:
        return len(pages) >= 2

    update_category(
        indexer(fake),
        Store(tmp_path / "s.db"),
        2000,
        full=True,
        stop=pause_after_two,
        progress=pages.append,
    )
    assert Store(tmp_path / "s.db").crawl_state(2000).next_offset == 200
    assert Store(tmp_path / "s.db").crawl_paused()
    fake.requests.clear()

    state = update_category(indexer(fake), Store(tmp_path / "s.db"), 2000, full=True)

    assert [r.url.params["offset"] for r in fake.requests] == ["200", "300", "400"]
    assert state.complete and state.next_offset == 0
    assert not Store(tmp_path / "s.db").crawl_paused()
    assert Store(tmp_path / "s.db").catalogue_size() == 450


def test_after_a_full_crawl_later_runs_are_incremental(tmp_path: Path) -> None:
    fake, store = FakeTorznab(), Store(tmp_path / "s.db")
    fake.add(2000, 450)
    update_category(indexer(fake), store, 2000, full=True)
    fake.add(2000, 10, start=450)
    fake.requests.clear()

    update_category(indexer(fake), store, 2000, full=True)

    assert [r.url.params["offset"] for r in fake.requests] == ["0", "100"]
    assert store.catalogue_size() == 460


def test_a_full_crawl_goes_on_past_known_torrents(tmp_path: Path) -> None:
    fake, store = FakeTorznab(), Store(tmp_path / "s.db")
    fake.add(2000, 300)
    update_category(indexer(fake), store, 2000, max_pages=1)  # the startup update
    fake.requests.clear()

    update_category(indexer(fake), store, 2000, full=True)

    assert [r.url.params["offset"] for r in fake.requests] == ["0", "100", "200", "300"]
    assert store.catalogue_size() == 300


def test_whole_catalogue_crawl_covers_every_category_once(tmp_path: Path) -> None:
    from torrentlinker.catalogue import crawl_categories

    assert crawl_categories(CATEGORIES) == [2000, 7000]
