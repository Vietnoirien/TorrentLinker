"""Indexer: a Torznab endpoint where Candidates are searched."""

from __future__ import annotations

import threading
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass, field

import httpx

from torrentlinker.store import Store

TORZNAB_NS = "{http://torznab.com/schemas/2015/feed}"
MIN_INTERVAL = 4.1  # seconds; c411 answers 429 above ~15 requests per minute
MAX_RETRIES = 3
SEARCH_CACHE_MAX_AGE = 24 * 3600
API_KEY_PLACEHOLDER = "{{TORRENTLINKER_APIKEY}}"


@dataclass(frozen=True)
class SearchQuery:
    q: str = ""
    mode: str = "search"  # search | movie | tvsearch | music | book
    categories: tuple[int, ...] = ()
    imdbid: str | None = None
    tmdbid: str | None = None
    season: int | None = None
    ep: int | None = None

    def params(self) -> dict[str, str]:
        p = {"t": self.mode}
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
    "search": "search",
    "tv-search": "tvsearch",
    "movie-search": "movie",
    "music-search": "music",
    "audio-search": "music",
    "book-search": "book",
}


@dataclass(frozen=True)
class Caps:
    categories: dict[int, str]
    modes: dict[str, set[str]]


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
        self._last_request: float | None = None

    def caps(self) -> Caps:
        root = ET.fromstring(self._get({"t": "caps"}))
        modes: dict[str, set[str]] = {}
        for el in root.iterfind("searching/*"):
            mode = _CAPS_MODES.get(el.tag)
            if mode and el.get("available") == "yes":
                modes[mode] = {p for p in el.get("supportedParams", "q").split(",") if p}
        categories: dict[int, str] = {}
        for el in root.iter():
            if el.tag in ("category", "subcat") and (el.get("id") or "").isdigit():
                categories[int(el.get("id", "0"))] = el.get("name", "")
        return Caps(categories, modes)

    def search(self, query: SearchQuery) -> list[Candidate]:
        params = query.params()
        key = self.url + "?" + "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        body = self._cache.cached_search(key, SEARCH_CACHE_MAX_AGE) if self._cache else None
        if body is None:
            body = self._get(params)
            if self._cache:
                self._cache.cache_search(key, self._redact(body))
        else:
            body = body.replace(API_KEY_PLACEHOLDER, self.api_key)
        return _parse_items(body)

    def _redact(self, body: str) -> str:
        return body.replace(self.api_key, API_KEY_PLACEHOLDER) if self.api_key else body

    def _get(self, params: dict[str, str]) -> str:
        with self._lock:
            for _attempt in range(MAX_RETRIES + 1):
                self._wait_turn()
                response = self._http.get(self.url, params={**params, "apikey": self.api_key})
                if response.status_code == 429:
                    self._sleep(_retry_after(response))
                    continue
                response.raise_for_status()
                return response.text
            response.raise_for_status()
            return response.text

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
