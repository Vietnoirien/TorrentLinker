"""Reseed keeps each Tracker's discovery, credentials and torrent separate."""

from pathlib import Path

import httpx
import pytest
import torf

from tests.test_tr4ker_torznab import KEY, feed, item
from torrentlinker.indexer import Candidate, SearchQuery
from torrentlinker.reseed_sources import Sources
from torrentlinker.review import remember_candidates, remembered_candidates
from torrentlinker.store import Store
from torrentlinker.torznab import TorznabIndexer


class C411:
    is_c411 = True

    def redact(self, text):
        return text.replace("C411-KEY", "[secret]")

    def unredact(self, text):
        return text.replace("[secret]", "C411-KEY")


def torrent(path: Path, announce: str) -> bytes:
    made = torf.Torrent(path=path, trackers=[announce], private=True, source="tr4ker")
    made.generate()
    return bytes(made.dump())


def test_tr4ker_discovery_uses_full_feed_and_remembered_candidate_uses_its_own_key(tmp_path):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, text=feed(item(seeders=0)))

    tr4ker = TorznabIndexer(
        "https://tr4ker.net/api",
        KEY,
        "tr4ker",
        http=httpx.Client(transport=httpx.MockTransport(handler)),
        tracker="tr4ker",
    )
    sources = Sources(C411(), lambda: {"tr4ker": tr4ker})
    found = sources.search_others(
        lambda feed_indexer, _: feed_indexer.search(SearchQuery(q="Film"))
    )
    assert len(found) == 1 and found[0].tracker == "tr4ker" and found[0].seeders == 0
    assert seen[0].url.path == "/api/torznab/all"
    assert seen[0].url.params["apikey"] == KEY

    store = Store(tmp_path / "state.db")
    path = tmp_path / "Film.mkv"
    remember_candidates(store, sources, path, found)
    saved = store.remembered_candidates(path)
    assert saved is not None and KEY not in saved and "[secret]" in saved
    assert remembered_candidates(store, sources, path) == found


def test_tr4ker_download_is_cached_privately_and_never_routed_to_c411(tmp_path):
    content = tmp_path / "Film.mkv"
    content.write_bytes(b"film" * 100)
    data = torrent(content, "https://tk.tr4ker.net/announce/passkey")
    store = Store(tmp_path / "state.db")
    store.torrent_dir.mkdir(mode=0o755)
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, content=data)

    tr4ker = TorznabIndexer(
        "https://tr4ker.net/api",
        KEY,
        "tr4ker",
        http=httpx.Client(transport=httpx.MockTransport(handler)),
        tracker="tr4ker",
        cache=store,
    )
    sources = Sources(C411(), lambda: {"tr4ker": tr4ker})
    candidate = Candidate(
        "Film",
        len(data),
        f"https://tr4ker.net/api/torrents/film/download?apikey={KEY}",
        tracker="tr4ker",
    )
    assert sources.fetch_torrent(candidate) == data
    assert sources.fetch_torrent(candidate) == data
    assert len(calls) == 1
    assert calls[0].url.params["apikey"] == KEY
    assert store.torrent_dir.stat().st_mode & 0o777 == 0o700
    assert next(store.torrent_dir.glob("*.torrent")).stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError, match="not configured"):
        sources.fetch_torrent(Candidate("Other", 1, "https://other.invalid/dl", tracker="other"))


def test_reseed_rejects_a_torrent_announcing_to_another_tracker(tmp_path):
    content = tmp_path / "Film.mkv"
    content.write_bytes(b"film" * 100)
    data = torrent(content, "https://c411.org/announce/passkey")
    store = Store(tmp_path / "state.db")
    tr4ker = TorznabIndexer(
        "https://tr4ker.net/api",
        KEY,
        "tr4ker",
        http=httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, content=data))
        ),
        tracker="tr4ker",
        cache=store,
    )
    candidate = Candidate(
        "Film", len(data), "https://tr4ker.net/api/torrents/film/download", tracker="tr4ker"
    )
    with pytest.raises(ValueError, match="does not announce to tr4ker"):
        Sources(C411(), lambda: {"tr4ker": tr4ker}).fetch_torrent(candidate)
