"""A page's frame loads the first time the page is shown, not when the shell starts."""

import os

import pytest

from tests.shell_support import shell_navigate
from tests.test_app_shell_browser import sign_in
from tests.test_toast_errors_browser import serve

pytestmark = pytest.mark.skipif(os.getenv("TL_WEB_BROWSER") != "1", reason="opt-in browser test")

PAGES = (
    "catalogue", "plan", "seeding", "settings", "profile", "community", "feeds", "torrents",
    "upload", "reseed", "documentation", "search", "assistant", "media",
)  # fmt: skip


def test_pages_load_on_first_visit_with_their_environment(tmp_path):
    from playwright.sync_api import expect, sync_playwright

    server, thread, base = serve(tmp_path)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={"width": 1280, "height": 900}, locale="en-US")
            loaded: list[str] = []
            page.on(
                "request",
                lambda request: (
                    loaded.append(request.url.split("/static/")[1].split("/")[0])
                    if request.url.endswith("/view.html") and "/static/" in request.url
                    else None
                ),
            )
            sign_in(page, base)
            page.wait_for_timeout(1500)
            started = {name for name in loaded if name in PAGES}
            assert started == {"settings"}, started  # an unconfigured server opens Settings
            for name in PAGES:
                if name != "settings":
                    assert page.locator(f"#{name}-frame").count() in (0, 1)
                    if page.locator(f"#{name}-frame").count():
                        assert not page.locator(f"#{name}-frame").get_attribute("src"), name
            shell_navigate(page, "feeds")
            expect(page.locator("#feeds-frame")).to_have_attribute("src", "static/feeds/view.html")
            # The page got its environment on its late load: it shows the interface language.
            expect(page.frame_locator("#feeds-frame").locator("html")).to_have_attribute(
                "lang", "en"
            )
            shell_navigate(page, "zen")
            assert not page.locator("#plan-frame").get_attribute("src")
            page.locator("#zen-plan-tab").click()
            expect(page.locator("#plan-frame")).to_have_attribute("src", "static/plan/view.html")
            assert not page.locator("#catalogue-frame").get_attribute("src")
            assert {"seeding", "catalogue", "community"}.isdisjoint(set(loaded))
            browser.close()
    finally:
        server.should_exit = True
        thread.join(5)
