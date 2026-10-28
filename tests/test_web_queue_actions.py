from fastapi.testclient import TestClient

from tests.test_web_jobs import login
from torrentlinker.download_queue import enqueue, entries
from torrentlinker.indexer import Candidate, Indexer
from torrentlinker.store import Store
from torrentlinker.web.app import create_app


def test_retry_only_requeues_safe_failures_and_refusals(tmp_path):
    app = create_app(tmp_path, password="test-password-long")
    with TestClient(app) as browser:
        browser.headers["X-TorrentLinker"] = "1"
        assert browser.post("/api/queue/retry", json=[]).status_code == 401
        login(browser)
        store = Store(tmp_path / "catalogue.sqlite")
        indexer = Indexer("https://example.test/api", "key")
        statuses = ["sent", "failed", "failed", "uncertain", "refused", "queued"]
        for i, _status in enumerate(statuses):
            candidate = Candidate(str(i), 100, f"https://example.test/{i}", 2, f"{i:040x}")
            enqueue(store, indexer, candidate, tmp_path)
        rows = entries(store)
        for i, (entry, status) in enumerate(zip(rows, statuses, strict=True)):
            store.download_outcome(entry.key, status, retry_safe=i == 1)
        response = browser.post("/api/queue/retry", json=[e.key for e in rows])
        assert response.status_code == 200
        assert [e.status for e in entries(store)] == [
            "sent",
            "queued",
            "failed",
            "uncertain",
            "queued",
            "queued",
        ]
        assert browser.get("/api/jobs").json() == []
