"""Reseed's sources: c411 and tr4ker side by side (ADR-0025, issue 176).

Reseed's discovery, comparison and download used to speak to c411 alone. A `Sources` object
stands where the c411 Indexer stood: it searches c411 as before and tr4ker's full feed
(`/api/torznab/all`, which also lists torrents without seeders) when its Indexer is added with
a key, stamps every Candidate with its Tracker, and sends each fetch to the Indexer the
Candidate came from. A tr4ker .torrent embeds the passkey: nothing here logs bytes or URLs,
and the Indexer keeps fetched torrents in private (0600) storage.
"""

from __future__ import annotations

import contextlib
import io
from collections.abc import Callable
from dataclasses import replace
from typing import Any

import httpx
import torf

from torrentlinker.indexer import Candidate, KeyRefused, RateLimited, SearchMode
from torrentlinker.trackers import C411, tracker_of_url


def torrent_tracker(data: bytes) -> str | None:
    """The Tracker a .torrent announces to (c411, tr4ker), by announce host; None for any
    other. Never raises on bytes it cannot read."""
    try:
        parsed = torf.Torrent.read_stream(io.BytesIO(data), validate=False)
        urls = [url for tier in parsed.trackers for url in tier]
    except Exception:  # noqa: BLE001 - an unreadable file simply has no known Tracker
        return None
    for url in urls:
        if (found := tracker_of_url(str(url))) is not None:
            return found.id
    return None


class Sources:
    """The c411 Indexer plus the other Trackers' Indexers, behaving as c411's where Reseed
    does not care which Tracker answers (any other attribute is c411's own)."""

    def __init__(self, c411: Any, others: Callable[[], dict[str, Any]]):
        self._c411, self._others = c411, others
        self.skipped: dict[str, str] = {}  # Tracker -> why its search was left out

    def __getattr__(self, name: str) -> Any:
        return getattr(self._c411, name)

    def trackers(self) -> dict[str, Any]:
        return {C411: self._c411, **self._others()}

    def for_tracker(self, tracker: str) -> Any:
        try:
            return self.trackers()[tracker or C411]
        except KeyError:
            raise ValueError(f"The {tracker} Tracker is not configured for Reseed.") from None

    def of(self, candidate: Candidate) -> Any:
        """The Indexer a Candidate came from."""
        return self.for_tracker(candidate.tracker)

    # Discovery -------------------------------------------------------------------

    def search_others(
        self, find: Callable[[Any, dict[SearchMode, set[str]] | None], list[Candidate]]
    ) -> list[Candidate]:
        """Run `find(indexer, modes)` on every other Tracker's discovery feed, marked with its
        Tracker. A Tracker that cannot answer is skipped: c411's results never wait for it."""
        found: list[Candidate] = []
        self.skipped = {}
        for name, indexer in self._others().items():
            feed = indexer.discovery() if hasattr(indexer, "discovery") else indexer
            try:
                rows = find(feed, feed.supported_modes())
            except (RateLimited, KeyRefused, httpx.HTTPError) as error:
                self.skipped[name] = indexer.redact(str(error)) or type(error).__name__
                continue
            found += [c if c.tracker == name else replace(c, tracker=name) for c in rows]
        return found

    # Fetching --------------------------------------------------------------------

    def fetch_torrent(self, candidate: Candidate, *, retry: bool = True) -> bytes:
        data = self.of(candidate).fetch_torrent(candidate, retry=retry)
        owner = torrent_tracker(data)
        wanted = candidate.tracker or C411
        if owner is not None and owner != wanted:
            # One torrent per Tracker: a file announcing to another Tracker is not this one's.
            raise ValueError(f"{candidate.title}: the torrent does not announce to {wanted}.")
        return data

    def cached_torrent(self, candidate: Candidate) -> bytes | None:
        return self.of(candidate).cached_torrent(candidate)

    def keep_torrent(self, candidate: Candidate, data: bytes) -> None:
        self.of(candidate).keep_torrent(candidate, data)

    def redact(self, text: str) -> str:
        for indexer in self.trackers().values():
            text = indexer.redact(text)
        return text

    def unredact_for(self, tracker: str, text: str) -> str:
        return self.for_tracker(tracker).unredact(text)

    @contextlib.contextmanager
    def background(self, stop: Any = None):
        with contextlib.ExitStack() as stack:
            for indexer in self.trackers().values():
                stack.enter_context(indexer.background(stop))
            yield
