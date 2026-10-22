"""Indexer: a Torznab endpoint where Candidates are searched."""

from __future__ import annotations

import hashlib
import threading
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from urllib.parse import urlsplit

import httpx

from torrentlinker.ratelimit import BudgetQueue, Queue, WindowQueue
from torrentlinker.store import Store

TORZNAB_NS = "{http://torznab.com/schemas/2015/feed}"
MAX_RETRIES = 3
SEARCH_CACHE_MAX_AGE = 24 * 3600
API_KEY_PLACEHOLDER = "{{TORRENTLINKER_APIKEY}}"


class RateLimited(Exception):
    """The Indexer answered 429; it asks to wait `retry_after` seconds."""

    def __init__(self, retry_after: float) -> None:
        super().__init__(f"rate limited, retry after {retry_after:.0f} s")
        self.retry_after = retry_after


class KeyRefused(Exception):
    """The Indexer refused the API key (401 or 403): wrong, revoked or missing a scope."""

    def __init__(self, status: int, key_number: int = 1, scope: str = "torznab:read") -> None:
        which = "the API key" if key_number == 1 else f"API key {key_number}"
        super().__init__(
            f"the Indexer refused {which} (HTTP {status}): check it in Settings → "
            f"Connections; on c411 it needs the {scope} scope"
        )
        self.status = status
        self.key_number = key_number
        self.scope = scope


MAX_KEYS = 5  # c411's limit per account
# A request the user waits for gives up, rather than wait longer than this for c411.
FOREGROUND_PATIENCE = 30.0  # seconds


@dataclass
class KeySlot:
    """One API key and its own two queues: c411 limits each key separately (ADR-0008)."""

    number: int  # 1 for the main key
    key: str
    api: BudgetQueue
    downloads: Queue
    resting: dict[str, float] = field(default_factory=dict)  # queue name -> until (clock)

    def queue(self, name: str) -> Queue:
        return self.api if name == "api" else self.downloads


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
        wall: Callable[[], float] = time.time,
        extra_keys: Sequence[str] = (),
    ) -> None:
        self.url = url
        self.api_key = api_key  # the main key: profile, stored URLs, the first slot
        self._http = http or httpx.Client(timeout=30, follow_redirects=True)
        self._clock = clock
        self._sleep = sleep
        self._cache = cache
        self.extra_keys = tuple(extra_keys)
        keys = [k for k in dict.fromkeys([api_key, *extra_keys]) if k][:MAX_KEYS] or [api_key]
        # Per key, two queues: c411 limits searches and .torrent downloads separately.
        self.slots = [
            KeySlot(
                n,
                k,
                BudgetQueue(clock=clock, sleep=sleep, wall=wall),
                WindowQueue(clock=clock, sleep=sleep),
            )
            for n, k in enumerate(keys, 1)
        ]
        self._caps_lock = threading.Lock()
        self._modes: dict[SearchMode, set[str]] | None = None
        self._thread = threading.local()  # .background: this thread's requests can wait

    @contextmanager
    def background(self) -> Iterator[None]:
        """Requests made in this block, on this thread, let the user's own go first and
        wait out c411's refusals (a Plan being sent, Catalogue updates)."""
        before = getattr(self._thread, "background", False)
        self._thread.background = True
        try:
            yield
        finally:
            self._thread.background = before

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
                except (httpx.HTTPError, KeyRefused, ET.ParseError):
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
        url = candidate.download_url
        data = self._request(
            lambda key: (self._with_key(url, key), None, None), retry=retry, queue="downloads"
        ).content
        if self._cache:
            self._cache.cache_torrent(self._torrent_key(candidate), data)
        return data

    def cached_torrent(self, candidate: Candidate) -> bytes | None:
        """The Candidate's .torrent if it was fetched before; never uses the network."""
        return self._cache.cached_torrent(self._torrent_key(candidate)) if self._cache else None

    def _torrent_key(self, candidate: Candidate) -> str:
        return hashlib.sha1(self._redact(candidate.download_url).encode()).hexdigest()

    def _redact(self, body: str) -> str:
        for slot in self.slots:
            if slot.key:
                body = body.replace(slot.key, API_KEY_PLACEHOLDER)
        return body

    def _with_key(self, url: str, key: str) -> str:
        """A URL made with the main key, as another key would make it."""
        return url.replace(self.api_key, key) if self.api_key else url

    def redact(self, text: str) -> str:
        """`text` with the API key replaced by a placeholder, safe to store."""
        return self._redact(text)

    def unredact(self, text: str) -> str:
        return text.replace(API_KEY_PLACEHOLDER, self.api_key)

    def _get(self, params: dict[str, str]) -> str:
        return self._request(lambda key: (self.url, {**params, "apikey": key}, None)).text

    @property
    def is_c411(self) -> bool:
        return urlsplit(self.url).hostname == "c411.org"

    def catalogue_json(self, params: dict[str, str]) -> dict[str, Any]:
        """c411's live catalogue, sharing the Torznab rate limiter and key."""
        if not self.is_c411:
            raise ValueError("The JSON catalogue is only available on c411.org")
        return self._request(
            lambda key: (
                "https://c411.org/api/torrents",
                params,
                {"Authorization": f"Bearer {key}"},
            )
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
            lambda key: (
                f"https://c411.org/api/torrents/{infohash}",
                None,
                {"Authorization": f"Bearer {key}"},
            )
        ).json()

    def drafts(self) -> list[dict[str, Any]]:
        """The account's c411 upload Drafts (main key, scope drafts:rw; ADR-0011)."""
        return list(self._draft_request("GET", "/api/user/drafts").json().get("data") or [])

    def save_draft(self, body: dict[str, Any]) -> int:
        """Save a new c411 Draft and return its id."""
        return int(self._draft_request("POST", "/api/user/drafts", body).json()["data"]["id"])

    def _draft_request(
        self, method: str, path: str, body: dict[str, Any] | None = None
    ) -> httpx.Response:
        if not self.is_c411:
            raise ValueError("Drafts are only available on c411.org")
        return self._request(
            lambda key: (f"https://c411.org{path}", None, {"Authorization": f"Bearer {key}"}),
            method=method,
            json=body,
            main_key_only=True,
            scope="drafts:rw",
        )

    def _request(
        self,
        build: Callable[[str], tuple[str, dict[str, str] | None, dict[str, str] | None]],
        *,
        retry: bool = True,
        queue: str = "api",
        method: str = "GET",
        json: Any = None,
        main_key_only: bool = False,
        scope: str = "torznab:read",
    ) -> httpx.Response:
        """Send with the key whose queue is free soonest; `build(key)` gives the URL,
        parameters and headers. A key refused with 429 rests as long as c411 asks while
        the others go on. With every key resting, a background request waits; a
        foreground one, or one with `retry=False`, raises RateLimited unless the wait is
        short. `main_key_only` keeps to the main key, for what only it may do."""
        background = getattr(self._thread, "background", False)
        waits = 0
        last: httpx.Response | None = None  # keys only rest after a 429, so it is set
        while True:
            slots = self.slots[:1] if main_key_only else self.slots
            slot = self._pick(queue, slots)
            if slot is None:
                wait = min(s.resting.get(queue, 0.0) for s in slots) - self._clock()
                if not retry or (not background and wait > FOREGROUND_PATIENCE):
                    raise RateLimited(max(wait, 0.0))
                if waits >= MAX_RETRIES and last is not None:
                    return self._checked(last)
                waits += 1
                self._sleep(max(wait, 0.0))
                continue
            lane = slot.queue(queue)
            url, params, headers = build(slot.key)
            with lane.turn(background):
                last = self._http.request(method, url, params=params, headers=headers, json=json)
                lane.observe(last.headers)
            if last.status_code == 429:
                slot.resting[queue] = self._clock() + _retry_after(last)
                continue
            if last.status_code in (401, 403):
                raise KeyRefused(last.status_code, slot.number, scope)
            return self._checked(last)

    def _pick(self, queue: str, slots: Sequence[KeySlot]) -> KeySlot | None:
        """The key, among those not resting, whose queue lets a request go soonest."""
        now = self._clock()
        ready = [s for s in slots if s.resting.get(queue, 0.0) <= now]
        return min(ready, key=lambda s: s.queue(queue).next_in()) if ready else None

    def _checked(self, response: httpx.Response) -> httpx.Response:
        """The response if it succeeded; errors never carry the key, which URLs hold."""
        if response.status_code in (401, 403):
            raise KeyRefused(response.status_code)
        try:
            return response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise httpx.HTTPStatusError(
                self._redact(str(e)), request=e.request, response=e.response
            ) from None

    def next_request_in(self) -> float:
        """Seconds before the next search or Catalogue request may go, with any key."""
        now = self._clock()
        return min(max(s.api.next_in(), s.resting.get("api", 0.0) - now) for s in self.slots)

    @property
    def api(self) -> BudgetQueue:
        """The main key's search queue."""
        return self.slots[0].api


def _retry_after(response: httpx.Response) -> float:
    """The wait c411 asks for; a download refusal says `43, 60` (the wait, the window)."""
    try:
        return float(response.headers.get("Retry-After", "25").split(",")[0])
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
