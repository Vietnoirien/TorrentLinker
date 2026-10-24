"""Assistant acceptance at owner setup/job APIs; provider HTTP is the external boundary."""

import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from torrentlinker.web.app import create_app


def login(browser):
    browser.headers["X-TorrentLinker"] = "1"
    assert browser.post("/api/login", json={"password": "test-password-long"}).is_success


@pytest.mark.parametrize(
    ("kind", "response"),
    [
        (
            "compatible",
            {
                "choices": [
                    {
                        "finish_reason": "length",
                        "message": {
                            "role": "assistant",
                            "content": "[b]Incomplete",
                            "tool_calls": [],
                        },
                    }
                ]
            },
        ),
        (
            "openai",
            {
                "status": "incomplete",
                "incomplete_details": {"reason": "max_output_tokens"},
                "output": [],
            },
        ),
        ("anthropic", {"stop_reason": "max_tokens", "content": []}),
        (
            "gemini",
            {
                "candidates": [
                    {
                        "finishReason": "MAX_TOKENS",
                        "content": {"role": "model", "parts": [{"text": "Incomplete"}]},
                    }
                ]
            },
        ),
    ],
)
def test_truncated_presentation_is_not_reported_as_completed(tmp_path, kind, response):
    app = create_app(
        tmp_path,
        password="test-password-long",
        assistant_transport=httpx.MockTransport(lambda request: httpx.Response(200, json=response)),
    )
    with TestClient(app) as browser:
        login(browser)
        provider = browser.post(
            "/api/setup/assistant/providers",
            json={
                "name": "Limited model",
                "kind": kind,
                "url": "http://localhost:1234/v1",
                "model": "test",
            },
        ).json()
        conversation = browser.post(
            "/api/assistant/conversations",
            json={
                "provider_id": provider["id"],
                "policy": {"name": "Read", "clients": ["default"]},
            },
        ).json()
        submitted = browser.post(
            "/api/assistant/jobs",
            json={"conversation_id": conversation["id"], "message": "Prepare a presentation."},
        ).json()
        result = wait_run(browser, submitted["id"])
        assert result["status"] == "failed", result
        assert "output token limit" in result["error"].lower()
        assert not result["events"]
        assert not browser.get("/api/agents").json()["proposals"]


def test_provider_setup_keeps_key_private_and_checks_real_tool_round_trip(tmp_path):
    seen = []

    def provider(request):
        body = json.loads(request.content)
        seen.append(body)
        assert request.headers["authorization"] == "Bearer provider-secret-123"
        if len(seen) == 1:
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "probe",
                        "type": "function",
                        "function": {
                            "name": "connection_probe",
                            "arguments": '{"value":"torrentlinker"}',
                        },
                    }
                ],
            }
        else:
            assert body["messages"][-1]["role"] == "tool"
            message = {"role": "assistant", "content": "Connected."}
        return httpx.Response(
            200, json={"choices": [{"message": message}], "usage": {"total_tokens": 12}}
        )

    app = create_app(
        tmp_path, password="test-password-long", assistant_transport=httpx.MockTransport(provider)
    )
    with TestClient(app) as browser:
        assert browser.get("/api/setup/assistant").status_code == 401
        login(browser)
        saved = browser.post(
            "/api/setup/assistant/providers",
            json={
                "name": "My local model",
                "kind": "compatible",
                "url": "http://localhost:1234/v1",
                "model": "test-model",
                "api_key": "provider-secret-123",
            },
        )
        assert saved.is_success, saved.text
        identifier = saved.json()["id"]
        assert "provider-secret-123" not in saved.text
        checked = browser.post(f"/api/setup/assistant/providers/{identifier}/test", json={})
        assert checked.is_success, checked.text
        assert checked.json()["tool_calling"] is True
        assert len(seen) == 2
        assert "provider-secret-123" not in browser.get("/api/setup/assistant").text
    assert b"provider-secret-123" not in (tmp_path / "assistant.sqlite").read_bytes()


def wait_run(browser, identifier):
    for _ in range(200):
        result = browser.get("/api/assistant/jobs/" + identifier).json()
        if result["status"] not in {"queued", "running"}:
            return result
        time.sleep(0.01)
    raise AssertionError("Assistant run did not finish")


def test_chat_uses_shared_proposals_without_enabling_external_mcp(tmp_path):
    count = 0

    def provider(request):
        nonlocal count
        count += 1
        if count == 1:
            message = {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "pause",
                        "type": "function",
                        "function": {
                            "name": "propose_action",
                            "arguments": json.dumps(
                                {
                                    "request_id": "pause-one",
                                    "operation": {
                                        "kind": "manage",
                                        "client_id": "default",
                                        "action": "pause",
                                        "hashes": ["a" * 40],
                                    },
                                }
                            ),
                        },
                    }
                ],
                "content": None,
            }
        else:
            message = {"role": "assistant", "content": "The pause is awaiting your approval."}
        return httpx.Response(
            200, json={"choices": [{"message": message}], "usage": {"total_tokens": 15}}
        )

    with TestClient(
        create_app(
            tmp_path,
            password="test-password-long",
            assistant_transport=httpx.MockTransport(provider),
        )
    ) as browser:
        login(browser)
        p = browser.post(
            "/api/setup/assistant/providers",
            json={"name": "Local", "kind": "ollama", "model": "test"},
        ).json()
        thread = browser.post(
            "/api/assistant/conversations",
            json={
                "name": "Books",
                "provider_id": p["id"],
                "policy": {"name": "Assistant", "clients": ["default"]},
            },
        )
        assert thread.is_success, thread.text
        run = browser.post(
            "/api/assistant/jobs",
            json={"conversation_id": thread.json()["id"], "message": "Pause this torrent."},
        )
        assert run.status_code == 202, run.text
        result = wait_run(browser, run.json()["id"])
        assert result["status"] == "awaiting_approval", result
        assert count == 2
        agents = browser.get("/api/agents").json()
        assert agents["enabled"] is False
        assert len(agents["proposals"]) == 1
        assert agents["proposals"][0]["status"] == "pending"
        assert result["tokens"] == 30
        assert "awaiting your approval" in result["messages"][-1]["content"]


def test_schedule_preview_run_now_pause_and_restart_are_persistent(tmp_path):
    def provider(request):
        return httpx.Response(
            200, json={"choices": [{"message": {"role": "assistant", "content": "Nothing to do."}}]}
        )

    def app():
        return create_app(
            tmp_path,
            password="test-password-long",
            assistant_transport=httpx.MockTransport(provider),
        )

    with TestClient(app()) as browser:
        login(browser)
        p = browser.post(
            "/api/setup/assistant/providers",
            json={"name": "Local", "kind": "ollama", "model": "test"},
        ).json()
        body = {
            "name": "Daily report",
            "instruction": "Summarize the current state.",
            "provider_id": p["id"],
            "policy": {"name": "Task", "clients": ["default"]},
            "frequency": "interval",
            "interval_minutes": 60,
            "enabled": True,
        }
        preview = browser.post("/api/assistant/schedules/preview", json=body)
        assert preview.is_success, preview.text
        assert 3590 < preview.json()["next_at"] - time.time() <= 3600
        task = browser.post("/api/assistant/schedules", json=body)
        assert task.is_success, task.text
        task_id = task.json()["id"]
        run = browser.post(f"/api/assistant/schedules/{task_id}/run", json={})
        assert run.is_success, run.text
        assert wait_run(browser, run.json()["id"])["status"] == "completed"
        body["enabled"] = False
        assert browser.put(f"/api/assistant/schedules/{task_id}", json=body).is_success
    with TestClient(app()) as browser:
        login(browser)
        tasks = browser.get("/api/assistant/schedules").json()
        assert len(tasks) == 1
        assert tasks[0]["enabled"] is False
        assert len(browser.get("/api/assistant/jobs").json()) == 1


def test_research_is_opt_in_and_rejects_private_network_urls(tmp_path):
    calls = 0

    def provider(request):
        nonlocal calls
        calls += 1
        body = json.loads(request.content)
        names = [t["function"]["name"] for t in body["tools"]]
        if calls == 1:
            assert "read_web_page" in names
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "web",
                        "type": "function",
                        "function": {
                            "name": "read_web_page",
                            "arguments": '{"url":"http://127.0.0.1:8080/private"}',
                        },
                    }
                ],
            }
        else:
            assert "public" in body["messages"][-1]["content"].lower()
            message = {"role": "assistant", "content": "This address cannot be fetched."}
        return httpx.Response(200, json={"choices": [{"message": message}]})

    with TestClient(
        create_app(
            tmp_path,
            password="test-password-long",
            assistant_transport=httpx.MockTransport(provider),
        )
    ) as browser:
        login(browser)
        p = browser.post(
            "/api/setup/assistant/providers",
            json={"name": "Local", "kind": "ollama", "model": "test"},
        ).json()
        c = browser.post(
            "/api/assistant/conversations",
            json={
                "provider_id": p["id"],
                "web": True,
                "policy": {"name": "Web", "clients": ["default"]},
            },
        ).json()
        r = browser.post(
            "/api/assistant/jobs", json={"conversation_id": c["id"], "message": "Read this link."}
        ).json()
        result = wait_run(browser, r["id"])
        assert result["status"] == "completed", result
        assert "public" in result["events"][0]["result"]["error"].lower()


def test_owner_can_stop_run_without_submitting_late_model_actions(tmp_path):
    import threading

    entered, release = threading.Event(), threading.Event()

    def provider(request):
        entered.set()
        release.wait(5)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "late",
                                    "type": "function",
                                    "function": {
                                        "name": "propose_action",
                                        "arguments": json.dumps(
                                            {
                                                "request_id": "late",
                                                "operation": {
                                                    "kind": "manage",
                                                    "client_id": "default",
                                                    "action": "pause",
                                                    "hashes": ["a" * 40],
                                                },
                                            }
                                        ),
                                    },
                                }
                            ],
                        }
                    }
                ]
            },
        )

    with TestClient(
        create_app(
            tmp_path,
            password="test-password-long",
            assistant_transport=httpx.MockTransport(provider),
        )
    ) as browser:
        login(browser)
        p = browser.post(
            "/api/setup/assistant/providers",
            json={"name": "Local", "kind": "ollama", "model": "test"},
        ).json()
        c = browser.post(
            "/api/assistant/conversations",
            json={"provider_id": p["id"], "policy": {"name": "Stop test", "clients": ["default"]}},
        ).json()
        r = browser.post(
            "/api/assistant/jobs",
            json={"conversation_id": c["id"], "message": "Pause this torrent."},
        ).json()
        assert entered.wait(2)
        try:
            assert browser.post("/api/assistant/jobs/" + r["id"] + "/cancel", json={}).is_success
        finally:
            release.set()
        assert wait_run(browser, r["id"])["status"] == "cancelled"
        assert browser.get("/api/agents").json()["proposals"] == []


def test_changing_provider_endpoint_never_forwards_previous_key(tmp_path):
    seen = []

    def provider(request):
        seen.append(request.headers.get("authorization"))
        return httpx.Response(200, json={"data": [{"id": "new-model"}]})

    with TestClient(
        create_app(
            tmp_path,
            password="test-password-long",
            assistant_transport=httpx.MockTransport(provider),
        )
    ) as browser:
        login(browser)
        body = {
            "name": "Private model",
            "kind": "compatible",
            "url": "https://one.example/v1",
            "model": "one",
            "api_key": "sensitive-provider-key",
        }
        p = browser.post("/api/setup/assistant/providers", json=body).json()
        body.pop("api_key")
        body["url"] = "https://two.example/v1"
        assert browser.put("/api/setup/assistant/providers/" + p["id"], json=body).is_success
        assert browser.get("/api/setup/assistant/providers/" + p["id"] + "/models").json() == [
            "new-model"
        ]
        assert seen == [None]


def test_native_provider_tool_round_trips_preserve_protocol_blocks(tmp_path):
    for kind in ["openai", "anthropic", "gemini"]:
        seen = []

        def provider(request, kind=kind, seen=seen):
            body = json.loads(request.content)
            seen.append(body)
            if kind == "openai":
                assert request.url.path == "/v1/responses"
                if len(seen) == 1:
                    assert body["store"] is False
                    assert body["tools"][0]["name"] == "connection_probe"
                    output = [
                        {"type": "reasoning", "id": "reason", "summary": []},
                        {
                            "type": "function_call",
                            "call_id": "probe",
                            "name": "connection_probe",
                            "arguments": '{"value":"torrentlinker"}',
                        },
                    ]
                else:
                    assert body["input"][-1]["type"] == "function_call_output"
                    assert body["input"][-3]["type"] == "reasoning"
                    output = [
                        {
                            "type": "message",
                            "content": [{"type": "output_text", "text": "Connected."}],
                        }
                    ]
                return httpx.Response(200, json={"output": output, "usage": {"total_tokens": 7}})
            if kind == "anthropic":
                assert request.url.path == "/v1/messages"
                assert "system" in body
                if len(seen) == 1:
                    output = [
                        {
                            "type": "tool_use",
                            "id": "probe",
                            "name": "connection_probe",
                            "input": {"value": "torrentlinker"},
                        }
                    ]
                else:
                    assert body["messages"][-1]["content"][0]["type"] == "tool_result"
                    output = [{"type": "text", "text": "Connected."}]
                return httpx.Response(
                    200, json={"content": output, "usage": {"input_tokens": 3, "output_tokens": 4}}
                )
            assert request.url.path == "/v1beta/models/test:generateContent"
            schema = body["tools"][0]["functionDeclarations"][0]
            assert "parametersJsonSchema" in schema
            assert "parameters" not in schema
            if len(seen) == 1:
                parts = [
                    {
                        "functionCall": {
                            "name": "connection_probe",
                            "args": {"value": "torrentlinker"},
                        },
                        "thoughtSignature": "opaque-signature",
                    }
                ]
            else:
                assert body["contents"][-2]["parts"][0]["thoughtSignature"] == "opaque-signature"
                assert "functionResponse" in body["contents"][-1]["parts"][0]
                parts = [{"text": "Connected."}]
            return httpx.Response(
                200,
                json={
                    "candidates": [{"content": {"role": "model", "parts": parts}}],
                    "usageMetadata": {"totalTokenCount": 7},
                },
            )

        with TestClient(
            create_app(
                tmp_path / kind,
                password="test-password-long",
                assistant_transport=httpx.MockTransport(provider),
            )
        ) as browser:
            login(browser)
            p = browser.post(
                "/api/setup/assistant/providers",
                json={"name": kind, "kind": kind, "model": "test", "api_key": "test-provider-key"},
            ).json()
            result = browser.post("/api/setup/assistant/providers/" + p["id"] + "/test", json={})
            assert result.is_success, result.text
            assert result.json()["tokens"] == 14
            assert len(seen) == 2


def test_oversized_provider_response_stops_before_json_parsing(tmp_path):
    def provider(request):
        return httpx.Response(200, content=b" " * 2_100_000 + b'{"data":[]}')

    with TestClient(
        create_app(
            tmp_path,
            password="test-password-long",
            assistant_transport=httpx.MockTransport(provider),
        )
    ) as browser:
        login(browser)
        result = browser.post(
            "/api/setup/assistant/models", json={"name": "Local", "kind": "ollama", "model": "test"}
        )
        assert not result.is_success
        assert "size limit" in result.text


def test_model_free_refresh_visits_every_selected_client(tmp_path):
    from tests.test_multi_client_web import Client

    seen = []

    class RecordingClient(Client):
        def torrents(self, **kwargs):
            seen.append(self.name)
            return super().torrents(**kwargs)

    def connect(kind, host, *args):
        return RecordingClient(host)

    with TestClient(
        create_app(tmp_path, password="test-password-long", connector=connect)
    ) as browser:
        login(browser)
        browser.post(
            "/api/setup/client", json={"client": "qbittorrent", "host": "https://one.test"}
        )
        remote = browser.post(
            "/api/clients",
            json={"client": "qbittorrent", "host": "https://two.test", "name": "Remote"},
        ).json()["client_id"]
        seen.clear()
        scheduled = browser.post(
            "/api/assistant/schedules",
            json={
                "name": "Refresh both",
                "instruction": "Refresh",
                "kind": "refresh",
                "policy": {"name": "Read clients", "clients": ["default", remote]},
            },
        )
        assert scheduled.is_success, scheduled.text
        run = browser.post("/api/assistant/schedules/" + scheduled.json()["id"] + "/run").json()
        result = wait_run(browser, run["id"])
        assert result["status"] == "completed", result
        assert set(seen) == {"https://one.test", "https://two.test"}
        assert result["calls"] == 0
        assert len(result["events"]) == 2


def test_schedule_validation_rejects_bad_timezone_and_offset_time(tmp_path):
    with TestClient(create_app(tmp_path, password="test-password-long")) as browser:
        login(browser)
        body = {
            "name": "Refresh",
            "instruction": "Refresh",
            "kind": "refresh",
            "policy": {"name": "Read", "clients": ["default"]},
        }
        for invalid in [{"timezone": "Not/A_Zone"}, {"at": "09:00+02:00"}]:
            result = browser.post("/api/assistant/schedules/preview", json={**body, **invalid})
            assert result.status_code == 422, result.text


def test_public_source_links_survive_chat_but_secrets_and_announce_urls_do_not(tmp_path):
    public = "https://www.sonypictures.com/movies/gattaca"
    image = "https://images.example/gattaca.jpg"

    def provider(request):
        prompt = json.loads(request.content)["messages"][-1]["content"]
        assert public in prompt
        assert "test-secret-987" not in prompt
        assert "private-passkey" not in prompt
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "[img]" + image + "[/img] " + public,
                        }
                    }
                ]
            },
        )

    with TestClient(
        create_app(
            tmp_path,
            password="test-password-long",
            assistant_transport=httpx.MockTransport(provider),
        )
    ) as browser:
        login(browser)
        p = browser.post(
            "/api/setup/assistant/providers",
            json={
                "name": "Test",
                "kind": "compatible",
                "url": "http://localhost:1234/v1",
                "model": "test",
                "api_key": "test-secret-987",
            },
        ).json()
        c = browser.post(
            "/api/assistant/conversations",
            json={"provider_id": p["id"], "policy": {"name": "Read", "clients": ["default"]}},
        ).json()
        run = browser.post(
            "/api/assistant/jobs",
            json={
                "conversation_id": c["id"],
                "message": public + " test-secret-987 "
                "https://tracker.example/announce/private-passkey "
                "https://example.com/api?apikey=private-passkey",
            },
        ).json()
        result = wait_run(browser, run["id"])
        assert result["status"] == "completed", result
        assert public in result["messages"][-1]["content"]
        assert image in result["messages"][-1]["content"]
        assert "private-passkey" not in json.dumps(result)


def test_chat_waits_for_application_job_without_spending_polling_model_calls(tmp_path):
    from pathlib import Path

    from torrentlinker.domain import Torrent

    class Client:
        def check(self):
            return "test"

        def torrents(self, **kwargs):
            time.sleep(0.1)
            return [
                Torrent("a" * 40, "Book.epub", Path("/downloads"), size=1024, state="uploading")
            ]

    turn = 0

    def provider(request):
        nonlocal turn
        turn += 1
        if turn == 1:
            m = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "refresh",
                        "type": "function",
                        "function": {
                            "name": "propose_action",
                            "arguments": json.dumps(
                                {
                                    "request_id": "fresh",
                                    "operation": {"kind": "refresh", "client_id": "default"},
                                }
                            ),
                        },
                    }
                ],
            }
        else:
            payload = json.loads(json.loads(request.content)["messages"][-1]["content"])
            assert payload["job"]["status"] == "completed"
            m = {"role": "assistant", "content": "Refresh completed."}
        return httpx.Response(200, json={"choices": [{"message": m}]})

    with TestClient(
        create_app(
            tmp_path,
            password="test-password-long",
            connector=lambda *args: Client(),
            assistant_transport=httpx.MockTransport(provider),
        )
    ) as browser:
        login(browser)
        browser.post(
            "/api/setup/client", json={"client": "qbittorrent", "host": "http://test.local"}
        )
        p = browser.post(
            "/api/setup/assistant/providers",
            json={"name": "Local", "kind": "ollama", "model": "test"},
        ).json()
        c = browser.post(
            "/api/assistant/conversations",
            json={"provider_id": p["id"], "policy": {"name": "Refresh", "clients": ["default"]}},
        ).json()
        r = browser.post(
            "/api/assistant/jobs", json={"conversation_id": c["id"], "message": "Refresh torrents."}
        ).json()
        result = wait_run(browser, r["id"])
        assert result["status"] == "completed", result
        assert turn == 2


def test_due_task_runs_once_and_blocks_new_runs_while_approval_is_pending(tmp_path, monkeypatch):
    calls = 0

    def provider(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "p",
                        "type": "function",
                        "function": {
                            "name": "propose_action",
                            "arguments": json.dumps(
                                {
                                    "request_id": "pause",
                                    "operation": {
                                        "kind": "manage",
                                        "client_id": "default",
                                        "action": "pause",
                                        "hashes": ["a" * 40],
                                    },
                                }
                            ),
                        },
                    }
                ],
            }
        else:
            message = {"role": "assistant", "content": "Awaiting approval."}
        return httpx.Response(200, json={"choices": [{"message": message}]})

    with TestClient(
        create_app(
            tmp_path,
            password="test-password-long",
            assistant_transport=httpx.MockTransport(provider),
        )
    ) as browser:
        login(browser)
        p = browser.post(
            "/api/setup/assistant/providers",
            json={"name": "Local", "kind": "ollama", "model": "test"},
        ).json()
        task = browser.post(
            "/api/assistant/schedules",
            json={
                "name": "Scheduled pause",
                "instruction": "Pause this torrent.",
                "provider_id": p["id"],
                "policy": {"name": "Task", "clients": ["default"]},
                "frequency": "interval",
                "interval_minutes": 5,
                "enabled": True,
            },
        ).json()
        future = time.time() + 301
        with monkeypatch.context() as clock:
            clock.setattr(time, "time", lambda: future)
            for _ in range(100):
                runs = browser.get("/api/assistant/jobs").json()
                if runs:
                    break
                time.sleep(0.02)
            assert len(runs) == 1
            assert wait_run(browser, runs[0]["id"])["status"] == "awaiting_approval"
            future += 301
            time.sleep(1.1)
            assert len(browser.get("/api/assistant/jobs").json()) == 1
            assert not browser.post(
                "/api/assistant/schedules/" + task["id"] + "/run", json={}
            ).is_success
            assert calls == 2


def test_crashed_run_is_visible_after_restart_and_never_replayed(tmp_path):
    import subprocess
    import sys

    code = """
import os, sys, time, threading
from pathlib import Path
import httpx
from fastapi.testclient import TestClient
from torrentlinker.web.app import create_app

entered = threading.Event()


def provider(request):
    entered.set()
    time.sleep(60)
    return httpx.Response(500)


with TestClient(
    create_app(
        Path(sys.argv[1]),
        password="test-password-long",
        assistant_transport=httpx.MockTransport(provider),
    )
) as b:
    b.headers["X-TorrentLinker"] = "1"
    b.post("/api/login", json={"password": "test-password-long"})
    p = b.post(
        "/api/setup/assistant/providers", json={"name": "Local", "kind": "ollama", "model": "test"}
    ).json()
    c = b.post(
        "/api/assistant/conversations",
        json={"provider_id": p["id"], "policy": {"name": "Crash test", "clients": ["default"]}},
    ).json()
    b.post(
        "/api/assistant/jobs", json={"conversation_id": c["id"], "message": "Test interruption."}
    )
    assert entered.wait(3)
    os._exit(0)
"""
    subprocess.run([sys.executable, "-c", code, str(tmp_path)], check=True, timeout=10)
    with TestClient(create_app(tmp_path, password="test-password-long")) as browser:
        login(browser)
        runs = browser.get("/api/assistant/jobs").json()
        assert len(runs) == 1
        assert runs[0]["status"] == "interrupted"
        assert "nothing was replayed" in runs[0]["error"]
