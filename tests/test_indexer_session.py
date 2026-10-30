import httpx
import pytest

from torrentlinker.companion_downloads import SessionFetchError
from torrentlinker.indexer import (
    Candidate,
    Indexer,
    RateLimited,
    SessionRefused,
    TorrentUnavailable,
)

HASH = "a" * 40


class Session:
    def __init__(self, enabled=True, result=b"torrent"):
        self.session_downloads = enabled
        self.result = result
        self.asked = []

    def fetch_descriptor(self, infohash):
        self.asked.append(infohash)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def indexer(session, api_calls):
    def handler(request):
        api_calls.append(str(request.url))
        return httpx.Response(200, content=b"from-api")

    ix = Indexer(
        "https://c411.org/api",
        "key",
        http=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _: None,
    )
    ix.session = session
    return ix


def candidate(infohash=HASH):
    return Candidate("x", 1, f"https://c411.org/api?t=get&id={HASH}&apikey=key", infohash=infohash)


def test_enabled_session_replaces_the_api_download():
    calls, session = [], Session()
    assert indexer(session, calls).fetch_torrent(candidate()) == b"torrent"
    assert session.asked == [HASH] and calls == []


def test_infohash_is_read_from_the_download_url_when_the_result_lacks_it():
    calls, session = [], Session()
    indexer(session, calls).fetch_torrent(candidate(None))
    assert session.asked == [HASH]


def test_disabled_session_keeps_the_api_path():
    calls, session = [], Session(enabled=False)
    assert indexer(session, calls).fetch_torrent(candidate()) == b"from-api"
    assert session.asked == [] and len(calls) == 1


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (SessionFetchError("gone", 404, fatal=False), TorrentUnavailable),
        (SessionFetchError("wait", 429, 90), RateLimited),
        (SessionFetchError("refused", 403), SessionRefused),
        (SessionFetchError("Connect the companion."), SessionRefused),
        (SessionFetchError("slow", 0, fatal=False), RuntimeError),
    ],
)
def test_session_failures_never_fall_back_to_the_api_key(error, expected):
    calls = []
    with pytest.raises(expected):
        indexer(Session(result=error), calls).fetch_torrent(candidate())
    assert calls == []


def test_rate_limit_carries_the_wait_c411_asked_for():
    with pytest.raises(RateLimited) as info:
        indexer(Session(result=SessionFetchError("wait", 429, 120)), []).fetch_torrent(candidate())
    assert info.value.retry_after == 120


def test_prefetch_asks_for_a_batch_at_once_and_fetch_takes_each_result():
    import threading

    gate = threading.Barrier(3, timeout=5)
    asked = []

    class Slow(Session):
        def fetch_descriptor(self, infohash):
            asked.append(infohash)
            gate.wait()  # only passes when three requests are in flight together
            return infohash.encode()

    calls, session = [], Slow()
    ix = indexer(session, calls)
    hashes = [c * 40 for c in "abc"]
    batch = [
        Candidate("x", 1, f"https://c411.org/api?t=get&id={h}&apikey=key", infohash=h)
        for h in hashes
    ]
    ix.prefetch(batch)
    assert [ix.fetch_torrent(c) for c in batch] == [h.encode() for h in hashes]
    assert sorted(asked) == sorted(hashes) and calls == []
    ix.drop_prefetch()


def test_prefetch_does_nothing_when_session_downloads_are_off():
    calls, session = [], Session(enabled=False)
    ix = indexer(session, calls)
    ix.prefetch([candidate()])
    assert session.asked == [] and ix._ahead == {}
