"""tr4ker's native API as Search and the detail view read it (ADR-0025, issue 177).

The native routes need a signed-in browser session, so they are read through the companion
(`Tr4kerAccount.read_json`) like the other native reads. When no companion answers, Search
falls back to Torznab (`/api`). Nothing here holds a key, passkey or cookie: the reader is
passed in, and the Torznab Indexer redacts its own key.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol
from urllib.parse import quote, urlencode, urlsplit

from torrentlinker.indexer import Candidate, SearchQuery, publication_time
from torrentlinker.torrent_details import (
    Media,
    TorrentDetails,
    preview_html,
    web_url,
)
from torrentlinker.trackers import TR4KER, tracker

ORIGIN = tracker(TR4KER).origin
# tr4ker answers HTTP 500 {"error": "erreur base de données"} for these (retest 23 Nov 2026,
# docs/research/tr4ker-integration.md). They are never sent: Search sorts by them inside
# TorrentLinker on the rows it fetched. Switch an entry off here once tr4ker fixes it.
# A value of None means "any value of that parameter".
BROKEN_NATIVE: dict[str, frozenset[str] | None] = {
    "sort": frozenset({"seeders", "title", "size", "leechers"}),
    "search_in": None,
}
NATIVE_SORTS = ("recent", "completed")  # the sorts tr4ker's own listing answers
# How long a Search waits for the companion. The browser extension polls for work in bursts:
# it stays awake about 10 s, then sleeps until its next alarm (30-60 s). A read submitted in
# that gap cannot be answered until the extension wakes, so Search gives up well before
# `read_json`'s own minute and says so, instead of holding c411's rows behind it.
SEARCH_TIMEOUT = 12.0
LOCAL_SORTS = ("seeders", "size", "title", "leechers")  # sorted here, on the fetched rows
MAX_LIMIT = 100
SLUG = re.compile(r"[A-Za-z0-9_-]{1,200}")


class Reader(Protocol):
    """What the companion session offers: `Tr4kerAccount`."""

    @property
    def can_read(self) -> bool: ...

    def read_json(self, path: str, timeout: float = 60.0) -> dict[str, Any]: ...


@dataclass(frozen=True)
class NativePage:
    rows: list[Candidate]
    page: int
    limit: int
    total: int | None
    capped: bool
    backend: str = "tr4ker-native"  # or "torznab" after the fallback
    notes: list[str] = field(default_factory=list)


def refuse_broken(params: dict[str, Any]) -> None:
    """Never let a parameter tr4ker answers with a 500 reach it."""
    for name, broken in BROKEN_NATIVE.items():
        value = params.get(name)
        if value is None or value == "":
            continue
        if broken is None or str(value) in broken:
            raise ValueError(f"tr4ker's native search fails on {name}={value}; not sent.")


def native_path(
    query: str = "",
    *,
    category: str = "",
    page: int = 1,
    limit: int = 50,
    tmdb_id: int | str | None = None,
    freeleech: bool = False,
    sort: str = "recent",
) -> str:
    """The `/api/torrents` request for the parameters that work, nothing else."""
    if sort not in NATIVE_SORTS:
        refuse_broken({"sort": sort})
        raise ValueError("Unknown tr4ker sort.")
    params: dict[str, str] = {}
    if query:
        params["q"] = query
    if category:
        params["cat"] = category
    if tmdb_id not in (None, ""):
        params["tmdb_id"] = str(tmdb_id)
    if freeleech:
        params["freeleech"] = "1"
    params["sort"] = sort
    params["page"] = str(max(1, int(page)))
    params["limit"] = str(max(1, min(int(limit), MAX_LIMIT)))
    refuse_broken(params)
    return "/api/torrents?" + urlencode(params, quote_via=quote)


def _int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def parse_row(item: Any) -> Candidate | None:
    """One native listing row as a Candidate. The row has no info hash (only the detail has),
    so the slug is the identity; the numeric ID and the slug stay in the metadata."""
    if not isinstance(item, dict):
        return None
    slug = _text(item.get("slug"))
    if not SLUG.fullmatch(slug) or not _text(item.get("name")):
        return None
    return Candidate(
        _text(item["name"]),
        _int(item.get("size_bytes")),
        f"{ORIGIN}/api/torrents/{slug}/download",
        _int(item.get("seeders")),
        None,
        f"{ORIGIN}/torrent/{slug}",
        (),
        publication_time(item.get("created_at")),
        {
            "tracker": TR4KER,
            "slug": slug,
            "tr4ker_id": item.get("id") if isinstance(item.get("id"), int) else None,
            "leechers": _int(item.get("leechers")),
            "completions": _int(item.get("times_completed")),
            "freeleech": item.get("is_freeleech") is True,
            "category": _text(item.get("parent_cat_name")),
            "category_slug": _text(item.get("parent_cat_slug")),
            "subcategory": _text(item.get("sub_cat_name")),
            "year": item.get("year") if isinstance(item.get("year"), int) else None,
            "tmdb_id": item.get("tmdb_id") if isinstance(item.get("tmdb_id"), int) else None,
            "poster": web_url(_text(item.get("poster_url"))),
            "files": _int(item.get("file_count")),
        },
    )


def parse_listing(body: Any) -> NativePage:
    torrents = body.get("torrents") if isinstance(body, dict) else None
    if not isinstance(torrents, list):
        raise ValueError("tr4ker returned an unexpected listing.")
    rows = [row for row in map(parse_row, torrents) if row is not None]
    total = body.get("total")
    return NativePage(
        rows,
        _int(body.get("page")) or 1,
        _int(body.get("limit")) or len(rows),
        total if isinstance(total, int) and not isinstance(total, bool) else None,
        body.get("total_capped") is True,
    )


def _local_key(by: str) -> Callable[[Candidate], Any]:
    if by == "title":
        return lambda c: c.title.casefold()
    if by == "size":
        return lambda c: c.size
    if by == "leechers":
        return lambda c: c.metadata.get("leechers", 0)
    if by == "seeders":
        return lambda c: c.seeders
    return lambda c: c.published_at or 0.0


def sort_rows(rows: list[Candidate], by: str, descending: bool = True) -> list[Candidate]:
    """The sorts tr4ker cannot do, done on the rows we hold (a page, not the whole feed)."""
    return sorted(rows, key=_local_key(by), reverse=descending)


class Torznab(Protocol):
    def search(self, query: SearchQuery) -> list[Candidate]: ...


def torznab_row(candidate: Candidate) -> Candidate:
    """A Torznab result of tr4ker, tagged so merged Search can badge it."""
    return Candidate(
        candidate.title,
        candidate.size,
        candidate.download_url,
        candidate.seeders,
        candidate.infohash,
        candidate.details_url,
        candidate.categories,
        candidate.published_at,
        {**candidate.metadata, "tracker": TR4KER},
    )


def search(
    session: Reader | None,
    fallback: Torznab | None,
    query: str,
    *,
    category: str = "",
    page: int = 1,
    limit: int = 50,
    tmdb_id: int | str | None = None,
    freeleech: bool = False,
    sort: str = "recent",
    torznab_category: int | None = None,
    timeout: float = SEARCH_TIMEOUT,
) -> NativePage:
    """tr4ker rows for merged Search: native through the companion, else Torznab.

    A sort tr4ker cannot do is applied here to the fetched rows; the native request then asks
    for `recent`. A native failure is raised as it is, never retried or hidden behind Torznab:
    only an absent companion (not paired, tab closed) selects the fallback. `timeout` bounds
    the wait on the companion, which answers in bursts (SEARCH_TIMEOUT)."""
    local = sort if sort in LOCAL_SORTS else ""
    if session is not None and session.can_read:
        path = native_path(
            query,
            category=category,
            page=page,
            limit=limit,
            tmdb_id=tmdb_id,
            freeleech=freeleech,
            sort="completed" if sort == "completed" else "recent",
        )
        found = parse_listing(session.read_json(path, timeout=timeout))
        rows = sort_rows(found.rows, local) if local else found.rows
        notes = [f"Sorted by {local} here: tr4ker cannot sort by it."] if local else []
        return NativePage(rows, found.page, found.limit, found.total, found.capped, notes=notes)
    if fallback is None:
        raise ValueError("Pair the tr4ker companion or add the tr4ker Indexer to search tr4ker.")
    rows = [
        torznab_row(c)
        for c in fallback.search(
            SearchQuery(
                q=query,
                categories=(torznab_category,) if torznab_category else (),
                limit=min(limit, MAX_LIMIT),
                offset=(max(1, page) - 1) * min(limit, MAX_LIMIT),
            )
        )
    ]
    if local:
        rows = sort_rows(rows, local)
    return NativePage(
        rows,
        page,
        limit,
        None,
        False,
        "torznab",
        ["The companion is not paired: tr4ker rows come from Torznab."],
    )


# ---- detail ----


def _files(item: Any) -> tuple[tuple[str, int], ...]:
    out = []
    for entry in item.get("files") if isinstance(item.get("files"), list) else []:
        if isinstance(entry, dict) and _text(entry.get("path")):
            out.append((_text(entry["path"]), _int(entry.get("size_bytes"))))
    return tuple(out)


def parse_detail(payload: dict[str, Any]) -> tuple[TorrentDetails, dict[str, Any]]:
    """tr4ker's `GET /api/torrents/<slug>` as the shared details model, plus the identity
    triple (numeric ID, slug, info hash) kept apart."""
    description = _text(payload.get("description")) or _text(payload.get("classic_description"))
    facts: list[tuple[str, tuple[str, ...]]] = []
    for label, value in (
        ("Release type", _text(payload.get("release_type"))),
        ("Source", _text(payload.get("source"))),
        ("Year", str(payload["year"]) if isinstance(payload.get("year"), int) else ""),
    ):
        if value:
            facts.append((label, (value,)))
    tags = tuple(t for t in payload.get("tags") or [] if isinstance(t, str) and t)
    if tags:
        facts.append(("Tags", tags))
    flags = tuple(
        label
        for key, label in (
            ("is_freeleech", "Freeleech"),
            ("is_double_upload", "Double upload"),
            ("is_internal", "Internal"),
        )
        if payload.get(key) is True
    )
    if flags:
        facts.append(("Status", flags))
    tmdb = payload.get("tmdb_id")
    media = (
        Media(
            "",
            "",
            payload["year"] if isinstance(payload.get("year"), int) else None,
            _text(payload.get("tmdb_type")),
            tmdb_id=str(tmdb),
        )
        if isinstance(tmdb, int) and not isinstance(tmdb, bool)
        else None
    )
    files = _files(payload)
    details = TorrentDetails(
        description,
        _text(payload.get("nfo")),
        bool(_text(payload.get("nfo"))),
        web_url(_text(payload.get("poster_url")) or _text(payload.get("classic_cover_url"))),
        files,
        "" if payload.get("is_anonymous") is True else _text(payload.get("uploader")),
        "",
        publication_time(payload.get("created_at")),
        payload.get("is_exclusive") is True,
        False,
        _int(payload.get("seeders")),
        _int(payload.get("leechers")),
        _int(payload.get("times_completed")),
        _text(payload.get("cat_name")),
        _text(payload.get("sub_cat_name")),
        tuple(facts),
        media=media,
    )
    info_hash = _text(payload.get("info_hash")).lower()
    identity = {
        "id": payload.get("id") if isinstance(payload.get("id"), int) else None,
        "slug": _text(payload.get("slug")),
        "info_hash": info_hash if re.fullmatch(r"[0-9a-f]{40}", info_hash) else "",
    }
    return details, identity


def detail_document(payload: dict[str, Any]) -> dict[str, Any]:
    """The document the Search detail view paints, as DetailsWorkspace builds it for c411.
    A function tr4ker lacks is listed as unavailable, never hidden or faked."""
    details, identity = parse_detail(payload)
    markup, images = preview_html(details.description, details.poster)
    facts = asdict(details)
    for key in ("description", "nfo", "files", "has_nfo"):
        facts.pop(key, None)
    size = payload.get("size_bytes")
    return {
        "title": _text(payload.get("name")),
        "size": size if isinstance(size, int) and not isinstance(size, bool) else 0,
        "description": markup,
        "images": images,
        "nfo": details.nfo,
        "files": details.files,
        "info": facts,
        "tracker": TR4KER,
        "tr4ker": identity,
        "unavailable": ["trust", "team", "options"],
    }


def slug_of(value: str) -> str:
    """The slug behind a tr4ker key. Native Search keys a row `tr4ker:<slug>`, while the RSS
    feed has no slug of its own and keys its items by guid, the `/torrent/<slug>` page URL.
    Both reach the detail view, so both are accepted here; anything else gives "".
    """
    value = value.strip()
    if "/" in value or ":" in value:
        parts = urlsplit(value)
        if f"{parts.scheme}://{parts.netloc}" != ORIGIN or not parts.path.startswith("/torrent/"):
            return ""
        value = parts.path.rstrip("/").rsplit("/", 1)[-1]
    return value if SLUG.fullmatch(value) else ""


def read_detail(session: Reader, slug: str) -> dict[str, Any]:
    slug = slug_of(slug)
    if not slug:
        raise ValueError("Select a tr4ker torrent with a valid slug.")
    return detail_document(session.read_json(f"/api/torrents/{slug}"))
