"""Failed calls stay visible and the model receives evidence for safe corrections."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from tests.test_assistant import generation_transport, login, wait_run
from torrentlinker.store import CatalogueRow
from torrentlinker.web.app import create_app


@pytest.mark.parametrize(
    "invalid",
    [
        {"criteria": {"count": 0}},
        {"selection": {"count": 1}},
        {"criteria": {"count": 1}, "selection": {"count": 1}},
    ],
)
def test_mcp_validation_failure_is_failed_then_model_can_correct_arguments(tmp_path, invalid):
    turns = 0
    errors = []

    def provider(request):
        nonlocal turns
        turns += 1
        payload = json.loads(request.content)
        if turns == 2:
            result = json.loads(
                next(m["content"] for m in reversed(payload["messages"]) if m["role"] == "tool")
            )
            errors.append(result)
            assert result["error"]
            assert "uncertain" in result["correction_guidance"]
        if turns < 3:
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": str(turns),
                        "type": "function",
                        "function": {
                            "name": "select_catalogue",
                            "arguments": json.dumps(
                                {
                                    "request_id": f"attempt-{turns}",
                                    "client_id": "default",
                                    **(invalid if turns == 1 else {"criteria": {"count": 1}}),
                                }
                            ),
                        },
                    }
                ],
            }
        else:
            message = {
                "role": "assistant",
                "content": "Corrected the invalid count and selected one item.",
            }
        return httpx.Response(200, json={"choices": [{"message": message}]})

    app = create_app(
        tmp_path, password="test-password-long", assistant_transport=generation_transport(provider)
    )
    with TestClient(app) as browser:
        login(browser)
        app.state.agent_service.setup.store.save_catalogue(
            [CatalogueRow("a" * 40, "Film", 4, 5, 2030, "https://test.invalid/file", "", 1)]
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
            json={"provider_id": model, "policy": {"name": "Read", "clients": ["default"]}},
        ).json()["id"]
        submitted = browser.post(
            "/api/assistant/jobs", json={"conversation_id": chat, "message": "Select a film."}
        ).json()["id"]
        result = wait_run(browser, submitted)
        assert result["status"] == "completed", result["error"]
        assert [e["status"] for e in result["events"]] == ["failed", "finished"]
        assert result["events"][0]["error"]
        assert result["events"][1]["result"]["job"]["result"]["selected_count"] == 1
        assert len(errors) == 1 and turns == 3
        assert len(errors[0]["correction_guidance"]) < 1200


def test_failed_read_job_is_failed_and_model_can_retry_after_observing_error(tmp_path):
    from tests.test_agent_selection import SelectionClient, book

    turns = 0

    class RecoveringClient(SelectionClient):
        def __init__(self):
            super().__init__([book(1, 4)])
            self.reads = 0

        def torrents(self, **kwargs):
            self.reads += 1
            if self.reads == 1:
                raise ValueError("Temporary client read failure")
            return super().torrents(**kwargs)

    client = RecoveringClient()

    def provider(request):
        nonlocal turns
        turns += 1
        payload = json.loads(request.content)
        if turns == 2:
            result = json.loads(
                next(m["content"] for m in reversed(payload["messages"]) if m["role"] == "tool")
            )
            assert result["job"]["status"] == "failed"
            assert "Temporary client read failure" in result["error"]
            assert "never bypass" in result["correction_guidance"]
        if turns < 3:
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": str(turns),
                        "type": "function",
                        "function": {
                            "name": "select_torrents",
                            "arguments": json.dumps(
                                {
                                    "request_id": f"read-{turns}",
                                    "client_id": "default",
                                    "criteria": {"category": "Ebook", "count": 1},
                                }
                            ),
                        },
                    }
                ],
            }
        else:
            message = {
                "role": "assistant",
                "content": "Client read recovered; one torrent selected.",
            }
        return httpx.Response(200, json={"choices": [{"message": message}]})

    app = create_app(
        tmp_path,
        password="test-password-long",
        connector=lambda *args: client,
        assistant_transport=generation_transport(provider),
    )
    with TestClient(app) as browser:
        login(browser)
        assert browser.post(
            "/api/setup/client", json={"client": "deluge", "host": "https://box.example"}
        ).is_success
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
            json={"provider_id": model, "policy": {"name": "Read", "clients": ["default"]}},
        ).json()["id"]
        submitted = browser.post(
            "/api/assistant/jobs", json={"conversation_id": chat, "message": "Read ebooks."}
        ).json()["id"]
        result = wait_run(browser, submitted)
        assert result["status"] == "completed", result["error"]
        assert [e["status"] for e in result["events"]] == ["failed", "finished"]
        assert result["events"][1]["result"]["job"]["status"] == "completed"
        assert turns == 3
