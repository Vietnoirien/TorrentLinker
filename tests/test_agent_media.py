"""MCP media tools act on server selections and their own attached player."""

import asyncio

from fastapi.testclient import TestClient

from tests.test_media_api import login, media_app, scan
from torrentlinker.agent.server import ACTOR, make_server


def invoke(app, actor, tool_name, **arguments):
    server, _ = make_server(app.state.agent_service)
    token = ACTOR.set(actor)
    try:
        result = asyncio.run(server.call_tool(tool_name, arguments))
        return result.structured_content
    finally:
        ACTOR.reset(token)


def test_mcp_search_and_controls_target_only_bound_player(tmp_path):
    app, _ = media_app(tmp_path)
    with TestClient(app) as browser:
        login(browser)
        scan(browser)
        first = browser.post("/api/media/sessions", json={"client_id": "default"}).json()
        second = browser.post("/api/media/sessions", json={"client_id": "default"}).json()
        conversation = browser.post(
            "/api/media/sessions/" + first["id"] + "/chat", json={"token": first["token"]}
        ).json()["conversation_id"]
        actor = app.state.assistant.conversation(conversation)[1]
        selected = invoke(app, actor, "search_media", client_id="default", kind="music")
        assert selected["count"] == 1
        assert "id" not in selected["items"][0]
        played = invoke(app, actor, "play_media", selection_id=selected["selection_id"], item=1)
        assert played["queued"] is True
        own = browser.post(
            "/api/media/sessions/" + first["id"], json={"token": first["token"]}
        ).json()
        other = browser.post(
            "/api/media/sessions/" + second["id"], json={"token": second["token"]}
        ).json()
        assert own["commands"][0]["action"] == "play"
        assert other["commands"] == []
        outsider = app.state.agent_service.access.create(
            app.state.assistant.conversation(conversation)[0].policy, internal=True
        )["id"]
        assert "error" in invoke(app, outsider, "control_media_player", action="pause")
        # Even the old actor loses control when the owner attaches that discussion elsewhere.
        browser.post(
            "/api/media/sessions/" + second["id"] + "/chat",
            json={"token": second["token"], "conversation_id": conversation},
        )
        invoke(app, actor, "control_media_player", action="pause")
        assert (
            browser.post(
                "/api/media/sessions/" + first["id"], json={"token": first["token"]}
            ).json()["commands"][-1]["action"]
            == "play"
        )
        assert (
            browser.post(
                "/api/media/sessions/" + second["id"], json={"token": second["token"]}
            ).json()["commands"][-1]["action"]
            == "pause"
        )


def test_queue_edits_and_playlist_saves_include_unacknowledged_prior_edits(tmp_path):
    app, _ = media_app(tmp_path)
    with TestClient(app) as browser:
        login(browser)
        scan(browser)
        player = browser.post("/api/media/sessions", json={"client_id": "default"}).json()
        discussion = browser.post(
            "/api/media/sessions/" + player["id"] + "/chat", json={"token": player["token"]}
        ).json()["conversation_id"]
        actor = app.state.assistant.conversation(discussion)[1]
        selection = invoke(app, actor, "search_media", client_id="default", kind="music")[
            "selection_id"
        ]
        invoke(app, actor, "edit_playback_queue", action="replace", selection_id=selection)
        invoke(app, actor, "edit_playback_queue", action="append", selection_id=selection)
        invoke(app, actor, "edit_playback_queue", action="append", selection_id=selection)
        saved = invoke(app, actor, "save_media_playlist", name="Pending songs")
        assert saved["count"] == 3
        queue = invoke(app, actor, "read_playback_queue")
        assert queue["count"] == 3
        response = browser.post(
            "/api/media/sessions/" + player["id"], json={"token": player["token"]}
        ).json()
        assert len(response["commands"][-1]["media_ids"]) == 3
        # Navigation is resolved by the player, including its shuffle mode. A queue
        # edit must not reset it to the last reported index before acknowledgment.
        invoke(app, actor, "control_media_player", action="next")
        waiting = invoke(app, actor, "edit_playback_queue", action="append", selection_id=selection)
        assert "acknowledg" in waiting.get("error", "").lower(), waiting
        pending = browser.post(
            "/api/media/sessions/" + player["id"], json={"token": player["token"]}
        ).json()["commands"]
        ids = response["commands"][-1]["media_ids"]
        browser.post(
            "/api/media/sessions/" + player["id"],
            json={
                "token": player["token"],
                "report": {
                    "queue": ids,
                    "current_id": ids[1],
                    "index": 1,
                    "command_ack": pending[-1]["sequence"],
                },
            },
        )
        assert invoke(app, actor, "edit_playback_queue", action="append", selection_id=selection)[
            "queued"
        ]
        appended = browser.post(
            "/api/media/sessions/" + player["id"], json={"token": player["token"]}
        ).json()["commands"][-1]
        assert appended["index"] == 1
        assert len(appended["media_ids"]) == 4


def test_media_controls_stop_after_permission_revocation_and_player_expiry(tmp_path, monkeypatch):
    import time

    app, _ = media_app(tmp_path)
    with TestClient(app) as browser:
        login(browser)
        browser.post(
            "/api/setup/assistant/providers",
            json={
                "name": "Test",
                "kind": "compatible",
                "url": "http://localhost:1234/v1",
                "model": "test",
            },
        )
        player = browser.post("/api/media/sessions", json={"client_id": "default"}).json()
        discussion = browser.post(
            "/api/media/sessions/" + player["id"] + "/chat", json={"token": player["token"]}
        ).json()["conversation_id"]
        body, actor = app.state.assistant.conversation(discussion)
        assert invoke(app, actor, "control_media_player", action="pause")["queued"]
        changed = body.model_dump()
        changed["policy"]["permissions"] = []
        response = browser.put("/api/assistant/conversations/" + discussion, json=changed)
        assert response.status_code == 200
        assert "error" in invoke(app, actor, "control_media_player", action="pause")
        changed["policy"]["permissions"] = ["media"]
        browser.put("/api/assistant/conversations/" + discussion, json=changed)
        now = time.time()
        monkeypatch.setattr("torrentlinker.media.time.time", lambda: now + 100)
        result = invoke(app, actor, "control_media_player", action="pause")
        assert "offline" in result["error"]
