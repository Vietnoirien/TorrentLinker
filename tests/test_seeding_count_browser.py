"""The seeding count is formatted in the interface language, on the Zen summary and the page."""

import os

import pytest

from tests.test_app_shell_browser import sign_in
from tests.test_toast_errors_browser import serve

pytestmark = pytest.mark.skipif(os.getenv("TL_WEB_BROWSER") != "1", reason="opt-in browser test")


def test_count_follows_the_interface_language(tmp_path):
    from playwright.sync_api import expect, sync_playwright

    from tests.shell_support import shell_navigate

    server, thread, base = serve(tmp_path)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={"width": 1280, "height": 800}, locale="en-US")
            page.route(
                "**/api/zen/seeding?*",
                lambda route: route.fulfill(
                    json={
                        "summary": {"daily": 28.34, "count": 1234, "paid": 28},
                        "total": 0,
                        "offset": 0,
                        "rows": [],
                        "classes": [],
                        "groups": [],
                    }
                ),
            )
            sign_in(page, base)
            shell_navigate(page, "zen")
            page.locator("#zen-seeding-tab").click()
            panel = page.frame_locator("#seeding-frame")
            expect(page.locator("#zen-count")).to_have_text("1,234")
            expect(panel.locator("#seeding-total")).to_contain_text("1,234 torrents seeding")
            page.frame_locator("#shell-navigation-frame").locator("#language").select_option("fr")
            expect(page.locator("#zen-count")).to_have_text("1 234")
            expect(panel.locator("#seeding-total")).to_contain_text("1 234 torrents en partage")
            browser.close()
    finally:
        server.should_exit = True
        thread.join(5)
