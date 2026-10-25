"""Content deduplication through the shared MCP selection/list/card workflow."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from tests import test_catalogue_selection
from tests.test_agent_torrent_lists import selected, tool

catalogue_app = test_catalogue_selection.catalogue_app


@pytest.mark.parametrize("keep,expected", [("first", "a"), ("smallest", "a"), ("most_seeded", "b")])
def test_distinct_films_share_one_release_across_cards_lists_and_totals(
    catalogue_app, keep, expected
):
    app, browser, token = catalogue_app
    store = app.state.agent_service.setup.store
    store.save_catalogue([replace(store.catalogue(["b" * 40])[0], seeders=8)])
    selection = selected(browser, token, "films", categories=[2030])
    calls = []

    def details(identity):
        calls.append(identity)
        return {
            "infoHash": identity,
            "description": "Same film, different releases.",
            "metadata": {
                "tmdbData": {
                    "id": 42,
                    "title": "One film",
                    "posterUrl": "https://example.org/poster.jpg",
                }
            },
        }

    app.state.agent_service.setup._indexer = SimpleNamespace(
        url="https://test.invalid", is_c411=True, torrent_json=details, redact=lambda v: v
    )
    result = tool(
        browser,
        token,
        "deduplicate_selection",
        request_id="unique",
        selection_id=selection,
        keep=keep,
        count=2,
    )
    assert result["selected_count"] == 1
    assert result["removed_duplicate_count"] == 1
    assert result["shortfall"] == 1
    assert result["unknown_identity_count"] == 0
    assert result["total_size_bytes"] == (4 if expected == "a" else 8)
    saved = tool(
        browser,
        token,
        "create_torrent_list",
        request_id="save",
        client_id="default",
        name="Distinct films",
        selection_id=result["selection_id"],
    )
    page = tool(browser, token, "get_torrent_list", list_id=saved["id"], revision=1)
    assert [row["hash"] for row in page["rows"]] == [expected * 40]
    cards = tool(
        browser, token, "present_selection", request_id="show", selection_id=result["selection_id"]
    )
    assert cards["count"] == 1
    assert cards["items"][0]["content_title"] == "One film"
    assert cards["items"][0]["image_url"]
    assert (
        tool(
            browser,
            token,
            "deduplicate_selection",
            request_id="unique",
            selection_id=selection,
            keep=keep,
            count=2,
        )
        == result
    )
    assert browser.get("/api/queue").json() == []


@pytest.mark.parametrize("mode", ["different_ids", "missing", "series", "changed_indexer"])
def test_matching_titles_or_posters_never_merge_unverified_content(catalogue_app, mode):
    app, browser, token = catalogue_app
    setup = app.state.agent_service.setup
    if mode == "series":
        setup.store.save_catalogue(
            [replace(row, category=5000) for row in setup.store.catalogue(["a" * 40, "b" * 40])]
        )
    selection = selected(browser, token, "candidates")
    calls = []

    def details(identity):
        calls.append(identity)
        return (
            {
                "infoHash": identity,
                "metadata": {
                    "tmdbData": {
                        "id": (41 if identity.startswith("a") else 42)
                        if mode == "different_ids"
                        else 42,
                        "title": "Same title",
                        "posterUrl": "https://example.org/same.jpg",
                    }
                },
            }
            if mode != "missing"
            else {}
        )

    setup._indexer = SimpleNamespace(
        url="https://other.invalid" if mode == "changed_indexer" else "https://test.invalid",
        is_c411=True,
        torrent_json=details,
        redact=lambda v: v,
    )
    result = tool(
        browser, token, "deduplicate_selection", request_id="distinct", selection_id=selection
    )
    assert result["selected_count"] == 3
    assert result["removed_duplicate_count"] == 0
    assert result["unknown_identity_count"] == (1 if mode == "different_ids" else 3)
    if mode == "changed_indexer":
        assert calls == []


@pytest.mark.parametrize("bad_id", ["²", "1" * 5000, "0", -1])
def test_invalid_content_identity_does_not_abort_other_films(catalogue_app, bad_id):
    app, browser, token = catalogue_app
    selection = selected(browser, token, "films", categories=[2030])
    app.state.agent_service.setup._indexer = SimpleNamespace(
        url="https://test.invalid",
        is_c411=True,
        redact=lambda v: v,
        torrent_json=lambda identity: {
            "infoHash": identity,
            "metadata": {
                "tmdbData": {
                    "id": bad_id if identity.startswith("a") else 42,
                    "title": "Film",
                }
            },
        },
    )
    result = tool(
        browser,
        token,
        "deduplicate_selection",
        request_id="safe-identities",
        selection_id=selection,
    )
    assert result["selected_count"] == 2
    assert result["unknown_identity_count"] == 1
    assert result["verified_distinct_count"] == 1


def test_deduplication_is_bounded_before_fetching_and_keeps_saved_revision(catalogue_app):
    from tests.test_agent_access import call
    from torrentlinker.store import CatalogueRow

    app, browser, token = catalogue_app
    setup = app.state.agent_service.setup
    setup.store.save_catalogue(
        [
            CatalogueRow(
                f"{i:040x}", f"Film {i}", i + 1, 5, 2030, "https://test.invalid/download", "", 1
            )
            for i in range(101)
        ]
    )
    selection = selected(browser, token, "too-many", count=101)
    calls = []
    setup._indexer = SimpleNamespace(
        url="https://test.invalid",
        is_c411=True,
        torrent_json=lambda h: calls.append(h) or {},
        redact=lambda v: v,
    )
    error = call(
        browser,
        token,
        "deduplicate_selection",
        {
            "request_id": "bounded",
            "selection_id": selection,
        },
    )
    assert "100 candidate" in str(error)
    assert calls == []
    small = selected(browser, token, "small", count=2)
    saved = tool(
        browser,
        token,
        "create_torrent_list",
        request_id="original",
        client_id="default",
        name="Original",
        selection_id=small,
    )
    result = tool(
        browser,
        token,
        "deduplicate_selection",
        request_id="subset",
        list_id=saved["id"],
        expected_revision=1,
        count=1,
    )
    assert result["selected_count"] == 1 and result["omitted_by_count"] == 1
    original = tool(browser, token, "get_torrent_list", list_id=saved["id"], revision=1)
    assert original["count"] == 2 and original["current_revision"] == 1
    conflict = call(
        browser,
        token,
        "deduplicate_selection",
        {
            "request_id": "subset",
            "list_id": saved["id"],
            "expected_revision": 1,
            "count": 1,
            "keep": "smallest",
        },
    )
    assert "different operation" in str(conflict)
    from tests.test_agent_queue_capabilities import approve

    setup._indexer.unredact = lambda value: value
    queued = approve(
        browser,
        tool(
            browser,
            token,
            "enqueue_selection",
            request_id="queue-exact-subset",
            selection_id=result["selection_id"],
        ),
    )
    assert queued["queued"] == 1
    assert len(browser.get("/api/queue").json()) == 1
