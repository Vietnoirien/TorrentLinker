"""Opt-in browser coverage of RSS discovery and preview, against a fake source."""

import os
import socket
import threading
import time

import pytest

pytestmark = pytest.mark.skipif(os.getenv("TL_WEB_BROWSER") != "1", reason="opt-in browser test")


def test_rss_preview_sidebar_unread_and_saved_selection(tmp_path):
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    from tests.test_feeds import Source, release
    from torrentlinker.web.app import create_app

    app = create_app(tmp_path / "config", password="test-password-long")
    source = Source()
    source.rows = [release(title="Baseline film")]
    app.state.agent_service.feed_control.feeds.indexer = lambda: source
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.02)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={"width": 1250, "height": 900}, locale="en-US")
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"http://127.0.0.1:{port}/")
            page.locator("#login-password").fill("test-password-long")
            page.locator("#login-form button").click()
            page.locator("[data-view=feeds]").click()
            page.get_by_role("button", name="New subscription", exact=True).click()
            page.locator("#dialog-content").get_by_label("Name", exact=True).fill("Films")
            page.locator("#dialog-content").get_by_label(
                "Torznab category IDs, comma separated", exact=True
            ).fill("2030")
            page.get_by_role("button", name="Preview", exact=True).click()
            expect(page.locator("#dialog-content pre")).to_contain_text("Limited discovery")
            page.get_by_role("button", name="Save subscription", exact=True).click()
            page.locator("#feeds-sidebar").get_by_role(
                "button", name="Films (0)", exact=True
            ).click()
            page.locator("#feeds-toolbar").get_by_role("button", name="Refresh", exact=True).click()
            expect(page.locator("#feeds-results")).to_contain_text("Baseline film")
            source.rows = [release("b", title="New film"), release(title="Baseline film")]
            page.locator("#feeds-toolbar").get_by_role("button", name="Refresh", exact=True).click()
            expect(page.locator("#feeds-sidebar")).to_contain_text("Films (1)")
            row = page.locator("#feeds-results tbody tr").filter(has_text="New film")
            row.locator("input[type=checkbox]").check()
            page.get_by_role("button", name="Save selection", exact=True).click()
            expect(page.locator("#dialog-content")).to_contain_text("New film")
            page.locator("#dialog .close").click()
            page.get_by_role("button", name="Saved selections", exact=True).click()
            page.locator("#dialog-content").get_by_role("button").first.click()
            expect(page.locator("#dialog-content")).to_contain_text("New film")
            expect(
                page.locator("#dialog-content").get_by_role(
                    "button", name="Queue selected", exact=True
                )
            ).to_be_visible()
            page.locator("#dialog .close").click()
            page.locator("[data-view=search]").click()
            page.locator("#search-query").fill("A new title")
            page.locator("#subscribe-search").click()
            expect(
                page.locator("#dialog-content").get_by_label("Title query", exact=True)
            ).to_have_value("A new title")
            assert errors == []
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)
