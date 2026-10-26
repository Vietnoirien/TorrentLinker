"""Opt-in local-model acceptance through the public Media and Assistant APIs."""

import os
import shutil
from pathlib import Path

import pytest
from mutagen.flac import FLAC

from tests.test_assistant_live import controlled, conversation, run  # noqa: F401
from tests.test_media_api import scan
from torrentlinker.domain import LibraryFolder

pytestmark = pytest.mark.skipif(
    not os.getenv("TL_LIVE_MODEL_URL"), reason="explicit local model endpoint required"
)


def test_live_media_playlist_and_attached_player(controlled, tmp_path):  # noqa: F811
    browser, provider, clients, _ = controlled
    root = tmp_path / "files"
    track = root / "validation.flac"
    shutil.copy(Path(__file__).parent / "fixtures/audio/track16.flac", track)
    tags = FLAC(track)
    tags["title"] = "Validation Track"
    tags["artist"] = "TorrentLinker Test Artist"
    tags["album"] = "Playback Validation"
    tags.save()
    setup = browser.app.state.agent_service.setup
    setup.settings.library_folders = [LibraryFolder(root)]
    scan(browser)
    item = browser.get("/api/media?client_id=default&kind=music").json()["rows"][0]
    first = browser.post("/api/media/sessions", json={"client_id": "default"}).json()
    second = browser.post("/api/media/sessions", json={"client_id": "default"}).json()
    thread = conversation(browser, provider, mode="execute", permissions=["media"])
    attached = browser.post(
        f"/api/media/sessions/{first['id']}/chat",
        json={"token": first["token"], "conversation_id": thread},
    )
    assert attached.is_success, attached.text
    result = run(
        browser,
        thread,
        "Dans ma bibliothèque musicale locale du client default, trouve les morceaux de "
        "TorrentLinker Test Artist et sauvegarde-les dans une playlist nommée Validation locale. "
        "Présente la sélection dans le chat. Ne lance aucune lecture ni téléchargement.",
        "media-playlist",
    )
    assert result["status"] == "completed", result
    playlists = browser.get("/api/media/playlists?client_id=default").json()
    assert any(
        p["name"] == "Validation locale" and p["media_ids"] == [item["id"]] for p in playlists
    ), result
    assert "present_media" in str(result), result
    report = browser.post(
        f"/api/media/sessions/{first['id']}",
        json={
            "token": first["token"],
            "report": {
                "current_id": item["id"],
                "queue": [item["id"]],
                "position": 2,
                "duration": 12,
                "paused": False,
                "command_ack": 0,
            },
        },
    )
    assert report.is_success, report.text
    result = run(
        browser,
        thread,
        "Mets mon lecteur attaché en pause et règle son volume à 25 %. "
        "Utilise les contrôles de ce lecteur, sans changer de média.",
        "media-player-control",
    )
    assert result["status"] == "completed", result
    commands = browser.post(
        f"/api/media/sessions/{first['id']}", json={"token": first["token"]}
    ).json()["commands"]
    assert any(command["action"] == "pause" for command in commands), commands
    assert any(
        command["action"] == "volume" and command["volume"] == 0.25 for command in commands
    ), commands
    other = browser.post(
        f"/api/media/sessions/{second['id']}", json={"token": second["token"]}
    ).json()
    assert other["commands"] == []
    assert all(not client.paused for client in clients.values())
