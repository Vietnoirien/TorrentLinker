"""Owner flows through desktop widgets and the browser."""

import os
import socket
import threading
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from tests.test_assistant import login
from torrentlinker.web.app import create_app


def provider(request):
    if request.method == "GET":
        return httpx.Response(
            200, json={"models": [{"name": "test:latest", "context_length": 262144}]}
        )
    return httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "Ready to prepare a Plan. No torrents were changed.",
                    }
                }
            ]
        },
    )


def test_desktop_discussion_keeps_the_composer_available(qtbot, tmp_path, monkeypatch):
    from torrentlinker.gui.assistant import AssistantTab

    app = create_app(
        tmp_path, password="test-password-long", assistant_transport=httpx.MockTransport(provider)
    )
    with TestClient(app) as browser:
        login(browser)
        browser.post(
            "/api/setup/assistant/providers",
            json={"name": "Local test", "kind": "ollama", "model": "test"},
        ).json()
        widget = AssistantTab(lambda: app.state.assistant)
        qtbot.addWidget(widget)
        widget.resize(1000, 700)
        widget.show()
        widget.activate()
        assert widget.send.isEnabled()
        widget.prompt.setPlainText("Help me build a Plan.")
        widget.send.click()
        qtbot.waitUntil(lambda: "Ready to prepare" in widget.transcript.toPlainText(), timeout=5000)
        chats = browser.get("/api/assistant/conversations").json()
        assert len(chats) == 1
        assert chats[0]["name"] == "Help me build a Plan."
        assert chats[0]["policy"]["mode"] == "propose"
        assert widget.send.isEnabled()
        assert widget.prompt.height() <= 115
        from PySide6.QtWidgets import QFrame, QToolButton

        assert len(widget.transcript.findChildren(QFrame, "chatMessage")) == 2
        activity = widget.transcript.findChild(QToolButton)
        assert not activity.isChecked()
        activity.click()
        assert activity.isChecked()

        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication, QPushButton

        next(b for b in widget.findChildren(QPushButton) if b.text() == "New discussion").click()
        assert QApplication.activeModalWidget() is None
        assert widget.prompt.hasFocus()
        assert widget.send.isEnabled()
        assert len(browser.get("/api/assistant/conversations").json()) == 1
        widget.prompt.setPlainText("Another task")
        qtbot.keyClick(widget.prompt, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
        assert "\n" in widget.prompt.toPlainText()
        assert len(browser.get("/api/assistant/conversations").json()) == 1
        qtbot.keyClick(widget.prompt, Qt.Key.Key_Return)
        qtbot.waitUntil(lambda: "Ready to prepare" in widget.transcript.toPlainText(), timeout=5000)
        assert len(browser.get("/api/assistant/conversations").json()) == 2
        widget.conversations.setCurrentRow(1)
        assert "Help me build a Plan." in widget.transcript.toPlainText()
        widget.grab().save(str(tmp_path / "assistant-desktop.png"))
        from PySide6.QtWidgets import QMessageBox

        monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)
        next(b for b in widget.findChildren(QPushButton) if b.text() == "Delete discussion").click()
        assert len(browser.get("/api/assistant/conversations").json()) == 1
        assert not widget.conversation_id
        assert "Help me build a Plan." not in widget.transcript.toPlainText()


@pytest.mark.skipif(os.getenv("TL_WEB_BROWSER") != "1", reason="opt-in browser test")
def test_browser_can_configure_model_chat_and_schedule_on_small_screen(tmp_path):
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    app = create_app(
        tmp_path, password="test-password-long", assistant_transport=httpx.MockTransport(provider)
    )
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", log_config=None))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.02)
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1000, "height": 740}, locale="en-US")
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/")
            page.locator("#login-password").fill("test-password-long")
            page.locator("#login-form button").click()
            page.locator('[data-view="assistant"]').click()
            page.get_by_role("button", name="Connections", exact=True).click()
            page.get_by_role("button", name="Add connection", exact=True).click()
            dialog = page.locator(".assistant-dialog")
            dialog.get_by_label("Name", exact=True).fill("Local test")
            dialog.get_by_label("Model ID", exact=True).fill("test")
            expect(dialog.get_by_label("Detect context automatically")).to_be_checked()
            dialog.get_by_role("button", name="Check context", exact=True).click()
            expect(dialog).to_contain_text("262,144 tokens")
            dialog.get_by_label("Detect context automatically").uncheck()
            dialog.get_by_label("Context window (tokens)", exact=True).fill("65536")
            dialog.get_by_role("button", name="Check context", exact=True).click()
            expect(dialog).to_contain_text("Manual context: 65,536 tokens")
            dialog.get_by_role("button", name="Save", exact=True).click()
            expect(page.get_by_role("heading", name="Local test")).to_be_visible()
            page.get_by_role("button", name="Discussion", exact=True).click()
            page.get_by_role("button", name="New discussion", exact=True).click()
            expect(page.locator(".assistant-dialog")).to_have_count(0)
            page.locator("#assistant-prompt").fill("Help me build a Plan.")
            page.locator("#assistant-prompt").press("Enter")
            expect(page.locator("#assistant-transcript")).to_contain_text(
                "Ready to prepare", timeout=10000
            )
            expect(page.locator(".assistant-message.user")).to_have_count(1)
            activity = page.locator(".assistant-activity")
            expect(activity).not_to_have_attribute("open", "")
            activity.locator("summary").first.click()
            expect(activity).to_have_attribute("open", "")
            page.locator("#assistant-prompt").fill("Keep this unfinished message")
            page.get_by_role("button", name="Discussion settings", exact=True).click()
            dialog = page.locator(".assistant-dialog")
            dialog.get_by_label("Name", exact=True).fill("My films")
            dialog.get_by_label("Allow public Web research", exact=True).check()
            dialog.get_by_role("button", name="Save", exact=True).click()
            expect(page.locator("#assistant-prompt")).to_have_value("Keep this unfinished message")
            expect(page.locator("#assistant-transcript")).to_contain_text("Ready to prepare")
            page.get_by_role("button", name="New discussion", exact=True).click()
            expect(page.locator(".assistant-dialog")).to_have_count(0)
            page.get_by_role("button", name="Discussion settings", exact=True).click()
            dialog = page.locator(".assistant-dialog")
            expect(dialog.get_by_label("Allow public Web research", exact=True)).not_to_be_checked()
            dialog.get_by_label("Allow public Web research", exact=True).check()
            dialog.get_by_role("button", name="Save", exact=True).click()
            page.get_by_role("button", name="New discussion", exact=True).click()
            page.get_by_role("button", name="Discussion settings", exact=True).click()
            dialog = page.locator(".assistant-dialog")
            expect(dialog.get_by_label("Allow public Web research", exact=True)).to_be_checked()
            dialog.get_by_role("button", name="Cancel", exact=True).click()
            page.get_by_role("button", name="My films", exact=True).click()
            expect(page.locator("#assistant-prompt")).to_have_value("Keep this unfinished message")
            page.screenshot(path=str(tmp_path / "assistant-web.png"))
            page.once("dialog", lambda dialog: dialog.accept())
            page.get_by_role("button", name="Delete discussion", exact=True).click()
            expect(page.get_by_role("button", name="My films", exact=True)).to_have_count(0)
            expect(page.locator(".assistant-message.user")).to_have_count(0)

            page.get_by_role("button", name="Automations", exact=True).click()
            page.get_by_role("button", name="Create task", exact=True).click()
            dialog = page.locator(".assistant-dialog")
            dialog.get_by_label("Name", exact=True).fill("Daily report")
            dialog.get_by_label("Instructions", exact=True).fill("Review my Plan.")
            dialog.get_by_role("button", name="Preview next run").click()
            dialog.get_by_role("button", name="Save", exact=True).click()
            expect(page.get_by_role("heading", name="Daily report")).to_be_visible()
            page.get_by_role("button", name="Run now", exact=True).click()
            expect(page.locator("#view-assistant")).to_contain_text("Runs and tool receipts")
            assert not errors
            browser.close()
    finally:
        server.should_exit = True
        thread.join(10)
        listener.close()


def test_desktop_context_detection_and_manual_override(qtbot, tmp_path):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QDialogButtonBox,
        QLabel,
        QPushButton,
        QSpinBox,
    )

    from torrentlinker.gui.assistant import AssistantTab

    app = create_app(
        tmp_path, password="test-password-long", assistant_transport=httpx.MockTransport(provider)
    )
    with TestClient(app) as browser:
        login(browser)
        saved = browser.post(
            "/api/setup/assistant/providers",
            json={"name": "Local test", "kind": "ollama", "model": "test"},
        ).json()
        widget = AssistantTab(lambda: app.state.assistant)
        qtbot.addWidget(widget)
        widget.show()
        widget.activate()

        def configure():
            dialog = QApplication.activeModalWidget()
            automatic = dialog.findChild(QCheckBox)
            assert automatic.isChecked()
            check = next(b for b in dialog.findChildren(QPushButton) if b.text() == "Check context")
            check.click()
            qtbot.waitUntil(
                lambda: any(
                    "262144 tokens" in label.text() for label in dialog.findChildren(QLabel)
                ),
                timeout=5000,
            )
            dialog.grab().save(str(tmp_path / "context-editor.png"))
            automatic.setChecked(False)
            dialog.findChild(QSpinBox).setValue(65536)
            dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Save).click()

        QTimer.singleShot(0, configure)
        widget.provider_editor(saved)
        result = browser.get(f"/api/setup/assistant/providers/{saved['id']}/context").json()
        assert result["context_window"] == 65536
        assert result["source"] == "manual"
        widget.close()


def test_chat_follows_messages_after_layout_settles(qtbot, tmp_path):
    from torrentlinker.gui.assistant import AssistantTab

    app = create_app(
        tmp_path, password="test-password-long", assistant_transport=httpx.MockTransport(provider)
    )
    with TestClient(app) as browser:
        login(browser)
        browser.post(
            "/api/setup/assistant/providers",
            json={"name": "Local", "kind": "ollama", "model": "test"},
        )
        widget = AssistantTab(lambda: app.state.assistant)
        qtbot.addWidget(widget)
        widget.resize(800, 600)
        widget.show()
        widget.activate()
        for i in range(4):
            widget.prompt.setPlainText(f"Message {i} with many lines.\n\n" * 20)
            widget.send.click()
            qtbot.waitUntil(lambda: widget.send.isEnabled(), timeout=5000)
            qtbot.wait(150)
            bar = widget.transcript.verticalScrollBar()
            assert bar.maximum() - bar.value() <= 10


def test_desktop_question_approval_and_markdown_table(qtbot, tmp_path):
    from PySide6.QtGui import QTextTable
    from PySide6.QtWidgets import QComboBox, QLineEdit, QPushButton

    from tests.test_assistant_waits import response, tool
    from tests.test_multi_client_web import Client
    from torrentlinker.gui.assistant import AssistantTab
    from torrentlinker.gui.chat_transcript import MessageText

    client = Client("Test")
    turns = []

    def model(request):
        if request.method == "GET":
            return httpx.Response(404)
        turns.append(request)
        if len(turns) == 1:
            return response(
                [tool("ask_user", {"question": "Which action?", "options": ["Pause", "Skip"]})]
            )
        if len(turns) == 2:
            return response(
                [
                    tool(
                        "propose_action",
                        {
                            "request_id": "pause",
                            "operation": {
                                "kind": "manage",
                                "client_id": "default",
                                "action": "pause",
                                "hashes": ["a" * 40],
                            },
                        },
                    )
                ]
            )
        return response(text="| Action | Result |\n| --- | --- |\n| Pause | Complete |")

    app = create_app(
        tmp_path,
        password="test-password-long",
        connector=lambda *args: client,
        assistant_transport=httpx.MockTransport(model),
    )
    with TestClient(app) as browser:
        login(browser)
        browser.post(
            "/api/setup/client", json={"client": "qbittorrent", "host": "https://one.test"}
        )
        browser.post(
            "/api/setup/assistant/providers",
            json={"name": "Local", "kind": "ollama", "model": "test"},
        )
        widget = AssistantTab(lambda: app.state.assistant)
        qtbot.addWidget(widget)
        widget.resize(900, 700)
        widget.show()
        widget.activate()
        widget.prompt.setPlainText("Help choose an action.")
        widget.send.click()
        qtbot.waitUntil(
            lambda: (
                bool(widget.transcript.findChildren(QPushButton))
                and any(
                    b.text() == "Submit answer" for b in widget.transcript.findChildren(QPushButton)
                )
            ),
            timeout=5000,
        )
        widget.pages.setCurrentIndex(2)
        widget.refresh_run()
        assert any(b.text() == "Submit answer" for b in widget.history.findChildren(QPushButton))
        widget.pages.setCurrentIndex(0)
        submit = next(
            b for b in widget.transcript.findChildren(QPushButton) if b.text() == "Submit answer"
        )
        assert not submit.isEnabled()
        options = widget.transcript.findChild(QComboBox)
        options.setCurrentIndex(1)
        assert submit.isEnabled()
        assert len(turns) == 1  # Selecting an option never submits it.
        widget.transcript.findChild(QLineEdit).setText("Please pause this torrent")
        submit.click()
        qtbot.waitUntil(
            lambda: any(
                b.text() == "Approve once" for b in widget.transcript.findChildren(QPushButton)
            ),
            timeout=5000,
        )
        assert client.paused == []  # The answer did not authorize the action.
        assert not widget.send.isEnabled()
        next(
            b for b in widget.transcript.findChildren(QPushButton) if b.text() == "Approve once"
        ).click()
        qtbot.waitUntil(lambda: "Complete" in widget.transcript.toPlainText(), timeout=5000)
        assert client.paused == ["a" * 40]
        assert any(
            isinstance(frame, QTextTable)
            for text in widget.transcript.findChildren(MessageText)
            for frame in text.document().rootFrame().childFrames()
        )
        widget.grab().save(str(tmp_path / "assistant-inline-desktop.png"))


@pytest.mark.skipif(os.getenv("TL_WEB_BROWSER") != "1", reason="opt-in browser test")
def test_browser_inline_question_approval_and_safe_table(tmp_path):
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    from tests.test_assistant_waits import response, tool
    from tests.test_multi_client_web import Client

    client = Client("Test")
    turns = []

    def model(request):
        if request.method == "GET":
            return httpx.Response(404)
        turns.append(request)
        if len(turns) == 1:
            return response(
                [tool("ask_user", {"question": "Which action?", "options": ["Pause", "Skip"]})]
            )
        if len(turns) == 2:
            return response(
                [
                    tool(
                        "propose_action",
                        {
                            "request_id": "pause",
                            "operation": {
                                "kind": "manage",
                                "client_id": "default",
                                "action": "pause",
                                "hashes": ["a" * 40],
                            },
                        },
                    )
                ]
            )
        return response(
            text="| Action | Result |\n| --- | --- |\n| Pause | Complete |\n\n<script>alert(1)</script>\n\n![bad](https://resource.test/image.png)\n\n[bad](javascript:alert(1))"
        )

    app = create_app(
        tmp_path,
        password="test-password-long",
        connector=lambda *args: client,
        assistant_transport=httpx.MockTransport(model),
    )
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", log_config=None))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.02)
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", trust_env=False) as owner:
            login(owner)
            owner.post(
                "/api/setup/client", json={"client": "qbittorrent", "host": "https://one.test"}
            )
            owner.post(
                "/api/setup/assistant/providers",
                json={"name": "Local", "kind": "ollama", "model": "test"},
            )
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 560, "height": 760}, locale="en-US")
            errors, remote = [], []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "request",
                lambda request: (
                    remote.append(request.url)
                    if request.url.startswith("https://resource.test/")
                    else None
                ),
            )
            page.goto(f"http://127.0.0.1:{port}/")
            page.locator("#login-password").fill("test-password-long")
            page.locator("#login-form button").click()
            page.locator('[data-view="assistant"]').click()
            page.locator("#assistant-prompt").fill("Help choose an action.")
            page.locator("#assistant-prompt").press("Enter")
            question = page.locator(".assistant-question")
            expect(question).to_be_visible(timeout=10000)
            submit = question.get_by_role("button", name="Submit answer", exact=True)
            expect(submit).to_be_disabled()
            question.get_by_role("combobox").select_option("Pause")
            expect(submit).to_be_enabled()
            assert len(turns) == 1
            question.get_by_role("textbox").fill("Please pause this torrent")
            submit.click()
            decision = page.locator(".assistant-decision")
            expect(decision).to_be_visible(timeout=10000)
            expect(decision).to_contain_text("pause")
            assert client.paused == []
            expect(page.locator("#assistant-send")).to_be_disabled()
            assert page.locator(".assistant-dialog").count() == 0
            decision.get_by_role("button", name="Approve once", exact=True).click()
            expect(
                page.locator(".assistant-markdown table td").filter(has_text="Complete")
            ).to_be_visible(timeout=10000)
            assert client.paused == ["a" * 40]
            assert (
                page.locator(
                    ".assistant-markdown script, .assistant-markdown a[href^='javascript:']"
                ).count()
                == 0
            )
            assert not remote
            assert (
                page.locator(
                    ".assistant-markdown a[href='https://resource.test/image.png']"
                ).count()
                == 1
            )
            assert not errors
            page.screenshot(path=str(tmp_path / "assistant-inline-web.png"))
            browser.close()
    finally:
        server.should_exit = True
        thread.join(5)
        listener.close()
