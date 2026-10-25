"""A missing destination stays inside the durable owner question and approval flow."""

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from tests.test_agent_download_folders import MountedClient
from tests.test_assistant import generation_transport, login, wait_run
from tests.test_assistant_waits import response, terminal, tool
from torrentlinker.downloads import IndexerCategory
from torrentlinker.store import CatalogueRow
from torrentlinker.web.app import create_app

HASH = "b" * 40


def provider(request):
    body = json.loads(request.content)
    if not any(message.get("role") == "tool" for message in body["messages"]):
        return response(
            [
                tool(
                    "propose_action",
                    {
                        "request_id": "queue-book",
                        "operation": {
                            "kind": "enqueue",
                            "client_id": "default",
                            "hashes": [HASH],
                        },
                    },
                )
            ]
        )
    return response(text="Finished reviewing the requested download.")


def prepare(app, browser, root):
    assert (
        browser.post(
            "/api/setup/client",
            json={
                "client": "qbittorrent",
                "host": "https://box.test",
                "name": "Seedbox",
            },
        ).status_code
        == 200
    )
    assert (
        browser.post(
            "/api/setup/folder",
            json={
                "local": str(root),
                "client_path": "/downloads",
                "purpose": "library",
            },
        ).status_code
        == 200
    )
    setup = app.state.agent_service.setup
    setup.settings.indexer_categories = {7000: IndexerCategory("Ebook")}
    setup.settings.free_space_margin = 0.0
    setup.save()
    restore_indexer(app)
    setup.store.save_catalogue(
        [
            CatalogueRow(HASH, "New book", 4, 1, 7000, "https://indexer.test/download", "", 1),
        ]
    )


def restore_indexer(app):
    app.state.agent_service.setup._indexer = SimpleNamespace(
        url="https://indexer.test",
        redact=lambda value: value,
        unredact=lambda value: value,
    )


def start_download(browser, mode="execute"):
    model = browser.post(
        "/api/setup/assistant/providers",
        json={
            "name": "Local",
            "kind": "ollama",
            "model": "test",
        },
    ).json()
    chat = browser.post(
        "/api/assistant/conversations",
        json={
            "provider_id": model["id"],
            "policy": {
                "name": "Helper",
                "clients": ["default"],
                "mode": mode,
                "permissions": ["queue"] if mode == "execute" else [],
                "reserve_bytes": 0,
            },
        },
    ).json()
    run = browser.post(
        "/api/assistant/jobs",
        json={
            "conversation_id": chat["id"],
            "message": "Download this ebook.",
        },
    ).json()
    return run["id"]


def mounted(tmp_path):
    root = tmp_path / "media"
    books = root / "books"
    books.mkdir(parents=True)
    (books / "book.epub").write_bytes(b"book")
    return root, books


@pytest.mark.parametrize("approve", [True, False])
@pytest.mark.parametrize("restart", [True, False])
def test_missing_folder_asks_then_approves_and_resumes_original_once(tmp_path, approve, restart):
    root, books = mounted(tmp_path)

    def app():
        return create_app(
            tmp_path / "config",
            password="test-password-long",
            roots=(root,),
            connector=lambda *args: MountedClient(),
            assistant_transport=generation_transport(provider),
        )

    first = app()
    with TestClient(first) as browser:
        login(browser)
        prepare(first, browser, root)
        identifier = start_download(browser)
        run = wait_run(browser, identifier)
        assert run["status"] == "awaiting_user", run
        question = run["events"][-1]["question"]
        assert "Ebook" in question["question"]
        assert "Seedbox" in question["question"]
        assert str(books) in question["options"]
        assert run["calls"] == 1
        if not restart:
            finish_folder(browser, first, identifier, books, approve)
    if restart:
        second = app()
        with TestClient(second) as browser:
            login(browser)
            restore_indexer(second)
            assert wait_run(browser, identifier)["status"] == "awaiting_user"
            finish_folder(browser, second, identifier, books, approve)


@pytest.mark.parametrize("book_configured", [False, True])
def test_mixed_batch_recovers_each_missing_category_without_setting_default(
    tmp_path, book_configured
):
    root, books = mounted(tmp_path)
    game_hash = "c" * 40

    def mixed_provider(request):
        body = json.loads(request.content)
        if not any(message.get("role") == "tool" for message in body["messages"]):
            return response(
                [
                    tool(
                        "propose_action",
                        {
                            "request_id": "mixed-downloads",
                            "operation": {
                                "kind": "enqueue",
                                "client_id": "default",
                                "hashes": [HASH, game_hash],
                            },
                        },
                    )
                ]
            )
        return response(text="Queued.")

    app = create_app(
        tmp_path / "config",
        password="test-password-long",
        roots=(root,),
        connector=lambda *args: MountedClient(),
        assistant_transport=generation_transport(mixed_provider),
    )
    with TestClient(app) as browser:
        login(browser)
        prepare(app, browser, root)
        setup = app.state.agent_service.setup
        setup.settings.indexer_categories[4050] = IndexerCategory("Games")
        if book_configured:
            setup.settings.download_folders.by_category[7000] = str(books)
        setup.save()
        setup.store.save_catalogue(
            [CatalogueRow(game_hash, "Game", 4, 1, 4050, "https://indexer.test/game", "", 1)]
        )
        identifier = start_download(browser)
        for category in [4050] if book_configured else [7000, 4050]:
            run = wait_run(browser, identifier)
            assert run["status"] == "awaiting_user", run
            index = len(run["events"]) - 1
            event = run["events"][index]
            assert event["folder_recovery"]["requirement"]["category"] == category
            assert setup.settings.indexer_categories[category].name in event["question"]["question"]
            assert browser.get("/api/queue").json() == []
            browser.post(
                f"/api/assistant/jobs/{identifier}/questions/{index}", json={"answer": str(books)}
            )
            run = wait_run(browser, identifier)
            assert run["status"] == "awaiting_approval", run
            assert run["events"][index]["review"]["category"] == category
            browser.post(
                f"/api/assistant/jobs/{identifier}/decisions/{index}", json={"approve": True}
            )
        run = terminal(browser, identifier)
        assert run["status"] == "completed", run
        assert len(browser.get("/api/queue").json()) == 2
        assert setup.settings.download_folders.default == ""
        assert setup.settings.download_folders.by_category == {7000: str(books), 4050: str(books)}


def finish_folder(browser, app, identifier, books, approve):
    run = wait_run(browser, identifier)
    index = len(run["events"]) - 1
    assert browser.post(
        f"/api/assistant/jobs/{identifier}/questions/{index}",
        json={
            "answer": str(books),
        },
    ).is_success
    run = wait_run(browser, identifier)
    assert run["status"] == "awaiting_approval", run
    review = run["events"][index]["review"]
    assert review["client_id"] == "default"
    assert review["category"] == 7000
    assert review["path"] == str(books)
    assert app.state.agent_service.setup.settings.download_folders.by_category == {}
    assert browser.get("/api/queue").json() == []
    assert browser.post(
        f"/api/assistant/jobs/{identifier}/decisions/{index}",
        json={
            "approve": approve,
        },
    ).is_success
    run = terminal(browser, identifier)
    assert run["status"] == "completed", run
    queue = browser.get("/api/queue").json()
    assert len(queue) == int(approve)
    if approve:
        assert queue[0]["folder"] == str(books)
        receipts = [
            e for e in run["events"] if e.get("result", {}).get("job", {}).get("kind") == "enqueue"
        ]
        assert len(receipts) == 1
        assert receipts[0]["result"]["job"]["result"]["queued"] == 1
    assert app.state.agent_service.setup.settings.download_folders.default == ""
    assert app.state.agent_service.setup.settings.download_folders.by_category == (
        {7000: str(books)} if approve else {}
    )
    # Decisions cannot replay the destination edit or original queue operation.
    repeated = browser.post(
        f"/api/assistant/jobs/{identifier}/decisions/{index}",
        json={
            "approve": approve,
        },
    )
    assert repeated.is_success or repeated.status_code == 400
    assert len(browser.get("/api/queue").json()) == int(approve)


def test_invalid_folder_answer_and_changed_mount_require_correction_and_new_approval(tmp_path):
    root, books = mounted(tmp_path)
    app = create_app(
        tmp_path / "config",
        password="test-password-long",
        roots=(root,),
        connector=lambda *args: MountedClient(),
        assistant_transport=generation_transport(provider),
    )
    with TestClient(app) as browser:
        login(browser)
        prepare(app, browser, root)
        identifier = start_download(browser)
        run = wait_run(browser, identifier)
        assert run["status"] == "awaiting_user", run
        browser.post(
            f"/api/assistant/jobs/{identifier}/questions/0", json={"answer": "/browser-only"}
        )
        run = wait_run(browser, identifier)
        assert run["status"] == "awaiting_user", run
        assert "unavailable" in run["events"][0]["question"]["question"]
        assert browser.get("/api/agents").json()["proposals"] == []
        browser.post(f"/api/assistant/jobs/{identifier}/questions/0", json={"answer": str(books)})
        assert wait_run(browser, identifier)["status"] == "awaiting_approval"
        (books / "book.epub").unlink()
        browser.post(f"/api/assistant/jobs/{identifier}/decisions/0", json={"approve": True})
        run = wait_run(browser, identifier)
        assert run["status"] == "awaiting_user", run
        assert "Mapping" in run["events"][0]["question"]["question"]
        assert app.state.agent_service.setup.settings.download_folders.by_category == {}
        (books / "book.epub").write_bytes(b"book")
        finish_folder(browser, app, identifier, books, True)


def test_folder_approval_does_not_approve_original_download(tmp_path):
    root, books = mounted(tmp_path)
    app = create_app(
        tmp_path / "config",
        password="test-password-long",
        roots=(root,),
        connector=lambda *args: MountedClient(),
        assistant_transport=generation_transport(provider),
    )
    with TestClient(app) as browser:
        login(browser)
        prepare(app, browser, root)
        identifier = start_download(browser, mode="propose")
        assert wait_run(browser, identifier)["status"] == "awaiting_user"
        browser.post(f"/api/assistant/jobs/{identifier}/questions/0", json={"answer": str(books)})
        assert wait_run(browser, identifier)["status"] == "awaiting_approval"
        browser.post(f"/api/assistant/jobs/{identifier}/decisions/0", json={"approve": True})
        run = wait_run(browser, identifier)
        assert run["status"] == "awaiting_approval", run
        assert run["events"][-1]["arguments"]["operation"]["kind"] == "enqueue"
        assert browser.get("/api/queue").json() == []
        index = len(run["events"]) - 1
        browser.post(f"/api/assistant/jobs/{identifier}/decisions/{index}", json={"approve": True})
        assert terminal(browser, identifier)["status"] == "completed"
        assert len(browser.get("/api/queue").json()) == 1


def test_folder_approval_survives_restart_without_repeating_question_or_original_action(tmp_path):
    root, books = mounted(tmp_path)

    def create():
        return create_app(
            tmp_path / "config",
            password="test-password-long",
            roots=(root,),
            connector=lambda *args: MountedClient(),
            assistant_transport=generation_transport(provider),
        )

    first = create()
    with TestClient(first) as browser:
        login(browser)
        prepare(first, browser, root)
        identifier = start_download(browser)
        assert wait_run(browser, identifier)["status"] == "awaiting_user"
        browser.post(f"/api/assistant/jobs/{identifier}/questions/0", json={"answer": str(books)})
        assert wait_run(browser, identifier)["status"] == "awaiting_approval"
    second = create()
    with TestClient(second) as browser:
        login(browser)
        restore_indexer(second)
        run = wait_run(browser, identifier)
        assert run["status"] == "awaiting_approval"
        assert run["calls"] == 1
        browser.post(f"/api/assistant/jobs/{identifier}/decisions/0", json={"approve": True})
        assert terminal(browser, identifier)["status"] == "completed"
        assert len(browser.get("/api/queue").json()) == 1


def test_settings_wait_after_folder_save_preserves_receipt_and_resumes_queue_once(
    tmp_path, monkeypatch
):
    root, books = mounted(tmp_path)
    app = create_app(
        tmp_path / "config",
        password="test-password-long",
        roots=(root,),
        connector=lambda *args: MountedClient(),
        assistant_transport=generation_transport(provider),
    )
    with TestClient(app) as browser:
        login(browser)
        prepare(app, browser, root)
        agent = app.state.agent_service
        configure = agent.setup.configure_download_folder

        def pause_after_save(*args, **kwargs):
            result = configure(*args, **kwargs)
            if kwargs.get("save"):
                agent.suspended = True
            return result

        monkeypatch.setattr(agent.setup, "configure_download_folder", pause_after_save)
        identifier = start_download(browser)
        assert wait_run(browser, identifier)["status"] == "awaiting_user"
        browser.post(f"/api/assistant/jobs/{identifier}/questions/0", json={"answer": str(books)})
        assert wait_run(browser, identifier)["status"] == "awaiting_approval"
        browser.post(f"/api/assistant/jobs/{identifier}/decisions/0", json={"approve": True})
        run = wait_run(browser, identifier)
        assert run["status"] == "waiting_settings", run
        assert len(run["events"]) == 1
        assert run["events"][0]["result"]["job"]["status"] == "completed"
        assert run["events"][0]["tool"] == "propose_download_folder"
        assert browser.get("/api/queue").json() == []
        agent.suspended = False
        run = terminal(browser, identifier)
        assert run["status"] == "completed", run
        assert len(run["events"]) == 2
        assert all(event["status"] == "finished" for event in run["events"])
        assert len(browser.get("/api/queue").json()) == 1
