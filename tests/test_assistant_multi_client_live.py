"""Opt-in local-model acceptance with isolated clients and no live torrent mutations."""

import os

import pytest

from tests import test_assistant_live
from tests.test_agent_selection import SelectionClient, book

controlled = test_assistant_live.controlled
pytestmark = pytest.mark.skipif(
    not os.getenv("TL_LIVE_MODEL_URL"), reason="explicit local model endpoint required"
)


def test_model_selects_compares_refines_and_pauses_exact_client_instances(controlled):
    browser, provider, clients, nas_id = controlled
    local = SelectionClient([book(1, 3000), book(2, 2000), book(9, 100)])
    nas = SelectionClient([book(1, 3000), book(3, 1000)])
    outside = SelectionClient([book(1, 3000)])
    clients["https://one.invalid"] = local
    clients["https://two.invalid"] = nas
    clients["https://three.invalid"] = outside
    agent = browser.app.state.agent_service
    agent.for_client("default").setup._client = local
    agent.for_client(nas_id).setup._client = nas
    added = browser.post(
        "/api/clients",
        json={
            "name": "Outside scope",
            "client": "qbittorrent",
            "host": "https://three.invalid",
        },
    )
    assert added.is_success, added.text
    created = browser.post(
        "/api/assistant/conversations",
        json={
            "name": "Controlled multi-client management",
            "provider_id": provider,
            "max_calls": 20,
            "max_seconds": 180,
            "max_tokens": 180000,
            "policy": {
                "name": "Two authorized clients",
                "clients": ["default", nas_id],
                "mode": "execute",
                "permissions": ["controls"],
                "daily_bytes": 0,
                "daily_torrents": 0,
            },
        },
    )
    assert created.is_success, created.text
    thread = created.json()["id"]
    result = test_assistant_live.run(
        browser,
        thread,
        f"Across Torrent Client IDs default and {nas_id}, select the 4 largest seeding ebooks "
        "in total with count_scope=global. Compare their exact hashes across those two clients. "
        f"Save a refined selection excluding any hash present only on {nas_id}. "
        "Pause exactly the refined selection, then verify the job result. Do not touch any "
        "other client or any unselected torrent. The controlled clients are simulated.",
        "multi-client-select-refine-pause",
    )
    assert result["status"] == "completed", result
    calls = [event["tool"] for event in result["events"] if "tool" in event]
    assert "select_torrents" in calls, result
    assert "compare_clients" in calls, result
    assert "refine_selection" in calls, result
    assert "manage_selection" in calls, result
    assert sorted(local.paused) == [f"{1:040x}", f"{2:040x}"]
    assert nas.paused == [f"{1:040x}"]
    assert outside.paused == []
    assert f"{9:040x}" not in local.paused
