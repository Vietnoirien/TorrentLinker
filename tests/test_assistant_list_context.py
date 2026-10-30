"""Authoritative list state reaches the model through its actual provider request."""

import json

import httpx
from fastapi.testclient import TestClient

from tests.test_assistant import generation_transport, login, wait_run
from torrentlinker.downloads import IndexerCategory
from torrentlinker.store import CatalogueRow
from torrentlinker.web.app import create_app


def test_next_turn_receipts_are_bounded_valid_json_with_latest_authoritative_list_state(tmp_path):
    turns = 0
    list_id = ""
    captured = []

    def provider(request):
        nonlocal turns, list_id
        turns += 1
        payload = json.loads(request.content)
        if turns == 1:
            name = "select_catalogue"
            args = {"request_id": "many-films", "client_id": "default", "criteria": {"count": 1000}}
        elif turns == 2:
            receipt = json.loads(
                next(m["content"] for m in reversed(payload["messages"]) if m["role"] == "tool")
            )
            name = "create_torrent_list"
            args = {
                "request_id": "save-many",
                "client_id": "default",
                "name": "Many films",
                "selection_id": receipt["job_id"],
            }
        elif turns == 3:
            receipt = json.loads(
                next(m["content"] for m in reversed(payload["messages"]) if m["role"] == "tool")
            )
            list_id = receipt["id"]
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": {"role": "assistant", "content": "The list has 999999 items."}}
                    ]
                },
            )
        else:
            captured.extend(payload["messages"])
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": "The saved list has 1000 items.",
                            }
                        }
                    ]
                },
            )
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
                                    "id": str(turns),
                                    "type": "function",
                                    "function": {"name": name, "arguments": json.dumps(args)},
                                }
                            ],
                        }
                    }
                ]
            },
        )

    app = create_app(
        tmp_path, password="test-password-long", assistant_transport=generation_transport(provider)
    )
    with TestClient(app) as browser:
        login(browser)
        setup = app.state.agent_service.setup
        setup.settings.indexer_categories = {2030: IndexerCategory("Films")}
        setup.store.save_catalogue(
            [
                CatalogueRow(
                    f"{i:040x}",
                    f"Film {i} " + "Large row marker " * 80,
                    i,
                    5,
                    2030,
                    f"https://test.invalid/{i}",
                    "",
                    1,
                )
                for i in range(1, 1001)
            ]
        )
        model = browser.post(
            "/api/setup/assistant/providers",
            json={
                "name": "Fake",
                "kind": "compatible",
                "url": "http://model.invalid/v1",
                "model": "test",
                "context_window": 262144,
            },
        ).json()["id"]
        chat = browser.post(
            "/api/assistant/conversations",
            json={"provider_id": model, "policy": {"name": "Read", "clients": ["default"]}},
        ).json()["id"]
        first = browser.post(
            "/api/assistant/jobs", json={"conversation_id": chat, "message": "Save 1000 films."}
        ).json()["id"]
        result = wait_run(browser, first)
        assert result["status"] == "completed", (result["error"], result["events"])
        second = browser.post(
            "/api/assistant/jobs",
            json={"conversation_id": chat, "message": "What is the actual saved count?"},
        ).json()["id"]
        assert wait_run(browser, second)["status"] == "completed"
        receipts = next(
            m["content"]
            for m in captured
            if m.get("content", "").startswith("Prior action receipts")
        )
        encoded = receipts.split(": ", 1)[1]
        assert len(encoded.encode()) <= 24000
        parsed = json.loads(encoded)
        assert parsed[-1]["result"]["revision"] == 1
        assert parsed[-1]["result"]["count"] == 1000
        assert "Large row marker" not in encoded
        inventory = next(
            m["content"]
            for m in captured
            if m.get("content", "").startswith("Current saved torrent lists")
        )
        state = json.loads(inventory.split(": ", 1)[1])
        assert state["clients"]["default"]["lists"][0]["id"] == list_id
        assert state["clients"]["default"]["lists"][0]["count"] == 1000
        assert state["clients"]["default"]["lists"][0]["total_size_bytes"] == 500500


def test_context_recovery_reduces_authoritative_list_inventory(tmp_path):
    inventories = []

    def provider(request):
        payload = json.loads(request.content)
        message = next(
            m["content"]
            for m in payload["messages"]
            if m.get("content", "").startswith("Current saved torrent lists")
        )
        encoded = message.split(": ", 1)[1]
        inventories.append(encoded)
        if len(inventories) < 3:
            return httpx.Response(400, json={"error": {"code": "context_length_exceeded"}})
        return httpx.Response(
            200, json={"choices": [{"message": {"role": "assistant", "content": "Recovered."}}]}
        )

    app = create_app(
        tmp_path, password="test-password-long", assistant_transport=generation_transport(provider)
    )
    with TestClient(app) as browser:
        login(browser)
        model = browser.post(
            "/api/setup/assistant/providers",
            json={
                "name": "Fake",
                "kind": "compatible",
                "url": "http://model.invalid/v1",
                "model": "test",
                "context_window": 32768,
            },
        ).json()["id"]
        chat = browser.post(
            "/api/assistant/conversations",
            json={"provider_id": model, "policy": {"name": "Read", "clients": ["default"]}},
        ).json()["id"]
        _, actor = app.state.assistant.conversation(chat)
        for number in range(20):
            app.state.agent_service.torrent_lists.create(
                actor, f"list-{number}", "default", f"{number}" + "é" * 117
            )
        submitted = browser.post(
            "/api/assistant/jobs", json={"conversation_id": chat, "message": "Read current state."}
        ).json()["id"]
        result = wait_run(browser, submitted)
        assert result["status"] == "completed", result["error"]
        assert len(inventories) == 3
        assert len(inventories[1].encode()) < len(inventories[0].encode())
        assert len(inventories[2].encode()) < len(inventories[1].encode())
        assert len(inventories[2].encode()) < len(inventories[0].encode()) // 2
        assert r"\u00e9" not in inventories[0]
        state = json.loads(inventories[2])
        assert state["clients"]["default"]["has_more"]


def test_context_recovery_accepts_valid_json_encoded_operation_history(tmp_path):
    turns = 0

    def provider(request):
        nonlocal turns
        turns += 1
        if turns == 1:
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "one",
                        "type": "function",
                        "function": {
                            "name": "propose_action",
                            "arguments": json.dumps(
                                {
                                    "request_id": "encoded-read",
                                    "operation": json.dumps(
                                        {"kind": "select-catalogue", "client_id": "default"}
                                    ),
                                }
                            ),
                        },
                    }
                ],
            }
        elif turns == 3:
            return httpx.Response(400, json={"error": {"code": "context_length_exceeded"}})
        else:
            message = {"role": "assistant", "content": "Read completed."}
        return httpx.Response(200, json={"choices": [{"message": message}]})

    app = create_app(
        tmp_path, password="test-password-long", assistant_transport=generation_transport(provider)
    )
    with TestClient(app) as browser:
        login(browser)
        model = browser.post(
            "/api/setup/assistant/providers",
            json={
                "name": "Fake",
                "kind": "compatible",
                "url": "http://model.invalid/v1",
                "model": "test",
                # Exercise the explicit provider rejection, not proactive prompt-size compaction.
                "context_window": 131072,
            },
        ).json()["id"]
        chat = browser.post(
            "/api/assistant/conversations",
            json={"provider_id": model, "policy": {"name": "Read", "clients": ["default"]}},
        ).json()["id"]
        first = browser.post(
            "/api/assistant/jobs",
            json={"conversation_id": chat, "message": "Read cached catalogue."},
        ).json()["id"]
        result = wait_run(browser, first)
        assert result["status"] == "completed", result["error"]
        assert result["events"][0]["result"]["job"]["status"] == "completed"
        second = browser.post(
            "/api/assistant/jobs",
            json={"conversation_id": chat, "message": "Continue after compaction."},
        ).json()["id"]
        result = wait_run(browser, second)
        assert result["status"] == "completed", result["error"]
        assert result["compactions"] == 1 and turns == 4
