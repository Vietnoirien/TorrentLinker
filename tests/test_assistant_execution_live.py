"""Real-model regression for prose claims being mistaken for executed actions."""

import json
import os
import time

import httpx
import pytest

from tests import test_assistant_live
from torrentlinker.download_queue import enqueue
from torrentlinker.indexer import Candidate, Indexer

controlled = test_assistant_live.controlled
pytestmark = pytest.mark.skipif(
    not os.getenv("TL_LIVE_MODEL_URL"), reason="explicit local model endpoint required"
)


def test_live_send_after_unexecuted_retry_claims_requires_real_proposal(controlled, tmp_path):
    browser, provider, clients, _ = controlled
    service = browser.app.state.assistant
    setup = browser.app.state.agent_service.setup
    destination = tmp_path / "files"
    setup.settings.download_folders.default = str(destination)
    setup.settings.free_space_margin = 0
    setup.save()
    candidate = Candidate(
        "Buddy.2026.VOSTFR.1080p.WEBRip.x265-TEST",
        1_845_679_740,
        "https://tracker.invalid/file",
        10,
        "a" * 40,
    )
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(500))) as http:
        enqueue(
            setup.store,
            Indexer("https://tracker.invalid/api", "fake-key", http=http),
            candidate,
            destination,
        )
    chat = browser.post(
        "/api/assistant/conversations",
        json={
            "name": "Media discussion",
            "provider_id": provider,
            "max_calls": 12,
            "max_seconds": 180,
            "policy": {
                "name": "Media discussion",
                "clients": ["default"],
                "mode": "execute",
                "permissions": ["media"],
            },
        },
    ).json()["id"]
    history = [
        ("mets Buddy en file", "Buddy a bien été mis en file, statut sent, 1/1."),
        ("oui", "L'envoi a été refusé : moins de 1,50 Go libres sur le disque."),
        ("retry", "Je relance. L'envoi a à nouveau été refusé pour manque d'espace."),
    ]
    with service.lock, service.db:
        for index, (request, answer) in enumerate(history):
            service.db.execute(
                "INSERT INTO runs(id,conversation_id,schedule_id,status,created,messages,"
                "events,tokens,calls,error) "
                "VALUES(?,?,'','completed',?,?,'[]',100,1,'')",
                (
                    f"unexecuted-{index}",
                    chat,
                    time.time() - 10 + index,
                    json.dumps(
                        [
                            {"role": "user", "content": request},
                            {"role": "assistant", "content": answer, "phase": "final"},
                        ]
                    ),
                ),
            )
    result = test_assistant_live.run(
        browser, chat, "lance le telechargement", "send-after-unexecuted-retries"
    )
    assert result["status"] == "awaiting_approval", result
    assert any(
        event.get("result", {}).get("requires_owner_approval") for event in result["events"]
    ), result
    pending = next(
        event["result"]
        for event in result["events"]
        if event.get("result", {}).get("requires_owner_approval")
    )
    review = browser.get(f"/api/agents/proposals/{pending['id']}/review")
    assert review.is_success, review.text
    assert review.json()["operation"]["kind"] == "send-queue"
    assert review.json()["operation"]["hashes"] == [candidate.infohash]
    assert not clients["https://one.invalid"].paused
    assert browser.get("/api/queue").json()[0]["status"] == "queued"
