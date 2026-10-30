"""Explicit local-model sampling survives saving, restart and protocol dispatch."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from tests.test_assistant import generation_transport, login, wait_run
from torrentlinker.web.app import create_app


@pytest.mark.parametrize("kind", ["compatible", "ollama", "lmstudio"])
def test_saved_sampling_override_reaches_model_and_can_return_to_server_default(tmp_path, kind):
    requests = []

    def provider(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            200, json={"choices": [{"message": {"role": "assistant", "content": "Written."}}]}
        )

    def app():
        return create_app(
            tmp_path,
            password="test-password-long",
            assistant_transport=generation_transport(provider),
        )

    body = {
        "name": "Local",
        "kind": kind,
        "url": "http://model.invalid/v1",
        "model": "test",
        "temperature": 0,
    }
    with TestClient(app()) as browser:
        login(browser)
        saved = browser.post("/api/setup/assistant/providers", json=body)
        assert saved.is_success, saved.text
        identifier = saved.json()["id"]
    with TestClient(app()) as browser:
        login(browser)
        assert browser.get("/api/setup/assistant").json()["providers"][0]["temperature"] == 0
        chat = browser.post(
            "/api/assistant/conversations",
            json={"provider_id": identifier, "policy": {"name": "Writing", "clients": ["default"]}},
        ).json()["id"]
        for temperature in (0, None):
            if temperature is None:
                assert browser.put(
                    f"/api/setup/assistant/providers/{identifier}",
                    json={**body, "temperature": None},
                ).is_success
            run = browser.post(
                "/api/assistant/jobs",
                json={"conversation_id": chat, "message": "Write a short sentence. No tools."},
            ).json()["id"]
            assert wait_run(browser, run)["status"] == "completed"
            if temperature is None:
                assert "temperature" not in requests[-1]
            else:
                assert requests[-1]["temperature"] == 0
        assert browser.get("/api/setup/assistant").json()["providers"][0]["temperature"] is None


@pytest.mark.parametrize(
    "fields", [{"temperature": -0.1}, {"temperature": 2.1}, {"kind": "openai", "temperature": 0}]
)
def test_invalid_sampling_configuration_is_rejected(tmp_path, fields):
    with TestClient(create_app(tmp_path, password="test-password-long")) as browser:
        login(browser)
        response = browser.post(
            "/api/setup/assistant/providers",
            json={"name": "Local", "kind": "ollama", "model": "test", **fields},
        )
        assert response.status_code == 422
        assert browser.get("/api/setup/assistant").json()["providers"] == []


def test_sampling_changes_invalidate_assessment_and_inflight_results(tmp_path, monkeypatch):
    from torrentlinker.assistant import capabilities
    from torrentlinker.assistant.providers import Provider

    app = create_app(
        tmp_path,
        password="test-password-long",
        assistant_transport=httpx.MockTransport(lambda request: httpx.Response(404)),
    )
    with TestClient(app):
        service = app.state.assistant
        body = Provider(name="Local", kind="ollama", model="test", temperature=0)
        identifier = service.save_provider(body)["id"]
        monkeypatch.setattr(capabilities, "assess", lambda *args: {"checks": {}})
        service.test_provider(identifier)
        assert service.provider_assessment(identifier) is not None
        updated = body.model_copy(update={"temperature": 0.5})
        service.save_provider(updated, identifier)
        assert service.provider_assessment(identifier) is None

        def changing_assessment(*args):
            service.save_provider(body, identifier)
            return {"checks": {}}

        monkeypatch.setattr(capabilities, "assess", changing_assessment)
        with pytest.raises(ValueError, match="changed during assessment"):
            service.test_provider(identifier)
        assert service.provider_assessment(identifier) is None


def test_sampling_cannot_change_while_owner_interaction_is_pending(tmp_path):
    from tests.test_assistant_waits import response, tool

    app = create_app(
        tmp_path,
        password="test-password-long",
        assistant_transport=generation_transport(
            lambda request: response(
                [tool("ask_user", {"question": "Which folder?", "options": []})]
            )
        ),
    )
    with TestClient(app) as browser:
        login(browser)
        body = {"name": "Local", "kind": "ollama", "model": "test", "temperature": 0}
        identifier = browser.post("/api/setup/assistant/providers", json=body).json()["id"]
        chat = browser.post(
            "/api/assistant/conversations",
            json={"provider_id": identifier, "policy": {"name": "Test", "clients": ["default"]}},
        ).json()["id"]
        run = browser.post(
            "/api/assistant/jobs", json={"conversation_id": chat, "message": "Help me choose."}
        ).json()["id"]
        assert wait_run(browser, run)["status"] == "awaiting_user"
        rejected = browser.put(
            f"/api/setup/assistant/providers/{identifier}", json={**body, "temperature": 0.5}
        )
        assert rejected.status_code == 400
        assert "Stop active discussions" in rejected.text
        assert app.state.assistant.provider(identifier).temperature == 0
