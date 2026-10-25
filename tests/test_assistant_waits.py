"""Durable owner interactions through the same API used by desktop and web."""

import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from tests.test_assistant import generation_transport, login, wait_run
from tests.test_multi_client_web import Client
from torrentlinker.web.app import create_app


def tool(name, args, identifier="call"):
    return {
        "id": identifier,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args)},
    }


def response(calls=None, text=None):
    return httpx.Response(
        200,
        json={
            "choices": [
                {"message": {"role": "assistant", "content": text, "tool_calls": calls or []}}
            ]
        },
    )


def start(browser):
    p = browser.post(
        "/api/setup/assistant/providers", json={"name": "Local", "kind": "ollama", "model": "test"}
    ).json()
    chat = browser.post(
        "/api/assistant/conversations",
        json={"provider_id": p["id"], "policy": {"name": "Assistant", "clients": ["default"]}},
    ).json()
    run = browser.post(
        "/api/assistant/jobs", json={"conversation_id": chat["id"], "message": "Help me choose."}
    ).json()
    return run["id"], chat["id"]


def terminal(browser, identifier):
    for _ in range(300):
        run = browser.get(f"/api/assistant/jobs/{identifier}").json()
        if run["status"] in {"completed", "failed", "cancelled"}:
            return run
        time.sleep(0.01)
    raise AssertionError(run)


@pytest.mark.parametrize("answer", ["Films", "A custom choice"])
def test_question_survives_restart_and_requires_explicit_answer(tmp_path, answer):
    requests = []

    def provider(request):
        requests.append(json.loads(request.content))
        if len(requests) == 1:
            return response(
                [
                    tool(
                        "ask_user",
                        {"question": "Which Library Folder?", "options": ["Films", "Books"]},
                    )
                ]
            )
        encoded = json.dumps(requests[-1])
        assert answer in encoded
        assert "permission_granted" in encoded
        return response(text="Answer received.")

    def app():
        return create_app(
            tmp_path,
            password="test-password-long",
            assistant_transport=generation_transport(provider),
        )

    with TestClient(app()) as browser:
        login(browser)
        identifier, chat = start(browser)
        run = wait_run(browser, identifier)
        assert run["status"] == "awaiting_user"
        assert len(requests) == 1
        assert "checkpoint" not in run
        assert not browser.post(
            f"/api/assistant/jobs/{identifier}/decisions/0", json={"approve": True}
        ).is_success
        assert not browser.post(
            f"/api/assistant/jobs/{identifier}/questions/0", json={"answer": " "}
        ).is_success
        assert not browser.post(
            "/api/assistant/jobs", json={"conversation_id": chat, "message": "Overlap"}
        ).is_success
    with TestClient(app()) as browser:
        login(browser)
        assert browser.get(f"/api/assistant/jobs/{identifier}").json()["status"] == "awaiting_user"
        assert len(requests) == 1
        assert browser.post(
            f"/api/assistant/jobs/{identifier}/questions/0", json={"answer": answer}
        ).is_success
        run = terminal(browser, identifier)
        assert run["status"] == "completed", run
        assert run["calls"] == 2
        assert len(run["events"]) == 1
        assert not browser.post(
            f"/api/assistant/jobs/{identifier}/questions/0", json={"answer": "Again"}
        ).is_success
        assert browser.get("/api/agents").json()["proposals"] == []


@pytest.mark.parametrize("approve", [True, False])
def test_approval_resumes_batch_once_after_restart(tmp_path, approve):
    client = Client("Test")
    calls = []

    def provider(request):
        calls.append(json.loads(request.content))
        if len(calls) == 1:
            return response(
                [
                    tool("overview", {}, "read"),
                    tool(
                        "propose_action",
                        {
                            "request_id": "pause",
                            "operation": {
                                "kind": "manage",
                                "client_id": "default",
                                "action": "pause",
                                "hashes": ["a" * 40],
                            },
                        },
                        "action",
                    ),
                    tool("ask_user", {"question": "What next?", "options": ["Done"]}, "question"),
                ]
            )
        return response(text="All decisions received.")

    def app():
        return create_app(
            tmp_path,
            password="test-password-long",
            connector=lambda *args: client,
            assistant_transport=generation_transport(provider),
        )

    with TestClient(app()) as browser:
        login(browser)
        browser.post(
            "/api/setup/client", json={"client": "qbittorrent", "host": "https://one.test"}
        )
        identifier, _ = start(browser)
        run = wait_run(browser, identifier)
        assert run["status"] == "awaiting_approval", run
        assert len(run["events"]) == 2
        assert len(calls) == 1
        assert client.paused == []
    with TestClient(app()) as browser:
        login(browser)
        url = f"/api/assistant/jobs/{identifier}/decisions/1"
        assert browser.post(url, json={"approve": approve}).is_success
        browser.post(url, json={"approve": approve})
        for _ in range(300):
            run = browser.get(f"/api/assistant/jobs/{identifier}").json()
            if run["status"] == "awaiting_user":
                break
            time.sleep(0.01)
        assert run["status"] == "awaiting_user", run
        assert len(run["events"]) == 3
        assert client.paused == (["a" * 40] if approve else [])
        assert browser.post(
            f"/api/assistant/jobs/{identifier}/questions/2", json={"answer": "Done"}
        ).is_success
        assert terminal(browser, identifier)["status"] == "completed"
        assert len(calls) == 2
        assert len(browser.get("/api/agents").json()["proposals"]) == 1
        assert browser.get("/api/assistant/conversations").json()[0]["policy"]["mode"] == "propose"


def test_settings_wait_releases_worker_and_resumes_without_new_model_call(tmp_path):
    calls = 0

    def provider(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return response([tool("overview", {})])
        return response(text="Ready.")

    app = create_app(
        tmp_path, password="test-password-long", assistant_transport=generation_transport(provider)
    )
    with TestClient(app) as browser:
        login(browser)
        app.state.agent_service.suspended = True
        identifier, _ = start(browser)
        run = wait_run(browser, identifier)
        assert run["status"] == "waiting_settings", run
        assert calls == 1
        # A different conversation still gets a worker while this one waits.
        second, _ = start(browser)
        assert wait_run(browser, second)["status"] == "completed"
        app.state.agent_service.suspended = False
        run = terminal(browser, identifier)
        assert run["status"] == "completed", run
        assert len(run["events"]) == 1
        assert run["calls"] == 2


def test_chat_markdown_tables_allow_only_proxied_image_resources():
    from torrentlinker.assistant.markdown import render

    html = render(
        "| Name | Count |\n| --- | ---: |\n| Films | 2 |\n\n"
        "<script>alert(1)</script>\n\n![image](https://example.test/a.png)\n\n"
        "[bad](javascript:alert(1)) [good](https://example.test)"
    )
    assert "<table>" in html
    assert "<td>Films</td>" in html
    assert "<script>" not in html
    assert '<img src="api/assistant/image?url=' in html
    assert 'src="https://' not in html
    assert 'href="javascript:' not in html
    assert 'href="https://example.test"' in html


def test_expired_approval_is_not_executed_or_left_pending(tmp_path, monkeypatch):
    client = Client("Test")
    calls = []

    def provider(request):
        calls.append(request)
        if len(calls) == 1:
            return response(
                [
                    tool(
                        "propose_action",
                        {
                            "request_id": "pause",
                            "operation": {
                                "kind": "manage",
                                "client_id": "default",
                                "action": "pause",
                                "hashes": ["a" * 40],
                            },
                        },
                    )
                ]
            )
        assert "expired or settings changed" in request.content.decode()
        return response(text="The approval expired. Please request a fresh action.")

    app = create_app(
        tmp_path,
        password="test-password-long",
        connector=lambda *args: client,
        assistant_transport=generation_transport(provider),
    )
    with TestClient(app) as browser:
        login(browser)
        browser.post(
            "/api/setup/client", json={"client": "qbittorrent", "host": "https://one.test"}
        )
        identifier, _ = start(browser)
        assert wait_run(browser, identifier)["status"] == "awaiting_approval"
        original = time.time
        monkeypatch.setattr(time, "time", lambda: original() + 901)
        assert browser.post(
            f"/api/assistant/jobs/{identifier}/decisions/0", json={"approve": True}
        ).is_success
        run = terminal(browser, identifier)
        assert run["status"] == "completed", run
        assert client.paused == []
        assert browser.get("/api/agents").json()["proposals"][0]["status"] == "rejected"


def test_waiting_time_does_not_consume_run_duration(tmp_path, monkeypatch):
    calls = []

    def provider(request):
        calls.append(request)
        if len(calls) == 1:
            return response([tool("ask_user", {"question": "Continue?", "options": ["Yes"]})])
        return response(text="Continued.")

    app = create_app(
        tmp_path, password="test-password-long", assistant_transport=generation_transport(provider)
    )
    with TestClient(app) as browser:
        login(browser)
        p = browser.post(
            "/api/setup/assistant/providers",
            json={"name": "Local", "kind": "ollama", "model": "test"},
        ).json()
        chat = browser.post(
            "/api/assistant/conversations",
            json={
                "provider_id": p["id"],
                "max_seconds": 2,
                "policy": {"name": "Assistant", "clients": ["default"]},
            },
        ).json()
        identifier = browser.post(
            "/api/assistant/jobs", json={"conversation_id": chat["id"], "message": "Ask first"}
        ).json()["id"]
        assert wait_run(browser, identifier)["status"] == "awaiting_user"
        original = time.monotonic
        monkeypatch.setattr(time, "monotonic", lambda: original() + 3600)
        assert browser.post(
            f"/api/assistant/jobs/{identifier}/questions/0", json={"answer": "Yes"}
        ).is_success
        run = terminal(browser, identifier)
        assert run["status"] == "completed", run
        assert run["calls"] == 2


def test_approval_waits_for_settings_without_losing_the_decision(tmp_path, monkeypatch):
    client = Client("Test")
    calls = []

    def provider(request):
        calls.append(request)
        if len(calls) == 1:
            return response(
                [
                    tool(
                        "propose_action",
                        {
                            "request_id": "pause",
                            "operation": {
                                "kind": "manage",
                                "client_id": "default",
                                "action": "pause",
                                "hashes": ["a" * 40],
                            },
                        },
                    )
                ]
            )
        return response(text="Paused.")

    app = create_app(
        tmp_path,
        password="test-password-long",
        connector=lambda *args: client,
        assistant_transport=generation_transport(provider),
    )
    with TestClient(app) as browser:
        login(browser)
        browser.post(
            "/api/setup/client", json={"client": "qbittorrent", "host": "https://one.test"}
        )
        identifier, _ = start(browser)
        assert wait_run(browser, identifier)["status"] == "awaiting_approval"
        service = app.state.agent_service
        execute = service.execute
        entered = False

        def settings_opened_during_approval(*args, **kwargs):
            nonlocal entered
            if not entered:
                entered = True
                service.suspended = True
            return execute(*args, **kwargs)

        monkeypatch.setattr(service, "execute", settings_opened_during_approval)
        assert browser.post(
            f"/api/assistant/jobs/{identifier}/decisions/0", json={"approve": True}
        ).is_success
        for _ in range(300):
            run = browser.get(f"/api/assistant/jobs/{identifier}").json()
            if run["status"] == "waiting_settings":
                break
            time.sleep(0.01)
        assert run["status"] == "waiting_settings", run
        assert run["events"][0]["decision"] is True
        assert client.paused == []
        service.suspended = False
        run = terminal(browser, identifier)
        assert run["status"] == "completed", run
        assert client.paused == ["a" * 40]
        assert len(run["events"]) == 1
