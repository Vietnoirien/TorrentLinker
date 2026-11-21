import json
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from tests.torznab_fixtures import CAPS_XML, SEARCH_XML
from torrentlinker import net
from torrentlinker.config import Settings
from torrentlinker.indexer import RateLimited, SearchQuery
from torrentlinker.torznab import IndexerKeyRefused, TorznabIndexer, retry_after
from torrentlinker.web.app import create_app


class Clock:
    def __init__(self) -> None:
        self.now = 100.0
        self.sleeps: list[float] = []

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def indexer(handler, clock: Clock) -> TorznabIndexer:  # type: ignore[no-untyped-def]
    return TorznabIndexer(
        "https://other.example/api",
        "SECRET",
        "Other",
        http=httpx.Client(transport=httpx.MockTransport(handler)),
        clock=clock.time,
        sleep=clock.sleep,
    )


def test_a_429_rests_the_pacer_for_retry_after_then_retries() -> None:
    clock, calls = Clock(), []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "7"})
        return httpx.Response(200, text=SEARCH_XML)

    found = indexer(handler, clock)
    with found.background():
        assert found.search(SearchQuery(q="x"))
    assert len(calls) == 2 and calls[1].url.params["apikey"] == "SECRET"
    assert sum(clock.sleeps) >= 7


def test_a_foreground_search_refuses_a_long_wait_and_no_pace_of_ours() -> None:
    clock = Clock()
    found = indexer(lambda r: httpx.Response(429, headers={"Retry-After": "600"}), clock)
    try:
        found.search(SearchQuery(q="x"))
    except RateLimited as error:
        assert error.retry_after == 600
    assert found.next_request_in() > 590

    fast = indexer(lambda r: httpx.Response(200, text=SEARCH_XML), clock)
    for _ in range(5):
        fast.search(SearchQuery(q="x"))
    assert clock.sleeps == []  # nothing waited: no cap of our own


def test_retry_after_as_seconds_or_date_and_refused_key_hides_secret() -> None:
    assert retry_after(httpx.Response(429, headers={"Retry-After": "12"})) == 12
    assert retry_after(httpx.Response(429, headers={"Retry-After": "soon"})) == 30
    clock = Clock()
    found = indexer(lambda r: httpx.Response(401), clock)
    try:
        found.search(SearchQuery(q="x"))
    except IndexerKeyRefused as error:
        assert "SECRET" not in str(error)


def test_old_settings_migrate_to_a_list_with_c411_first(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"indexer": {"url": "https://c411.example/api"}}))
    settings = Settings.load(path)
    assert [i.id for i in settings.indexers] == ["c411"]
    assert settings.indexer.url == "https://c411.example/api"
    settings.save(path)
    assert Settings.load(path).indexer.url == "https://c411.example/api"


def test_owner_adds_tests_disables_and_removes_an_indexer(tmp_path: Path, monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("apikey") != "good":
            return httpx.Response(401)
        return httpx.Response(200, text=CAPS_XML)

    monkeypatch.setattr(
        net, "client", lambda **kwargs: httpx.Client(transport=httpx.MockTransport(handler))
    )
    with TestClient(create_app(tmp_path, password="test-password-long")) as web:
        web.headers["X-TorrentLinker"] = "1"
        assert web.post("/api/login", json={"password": "test-password-long"}).status_code == 200
        bad = web.post(
            "/api/indexers", json={"name": "O", "url": "https://o.example/api", "api_key": "bad"}
        )
        assert bad.status_code == 400
        added = web.post(
            "/api/indexers",
            json={"name": "Other", "url": "https://o.example/api", "api_key": "good"},
        )
        assert added.status_code == 200, added.text
        assert "imdbid" in added.json()["searchable_ids"]
        listed = web.get("/api/indexers").json()["indexers"]
        assert [r["name"] for r in listed] == ["c411", "Other"]
        assert "good" not in json.dumps(listed) and listed[1]["has_key"]
        identifier = added.json()["id"]
        assert web.post(f"/api/indexers/{identifier}", json={"enabled": False}).status_code == 200
        assert web.post(f"/api/indexers/{identifier}/test").json()["ok"]
        assert not web.get("/api/indexers").json()["indexers"][1]["enabled"]
        assert web.post("/api/indexers/c411/remove").status_code == 400
        assert web.post(f"/api/indexers/{identifier}/remove").status_code == 200
        assert len(web.get("/api/indexers").json()["indexers"]) == 1
        assert "good" not in (tmp_path / "settings.json").read_text()
