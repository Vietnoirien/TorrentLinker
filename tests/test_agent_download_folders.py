from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.test_agent_access import call
from tests.test_web_jobs import finished, login
from torrentlinker.config import Settings
from torrentlinker.domain import Torrent
from torrentlinker.downloads import IndexerCategory
from torrentlinker.web.app import create_app


class MountedClient:
    def check(self):
        return "test"

    def folder_settings(self):
        from torrentlinker.client_folders import ClientFolder

        return [ClientFolder("Ebooks", "/downloads/books")]

    def torrents(self, **kwargs):
        return [Torrent("a" * 40, "book", Path("/downloads/books"))]

    def files(self, hash):
        return {"book.epub": 4}


@pytest.mark.parametrize("approve", [False, True])
def test_scoped_download_folder_requires_exact_owner_approval_and_persists(tmp_path, approve):
    root = tmp_path / "media"
    books = root / "books"
    books.mkdir(parents=True)
    (books / "book.epub").write_bytes(b"book")
    app = create_app(
        tmp_path / "config",
        password="test-password-long",
        roots=(root,),
        connector=lambda *args: MountedClient(),
    )
    with TestClient(app) as browser:
        login(browser)
        connection = {"client": "qbittorrent", "host": "https://one.test"}
        assert browser.post("/api/setup/client", json=connection).status_code == 200
        other = browser.post(
            "/api/clients", json={**connection, "host": "https://two.test", "name": "Other"}
        )
        assert other.status_code == 200
        other_id = other.json()["client_id"]
        setup = app.state.agent_service.setup
        setup.settings.indexer_categories = {7000: IndexerCategory("Ebook")}
        setup.save()
        # Establish a mapping through the normal owner setup flow without setting
        # any default Download Folder.
        saved = browser.post(
            "/api/setup/folder",
            json={
                "local": str(root),
                "client_path": "/downloads",
                "purpose": "library",
            },
        )
        assert saved.status_code == 200, saved.text
        grant = browser.post(
            "/api/agents",
            json={
                "name": "Helper",
                "clients": ["default", other_id],
                "mode": "execute",
                "permissions": ["downloads"],
            },
        ).json()
        browser.put("/api/agents", json={"enabled": True})
        options = call(
            browser,
            grant["token"],
            "download_folder_options",
            {
                "client_id": "default",
                "category": 7000,
            },
        )["structuredContent"]
        assert options["custom_answer_allowed"]
        assert options["suggestions"] == [{"path": str(books), "client_path": "/downloads/books"}]
        before = (tmp_path / "config" / "settings.json").read_bytes()
        arguments = {
            "request_id": "books-folder",
            "client_id": "default",
            "path": str(books),
            "category": 7000,
        }
        proposed = call(browser, grant["token"], "propose_download_folder", arguments)
        proposal = proposed["structuredContent"]
        assert proposal["requires_owner_approval"]
        assert (tmp_path / "config" / "settings.json").read_bytes() == before
        review = browser.get(f"/api/agents/proposals/{proposal['id']}/review").json()
        assert review["path"] == str(books)
        assert review["client_id"] == "default"
        assert review["category_name"] == "Ebook"
        assert review["client_path"] == "/downloads/books"
        if approve:
            approved = browser.post(f"/api/agents/proposals/{proposal['id']}/approve")
            assert approved.status_code == 200, approved.text
            result = finished(browser, approved.json()["job_id"])
            assert result["status"] == "completed", result
            repeated = call(browser, grant["token"], "propose_download_folder", arguments)
            assert repeated["structuredContent"]["id"] == proposal["id"]
            repeated_approval = browser.post(f"/api/agents/proposals/{proposal['id']}/approve")
            assert repeated_approval.json()["job_id"] == approved.json()["job_id"]
            from types import SimpleNamespace

            from torrentlinker.store import CatalogueRow

            setup._indexer = SimpleNamespace(
                url="https://indexer.test",
                redact=lambda value: value,
                unredact=lambda value: value,
            )
            setup.store.save_catalogue(
                [
                    CatalogueRow(
                        "b" * 40,
                        "New book",
                        4,
                        1,
                        7000,
                        "https://indexer.test/download",
                        "",
                        1,
                    )
                ]
            )
            for expected in [1, 0]:
                queued = browser.post(
                    "/api/jobs",
                    json={
                        "kind": "enqueue",
                        "client_id": "default",
                        "hashes": ["b" * 40],
                    },
                )
                assert queued.status_code == 202, queued.text
                result = finished(browser, queued.json()["id"])
                assert result["status"] == "completed", result
                assert result["result"]["queued"] == expected
            queue = browser.get("/api/queue", params={"client_id": "default"}).json()
            assert len(queue) == 1
            assert queue[0]["folder"] == str(books)
        else:
            assert browser.post(f"/api/agents/proposals/{proposal['id']}/reject").status_code == 200
            assert (tmp_path / "config" / "settings.json").read_bytes() == before
        loaded = Settings.load(tmp_path / "config" / "settings.json")
        assert loaded.for_client("default").download_folders.by_category == (
            {7000: str(books)} if approve else {}
        )
        assert loaded.for_client("default").download_folders.default == ""
        assert loaded.for_client(other_id).download_folders.by_category == {}
        assert loaded.for_client(other_id).download_folders.default == ""


def test_folder_proposal_refuses_unmounted_paths_and_mapping_changes(tmp_path):
    root = tmp_path / "media"
    root.mkdir()
    app = create_app(
        tmp_path / "config",
        password="test-password-long",
        roots=(root,),
        connector=lambda *args: MountedClient(),
    )
    with TestClient(app) as browser:
        login(browser)
        browser.post(
            "/api/setup/client", json={"client": "qbittorrent", "host": "https://box.test"}
        )
        grant = browser.post("/api/agents", json={"name": "Helper", "clients": ["default"]}).json()
        browser.put("/api/agents", json={"enabled": True})
        for path, client_path in [("/not-mounted", ""), (str(root), "/invented")]:
            result = call(
                browser,
                grant["token"],
                "propose_download_folder",
                {
                    "request_id": path,
                    "client_id": "default",
                    "path": path,
                    "client_path": client_path,
                },
            )["structuredContent"]
            assert "error" in result
        result = call(
            browser,
            grant["token"],
            "propose_download_folder",
            {
                "request_id": "unverified",
                "client_id": "default",
                "path": str(root),
            },
        )["structuredContent"]
        assert "seeded sample" in result["error"]
        assert browser.get("/api/agents").json()["proposals"] == []
        assert app.state.agent_service.setup.settings.download_folders.default == ""


def test_folder_approval_revalidates_mount_after_proposal_and_can_be_corrected(tmp_path):
    root = tmp_path / "media"
    books = root / "books"
    books.mkdir(parents=True)
    sample = books / "book.epub"
    sample.write_bytes(b"book")
    app = create_app(
        tmp_path / "config",
        password="test-password-long",
        roots=(root,),
        connector=lambda *args: MountedClient(),
    )
    with TestClient(app) as browser:
        login(browser)
        browser.post(
            "/api/setup/client", json={"client": "qbittorrent", "host": "https://box.test"}
        )
        browser.post(
            "/api/setup/folder",
            json={
                "local": str(root),
                "client_path": "/downloads",
                "purpose": "library",
            },
        )
        grant = browser.post("/api/agents", json={"name": "Helper", "clients": ["default"]}).json()
        browser.put("/api/agents", json={"enabled": True})
        arguments = {"request_id": "first", "client_id": "default", "path": str(books)}
        proposed = call(browser, grant["token"], "propose_download_folder", arguments)[
            "structuredContent"
        ]
        review = browser.get(f"/api/agents/proposals/{proposed['id']}/review").json()
        assert review["category"] is None
        assert review["category_name"] == (
            "Default for all categories without a configured Download Folder"
        )
        sample.unlink()
        approved = browser.post(f"/api/agents/proposals/{proposed['id']}/approve")
        result = finished(browser, approved.json()["job_id"])
        assert result["status"] == "failed", result
        assert "mapping" in result["error"].lower()
        assert app.state.agent_service.setup.settings.download_folders.default == ""
        sample.write_bytes(b"book")
        corrected = call(
            browser,
            grant["token"],
            "propose_download_folder",
            {
                **arguments,
                "request_id": "corrected",
            },
        )["structuredContent"]
        assert corrected["requires_owner_approval"]
        assert app.state.agent_service.setup.settings.download_folders.default == ""
        approved = browser.post(f"/api/agents/proposals/{corrected['id']}/approve")
        assert finished(browser, approved.json()["job_id"])["status"] == "completed"


def test_category_plan_uses_child_download_folders_without_requiring_default(tmp_path):
    from torrentlinker.agent.desktop import DesktopSetup
    from torrentlinker.store import CatalogueRow, Store

    class LocalClient(MountedClient):
        def torrents(self, **kwargs):
            return []

    folders = [tmp_path / name for name in ("books", "children", "other")]
    for folder in folders:
        folder.mkdir()
    settings = Settings()
    settings.free_space_margin = 0.0
    settings.indexer_categories = {
        7000: IndexerCategory("Ebook"),
        7010: IndexerCategory("Audio", 7000),
        8000: IndexerCategory("Other"),
    }
    settings.download_folders.by_category = dict(
        zip([7000, 7010, 8000], map(str, folders), strict=True)
    )
    setup = DesktopSetup(settings, tmp_path / "settings.json", Store(tmp_path / "state.sqlite"))
    setup.connector = lambda *args: LocalClient()
    setup.store.save_catalogue(
        [
            CatalogueRow(
                h * 40, "Book " + h, 1024**2, 1, category, "https://indexer.test/" + h, "", 1
            )
            for h, category in [("b", 7000), ("c", 7010), ("d", 8000)]
        ]
    )
    app = create_app(
        tmp_path, password="test-password-long", service_override=setup, monitor_verifications=False
    )
    with TestClient(app) as browser:
        login(browser)
        requested = browser.post(
            "/api/jobs",
            json={
                "kind": "plan",
                "category": 7000,
                "cached_only": True,
            },
        )
        assert requested.status_code == 202, requested.text
        result = finished(browser, requested.json()["id"])
        assert result["status"] == "completed", result
        assert {row["hash"] for row in result["result"]["rows"]} == {"b" * 40, "c" * 40}
        assert setup.settings.download_folders.default == ""
