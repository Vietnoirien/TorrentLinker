"""Tool chronology is observable through the public Assistant job API."""

import httpx
from fastapi.testclient import TestClient

from tests.test_assistant import generation_transport, login, wait_run
from torrentlinker.web.app import create_app


def test_model_commentary_and_silent_tool_calls_keep_chronological_anchors(tmp_path):
    turns = 0

    def provider(request):
        nonlocal turns
        turns += 1
        if turns < 3:
            message = {
                "role": "assistant",
                "content": "I will inspect the allowed clients." if turns == 1 else None,
                "tool_calls": [
                    {
                        "id": str(turns),
                        "type": "function",
                        "function": {"name": "overview", "arguments": "{}"},
                    }
                ],
            }
        else:
            message = {"role": "assistant", "content": "Inspection complete."}
        return httpx.Response(
            200, json={"choices": [{"message": message}], "usage": {"total_tokens": 5}}
        )

    with TestClient(
        create_app(
            tmp_path,
            password="test-password-long",
            assistant_transport=generation_transport(provider),
        )
    ) as browser:
        login(browser)
        model = browser.post(
            "/api/setup/assistant/providers",
            json={"name": "Local", "kind": "ollama", "model": "test"},
        ).json()["id"]
        chat = browser.post(
            "/api/assistant/conversations",
            json={"provider_id": model, "policy": {"name": "Read", "clients": ["default"]}},
        ).json()["id"]
        submitted = browser.post(
            "/api/assistant/jobs",
            json={"conversation_id": chat, "message": "Inspect allowed clients."},
        ).json()["id"]
        result = wait_run(browser, submitted)
        assert result["status"] == "completed", result
        assert result["messages"][1]["content"] == "I will inspect the allowed clients."
        assert result["messages"][1]["phase"] == "commentary"
        assert result["messages"][1]["model_turn"] == 1
        assert result["messages"][2]["phase"] == "final"
        assert [event["after_message_index"] for event in result["events"]] == [1, 1]
        assert [event["model_turn"] for event in result["events"]] == [1, 2]
        assert all(
            event["description"]["en"] == "Inspect permissions and Torrent Clients."
            for event in result["events"]
        )
        assert all(event["description"]["fr"] for event in result["events"])
