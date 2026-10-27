"""Opt-in browser coverage of the Search page against a fake c411."""

import os
import socket
import threading
import time

import httpx
import pytest

from tests.test_web_jobs import Client
from tests.test_web_search import HASHES, POSTER, fake_net

pytestmark = pytest.mark.skipif(os.getenv("TL_WEB_BROWSER") != "1", reason="opt-in browser test")


def serve(tmp_path):
    import uvicorn

    from torrentlinker.web.app import create_app

    app = create_app(
        tmp_path / "config", password="test-password-long", connector=lambda *a: Client()
    )
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.02)
    base = f"http://127.0.0.1:{port}"
    with httpx.Client(base_url=base, headers={"X-TorrentLinker": "1"}) as setup:
        assert setup.post("/api/login", json={"password": "test-password-long"}).status_code == 200
        setup.post("/api/setup/client", json={"client": "deluge", "host": "https://box.example"})
        saved = setup.post(
            "/api/setup/indexer", json={"url": "https://c411.org/api", "api_key": "private-key"}
        )
        assert saved.status_code == 200, saved.text
    return server, base


def open_search(playwright, base, locale="en-US", scheme="light"):
    browser = playwright.chromium.launch()
    page = browser.new_page(
        viewport={"width": 1280, "height": 900}, locale=locale, color_scheme=scheme
    )
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(base + "/")
    page.locator("#login-password").fill("test-password-long")
    page.locator("#login-form button").click()
    page.locator("[data-view=search]").click()
    return browser, page, errors


def test_search_page_pills_filters_sort_pages_and_density(tmp_path, monkeypatch):
    from playwright.sync_api import expect, sync_playwright

    seen: list = []
    fake_net(monkeypatch, seen)
    server, base = serve(tmp_path)
    listing = lambda: [r.url.params for r in seen if r.url.path == "/api/torrents"]  # noqa: E731

    def until(check, timeout=6):
        deadline = time.time() + timeout
        while time.time() < deadline and not check():
            time.sleep(0.1)
        assert check()

    try:
        with sync_playwright() as playwright:
            browser, page, errors = open_search(playwright, base)
            pills = page.locator("#search-pills")
            expect(pills.get_by_role("button", name="Films & Vidéos")).to_be_visible()
            page.locator("#search-query").fill("film")
            page.locator("#search-form .primary").click()
            rows = page.locator("#search-table .sr-row")
            expect(rows).to_have_count(2)
            expect(rows.first).to_contain_text("Title 1")
            expect(rows.first).to_contain_text("MULTI.VFF")
            expect(rows.first).to_contain_text("1080p")
            expect(rows.first).to_contain_text("up1")
            expect(page.locator("#search-summary")).to_contain_text("137,565 torrents")
            expect(pills.get_by_role("button", name="Films & Vidéos")).to_contain_text("138,013")
            # Posters come through this server, never straight from TMDB.
            expect(rows.first.locator("img")).to_have_attribute(
                "src", f"api/poster?url={POSTER.replace(':', '%3A').replace('/', '%2F')}"
            )
            # Numbered pages and sort chips search again.
            expect(page.locator("#search-pages-top")).to_contain_text("400")
            page.locator("#search-pages-top").get_by_role("button", name="Page 2").click()
            expect(page.locator("#search-pages-top [aria-current=page]")).to_have_text("2")
            until(lambda: listing()[-1]["page"] == "2")
            page.locator("#search-sort").get_by_role("button", name="Seeders").click()
            expect(page.locator("#search-sort [aria-pressed=true]")).to_contain_text("Seeders")
            until(
                lambda: (
                    listing()[-1]["sortBy"] == "seeders" and listing()[-1]["sortOrder"] == "desc"
                )
            )
            page.locator("#search-sort").get_by_role("button", name="Seeders").click()
            expect(page.locator("#search-sort [aria-pressed=true]")).to_contain_text("↑")
            until(lambda: listing()[-1]["sortOrder"] == "asc")
            # A pill picks the category and searches at once.
            pills.get_by_role("button", name="Films & Vidéos").click()
            expect(pills.locator("[aria-pressed=true]")).to_contain_text("Films & Vidéos")
            until(lambda: listing()[-1].get("category") == "1")
            # A filter dropdown searches by itself after a pause.
            page.locator("#search-facets summary", has_text="Resolution").click()
            page.locator("#search-facets .fdrop[open] label", has_text="1080p").locator(
                "input"
            ).check()
            until(lambda: listing()[-1].get("resolution") == "1080p")
            expect(page.locator("#search-facets summary", has_text="Resolution")).to_contain_text(
                "· 1"
            )
            page.keyboard.press("Escape")  # an open panel covers the buttons under it
            expect(page.locator("#search-facets .fdrop[open]")).to_have_count(0)
            # Team is a free-text filter.
            page.locator("#search-facets summary", has_text="Team").click()
            page.locator("#search-facets .fdrop[open] input").fill("bouba")
            until(lambda: listing()[-1].get("team") == "bouba")
            # Selecting a row shows the selection bar.
            expect(page.locator("#search-selection")).to_be_hidden()
            page.locator("#search-table .sr-row").first.locator("input[type=checkbox]").check()
            expect(page.locator("#search-selection")).to_contain_text("1 selected")
            # Compact keeps the table and remembers the choice.
            page.locator("#search-density-compact").click()
            expect(page.locator("#search-table table")).to_be_visible()
            expect(page.locator("#search-table th", has_text="Leechers")).to_be_visible()
            page.reload()
            page.locator("[data-view=search]").click()
            expect(page.locator("#search-density-compact")).to_have_attribute(
                "aria-pressed", "true"
            )
            assert errors == []
            browser.close()
    finally:
        server.should_exit = True
    assert HASHES
