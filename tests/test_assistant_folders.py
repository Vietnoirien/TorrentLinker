import json

import httpx
from fastapi.testclient import TestClient

from tests.test_assistant import generation_transport, login, wait_run
from torrentlinker.web.app import create_app


def create_chat(browser, provider):
    return browser.post(
        "/api/assistant/conversations",
        json={
            "name": "Research",
            "provider_id": provider,
            "policy": {"name": "Read", "clients": ["default"]},
        },
    ).json()


def test_owner_folder_move_persists_and_regular_settings_edits_preserve_it(tmp_path):
    def app():
        return create_app(tmp_path, password="test-password-long")

    with TestClient(app()) as browser:
        login(browser)
        provider = browser.post(
            "/api/setup/assistant/providers",
            json={"name": "Local", "kind": "ollama", "model": "test"},
        ).json()["id"]
        chat = create_chat(browser, provider)
        assert chat["folder"] == ""
        moved = browser.put(
            f"/api/assistant/conversations/{chat['id']}/folder", json={"folder": "My uploads"}
        )
        assert moved.is_success, moved.text
        assert moved.json()["folder_source"] == "manual"
        edited = browser.put(
            f"/api/assistant/conversations/{chat['id']}",
            json={k: v for k, v in chat.items() if k not in {"id", "folder", "folder_source"}},
        )
        assert edited.is_success, edited.text
        assert edited.json()["folder"] == "My uploads"
    with TestClient(app()) as browser:
        login(browser)
        restored = browser.get("/api/assistant/conversations").json()[0]
        assert restored["folder"] == "My uploads"
        assert restored["folder_source"] == "manual"
        unlocked = browser.put(
            f"/api/assistant/conversations/{chat['id']}/folder",
            json={"folder": "uploads", "automatic": True},
        )
        assert unlocked.json()["folder_source"] == "auto"
        assert (
            browser.put(
                f"/api/assistant/conversations/{chat['id']}/folder", json={"folder": "x" * 81}
            ).status_code
            == 422
        )


def test_model_can_classify_only_current_chat_and_cannot_override_owner(tmp_path):
    turns = 0
    foreign_id = ""

    def provider(request):
        nonlocal turns
        turns += 1
        if turns in {1, 3, 5}:
            args = {"folder": "film_research"}
            if turns == 3:
                args["conversation_id"] = foreign_id
            message = {
                "role": "assistant",
                "content": "I will organize this discussion.",
                "tool_calls": [
                    {
                        "id": str(turns),
                        "type": "function",
                        "function": {
                            "name": "classify_conversation",
                            "arguments": json.dumps(args),
                        },
                    }
                ],
            }
        else:
            message = {"role": "assistant", "content": "Done."}
        return httpx.Response(200, json={"choices": [{"message": message}]})

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
        current = create_chat(browser, model)
        foreign = create_chat(browser, model)
        foreign_id = foreign["id"]

        def run():
            identifier = browser.post(
                "/api/assistant/jobs",
                json={"conversation_id": current["id"], "message": "Research a film."},
            ).json()["id"]
            result = wait_run(browser, identifier)
            assert result["status"] == "completed", result
            return result

        first = run()
        assert first["events"][0]["result"]["folder"] == "film_research"
        run()
        rows = {row["id"]: row for row in browser.get("/api/assistant/conversations").json()}
        assert rows[foreign_id]["folder"] == ""
        browser.put(
            f"/api/assistant/conversations/{current['id']}/folder", json={"folder": "uploads"}
        )
        last = run()
        assert last["events"][0]["result"]["changed"] is False
        assert last["events"][0]["result"]["folder"] == "uploads"
