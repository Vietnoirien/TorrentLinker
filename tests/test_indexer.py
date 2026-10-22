from pathlib import Path

import httpx
import pytest

from tests.torznab_fixtures import CAPS_XML, SEARCH_XML
from torrentlinker.indexer import Candidate, Indexer, KeyRefused, RateLimited, SearchQuery


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


def test_searches_are_spaced_by_c411s_documented_rate() -> None:
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
    assert gaps == [pytest.approx(0.5), pytest.approx(0.5)]  # 120 a minute


def test_too_many_requests_is_retried_after_the_advertised_delay() -> None:
    clock = FakeClock()
    responses = [
        httpx.Response(429, headers={"Retry-After": "25"}),
        httpx.Response(200, text=SEARCH_XML),
    ]

    candidates = make_indexer(lambda r: responses.pop(0), clock).search(SearchQuery(q="a"))

    assert len(candidates) == 2
    assert 25 in clock.sleeps


def test_a_torrent_download_can_hand_a_429_back_instead_of_sleeping() -> None:
    clock = FakeClock()
    indexer = make_indexer(lambda r: httpx.Response(429, headers={"Retry-After": "900"}), clock)

    with pytest.raises(RateLimited) as limited:
        indexer.fetch_torrent(Candidate("t", 1, "https://c411.example/dl/1"), retry=False)

    assert limited.value.retry_after == 900
    assert 900 not in clock.sleeps


@pytest.mark.parametrize("status", [401, 403])
def test_a_refused_key_says_so_without_showing_the_key(status: int) -> None:
    indexer = make_indexer(lambda r: httpx.Response(status))

    with pytest.raises(KeyRefused) as refused:
        indexer.search(SearchQuery(q="a"))

    assert refused.value.status == status
    assert "apikey" not in str(refused.value)


def test_other_http_errors_never_show_the_key_from_the_url() -> None:
    indexer = make_indexer(lambda r: httpx.Response(500))

    with pytest.raises(httpx.HTTPStatusError) as failed:
        indexer.search(SearchQuery(q="a"))

    assert "apikey=K" not in str(failed.value)
    assert "500" in str(failed.value)


def test_caps_lists_categories_and_supported_search_modes() -> None:
    caps = make_indexer(lambda r: httpx.Response(200, text=CAPS_XML)).caps()

    assert caps.categories[2030] == "Films étrangers"
    assert caps.parents == {2030: 2000}
    assert caps.categories[7000] == "Ebook"
    assert caps.modes["movie"] == {"q", "imdbid", "tmdbid"}
    assert "music" not in caps.modes


def test_bad_api_key_is_reported_as_an_error() -> None:
    with pytest.raises(KeyRefused):
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
    clock.now += 0.2

    assert indexer.next_request_in() == pytest.approx(0.3)


def test_supported_modes_are_fetched_once_and_unknown_when_caps_fail() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, text=CAPS_XML)

    indexer = make_indexer(handler)
    assert indexer.supported_modes() == indexer.supported_modes()
    assert len(calls) == 1

    broken = make_indexer(lambda r: httpx.Response(500))
    assert broken.supported_modes() is None


def test_c411_caps_give_one_entry_per_category_id_in_c411s_own_tree() -> None:
    """c411 reuses Newznab ids across its categories: results only carry the id, so the
    tree has each id once, labelled with every c411 meaning it covers."""
    from pathlib import Path

    xml = (Path(__file__).parent / "fixtures" / "c411_caps.xml").read_text(encoding="utf-8")
    caps = make_indexer(lambda r: httpx.Response(200, text=xml)).caps()

    assert caps.categories[2000] == "Films & Vidéos / Série Documentaire"
    assert 2000 not in caps.parents
    assert (caps.categories[2030], caps.parents[2030]) == ("Film", 2000)
    assert (caps.categories[5000], caps.parents[5000]) == ("Série TV", 2000)
    assert caps.categories[8010] == "Imprimante 3D / Objets / Personnages / Pack"
    assert 8010 not in caps.parents
    assert caps.categories[1000] == "Jeux Vidéo / Emulation / VR"
    assert caps.categories[7020] == "Livres / Partitions & Tablatures / Revues & Manuels techniques"
    assert caps.parents[7020] == 7000
    assert all(child != parent for child, parent in caps.parents.items())
    assert all(parent not in caps.parents for parent in caps.parents.values())


# The two queues ------------------------------------------------------------------


def test_a_search_never_waits_behind_a_torrent_download() -> None:
    clock = FakeClock()
    sent: list[tuple[str, float]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append((request.url.path, clock.now))
        if "dl" in request.url.path:
            return httpx.Response(200, content=b"d8:announce0:e")
        return httpx.Response(200, text=SEARCH_XML)

    indexer = make_indexer(handler, clock)
    one, two = (Candidate(t, 1, f"https://c411.example/dl/{t}") for t in "ab")

    indexer.fetch_torrent(one)
    indexer.search(SearchQuery(q="a"))
    indexer.fetch_torrent(two)

    times = dict(sent)
    assert times["/api/torznab"] == pytest.approx(times["/dl/a"])  # no wait at all
    assert times["/dl/b"] - times["/dl/a"] == pytest.approx(4.1)  # downloads keep theirs


def test_a_low_budget_slows_searches_down_to_what_the_hour_sustains() -> None:
    from torrentlinker.ratelimit import BudgetQueue

    clock = FakeClock()
    queue = BudgetQueue(clock=clock.time, sleep=clock.sleep, wall=lambda: 5000.0)
    queue.observe({"x-ratelimit-remaining": "80", "x-ratelimit-reset": "5600"})

    queue.wait_turn()
    queue.wait_turn()

    assert clock.sleeps == [pytest.approx(3.0)]  # 3600 s / 1,200 requests


def test_an_empty_budget_waits_for_c411s_reset() -> None:
    from torrentlinker.ratelimit import BudgetQueue

    clock = FakeClock()
    queue = BudgetQueue(clock=clock.time, sleep=clock.sleep, wall=lambda: 5000.0)
    queue.wait_turn()
    queue.observe({"x-ratelimit-remaining": "0", "x-ratelimit-reset": "5120"})

    queue.wait_turn()

    assert clock.sleeps == [pytest.approx(120)]  # until c411 gives requests back


def test_without_headers_the_queue_counts_its_own_requests_over_the_hour() -> None:
    from torrentlinker.ratelimit import BudgetQueue

    clock = FakeClock()
    queue = BudgetQueue(budget=150, clock=clock.time, sleep=clock.sleep)
    start = clock.now

    for _ in range(151):
        queue.wait_turn()

    # 50 at the full rate, 100 at the sustained rate, then a wait for the first to expire.
    assert clock.now - start == pytest.approx(3600)
    assert queue.left() == 0  # the 151st replaced the first, gone from the hour


def test_c411s_reported_budget_wins_over_the_own_count() -> None:
    from torrentlinker.ratelimit import BudgetQueue

    queue = BudgetQueue(clock=lambda: 10.0, wall=lambda: 5000.0)
    queue.observe(
        {"x-ratelimit-limit": "1200", "x-ratelimit-remaining": "300", "x-ratelimit-reset": "5900"}
    )

    assert queue.left() == 300  # other apps used the key too


# Several keys ---------------------------------------------------------------------


def pool(handler, clock: FakeClock, keys: list[str]) -> Indexer:  # type: ignore[no-untyped-def]
    return Indexer(
        url="https://c411.example/api/torznab",
        api_key=keys[0],
        extra_keys=keys[1:],
        http=httpx.Client(transport=httpx.MockTransport(handler)),
        clock=clock.time,
        sleep=clock.sleep,
    )


def test_downloads_take_turns_between_keys_each_at_its_own_pace() -> None:
    clock = FakeClock()
    sent: list[tuple[str, float]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append((request.url.params["apikey"], clock.now))
        return httpx.Response(200, content=b"d8:announce0:e")

    indexer = pool(handler, clock, ["K1", "K2"])
    for i in range(4):
        url = f"https://c411.example/api?t=get&id={i}&apikey=K1"
        indexer.fetch_torrent(Candidate(str(i), 1, url))

    assert [k for k, _ in sent] == ["K1", "K2", "K1", "K2"]
    assert [t - sent[0][1] for _, t in sent] == pytest.approx([0, 0, 4.1, 4.1])


def test_a_key_c411_asks_to_wait_rests_while_another_carries_on() -> None:
    clock = FakeClock()
    used: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        used.append(request.url.params["apikey"])
        if request.url.params["apikey"] == "K1":
            return httpx.Response(429, headers={"Retry-After": "900"})
        return httpx.Response(200, text=SEARCH_XML)

    indexer = pool(handler, clock, ["K1", "K2"])

    assert indexer.search(SearchQuery(q="a"), cached=False)
    indexer.search(SearchQuery(q="b"), cached=False)

    assert used == ["K1", "K2", "K2"]  # K1 rests for its 900 s
    assert clock.sleeps == [pytest.approx(0.5)]  # K2's own pace, no wait for K1


def test_with_every_key_resting_a_download_hands_back_the_shortest_wait() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        wait = {"K1": "600", "K2": "120"}[request.url.params["apikey"]]
        return httpx.Response(429, headers={"Retry-After": wait})

    indexer = pool(handler, FakeClock(), ["K1", "K2"])

    with pytest.raises(RateLimited) as limited:
        indexer.fetch_torrent(
            Candidate("t", 1, "https://c411.example/api?t=get&id=1&apikey=K1"), retry=False
        )

    assert limited.value.retry_after == pytest.approx(120)


def test_the_json_api_gets_each_key_as_a_bearer_token() -> None:
    clock = FakeClock()
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers["authorization"])
        return httpx.Response(200, json={"data": [], "meta": {}})

    indexer = Indexer(
        url="https://c411.org/api/torznab",
        api_key="K1",
        extra_keys=["K2"],
        http=httpx.Client(transport=httpx.MockTransport(handler)),
        clock=clock.time,
        sleep=clock.sleep,
    )
    indexer.catalogue_json({"page": "1"})
    indexer.catalogue_json({"page": "2"})

    assert seen == ["Bearer K1", "Bearer K2"]


def test_no_key_ever_shows_in_errors_or_stored_searches(tmp_path: Path) -> None:
    from torrentlinker.store import Store

    clock = FakeClock()
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 2:
            return httpx.Response(500)
        return httpx.Response(200, text=SEARCH_XML.replace("apikey=K", "apikey=SECRET2"))

    store = Store(tmp_path / "s.db")
    indexer = Indexer(
        url="https://c411.example/api/torznab",
        api_key="SECRET1",
        extra_keys=["SECRET2"],
        http=httpx.Client(transport=httpx.MockTransport(handler)),
        clock=clock.time,
        sleep=clock.sleep,
        cache=store,
    )
    indexer.search(SearchQuery(q="a"))
    with pytest.raises(httpx.HTTPStatusError) as failed:
        indexer.search(SearchQuery(q="b"))

    stored = store._db.execute("SELECT body FROM search_cache").fetchone()[0]
    assert "SECRET" not in stored and "SECRET" not in str(failed.value)


def test_a_refused_extra_key_is_named() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401 if request.url.params["apikey"] == "K2" else 200, text=SEARCH_XML)

    clock = FakeClock()
    indexer = pool(handler, clock, ["K1", "K2"])
    indexer.search(SearchQuery(q="a"), cached=False)

    with pytest.raises(KeyRefused) as refused:
        indexer.search(SearchQuery(q="b"), cached=False)

    assert refused.value.key_number == 2 and "API key 2" in str(refused.value)


# Foreground and background ----------------------------------------------------


def test_a_request_the_user_waits_for_goes_before_the_background_ones() -> None:
    import threading

    from torrentlinker.ratelimit import Queue

    queue = Queue(0.15)  # real time, kept short
    order: list[str] = []
    first_sent = threading.Event()

    def plan_being_sent() -> None:
        for i in range(3):
            with queue.turn(background=True):
                order.append(f"plan {i}")
            first_sent.set()

    worker = threading.Thread(target=plan_being_sent)
    worker.start()
    first_sent.wait(2)
    with queue.turn():  # the user's Library search
        order.append("search")
    worker.join(5)

    assert order == ["plan 0", "search", "plan 1", "plan 2"]


def test_a_search_does_not_wait_long_when_c411_rests_every_key() -> None:
    clock = FakeClock()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "1200"})

    indexer = pool(handler, clock, ["K1", "K2"])

    with pytest.raises(RateLimited) as limited:
        indexer.search(SearchQuery(q="a"), cached=False)

    assert limited.value.retry_after == pytest.approx(1200)
    assert clock.sleeps == []  # told at once, not stuck for 20 minutes


def test_background_requests_wait_out_c411s_rest() -> None:
    clock = FakeClock()
    answers = [
        httpx.Response(429, headers={"Retry-After": "1200"}),
        httpx.Response(200, text=SEARCH_XML),
    ]
    indexer = pool(lambda r: answers.pop(0), clock, ["K1"])

    with indexer.background():
        found = indexer.search(SearchQuery(q="a"), cached=False)

    assert found and 1200 in [round(s) for s in clock.sleeps]


def test_drafts_go_to_c411_with_the_main_key_only() -> None:
    import json

    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "POST":
            return httpx.Response(200, json={"success": True, "data": {"id": 128232}})
        return httpx.Response(200, json={"success": True, "data": [{"id": 1}], "count": 1})

    ix = Indexer(
        url="https://c411.org/api",
        api_key="MAIN",
        extra_keys=["EXTRA"],
        http=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert ix.drafts() == [{"id": 1}]
    assert ix.save_draft({"title": "T"}) == 128232
    assert ix.save_draft({"title": "U"}) == 128232

    assert [r.method for r in seen] == ["GET", "POST", "POST"]
    assert {r.headers["Authorization"] for r in seen} == {"Bearer MAIN"}
    assert json.loads(seen[1].content) == {"title": "T"}


def test_a_key_without_the_drafts_scope_is_named_in_the_error() -> None:
    ix = Indexer(
        url="https://c411.org/api",
        api_key="K",
        http=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(403))),
    )

    with pytest.raises(KeyRefused, match="drafts:rw"):
        ix.save_draft({})
