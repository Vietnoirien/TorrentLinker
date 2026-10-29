"""A reviewed WebUI Plan can be sent and resumed without a live tracker."""

import hashlib
import threading

import httpx
from fastapi.testclient import TestClient

from tests.fake_qbit import FakeQbit
from tests.test_web_jobs import finished, login
from tests.torrents import make_torrent
from torrentlinker.domain import Torrent
from torrentlinker.downloads import IndexerCategory
from torrentlinker.store import CatalogueRow
from torrentlinker.torrent_meta import read_torrent
from torrentlinker.web.app import create_app
from torrentlinker.web.security import ServerSecrets
from torrentlinker.web.setup import Setup
from torrentlinker.zen import ZenClass, ZenProfile


def prepared(tmp_path):
    root, config, source = tmp_path / "downloads", tmp_path / "config", tmp_path / "source"
    for folder in (root, config, source):
        folder.mkdir()
    (root / "existing.epub").write_bytes(b"seed")
    client = FakeQbit()
    client.by_hash["f" * 40] = Torrent(
        "f" * 40, "Existing", root, files={"existing.epub": 4}, size=4
    )
    setup = Setup(config, (root,), ServerSecrets(config), lambda *args: client)
    setup.configured = True
    setup.settings.zen = ZenProfile(ZenClass.SWARM_KEEPER)
    setup.settings.indexer_categories = {7000: IndexerCategory("Ebook")}
    setup.settings.download_folders.default = str(root)
    setup.settings.download_speed = 1000
    setup.secrets.update({"indexer-api-key": "test-key"})
    indexer = setup.indexer()
    rows = []
    for name in ("Alpha", "Beta", "Gamma"):
        book = source / f"{name}.epub"
        book.write_bytes(name.encode() * 100)
        data = make_torrent(book)
        meta = read_torrent(data)
        url = f"https://c411.org/download/{name}"
        key = hashlib.sha1(indexer.redact(url).encode()).hexdigest()
        setup.store.cache_torrent(key, data)
        rows.append(CatalogueRow(meta.infohash, name, book.stat().st_size, 3, 7000, url, "", 0))
    setup.store.save_catalogue(rows)
    setup.save()
    return config, setup, client, rows


def run(browser, body):
    response = browser.post("/api/jobs", json=body)
    assert response.status_code == 202, response.text
    result = finished(browser, response.json()["id"])
    assert result["status"] == "completed", result
    return result["result"]


def second_client(tmp_path, setup, first):
    root = tmp_path / "second-downloads"
    root.mkdir()
    (root / "existing.epub").write_bytes(b"seed")
    second = FakeQbit()
    second.by_hash["e" * 40] = Torrent(
        "e" * 40, "Existing second", root, files={"existing.epub": 4}, size=4
    )
    profile = setup.settings.add_client("Second client")
    profile.host = "http://second.example:8080"
    profile.download_folders.default = str(root)
    setup.roots = (*setup.roots, root)
    setup.connector = lambda kind, host, *args: second if host == profile.host else first
    setup.save()
    return profile, second


def test_distributed_plan_respects_each_client_budget_and_shared_disk(tmp_path):
    config, setup, first, rows = prepared(tmp_path)
    profile, second = second_client(tmp_path, setup, first)
    with TestClient(
        create_app(
            config,
            password="test-password-long",
            service_override=setup,
            monitor_verifications=False,
        )
    ) as browser:
        login(browser)
        plan = run(
            browser,
            {
                "kind": "plan",
                "cached_only": True,
                "client_ids": ["default", profile.id],
                "client_budgets": {"default": 500, profile.id: 500},
            },
        )
        assert len(plan["rows"]) == 2
        assert {r["client_id"] for r in plan["rows"]} == {"default", profile.id}
        for identifier in ("default", profile.id):
            assert (
                sum(r["download_size"] for r in plan["rows"] if r["client_id"] == identifier) <= 500
            )
        assert len(plan["storage"]) == 1  # both temp folders are on the same physical disk
        sent = run(browser, {"kind": "send-plan", "plan_id": plan["plan_id"]})
        assert len(sent["added"]) == 2
        assert len(first.downloads) == len(second.downloads) == 1
        for row in plan["rows"]:
            client = first if row["client_id"] == "default" else second
            assert str(client.by_hash[row["hash"]].save_path) == row["folder"]


def test_reviewed_plan_survives_reload_and_sends_only_selected_downloads(tmp_path):
    config, setup, client, rows = prepared(tmp_path)

    def app():
        return create_app(
            config,
            password="test-password-long",
            service_override=setup,
            monitor_verifications=False,
        )

    with TestClient(app()) as browser:
        login(browser)
        result = run(browser, {"kind": "plan", "cached_only": True})
        assert result["download_seconds"] == 1.4
        plan_id = result["plan_id"]
        assert browser.get("/api/zen/plan").json()["plan_id"] == plan_id
        assert (
            browser.post("/api/jobs", json={"kind": "send-plan", "plan_id": "stale"}).status_code
            == 400
        )
        sent = run(
            browser,
            {"kind": "send-plan", "plan_id": plan_id, "plan_selection": [rows[0].infohash] * 1001},
        )
        assert len(sent["added"]) == 1
        assert client.downloads == [rows[0].infohash]
        remaining = browser.get("/api/zen/plan").json()
        assert {r["hash"] for r in remaining["rows"]} == {r.infohash for r in rows[1:]}
        assert sum(s["download"] for s in remaining["storage"]) == remaining["size"] == 900
        assert remaining["storage"][0]["after_plan"] == result["storage"][0]["after_plan"]
    # A new HTTP app restores unsent downloads from the same saved Plan.
    with TestClient(app()) as browser:
        login(browser)
        remaining = browser.get("/api/zen/plan").json()
        assert {r["hash"] for r in remaining["rows"]} == {r.infohash for r in rows[1:]}
        run(browser, {"kind": "send-plan", "plan_id": remaining["plan_id"]})
        assert len(client.downloads) == 3
        assert browser.get("/api/zen/plan").json()["rows"] == []


def test_stopping_plan_send_keeps_unsent_rows_and_reports_progress(tmp_path):
    config, setup, client, rows = prepared(tmp_path)
    entered, release = threading.Event(), threading.Event()
    original = client.download

    def slow_download(*args):
        entered.set()
        assert release.wait(5)
        return original(*args)

    client.download = slow_download
    with TestClient(
        create_app(
            config,
            password="test-password-long",
            service_override=setup,
            monitor_verifications=False,
        )
    ) as browser:
        login(browser)
        plan = run(browser, {"kind": "plan", "cached_only": True})
        response = browser.post("/api/jobs", json={"kind": "send-plan", "plan_id": plan["plan_id"]})
        assert response.status_code == 202, response.text
        identifier = response.json()["id"]
        try:
            assert entered.wait(3)
            progress = browser.get(f"/api/jobs/{identifier}").json()["progress"]
            assert progress["total"] == 3
            assert progress["elapsed"] >= 0
            assert progress["zen_added"] == 0
            assert "remaining_seconds" in progress
            assert browser.post(f"/api/jobs/{identifier}/cancel", json={}).is_success
        finally:
            release.set()
        stopped = finished(browser, identifier)
        assert stopped["result"]["stopped"] is True
        assert len(client.downloads) == 1
        assert len(browser.get("/api/zen/plan").json()["rows"]) == 2


def test_web_zen_preferences_change_estimates_and_survive_reload(tmp_path):
    config, setup, client, rows = prepared(tmp_path)
    with TestClient(
        create_app(
            config,
            password="test-password-long",
            service_override=setup,
            monitor_verifications=False,
        )
    ) as browser:
        assert browser.get("/api/zen/preferences").status_code == 401
        login(browser)
        before = run(browser, {"kind": "plan", "cached_only": True})
        assert browser.post(
            "/api/zen/preferences",
            json={
                "uploads": 7,
                "download_speed": 2000,
                "seed_hours": 12,
                "free_space_margin": 0.2,
                "plan_exclusions": ["Gamma"],
            },
        ).is_success
        after = run(browser, {"kind": "plan", "cached_only": True})
        assert {r["title"] for r in after["rows"]} == {"Alpha", "Beta"}
        assert after["download_seconds"] == 0.45
        assert after["zen"] < before["zen"]
        assert browser.get("/api/zen/seeding").json()["uploads"] == 7
        assert browser.post("/api/zen/preferences", json={"seed_hours": 25}).status_code == 422
    from torrentlinker.config import Settings

    saved = Settings.load(config / "settings.json")
    assert saved.uploads == 7
    assert saved.free_space_margin == 0.2
    assert saved.download_speed == 2000


def test_stop_fetching_builds_from_cache_instead_of_cancelling_the_plan(tmp_path):
    from torrentlinker.indexer import Indexer

    config, setup, client, rows = prepared(tmp_path)
    entered, release = threading.Event(), threading.Event()

    def response(request):
        entered.set()
        assert release.wait(5)
        return httpx.Response(200, text="<rss><channel></channel></rss>")

    setup.settings.indexer.url = "https://tracker.example/api"
    setup._indexer = Indexer(
        setup.settings.indexer.url,
        "test-key",
        cache=setup.store,
        http=httpx.Client(transport=httpx.MockTransport(response)),
    )
    with TestClient(
        create_app(
            config,
            password="test-password-long",
            service_override=setup,
            monitor_verifications=False,
        )
    ) as browser:
        login(browser)
        response = browser.post("/api/jobs", json={"kind": "plan", "maximum_torrents": 2000})
        assert response.status_code == 202, response.text
        identifier = response.json()["id"]
        try:
            assert entered.wait(3)
            assert browser.post(f"/api/jobs/{identifier}/plan-now", json={}).is_success
        finally:
            release.set()
        result = finished(browser, identifier)
        assert result["status"] == "completed", result
        assert len(result["result"]["rows"]) == 3
        assert client.downloads == []
        assert browser.get("/api/zen/preferences").json()["plan_options"]["max_torrents"] == 2000


def test_plan_excludes_files_in_registered_library_outside_download_folders(tmp_path):
    config, setup, client, rows = prepared(tmp_path)
    source = tmp_path / "source"
    setup.roots = (*setup.roots, source)
    with TestClient(
        create_app(
            config,
            password="test-password-long",
            service_override=setup,
            monitor_verifications=False,
        )
    ) as browser:
        login(browser)
        assert browser.post("/api/setup/folder", json={"local": str(source)}).is_success
        run(browser, {"kind": "scan"})
        plan = run(browser, {"kind": "plan", "cached_only": True})
        assert plan["rows"] == []
        assert plan["excluded"] == 3
        assert {r["path"] for r in plan["on_disk"]} == {str(p) for p in source.iterdir()}


def test_failed_refresh_uses_cached_catalogue_with_visible_notice(tmp_path):
    from torrentlinker.indexer import Indexer

    config, setup, client, rows = prepared(tmp_path)
    setup.settings.indexer.url = "https://tracker.example/api"
    setup._indexer = Indexer(
        setup.settings.indexer.url,
        "test-key",
        cache=setup.store,
        http=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(403))),
    )
    with TestClient(
        create_app(
            config,
            password="test-password-long",
            service_override=setup,
            monitor_verifications=False,
        )
    ) as browser:
        login(browser)
        result = run(browser, {"kind": "plan"})
        assert len(result["rows"]) == 3
        assert "cached" in result["notice"].lower()
        assert "test-key" not in result["notice"]
        assert client.downloads == []


def test_additional_indexer_keys_are_private_and_used_for_plan_sends(tmp_path, monkeypatch):
    config, setup, client, rows = prepared(tmp_path)
    seen = []
    data = make_torrent(tmp_path / "source" / "Alpha.epub")

    def reply(request):
        key = request.url.params.get("apikey")
        if request.url.params.get("t") == "caps":
            return httpx.Response(
                200, text='<caps><categories><category id="7000" name="Ebook"/></categories></caps>'
            )
        seen.append(key)
        return (
            httpx.Response(429, headers={"Retry-After": "60"})
            if key == "main-secret"
            else httpx.Response(200, content=data)
        )

    monkeypatch.setattr(
        "torrentlinker.net.client", lambda **kw: httpx.Client(transport=httpx.MockTransport(reply))
    )
    # Force a real request through the local transport, rather than the torrent cache.
    from torrentlinker.store import Store

    setup.store = Store(config / "uncached.db")
    setup.store.save_catalogue(
        [
            CatalogueRow(
                rows[0].infohash,
                "Alpha",
                500,
                3,
                7000,
                "https://c411.org/api/torznab?t=get&id=alpha&apikey={{TORRENTLINKER_APIKEY}}",
                "",
                0,
            )
        ]
    )
    with TestClient(
        create_app(
            config,
            password="test-password-long",
            service_override=setup,
            monitor_verifications=False,
        )
    ) as browser:
        login(browser)
        response = browser.post(
            "/api/setup/indexer", json={"api_key": "main-secret", "extra_keys": ["extra-secret"]}
        )
        assert response.is_success, response.text
        state = browser.get("/api/setup")
        assert state.json()["indexer_key_count"] == 2
        assert "main-secret" not in state.text and "extra-secret" not in state.text
        plan = run(browser, {"kind": "plan", "cached_only": True})
        report = run(browser, {"kind": "send-plan", "plan_id": plan["plan_id"]})
        assert len(report["added"]) == 1, report
        assert seen == ["main-secret", "extra-secret"]
        assert "extra-secret" not in browser.get("/api/jobs").text
