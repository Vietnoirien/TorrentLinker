"""Opt-in local-model discovery through native c411 search, with a simulated tracker."""

import os

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

CASES = [
    (1, 6, "Films & Vidéos", "Film", "Science-fiction", 47, 2024, "The Quiet Signal", 2030),
    (3, 18, "Audio", "Musique", "Jazz", 321, 2023, "Midnight Session", 3000),
    (2, 14, "Ebook", "Livres", "Fantasy", 211, 2022, "The Glass Forest", 7000),
]


@pytest.mark.parametrize(
    "case,after_year",
    [(case, False) for case in CASES] + [(CASES[0], True)],
    ids=["film-scifi", "music-jazz", "ebook-fantasy", "film-after-2020"],
)
def test_live_prefers_native_search_and_discovers_category_filters(controlled, case, after_year):
    browser, provider, clients, _ = controlled
    root, child, root_name, child_name, genre, option, year, title, cached_category = case
    requests = []
    infohash = f"{option:040x}"

    def handler(request):
        requests.append(request)
        if request.url.path == "/api/categories":
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": rid,
                            "name": rname,
                            "slug": rname.lower(),
                            "subcategories": [{"id": cid, "name": cname, "slug": cname.lower()}],
                        }
                        for rid, cid, rname, cname, *_ in CASES
                    ]
                },
            )
        filter_case = next(
            (
                item
                for item in CASES
                if request.url.path == f"/api/categories/{item[0]}/filter-options"
            ),
            None,
        )
        if filter_case:
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "slug": "genre",
                            "name": "Genre",
                            "values": [{"id": filter_case[5], "value": filter_case[4]}],
                        }
                    ]
                },
            )
        if request.url.path == "/api/torrents":
            params = request.url.params
            matched = (
                params.get("category") == str(root)
                and params.get("subcat") == str(child)
                and str(option) in params.get("options", "").split(",")
                and (params.get("year") == str(year) or (after_year and not params.get("year")))
                and not params.get("name")
            )
            rows = (
                [
                    {
                        "infoHash": infohash,
                        "name": f"{title} {year}",
                        "size": 1_000_000,
                        "seeders": 5,
                        "createdAt": "2026-10-23T10:00:00.000Z",
                        "category": {"id": root, "name": root_name},
                        "subcategory": {"id": child, "name": child_name},
                    }
                ]
                if matched
                else []
            )
            return httpx.Response(
                200,
                json={
                    "data": rows,
                    "meta": {"total": len(rows), "page": 1, "perPage": 100, "totalPages": 1},
                },
            )
        raise AssertionError(f"Unexpected tracker endpoint: {request.url.path}")

    setup = browser.app.state.agent_service.setup
    setup._indexer = fake_indexer(handler)
    setup.settings.indexer_categories = {
        category: IndexerCategory(name) for _, _, _, name, *_, category in CASES
    }
    setup.store.save_catalogue(
        [
            CatalogueRow(
                "f" * 40,
                f"Unverified cached title {genre} {year}",
                1,
                5,
                cached_category,
                "https://test.invalid/lure",
                "",
                1,
            )
        ]
    )
    thread = test_assistant_live.conversation(browser, provider)
    released = "après 2020" if after_year else f"en {year}"
    result = test_assistant_live.run(
        browser,
        thread,
        f"Pour le client default, trouve un titre dans la catégorie {child_name}, "
        f"de genre {genre}, sorti {released}. Présente-moi le résultat avant toute action. "
        "Ne mets rien en file et ne lance aucun téléchargement.",
        f"native-search-{child_name.lower()}-{'range' if after_year else 'year'}",
    )
    assert result["status"] == "completed", result
    assert any(r.url.path == f"/api/categories/{root}/filter-options" for r in requests), result
    assert any(
        r.url.path == "/api/torrents"
        and r.url.params.get("category") == str(root)
        and r.url.params.get("subcat") == str(child)
        and (r.url.params.get("year") == str(year) or (after_year and not r.url.params.get("year")))
        and str(option) in r.url.params.get("options", "").split(",")
        for r in requests
    ), result
    assert any(event["tool"] == "search_indexer" for event in result["events"]), result
    assert not any(event["tool"] == "select_catalogue" for event in result["events"]), result
    # Card presentations intentionally omit a duplicate item list from the final prose.
    presented = [
        item
        for event in result["events"]
        if event["tool"] == "present_selection"
        for item in event.get("result", {}).get("items", [])
    ]
    assert title in result["messages"][-1]["content"] or any(
        item["title"] == f"{title} {year}" for item in presented
    ), result
    assert browser.get("/api/queue").json() == [], result
    assert all(not client.paused for client in clients.values())
    assert not any(
        event["tool"] in {"enqueue_selection", "send_selection", "manage_selection"}
        for event in result["events"]
    ), result
