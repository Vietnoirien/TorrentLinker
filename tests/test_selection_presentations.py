from tests import test_catalogue_selection
from tests.test_agent_torrent_lists import selected, tool

catalogue_app = test_catalogue_selection.catalogue_app


def test_presentation_freezes_exact_list_and_survives_edits(catalogue_app):
    app, browser, token = catalogue_app
    selection = selected(browser, token, "cards-source")
    saved = tool(
        browser,
        token,
        "create_torrent_list",
        request_id="cards-list",
        client_id="default",
        name="Cards",
        selection_id=selection,
    )
    args = dict(request_id="cards", list_id=saved["id"], expected_revision=1, limit=2)
    page = tool(browser, token, "present_selection", **args)
    assert page["count"] == 3 and page["has_more"]
    assert len(page["items"]) == 2
    assert page["items"][0]["image_url"] == ""
    assert page["items"][0]["title"]
    tool(
        browser,
        token,
        "edit_torrent_list",
        request_id="clear-cards",
        list_id=saved["id"],
        expected_revision=1,
        action="clear",
    )
    assert (
        tool(browser, token, "present_selection", **args)["presentation_id"]
        == page["presentation_id"]
    )
    detail = tool(
        browser,
        token,
        "get_presentation_item",
        presentation_id=page["presentation_id"],
        item_id="0",
    )
    assert detail["title"] == page["items"][0]["title"]
    owner = browser.get(f"/api/assistant/presentations/{page['presentation_id']}?offset=2&limit=2")
    assert owner.status_code == 200, owner.text
    assert owner.json()["count"] == 3 and len(owner.json()["items"]) == 1


def test_native_artwork_provenance_and_sanitized_details(catalogue_app):
    from types import SimpleNamespace

    app, browser, token = catalogue_app
    service = app.state.agent_service
    calls = []

    def details(identity):
        calls.append(identity)
        return {
            "infoHash": identity,
            "description": '<p>Verified description<script>bad()</script><img src="https://example.org/banner.jpg"></p>',
            "metadata": {
                "tmdbData": {
                    "id": 42,
                    "title": "Content title",
                    "posterUrl": "https://example.org/poster.jpg",
                    "runtime": 100,
                }
            },
        }

    selection = selected(browser, token, "native-cards", categories=[2030])
    saved = tool(
        browser,
        token,
        "create_torrent_list",
        request_id="native-list",
        client_id="default",
        name="Films",
        selection_id=selection,
    )
    materialized = tool(
        browser,
        token,
        "select_torrent_list",
        request_id="native-materialized",
        list_id=saved["id"],
        expected_revision=1,
        source="catalogue",
    )
    selection = materialized["selection_id"]
    service.setup._indexer = SimpleNamespace(
        url="https://test.invalid", is_c411=True, torrent_json=details, redact=lambda v: v
    )
    page = tool(
        browser,
        token,
        "present_selection",
        request_id="native-show",
        selection_id=selection,
        limit=1,
    )
    item = page["items"][0]
    assert item["title"] == "Film A" and item["content_title"] == "Content title"
    assert item["image_url"] == "https://example.org/poster.jpg"
    assert item["content_identity"] == {"provider": "tmdb", "id": "42"}
    assert item["provenance"][0]["release_hash"] == "a" * 40
    detail = tool(
        browser,
        token,
        "get_presentation_item",
        presentation_id=page["presentation_id"],
        item_id="0",
    )
    assert "<script" not in detail["description_html"] and "<img" not in detail["description_html"]
    assert "Verified description" in detail["description"]
    assert calls == ["a" * 40]
    assert item["torrent_note"] is not None and item["estimated_zen_per_day"] is not None
    assert "seed_days=0" in item["zen_assumptions"]


def test_description_image_is_never_used_as_cover_and_enrichment_reusable(catalogue_app):
    from types import SimpleNamespace

    app, browser, token = catalogue_app
    selection = selected(browser, token, "no-cover", categories=[7000])
    app.state.agent_service.setup._indexer = SimpleNamespace(
        url="https://test.invalid",
        is_c411=True,
        torrent_json=lambda h: {"description": "[img]https://example.org/banner.jpg[/img]"},
        redact=lambda v: v,
    )
    enriched = tool(
        browser, token, "enrich_selection", request_id="enrich-book", selection_id=selection
    )
    assert "presentation_id" not in enriched
    assert enriched["items"][0]["image_url"] == ""
    page = tool(
        browser,
        token,
        "present_selection",
        request_id="enriched-show",
        enrichment_id=enriched["enrichment_id"],
    )
    assert page["items"][0]["kind"] == "ebook"
    assert page["count"] == 1


def test_presentation_is_owned_and_permission_checked(catalogue_app):
    import pytest

    app, browser, token = catalogue_app
    service = app.state.agent_service
    selection = selected(browser, token, "owned-cards")
    page = tool(
        browser, token, "present_selection", request_id="owned-show", selection_id=selection
    )
    with pytest.raises(ValueError, match="connection"):
        service.presentations.page("different-actor", page["presentation_id"])
    error = browser.get(f"/api/assistant/presentations/{page['presentation_id']}/items/../0")
    assert error.status_code != 200
    for item_id in ("-1", "00", "3", "x", "0/../1"):
        with pytest.raises(ValueError):
            service.presentations.item(None, page["presentation_id"], item_id)


def test_request_conflict_and_research_permission(catalogue_app):
    from tests.test_agent_access import call

    _, browser, token = catalogue_app
    selection = selected(browser, token, "conflict-cards")
    tool(browser, token, "present_selection", request_id="show-once", selection_id=selection)
    for args in (
        {"request_id": "show-once", "selection_id": selection, "title": "Changed"},
        {"request_id": "research-denied", "selection_id": selection, "research": True},
        {"request_id": "no-source"},
        {"request_id": "bad-page", "selection_id": selection, "limit": 21},
    ):
        result = call(browser, token, "present_selection", args)
        assert result.get("isError") or result.get("structuredContent", {}).get("error"), result


def test_persisted_presentation_outlives_selection_and_service_restart(catalogue_app, monkeypatch):
    from torrentlinker.agent.selection_presentations import Presentations

    app, browser, token = catalogue_app
    selection = selected(browser, token, "persistent-source")
    page = tool(
        browser, token, "present_selection", request_id="persistent-show", selection_id=selection
    )
    service = app.state.agent_service
    restarted = Presentations(service)
    monkeypatch.setattr(
        service, "selection", lambda *a, **kw: (_ for _ in ()).throw(ValueError("expired"))
    )
    assert restarted.page(None, page["presentation_id"])["items"] == page["items"]
    assert (
        restarted.create(
            service.presentations.record(None, page["presentation_id"])[0],
            "persistent-show",
            selection_id=selection,
        )["presentation_id"]
        == page["presentation_id"]
    )


def test_release_mismatch_never_adopts_other_metadata(catalogue_app):
    from types import SimpleNamespace

    app, browser, token = catalogue_app
    selection = selected(browser, token, "wrong-release", categories=[2030])
    app.state.agent_service.setup._indexer = SimpleNamespace(
        url="https://test.invalid",
        is_c411=True,
        torrent_json=lambda h: {
            "infoHash": "f" * 40,
            "metadata": {
                "tmdbData": {
                    "id": 12,
                    "title": "Wrong",
                    "posterUrl": "https://example.org/wrong.png",
                }
            },
        },
        redact=lambda v: v,
    )
    page = tool(
        browser, token, "present_selection", request_id="wrong-show", selection_id=selection
    )
    assert all(not item["image_url"] and item["content_identity"] is None for item in page["items"])


def test_empty_unknown_fields_and_category_kinds(catalogue_app):
    from torrentlinker.agent.selection_presentations import kind_of

    app, browser, token = catalogue_app
    saved = tool(
        browser,
        token,
        "create_torrent_list",
        request_id="empty-list",
        client_id="default",
        name="Empty",
    )
    page = tool(
        browser,
        token,
        "present_selection",
        request_id="empty-show",
        list_id=saved["id"],
        expected_revision=1,
    )
    assert page["count"] == 0 and page["items"] == [] and page["has_more"] is False
    basic = app.state.agent_service.presentations.basic(
        {"title": "Unknown", "size": 0, "seeders": -1}, "0"
    )
    assert basic["size_bytes"] is None and basic["seeders"] is None
    assert [
        kind_of({"category": c}) for c in (2030, 5000, 7030, 7000, 3000, 1000, 4000, 8010, None)
    ] == ["movie", "series", "comic", "ebook", "music", "game", "software", "model3d", "other"]


def test_external_research_requires_exact_native_content_identity(catalogue_app):
    from types import SimpleNamespace

    app, browser, token = catalogue_app
    service = app.state.agent_service
    selection = selected(browser, token, "research-source", categories=[2030])
    service.setup._indexer = SimpleNamespace(
        url="https://test.invalid",
        is_c411=True,
        torrent_json=lambda h: {"metadata": {"tmdbData": {"id": 42, "title": "Verified"}}},
        redact=lambda v: v,
    )
    service.presentations.research_for_actor = lambda actor: SimpleNamespace(
        lookup_metadata=lambda query, kind: {
            "sources": [{"id": 43, "title": "Wrong", "image": "https://example.org/wrong.jpg"}]
        }
    )
    page = tool(
        browser,
        token,
        "present_selection",
        request_id="research-mismatch",
        selection_id=selection,
        research=True,
    )
    assert all(item["image_url"] == "" for item in page["items"])
    service.presentations.research_for_actor = lambda actor: SimpleNamespace(
        lookup_metadata=lambda query, kind: {
            "sources": [
                {
                    "id": 42,
                    "url": "https://www.themoviedb.org/movie/42",
                    "image": "https://example.org/verified.jpg",
                }
            ]
        }
    )
    page = tool(
        browser,
        token,
        "present_selection",
        request_id="research-match",
        selection_id=selection,
        research=True,
    )
    assert all(item["artwork_status"] == "verified" for item in page["items"])


def test_native_game_subcategory_and_gps_are_distinct():
    from torrentlinker.agent.selection_presentations import kind_of

    assert kind_of({"category": 4050, "provenance": {"search": {"category": -29}}}) == "game"
    assert kind_of({"category": 4050, "provenance": {"search": {"category": 7}}}) == "software"


def test_original_source_remains_bound_before_and_after_presentation(catalogue_app):
    from types import SimpleNamespace

    app, browser, token = catalogue_app
    selection = selected(browser, token, "source-a")
    saved = tool(
        browser,
        token,
        "create_torrent_list",
        request_id="source-list",
        client_id="default",
        name="SourceA",
        selection_id=selection,
    )
    calls = []
    app.state.agent_service.setup._indexer = SimpleNamespace(
        url="https://other.invalid",
        is_c411=True,
        torrent_json=lambda h: calls.append(h) or {},
        redact=lambda v: v,
    )
    page = tool(
        browser,
        token,
        "present_selection",
        request_id="source-b-show",
        list_id=saved["id"],
        expected_revision=1,
    )
    assert calls == []
    assert all(item["metadata_status"] == "missing" for item in page["items"])
    direct = tool(
        browser, token, "present_selection", request_id="source-b-direct", selection_id=selection
    )
    assert calls == [] and direct["count"] == 3
    materialized = tool(
        browser,
        token,
        "select_torrent_list",
        request_id="source-b-materialize",
        list_id=saved["id"],
        expected_revision=1,
        source="catalogue",
    )
    page = tool(
        browser,
        token,
        "present_selection",
        request_id="source-b-materialized-show",
        selection_id=materialized["selection_id"],
    )
    assert calls == []
    assert all(item["metadata_status"] == "missing" for item in page["items"])
