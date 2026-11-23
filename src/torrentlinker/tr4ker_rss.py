"""tr4ker's passkey RSS feed (ADR-0025, issue 180): `/api/rss?passkey=…`, 100 latest items.

The passkey is the feed's only credential and also the identity in every `.torrent` announce,
so it is kept in the secret store (`indexer-passkey-tr4ker`) and nowhere else: not in a
subscription, a cache, a log, an error, an export or a stored enclosure or link. Every URL read
from a feed is stripped of it before it becomes a row, and an error text is redacted before it
is shown. A feed item carries no info hash: its identity is the guid, kept per Tracker.
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from torrentlinker.indexer import TORZNAB_NS, Candidate, publication_time
from torrentlinker.trackers import TR4KER, tracker

RSS_NS = "{https://tr4ker.net/rss}"
FEED_PATH = "/api/rss"
CATEGORY_SLUG = re.compile(r"[a-z0-9][a-z0-9-]{0,59}")
KEY_PREFIX = "tr4ker:"
_PASSKEY = re.compile(r"(passkey=)[^&\s\"'<>]*", re.IGNORECASE)


class _RedactPasskey(logging.Filter):
    """httpx logs every request URL at INFO; the feed's URL holds the passkey. The app keeps
    that logger at WARNING, and this filter hides the passkey even when someone lowers it."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if "passkey=" in message.lower():
            record.msg, record.args = redact_passkey(message), None
        return True


logging.getLogger("httpx").addFilter(_RedactPasskey())


class FeedRefused(Exception):
    """tr4ker's feed did not answer with items; the message never holds the passkey."""


def redact_passkey(text: str, passkey: str = "") -> str:
    """Hide the passkey wherever it was named in a URL, and anywhere else it is spelled."""
    text = _PASSKEY.sub(r"\1[secret]", text)
    return text.replace(passkey, "[secret]") if passkey else text


def feed_url(passkey: str, category: str = "", freeleech: bool = False) -> str:
    """The feed's address; the only place the passkey is put in a URL."""
    if not passkey:
        raise ValueError("Add the tr4ker passkey in Settings first.")
    params = {"passkey": passkey}
    if category:
        if not CATEGORY_SLUG.fullmatch(category):
            raise ValueError("Use a tr4ker category slug, such as films.")
        params["cat"] = category
    if freeleech:
        params["freeleech"] = "1"
    return tracker(TR4KER).origin + FEED_PATH + "?" + urlencode(params)


def clean_url(value: str | None) -> str:
    """A tr4ker URL without its credentials; anything not on tr4ker's origin is dropped."""
    if not value:
        return ""
    parts = urlsplit(value.strip())
    if f"{parts.scheme}://{parts.netloc}" != tracker(TR4KER).origin:
        return ""
    query = [(k, v) for k, v in parse_qsl(parts.query) if k.lower() not in {"passkey", "apikey"}]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def _number(value: str | None) -> int:
    return int(value) if value and value.isdigit() else 0


def _slug(url: str) -> str:
    path = urlsplit(url).path
    return path.rsplit("/", 1)[-1] if path.startswith("/torrent/") else ""


def parse_feed(xml: str) -> list[Candidate]:
    """The items of one feed as Candidates, once per guid. Rows are keyed `tr4ker:<guid>`
    (the feed has no info hash) and keep the torrent's size, peers and volume factor."""
    root = ET.fromstring(xml)
    rows: dict[str, Candidate] = {}
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        guid = (item.findtext("guid") or "").strip()
        if not title or not guid:
            continue
        key = KEY_PREFIX + guid[:200]
        attrs = {
            a.get("name"): a.get("value")
            for a in item.findall(f"{TORZNAB_NS}attr")
            if a.get("name")
        }
        enclosure = item.find("enclosure")
        link = clean_url(item.findtext("link"))
        size = _number(item.findtext(f"{RSS_NS}size")) or _number(attrs.get("size"))
        if not size and enclosure is not None:
            size = _number(enclosure.get("length"))
        seeders = _number(item.findtext(f"{RSS_NS}seeders")) or _number(attrs.get("seeders"))
        factor = attrs.get("downloadvolumefactor")
        freeleech = (item.findtext(f"{RSS_NS}freeleech") or "").strip().lower() in {"1", "true"}
        rows.setdefault(
            key,
            Candidate(
                title,
                size,
                clean_url(enclosure.get("url") if enclosure is not None else ""),
                seeders,
                key,
                link,
                (),
                publication_time(item.findtext("pubDate")),
                {
                    "tracker": TR4KER,
                    "guid": guid[:200],
                    "slug": _slug(link),
                    "leechers": _number(item.findtext(f"{RSS_NS}leechers")),
                    "freeleech": freeleech or factor == "0",
                    "downloadvolumefactor": factor,
                    "feed_category": (item.findtext("category") or "").strip()[:80],
                    "source": "rss",
                },
            ),
        )
    return list(rows.values())


def fetch_feed(
    http: httpx.Client, passkey: str, category: str = "", freeleech: bool = False
) -> list[Candidate]:
    """One poll of the feed. A refusal, an HTTP error or a bad body is raised without the
    passkey in its text; nothing is retried."""
    try:
        response = http.get(feed_url(passkey, category, freeleech))
    except httpx.HTTPError as error:
        raise FeedRefused(
            redact_passkey(f"tr4ker's feed is unreachable ({type(error).__name__})", passkey)
        ) from None
    if response.status_code in (401, 403):
        raise FeedRefused(
            f"tr4ker refused the passkey (HTTP {response.status_code}): check it in Settings"
        )
    if response.status_code == 429:
        raise FeedRefused("tr4ker's feed asked to wait (HTTP 429): the next poll tries again")
    if response.status_code != 200:
        raise FeedRefused(f"tr4ker's feed answered HTTP {response.status_code}")
    try:
        return parse_feed(response.text)
    except ET.ParseError:
        raise FeedRefused("tr4ker's feed was not valid RSS") from None
