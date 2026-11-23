"""Settings > Connections > tr4ker (ADR-0025, #175): its switch, keys, test and the adoption of an
existing Indexer. Every call is mocked; no tracker, TMDb or client is reached."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from tests.test_settings_secrets import connections_body
from tests.test_web_jobs import Client, login
from tests.test_web_plan_execution import prepared
from tests.torznab_fixtures import CAPS_XML
from torrentlinker import net
from torrentlinker.settings_workspace import SettingsWorkspace
from torrentlinker.web.app import create_app


def mock_network(monkeypatch, handler):
    monkeypatch.setattr(
        net, "client", lambda **kwargs: httpx.Client(transport=httpx.MockTransport(handler))
    )


def tr4ker_body(setup, **fields):
    body = connections_body(setup)
    body["trackers"] = {"tr4ker": fields}
    return body


def test_enabling_tr4ker_stores_its_keys_and_keeps_the_announce_url_in_step(tmp_path):
    _, setup, _, _ = prepared(tmp_path)
    workspace = SettingsWorkspace(setup)
    before = workspace.snapshot()
    assert before["connections"]["trackers"] == {"tr4ker": {"enabled": False}}
    assert before["adoptable"] == {"tr4ker": None}
    saved = workspace.save(
        "connections", tr4ker_body(setup, enabled=True, api_key="KEY-T4K", passkey="PASS-T4K")
    )
    assert saved["connections"]["trackers"]["tr4ker"] == {"enabled": True}
    assert saved["connections"]["secrets"]["trackers"]["tr4ker"] == {
        "api_key": True,
        "passkey": True,
    }
    assert setup.secrets.get("indexer-key-tr4ker") == "KEY-T4K"
    assert setup.secrets.get("indexer-passkey-tr4ker") == "PASS-T4K"
    assert setup.secrets.get("announce-url-tr4ker") == "https://tk.tr4ker.net/announce/PASS-T4K"
    entry = setup.settings.tracker_indexer("tr4ker")
    assert entry.enabled and entry.url == "https://tr4ker.net/api"
    for text in (json.dumps(saved), (tmp_path / "config" / "settings.json").read_text()):
        assert "KEY-T4K" not in text and "PASS-T4K" not in text
    # A save without the credentials keeps them; an empty passkey clears it and its Announce URL.
    workspace.save("connections", tr4ker_body(setup, enabled=True))
    assert setup.secrets.get("indexer-key-tr4ker") == "KEY-T4K"
    workspace.save("connections", tr4ker_body(setup, enabled=False, passkey=""))
    assert not setup.settings.tracker_indexer("tr4ker").enabled
    assert setup.secrets.get("indexer-passkey-tr4ker") == ""
    assert setup.secrets.get("announce-url-tr4ker") == ""
    assert setup.secrets.get("indexer-key-tr4ker") == "KEY-T4K"
    # c411 and unknown Trackers are not tr4ker's to set.
    bad = connections_body(setup)
    bad["trackers"] = {"c411": {"enabled": True}}
    with pytest.raises(ValueError, match="Unknown Tracker"):
        workspace.save("connections", bad)
    assert workspace.reveal("passkey:tr4ker") == ""


def test_the_tr4ker_test_reads_caps_through_the_torznab_path_with_the_typed_or_saved_key(
    tmp_path, monkeypatch
):
    _, setup, _, _ = prepared(tmp_path)
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.params.get("apikey") != "good":
            return httpx.Response(401)
        return httpx.Response(200, text=CAPS_XML)

    mock_network(monkeypatch, handler)
    workspace = SettingsWorkspace(setup)
    with pytest.raises(ValueError, match="Enter your tr4ker API key"):
        workspace.test_connection("tr4ker", {})
    found = workspace.test_connection("tr4ker", {"api_key": "good"})
    assert found["ok"] and "imdbid" in found["searchable_ids"] and found["modes"] >= 1
    assert str(seen[0].url).startswith("https://tr4ker.net/api?")
    with pytest.raises(ValueError) as refused:
        workspace.test_connection("tr4ker", {"api_key": "bad"})
    assert "bad" not in str(refused.value)
    setup.secrets.update({"indexer-key-tr4ker": "good"})
    assert workspace.test_connection("tr4ker", {})["ok"]
    with pytest.raises(ValueError, match="Unknown connection test"):
        workspace.test_connection("nobody", {})


def test_the_tmdb_test_accepts_or_refuses_the_key_without_echoing_it(tmp_path, monkeypatch):
    _, setup, _, _ = prepared(tmp_path)
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.url.path == "/3/configuration"
        return httpx.Response(200 if request.url.params["api_key"] == "good" else 401, json={})

    mock_network(monkeypatch, handler)
    workspace = SettingsWorkspace(setup)
    with pytest.raises(ValueError, match="Enter your TMDb API key"):
        workspace.test_connection("tmdb", {})
    assert workspace.test_connection("tmdb", {"api_key": "good"}) == {"ok": True}
    with pytest.raises(ValueError, match="TMDb refused the API key") as refused:
        workspace.test_connection("tmdb", {"api_key": "wrong"})
    assert "wrong" not in str(refused.value)
    setup.secrets.update({"tmdb-api-key": "good"})
    assert workspace.test_connection("tmdb", {})["ok"]
    mock_network(monkeypatch, lambda request: httpx.Response(500))
    with pytest.raises(ValueError, match="TMDb test failed"):
        workspace.test_connection("tmdb", {})


def add_hand_indexer(setup, monkeypatch, url="https://tr4ker.net/api", name="Tr4ker"):
    """An Indexer already there (added before tr4ker was a Tracker), with Cross-seed history."""
    from torrentlinker.config import IndexerSettings, Settings

    entry = IndexerSettings(url=url, id="ab12cd34", name=name)
    setup.settings.indexers.append(entry)
    setup.secrets.update({Settings.indexer_secret("ab12cd34"): "OLD-KEY"})
    setup.save()
    store = setup.store
    store.save_crossseed("item:/a", "ab12cd34", "k1", "review", {"title": "One"})
    store.save_crossseed("item:/b", "ab12cd34", "", "queued", {"name": "b"})
    store.for_client("other").save_crossseed("item:/c", "ab12cd34", "k2", "review", {})
    return entry


def test_adopting_an_indexer_keeps_its_key_and_cross_seed_history_and_leaves_one_entry(
    tmp_path, monkeypatch
):
    _, setup, _, _ = prepared(tmp_path)
    add_hand_indexer(setup, monkeypatch)
    workspace = SettingsWorkspace(setup)
    offer = workspace.snapshot()["adoptable"]["tr4ker"]
    assert offer == {
        "name": "Tr4ker",
        "source": "",
        "url": "https://tr4ker.net/api",
        "history": 3,
        "needs_key": False,
    }
    assert workspace.snapshot()["indexer_count"] == 2  # c411 and the one to adopt
    snapshot = workspace.adopt("tr4ker")
    assert snapshot["adoptable"] == {"tr4ker": None}
    assert snapshot["indexer_count"] == 1
    assert snapshot["connections"]["trackers"]["tr4ker"] == {"enabled": True}
    assert [i.id for i in setup.settings.indexers] == ["c411", "tr4ker"]
    assert setup.settings.indexers[1].url == "https://tr4ker.net/api"
    assert setup.secrets.get("indexer-key-tr4ker") == "OLD-KEY"
    assert setup.secrets.get("indexer-key-ab12cd34") == ""
    assert setup.store.crossseed_count("ab12cd34") == 0
    assert setup.store.crossseed_count("tr4ker") == 3
    assert [r["indexer_id"] for r in setup.store.crossseed_rows()] == ["tr4ker", "tr4ker"]
    rows = setup.indexer_rows()
    assert [(r["id"], r["tracker"]) for r in rows] == [("c411", "c411"), ("tr4ker", "tr4ker")]
    on_disk = (tmp_path / "config" / "settings.json").read_text()
    assert "OLD-KEY" not in json.dumps(snapshot) + on_disk
    with pytest.raises(ValueError, match="No Indexer of tr4ker to adopt"):
        workspace.adopt("tr4ker")
    with pytest.raises(ValueError, match="c411 is built in"):
        workspace.adopt("c411")


def test_adoption_keeps_the_key_tr4ker_already_has(tmp_path, monkeypatch):
    _, setup, _, _ = prepared(tmp_path)
    add_hand_indexer(setup, monkeypatch)
    workspace = SettingsWorkspace(setup)
    workspace.save("connections", tr4ker_body(setup, enabled=True, api_key="OWN-KEY"))
    assert workspace.snapshot()["adoptable"]["tr4ker"]["needs_key"] is False
    workspace.adopt("tr4ker")
    assert setup.secrets.get("indexer-key-tr4ker") == "OWN-KEY"
    assert setup.secrets.get("indexer-key-ab12cd34") == ""
    assert setup.store.crossseed_count("tr4ker") == 3


def test_a_prowlarr_resync_does_not_recreate_the_adopted_indexer(tmp_path, monkeypatch):
    listing = [
        {"id": 9, "name": "tr4ker", "protocol": "torrent", "enable": True},
        {"id": 1, "name": "Nebula", "protocol": "torrent", "enable": True},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/indexer":
            return httpx.Response(200, json=listing)
        return httpx.Response(200, text=CAPS_XML)

    mock_network(monkeypatch, handler)
    config, setup, _, _ = prepared(tmp_path)
    app = create_app(
        config,
        password="test-password-long",
        service_override=setup,
        connector=lambda *args: Client(),
    )
    with TestClient(app) as web:
        web.headers["X-TorrentLinker"] = "1"
        login(web)
        entry = {"service": "prowlarr", "url": "http://prowlarr.example:9696", "api_key": "hubkey"}
        assert web.post("/api/indexers/hub", json=entry).status_code == 200
        done = web.post("/api/indexers/hub/import", json={"ids": ["9", "1"]})
        assert sorted(done.json()["added"]) == ["Nebula", "tr4ker"]
        offer = web.get("/api/settings").json()["adoptable"]["tr4ker"]
        assert offer["source"] == "prowlarr" and offer["needs_key"] is True
        adopted = web.post("/api/settings/adopt/tr4ker", json={})
        assert adopted.status_code == 200, adopted.text
        # It now searches tr4ker itself; the hub's key is not tr4ker's and does not follow.
        own = next(i for i in setup.settings.indexers if i.id == "tr4ker")
        assert own.url == "https://tr4ker.net/api" and own.source == "prowlarr"
        assert setup.secrets.get("indexer-key-tr4ker") == ""
        assert adopted.json()["adoptable"] == {"tr4ker": None}
        rows = web.get("/api/indexers").json()["indexers"]
        assert [r["id"] for r in rows if r["tracker"] and not r["c411"]] == ["tr4ker"]
        available = web.get("/api/indexers/hub/available").json()["available"]
        assert {r["name"]: (r["imported"], r["adopted"]) for r in available} == {
            "tr4ker": (True, True),
            "Nebula": (True, False),
        }
        for _ in range(2):  # a re-import and a re-sync create nothing new
            again = web.post("/api/indexers/hub/import", json={"ids": ["9", "1"]})
            assert again.json()["added"] == []
            synced = web.post("/api/indexers/hub/sync").json()
            assert synced["new"] == [] and synced["removed"] == []
        ids = [r["id"] for r in web.get("/api/indexers").json()["indexers"]]
        assert ids.count("tr4ker") == 1 and len(ids) == 3
        own = next(i for i in setup.settings.indexers if i.id == "tr4ker")
        assert own.url == "https://tr4ker.net/api"  # the re-sync left the Tracker alone
        assert setup.secrets.get("indexer-key-tr4ker") == ""
        assert "hubkey" not in (config / "settings.json").read_text()


def test_a_tracker_cannot_be_added_as_a_plain_indexer(tmp_path, monkeypatch):
    mock_network(monkeypatch, lambda request: httpx.Response(200, text=CAPS_XML))
    _, setup, _, _ = prepared(tmp_path)
    from torrentlinker.web.setup import IndexerEntry

    with pytest.raises(ValueError, match="turn tr4ker on"):
        setup.add_indexer(IndexerEntry(name="T", url="https://tr4ker.net/api", api_key="k"))
    assert len(setup.settings.indexers) == 1


def test_the_desktop_workspace_takes_over_an_indexer_the_same_way(tmp_path):
    from torrentlinker.agent.desktop import DesktopSetup
    from torrentlinker.config import IndexerSettings, Settings
    from torrentlinker.store import Store
    from torrentlinker.web.security import ServerSecrets

    setup = DesktopSetup(
        Settings(language="en"), tmp_path / "settings.json", Store(tmp_path / "t.db")
    )
    setup.secrets = ServerSecrets(tmp_path)
    setup.settings.indexers.append(IndexerSettings(url="https://tr4ker.net/api", id="ab12cd34"))
    setup.secrets.update({"indexer-key-ab12cd34": "OLD-KEY"})
    setup.store.save_crossseed("item:/a", "ab12cd34", "k1", "review", {})
    workspace = SettingsWorkspace(setup)
    assert workspace.snapshot()["adoptable"]["tr4ker"]["history"] == 1
    assert workspace.adopt("tr4ker")["adoptable"] == {"tr4ker": None}
    assert [i.id for i in setup.settings.indexers] == ["c411", "tr4ker"]
    assert setup.secrets.get("indexer-key-tr4ker") == "OLD-KEY"
    assert setup.store.crossseed_count("tr4ker") == 1
