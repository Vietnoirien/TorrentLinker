"""Indexer: a Torznab endpoint where Candidates are searched."""

from __future__ import annotations

import hashlib
import threading
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from urllib.parse import urlsplit

import httpx

from torrentlinker.store import Store

TORZNAB_NS = "{http://torznab.com/schemas/2015/feed}"
MIN_INTERVAL = 4.1  # seconds; c411 answers 429 above ~15 requests per minute
MAX_RETRIES = 3
SEARCH_CACHE_MAX_AGE = 24 * 3600
API_KEY_PLACEHOLDER = "{{TORRENTLINKER_APIKEY}}"


class RateLimited(Exception):
    """The Indexer answered 429; it asks to wait `retry_after` seconds."""

    def __init__(self, retry_after: float) -> None:
        super().__init__(f"rate limited, retry after {retry_after:.0f} s")
        self.retry_after = retry_after


class SearchMode(StrEnum):
    """Torznab search functions (`t=`)."""

    SEARCH = "search"
    MOVIE = "movie"
    TV = "tvsearch"
    MUSIC = "music"
    BOOK = "book"


@dataclass(frozen=True)
class SearchQuery:
    q: str = ""
    mode: SearchMode = SearchMode.SEARCH
    categories: tuple[int, ...] = ()
    imdbid: str | None = None
    tmdbid: str | None = None
    season: int | None = None
    ep: int | None = None
    limit: int | None = None
    offset: int | None = None
    extended: bool = False

    def params(self) -> dict[str, str]:
        p = {"t": self.mode.value}
        if self.limit is not None:
            p["limit"] = str(self.limit)
        if self.offset is not None:
            p["offset"] = str(self.offset)
        if self.extended:
            p["extended"] = "1"
        if self.q:
            p["q"] = self.q
        if self.categories:
            p["cat"] = ",".join(str(c) for c in self.categories)
        if self.imdbid:
            p["imdbid"] = self.imdbid
        if self.tmdbid:
            p["tmdbid"] = self.tmdbid
        if self.season is not None:
            p["season"] = str(self.season)
        if self.ep is not None:
            p["ep"] = str(self.ep)
        return p


@dataclass(frozen=True)
class Candidate:
    title: str
    size: int
    download_url: str
    seeders: int = 0
    infohash: str | None = None
    details_url: str = ""
    categories: tuple[int, ...] = field(default=())


_CAPS_MODES = {
    "search": SearchMode.SEARCH,
    "tv-search": SearchMode.TV,
    "movie-search": SearchMode.MOVIE,
    "music-search": SearchMode.MUSIC,
    "audio-search": SearchMode.MUSIC,
    "book-search": SearchMode.BOOK,
}


@dataclass(frozen=True)
class Caps:
    categories: dict[int, str]
    modes: dict[SearchMode, set[str]]
    parents: dict[int, int] = field(default_factory=dict)  # subcategory -> category


def _category_tree(root: ET.Element) -> tuple[dict[int, str], dict[int, int]]:
    """Labels and parents of the Indexer's category ids, one entry per id.

    An Indexer may reuse a Newznab id for several of its own categories (c411 files
    "Série TV" as 5000 under "Films & Vidéos", and 4050 under five categories). Results
    only carry the id, so each id gets every meaning it covers in its label, sits under
    the first category that lists it, and is top-level if it is a category itself.
    """

    def label(el: ET.Element) -> str:
        return el.get("description") or el.get("name") or ""

    tops = [el for el in root.iter("category") if (el.get("id") or "").isdigit()]
    top_ids = {int(el.get("id", "0")) for el in tops}
    meanings: dict[int, list[str]] = {}
    parents: dict[int, int] = {}

    def add(cid: int, text: str) -> None:
        known = meanings.setdefault(cid, [])
        if text and text not in known:
            known.append(text)

    for el in tops:
        add(int(el.get("id", "0")), label(el))
    for el in tops:
        parent = int(el.get("id", "0"))
        for sub in el.iter("subcat"):
            if not (sub.get("id") or "").isdigit():
                continue
            cid = int(sub.get("id", "0"))
            add(cid, label(sub))
            if cid not in top_ids and cid not in parents:
                parents[cid] = parent
    return {cid: " / ".join(texts) for cid, texts in meanings.items()}, parents


class Indexer:
    def __init__(
        self,
        url: str,
        api_key: str,
        http: httpx.Client | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        cache: Store | None = None,
    ) -> None:
        self.url = url
        self.api_key = api_key
        self._http = http or httpx.Client(timeout=30, follow_redirects=True)
        self._clock = clock
        self._sleep = sleep
        self._cache = cache
        self._lock = threading.Lock()
        self._caps_lock = threading.Lock()
        self._modes: dict[SearchMode, set[str]] | None = None
        self._last_request: float | None = None

    def caps(self) -> Caps:
        root = ET.fromstring(self._get({"t": "caps"}))
        modes: dict[SearchMode, set[str]] = {}
        for el in root.iterfind("searching/*"):
            mode = _CAPS_MODES.get(el.tag)
            if mode and el.get("available") == "yes":
                modes[mode] = {p for p in el.get("supportedParams", "q").split(",") if p}
        categories, parents = _category_tree(root)
        return Caps(categories, modes, parents)

    def supported_modes(self) -> dict[SearchMode, set[str]] | None:
        """Search modes and their parameters from caps, fetched once; None if unknown."""
        with self._caps_lock:
            if self._modes is None:
                try:
                    self._modes = self.caps().modes
                except (httpx.HTTPError, ET.ParseError):
                    return None
            return self._modes

    def search(self, query: SearchQuery, cached: bool = True) -> list[Candidate]:
        """Run a Torznab search; `cached=False` always asks the Indexer and keeps nothing."""
        params = query.params()
        if not cached:
            return _parse_items(self._get(params))
        key = self.url + "?" + "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        body = self._cache.cached_search(key, SEARCH_CACHE_MAX_AGE) if self._cache else None
        if body is None:
            body = self._get(params)
            if self._cache:
                self._cache.cache_search(key, self._redact(body))
        else:
            body = self.unredact(body)
        return _parse_items(body)

    def fetch_torrent(self, candidate: Candidate, *, retry: bool = True) -> bytes:
        """The Candidate's .torrent; downloaded at most once (it may count as a grab).

        With `retry=False` a 429 raises RateLimited at once, so the caller can wait.
        """
        if (data := self.cached_torrent(candidate)) is not None:
            return data
        data = self._request(candidate.download_url, retry=retry).content
        if self._cache:
            self._cache.cache_torrent(self._torrent_key(candidate), data)
        return data

    def cached_torrent(self, candidate: Candidate) -> bytes | None:
        """The Candidate's .torrent if it was fetched before; never uses the network."""
        return self._cache.cached_torrent(self._torrent_key(candidate)) if self._cache else None

    def _torrent_key(self, candidate: Candidate) -> str:
        return hashlib.sha1(self._redact(candidate.download_url).encode()).hexdigest()

    def _redact(self, body: str) -> str:
        return body.replace(self.api_key, API_KEY_PLACEHOLDER) if self.api_key else body

    def redact(self, text: str) -> str:
        """`text` with the API key replaced by a placeholder, safe to store."""
        return self._redact(text)

    def unredact(self, text: str) -> str:
        return text.replace(API_KEY_PLACEHOLDER, self.api_key)

    def _get(self, params: dict[str, str]) -> str:
        return self._request(self.url, {**params, "apikey": self.api_key}).text

    @property
    def is_c411(self) -> bool:
        return urlsplit(self.url).hostname == "c411.org"

    def catalogue_json(self, params: dict[str, str]) -> dict[str, Any]:
        """c411's live catalogue, sharing the Torznab rate limiter and key."""
        if not self.is_c411:
            raise ValueError("The JSON catalogue is only available on c411.org")
        return self._request(
            "https://c411.org/api/torrents",
            params,
            headers={"Authorization": f"Bearer {self.api_key}"},
        ).json()

    def torrent_json(self, infohash: str) -> dict[str, Any]:
        """Read live metadata only; this does not grab a .torrent."""
        if (
            not self.is_c411
            or len(infohash) != 40
            or any(c not in "0123456789abcdef" for c in infohash)
        ):
            raise ValueError("Invalid c411 torrent hash")
        return self._request(
            f"https://c411.org/api/torrents/{infohash}",
            headers={"Authorization": f"Bearer {self.api_key}"},
        ).json()

    def _request(
        self,
        url: str,
        params: dict[str, str] | None = None,
        *,
        headers: dict[str, str] | None = None,
        retry: bool = True,
    ) -> httpx.Response:
        with self._lock:
            if not retry:
                self._wait_turn()
                response = self._http.get(url, params=params, headers=headers)
                if response.status_code == 429:
                    raise RateLimited(_retry_after(response))
                response.raise_for_status()
                return response
            for _attempt in range(MAX_RETRIES):
                self._wait_turn()
                response = self._http.get(url, params=params, headers=headers)
                if response.status_code != 429:
                    break
                self._sleep(_retry_after(response))
            else:
                self._wait_turn()
                response = self._http.get(url, params=params, headers=headers)
        response.raise_for_status()
        return response

    def next_request_in(self) -> float:
        """Seconds before the rate limiter lets the next request through."""
        if self._last_request is None:
            return 0.0
        return max(0.0, self._last_request + MIN_INTERVAL - self._clock())

    def _wait_turn(self) -> None:
        if self._last_request is not None:
            wait = self._last_request + MIN_INTERVAL - self._clock()
            if wait > 0:
                self._sleep(wait)
        self._last_request = self._clock()


def _retry_after(response: httpx.Response) -> float:
    try:
        return float(response.headers.get("Retry-After", "25"))
    except ValueError:
        return 25.0


def _parse_items(xml: str) -> list[Candidate]:
    root = ET.fromstring(xml)
    candidates = []
    for item in root.iter("item"):
        attrs: dict[str, list[str]] = {}
        for a in item.iter(f"{TORZNAB_NS}attr"):
            attrs.setdefault(a.get("name", ""), []).append(a.get("value", ""))
        enclosure = item.find("enclosure")
        size = item.findtext("size") or attrs.get("size", ["0"])[0]
        candidates.append(
            Candidate(
                title=item.findtext("title", ""),
                size=int(size),
                download_url=enclosure.get("url", "") if enclosure is not None else "",
                seeders=int(attrs.get("seeders", ["0"])[0]),
                infohash=(attrs.get("infohash", [""])[0].lower() or None),
                details_url=item.findtext("link", "") or item.findtext("guid", ""),
                categories=tuple(int(c) for c in attrs.get("category", []) if c.isdigit()),
            )
        )
    return candidates
