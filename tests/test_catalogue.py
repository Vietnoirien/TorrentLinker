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


def test_a_plan_fetches_its_chosen_categories_or_else_those_with_a_download_folder() -> None:
    from torrentlinker.catalogue import plan_categories
    from torrentlinker.downloads import DownloadFolders, IndexerCategory

    cats = {
        2000: IndexerCategory("Films & Vidéos"),
        2030: IndexerCategory("Film", 2000),
        5000: IndexerCategory("Série TV", 2000),
        7000: IndexerCategory("Ebook"),
        7020: IndexerCategory("Livres", 7000),
        8010: IndexerCategory("Imprimante 3D"),
    }
    folders = DownloadFolders({2030: "/f", 5000: "/s", 7000: "/e", 8010: "/3d"})

    assert plan_categories(None, folders, cats) == [2030, 5000, 7000, 7020, 8010]
    assert plan_categories({8010, 2030}, folders, cats) == [2030, 8010]
    # a chosen category comes with each of its subcategories
    assert plan_categories({7000}, folders, cats) == [7000, 7020]
    # a chosen category without any Download Folder is not planned, so not fetched
    assert plan_categories({9999}, folders, cats) == []


def test_a_full_crawl_is_incomplete_when_the_indexer_stops_paging(tmp_path: Path) -> None:
    """c411 serves at most ~600 results per query; deeper offsets repeat the last page."""
    fake, store = FakeTorznab(window=600), Store(tmp_path / "s.db")
    fake.add(7020, 2000)

    state = update_category(indexer(fake), store, 7020, full=True)

    assert len(fake.requests) <= 8  # not an endless crawl of repeated pages
    assert not state.complete
    assert state.limited and state.next_offset == 0
    assert store.catalogue_size() == 600
    assert Store(tmp_path / "s.db").limited_categories() == {7020}
    assert not store.crawl_paused()  # a server limit is different from a user pause

    # A later Plan retries from the beginning instead of updating a falsely complete
    # category. If the server removes its limit, all older torrents can be reached.
    fake.window = None
    fake.requests.clear()
    state = update_category(indexer(fake), store, 7020, full=True)

    assert fake.requests[0].url.params["offset"] == "0"
    assert state.complete and not state.limited
    assert store.catalogue_size() == 2000
    assert not store.limited_categories()


def test_reordered_repeated_pages_do_not_certify_a_complete_catalogue(tmp_path: Path) -> None:
    fake, store = FakeTorznab(window=100), Store(tmp_path / "s.db")
    fake.add(7020, 2000)
    original = fake.handler

    def reordered(request: httpx.Request) -> httpx.Response:
        # Some Indexers do not preserve ordering between requests.
        if len(fake.requests) % 2:
            fake.by_category[7020][:100] = reversed(fake.by_category[7020][:100])
        return original(request)

    fake.handler = reordered  # type: ignore[method-assign]
    state = update_category(indexer(fake), store, 7020, full=True, max_pages=4)

    assert state.limited and not state.complete
    assert len(fake.requests) == 2


def test_a_plan_fetches_each_subcategory_on_its_own_to_get_past_the_paging_limit() -> None:
    from torrentlinker.catalogue import plan_categories
    from torrentlinker.downloads import DownloadFolders, IndexerCategory

    cats = {
        7000: IndexerCategory("Ebook"),
        7010: IndexerCategory("Presse", 7000),
        7020: IndexerCategory("Livres", 7000),
        2000: IndexerCategory("Films & Vidéos"),
        2030: IndexerCategory("Film", 2000),
        8010: IndexerCategory("Imprimante 3D"),
    }
    folders = DownloadFolders({7000: "/e", 2030: "/f", 8010: "/3d"})

    assert plan_categories({7000}, folders, cats) == [7000, 7010, 7020]
    assert plan_categories(None, folders, cats) == [2030, 7000, 7010, 7020, 8010]
