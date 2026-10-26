"""Saved Upload revisions are reviewable through the same public card APIs."""

from tests import test_catalogue_selection
from tests.test_agent_torrent_lists import tool

catalogue_app = test_catalogue_selection.catalogue_app


def draft_payload(title="A book", category=2, subcategory=14):
    return {
        "path": "/library/book.epub",
        "form": {
            "title": title,
            "category": category,
            "subcategory": subcategory,
            "image": "https://example.org/cover.jpg",
            "description": "[b]Saved description[/b]",
            "nfo": "Saved NFO",
            "source": "Retail",
            "options": {"language": [1]},
            "reviewed": False,
        },
        "files": [{"path": "book.epub", "size": 1234, "mtime": 1}],
        "review": {"warnings": ["Check the edition"], "refusals": ["Missing option"]},
        "extra": {},
    }


def test_saved_upload_is_presented_without_sending_or_changing_review(catalogue_app):
    app, browser, token = catalogue_app
    store = app.state.agent_service.setup.store
    draft = store.save_local_draft(draft_payload())
    page = tool(
        browser,
        token,
        "present_upload_drafts",
        request_id="show-upload",
        client_id="default",
        drafts=[{"draft_id": draft["id"], "revision": 1}],
    )
    assert page["presentation_type"] == "upload_drafts"
    assert page["count"] == 1
    item = page["items"][0]
    assert item["kind"] == "ebook" and item["size_bytes"] == 1234
    assert item["image_url"] == "https://example.org/cover.jpg"
    assert item["draft_id"] == draft["id"] and item["draft_revision"] == 1
    assert "files" not in item and "nfo" not in item
    detail = tool(
        browser,
        token,
        "get_presentation_item",
        presentation_id=page["presentation_id"],
        item_id="0",
    )
    assert "Saved description" in detail["description_html"]
    assert detail["nfo"] == "Saved NFO"
    assert detail["files"] == draft["files"]
    assert detail["upload_review"]["refusals"] == ["Missing option"]
    assert store.local_draft(draft["id"]) == draft


def test_chat_upload_card_opens_saved_review_tabs(qtbot):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QDialog, QLabel, QPlainTextEdit, QPushButton, QTabWidget

    from tests.test_selection_cards import presentation_run
    from torrentlinker.gui.chat_transcript import ChatTranscript

    item = {
        "item_id": "0",
        "title": "Review my book",
        "kind": "ebook",
        "category": "Ebook",
        "image_url": "",
        "size_bytes": 1234,
        "presentation_type": "upload_drafts",
        "draft_id": "draft",
        "draft_revision": 1,
        "saved_status": "queued",
        "current_status": "queued",
        "draft_changed": True,
        "current_revision": 2,
        "review_summary": {"warnings": 1, "refusals": 1},
        "description": "Saved description",
        "nfo": "Saved NFO",
        "files": [{"path": "book.epub", "size": 1234}],
        "upload_form": {"options": {"language": [1]}},
        "upload_review": {"warnings": ["Check edition"], "refusals": ["Missing option"]},
    }
    page = {
        "presentation_id": "demo",
        "presentation_type": "upload_drafts",
        "title": "Uploads",
        "count": 1,
        "items": [item],
        "has_more": False,
        "offset": 0,
    }
    run = presentation_run()
    run["events"][0]["tool"] = "present_upload_drafts"
    transcript = ChatTranscript(
        presentation_page=lambda *args, **kw: page, presentation_item=lambda *args: item
    )
    qtbot.addWidget(transcript)
    transcript.set_runs([run], str)
    transcript.show()
    qtbot.waitUntil(lambda: bool(transcript.findChildren(QPushButton, "selectionCard")))
    card = transcript.findChild(QPushButton, "selectionCard")
    assert not card.findChildren(QLabel, "selectionScores")
    qtbot.mouseClick(card, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: bool(transcript.findChildren(QTabWidget, "uploadReviewTabs")))
    tabs = transcript.findChild(QTabWidget, "uploadReviewTabs")
    assert {tabs.tabText(i) for i in range(tabs.count())} >= {
        "Description",
        "NFO",
        "Files",
        "Review",
    }
    texts = [widget.toPlainText() for widget in tabs.findChildren(QPlainTextEdit)]
    assert any("Saved NFO" in text for text in texts)
    assert any("book.epub" in text for text in texts)
    assert any("Missing option" in text for text in texts)
    dialog = transcript.findChild(QDialog, "selectionDetail")
    assert any("changed" in label.text() for label in dialog.findChildren(QLabel))
    dialog.close()


def test_review_snapshot_survives_edits_removal_and_restart(catalogue_app):
    from torrentlinker.agent.selection_presentations import Presentations

    app, browser, token = catalogue_app
    service = app.state.agent_service
    store = service.setup.store
    draft = store.save_local_draft(draft_payload())
    args = dict(
        request_id="immutable-review",
        client_id="default",
        drafts=[{"draft_id": draft["id"], "revision": 1}],
    )
    page = tool(browser, token, "present_upload_drafts", **args)
    changed = store.save_local_draft(draft_payload("New title"), draft["id"], 1)
    retried = tool(browser, token, "present_upload_drafts", **args)
    assert retried["presentation_id"] == page["presentation_id"]
    assert retried["items"][0]["title"] == "A book"
    assert retried["items"][0]["draft_changed"] is True
    assert retried["items"][0]["current_revision"] == 2
    restarted = Presentations(service)
    assert restarted.page(None, page["presentation_id"])["items"] == retried["items"]
    store.remove_local_draft(changed["id"], 2)
    detail = tool(
        browser,
        token,
        "get_presentation_item",
        presentation_id=page["presentation_id"],
        item_id="0",
    )
    assert detail["draft_deleted"] is True and detail["nfo"] == "Saved NFO"


def test_upload_cards_reject_wrong_revisions_client_and_actor(catalogue_app):
    import pytest

    from tests.test_agent_access import call

    app, browser, token = catalogue_app
    service = app.state.agent_service
    draft = service.setup.store.save_local_draft(draft_payload())
    for refs in (
        [{"draft_id": draft["id"], "revision": 2}],
        [],
        [{"draft_id": draft["id"], "revision": 1}] * 2,
    ):
        result = call(
            browser,
            token,
            "present_upload_drafts",
            {"request_id": "invalid", "client_id": "default", "drafts": refs},
        )
        assert result.get("isError") or result.get("structuredContent", {}).get("error"), result
    other = service.setup.settings.add_client("Another client")
    service.setup.store.for_client(other.id).save_local_draft(draft_payload("Other"))
    result = call(
        browser,
        token,
        "present_upload_drafts",
        {
            "request_id": "wrong-client",
            "client_id": other.id,
            "drafts": [{"draft_id": draft["id"], "revision": 1}],
        },
    )
    assert result.get("isError") or result.get("structuredContent", {}).get("error"), result
    page = tool(
        browser,
        token,
        "present_upload_drafts",
        request_id="owned",
        client_id="default",
        drafts=[{"draft_id": draft["id"], "revision": 1}],
    )
    with pytest.raises(ValueError, match="connection"):
        service.presentations.page("other-actor", page["presentation_id"])


def test_draft_cards_sanitize_artwork_and_description_and_paginate(catalogue_app):
    app, browser, token = catalogue_app
    store = app.state.agent_service.setup.store
    payload = draft_payload()
    payload["form"]["image"] = "http://127.0.0.1/private.png"
    payload["form"]["description"] = (
        '<p>Review<script>alert(1)</script><img src="file:///private.png"></p>'
    )
    drafts = [
        store.save_local_draft(payload),
        store.save_local_draft(draft_payload("Music", 3, 18)),
    ]
    page = tool(
        browser,
        token,
        "present_upload_drafts",
        request_id="paged",
        client_id="default",
        drafts=[{"draft_id": row["id"], "revision": 1} for row in drafts],
        limit=1,
    )
    assert page["has_more"] is True and page["items"][0]["image_url"] == ""
    detail = tool(
        browser,
        token,
        "get_presentation_item",
        presentation_id=page["presentation_id"],
        item_id="0",
    )
    assert "<script" not in detail["description_html"] and "<img" not in detail["description_html"]
    next_page = browser.get(
        f"/api/assistant/presentations/{page['presentation_id']}?offset=1&limit=1"
    )
    assert next_page.is_success
    assert next_page.json()["items"][0]["kind"] == "music"
    assert next_page.json()["has_more"] is False


def test_queue_preview_uses_saved_revision_and_does_not_send(catalogue_app):
    app, browser, _ = catalogue_app
    store = app.state.agent_service.setup.store
    draft = store.save_local_draft(draft_payload())
    url = f"/api/upload/queue/{draft['id']}/preview?revision=1&client_id=default"
    response = browser.get(url)
    assert response.status_code == 200
    item = response.json()
    assert item["draft_revision"] == 1
    assert item["nfo"] == "Saved NFO"
    assert item["upload_review"]["refusals"] == ["Missing option"]
    assert store.local_draft(draft["id"]) == draft
    store.save_local_draft(draft_payload("Changed"), draft["id"], 1)
    assert browser.get(url).status_code == 409
    assert browser.get(url.replace("revision=1", "revision=2")).json()["title"] == "Changed"
    assert browser.get(url.replace("client_id=default", "client_id=other")).status_code >= 400


def test_desktop_queue_opens_saved_preview_without_saving_edits(qtbot, tmp_path):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QDialog, QLabel, QTabWidget

    from torrentlinker.gui.local_drafts import LocalDrafts
    from torrentlinker.store import Store

    store = Store(tmp_path / "queue.sqlite")
    payload = draft_payload()
    payload["form"]["image"] = ""
    draft = store.save_local_draft(payload)
    calls = []
    widget = LocalDrafts(
        store, lambda *args: calls.append("save"), lambda *args: calls.append("send")
    )
    qtbot.addWidget(widget)
    widget.table.selectRow(0)
    widget.title.setText("Unsaved changes")
    qtbot.mouseClick(widget.preview_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: widget.findChild(QTabWidget, "uploadReviewTabs") is not None)
    dialog = widget.findChild(QDialog, "selectionDetail")
    assert dialog.findChild(QLabel, "selectionDetailTitle").text() == "A book"
    assert store.local_draft(draft["id"]) == draft
    assert not calls
    dialog.close()
