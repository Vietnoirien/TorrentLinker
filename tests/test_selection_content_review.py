"""Descriptions drive owned, durable selection refinements, not title-only guesses."""

from types import SimpleNamespace

import pytest

from tests import test_catalogue_selection
from tests.test_agent_access import call
from tests.test_agent_torrent_lists import selected, tool

catalogue_app = test_catalogue_selection.catalogue_app


def source(app, browser, token):
    selection = selected(browser, token, "source")
    descriptions = {
        "a": "A quiet family story about a mountain expedition.",
        "b": "A documentary about animal experimentation in laboratories.",
        "c": "",
    }
    app.state.agent_service.setup._indexer = SimpleNamespace(
        url="https://test.invalid",
        is_c411=True,
        torrent_json=lambda identity: {
            "infoHash": identity,
            "description": descriptions[identity[0]],
        },
        redact=lambda value: value,
    )
    return selection


def test_read_review_and_save_exact_subset_with_evidence(catalogue_app):
    app, browser, token = catalogue_app
    selection = source(app, browser, token)
    read = tool(
        browser, token, "read_selection_descriptions", request_id="read", selection_id=selection
    )
    assert read["count"] == 3 and read["untrusted_source"]
    by_title = {r["title"]: r for r in read["items"]}
    assert by_title["Book"]["description_status"] == "unavailable"
    decisions = [
        dict(
            item_id=by_title["Film A"]["item_id"],
            decision="keep",
            reason="An outdoor family story matches the request.",
            evidence="family story about a mountain expedition",
        ),
        dict(
            item_id=by_title["Film B"]["item_id"],
            decision="exclude",
            reason="The user excluded animal experimentation.",
            evidence="animal experimentation in laboratories",
        ),
        dict(
            item_id=by_title["Book"]["item_id"],
            decision="uncertain",
            reason="No description is available.",
        ),
    ]
    args = dict(
        request_id="review",
        enrichment_id=read["enrichment_id"],
        criteria="Family stories; exclude animal experimentation",
        decisions=decisions,
    )
    reviewed = tool(browser, token, "review_selection", **args)
    assert (
        reviewed["selected_count"],
        reviewed["excluded_count"],
        reviewed["uncertain_count"],
        reviewed["unreviewed_count"],
    ) == (1, 1, 1, 0)
    assert tool(browser, token, "review_selection", **args) == reviewed
    saved = tool(
        browser,
        token,
        "create_torrent_list",
        request_id="save",
        client_id="default",
        name="Reviewed",
        selection_id=reviewed["selection_id"],
    )
    page = tool(browser, token, "get_torrent_list", list_id=saved["id"], revision=1)
    assert [r["hash"] for r in page["rows"]] == ["a" * 40]
    assert page["rows"][0]["content_review"]["evidence"] == decisions[0]["evidence"]
    assert browser.get("/api/queue").json() == []


def test_unread_and_invented_evidence_cannot_be_kept(catalogue_app):
    app, browser, token = catalogue_app
    selection = source(app, browser, token)
    read = tool(
        browser,
        token,
        "read_selection_descriptions",
        request_id="read",
        selection_id=selection,
        limit=1,
    )
    result = call(
        browser,
        token,
        "review_selection",
        dict(
            request_id="bad",
            enrichment_id=read["enrichment_id"],
            criteria="No unwanted topics",
            decisions=[
                dict(
                    item_id="1",
                    decision="keep",
                    reason="Looks suitable",
                    evidence="invented synopsis",
                )
            ],
        ),
    )
    assert "Read each item's description" in result["structuredContent"]["error"]


def test_partial_description_requires_completion_before_keep(catalogue_app):
    app, browser, token = catalogue_app
    selection = source(app, browser, token)
    read = tool(
        browser,
        token,
        "read_selection_descriptions",
        request_id="read",
        selection_id=selection,
        offset=1,
        limit=1,
        description_limit=20,
    )
    item = read["items"][0]
    args = dict(
        enrichment_id=read["enrichment_id"],
        criteria="Suitable story",
        decisions=[
            dict(
                item_id=item["item_id"],
                decision="keep",
                reason="Fits the request",
                evidence=item["description"].strip(),
            )
        ],
    )
    failed = call(browser, token, "review_selection", {**args, "request_id": "partial"})
    assert "Read the complete description" in failed["structuredContent"]["error"]
    tool(
        browser,
        token,
        "read_selection_descriptions",
        request_id="continue",
        enrichment_id=read["enrichment_id"],
        offset=1,
        limit=1,
        description_offset=20,
    )
    result = tool(browser, token, "review_selection", request_id="complete", **args)
    assert result["selected_count"] == 1 and result["unreviewed_count"] == 2


@pytest.mark.parametrize("missing", [False, True])
def test_read_items_cannot_use_invented_evidence(catalogue_app, missing):
    app, browser, token = catalogue_app
    selection = source(app, browser, token)
    read = tool(
        browser, token, "read_selection_descriptions", request_id="read", selection_id=selection
    )
    result = call(
        browser,
        token,
        "review_selection",
        dict(
            request_id="invented",
            enrichment_id=read["enrichment_id"],
            criteria="Suitable content",
            decisions=[
                dict(
                    item_id="0" if missing else "1",
                    decision="keep",
                    reason="Looks suitable",
                    evidence="No violence whatsoever",
                )
            ],
        ),
    )["structuredContent"]
    assert "exact excerpt" in result["error"]


def test_reviews_accumulate_and_recover_without_modifying_source(catalogue_app):
    from torrentlinker.agent.selection_review import ContentReviews

    app, browser, token = catalogue_app
    selection = source(app, browser, token)
    saved = tool(
        browser,
        token,
        "create_torrent_list",
        request_id="save",
        client_id="default",
        name="Original",
        selection_id=selection,
    )
    read = tool(
        browser,
        token,
        "read_selection_descriptions",
        request_id="read",
        list_id=saved["id"],
        expected_revision=1,
    )
    args = dict(
        enrichment_id=read["enrichment_id"], criteria="Outdoor story; no animal experiments"
    )
    first = tool(
        browser,
        token,
        "review_selection",
        request_id="first",
        **args,
        decisions=[
            dict(
                item_id="1",
                decision="keep",
                reason="Outdoor adventure",
                evidence="mountain expedition",
            )
        ],
    )
    assert first["kept_count"] == 1 and first["unreviewed_count"] == 2
    app.state.agent_service.content_reviews = ContentReviews(app.state.agent_service)
    resumed = tool(
        browser,
        token,
        "read_selection_descriptions",
        request_id="resume",
        enrichment_id=read["enrichment_id"],
    )
    assert resumed["review_revision"] == 1
    assert resumed["items"][1]["review"]["decision"] == "keep"
    update = dict(
        **args,
        decisions=[
            dict(
                item_id="2",
                decision="exclude",
                reason="Excluded topic",
                evidence="animal experimentation",
            )
        ],
    )
    stale = call(browser, token, "review_selection", dict(request_id="stale", **update))
    assert "revision changed" in stale["structuredContent"]["error"]
    changed = call(
        browser,
        token,
        "review_selection",
        {
            **update,
            "criteria": "Different request",
            "request_id": "changed",
            "expected_review_revision": 1,
        },
    )
    assert "new description-review snapshot" in changed["structuredContent"]["error"]
    final = tool(
        browser,
        token,
        "review_selection",
        request_id="second",
        expected_review_revision=1,
        **update,
    )
    assert (final["kept_count"], final["excluded_count"], final["unreviewed_count"]) == (1, 1, 1)
    original = tool(browser, token, "get_torrent_list", list_id=saved["id"], revision=1)
    assert original["count"] == 3


def test_truncated_source_cannot_be_kept_even_after_reading_cached_text(catalogue_app):
    app, browser, token = catalogue_app
    selection = source(app, browser, token)
    app.state.agent_service.setup._indexer.torrent_json = lambda identity: {
        "infoHash": identity,
        "description": "Mountain expedition. " * 1500,
    }
    read = tool(
        browser,
        token,
        "read_selection_descriptions",
        request_id="read",
        selection_id=selection,
        offset=1,
        limit=1,
        description_limit=20000,
    )
    assert read["items"][0]["source_truncated"]
    assert not read["items"][0]["fully_read"]
    result = call(
        browser,
        token,
        "review_selection",
        dict(
            request_id="keep",
            enrichment_id=read["enrichment_id"],
            criteria="Mountain stories",
            decisions=[
                dict(
                    item_id="1",
                    decision="keep",
                    reason="Mountain adventure",
                    evidence="Mountain expedition.",
                )
            ],
        ),
    )["structuredContent"]
    assert "complete description" in result["error"]


def test_description_reviews_cannot_cross_connection_ownership(catalogue_app):
    app, browser, token = catalogue_app
    selection = source(app, browser, token)
    read = tool(
        browser, token, "read_selection_descriptions", request_id="read", selection_id=selection
    )
    from torrentlinker.agent.selection_review import ContentDecision

    with pytest.raises(ValueError, match="connection"):
        app.state.agent_service.content_reviews.apply(
            "different-actor",
            "steal",
            read["enrichment_id"],
            "Family stories",
            [
                ContentDecision(
                    item_id="1",
                    decision="keep",
                    reason="Family adventure",
                    evidence="mountain expedition",
                )
            ],
            0,
        )
