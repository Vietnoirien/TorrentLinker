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


def test_desktop_discussion_keeps_the_composer_available(qtbot, tmp_path):
    from torrentlinker.gui.assistant import AssistantTab

    app = create_app(
        tmp_path, password="test-password-long", assistant_transport=httpx.MockTransport(provider)
    )
    with TestClient(app) as browser:
        login(browser)
        p = browser.post(
            "/api/setup/assistant/providers",
            json={"name": "Local test", "kind": "ollama", "model": "test"},
        ).json()
        browser.post(
            "/api/assistant/conversations",
            json={
                "name": "My Plan",
                "provider_id": p["id"],
                "policy": {"name": "Local test", "clients": ["default"]},
            },
        )
        widget = AssistantTab(lambda: app.state.assistant)
        qtbot.addWidget(widget)
        widget.resize(1000, 700)
        widget.show()
        widget.activate()
        widget.conversations.setCurrentRow(0)
        widget.prompt.setPlainText("Help me build a Plan.")
        widget.send.click()
        qtbot.waitUntil(lambda: "Ready to prepare" in widget.transcript.toPlainText(), timeout=5000)
        assert widget.send.isEnabled()
        assert widget.prompt.height() <= 115
        widget.grab().save(str(tmp_path / "assistant-desktop.png"))


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
            dialog.get_by_role("button", name="Save", exact=True).click()
            expect(page.get_by_role("heading", name="Local test")).to_be_visible()
            page.get_by_role("button", name="Discussion", exact=True).click()
            page.get_by_role("button", name="New discussion", exact=True).click()
            dialog = page.locator(".assistant-dialog")
            dialog.get_by_label("Name", exact=True).fill("My Plan")
            dialog.get_by_role("button", name="Save", exact=True).click()
            page.locator("#assistant-prompt").fill("Help me build a Plan.")
            page.locator("#assistant-send").click()
            expect(page.locator("#assistant-transcript")).to_contain_text(
                "Ready to prepare", timeout=10000
            )
            page.screenshot(path=str(tmp_path / "assistant-web.png"))
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
