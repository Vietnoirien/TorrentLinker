"""The model receives a display receipt while the chat retains complete card data."""

import json
from types import SimpleNamespace

import httpx
from fastapi.testclient import TestClient

from tests.test_assistant import generation_transport, login, wait_run
from torrentlinker.assistant.context import model_receipt
from torrentlinker.store import CatalogueRow
from torrentlinker.web.app import create_app


def test_presentation_receipt_keeps_cards_in_history_without_inviting_prose_duplicates(tmp_path):
    turns = 0
    display_receipts = []

    def provider(request):
        nonlocal turns
        turns += 1
        payload = json.loads(request.content)
        receipt = (
            json.loads(
                next(m["content"] for m in reversed(payload["messages"]) if m["role"] == "tool")
            )
            if turns > 1
            else {}
        )
        if turns == 1:
            name = "select_catalogue"
            arguments = {"request_id": "select", "client_id": "default", "criteria": {"count": 1}}
        elif turns == 2:
            name = "present_selection"
            arguments = {"request_id": "show", "selection_id": receipt["job_id"]}
        else:
            display_receipts.append(receipt)
            assert receipt["displayed_in_chat"] is True
            assert receipt["count"] == 1 and receipt["presentation_id"]
            assert "items" not in receipt
            assert "do not repeat" in receipt["response_guidance"]
            message = {
                "role": "assistant",
                "content": "The selection is ready. Open a card for details.",
            }
            return httpx.Response(200, json={"choices": [{"message": message}]})
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
                                    "function": {"name": name, "arguments": json.dumps(arguments)},
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
        setup._indexer = SimpleNamespace(
            url="https://test.invalid",
            is_c411=False,
            redact=lambda value: value,
            unredact=lambda value: value,
        )
        setup.store.save_catalogue(
            [CatalogueRow("a" * 40, "Demo Film", 4000, 5, 2030, "https://test.invalid/file", "", 1)]
        )
        model = browser.post(
            "/api/setup/assistant/providers",
            json={
                "name": "Fake",
                "kind": "compatible",
                "url": "http://model.invalid/v1",
                "model": "test",
            },
        ).json()["id"]
        chat = browser.post(
            "/api/assistant/conversations",
            json={
                "provider_id": model,
                "policy": {"name": "Read", "clients": ["default"]},
            },
        ).json()["id"]
        submitted = browser.post(
            "/api/assistant/jobs",
            json={
                "conversation_id": chat,
                "message": "Show one film as a card.",
            },
        ).json()["id"]
        result = wait_run(browser, submitted)
        assert result["status"] == "completed", result["error"]
        event = result["events"][-1]
        assert event["result"]["items"][0]["title"] == "Demo Film"
        identifier = display_receipts[0]["presentation_id"]
        assert browser.get(f"/api/assistant/presentations/{identifier}").json()["items"]
        assert len(display_receipts) == 1


def test_plain_reads_and_failed_presentations_retain_their_details():
    page = {
        "presentation_id": "saved",
        "count": 1,
        "items": [{"title": "Film", "image_url": "url"}],
    }
    assert model_receipt(page, "run", 0) == page
    failed = {**page, "displayed_in_chat": True, "error": "Presentation failed"}
    assert model_receipt(failed, "run", 0) == failed
