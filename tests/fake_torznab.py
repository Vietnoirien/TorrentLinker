"""A Torznab Indexer over an in-memory list of torrents, newest first."""

from __future__ import annotations

from dataclasses import dataclass, field
from xml.sax.saxutils import escape

import httpx


@dataclass
class FakeTorrent:
    infohash: str
    title: str
    size: int
    seeders: int
    category: int


@dataclass
class FakeTorznab:
    by_category: dict[int, list[FakeTorrent]] = field(default_factory=dict)
    requests: list[httpx.Request] = field(default_factory=list)
    subcats: dict[int, int] = field(default_factory=dict)  # subcategory -> category
    # c411 serves at most this many results per query: deeper offsets get the last page
    window: int | None = None

    def add(self, category: int, count: int, start: int = 0, size: int = 4_000_000_000) -> None:
        """Add `count` torrents, newer than those already there."""
        new = [
            FakeTorrent(
                f"{category:04d}{start + i:036x}", f"T{category}-{start + i}", size, 50, category
            )
            for i in range(count)
        ]
        self.by_category[category] = list(reversed(new)) + self.by_category.get(category, [])

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        p = request.url.params
        cats = {int(c) for c in p.get("cat", "").split(",") if c}
        items = [
            t
            for c, ts in self.by_category.items()
            if c in cats or self.subcats.get(c) in cats
            for t in ts
        ]
        offset, limit = int(p.get("offset", "0")), int(p.get("limit", "25"))
        if self.window is not None:
            items = items[: self.window]
            offset = min(offset, max(0, len(items) - limit))
        return httpx.Response(200, text=_feed(items[offset : offset + limit]))

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))


def _feed(items: list[FakeTorrent]) -> str:
    body = "".join(
        f"""<item><title>{escape(t.title)}</title><link>https://c411.example/t/{t.infohash}</link>
<size>{t.size}</size><enclosure url="https://c411.example/dl/{t.infohash}?apikey=K"/>
<torznab:attr name="seeders" value="{t.seeders}"/>
<torznab:attr name="infohash" value="{t.infohash}"/>
<torznab:attr name="category" value="{t.category}"/></item>"""
        for t in items
    )
    return (
        '<?xml version="1.0"?><rss xmlns:torznab="http://torznab.com/schemas/2015/feed">'
        f"<channel>{body}</channel></rss>"
    )
