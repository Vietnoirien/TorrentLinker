"""The tr4ker Catalogue, crawled from its full Torznab feed (ADR-0025).

`/api/torznab/all` is paged by offset, 100 a page, and lists torrents without seeders, which
Cross-seed and Reseed need. A crawl is paced by the Indexer's own pacer (`Retry-After`
included), resumes at its stored offset after any interruption, and is followed by cheap
refreshes from the newest page. Nothing here ships with the app, and coverage is only ever
reported as measured: the native listing's capped total says nothing about completeness.
Rows live under Tracker tr4ker, so c411's rows are never read, pruned or overwritten.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from torrentlinker.indexer import (
    Candidate,
    KeyRefused,
    RateLimited,
    SearchMode,
    SearchQuery,
)
from torrentlinker.store import CatalogueRow, CrawlState, FeedState, Store
from torrentlinker.torznab import Page, TorznabIndexer, parse_page
from torrentlinker.trackers import TR4KER

PAGE = 100  # tr4ker's maximum page size (its caps: max 100, default 50)
CRAWL = 0  # the one crawl state of the whole feed (a Torznab category id is never 0)
FEED = "tr4ker-crawl"  # its measured totals: pages read, items stored
LATEST = "tr4ker-latest"  # the last refresh from the newest page
REFRESH_INTERVAL = 4 * 3600
REFRESH_PAGES = 20  # a refresh reads at most this many pages from the newest
log = logging.getLogger(__name__)

Progress = Callable[[dict[str, Any]], None]


@dataclass(frozen=True)
class Outcome:
    """How a run ended: the Catalogue's measured state, never a claim of completeness."""

    status: str  # done | cancelled | rate_limited | refused | unreachable | idle
    pages: int  # read in this run
    added: int  # new to the Catalogue in this run
    next_offset: int
    reached_end: bool


def row(indexer: TorznabIndexer, c: Candidate, now: float) -> CatalogueRow:
    """A listing item as a Catalogue row; its download address never holds the API key."""
    return CatalogueRow(
        str(c.infohash).lower(),
        c.title,
        c.size,
        c.seeders,
        c.categories[0] if c.categories else None,
        indexer.redact(c.download_url),
        c.details_url,
        now,
    )


def _read(indexer: TorznabIndexer, offset: int) -> Page:
    query = SearchQuery(mode=SearchMode.SEARCH, limit=PAGE, offset=offset, extended=True)
    return parse_page(indexer.discovery()._get(query.params()))


def _store(indexer: TorznabIndexer, store: Store, page: Page, now: float) -> int:
    """Save a page's usable items (those with an infohash); return how many were new."""
    found = [c for c in page.items if c.infohash]
    hashes = [str(c.infohash).lower() for c in found]
    known = store.known_hashes(hashes)
    store.save_catalogue([row(indexer, c, now) for c in found])
    return len(set(hashes) - known)


def crawl(
    indexer: TorznabIndexer,
    store: Store,
    *,
    stop: Callable[[], bool] = lambda: False,
    progress: Progress = lambda p: None,
    max_pages: int | None = None,
    clock: Callable[[], float] = time.time,
) -> Outcome:
    """Page the full feed from the stored offset to its end; safe to interrupt at any time."""
    store = store.for_tracker(TR4KER)
    state = store.crawl_state(CRAWL)
    if state.complete:
        return Outcome("idle", 0, 0, 0, True)
    totals = store.feed_state(FEED)
    offset, pages, added = state.next_offset, 0, 0
    status, reached = "done", False
    while True:
        if stop():
            status = "cancelled"
            break
        if max_pages is not None and pages >= max_pages:
            break
        try:
            page = _read(indexer, offset)
        except InterruptedError:
            status = "cancelled"  # a wait for Retry-After was cancelled
            break
        except RateLimited:
            status = "rate_limited"  # the pacer already rests for the Retry-After it was given
            break
        except KeyRefused:
            status = "refused"
            break
        except (httpx.HTTPError, OSError, ValueError):
            status = "unreachable"
            break
        added += _store(indexer, store, page, clock())
        pages += 1
        offset += PAGE
        # Saved after every page: an interruption resumes exactly here.
        store.save_crawl_state(CrawlState(CRAWL, offset, False, clock()))
        store.save_feed_state(
            FeedState(FEED, totals.next_page + pages, clock(), store.catalogue_size())
        )
        progress({"phase": "fetching", "tracker": TR4KER, "pages": pages, "offset": offset})
        if len(page.items) < PAGE:  # a short or empty page is the end of the feed
            reached = True
            break
    if reached:
        store.save_crawl_state(CrawlState(CRAWL, 0, True, clock()))
    return Outcome(status, pages, added, 0 if reached else offset, reached)


def refresh(
    indexer: TorznabIndexer,
    store: Store,
    *,
    stop: Callable[[], bool] = lambda: False,
    progress: Progress = lambda p: None,
    clock: Callable[[], float] = time.time,
) -> Outcome:
    """The newest pages, down to the first holding nothing new: what a finished crawl needs."""
    store = store.for_tracker(TR4KER)
    offset, pages, added, status = 0, 0, 0, "done"
    while pages < REFRESH_PAGES:
        if stop():
            status = "cancelled"
            break
        try:
            page = _read(indexer, offset)
        except InterruptedError:
            status = "cancelled"
            break
        except RateLimited:
            status = "rate_limited"
            break
        except KeyRefused:
            status = "refused"
            break
        except (httpx.HTTPError, OSError, ValueError):
            status = "unreachable"
            break
        new = _store(indexer, store, page, clock())
        pages += 1
        added += new
        offset += PAGE
        progress({"phase": "refreshing", "tracker": TR4KER, "pages": pages, "added": added})
        if new == 0 or len(page.items) < PAGE:
            break
    if status == "done":
        store.save_feed_state(FeedState(LATEST, updated_at=clock(), count=added))
    return Outcome(status, pages, added, offset, False)


def due(store: Store, now: float | None = None) -> bool:
    """Whether a crawl is unfinished, or the last refresh is older than REFRESH_INTERVAL."""
    scoped = store.for_tracker(TR4KER)
    if not scoped.crawl_state(CRAWL).complete:
        return True
    last = scoped.feed_state(LATEST).updated_at
    return last is None or (time.time() if now is None else now) - last >= REFRESH_INTERVAL


def run(
    indexer: TorznabIndexer,
    store: Store,
    stop: threading.Event | None = None,
    progress: Progress = lambda p: None,
    clock: Callable[[], float] = time.time,
) -> Outcome:
    """Continue the crawl if it is unfinished, else refresh from the newest. Cancelling
    `stop` also interrupts a wait for `Retry-After`."""
    scoped = store.for_tracker(TR4KER)
    cancelled = stop.is_set if stop is not None else (lambda: False)
    with indexer.background(stop):
        if not scoped.crawl_state(CRAWL).complete:
            return crawl(indexer, store, stop=cancelled, progress=progress, clock=clock)
        return refresh(indexer, store, stop=cancelled, progress=progress, clock=clock)


def coverage(store: Store) -> dict[str, Any]:
    """What was measured: pages and items read, the offset reached, whether a crawl ever
    reached the feed's end. It never states a total for the tracker."""
    scoped = store.for_tracker(TR4KER)
    state, totals = scoped.crawl_state(CRAWL), scoped.feed_state(FEED)
    return {
        "tracker": TR4KER,
        "items": scoped.catalogue_size(),
        "pages": max(totals.next_page - 1, 0),
        "last_offset": state.next_offset,
        "reached_end": state.complete,
        "updated_at": state.updated_at,
        "measured": True,  # counts of what was read, not of what tr4ker holds
    }
