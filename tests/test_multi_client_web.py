from pathlib import Path

from fastapi.testclient import TestClient

from tests.test_web_jobs import finished, login
from torrentlinker.domain import Torrent
from torrentlinker.web.app import create_app


class Client:
    def __init__(self, name):
        self.name = name
        self.paused = []

    def check(self):
        return "test"

    def folder_settings(self):
        return []

    def torrents(self, **kwargs):
        return [Torrent("a" * 40, self.name, Path("/data"), size=123)]

    def torrent(self, hash, **kwargs):
        return self.torrents()[0]

    def pause(self, hash):
        self.paused.append(hash)


def test_tracker_filter_groups_c411_mirror_and_keeps_actual_hosts(tmp_path):
    class MirrorClient(Client):
        def torrents(self, **kwargs):
            return [
                Torrent("a" * 40, "Main", Path("/data"), tracker="https://c411.org/announce/key"),
                Torrent(
                    "b" * 40, "Mirror", Path("/data"), tracker="https://tk.c411.tw/announce/key"
                ),
                Torrent("c" * 40, "Other", Path("/data"), tracker="https://other.test/announce"),
            ]

    app = create_app(
        tmp_path, password="test-password-long", connector=lambda *args: MirrorClient("test")
    )
    with TestClient(app) as browser:
        login(browser)
        assert (
            browser.post(
                "/api/setup/client", json={"client": "qbittorrent", "host": "https://one.test"}
            ).status_code
            == 200
        )
        response = browser.post("/api/jobs", json={"kind": "refresh"})
        assert finished(browser, response.json()["id"])["status"] == "completed"
        data = browser.get("/api/torrents", params={"tracker": "c411.org"}).json()
        assert data["trackers"] == ["c411.org", "other.test"]
        assert {row["name"] for row in data["rows"]} == {"Main", "Mirror"}
        assert next(row for row in data["rows"] if row["name"] == "Mirror")["trackers"] == [
            "tk.c411.tw"
        ]
        assert browser.get("/api/torrents", params={"tracker": "tk.c411.tw"}).json()["total"] == 2


def test_two_same_engine_clients_use_separate_secrets_and_actions(tmp_path):
    clients = {"https://one.test": Client("Local book"), "https://two.test": Client("Remote book")}
    connections = []

    def connect(kind, host, username, password, api_key=""):
        connections.append((host, password))
        return clients[host]

    app = create_app(tmp_path, password="test-password-long", connector=connect)
    with TestClient(app) as browser:
        login(browser)
        assert (
            browser.post(
                "/api/setup/client",
                json={
                    "client": "qbittorrent",
                    "host": "https://one.test",
                    "password": "first-private",
                    "name": "Home",
                },
            ).status_code
            == 200
        )
        added = browser.post(
            "/api/clients",
            json={
                "client": "qbittorrent",
                "host": "https://two.test",
                "password": "second-private",
                "name": "Seedbox",
            },
        )
        assert added.status_code == 200, added.text
        remote = added.json()["client_id"]
        result = browser.post("/api/jobs", json={"kind": "refresh", "client_id": "all"})
        assert finished(browser, result.json()["id"])["status"] == "completed"
        rows = browser.get("/api/torrents?client_id=all").json()["rows"]
        assert {(r["client_name"], r["name"]) for r in rows} == {
            ("Home", "Local book"),
            ("Seedbox", "Remote book"),
        }
        # A default change must not alter a job carrying an explicit destination.
        assert browser.post("/api/clients/default", json={"client_id": remote}).status_code == 200
        result = browser.post(
            "/api/jobs",
            json={
                "kind": "manage",
                "action": "pause",
                "hashes": ["a" * 40],
                "client_id": "default",
            },
        )
        job = finished(browser, result.json()["id"])
        assert job["status"] == "completed", job
        assert job["client_id"] == "default"
        assert clients["https://one.test"].paused == ["a" * 40]
        assert not clients["https://two.test"].paused
        removal = {
            "kind": "manage",
            "action": "delete",
            "hashes": ["a" * 40],
            "client_id": "default",
        }
        preview = browser.post("/api/confirm", json=removal)
        assert preview.status_code == 200
        # Consent for the same hash on Home cannot authorize deletion on Seedbox.
        rejected = browser.post(
            "/api/jobs",
            json={**removal, "client_id": remote, "confirmation": preview.json()["token"]},
        )
        assert rejected.status_code == 409
        assert (
            browser.post(
                "/api/setup/client",
                json={
                    "client_id": remote,
                    "client": "qbittorrent",
                    "host": "https://two.test",
                    "name": "Renamed",
                },
            ).status_code
            == 200
        )
        snapshot = browser.get("/api/setup?client_id=" + remote).json()
        assert snapshot["name"] == "Renamed"
        assert snapshot["client_id"] == remote
        assert "private" not in str(snapshot)
        assert ("https://one.test", "first-private") in connections
        assert ("https://two.test", "second-private") in connections

        def offline(**kwargs):
            raise TimeoutError("offline")

        clients["https://one.test"].torrents = offline
        result = browser.post("/api/jobs", json={"kind": "refresh", "client_id": "all"})
        refreshed = finished(browser, result.json()["id"])
        assert refreshed["status"] == "completed"
        overview = browser.get("/api/torrents?client_id=all").json()
        assert overview["client_errors"]
        assert any(r["client_id"] == remote for r in overview["rows"])
    # No credential is persisted in settings or job result JSON.
    assert "private" not in (tmp_path / "settings.json").read_text()


def test_plan_validates_its_destinations_instead_of_the_selected_workspace(tmp_path):
    import pytest

    from torrentlinker.web.operations import JobRequest, Operations
    from torrentlinker.web.security import ServerSecrets
    from torrentlinker.web.setup import Setup

    config = tmp_path / "config"
    storage = tmp_path / "downloads"
    config.mkdir()
    storage.mkdir()
    setup = Setup(config, (storage,), ServerSecrets(config))
    remote = setup.settings.add_client("Seedbox")
    remote.download_folders.default = str(storage)
    operations = Operations(setup)
    operations.validate(JobRequest(kind="plan", client_ids=[remote.id]))
    with pytest.raises(ValueError, match="Download Folder"):
        operations.validate(JobRequest(kind="plan", client_ids=["default"]))
