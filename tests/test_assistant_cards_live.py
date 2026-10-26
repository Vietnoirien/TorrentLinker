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


def test_local_model_reviews_descriptions_before_recommending(controlled):
    browser, provider, clients, _ = controlled
    setup = browser.app.state.agent_service.setup
    setup.settings.indexer_categories = {7000: IndexerCategory("Ebooks")}
    descriptions = {
        1: "An illustrated natural history of coral reefs, their ecosystems and marine wildlife.",
        2: "A history of naval warfare, violent military campaigns and battles at sea.",
        3: "",
    }
    setup._indexer = fake_indexer(
        lambda request: httpx.Response(
            200,
            json={
                "infoHash": request.url.path.rsplit("/", 1)[-1],
                "description": descriptions[int(request.url.path.rsplit("/", 1)[-1], 16)],
            },
        )
    )
    setup.store.save_catalogue(
        [
            CatalogueRow(
                f"{i:040x}",
                f"Ocean {i}",
                i * 1_000_000,
                5,
                7000,
                f"https://c411.org/api?t=get&id={i:040x}",
                "",
                1,
            )
            for i in descriptions
        ]
    )
    thread = test_assistant_live.conversation(browser, provider, max_calls=16)
    result = test_assistant_live.run(
        browser,
        thread,
        "Dans le catalogue local du client default, examine les trois ebooks Ocean. "
        "Je cherche un livre sur la nature marine et je veux exclure les sujets guerre/batailles. "
        "Analyse leurs descriptions avant de choisir : le titre ne suffit pas. "
        "Si la description manque, signale-le et ne le retiens pas. Enregistre tes décisions "
        "avec leurs raisons et extraits justificatifs, puis sauvegarde et présente uniquement "
        "les livres retenus en cartes. Ne mets rien en file et ne télécharge rien.",
        "selection-description-review",
    )
    assert result["status"] == "completed", result
    reviews = [
        e["result"]
        for e in result["events"]
        if e["tool"] == "review_selection" and e.get("result", {}).get("selection_id")
    ]
    assert reviews, result
    assert (
        reviews[-1]["kept_count"],
        reviews[-1]["excluded_count"],
        reviews[-1]["uncertain_count"],
        reviews[-1]["unreviewed_count"],
    ) == (1, 1, 1, 0)
    pages = [
        e["result"]
        for e in result["events"]
        if e["tool"] == "present_selection" and e.get("result", {}).get("items")
    ]
    assert pages and pages[-1]["count"] == 1, result
    assert pages[-1]["items"][0]["title"] == "Ocean 1"
    _, actor = browser.app.state.assistant.conversation(thread)
    saved = browser.app.state.agent_service.torrent_lists.listing(actor, "default", 0, 50)
    assert any(
        item["count"] == 1 and item["total_size_bytes"] == 1_000_000 for item in saved["lists"]
    ), saved
    assert browser.get("/api/queue").json() == []
    assert all(not client.paused for client in clients.values())


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
    assert all(item["image_url"] == "https://covers.example/demo.png" for item in page["items"])
    for item in page["items"]:
        detail = browser.get(
            f"/api/assistant/presentations/{page['presentation_id']}/items/{item['item_id']}"
        ).json()
        assert "fictional entry used for testing" in detail["description"]
    assert browser.get("/api/queue").json() == []
    assert not any(e["tool"] in {"enqueue_selection", "send_queue"} for e in run["events"])
    assert all(not client.paused for client in clients.values())


def test_local_model_deduplicates_film_releases_before_presenting(controlled):
    browser, provider, clients, _ = controlled
    setup = browser.app.state.agent_service.setup
    setup.settings.indexer_categories = {2030: IndexerCategory("Films")}
    rows = [
        CatalogueRow(
            f"{i:040x}",
            f"Film release {i}",
            i * 1_000_000,
            5,
            2030,
            f"https://c411.org/api?t=get&id={i:040x}",
            "",
            1,
        )
        for i in (1, 2, 3)
    ]

    def tracker(request):
        identity = request.url.path.rsplit("/", 1)[-1]
        number = int(identity, 16)
        assert number in (1, 2, 3)
        return httpx.Response(
            200,
            json={
                "infoHash": identity,
                "description": "Fictional film for deduplication tests.",
                "metadata": {
                    "tmdbData": {
                        "id": 42 if number < 3 else 43,
                        "title": "First film" if number < 3 else "Second film",
                        "posterUrl": "https://covers.example/demo.png",
                    }
                },
            },
        )

    setup._indexer = fake_indexer(tracker)
    setup.store.save_catalogue(rows)
    thread = test_assistant_live.conversation(browser, provider)
    run = test_assistant_live.run(
        browser,
        thread,
        "Dans le catalogue local du client default, compare les 3 releases Film disponibles "
        "et présente 2 films DISTINCTS en cartes. Plusieurs releases peuvent être le même film : "
        "garde la plus légère pour chaque film. Sauvegarde la sélection finale pour plus tard. "
        "Ne mets rien en file et ne télécharge rien.",
        "selection-cards-distinct-films",
    )
    assert run["status"] == "completed", run
    assert any(e["tool"] == "deduplicate_selection" for e in run["events"]), run
    presentations = [
        e["result"]
        for e in run["events"]
        if e["tool"] == "present_selection" and e.get("result", {}).get("items")
    ]
    assert presentations, run
    page = presentations[-1]
    assert page["count"] == 2
    assert {i["content_identity"]["id"] for i in page["items"]} == {"42", "43"}
    assert sum(i["size_bytes"] for i in page["items"]) == 4_000_000
    _, actor = browser.app.state.assistant.conversation(thread)
    saved = browser.app.state.agent_service.torrent_lists.listing(actor, "default", 0, 50)
    assert any(
        item["count"] == 2 and item["total_size_bytes"] == 4_000_000 for item in saved["lists"]
    ), saved
    assert browser.get("/api/queue").json() == []
    assert all(not client.paused for client in clients.values())
