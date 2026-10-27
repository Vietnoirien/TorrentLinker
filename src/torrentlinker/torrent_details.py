"""Read-only torrent previews and anonymous, bounded image loading."""

from __future__ import annotations

import html
import ipaddress
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlsplit

from torrentlinker import net
from torrentlinker.bbcode import bbcode_to_html
from torrentlinker.indexer import Candidate, Indexer

MAX_IMAGE_BYTES = 32 * 1024 * 1024
MAX_IMAGES = 12


def web_url(value: str) -> str:
    """Only browser links, never local files, application URLs or embedded credentials."""
    try:
        parts = urlsplit(value.strip())
        if (
            parts.scheme in {"https", "http"}
            and parts.hostname
            and not parts.username
            and not parts.password
            and not any(ch.isspace() or ord(ch) < 32 for ch in value)
        ):
            return value.strip()
    except ValueError:
        pass
    return ""


def website_url(candidate: Candidate, indexer: Indexer) -> str:
    h = candidate.infohash or ""
    if indexer.is_c411 and re.fullmatch(r"[0-9a-fA-F]{40}", h):
        return f"https://c411.org/torrents/{h.lower()}"
    return web_url(candidate.details_url)


class _PreviewHTML(HTMLParser):
    """Keep formatting, public links and explicit image placeholders only."""

    tags = {
        "p",
        "div",
        "span",
        "b",
        "strong",
        "i",
        "em",
        "u",
        "s",
        "br",
        "hr",
        "h1",
        "h2",
        "h3",
        "h4",
        "pre",
        "code",
        "blockquote",
        "ul",
        "ol",
        "li",
        "table",
        "thead",
        "tbody",
        "tr",
        "td",
        "th",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.output: list[str] = []
        self.images: list[str] = []
        self._hidden = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "iframe", "object"}:
            self._hidden += 1
            return
        if self._hidden:
            return
        attributes = dict(attrs)
        if tag == "img":
            url = web_url(attributes.get("src") or "")
            if url and len(self.images) < MAX_IMAGES:
                if url not in self.images:
                    self.images.append(url)
                index = self.images.index(url)
                width = attributes.get("width") or ""
                if not width:
                    match = re.search(r"(?:^|;)\s*width:\s*(\d+)px", attributes.get("style") or "")
                    width = match[1] if match else ""
                width = str(min(600, max(1, int(width)))) if width.isdecimal() else "300"
                self.output.append(f'<img src="preview-image:{index}" width="{width}">')
        elif tag == "a":
            url = web_url(attributes.get("href") or "")
            self.output.append(f'<a href="{html.escape(url, quote=True)}">' if url else "<a>")
        elif tag in self.tags:
            align = attributes.get("align")
            match = re.search(
                r"(?:^|;)\s*text-align:\s*(center|left|right)\b",
                attributes.get("style") or "",
                re.I,
            )
            if match:
                align = match[1].lower()
            alignment = f' align="{align}"' if align in {"center", "left", "right"} else ""
            styles = []
            for part in (attributes.get("style") or "").split(";"):
                key, _, value = part.strip().partition(":")
                value = value.strip()
                if key == "color" and re.fullmatch(
                    r"#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?|[a-zA-Z]{1,20}", value
                ):
                    styles.append(f"color:{value}")
                if key == "font-size" and re.fullmatch(r"\d{1,2}px", value):
                    styles.append(f"font-size:{min(36, max(8, int(value[:-2])))}px")
            style = f' style="{";".join(styles)}"' if styles else ""
            self.output.append(f"<{tag}{alignment}{style}>")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "iframe", "object"}:
            self._hidden = max(0, self._hidden - 1)
            return
        if self._hidden:
            return
        if tag in self.tags or tag == "a":
            self.output.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if not self._hidden:
            self.output.append(html.escape(data))


def preview_html(description: str, poster: str = "") -> tuple[str, tuple[str, ...]]:
    parser = _PreviewHTML()
    # c411 returns HTML for both "standard" and "html" descriptions.
    # Older/plain BBCode descriptions still get a readable preview.
    markup = (
        description if re.search(r"</?[a-zA-Z][^>]*>", description) else bbcode_to_html(description)
    )
    if web_url(poster) and poster not in description:
        markup = f'<p><img src="{html.escape(poster, quote=True)}"></p>' + markup
    parser.feed(markup)
    return '<div align="center">' + "".join(parser.output) + "</div>", tuple(parser.images)


@dataclass(frozen=True)
class Trust:
    """c411's community trust votes, read-only: voting needs a website session."""

    status: str = ""
    tested: bool = False
    positive: int = 0
    negative: int = 0
    required: int = 0


@dataclass(frozen=True)
class Media:
    """The TMDB card c411 shows under the facts."""

    title: str = ""
    original_title: str = ""
    year: int | None = None
    kind: str = ""  # TMDB's "movie" or "tv"
    genres: tuple[str, ...] = ()
    rating: float | None = None
    votes: int = 0
    runtime: int | None = None
    directors: tuple[str, ...] = ()
    cast: tuple[str, ...] = ()
    tmdb_id: str = ""
    imdb_id: str = ""


@dataclass(frozen=True)
class TorrentDetails:
    description: str
    nfo: str
    has_nfo: bool
    poster: str = ""
    files: tuple[tuple[str, int], ...] = ()
    uploader: str = ""
    team: str = ""
    created_at: float | None = None
    exclusive: bool = False
    low_bitrate: bool = False
    seeders: int | None = None
    leechers: int | None = None
    completions: int | None = None
    category: str = ""
    subcategory: str = ""
    facts: tuple[
        tuple[str, tuple[str, ...]], ...
    ] = ()  # ("Language", ("Multi (Français inclus)",))
    trust: Trust = Trust()
    media: Media | None = None


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _count(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _names(values: Any, key: str = "") -> tuple[str, ...]:
    out = []
    for value in values if isinstance(values, list) else []:
        text = _text(value.get(key) if isinstance(value, dict) else value)
        if text:
            out.append(text)
    return tuple(out)


def _media(data: Any, ids: Any) -> Media | None:
    if not isinstance(data, dict) or not data:
        return None
    imdb = _text(data.get("imdbId"))
    tmdb = str(data.get("id") or "")
    for entry in ids if isinstance(ids, list) else []:
        kind, value = _text(entry.get("kind")), _text(entry.get("value"))
        if kind.startswith("imdb") and not imdb:
            imdb = value
        if kind.startswith("tmdb") and not tmdb:
            tmdb = value
    year, rating = data.get("year"), data.get("rating")
    runtime = data.get("runtime")
    return Media(
        _text(data.get("title")),
        _text(data.get("originalTitle")),
        year if isinstance(year, int) and 1800 <= year <= 2200 else None,
        _text(data.get("type")),
        _names(data.get("genres")),
        float(rating) if isinstance(rating, int | float) and 0 < rating <= 10 else None,
        _count(data.get("ratingCount")) or 0,
        runtime if isinstance(runtime, int) and runtime > 0 else None,
        _names(data.get("directors")),
        _names(data.get("cast"), "name")[:4],
        tmdb if tmdb.isdigit() else "",
        imdb if re.fullmatch(r"tt\d{4,10}", imdb) else "",
    )


def parse_details(payload: dict[str, Any]) -> TorrentDetails:
    item = payload  # The detail endpoint is flat, unlike the listing endpoint.
    metadata = item.get("metadata") or {}
    trust: dict[str, Any] = item["trust"] if isinstance(item.get("trust"), dict) else {}
    team: dict[str, Any] = item["team"] if isinstance(item.get("team"), dict) else {}
    category: dict[str, Any] = (
        metadata["category"] if isinstance(metadata.get("category"), dict) else {}
    )
    sub: dict[str, Any] = (
        metadata["subcategory"] if isinstance(metadata.get("subcategory"), dict) else {}
    )
    from torrentlinker.indexer import publication_time

    facts = []
    groups = metadata.get("options")
    for group in groups if isinstance(groups, list) else []:
        if isinstance(group, dict) and _text(group.get("name")):
            values = _names(group.get("values"), "value")
            if values:
                facts.append((_text(group["name"]), values))
    return TorrentDetails(
        str(item.get("description") or ""),
        str(metadata.get("nfoContent") or ""),
        bool(metadata.get("hasNfo")),
        web_url(str((metadata.get("tmdbData") or {}).get("posterUrl") or "")),
        tuple(
            ("/".join(str(part) for part in file["path"]), int(file["length"]))
            for file in item.get("files", [])
            if isinstance(file.get("path"), list)
        ),
        _text(item.get("uploader")),
        _text(team.get("name")),
        publication_time(item.get("createdAt")),
        metadata.get("isExclusive") is True,
        metadata.get("lowBitrateWarning") is True,
        _count(item.get("seeders")),
        _count(item.get("leechers")),
        _count(item.get("completions")),
        _text(category.get("name")),
        _text(sub.get("name")),
        tuple(facts),
        Trust(
            _text(trust.get("status")),
            trust.get("isTested") is True,
            _count(trust.get("positiveCount")) or 0,
            _count(trust.get("negativeCount")) or 0,
            _count(trust.get("minVotesRequired")) or 0,
        ),
        _media(metadata.get("tmdbData"), item.get("externalIds")),
    )


def _image_url(url: str) -> str:
    value = web_url(url)
    if not value:
        raise ValueError("Invalid image URL")
    host = (urlsplit(value).hostname or "").lower()
    if host == "localhost" or host.endswith((".localhost", ".local")) or "." not in host:
        raise ValueError("Local image URLs are not supported")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        if not address.is_global:
            raise ValueError("Local image URLs are not supported")
    return value


def fetch_image(url: str) -> bytes:
    # A separate client intentionally carries no Indexer keys, cookies or referer.
    with net.client(timeout=15, follow_redirects=False) as http:
        for _ in range(4):
            with http.stream("GET", _image_url(url)) as response:
                if response.is_redirect:
                    url = str(response.url.join(response.headers["location"]))
                    continue
                response.raise_for_status()
                if not response.headers.get("content-type", "").split(";")[0].startswith("image/"):
                    raise ValueError("Not an image")
                data = bytearray()
                for chunk in response.iter_bytes():
                    data.extend(chunk)
                    if len(data) > MAX_IMAGE_BYTES:
                        raise ValueError("Image exceeds 32 MiB")
                return bytes(data)
    raise ValueError("Too many image redirects")
