import time
from dataclasses import replace
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from tests.test_agent_access import call, rpc
from tests.test_agent_download_folders import MountedClient
from tests.test_agent_selection import SelectionClient, connect
from tests.test_web_jobs import finished
from torrentlinker.catalogue_selection import CatalogueCriteria, select_catalogue_rows
from torrentlinker.downloads import IndexerCategory
from torrentlinker.store import CatalogueRow
from torrentlinker.web.app import create_app


def test_select_500_smallest_films_counts_whole_catalogue_without_a_download_folder(tmp_path):
    app = create_app(
        tmp_path, password="test-password-long", connector=lambda *args: SelectionClient([])
    )
    with TestClient(app) as browser:
        token = connect(browser)
        setup = app.state.agent_service.setup
        setup.settings.indexer_categories = {
            2000: IndexerCategory("Films & Videos"),
            2030: IndexerCategory("Films", 2000),
            7000: IndexerCategory("Ebook"),
        }
        setup.store.save_catalogue(
            [
                CatalogueRow(
                    f"{i:040x}",
                    f"Film {i}",
                    i * 1024,
                    5,
                    2030,
                    "https://test.invalid/download",
                    "",
                    1,
                )
                for i in range(1, 502)
            ]
            + [CatalogueRow("f" * 40, "Book", 1, 5, 7000, "https://test.invalid/download", "", 1)]
        )
        response = call(
            browser,
            token,
            "select_catalogue",
            {
                "request_id": "smallest-films",
                "client_id": "default",
                "criteria": {"categories": [2030], "sort_by": "size", "count": 500},
            },
        )
        assert not response.get("isError"), response
        proposal = response["structuredContent"]
        assert proposal["selection_id"] == proposal["job_id"]
        job = finished(browser, proposal["job_id"])
        assert job["status"] == "completed", job
        result = call(browser, token, "job_status", {"job_id": job["id"]})["structuredContent"][
            "result"
        ]
        assert result["selected_count"] == 500
        assert result["eligible_count"] == 501
        assert result["total_size_bytes"] == sum(range(1, 501)) * 1024
        assert result["min_size_bytes"] == 1024
        assert result["max_size_bytes"] == 500 * 1024
        assert len(result["rows"]) == 50
        assert all(r["category"] == 2030 for r in result["rows"])
        assert setup.settings.download_folders.default == ""


@pytest.fixture
def catalogue_app(tmp_path):
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
        token = connect(browser)
        assert browser.post(
            "/api/setup/folder",
            json={"local": str(root), "client_path": "/downloads", "purpose": "library"},
        ).is_success
        setup = app.state.agent_service.setup
        setup.settings.indexer_categories = {
            2000: IndexerCategory("Videos"),
            2030: IndexerCategory("Films", 2000),
            7000: IndexerCategory("Books"),
        }
        setup.settings.free_space_margin = 0
        setup.settings.download_folders.by_category = {2030: str(books), 7000: str(books)}
        setup.save()
        setup._indexer = SimpleNamespace(
            url="https://test.invalid", redact=lambda v: v, unredact=lambda v: v
        )
        setup.store.save_catalogue(
            [
                CatalogueRow(h * 40, title, size, 5, cat, "https://test.invalid/" + h, "", 1)
                for h, title, size, cat in [
                    ("a", "Film A", 4, 2030),
                    ("b", "Film B", 8, 2030),
                    ("c", "Book", 2, 7000),
                ]
            ]
        )
        yield app, browser, token


def selection(browser, token, **criteria):
    result = call(
        browser,
        token,
        "select_catalogue",
        {
            "request_id": "selection",
            "client_id": "default",
            "criteria": {"categories": [2030], "count": 1, **criteria},
        },
    )["structuredContent"]
    assert "job_id" in result, result
    done = finished(browser, result["job_id"])
    assert done["status"] == "completed", done
    return result["job_id"]


def test_mcp_discovery_categories_and_paginated_selection(catalogue_app):
    _, browser, token = catalogue_app
    tools = rpc(browser, token, "tools/list").json()["result"]["tools"]
    assert {"catalogue_categories", "select_catalogue", "enqueue_selection", "send_selection"} <= {
        t["name"] for t in tools
    }
    response = call(browser, token, "catalogue_categories", {"client_id": "default"})[
        "structuredContent"
    ]
    counts = {r["id"]: r["cached_count"] for r in response["rows"]}
    assert counts == {2000: 2, 2030: 2, 7000: 1}
    identifier = selection(browser, token, categories=[2000], count=3, descending=True)
    result = call(browser, token, "job_status", {"job_id": identifier, "offset": 1, "limit": 1})[
        "structuredContent"
    ]["result"]
    assert result["total_size_bytes"] == 12
    assert result["shortfall"] == 1
    assert [r["hash"] for r in result["rows"]] == ["a" * 40]


def test_enqueue_selection_requires_approval_and_retries_without_duplicating(catalogue_app):
    app, browser, token = catalogue_app
    identifier = selection(browser, token)
    arguments = {"request_id": "queue", "selection_id": identifier}
    proposal = call(browser, token, "enqueue_selection", arguments)["structuredContent"]
    assert proposal["requires_owner_approval"]
    assert browser.get("/api/queue").json() == []
    review = browser.get(f"/api/agents/proposals/{proposal['id']}/review").json()
    assert review["selection"]["total_size_bytes"] == 4
    approved = browser.post(f"/api/agents/proposals/{proposal['id']}/approve")
    assert approved.is_success, approved.text
    done = finished(browser, approved.json()["job_id"])
    assert done["status"] == "completed", done
    assert done["result"]["queued"] == 1
    queue = browser.get("/api/queue").json()
    assert len(queue) == 1
    assert queue[0]["size"] == 4
    retry = call(browser, token, "enqueue_selection", arguments)["structuredContent"]
    assert retry["job_id"] == done["id"]
    assert app.state.agent_service.setup.settings.download_folders.default == ""


@pytest.mark.parametrize("change", ["size", "category", "new-smaller"])
def test_changed_catalogue_selection_is_not_executed(catalogue_app, change):
    app, browser, token = catalogue_app
    identifier = selection(browser, token)
    proposal = call(
        browser, token, "enqueue_selection", {"request_id": "queue", "selection_id": identifier}
    )["structuredContent"]
    store = app.state.agent_service.setup.store
    row = store.catalogue(["a" * 40])[0]
    updated = replace(row, size=5) if change == "size" else replace(row, category=7000)
    if change == "new-smaller":
        updated = replace(row, infohash="d" * 40, size=1)
    store.save_catalogue([updated])
    response = browser.post(f"/api/agents/proposals/{proposal['id']}/approve")
    assert response.status_code == 400
    assert "selection changed" in response.text
    assert browser.get("/api/queue").json() == []


def test_selection_ownership_and_expiry_are_enforced(catalogue_app, monkeypatch):
    app, browser, token = catalogue_app
    identifier = selection(browser, token)
    other = browser.post("/api/agents", json={"name": "Other", "clients": ["default"]}).json()
    request = {"request_id": "queue", "selection_id": identifier}
    assert (
        "error" in call(browser, other["token"], "enqueue_selection", request)["structuredContent"]
    )
    later = time.time() + 901
    monkeypatch.setattr(time, "time", lambda: later)
    assert (
        "expired"
        in call(browser, token, "enqueue_selection", request)["structuredContent"]["error"]
    )
    assert browser.get("/api/queue").json() == []


def test_goal_category_reaches_plan_request(catalogue_app, monkeypatch):
    app, browser, token = catalogue_app
    saved = call(
        browser,
        token,
        "save_goal",
        {
            "goal_id": "films",
            "revision": 0,
            "goal": {"name": "Films", "client_ids": ["default"], "category": 2030},
        },
    )["structuredContent"]
    assert saved["category"] == 2030
    captured = []

    def request(actor, request_id, body):
        captured.append(body)
        return {"captured": True}

    monkeypatch.setattr(app.state.agent_service, "request", request)
    result = call(browser, token, "plan_goal", {"request_id": "plan", "goal_id": "films"})[
        "structuredContent"
    ]
    assert result["captured"]
    assert captured[0].kind == "plan"
    assert captured[0].category == 2030


def test_catalogue_filter_ranges_descendants_ties_and_unknown_sizes():
    cats = {2000: IndexerCategory("Video"), 2030: IndexerCategory("Film", 2000)}
    rows = [
        CatalogueRow(str(i) * 40, title, size, seeds, category, "", "", 1)
        for i, title, size, seeds, category in [
            (1, "Film alpha", 10, 2, 2030),
            (2, "Film beta", 10, 3, 2030),
            (3, "Film unknown", 0, -1, 2030),
            (4, "Film parent", 5, 4, 2000),
            (5, "Other", 12, 10, 2030),
            (6, "Film hidden", 11, -1, 2030),
        ]
    ]
    result = select_catalogue_rows(
        rows,
        cats,
        CatalogueCriteria(
            categories=[2030],
            query="film",
            exclude_terms=["beta"],
            min_size_bytes=5,
            max_size_bytes=11,
            min_seeders=1,
            max_seeders=3,
        ),
    )
    assert [r["hash"] for r in result["rows"]] == ["1" * 40]
    result = select_catalogue_rows(
        rows,
        cats,
        CatalogueCriteria(categories=[2000], sort_by="size", descending=True, offset=2, count=2),
    )
    assert [r["hash"] for r in result["rows"]] == ["1" * 40, "2" * 40]
    exact = select_catalogue_rows(
        rows, cats, CatalogueCriteria(categories=[2000], include_descendants=False)
    )
    assert exact["selected_count"] == 1
    assert exact["total_size_bytes"] == 5
    with pytest.raises(ValueError):
        CatalogueCriteria(min_size_bytes=20, max_size_bytes=10)


@pytest.mark.parametrize("limit", ["bytes", "torrents", "space"])
def test_large_queue_is_allowed_but_actual_send_respects_limits(catalogue_app, monkeypatch, limit):
    from collections import namedtuple

    app, browser, _ = catalogue_app
    limits = (
        {"daily_bytes": 1}
        if limit == "bytes"
        else {"daily_torrents": 0}
        if limit == "torrents"
        else {}
    )
    restricted = browser.post(
        "/api/agents", json={"name": "Limited", "clients": ["default"], **limits}
    ).json()
    token = restricted["token"]
    # A 4-byte selection is larger than this entire 1-byte disk, not just its free space.
    if limit == "space":
        usage = namedtuple("usage", "total used free")(1, 1, 0)
        monkeypatch.setattr("torrentlinker.agent.budgets.shutil.disk_usage", lambda _: usage)
    identifier = selection(browser, token)
    proposal = call(
        browser, token, "enqueue_selection", {"request_id": "queue", "selection_id": identifier}
    )["structuredContent"]
    approved = browser.post(f"/api/agents/proposals/{proposal['id']}/approve")
    assert approved.is_success, approved.text
    assert finished(browser, approved.json()["job_id"])["status"] == "completed"
    assert len(browser.get("/api/queue").json()) == 1
    assert (
        app.state.agent_service.access.db.execute("SELECT count(*) FROM reservations").fetchone()[0]
        == 0
    )
    send = call(
        browser, token, "send_selection", {"request_id": "send", "selection_id": identifier}
    )["structuredContent"]
    denied = browser.post(f"/api/agents/proposals/{send['id']}/approve")
    assert denied.status_code == 400
    assert ("Insufficient disk space" if limit == "space" else "budget") in denied.text
    assert browser.get("/api/queue").json()[0]["status"] == "queued"


def test_send_selection_only_sends_its_queued_rows(catalogue_app, monkeypatch):
    app, browser, token = catalogue_app
    for h in ["a", "c"]:
        proposal = call(
            browser,
            token,
            "propose_action",
            {
                "request_id": "queue-" + h,
                "operation": {"kind": "enqueue", "client_id": "default", "hashes": [h * 40]},
            },
        )["structuredContent"]
        approval = browser.post(f"/api/agents/proposals/{proposal['id']}/approve")
        assert approval.is_success, approval.text
        assert finished(browser, approval.json()["job_id"])["status"] == "completed"
    identifier = selection(browser, token)
    from torrentlinker.download_queue import QueueSendReport, entries

    sent = []

    def send(store, indexer, client, categories, stop, progress, *, only):
        report = QueueSendReport()
        for entry in entries(store):
            if entry.key in only:
                sent.append(entry.candidate.infohash)
                store.remove_downloads([entry.key])
                report.sent_keys.append(entry.key)
                report.added.append(entry.candidate.title)
        return report

    monkeypatch.setattr("torrentlinker.web.operations.run_queue", send)
    proposal = call(
        browser, token, "send_selection", {"request_id": "send-films", "selection_id": identifier}
    )["structuredContent"]
    assert proposal["requires_owner_approval"]
    assert sent == []
    approval = browser.post(f"/api/agents/proposals/{proposal['id']}/approve")
    assert approval.is_success, approval.text
    done = finished(browser, approval.json()["job_id"])
    assert done["status"] == "completed", done
    assert sent == ["a" * 40]
    assert [
        e.candidate.infohash
        for e in entries(app.state.agent_service.setup.store)
        if e.status == "queued"
    ] == ["c" * 40]


def test_catalogue_selection_survives_configuring_its_missing_folder(catalogue_app):
    app, browser, token = catalogue_app
    setup = app.state.agent_service.setup
    folder = setup.settings.download_folders.by_category.pop(2030)
    setup.save()
    identifier = selection(browser, token)
    arguments = {"request_id": "queue", "selection_id": identifier}
    required = call(browser, token, "enqueue_selection", arguments)["structuredContent"]
    assert required["download_folder_required"]["category"] == 2030
    proposal = call(
        browser,
        token,
        "propose_download_folder",
        {"request_id": "folder", "client_id": "default", "category": 2030, "path": folder},
    )["structuredContent"]
    approved = browser.post(f"/api/agents/proposals/{proposal['id']}/approve")
    assert approved.is_success, approved.text
    assert finished(browser, approved.json()["job_id"])["status"] == "completed"
    proposal = call(browser, token, "enqueue_selection", arguments)["structuredContent"]
    approved = browser.post(f"/api/agents/proposals/{proposal['id']}/approve")
    assert approved.is_success, approved.text
    done = finished(browser, approved.json()["job_id"])
    assert done["status"] == "completed", done
    assert len(browser.get("/api/queue").json()) == 1
    assert setup.settings.download_folders.default == ""
