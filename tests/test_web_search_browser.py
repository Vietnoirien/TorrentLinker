"""Opt-in browser coverage of the Search page against a fake c411."""

import os
import re
import socket
import threading
import time

import httpx
import pytest

from tests.shell_support import shell_navigate
from tests.test_web_jobs import Client
from tests.test_web_search import HASHES, fake_net

pytestmark = pytest.mark.skipif(os.getenv("TL_WEB_BROWSER") != "1", reason="opt-in browser test")


def serve(tmp_path, roots=(), connector=None):
    import uvicorn

    from torrentlinker.web.app import create_app

    app = create_app(
        tmp_path / "config",
        password="test-password-long",
        connector=connector or (lambda *a: Client()),
        roots=roots,
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
    shell_navigate(page, "search")
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
            panel = page.frame_locator("#search-frame")
            pills = panel.locator("#search-pills")
            expect(pills.get_by_role("button", name="Films & Vidéos")).to_be_visible()
            panel.locator("#search-query").fill("film")
            panel.locator("#search-form .primary").click()
            rows = panel.locator("#search-table .sr-row")
            expect(rows).to_have_count(2)
            expect(rows.first).to_contain_text("Title 1")
            expect(rows.first).to_contain_text("MULTI.VFF")
            expect(rows.first).to_contain_text("1080p")
            expect(rows.first).to_contain_text("up1")
            expect(panel.locator("#search-summary")).to_contain_text("137,565 torrents")
            expect(pills.get_by_role("button", name="Films & Vidéos")).to_contain_text("138,013")
            # Posters come through this server, never straight from TMDB.
            expect(rows.first.locator("img")).to_have_attribute(
                "src", re.compile("^data:image/png;base64,")
            )
            # Resting the pointer on a row opens c411's card; leaving closes it.
            rows.first.hover()
            card = panel.locator(".hover-card")
            expect(card).to_be_visible()
            expect(card).to_contain_text("Release.1.2020")
            expect(card).to_contain_text("2020 · 1h59 · Jake Kasdan")
            expect(card).to_contain_text("Aventure")
            expect(card).to_contain_text("Dwayne Johnson")
            expect(card.locator(".hc-poster")).to_have_attribute("src", re.compile("^data:image/"))
            page.mouse.move(5, 5)
            expect(card).to_be_hidden()
            # Numbered pages and sort chips search again.
            expect(panel.locator("#search-pages-top")).to_contain_text("400")
            panel.locator("#search-pages-top").get_by_role("button", name="Page 2").click()
            expect(panel.locator("#search-pages-top [aria-current=page]")).to_have_text("2")
            until(lambda: listing()[-1]["page"] == "2")
            panel.locator("#search-sort").get_by_role("button", name="Seeders").click()
            expect(panel.locator("#search-sort [aria-pressed=true]")).to_contain_text("Seeders")
            until(
                lambda: (
                    listing()[-1]["sortBy"] == "seeders" and listing()[-1]["sortOrder"] == "desc"
                )
            )
            panel.locator("#search-sort").get_by_role("button", name="Seeders").click()
            expect(panel.locator("#search-sort [aria-pressed=true]")).to_contain_text("↑")
            until(lambda: listing()[-1]["sortOrder"] == "asc")
            # A pill picks the category and searches at once.
            pills.get_by_role("button", name="Films & Vidéos").click()
            expect(pills.locator("[aria-pressed=true]")).to_contain_text("Films & Vidéos")
            until(lambda: listing()[-1].get("category") == "1")
            # A filter dropdown searches by itself after a pause.
            panel.locator("#search-facets summary", has_text="Resolution").click()
            panel.locator("#search-facets .fdrop[open] label", has_text="1080p").locator(
                "input"
            ).check()
            until(lambda: listing()[-1].get("resolution") == "1080p")
            expect(panel.locator("#search-facets summary", has_text="Resolution")).to_contain_text(
                "· 1"
            )
            page.keyboard.press("Escape")  # an open panel covers the buttons under it
            expect(panel.locator("#search-facets .fdrop[open]")).to_have_count(0)
            # Team is a free-text filter.
            panel.locator("#search-facets summary", has_text="Team").click()
            panel.locator("#search-facets .fdrop[open] input").fill("bouba")
            until(lambda: listing()[-1].get("team") == "bouba")
            # Selecting a row shows the selection bar.
            expect(panel.locator("#search-selection")).to_be_hidden()
            panel.locator("#search-table .sr-row").first.locator("input[type=checkbox]").check()
            expect(panel.locator("#search-selection")).to_contain_text("1 selected")
            # Compact keeps the table and remembers the choice.
            panel.locator("#search-density-compact").click()
            expect(panel.locator("#search-table table")).to_be_visible()
            expect(panel.locator("#search-table th", has_text="Leechers")).to_be_visible()
            # Compact follows c411: the name carries its tags and a header sorts the search.
            first = panel.locator("#search-table tbody tr").first
            expect(first.locator(".type-badge")).to_have_text("FILM")
            expect(first).to_contain_text("Multi (Français inclus)")
            panel.locator("#search-table th").get_by_role("button", name="Leechers").click()
            until(lambda: listing()[-1].get("sortBy") == "leechers")
            # The details tab shows c411's page: header, banner, facts, TMDB card, trust.
            panel.locator("#search-table .sr-release").first.click()
            dialog = panel.locator(".torrent-detail:visible")
            expect(dialog).to_contain_text("Sent by up1")
            expect(dialog).to_contain_text("Team BOUBA")
            expect(dialog.locator(".dt-banner")).to_contain_text("not tested")
            expect(dialog.locator(".dt-badge")).to_have_text("FILM")
            expect(dialog).to_contain_text("Seeds wanted")
            expect(dialog.locator(".dt-card")).to_contain_text("Title 1 (2020)")
            expect(dialog.locator(".dt-trust")).to_contain_text("Community trust")
            expect(dialog.locator("details", has_text="Show the NFO")).to_be_visible()
            expect(dialog.locator(".dt-poster")).to_have_attribute(
                "src", re.compile("^data:image/")
            )
            panel.locator("#detail-tabs [role=tab]").first.click()
            page.reload()
            shell_navigate(page, "search")
            expect(panel.locator("#search-density-compact")).to_have_attribute(
                "aria-pressed", "true"
            )
            assert errors == []
            browser.close()
    finally:
        server.should_exit = True
    assert HASHES


@pytest.mark.parametrize("locale,scheme", [("en-US", "dark"), ("fr-FR", "light")])
def test_shared_search_panel_preserves_results_when_visiting_queue(
    tmp_path, monkeypatch, locale, scheme
):
    from playwright.sync_api import expect, sync_playwright

    fake_net(monkeypatch, [])
    server, base = serve(tmp_path)
    try:
        with sync_playwright() as playwright:
            browser, page, errors = open_search(playwright, base, locale, scheme)
            panel = page.frame_locator("#search-frame")
            expect(panel.locator("#search-query")).to_be_visible()
            panel.locator("#search-query").fill("film")
            panel.locator("#search-form .primary").click()
            expect(panel.locator(".sr-row")).to_have_count(2)
            if folder := os.getenv("TL_SEARCH_SCREENSHOTS"):
                from pathlib import Path

                Path(folder).mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(Path(folder) / f"search-web-{locale}-{scheme}.png"))
            panel.locator("#search-queue-link").click()
            expect(panel.locator("#start-selected-queue")).to_be_visible()
            panel.locator("#back-results").click()
            expect(panel.locator("#search-query")).to_have_value("film")
            expect(panel.locator(".sr-row")).to_have_count(2)
            polls = []
            page.on(
                "request",
                lambda request: (
                    polls.append(request.url)
                    if "/api/search/workspace/state" in request.url
                    else None
                ),
            )
            shell_navigate(page, "setup")
            page.wait_for_timeout(250)
            before = len(polls)
            # A hidden frame can deliver a poll queued before it became inactive.
            panel.locator("body").evaluate("() => request('state').catch(() => null)")
            page.wait_for_timeout(2200)
            assert len(polls) == before
            assert not errors
            browser.close()
    finally:
        server.should_exit = True


def test_missing_category_folder_is_picked_once_and_reused(tmp_path, monkeypatch):
    from playwright.sync_api import expect, sync_playwright

    from torrentlinker.domain import Torrent

    fake_net(
        monkeypatch,
        [],
        caps=(
            '<caps><categories><category id="2000" name="Films">'
            '<subcat id="2030" name="Film"/></category></categories></caps>'
        ),
    )
    target = tmp_path / "films"
    target.mkdir()
    (target / "sample.mkv").write_bytes(b"test")

    class MountedClient(Client):
        def torrents(self, **kwargs):
            return [Torrent("d" * 40, "sample", target, size=4)]

        def files(self, infohash):
            return {"sample.mkv": 4}

    server, base = serve(tmp_path, roots=(target,), connector=lambda *a: MountedClient())
    try:
        with sync_playwright() as playwright:
            browser, page, errors = open_search(playwright, base)
            panel = page.frame_locator("#search-frame")
            panel.locator("#search-query").fill("film")
            panel.locator("#search-form .primary").click()
            expect(panel.locator(".sr-row")).to_have_count(2)
            panel.locator(".sr-row input").first.check()
            panel.locator("#queue-search").click()
            expect(panel.locator("#folder-dialog")).to_be_visible()
            panel.locator("#folder-dialog .path-row button").click()
            panel.locator("#picker").get_by_role("button", name=str(target), exact=True).click()
            panel.locator("#picker").get_by_role(
                "button", name="Choose this folder", exact=True
            ).click()
            expect(panel.locator("#folder-dialog input")).to_have_value(str(target))
            panel.locator("#folder-dialog .primary").click()
            try:
                expect(panel.locator("#search-queue-link")).to_contain_text("(1)")
            except AssertionError:
                print(panel.locator("body").inner_text())
                raise
            starts = []
            page.route(
                "**/api/search/workspace/start?**",
                lambda route: (
                    starts.append(route.request.post_data_json),
                    route.fulfill(json={"job": "simulated"}),
                ),
            )
            panel.locator(".sr-title").nth(1).click()
            panel.get_by_role("button", name="Download now", exact=True).click()
            expect(panel.locator("#queue-table")).to_contain_text("Release.2")
            assert len(starts) == 1 and len(starts[0]["keys"]) == 1
            chosen = panel.locator("#queue-table tr[data-key]").filter(has_text="Release.2")
            assert chosen.get_attribute("data-key") == starts[0]["keys"][0]
            expect(panel.locator("#search-queue-link")).to_contain_text("(2)")
            expect(panel.locator("#folder-dialog")).not_to_be_visible()
            expect(panel.locator("#queue-table")).to_contain_text(str(target))
            assert not errors
            browser.close()
    finally:
        server.should_exit = True


@pytest.mark.parametrize("check", ["empty-peer-bar", "visible-note"])
def test_search_zero_peer_bar_and_visible_torrent_note(tmp_path, monkeypatch, check):
    from playwright.sync_api import expect, sync_playwright

    from tests import test_web_search

    listing = test_web_search.c411_listing

    def zero_peers(request):
        result = listing(request)
        result["data"][0]["seeders"] = 0
        result["data"][0]["leechers"] = 0
        return result

    monkeypatch.setattr(test_web_search, "c411_listing", zero_peers)
    fake_net(monkeypatch, [])
    server, base = serve(tmp_path)
    try:
        with sync_playwright() as playwright:
            browser, page, errors = open_search(playwright, base)
            panel = page.frame_locator("#search-frame")
            panel.locator("#search-query").fill("film")
            panel.locator("#search-form .primary").click()
            row = panel.locator(".sr-row").first
            expect(row).to_be_visible()
            if folder := os.getenv("TL_SEARCH_SCREENSHOTS"):
                from pathlib import Path

                Path(folder).mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(Path(folder) / "search-zero-peers.png"))
            if check == "empty-peer-bar":
                bar = row.locator(".seedbar")
                assert bar.bounding_box()["height"] <= 5
            else:
                expect(row.locator(".sr-zen")).to_contain_text("Note")
            assert not errors
            browser.close()
    finally:
        server.should_exit = True


def test_entering_search_loads_latest_once_and_keeps_results_on_return(tmp_path, monkeypatch):
    from playwright.sync_api import expect, sync_playwright

    seen = []
    fake_net(monkeypatch, seen)
    server, base = serve(tmp_path)
    try:
        with sync_playwright() as playwright:
            browser, page, errors = open_search(playwright, base)
            panel = page.frame_locator("#search-frame")
            expect(panel.locator(".sr-row")).to_have_count(2)
            listings = lambda: [r for r in seen if r.url.path == "/api/torrents"]  # noqa: E731
            assert len(listings()) == 1
            panel.locator("#search-queue-link").click()
            panel.locator("#back-results").click()
            expect(panel.locator(".sr-row")).to_have_count(2)
            shell_navigate(page, "setup")
            shell_navigate(page, "search")
            expect(panel.locator(".sr-row")).to_have_count(2)
            page.wait_for_timeout(500)
            assert len(listings()) == 1
            assert not errors
            browser.close()
    finally:
        server.should_exit = True


def test_torrent_details_open_in_shared_tabs_and_return_to_search(tmp_path, monkeypatch):
    from playwright.sync_api import expect, sync_playwright

    fake_net(monkeypatch, [])
    server, base = serve(tmp_path)
    try:
        with sync_playwright() as playwright:
            browser, page, errors = open_search(playwright, base)
            panel = page.frame_locator("#search-frame")
            expect(panel.locator(".sr-row")).to_have_count(2)
            panel.locator(".sr-title").first.click()
            try:
                expect(panel.locator(".torrent-detail:visible")).to_contain_text("Sent by up1")
            except AssertionError:
                print(errors, panel.locator("body").inner_text())
                raise
            expect(panel.locator("#detail-tabs [role=tab]")).to_have_count(2)
            panel.locator("#detail-tabs [role=tab]").first.click()
            panel.locator(".sr-title").nth(1).click()
            expect(panel.locator("#detail-tabs [role=tab]")).to_have_count(3)
            panel.locator("#detail-tabs [role=tab]").last.focus()
            page.keyboard.press("ArrowLeft")
            expect(panel.locator(".torrent-detail:visible .dt-title")).to_contain_text("Release.1")
            page.frame_locator("#shell-navigation-frame").locator("#language").select_option("fr")
            expect(panel.locator(".torrent-detail:visible")).to_contain_text(
                "Télécharger maintenant"
            )
            expect(panel.locator(".torrent-detail:visible")).to_contain_text("Envoyé par up1")
            page.frame_locator("#shell-navigation-frame").locator("#language").select_option("en")
            expect(panel.locator(".torrent-detail:visible")).to_contain_text("Download now")
            panel.locator(".detail-tab").nth(2).drag_to(panel.locator(".detail-tab").nth(1))
            expect(panel.locator("#detail-tabs [role=tab]").nth(1)).to_contain_text("Release.2")
            panel.locator("#detail-tabs [aria-label='Close tab']").first.click()
            expect(panel.locator("#detail-tabs [role=tab]")).to_have_count(2)
            panel.locator("#detail-tabs [role=tab]").first.click()
            expect(panel.locator(".sr-row")).to_have_count(2)
            assert not errors
            browser.close()
    finally:
        server.should_exit = True


def test_details_inline_image_retry_and_language_changes(tmp_path, monkeypatch):
    from playwright.sync_api import expect, sync_playwright

    from tests.test_web_search import DETAIL, POSTER

    monkeypatch.setitem(DETAIL, "description", f'<p>Synopsis</p><img src="{POSTER}">')
    fake_net(monkeypatch, [])
    server, base = serve(tmp_path)
    try:
        with sync_playwright() as playwright:
            browser, page, errors = open_search(playwright, base)
            attempts = []

            def unavailable_once(route):
                attempts.append(route.request.post_data_json)
                if len(attempts) == 1:
                    route.fulfill(json={"error": "Image unavailable", "retry_after": 0})
                else:
                    route.continue_()

            page.route("**/api/search/workspace/detail-image?**", unavailable_once)
            panel = page.frame_locator("#search-frame")
            panel.locator(".sr-title").first.click()
            expect(panel.locator(".detail-image-error")).to_contain_text("Image unavailable")
            panel.get_by_role("button", name="Retry images", exact=True).click()
            expect(panel.locator(".description img")).to_be_visible()
            expect(panel.locator(".description img")).to_have_attribute(
                "src", re.compile("^data:image/png")
            )
            expect(panel.locator(".detail-image-error")).to_have_count(0)
            assert len(attempts) == 2
            for language in ("fr", "en"):
                page.frame_locator("#shell-navigation-frame").locator("#language").select_option(
                    language
                )
                for theme in ("dark", "light"):
                    page.frame_locator("#shell-navigation-frame").locator("#theme").select_option(
                        theme
                    )
                    expect(panel.locator(".torrent-detail:visible .dt-bar")).to_contain_text(
                        "Télécharger maintenant" if language == "fr" else "Download now"
                    )
                    if target := os.getenv("TL_SEARCH_SCREENSHOTS"):
                        from pathlib import Path

                        Path(target).mkdir(parents=True, exist_ok=True)
                        page.screenshot(
                            path=str(Path(target) / f"details-web-{language}-{theme}.png")
                        )
            assert not errors
            browser.close()
    finally:
        server.should_exit = True
