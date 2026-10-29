"""Desktop planning capabilities remain usable through the visible WebUI."""

import os
import socket
import threading
import time
from pathlib import Path

import pytest

from tests.test_web_plan_execution import prepared, second_client
from torrentlinker.web.app import create_app

pytestmark = pytest.mark.skipif(os.getenv("TL_WEB_BROWSER") != "1", reason="opt-in browser test")


def test_review_sort_send_and_resume_plan_in_browser(tmp_path):
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    config, setup, client, rows = prepared(tmp_path)
    profile, second = second_client(tmp_path, setup, client)
    app = create_app(
        config, password="test-password-long", service_override=setup, monitor_verifications=False
    )
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
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1600, "height": 1100}, locale="en-US")
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/")
            page.locator("#login-password").fill("test-password-long")
            page.locator("#login-form button").click()
            page.locator("[data-view=zen]").first.click()
            page.locator("#zen-plan-tab").click()
            expect(page.locator("#plan-send")).to_be_disabled()
            page.locator("#plan-limit-count").check()
            page.locator("#plan-cached").check()
            page.locator("#plan-category").select_option(["7000"])
            page.locator("#plan-count").fill("2000")
            page.locator("#plan").click()
            expect(page.locator("#plan-summary")).to_contain_text("paid back", timeout=15000)
            expect(page.locator("#plan-storage")).to_contain_text("Reserved")
            expect(page.locator("#plan-result tbody tr")).to_have_count(3)
            expect(page.locator("#plan-times")).to_contain_text("Sending")
            page.locator("#plan-sort").select_option("title")
            expect(page.locator("#plan-result tbody tr").first).to_contain_text("Alpha")
            page.locator("#plan-budget").fill("12")
            expect(page.locator("#plan-send")).to_be_disabled()
            page.locator("#plan").click()
            expect(page.locator("#plan-send")).to_be_enabled(timeout=15000)
            page.locator("#plan-result thead input").uncheck()
            page.locator("#plan-result tbody input").first.check()
            page.locator("#plan-send").click()
            expect(page.locator("#dialog")).to_contain_text("1 download")
            assert client.downloads == []
            page.locator("#dialog").get_by_role("button", name="Send selected", exact=True).click()
            expect(page.locator("#plan-result tbody tr")).to_have_count(2, timeout=15000)
            assert len(client.downloads) == 1
            page.reload()
            page.locator("[data-view=zen]").first.click()
            page.locator("#zen-plan-tab").click()
            expect(page.locator("#plan-result tbody tr")).to_have_count(2)
            expect(page.locator("#plan-count")).to_have_value("2000")
            expect(page.locator("#plan-budget")).to_have_value("12")
            page.locator(f'input[data-budget-id="{profile.id}"]').fill("0.5")
            page.locator("#plan-folders").click()
            expect(page.locator("#dialog")).to_contain_text("TorrentLinker host")
            page.locator('#dialog select[aria-label="Torrent Client"]').select_option(profile.id)
            expect(
                page.locator('#dialog input[aria-label="Folder on the TorrentLinker host"]')
            ).to_have_value(profile.download_folders.default)
            page.locator("#dialog").get_by_role("button", name="Save folder", exact=True).click()
            expect(page.locator("#dialog")).to_contain_text(
                "Folder verified and saved", timeout=15000
            )
            page.keyboard.press("Escape")
            expect(page.locator(f'input[data-budget-id="{profile.id}"]')).to_have_value("0.5")
            expect(page.locator("#plan-send")).to_be_disabled()
            page.locator("#theme").select_option("dark")
            page.locator("#plan-cached").check()
            page.locator("#plan").click()
            expect(page.locator("#plan-send")).to_be_enabled(timeout=15000)
            if destination := os.getenv("TL_WEB_SCREENSHOTS"):
                Path(destination).mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(Path(destination) / "web-plan-parity.png"), full_page=True)
            page.locator("#language").select_option("fr")
            expect(page.locator("#plan-summary")).to_contain_text("amorti")
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            if destination := os.getenv("TL_WEB_SCREENSHOTS"):
                page.screenshot(
                    path=str(Path(destination) / "web-plan-mobile-fr.png"), full_page=True
                )
            # A Catalogue fetch belongs to the shared cache even after changing clients.
            import httpx

            from torrentlinker.indexer import Indexer

            entered, release = threading.Event(), threading.Event()

            def catalogue_response(request):
                entered.set()
                assert release.wait(10)
                return httpx.Response(200, text="<rss><channel></channel></rss>")

            setup.settings.indexer.url = "https://tracker.example/api"
            setup._indexer = Indexer(
                setup.settings.indexer.url,
                "test-key",
                cache=setup.store,
                http=httpx.Client(transport=httpx.MockTransport(catalogue_response)),
            )
            page.set_viewport_size({"width": 1600, "height": 1100})
            page.locator("#zen-catalogue-tab").click()
            page.locator("#catalogue").click()
            try:
                assert entered.wait(5)
                page.locator("#target-client").select_option(profile.id)
                expect(page.locator("#catalogue")).to_be_disabled()
                page.locator("#catalogue-pause").click()
            finally:
                release.set()
            expect(page.locator("#catalogue")).to_be_enabled(timeout=15000)
            expect(page.locator("#catalogue-pause")).to_be_hidden()
            assert not errors
            browser.close()
    finally:
        server.should_exit = True
        thread.join(5)
