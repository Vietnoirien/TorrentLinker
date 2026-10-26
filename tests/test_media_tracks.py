"""Track choices use the attached player's inventory and acknowledged source."""

import pytest
from fastapi.testclient import TestClient

from tests.test_agent_media import invoke
from tests.test_media_api import login, media_app, scan


@pytest.fixture
def attached(tmp_path):
    app, _ = media_app(tmp_path)
    with TestClient(app) as browser:
        login(browser)
        scan(browser)
        player = browser.post("/api/media/sessions", json={"client_id": "default"}).json()
        other = browser.post("/api/media/sessions", json={"client_id": "default"}).json()
        thread = browser.post(
            "/api/media/sessions/" + player["id"] + "/chat", json={"token": player["token"]}
        ).json()["conversation_id"]
        actor = app.state.assistant.conversation(thread)[1]
        selection = invoke(app, actor, "search_media", client_id="default", kind="music")[
            "selection_id"
        ]
        item = browser.get("/api/media?client_id=default").json()["rows"][0]["id"]
        yield app, browser, player, other, actor, selection, item


def inventory(item, token="source-one"):
    return {
        "media_id": item,
        "source_token": token,
        "ready": True,
        "audio_supported": True,
        "subtitle_supported": True,
        "audio": [
            {"id": "audio:0", "label": "French VFF", "language": "fr", "selected": True},
            {"id": "audio:1", "label": "English", "language": "en", "selected": False},
        ],
        "subtitles": [
            {"id": "embedded:0", "label": "French full", "language": "fr", "selected": False}
        ],
    }


def report(browser, player, item, tracks, ack=0, result=None):
    body = {
        "current_id": item,
        "queue": [item],
        "index": 0,
        "paused": True,
        "command_ack": ack,
        "track_state": tracks,
    }
    if result is not None:
        body["track_result"] = result
    response = browser.post(
        "/api/media/sessions/" + player["id"], json={"token": player["token"], "report": body}
    )
    assert response.is_success, response.text
    return response.json()


def test_mcp_switch_is_exact_and_stale_or_unsupported_tracks_are_rejected(attached):
    app, browser, player, other, actor, _, item = attached
    tracks = inventory(item)
    report(browser, player, item, tracks)
    listed = invoke(app, actor, "read_media_tracks")
    assert listed["source_token"] == "source-one"
    assert listed["audio"][1]["language"] == "en"
    chosen = invoke(
        app,
        actor,
        "select_media_track",
        kind="audio",
        track_id="audio:1",
        source_token="source-one",
    )
    assert chosen["queued"]
    commands = report(browser, player, item, tracks)["commands"]
    command = commands[-1]
    assert command["action"] == "select_track"
    assert command["media_id"] == item
    assert command["track_id"] == "audio:1"
    assert "error" in invoke(
        app,
        actor,
        "select_media_track",
        kind="audio",
        track_id="audio:99",
        source_token="source-one",
    )
    assert "error" in invoke(
        app, actor, "select_media_track", kind="audio", track_id="audio:1", source_token="old"
    )
    tracks["audio_supported"] = False
    tracks["audio"] = []
    report(browser, player, item, tracks, command["sequence"])
    assert "error" in invoke(
        app,
        actor,
        "select_media_track",
        kind="audio",
        track_id="audio:1",
        source_token="source-one",
    )
    assert (
        browser.post("/api/media/sessions/" + other["id"], json={"token": other["token"]}).json()[
            "commands"
        ]
        == []
    )


def test_requested_languages_are_applied_before_playback_resumes(attached):
    app, browser, player, _, actor, selection, item = attached
    started = invoke(
        app,
        actor,
        "play_media",
        selection_id=selection,
        audio_language="en",
        subtitle_language="fr",
    )
    assert started["queued"]
    snapshot = browser.post(
        "/api/media/sessions/" + player["id"], json={"token": player["token"]}
    ).json()
    load = snapshot["commands"][0]
    assert load["start_paused"] is True
    tracks = inventory(item, load["load_token"])
    response = report(browser, player, item, tracks, load["sequence"])
    audio = response["commands"][0]
    assert audio["track_id"] == "audio:1"
    tracks["audio"][0]["selected"] = False
    tracks["audio"][1]["selected"] = True
    response = report(
        browser,
        player,
        item,
        tracks,
        audio["sequence"],
        {"sequence": audio["sequence"], "applied": True, "error": ""},
    )
    subtitle = response["commands"][0]
    assert subtitle["track_id"] == "embedded:0"
    tracks["subtitles"][0]["selected"] = True
    response = report(
        browser,
        player,
        item,
        tracks,
        subtitle["sequence"],
        {"sequence": subtitle["sequence"], "applied": True, "error": ""},
    )
    resume = response["commands"][0]
    assert resume["action"] == "play" and "media_ids" not in resume
    assert resume["source_token"] == tracks["source_token"]


@pytest.mark.parametrize(
    "failure",
    ["ambiguous", "missing", "unsupported", "changed_source", "rejected", "unapplied", "revoked"],
)
def test_preferred_playback_does_not_resume_on_failed_or_ambiguous_selection(attached, failure):
    app, browser, player, _, actor, selection, item = attached
    assert invoke(
        app,
        actor,
        "play_media",
        selection_id=selection,
        audio_language="en",
        subtitle_language="fr",
    )["queued"]
    load = browser.post(
        "/api/media/sessions/" + player["id"], json={"token": player["token"]}
    ).json()["commands"][0]
    tracks = inventory(item, load["load_token"])
    if failure == "ambiguous":
        tracks["audio"].append(
            {"id": "audio:2", "label": "English commentary", "language": "en", "selected": False}
        )
    if failure == "missing":
        tracks["audio"] = tracks["audio"][:1]
    if failure == "unsupported":
        tracks["audio_supported"] = False
    if failure == "changed_source":
        tracks["source_token"] = "different-load"
    if failure == "revoked":
        grant = app.state.agent_service.access.grant(actor)
        grant.permissions = []
        app.state.agent_service.access.update_internal(actor, grant)
    response = report(browser, player, item, tracks, load["sequence"])
    if failure in {"rejected", "unapplied"}:
        chosen = response["commands"][0]
        response = report(
            browser,
            player,
            item,
            tracks,
            chosen["sequence"],
            {
                "sequence": chosen["sequence"],
                "applied": failure == "unapplied",
                "error": "Decoder rejected this track" if failure == "rejected" else "",
            },
        )
    assert response["commands"] == []
    assert response["state"]["track_request"]["status"] == "failed"


def test_track_report_rejects_wrong_source_and_duplicate_ids(attached):
    _, browser, player, _, _, _, item = attached
    tracks = inventory("other")
    response = browser.post(
        "/api/media/sessions/" + player["id"],
        json={
            "token": player["token"],
            "report": {"current_id": item, "queue": [item], "track_state": tracks},
        },
    )
    assert response.status_code == 400

    tracks = inventory(item)
    tracks["audio"].append(tracks["audio"][0])
    response = browser.post(
        "/api/media/sessions/" + player["id"],
        json={
            "token": player["token"],
            "report": {"current_id": item, "queue": [item], "track_state": tracks},
        },
    )
    assert response.status_code == 400


def test_owner_pause_cancels_preparation_without_reusing_command_sequence(attached):
    app, browser, player, _, actor, selection, _ = attached
    invoke(app, actor, "play_media", selection_id=selection, audio_language="en")
    before = browser.post(
        "/api/media/sessions/" + player["id"], json={"token": player["token"]}
    ).json()
    load_sequence = before["commands"][0]["sequence"]
    cancelled = browser.post(
        "/api/media/sessions/" + player["id"], json={"token": player["token"], "action": "pause"}
    ).json()
    assert [c["action"] for c in cancelled["commands"]] == ["pause"]
    assert cancelled["commands"][0]["sequence"] > load_sequence
    assert cancelled["state"]["track_request"]["status"] == "failed"


def test_load_acknowledgment_can_arrive_before_new_track_inventory(attached):
    app, browser, player, _, actor, selection, item = attached
    report(browser, player, item, inventory(item))
    invoke(app, actor, "play_media", selection_id=selection, audio_language="en")
    load = browser.post(
        "/api/media/sessions/" + player["id"], json={"token": player["token"]}
    ).json()["commands"][0]
    waiting = browser.post(
        "/api/media/sessions/" + player["id"],
        json={"token": player["token"], "report": {"command_ack": load["sequence"]}},
    ).json()
    assert waiting["state"]["track_request"]["status"] == "loading"
    assert waiting["commands"] == []
    ready = report(browser, player, item, inventory(item, load["load_token"]), load["sequence"])
    assert ready["commands"][0]["track_id"] == "audio:1"


def test_label_disambiguation_and_subtitles_off(attached):
    app, browser, player, _, actor, selection, item = attached
    invoke(
        app,
        actor,
        "play_media",
        selection_id=selection,
        audio_language="fr",
        audio_label="VFF",
        subtitle_language="off",
    )
    load = browser.post(
        "/api/media/sessions/" + player["id"], json={"token": player["token"]}
    ).json()["commands"][0]
    tracks = inventory(item, load["load_token"])
    tracks["audio"].append(
        {"id": "audio:2", "label": "French VFQ", "language": "fr", "selected": False}
    )
    response = report(browser, player, item, tracks, load["sequence"])
    audio = response["commands"][0]
    assert audio["track_id"] == "audio:0"
    response = report(
        browser,
        player,
        item,
        tracks,
        audio["sequence"],
        {"sequence": audio["sequence"], "applied": True, "error": ""},
    )
    assert response["commands"][0]["track_id"] == "off"
