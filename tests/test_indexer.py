import httpx
import pytest

from tests.torznab_fixtures import CAPS_XML, SEARCH_XML
from torrentlinker.indexer import Indexer, SearchQuery


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def make_indexer(handler, clock: FakeClock | None = None, **kw) -> Indexer:  # type: ignore[no-untyped-def]
    clock = clock or FakeClock()
    return Indexer(
        url="https://c411.example/api/torznab",
        api_key="K",
        http=httpx.Client(transport=httpx.MockTransport(handler)),
        clock=clock.time,
        sleep=clock.sleep,
        **kw,
    )


def test_search_returns_candidates_from_torznab_items() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, text=SEARCH_XML)

    candidates = make_indexer(handler).search(SearchQuery(q="Le joueur d'echecs Stefan Zweig"))

    assert seen[0].url.params["t"] == "search"
    assert seen[0].url.params["q"] == "Le joueur d'echecs Stefan Zweig"
    assert seen[0].url.params["apikey"] == "K"
    first = candidates[0]
    assert first.title == "Le.Joueur.D'echecs.Stefan.Zweig.2013.FR.[EPUB]-NOTAG"
    assert first.size == 67163
    assert first.seeders == 12
    assert first.download_url == "https://c411.example/api/download/42?apikey=K"
    assert first.infohash == "abcdef0123456789abcdef0123456789abcdef01"
    assert candidates[1].infohash is None


def test_requests_are_spaced_at_least_the_minimum_interval_apart() -> None:
    clock = FakeClock()
    sent_at: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent_at.append(clock.now)
        clock.now += 0.5  # the request itself takes half a second
        return httpx.Response(200, text=SEARCH_XML)

    indexer = make_indexer(handler, clock)
    indexer.search(SearchQuery(q="a"))
    indexer.search(SearchQuery(q="b"))
    indexer.search(SearchQuery(q="c"))

    gaps = [b - a for a, b in zip(sent_at, sent_at[1:], strict=False)]
    assert gaps == [pytest.approx(4.1), pytest.approx(4.1)]


def test_too_many_requests_is_retried_after_the_advertised_delay() -> None:
    clock = FakeClock()
    responses = [
        httpx.Response(429, headers={"Retry-After": "25"}),
        httpx.Response(200, text=SEARCH_XML),
    ]

    candidates = make_indexer(lambda r: responses.pop(0), clock).search(SearchQuery(q="a"))

    assert len(candidates) == 2
    assert 25 in clock.sleeps


def test_caps_lists_categories_and_supported_search_modes() -> None:
    caps = make_indexer(lambda r: httpx.Response(200, text=CAPS_XML)).caps()

    assert caps.categories[2030] == "Films étrangers"
    assert caps.categories[7000] == "Ebook"
    assert caps.modes["movie"] == {"q", "imdbid", "tmdbid"}
    assert "music" not in caps.modes


def test_bad_api_key_is_reported_as_an_error() -> None:
    with pytest.raises(httpx.HTTPStatusError):
        make_indexer(lambda r: httpx.Response(401)).caps()


def test_identical_searches_are_served_from_the_cache(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from torrentlinker.store import Store

    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, text=SEARCH_XML)

    store = Store(tmp_path / "state.db")
    make_indexer(handler, cache=store).search(SearchQuery(q="zweig"))
    again = make_indexer(handler, cache=store).search(SearchQuery(q="zweig"))

    assert len(calls) == 1
    assert again[0].size == 67163


def test_api_key_is_never_written_to_the_cache(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from torrentlinker.store import Store

    body = SEARCH_XML.replace("apikey=K", "apikey=S3CRET-KEY")
    store = Store(tmp_path / "state.db")

    def make() -> Indexer:
        return Indexer(
            url="https://c411.example/api/torznab",
            api_key="S3CRET-KEY",
            http=httpx.Client(
                transport=httpx.MockTransport(lambda r: httpx.Response(200, text=body))
            ),
            cache=store,
        )

    make().search(SearchQuery(q="zweig"))
    cached = make().search(SearchQuery(q="zweig"))

    assert b"S3CRET-KEY" not in (tmp_path / "state.db").read_bytes()
    assert cached[0].download_url.endswith("apikey=S3CRET-KEY")


def test_torrent_file_is_downloaded_once_then_served_from_disk(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from torrentlinker.indexer import Candidate
    from torrentlinker.store import Store

    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, content=b"d8:announce0:e")

    store = Store(tmp_path / "state.db")
    candidate = Candidate("t", 1, "https://c411.example/api/download/42?apikey=K")
    first = make_indexer(handler, cache=store).fetch_torrent(candidate)
    second = make_indexer(handler, cache=store).fetch_torrent(candidate)

    assert first == second == b"d8:announce0:e"
    assert len(calls) == 1


def test_indexer_tells_how_long_until_its_next_request_is_allowed() -> None:
    clock = FakeClock()
    indexer = make_indexer(lambda r: httpx.Response(200, text=SEARCH_XML), clock)
    assert indexer.next_request_in() == 0

    indexer.search(SearchQuery(q="a"))
    clock.now += 1.0

    assert indexer.next_request_in() == pytest.approx(3.1)
