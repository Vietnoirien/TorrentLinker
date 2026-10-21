"""The Catalogue: torrents of the Indexer stored locally, for Plans to choose from.

Built by paging through Torznab searches per category (newest first, 100 per page) at
the Indexer's rate limit, never through a third party (ADR-0005). An update stops at
the first page holding only known torrents; a full crawl goes to the end of every
category and can be paused and resumed, even after a restart.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Collection, Iterable, Mapping
from dataclasses import dataclass, replace

from torrentlinker.downloads import DownloadFolders, IndexerCategory
from torrentlinker.indexer import Candidate, Indexer, SearchMode, SearchQuery
from torrentlinker.store import CatalogueRow, CrawlState, Store

PAGE = 100  # c411's maximum results per Torznab request
STARTUP_PAGES = 10  # an update at startup reads at most this many pages per category


@dataclass(frozen=True)
class CrawlProgress:
    category: int
    pages: int  # pages read in this run for this category
    added: int  # torrents new to the Catalogue in this run for this category
    offset: int  # next offset in the category


Progress = Callable[[CrawlProgress], None]


def update_category(
    indexer: Indexer,
    store: Store,
    category: int,
    *,
    full: bool = False,
    max_pages: int | None = None,
    stop: Callable[[], bool] = lambda: False,
    progress: Progress = lambda p: None,
    categories: Mapping[int, IndexerCategory] = {},
    clock: Callable[[], float] = time.time,
) -> CrawlState:
    """Read one category into the Catalogue and return its crawl state.

    Without `full`, read from the newest torrents and stop at the first page that
    holds only torrents already in the Catalogue. With `full`, resume a crawl where it
    stopped and go on to the end of the category; once a category was crawled to the
    end, later full crawls are updates.
    """
    state = store.crawl_state(category)
    resuming = full and not state.complete
    offset = state.next_offset if resuming else 0
    pages = added = 0
    previous: list[str] | None = None
    while not stop() and (max_pages is None or pages < max_pages):
        query = SearchQuery(
            mode=SearchMode.SEARCH,
            categories=(category,),
            limit=PAGE,
            offset=offset,
            extended=True,
        )
        page = indexer.search(query, cached=False)
        found = [c for c in page if c.infohash]
        hashes = [str(c.infohash) for c in found]
        known = store.known_hashes(hashes)
        now = clock()
        store.save_catalogue([_row(indexer, c, category, categories, now) for c in found])
        pages += 1
        added += len(set(hashes) - known)
        offset += PAGE
        # The end of the category, or the end of what the Indexer will page through:
        # c411 serves at most ~600 results per query, then repeats its last page.
        end = len(page) < PAGE or hashes == previous
        previous = hashes
        if resuming:
            state = replace(state, next_offset=0 if end else offset, complete=end)
        state = replace(state, updated_at=now)
        store.save_crawl_state(state)
        progress(CrawlProgress(category, pages, added, offset))
        if end or (not resuming and set(hashes) <= known):
            break
    return state


def update_categories(
    indexer: Indexer,
    store: Store,
    wanted: Iterable[int],
    *,
    full: bool = False,
    max_pages: int | None = None,
    stop: Callable[[], bool] = lambda: False,
    progress: Progress = lambda p: None,
    categories: Mapping[int, IndexerCategory] = {},
) -> None:
    for category in wanted:
        if stop():
            return
        update_category(
            indexer,
            store,
            category,
            full=full,
            max_pages=max_pages,
            stop=stop,
            progress=progress,
            categories=categories,
        )


def startup_categories(
    folders: DownloadFolders,
    categories: Mapping[int, IndexerCategory],
    seeded_hashes: list[str],
    store: Store,
) -> list[int]:
    """The user's categories: those given a Download Folder and those of the torrents
    they seed that the Catalogue already knows. A subcategory is skipped when its
    category is fetched anyway (Torznab includes subcategories)."""
    wanted = set(folders.by_category) | store.catalogue_categories(seeded_hashes)
    return sorted(c for c in wanted if _parent(c, categories) not in wanted)


def plan_categories(
    chosen: Collection[int] | None,
    folders: DownloadFolders,
    categories: Mapping[int, IndexerCategory],
) -> list[int]:
    """Categories to fetch in full before a Plan: the ones chosen for it (else those
    given a Download Folder) that can be planned at all, i.e. resolve to a folder, each
    with every subcategory on its own: an Indexer pages through a limited number of
    results per query (~600 on c411), so each subcategory reaches deeper."""
    wanted = set(chosen) if chosen is not None else set(folders.by_category)
    plannable = {c for c in wanted if folders.resolve(c, categories) is not None}
    expanded = set(plannable)
    for cid in categories:
        ancestor = _parent(cid, categories)
        if ancestor in plannable:
            expanded.add(cid)
    return sorted(expanded)


def crawl_categories(categories: Mapping[int, IndexerCategory]) -> list[int]:
    """Categories a whole-Catalogue crawl reads: every top category, which includes its
    subcategories."""
    return sorted(c for c in categories if _parent(c, categories) not in categories)


def _parent(category: int, categories: Mapping[int, IndexerCategory]) -> int | None:
    known = categories.get(category)
    return known.parent if known else None


def _row(
    indexer: Indexer,
    c: Candidate,
    crawled: int,
    categories: Mapping[int, IndexerCategory],
    now: float,
) -> CatalogueRow:
    return CatalogueRow(
        infohash=str(c.infohash).lower(),
        title=c.title,
        size=c.size,
        seeders=c.seeders,
        category=_most_specific(c.categories, crawled, categories),
        download_url=indexer.redact(c.download_url),
        details_url=indexer.redact(c.details_url),
        seen_at=now,
    )


def _most_specific(
    listed: tuple[int, ...], crawled: int, categories: Mapping[int, IndexerCategory]
) -> int:
    """The subcategory when the Indexer lists one, else its category, else the one read."""
    if not listed:
        return crawled
    subcats = [c for c in listed if _parent(c, categories) is not None]
    return (subcats or [c for c in listed if c in categories] or list(listed))[0]


def candidate(indexer: Indexer, row: CatalogueRow) -> Candidate:
    """A Catalogue torrent as a Candidate whose .torrent the Indexer can fetch."""
    return Candidate(
        title=row.title,
        size=row.size,
        download_url=indexer.unredact(row.download_url),
        seeders=row.seeders,
        infohash=row.infohash,
        details_url=indexer.unredact(row.details_url),
        categories=(row.category,) if row.category is not None else (),
    )


def age(updated_at: float | None, now: float) -> tuple[int, str] | None:
    """How old the Catalogue is, as (amount, "min" | "h" | "d"); None if never fetched."""
    if updated_at is None:
        return None
    seconds = max(0.0, now - updated_at)
    if seconds < 3600:
        return round(seconds / 60), "min"
    if seconds < 86400:
        return round(seconds / 3600), "h"
    return round(seconds / 86400), "d"
