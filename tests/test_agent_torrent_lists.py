import json

from tests import test_catalogue_selection
from tests.test_agent_access import call
from tests.test_agent_queue_capabilities import approve
from tests.test_web_jobs import finished

catalogue_app = test_catalogue_selection.catalogue_app


def tool(browser, token, tool_name, **arguments):
    result = call(browser, token, tool_name, arguments)
    assert not result.get("isError"), result
    content = result["structuredContent"]
    assert not content.get("error"), content
    return content


def selected(browser, token, request_id, **criteria):
    proposal = tool(
        browser,
        token,
        "select_catalogue",
        request_id=request_id,
        client_id="default",
        criteria={"count": 100, **criteria},
    )
    assert finished(browser, proposal["job_id"])["status"] == "completed"
    return proposal["job_id"]


def test_durable_list_composes_refines_and_keeps_materialized_revision(catalogue_app):
    app, browser, token = catalogue_app
    films = selected(browser, token, "films", categories=[2030])
    created = tool(
        browser,
        token,
        "create_torrent_list",
        request_id="create",
        client_id="default",
        name="Weekend",
        selection_id=films,
    )
    identifier = created["id"]
    assert (created["revision"], created["count"], created["total_size_bytes"]) == (1, 2, 12)
    books = selected(browser, token, "books", categories=[7000])
    added = tool(
        browser,
        token,
        "edit_torrent_list",
        request_id="add",
        list_id=identifier,
        expected_revision=1,
        action="add",
        selection_id=books,
    )
    assert added["count"] == 3
    subset = selected(browser, token, "one-film", query="Film B")
    refined = tool(
        browser,
        token,
        "edit_torrent_list",
        request_id="refine",
        list_id=identifier,
        expected_revision=2,
        action="replace_subset",
        selection_id=subset,
        subset={"categories": [2030]},
    )
    assert (refined["revision"], refined["count"], refined["total_size_bytes"]) == (3, 2, 10)
    materialized = tool(
        browser,
        token,
        "select_torrent_list",
        request_id="materialize",
        list_id=identifier,
        expected_revision=3,
        source="catalogue",
    )
    selection = materialized["selection_id"]
    tool(
        browser,
        token,
        "edit_torrent_list",
        request_id="clear",
        list_id=identifier,
        expected_revision=3,
        action="clear",
    )
    result = approve(
        browser,
        tool(
            browser, token, "enqueue_selection", request_id="enqueue-list", selection_id=selection
        ),
    )
    assert result["queued"] == 2
    assert len(browser.get("/api/queue").json()) == 2
    rows = tool(browser, token, "get_torrent_list", list_id=identifier, revision=3)["rows"]
    assert {row["title"] for row in rows} == {"Film B", "Book"}
    assert all(row["provenance"]["selection_id"] for row in rows)
    # Exact retry returns original revision, without repeating the edit after later changes.
    retry = tool(
        browser,
        token,
        "edit_torrent_list",
        request_id="add",
        list_id=identifier,
        expected_revision=1,
        action="add",
        selection_id=books,
    )
    assert retry == added


def test_preexisting_list_rows_without_client_ids_remain_editable(catalogue_app):
    app, browser, token = catalogue_app
    selection = selected(browser, token, "legacy-source", categories=[2030])
    created = tool(
        browser,
        token,
        "create_torrent_list",
        request_id="legacy-list",
        client_id="default",
        name="Before upgrade",
        selection_id=selection,
    )
    db = app.state.agent_service.access.db
    original = json.loads(
        db.execute(
            "SELECT body FROM torrent_list_revisions WHERE list_id=? AND revision=1",
            (created["id"],),
        ).fetchone()[0]
    )
    for row in original:
        row.pop("client_id")
    with db:
        db.execute(
            "UPDATE torrent_list_revisions SET body=? WHERE list_id=? AND revision=1",
            (json.dumps(original), created["id"]),
        )
    shown = tool(browser, token, "get_torrent_list", list_id=created["id"], revision=1)
    assert all(row["client_id"] == "default" for row in shown["rows"])
    changed = tool(
        browser,
        token,
        "edit_torrent_list",
        request_id="legacy-edit",
        list_id=created["id"],
        expected_revision=1,
        action="remove",
        subset={"query": "Film B"},
    )
    assert changed["revision"] == 2


def test_list_revision_conflicts_and_planning_has_no_budget_side_effects(catalogue_app):
    app, browser, token = catalogue_app
    created = tool(
        browser, token, "create_torrent_list", request_id="empty", client_id="default", name="Empty"
    )
    assert created["count"] == 0 and created["total_size_bytes"] == 0
    tool(
        browser,
        token,
        "edit_torrent_list",
        request_id="bump",
        list_id=created["id"],
        expected_revision=1,
        action="clear",
    )
    from tests.test_agent_access import call

    result = call(
        browser,
        token,
        "edit_torrent_list",
        {
            "request_id": "stale",
            "list_id": created["id"],
            "expected_revision": 1,
            "action": "clear",
        },
    )["structuredContent"]
    assert "revision" in result["error"].lower()
    listed = tool(browser, token, "list_torrent_lists", client_id="default")
    assert listed["lists"][0]["revision"] == 2
    assert (
        app.state.agent_service.access.db.execute("SELECT COUNT(*) FROM reservations").fetchone()[0]
        == 0
    )


def test_lists_survive_snapshot_expiry_and_new_application_instance(catalogue_app, monkeypatch):
    import time

    from fastapi.testclient import TestClient

    from tests.test_assistant import login
    from torrentlinker.web.app import create_app

    app, browser, token = catalogue_app
    source = selected(browser, token, "persist-source", categories=[2030])
    created = tool(
        browser,
        token,
        "create_torrent_list",
        request_id="persist",
        client_id="default",
        name="Persisted",
        selection_id=source,
    )
    now = time.time()
    monkeypatch.setattr("torrentlinker.agent.service.time.time", lambda: now + 901)
    persisted = tool(browser, token, "get_torrent_list", list_id=created["id"], revision=1)
    assert persisted["count"] == 2
    materialized = tool(
        browser,
        token,
        "select_torrent_list",
        request_id="fresh",
        list_id=created["id"],
        expected_revision=1,
        source="catalogue",
    )
    assert materialized["selected_count"] == 2
    directory = app.state.agent_service.setup.path.parent
    with TestClient(create_app(directory, password="test-password-long")) as restarted:
        login(restarted)
        lists = tool(restarted, token, "list_torrent_lists", client_id="default")
        assert lists["lists"][0]["id"] == created["id"]
        rows = tool(restarted, token, "get_torrent_list", list_id=created["id"], revision=1)["rows"]
        assert len(rows) == 2
        assert rows[0]["provenance"]["selection_id"] == source


def test_list_actor_isolation_request_reuse_and_revocation(catalogue_app):
    app, browser, token = catalogue_app
    source = selected(browser, token, "private-source")
    created = tool(
        browser,
        token,
        "create_torrent_list",
        request_id="private",
        client_id="default",
        name="Private",
        selection_id=source,
    )
    other = browser.post("/api/agents", json={"name": "Other", "clients": ["default"]}).json()
    assert tool(browser, other["token"], "list_torrent_lists", client_id="default")["lists"] == []
    for name, args in [
        ("get_torrent_list", {"list_id": created["id"], "revision": 1}),
        (
            "create_torrent_list",
            {
                "request_id": "steal",
                "client_id": "default",
                "name": "Stolen",
                "selection_id": source,
            },
        ),
        (
            "select_torrent_list",
            {
                "request_id": "steal-select",
                "list_id": created["id"],
                "expected_revision": 1,
                "source": "catalogue",
            },
        ),
    ]:
        assert "error" in call(browser, other["token"], name, args)["structuredContent"]
    conflicting = call(
        browser,
        token,
        "create_torrent_list",
        {"request_id": "private", "client_id": "default", "name": "Changed"},
    )
    assert "request_id" in conflicting["structuredContent"]["error"]
    # List planning has no grant permission/budget requirements, but no client-scope bypass.
    denied = call(browser, token, "list_torrent_lists", {"client_id": "other"})
    assert "error" in denied["structuredContent"]


def test_large_list_batches_and_storage_cap_are_explicit(catalogue_app, monkeypatch):
    from torrentlinker.store import CatalogueRow

    app, browser, token = catalogue_app
    store = app.state.agent_service.setup.store
    store.save_catalogue(
        [
            CatalogueRow(
                f"{i:040x}", f"Saved Film {i:04}", i, 5, 2030, f"https://test.invalid/{i}", "", 1
            )
            for i in range(1, 1006)
        ]
    )
    first = selected(browser, token, "first1000", categories=[2030], query="Saved", count=1000)
    second = selected(
        browser, token, "last5", categories=[2030], query="Saved", offset=1000, count=1000
    )
    created = tool(
        browser,
        token,
        "create_torrent_list",
        request_id="large",
        client_id="default",
        name="Large",
        selection_id=first,
    )
    added = tool(
        browser,
        token,
        "edit_torrent_list",
        request_id="larger",
        list_id=created["id"],
        expected_revision=1,
        action="add",
        selection_id=second,
    )
    assert added["count"] == 1005
    page = tool(
        browser,
        token,
        "get_torrent_list",
        list_id=created["id"],
        revision=2,
        offset=1000,
        limit=100,
    )
    assert len(page["rows"]) == 5 and not page["has_more"] and page["count"] == 1005
    batch = tool(
        browser,
        token,
        "select_torrent_list",
        request_id="batch1000",
        list_id=created["id"],
        expected_revision=2,
        source="catalogue",
        count=1000,
    )
    assert batch["selected_count"] == 1000 and batch["list_totals"]["count"] == 1005
    assert batch["has_more"] and batch["next_offset"] == 1000
    tail = tool(
        browser,
        token,
        "select_torrent_list",
        request_id="batch5",
        list_id=created["id"],
        expected_revision=2,
        source="catalogue",
        offset=1000,
        count=1000,
    )
    assert tail["selected_count"] == 5 and not tail["has_more"]
    monkeypatch.setattr("torrentlinker.agent.torrent_lists.MAX_ROWS", 1004)
    denied = call(
        browser,
        token,
        "edit_torrent_list",
        {
            "request_id": "over-cap",
            "list_id": created["id"],
            "expected_revision": 2,
            "action": "add",
            "selection_id": second,
        },
    )["structuredContent"]
    assert "nothing was changed" in denied["error"]
    assert (
        tool(browser, token, "get_torrent_list", list_id=created["id"], revision=2)[
            "current_revision"
        ]
        == 2
    )


def test_queue_materialization_unknown_size_and_fresh_live_status_comparison(catalogue_app):
    from pathlib import Path
    from types import SimpleNamespace

    from tests.test_agent_queue_capabilities import queue_selection
    from torrentlinker.domain import Torrent
    from torrentlinker.download_queue import enqueue
    from torrentlinker.indexer import Candidate

    app, browser, token = catalogue_app
    setup = app.state.agent_service.setup
    for i, size in enumerate([4, 0, 8], 1):
        enqueue(
            setup.store,
            setup.indexer(),
            Candidate(
                f"Item {i}", size, "https://test.invalid/file", 5, f"{i:040x}", categories=(2030,)
            ),
            Path(setup.settings.download_folders.by_category[2030]),
        )
    source = queue_selection(browser, token)
    created = tool(
        browser,
        token,
        "create_torrent_list",
        request_id="unknown",
        client_id="default",
        name="Unknown size",
        selection_id=source,
    )
    assert created["total_size_bytes"] is None and created["known_size_bytes"] == 12
    assert created["unknown_size_count"] == 1
    materialized = tool(
        browser,
        token,
        "select_torrent_list",
        request_id="queue-mat",
        list_id=created["id"],
        expected_revision=1,
        source="queue",
    )
    preview = tool(browser, token, "preview_download", selection_id=materialized["selection_id"])
    assert preview["total_size_bytes"] is None
    setup._client = SimpleNamespace(
        torrents=lambda **kwargs: [
            Torrent(f"{1:040x}", "One", Path("/downloads"), state="uploading"),
            Torrent(f"{2:040x}", "Two", Path("/downloads"), state="pausedUP"),
            Torrent(f"{3:040x}", "Three", Path("/downloads"), state="checkingUP"),
        ]
    )
    compared = tool(
        browser, token, "compare_torrent_list_client", list_id=created["id"], expected_revision=1
    )
    assert compared["groups"]["actively_seeding"]["count"] == 1
    assert compared["groups"]["completed_paused"]["count"] == 1
    assert compared["groups"]["completed_other"]["count"] == 1
    assert compared["observed_at"] > 0


def test_list_optimistic_concurrency_is_atomic_and_request_ids_are_global(catalogue_app):
    from concurrent.futures import ThreadPoolExecutor

    app, browser, token = catalogue_app
    source = selected(browser, token, "shared-id", categories=[2030])
    conflict = call(
        browser,
        token,
        "create_torrent_list",
        {
            "request_id": "shared-id",
            "client_id": "default",
            "name": "Conflicting",
            "selection_id": source,
        },
    )["structuredContent"]
    assert "request_id" in conflict["error"]
    created = tool(
        browser,
        token,
        "create_torrent_list",
        request_id="concurrent",
        client_id="default",
        name="Concurrent",
    )
    args = {
        "list_id": created["id"],
        "expected_revision": 1,
        "action": "add",
        "selection_id": source,
    }
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(
                call, browser, token, "edit_torrent_list", {**args, "request_id": f"race-{i}"}
            )
            for i in range(2)
        ]
        results = [f.result()["structuredContent"] for f in futures]
    assert sum("error" in r for r in results) == 1
    assert tool(browser, token, "get_torrent_list", list_id=created["id"], revision=2)["count"] == 2
    denied = call(
        browser,
        token,
        "select_catalogue",
        {"request_id": "concurrent", "client_id": "default", "criteria": {}},
    )["structuredContent"]
    assert "request_id" in denied["error"]


def test_materialization_refreshes_only_volatile_metadata_and_keeps_saved_provenance(catalogue_app):
    from dataclasses import replace

    app, browser, token = catalogue_app
    source = selected(browser, token, "freshness-source", query="Film B")
    created = tool(
        browser,
        token,
        "create_torrent_list",
        request_id="freshness",
        client_id="default",
        name="Later",
        selection_id=source,
    )
    store = app.state.agent_service.setup.store
    original = store.catalogue(["b" * 40])[0]
    store.save_catalogue([replace(original, seeders=99, seen_at=77)])
    materialized = tool(
        browser,
        token,
        "select_torrent_list",
        request_id="volatile-update",
        list_id=created["id"],
        expected_revision=1,
        source="catalogue",
    )
    assert materialized["volatile_metadata_refreshed_count"] == 1
    saved = tool(browser, token, "get_torrent_list", list_id=created["id"], revision=1)
    assert saved["rows"][0]["seeders"] == 5
    actor = app.state.agent_service.access.authenticate(token)
    _, snapshot = app.state.agent_service.selection(actor, materialized["selection_id"], kind=None)
    assert snapshot["rows"][0]["seeders"] == 99
    store.save_catalogue([replace(original, size=500)])
    denied = call(
        browser,
        token,
        "select_torrent_list",
        {
            "request_id": "changed-size",
            "list_id": created["id"],
            "expected_revision": 1,
            "source": "catalogue",
        },
    )["structuredContent"]
    assert "metadata changed" in denied["error"]


def test_saved_lists_outlive_expired_imports_but_materializations_still_expire(
    catalogue_app, monkeypatch
):
    import time

    app, browser, token = catalogue_app
    source = selected(browser, token, "expiry-source", categories=[2030])
    created = tool(
        browser,
        token,
        "create_torrent_list",
        request_id="expiry",
        client_id="default",
        name="Long lived",
        selection_id=source,
    )
    mat = tool(
        browser,
        token,
        "select_torrent_list",
        request_id="expiry-mat",
        list_id=created["id"],
        expected_revision=1,
        source="catalogue",
    )
    now = time.time()
    monkeypatch.setattr("torrentlinker.agent.service.time.time", lambda: now + 901)
    retry = tool(
        browser,
        token,
        "create_torrent_list",
        request_id="expiry",
        client_id="default",
        name="Long lived",
        selection_id=source,
    )
    assert retry == created
    denied = call(
        browser,
        token,
        "enqueue_selection",
        {"request_id": "expired-send", "selection_id": mat["selection_id"]},
    )["structuredContent"]
    assert "expired" in denied["error"]
    assert tool(browser, token, "get_torrent_list", list_id=created["id"], revision=1)["count"] == 2


def test_queue_duplicate_hashes_deduplicate_in_lists_but_cannot_widen_actions(catalogue_app):
    from types import SimpleNamespace

    from tests.test_agent_queue_capabilities import queue_films, queue_selection
    from torrentlinker.download_queue import enqueue, entries

    app, browser, token = catalogue_app
    queue_films(browser, token)
    setup = app.state.agent_service.setup
    existing = entries(setup.store)[0]
    enqueue(
        setup.store,
        SimpleNamespace(url="https://other.invalid", redact=lambda v: v),
        existing.candidate,
        existing.folder,
    )
    selected_queue = queue_selection(browser, token)
    created = tool(
        browser,
        token,
        "create_torrent_list",
        request_id="dedup",
        client_id="default",
        name="Dedup",
        selection_id=selected_queue,
    )
    assert created["count"] == 2
    denied = call(
        browser,
        token,
        "select_torrent_list",
        {
            "request_id": "ambiguous",
            "list_id": created["id"],
            "expected_revision": 1,
            "source": "queue",
        },
    )["structuredContent"]
    assert "exactly one" in denied["error"]
    assert len(entries(setup.store)) == 3


def test_omitted_keep_source_cannot_clear_list_and_filters_refine_without_hash_copying(
    catalogue_app,
):
    _, browser, token = catalogue_app
    source = selected(browser, token, "safe-keep-source", categories=[2030])
    created = tool(
        browser,
        token,
        "create_torrent_list",
        request_id="safe-keep",
        client_id="default",
        name="Safe keep",
        selection_id=source,
    )
    denied = call(
        browser,
        token,
        "edit_torrent_list",
        {
            "request_id": "missing-source",
            "list_id": created["id"],
            "expected_revision": 1,
            "action": "keep",
        },
    )["structuredContent"]
    assert "error" in denied
    assert (
        tool(browser, token, "get_torrent_list", list_id=created["id"], revision=1)[
            "current_revision"
        ]
        == 1
    )
    kept = tool(
        browser,
        token,
        "edit_torrent_list",
        request_id="keep-one",
        list_id=created["id"],
        expected_revision=1,
        action="keep",
        subset={"categories": [2030], "sort_by": "size", "count": 1},
    )
    assert kept["count"] == 1 and kept["total_size_bytes"] == 4
    removed = tool(
        browser,
        token,
        "edit_torrent_list",
        request_id="remove-one",
        list_id=created["id"],
        expected_revision=2,
        action="remove",
        subset={"query": "Film A"},
    )
    assert removed["count"] == 0


def test_list_sources_cannot_cross_client_scope_and_missing_observations_are_errors(catalogue_app):
    app, browser, _ = catalogue_app
    remote = browser.post(
        "/api/clients",
        json={"client": "qbittorrent", "host": "https://remote.invalid", "name": "Remote"},
    ).json()["client_id"]
    token = browser.post(
        "/api/agents", json={"name": "Both", "clients": ["default", remote]}
    ).json()["token"]
    source = selected(browser, token, "cross-source", categories=[2030])
    denied = call(
        browser,
        token,
        "create_torrent_list",
        {
            "request_id": "cross-create",
            "client_id": remote,
            "name": "Wrong client",
            "selection_id": source,
        },
    )["structuredContent"]
    assert "same Torrent Client" in denied["error"]
    created = tool(
        browser,
        token,
        "create_torrent_list",
        request_id="remote-empty",
        client_id=remote,
        name="Remote list",
    )
    denied = call(
        browser,
        token,
        "edit_torrent_list",
        {
            "request_id": "cross-edit",
            "list_id": created["id"],
            "expected_revision": 1,
            "action": "add",
            "selection_id": source,
        },
    )["structuredContent"]
    assert "same Torrent Client" in denied["error"]
    assert (
        tool(browser, token, "get_torrent_list", list_id=created["id"], revision=1)[
            "current_revision"
        ]
        == 1
    )


def test_blank_exclusion_filter_cannot_silently_clear_saved_list(catalogue_app):
    _, browser, token = catalogue_app
    source = selected(browser, token, "blank-source", categories=[2030])
    created = tool(
        browser,
        token,
        "create_torrent_list",
        request_id="blank-list",
        client_id="default",
        name="Kept safe",
        selection_id=source,
    )
    denied = call(
        browser,
        token,
        "edit_torrent_list",
        {
            "request_id": "blank-filter",
            "list_id": created["id"],
            "expected_revision": 1,
            "action": "remove",
            "subset": {"exclude_terms": ["", " "]},
        },
    )["structuredContent"]
    assert "error" in denied
    saved = tool(browser, token, "get_torrent_list", list_id=created["id"], revision=1)
    assert saved["count"] == 2 and saved["current_revision"] == 1


def test_exact_film_music_workflow_queues_53_saved_members_with_zero_download_budget(catalogue_app):
    from torrentlinker.downloads import IndexerCategory
    from torrentlinker.store import CatalogueRow

    app, browser, _ = catalogue_app
    setup = app.state.agent_service.setup
    setup.settings.indexer_categories[3000] = IndexerCategory("Music")
    setup.settings.download_folders.by_category[3000] = setup.settings.download_folders.by_category[
        2030
    ]
    setup.store.save_catalogue(
        [
            CatalogueRow(
                f"{i:040x}",
                f"Saved film {i:02}",
                i * 1000,
                5,
                2030,
                f"https://test.invalid/{i}",
                "",
                1,
            )
            for i in range(1, 13)
        ]
        + [
            CatalogueRow(
                f"{100 + i:040x}",
                f"Saved album {i:02}",
                i * 100,
                5,
                3000,
                f"https://test.invalid/{100 + i}",
                "",
                1,
            )
            for i in range(1, 52)
        ]
    )
    token = browser.post(
        "/api/agents",
        json={
            "name": "Queue-only planning",
            "clients": ["default"],
            "mode": "execute",
            "permissions": ["queue"],
            "daily_bytes": 0,
            "daily_torrents": 0,
            "reserve_bytes": 0,
        },
    ).json()["token"]
    films = selected(browser, token, "ten-films", query="Saved film", count=10)
    saved = tool(
        browser,
        token,
        "create_torrent_list",
        request_id="weekend",
        client_id="default",
        name="Weekend",
        selection_id=films,
    )
    kept = tool(
        browser,
        token,
        "edit_torrent_list",
        request_id="five-films",
        list_id=saved["id"],
        expected_revision=1,
        action="keep",
        subset={"sort_by": "size", "count": 5},
    )
    assert kept["count"] == 5 and kept["total_size_bytes"] == 15000
    music = selected(browser, token, "fifty-albums", query="Saved album", count=50)
    added = tool(
        browser,
        token,
        "edit_torrent_list",
        request_id="add-music",
        list_id=saved["id"],
        expected_revision=2,
        action="add",
        selection_id=music,
    )
    assert added["count"] == 55 and added["total_size_bytes"] == 142500
    films = selected(browser, token, "three-films", query="Saved film", count=3)
    refined = tool(
        browser,
        token,
        "edit_torrent_list",
        request_id="refine-films",
        list_id=saved["id"],
        expected_revision=3,
        action="replace_subset",
        selection_id=films,
        subset={"categories": [2030]},
    )
    assert refined["count"] == 53 and refined["total_size_bytes"] == 133500
    materialized = tool(
        browser,
        token,
        "select_torrent_list",
        request_id="exact-weekend",
        list_id=saved["id"],
        expected_revision=4,
        source="catalogue",
    )
    proposed = tool(
        browser,
        token,
        "enqueue_selection",
        request_id="queue-weekend",
        selection_id=materialized["selection_id"],
    )
    assert finished(browser, proposed["job_id"])["status"] == "completed"
    queued = browser.get("/api/queue").json()
    assert len(queued) == 53
    assert {row["hash"] for row in queued} == {f"{i:040x}" for i in range(1, 4)} | {
        f"{100 + i:040x}" for i in range(1, 51)
    }
    assert (
        tool(browser, token, "get_torrent_list", list_id=saved["id"], revision=4)[
            "current_revision"
        ]
        == 4
    )
