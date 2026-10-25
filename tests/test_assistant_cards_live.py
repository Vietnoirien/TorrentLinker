"""Opt-in local model card presentation, with isolated clients and tracker responses."""

import os
import re

import httpx
import pytest

from tests import test_assistant_live
from tests.test_torrent_search import fake_indexer
from torrentlinker.downloads import IndexerCategory
from torrentlinker.store import CatalogueRow

controlled = test_assistant_live.controlled
pytestmark = pytest.mark.skipif(
    not os.getenv("TL_LIVE_MODEL_URL"), reason="explicit local model endpoint required"
)


@pytest.mark.parametrize(
    "category,label,kind",
    [(2030, "films", "movie"), (7000, "ebooks", "ebook"), (3000, "albums de musique", "music")],
)
def test_local_model_presents_category_cards_without_downloading(controlled, category, label, kind):
    browser, provider, clients, _ = controlled
    setup = browser.app.state.agent_service.setup
    setup.settings.indexer_categories = {
        2030: IndexerCategory("Films"),
        7000: IndexerCategory("Ebooks"),
        3000: IndexerCategory("Musique"),
    }
    rows = [
        CatalogueRow(
            f"{cat + i:040x}",
            f"Demo {name} {i}",
            1_000_000 * i,
            5,
            cat,
            f"https://c411.org/api?t=get&id={cat + i:040x}",
            "",
            1,
        )
        for cat, name in [(2030, "film"), (7000, "ebook"), (3000, "album")]
        for i in [1, 2]
    ]
    titles = {row.infohash: row.title for row in rows}

    def tracker(request):
        identity = request.url.path.rsplit("/", 1)[-1]
        assert identity in titles, request.url
        return httpx.Response(
            200,
            json={
                "infoHash": identity,
                "description": "<p>A fictional entry used for testing selection cards.</p>",
                "metadata": {"coverUrl": "https://covers.example/demo.png"},
            },
        )

    setup._indexer = fake_indexer(tracker)
    setup.store.save_catalogue(rows)
    thread = test_assistant_live.conversation(browser, provider)
    run = test_assistant_live.run(
        browser,
        thread,
        f"Dans le catalogue local du client default, présente les 2 {label} les plus légers "
        "sous forme de cartes cliquables dans cette discussion, avec leur illustration, leur Note "
        "et le Zen par jour estimé. Je veux ouvrir leurs descriptions en cliquant. "
        "Ne mets rien en file et ne télécharge rien.",
        "selection-cards-" + kind,
    )
    assert run["status"] == "completed", run
    presentations = [
        e["result"]
        for e in run["events"]
        if e["tool"] == "present_selection" and e.get("result", {}).get("presentation_id")
    ]
    assert presentations, run
    final = "\n".join(
        m["content"]
        for m in run["messages"]
        if m["role"] == "assistant" and m.get("phase") == "final"
    )
    assert not re.search(r"!\[[^\]]*\]\(", final), final
    assert "covers.example" not in final, final
    assert not re.search(r"(?m)^\s*(?:\d+[.)]|[-*])\s+.*Demo ", final), final
    page = browser.get(
        "/api/assistant/presentations/" + presentations[-1]["presentation_id"]
    ).json()
    assert page["count"] == 2 and {item["kind"] for item in page["items"]} == {kind}, page
    assert all(item["torrent_note"] is not None for item in page["items"]), page
    assert all(item["estimated_zen_per_day"] is not None for item in page["items"]), page
    assert browser.get("/api/queue").json() == []
    assert not any(e["tool"] in {"enqueue_selection", "send_queue"} for e in run["events"])
    assert all(not client.paused for client in clients.values())
