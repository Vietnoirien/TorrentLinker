"""Authenticated review retains Candidates and rejects them across searches."""

import hashlib

from fastapi.testclient import TestClient

from tests.test_web_jobs import finished, login
from tests.torrents import make_torrent
from torrentlinker.indexer import Candidate
from torrentlinker.review import remember_candidates
from torrentlinker.web.app import create_app
from torrentlinker.web.security import ServerSecrets
from torrentlinker.web.setup import Setup


class EmptyClient:
    def torrents(self, **kwargs):
        return []


def test_review_exposes_file_comparison_and_reject_removes_candidate(tmp_path):
    root = tmp_path / "Books"
    root.mkdir()
    book = root / "Example.epub"
    book.write_bytes(b"book" * 100)
    directory = tmp_path / "config"
    directory.mkdir()
    setup = Setup(
        directory,
        roots=(root,),
        secrets=ServerSecrets(directory),
        connector=lambda *args: EmptyClient(),
    )
    setup.secrets.update({"indexer-api-key": "test-key"})
    setup.configured = True
    indexer = setup.indexer()
    candidate = Candidate(
        "Example EPUB", 400, "https://c411.org/download/example", infohash="a" * 40
    )
    remember_candidates(setup.store, indexer, book, [candidate])
    key = hashlib.sha1(indexer.redact(candidate.download_url).encode()).hexdigest()
    setup.store.cache_torrent(key, make_torrent(book))
    with TestClient(
        create_app(directory, password="test-password-long", service_override=setup)
    ) as browser:
        login(browser)
        assert browser.post("/api/setup/folder", json={"local": str(root)}).status_code == 200

        def run(body):
            created = browser.post("/api/jobs", json=body)
            assert created.status_code == 202, created.text
            result = finished(browser, created.json()["id"])
            assert result["status"] == "completed", result
            return result["result"]

        run({"kind": "scan"})
        rows = run({"kind": "library-review", "path": str(book)})
        assert rows[0]["match"] == "full"
        assert rows[0]["files"] == [
            {"torrent": "Example.epub", "local": "Example.epub", "status": "matched"}
        ]
        run({"kind": "library-reject", "path": str(book), "candidate_key": "a" * 40})
        assert run({"kind": "library-review", "path": str(book)}) == []
        denied = browser.post(
            "/api/jobs", json={"kind": "reseed", "path": str(book), "hashes": ["a" * 40]}
        )
        if denied.status_code == 202:
            assert finished(browser, denied.json()["id"])["status"] == "failed"


def test_remove_category_destination_restores_inheritance_without_changing_other_rules(tmp_path):
    from torrentlinker.downloads import IndexerCategory

    config = tmp_path / "config"
    config.mkdir()
    setup = Setup(config, (), ServerSecrets(config))
    setup.settings.indexer_categories = {
        2000: IndexerCategory("Films"),
        2010: IndexerCategory("HD", 2000),
        5000: IndexerCategory("TV"),
    }
    folders = setup.settings.download_folders
    folders.default = "/downloads"
    folders.by_category = {2000: "/films", 2010: "/hd", 5000: "/series"}
    setup.save()
    with TestClient(
        create_app(config, password="test-password-long", service_override=setup)
    ) as browser:
        login(browser)
        response = browser.post(
            "/api/setup/remove-folder",
            json={"local": "/hd", "purpose": "download", "category": 2010},
        )
        assert response.status_code == 200, response.text
        saved = browser.get("/api/setup").json()["download_folders"]
        assert saved["by_category"] == {"2000": "/films", "5000": "/series"}
        assert saved["effective"]["2010"] == "/films"
        assert saved["default"] == "/downloads"


def test_clearing_download_destination_keeps_the_scanned_library(tmp_path):
    root, config = tmp_path / "Books", tmp_path / "config"
    root.mkdir()
    config.mkdir()
    (root / "book.epub").write_bytes(b"book")
    setup = Setup(config, (root,), ServerSecrets(config), lambda *args: EmptyClient())
    setup.configured = True
    setup.settings.download_folders.by_category[7000] = str(root)
    setup.save()
    with TestClient(
        create_app(config, password="test-password-long", service_override=setup)
    ) as browser:
        login(browser)
        browser.post("/api/setup/folder", json={"local": str(root)})
        scan = browser.post("/api/jobs", json={"kind": "scan"})
        assert finished(browser, scan.json()["id"])["status"] == "completed"
        before = browser.get("/api/library").json()["rows"]
        assert len(before) == 1
        result = browser.post(
            "/api/setup/remove-folder",
            json={"local": str(root), "purpose": "download", "category": 7000},
        )
        assert result.status_code == 200
        assert browser.get("/api/library").json()["rows"] == before
        assert browser.get("/api/setup").json()["folders"][0]["local"] == str(root)
