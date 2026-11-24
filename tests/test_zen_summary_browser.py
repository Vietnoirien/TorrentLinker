"""Zen tab navigation must not jump when its seeding summary appears."""

import os

import pytest

from tests.test_app_shell_browser import sign_in
from tests.test_toast_errors_browser import serve

pytestmark = pytest.mark.skipif(os.getenv("TL_WEB_BROWSER") != "1", reason="opt-in browser test")


@pytest.mark.parametrize("width", [1280, 800, 390])
def test_zen_tabs_stay_put_and_summary_is_compact(tmp_path, width):
    from playwright.sync_api import expect, sync_playwright

    from tests.shell_support import shell_navigate

    server, thread, base = serve(tmp_path)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(
                viewport={"width": width, "height": 800}, reduced_motion="reduce", locale="fr-FR"
            )
            page.route(
                "**/api/zen/seeding?*",
                lambda route: route.fulfill(
                    json={
                        "summary": {"daily": 28.34, "count": 11695, "paid": 28},
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
            tabs = page.locator('#view-zen [role="tablist"]')
            original = tabs.bounding_box()
            assert original
            for name in ("seeding", "plan", "profile", "seeding"):
                page.locator(f"#zen-{name}-tab").click()
                box = tabs.bounding_box()
                assert box and abs(box["y"] - original["y"]) <= 1
                summary = page.locator("#zen-overview")
                if name == "seeding":
                    expect(summary).to_be_visible()
                    bounds = summary.bounding_box()
                    assert bounds and bounds["height"] <= 90
                    assert bounds["y"] >= box["y"] + box["height"]
                    assert bounds["x"] + bounds["width"] <= width
                    assert bounds["width"] < 340
                    expect(page.locator("#zen-count")).to_have_text("11\u202f695")
                    panel = page.frame_locator("#seeding-frame")
                    title = panel.locator("h1").bounding_box()
                    assert title and abs(title["x"] - bounds["x"]) <= 1
                    refresh = panel.get_by_role("button", name="Actualiser", exact=True)
                    expect(refresh).to_be_visible()
                    expect(refresh.locator("svg")).to_be_visible()
                    expect(refresh).to_have_attribute("title", "Actualiser")
                else:
                    expect(summary).to_be_hidden()
            browser.close()
    finally:
        server.should_exit = True
        thread.join(5)
