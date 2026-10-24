"""Opt-in real-browser tests against a temporary server and fake Torrent Client."""

import os
import socket
import threading
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.getenv("TL_WEB_BROWSER") != "1", reason="opt-in browser test")


def test_guided_setup_and_management_on_small_screen(tmp_path: Path):
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    from torrentlinker.client_folders import ClientFolder
    from torrentlinker.domain import Torrent
    from torrentlinker.web.app import create_app

    class Client:
        def __init__(self):
            self.paused = False

        def check(self):
            return "qBittorrent test"

        def folder_settings(self):
            return [ClientFolder("", "/downloads", "default")]

        def torrents(self, **kwargs):
            return [
                Torrent(
                    "a" * 40,
                    "Example book.epub",
                    Path("/downloads"),
                    size=1048576,
                    state="pausedUP" if self.paused else "uploading",
                    connected_seeds=3,
                    connected_peers=2,
                )
            ]

        def torrent(self, hash, **kwargs):
            return self.torrents()[0]

        def pause(self, hash):
            self.paused = True

    client = Client()
    app = create_app(
        tmp_path / "config", password="test-password-long", connector=lambda *args: client
    )
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
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
            page = browser.new_page(viewport={"width": 1100, "height": 850}, locale="en-US")
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"http://127.0.0.1:{port}/")
            page.locator("#login-password").fill("test-password-long")
            page.locator("#login-form button").click()
            expect(page.locator("#view-setup")).to_be_visible()
            page.locator("#client-host").fill("https://seedbox.example/qbittorrent/")
            page.locator("#client-username").fill("reader")
            page.locator("#client-password").fill("client-password")
            page.locator("#test-client").click()
            expect(page.locator("#client-result")).to_contain_text("qBittorrent test")
            screenshot = os.getenv("TL_WEB_SCREENSHOTS")
            if screenshot:
                Path(screenshot).mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(Path(screenshot) / "setup-en.png"))
                page.locator("#language").select_option("fr")
                page.screenshot(path=str(Path(screenshot) / "setup-fr.png"))
                page.locator("#language").select_option("en")
            page.locator("#client-form button.primary").click()
            expect(page.locator("#step-storage")).to_be_visible()
            expect(page.locator("#import-folders")).to_contain_text("/downloads")
            if screenshot:
                for lang in ("fr", "en"):
                    page.locator("#language").select_option(lang)
                    page.screenshot(path=str(Path(screenshot) / f"storage-{lang}.png"))
            page.locator("#step-storage [data-i18n=skipStorage]").click()
            page.locator("#step-indexer [data-i18n=skip]").click()
            expect(page.locator("#capabilities")).to_contain_text("Torrent management")
            page.locator("#finish-setup").click()
            expect(page.locator("#torrent-table")).to_contain_text("Example book.epub")
            page.locator("#torrent-table tbody input[type=checkbox]").check()
            page.locator("[data-action=pause]").click()
            expect(page.locator("#torrent-table")).to_contain_text("paused", timeout=10000)
            if screenshot:
                for lang in ("fr", "en"):
                    page.locator("#language").select_option(lang)
                    page.screenshot(path=str(Path(screenshot) / f"torrents-{lang}.png"))
            page.locator("[data-view=documentation]").click()
            expect(page.locator("#guide-content")).to_contain_text("Read guides inside the app")
            page.locator("#guide-select").select_option("guide/en/torrents.md")
            expect(page.locator("#guide-content h1")).to_have_text("Manage torrents")
            page.wait_for_function(
                "Array.from(document.querySelectorAll('#guide-content img'))"
                ".every(i => i.complete && i.naturalWidth > 0)"
            )
            if screenshot:
                page.screenshot(path=str(Path(screenshot) / "documentation-en.png"))
            page.locator("#guide-back").click()
            expect(page.locator("#guide-content")).to_contain_text("Read guides inside the app")
            page.locator("#language").select_option("fr")
            expect(page.locator("#guide-content")).to_contain_text("Consulter les guides")
            if screenshot:
                page.locator("#guide-select").select_option("guide/fr/torrents.md")
                expect(page.locator("#guide-content h1")).to_have_text("Gérer les torrents")
                page.wait_for_function(
                    "Array.from(document.querySelectorAll('#guide-content img'))"
                    ".every(i => i.complete && i.naturalWidth > 0)"
                )
                page.screenshot(path=str(Path(screenshot) / "documentation-fr.png"))
            page.set_viewport_size({"width": 600, "height": 800})
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            page.locator("#language").select_option("en")
            page.locator("[data-view=torrents]").click()
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            page.locator("#theme").select_option("dark")
            if screenshot:
                page.wait_for_timeout(250)
                page.screenshot(path=str(Path(screenshot) / "torrents-small.png"))
            assert not errors, errors
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)
