"""tr4ker through Torznab: modes, pacing, refusals, Cross-seed both ways (ADR-0025).

Fixtures are synthetic (the caps file is a sanitized capture); nothing reaches a real tracker.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from tests.test_crossseed import EPISODES, Fixture
from tests.test_torznab_indexers import Clock
from torrentlinker.config import IndexerSettings
from torrentlinker.indexer import RateLimited, SearchMode, SearchQuery, parse_caps
from torrentlinker.reseed import VERIFYING
from torrentlinker.torznab import (
    IndexerBanned,
    IndexerKeyRefused,
    IndexerMaintenance,
    TorznabIndexer,
    parse_page,
)

CAPS = (Path(__file__).parent / "fixtures" / "tr4ker_caps.xml").read_text()
KEY = "SECRETKEY123"
ITEM = """<item><title>{title}</title><guid>https://tr4ker.net/torrents/{n}</guid>
<link>https://tr4ker.net/torrents/{n}</link><comments>https://tr4ker.net/torrents/{n}</comments>
<pubDate>Mon, 23 Nov 2026 10:00:00 +0000</pubDate><size>{size}</size>
<enclosure url="https://tr4ker.net/api/torrents/slug-{n}/download?apikey={key}" length="{size}"
 type="application/x-bittorrent"/>
<torznab:attr name="category" value="{cat}"/><torznab:attr name="size" value="{size}"/>
<torznab:attr name="seeders" value="{seeders}"/><torznab:attr name="leechers" value="1"/>
<torznab:attr name="infohash" value="{hash}"/>
<torznab:attr name="downloadvolumefactor" value="0"/>
<torznab:attr name="uploadvolumefactor" value="1"/>
<torznab:attr name="tmdbid" value="603"/></item>"""


def feed(*items: str, offset: int | None = 0, total: int | None = None) -> str:
    paging = f'<newznab:response offset="{offset}" total="{total}"/>' if total is not None else ""
    return (
        '<rss xmlns:torznab="http://torznab.com/schemas/2015/feed" '
        'xmlns:newznab="http://www.newznab.com/DTD/2010/feeds/attributes/"><channel>'
        f"{paging}{''.join(items)}</channel></rss>"
    )


def item(n=1, title="Film.2020.1080p", size=1000, cat=2040, seeders=0, hash_=None):
    return ITEM.format(
        n=n,
        title=title,
        size=size,
        cat=cat,
        seeders=seeders,
        key=KEY,
        hash_=hash_,
        hash=hash_ or f"{n:040x}",
    )


def tr4ker(handler, clock=None) -> TorznabIndexer:
    clock = clock or Clock()
    return TorznabIndexer(
        "https://tr4ker.net/api",
        KEY,
        "tr4ker",
        http=httpx.Client(transport=httpx.MockTransport(handler)),
        clock=clock.time,
        sleep=clock.sleep,
        tracker="tr4ker",
    )


def test_magnet_only_download_requires_torrent_metainfo_without_exposing_link():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/download"):
            return httpx.Response(302, headers={"Location": "magnet://?xt=urn:btih:secret"})
        return httpx.Response(200, text=feed(item()))

    found = tr4ker(handler)
    found._http = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    candidate = found.search(SearchQuery(q="Film.2020"))[0]
    with pytest.raises(ValueError, match="provided only a magnet link") as error:
        found.fetch_torrent(candidate)
    assert "secret" not in str(error.value)
    assert KEY not in str(error.value)


def test_caps_advertise_five_modes_and_each_one_is_searched_with_its_own_parameters():
    caps = parse_caps(CAPS)
    assert set(caps.modes) == {
        SearchMode.SEARCH,
        SearchMode.TV,
        SearchMode.MOVIE,
        SearchMode.MUSIC,
        SearchMode.BOOK,
    }
    assert caps.modes[SearchMode.MOVIE] == {
        "q",
        "imdbid",
        "tmdbid",
        "cat",
        "limit",
        "offset",
        "apikey",
    }
    seen: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.url.params))
        return httpx.Response(200, text=feed(item(len(seen))))

    found = tr4ker(handler)
    queries = {
        SearchMode.SEARCH: SearchQuery(q="matrix", categories=(2000,), limit=100, offset=100),
        SearchMode.MOVIE: SearchQuery(q="matrix", mode=SearchMode.MOVIE, tmdbid="603"),
        SearchMode.TV: SearchQuery(q="show", mode=SearchMode.TV, season=2, ep=3, imdbid="tt1"),
        SearchMode.MUSIC: SearchQuery(q="album", mode=SearchMode.MUSIC),
        SearchMode.BOOK: SearchQuery(q="livre", mode=SearchMode.BOOK),
    }
    for mode, query in queries.items():
        before = len(seen)
        results = found.search(query)
        assert len(seen) == before + 1 and results, mode
        sent = seen[-1]
        assert sent["t"] == mode.value and sent["apikey"] == KEY
        assert set(sent) - {"t"} <= caps.modes[mode], (mode, set(sent))  # only advertised params
    assert seen[0]["offset"] == "100" and seen[0]["limit"] == "100"
    result = found.search(queries[SearchMode.MOVIE])[0]
    assert result.metadata["tmdbid"] == "603" and result.infohash == f"{len(seen):040x}"
    assert result.seeders == 0  # a torrent without seeders is still a result


def test_a_429_waits_retry_after_else_tr4kers_sixty_seconds_and_cancellation_interrupts():
    clock, calls = Clock(), []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429)  # no Retry-After
        return httpx.Response(200, text=feed(item()))

    found = tr4ker(handler, clock)
    with found.background():
        assert found.search(SearchQuery(q="x"))
    assert sum(clock.sleeps) >= 60

    import threading

    stop = threading.Event()
    stop.set()
    slow = tr4ker(lambda r: httpx.Response(429, headers={"Retry-After": "30"}), Clock())
    with slow.background(stop), pytest.raises((InterruptedError, RateLimited)):
        slow.search(SearchQuery(q="x"))


def test_expired_banned_and_maintenance_are_told_apart_and_a_plain_503_is_transient():
    clock = Clock()
    with pytest.raises(IndexerKeyRefused) as expired:
        tr4ker(lambda r: httpx.Response(401), clock).search(SearchQuery(q="x"))
    assert not isinstance(expired.value, IndexerBanned) and "401" in str(expired.value)
    with pytest.raises(IndexerBanned) as banned:
        tr4ker(lambda r: httpx.Response(403), clock).search(SearchQuery(q="x"))
    assert "banned" in str(banned.value) and KEY not in str(banned.value)
    with pytest.raises(IndexerMaintenance) as maintenance:
        tr4ker(lambda r: httpx.Response(503, json={"error": "Maintenance en cours"}), clock).search(
            SearchQuery(q="x")
        )
    assert isinstance(maintenance.value, RateLimited) and maintenance.value.retry_after > 0
    with pytest.raises(httpx.HTTPStatusError) as transient:
        tr4ker(lambda r: httpx.Response(503, text="Bad gateway"), clock).search(SearchQuery(q="x"))
    assert KEY not in str(transient.value)
    # Other Indexers keep their behaviour: a 403 is a refused key there.
    other = TorznabIndexer(
        "https://o.example/api",
        KEY,
        "Other",
        http=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(403))),
    )
    with pytest.raises(IndexerKeyRefused) as plain:
        other.search(SearchQuery(q="x"))
    assert not isinstance(plain.value, IndexerBanned)


def test_the_api_key_never_reaches_logs_or_errors(caplog):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text=f"boom {request.url}")

    found = tr4ker(handler)
    logging.getLogger("httpx").setLevel(logging.WARNING)  # as the app does at start
    with caplog.at_level(logging.DEBUG), pytest.raises(httpx.HTTPStatusError) as error:
        found.search(SearchQuery(q="x"))
    assert KEY not in str(error.value) and KEY not in caplog.text
    assert (
        found.redact(f"https://tr4ker.net/x?apikey={KEY}") == "https://tr4ker.net/x?apikey=[secret]"
    )


def test_pagination_is_read_once_whichever_namespaces_carry_it():
    both = (
        '<rss xmlns:torznab="http://torznab.com/schemas/2015/feed" '
        'xmlns:newznab="http://www.newznab.com/DTD/2010/feeds/attributes/"><channel>'
        '<newznab:response offset="200" total="1234"/><torznab:response offset="200" total="1234"/>'
        f"{item()}</channel></rss>"
    )
    page = parse_page(both)
    assert (page.offset, page.total, len(page.items)) == (200, 1234, 1)  # 1234, never 2468
    assert parse_page(feed(item(), offset=None)).total is None


def test_the_discovery_view_reads_the_full_feed_with_the_same_key_and_pacer():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, text=feed(item()))

    found = tr4ker(handler)
    found.search(SearchQuery(q="x"))
    wide = found.discovery()
    wide.search(SearchQuery(q="x"))
    assert [r.url.path for r in seen] == ["/api", "/api/torznab/all"]
    assert all(r.url.params["apikey"] == KEY for r in seen)
    assert wide.pacer is found.pacer
    assert tr4ker(handler).discovery().discovery() is not None
    plain = TorznabIndexer("https://o.example/api", "K", "O")
    assert plain.discovery() is plain  # another Indexer has no wider feed


# -- Cross-seed ----------------------------------------------------------------------------

C411_ANNOUNCE = "https://tracker.c411.org/announce/p"
TR4KER_ANNOUNCE = "https://tr4ker.net/announce/p"


def as_tracker(f: Fixture, ident: str, url: str, name: str, source_announce: str) -> None:
    """Make the fixture's one Indexer `ident` at `url`; the original announces to `source`."""
    f.setup.settings.indexers[-1] = IndexerSettings(url, ident, name, True)
    f.setup.secrets.update({f"indexer-key-{ident}": "KEY"})
    held = f.setup._torznab.pop("other")
    f.indexer.url = url
    f.indexer.tracker = ident if ident == "tr4ker" else ""
    if ident == "tr4ker":
        f.indexer.discovery_url = "https://tr4ker.net/api/torznab/all"
    f.setup._torznab[ident] = ((url, "KEY"), held[1])
    for h, t in list(f.qbit.by_hash.items()):
        f.qbit.by_hash[h] = replace(t, tracker=source_announce, trackers=(source_announce,))


def run(f: Fixture, ident: str) -> None:
    f.engine.enqueue()
    while f.engine.search_next(ident, f.stop):
        pass


def test_a_c411_torrent_is_cross_seeded_onto_tr4ker_added_stopped_verified_started(
    tmp_path, monkeypatch
):
    f = Fixture(tmp_path, monkeypatch, EPISODES)
    as_tracker(f, "tr4ker", "https://tr4ker.net/api", "tr4ker", C411_ANNOUNCE)
    new = f.offer()
    paths: list[str] = []
    real = f.fake.handler
    f.fake.handler = lambda r: (paths.append(r.url.path), real(r))[1]  # type: ignore[method-assign]
    f.indexer._http = httpx.Client(transport=httpx.MockTransport(f.fake.handler))

    run(f, "tr4ker")

    added = f.qbit.by_hash[new]
    assert {"cross-seed", "tr4ker", VERIFYING} <= added.tags
    assert added.state != "uploading"  # stopped until verified
    assert "/api/torznab/all" in paths  # discovery reads tr4ker's full feed
    f.verified(new)
    assert f.qbit.started == [new] and VERIFYING not in f.qbit.by_hash[new].tags
    rows = f.rows("added")
    assert [r["tracker"] for r in rows] == ["tr4ker"]
    assert f.engine.activity()["rows"][0]["tracker"] == "tr4ker"


def test_a_tr4ker_torrent_is_cross_seeded_onto_c411_and_never_back_onto_tr4ker(
    tmp_path, monkeypatch
):
    f = Fixture(tmp_path, monkeypatch, EPISODES)
    as_tracker(f, "other", "https://c411.org/api/torznab", "c411 mirror", TR4KER_ANNOUNCE)
    new = f.offer()
    run(f, "other")
    assert {"cross-seed", VERIFYING} <= f.qbit.by_hash[new].tags
    assert [r["tracker"] for r in f.rows("verifying")] == ["c411"]

    # The reverse is skipped: a torrent announcing to c411 is not searched on c411 again,
    # and one announcing to tr4ker is not searched on tr4ker (one torrent per Tracker).
    g = Fixture(tmp_path / "again", monkeypatch, EPISODES)
    as_tracker(g, "other", "https://c411.org/api/torznab", "c411 mirror", C411_ANNOUNCE)
    assert g.engine.enqueue() == 0
    h = Fixture(tmp_path / "third", monkeypatch, EPISODES)
    as_tracker(h, "tr4ker", "https://tr4ker.net/api", "tr4ker", TR4KER_ANNOUNCE)
    assert h.engine.enqueue() == 0


def test_a_full_text_result_of_another_kind_is_not_an_exact_match(tmp_path, monkeypatch):
    """A query for a film may return an Audio torrent: only its files can make a Match."""
    f = Fixture(tmp_path, monkeypatch, EPISODES)
    as_tracker(f, "tr4ker", "https://tr4ker.net/api", "tr4ker", C411_ANNOUNCE)
    other = f.tmp / "audio" / "Album"
    other.mkdir(parents=True)
    (other / "track1.flac").write_bytes(b"x" * 400_000)
    from tests.test_crossseed import torrent_of

    f.fake.data = torrent_of(other, {}, "AUDIO")
    run(f, "tr4ker")
    assert f.rows("added") == [] and f.rows("review") == []
    assert [r["state"] for r in f.rows("searched")] == ["searched"]
