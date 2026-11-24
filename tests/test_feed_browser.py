"""Opt-in browser coverage of RSS discovery and preview, against a fake source."""

import os
import re
import socket
import threading
import time

import pytest

from tests.shell_support import shell_navigate

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
            shell_navigate(page, "feeds")
            page.frame_locator("#feeds-frame").locator("#feeds-empty").get_by_role(
                "button", name="New subscription"
            ).click()
            editor = page.frame_locator("#feeds-frame").locator("#dialog-content")
            editor.get_by_label("Name", exact=True).fill("Films")
            editor.get_by_label("Title contains", exact=True).fill("film")
            expect(editor.locator(".feed-strip")).to_contain_text("Would match now: 1 of 1")
            editor.get_by_role("button", name="Save", exact=True).click()
            films = (
                page.frame_locator("#feeds-frame")
                .locator("#feeds-sidebar")
                .get_by_role("button", name=re.compile("^Films"))
            )
            films.click()
            page.frame_locator("#feeds-frame").locator("#feeds-header").get_by_role(
                "button", name="Refresh now"
            ).click()
            expect(page.frame_locator("#feeds-frame").locator("#feeds-results")).to_contain_text(
                "Baseline film"
            )
            source.rows = [release("b", title="New film"), release(title="Baseline film")]
            page.frame_locator("#feeds-frame").locator("#feeds-header").get_by_role(
                "button", name="Refresh now"
            ).click()
            expect(page.frame_locator("#feeds-frame").locator("#feeds-sidebar")).to_contain_text(
                "Films"
            )
            expect(
                page.frame_locator("#feeds-frame").locator("#feeds-sidebar .feed-row-badge").nth(1)
            ).to_have_text("1")
            expect(page.frame_locator("#feeds-frame").locator("#feeds-actions")).to_be_hidden()
            row = (
                page.frame_locator("#feeds-frame")
                .locator("#feeds-results tbody tr")
                .filter(has_text="New film")
            )
            row.locator("input[type=checkbox]").check()
            expect(page.frame_locator("#feeds-frame").locator("#feeds-actions")).to_contain_text(
                "1 selected"
            )
            page.frame_locator("#feeds-frame").locator("#feeds-actions").get_by_role(
                "button", name="Save selection", exact=True
            ).click()
            expect(page.frame_locator("#feeds-frame").locator("#dialog-content")).to_contain_text(
                "New film"
            )
            page.frame_locator("#feeds-frame").locator("#dialog .close").click()
            page.frame_locator("#feeds-frame").locator("#feeds-header").get_by_label(
                "More", exact=True
            ).click()
            page.frame_locator("#feeds-frame").get_by_role(
                "menuitem", name="Saved selections", exact=True
            ).click()
            page.frame_locator("#feeds-frame").locator("#dialog-content").get_by_role(
                "button"
            ).first.click()
            expect(page.frame_locator("#feeds-frame").locator("#dialog-content")).to_contain_text(
                "New film"
            )
            expect(
                page.frame_locator("#feeds-frame")
                .locator("#dialog-content")
                .get_by_role("button", name="Queue selected", exact=True)
            ).to_be_visible()
            page.frame_locator("#feeds-frame").locator("#dialog .close").click()
            # An inbox-only release keeps RSS's destination-selection flow.
            page.frame_locator("#feeds-frame").locator("#feeds-results tbody tr").filter(
                has_text="New film"
            ).get_by_role("button").first.click()
            panel = page.frame_locator("#search-frame")
            expect(panel.locator(".dt-title")).to_contain_text("New film")
            expect(panel.get_by_role("button", name="Download now", exact=True)).to_have_count(0)
            panel.get_by_role("button", name="Add to queue", exact=True).click()
            expect(page.frame_locator("#feeds-frame").locator("#dialog-content")).to_contain_text(
                "Queue selected releases"
            )
            page.frame_locator("#feeds-frame").locator("#dialog .close").click()
            shell_navigate(page, "search")
            panel = page.frame_locator("#search-frame")
            panel.locator("#detail-tabs [role=tab]").first.click()
            panel.locator("#search-query").fill("A new title")
            panel.locator("#subscribe-search").click()
            expect(
                page.frame_locator("#feeds-frame")
                .locator("#dialog-content")
                .get_by_label("Title contains", exact=True)
            ).to_have_value("A new title")
            assert errors == []
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def test_rss_editor_chips_judge_fetched_releases(tmp_path):
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    from tests.test_feeds import Source, release
    from torrentlinker.web.app import create_app

    app = create_app(tmp_path / "config", password="test-password-long")
    from torrentlinker.downloads import IndexerCategory

    source = Source()
    source.rows = [
        release("a", title="Good.1080p", metadata={"quality": "1080p"}),
        release("b", title="Other.720p", metadata={"quality": "720p"}),
    ]
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
    app.state.agent_service.feed_control.service.setup.settings.indexer_categories = {
        2030: IndexerCategory("Films"),
        7020: IndexerCategory("Books"),
        1000: IndexerCategory("Games"),
        3010: IndexerCategory("Music"),
        4050: IndexerCategory("Applications"),
    }
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={"width": 1250, "height": 900}, locale="en-US")
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"http://127.0.0.1:{port}/")
            page.locator("#login-password").fill("test-password-long")
            page.locator("#login-form button").click()
            shell_navigate(page, "feeds")
            page.frame_locator("#feeds-frame").locator("#feeds-empty").get_by_role(
                "button", name="New subscription"
            ).click()
            editor = page.frame_locator("#feeds-frame").locator("#dialog-content")
            page.wait_for_timeout(1500)  # Includes the source debounce interval.
            expect(editor.locator(".feed-strip")).to_have_text("")
            expect(editor.locator(".feed-chip").filter(has_text="720p")).to_have_count(0)
            editor.get_by_role("button", name="Books", exact=True).click()
            expect(editor.locator(".feed-chip").filter(has_text="720p")).to_have_count(0)
            editor.get_by_role("button", name="Books", exact=True).click()
            for category, expected in (
                ("Games", ["Platform"]),
                ("Music", ["Format", "Bitrate"]),
                ("Applications", ["Platform", "License"]),
            ):
                editor.get_by_role("button", name=category, exact=True).click()
                labels = editor.locator(".feed-chip-label").all_text_contents()
                assert len(labels) == len(expected)
                assert all(any(label.startswith(name) for label in labels) for name in expected)
                expect(editor.locator(".feed-chip").filter(has_text="720p")).to_have_count(0)
                editor.get_by_role("button", name=category, exact=True).click()
            editor.get_by_role("button", name="Films", exact=True).click()
            editor.get_by_role("button", name="Check again", exact=True).click()
            expect(editor.locator(".feed-strip")).to_contain_text("Would match now: 2 of 2")
            chip = editor.locator(".feed-chip").filter(has_text="720p")
            chip.click()
            expect(editor.locator(".feed-chip.prefer")).to_have_text("♡ 1. 720p")
            expect(editor.locator(".feed-chip.prefer")).to_be_focused()
            editor.locator(".feed-chip.prefer").click()
            expect(editor.locator(".feed-chip.must")).to_have_text("✓ 720p")
            expect(editor.locator(".feed-strip")).to_contain_text("Would match now: 1 of 2")
            expect(editor.locator(".feed-strip-titles")).to_have_text("Other.720p")
            editor.locator("summary", has_text="Advanced").click()
            expect(editor.locator("pre")).to_contain_text('"required"')
            editor.get_by_role("button", name="Films", exact=True).click()
            editor.get_by_role("button", name="Books", exact=True).click()
            expect(editor.locator(".feed-chip").filter(has_text="720p")).to_have_count(0)
            editor.locator("summary", has_text="Saved rules outside").click()
            expect(editor.locator(".feed-preserved-rule")).to_contain_text("720p")
            expect(editor.locator(".feed-preserved-rule input")).to_have_count(0)
            editor.get_by_role("button", name="Remove this rule", exact=True).click()
            expect(editor.locator(".feed-preserved-rule")).to_have_count(0)
            expect(editor.locator("pre")).not_to_contain_text('"quality": [')
            assert errors == []
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def test_rss_category_legend_and_rich_editor_roundtrip(tmp_path):
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    from tests.test_feeds import Source, release
    from torrentlinker.web.app import create_app

    app = create_app(tmp_path / "config", password="test-password-long")
    source = Source()
    source.rows = [
        release("a", title="Good.1080p", metadata={"quality": "1080p"}),
        release("b", title="Other.720p", metadata={"quality": "720p"}),
    ]
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
    from tests.test_feed_editor import RICH
    from torrentlinker.downloads import IndexerCategory

    control = app.state.agent_service.feed_control
    control.service.setup.settings.indexer_categories = {
        2030: IndexerCategory("Films"),
        7020: IndexerCategory("Books"),
        3010: IndexerCategory("Music"),
        4050: IndexerCategory("Applications"),
    }
    rich = control.feeds.save(RICH)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={"width": 1280, "height": 900}, locale="en-US")
            page.goto(f"http://127.0.0.1:{port}/")
            page.locator("#login-password").fill("test-password-long")
            page.locator("#login-form button").click()
            shell_navigate(page, "feeds")
            panel = page.frame_locator("#feeds-frame")
            panel.locator("#feeds-sidebar").get_by_role("button", name=re.compile("^Rich")).click()
            panel.locator("#feeds-header").get_by_label("More", exact=True).click()
            panel.get_by_role("menuitem", name="Edit…", exact=True).click()
            editor = panel.locator("#dialog-content")
            editor.get_by_role("button", name="Selection legend", exact=True).click()
            expect(editor.locator("#criteria-legend")).to_be_visible()
            expect(editor.locator("#criteria-legend")).to_contain_text("Require")
            editor.get_by_role("button", name="Save", exact=True).click()
            expect(panel.locator("#dialog")).not_to_be_visible()
            saved = control.feeds.get(rich.id)
            assert saved.model_dump(exclude={"id"}) == RICH.model_dump(exclude={"id"})
            panel.locator("#feeds-side-head").get_by_role("button").click()
            editor = panel.locator("#dialog-content")
            editor.locator(".feed-cats summary").click()
            editor.get_by_label("Books", exact=True).check()
            editor.get_by_label("Music", exact=True).check()
            format_row = editor.locator(".feed-chip-row").filter(has_text=re.compile("^Format"))
            expect(format_row.locator(".category-tags")).to_contain_text("Books")
            expect(format_row.locator(".category-tags")).to_contain_text("Music")
            format_row.locator("input").fill("EPUB")
            format_row.locator("input").press("Enter")
            expect(format_row.locator(".prefer")).to_contain_text("EPUB")
            editor.get_by_label("Name", exact=True).fill("Mixed categories")
            page.frame_locator("#shell-navigation-frame").locator("#language").select_option("fr")
            expect(editor.get_by_label("Nom", exact=True)).to_have_value("Mixed categories")
            expect(editor.get_by_role("button", name="Légende de sélection")).to_be_visible()
            page.frame_locator("#shell-navigation-frame").locator("#language").select_option("en")
            expect(editor.get_by_label("Name", exact=True)).to_have_value("Mixed categories")
            if folder := os.getenv("TL_RSS_SCREENSHOTS"):
                from pathlib import Path

                Path(folder).mkdir(parents=True, exist_ok=True)
                for lang in ("en", "fr"):
                    page.frame_locator("#shell-navigation-frame").locator(
                        "#language"
                    ).select_option(lang)
                    for theme in ("dark", "light"):
                        page.frame_locator("#shell-navigation-frame").locator(
                            "#theme"
                        ).select_option(theme)
                        editor.locator(".criterion-help").scroll_into_view_if_needed()
                        page.screenshot(path=str(Path(folder) / f"rss-web-{lang}-{theme}.png"))
            page.frame_locator("#shell-navigation-frame").locator("#language").select_option("en")
            page.set_viewport_size({"width": 390, "height": 844})
            assert panel.locator("body").evaluate("el => el.scrollWidth <= innerWidth")
            editor.get_by_label("Name", exact=True).focus()
            reached_save = False
            for _ in range(150):
                page.keyboard.press("Tab")
                focused = panel.locator(":focus")
                expect(focused).to_be_in_viewport()
                if editor.get_by_role("button", name="Save", exact=True).evaluate(
                    "el => el === document.activeElement"
                ):
                    reached_save = True
                    break
            assert reached_save, "The RSS save action must be reachable by Tab"
            if folder:
                page.screenshot(path=str(Path(folder) / "rss-web-narrow.png"))
            page.set_viewport_size({"width": 1280, "height": 900})

            editor.get_by_role("radio", name=re.compile("Download automatically")).check()
            expect(editor.locator(".feed-limits")).to_be_visible()
            editor.get_by_role("radio", name=re.compile("Notify me")).check()
            expect(editor.locator(".feed-limits")).to_be_hidden()
            editor.get_by_role("button", name="Save", exact=True).click()
            expect(panel.locator("#dialog")).not_to_be_visible()
            rule = next(x for x in control.feeds.subscriptions() if x["id"] != rich.id)
            assert rule["preferences"]["category_scopes"]["format"] == [7020, 3010]
            panel.locator("#feeds-sidebar").get_by_role(
                "button", name=re.compile("^Mixed categories")
            ).click()
            panel.locator("#feeds-header").get_by_label("More", exact=True).click()
            panel.get_by_role("menuitem", name="Edit…", exact=True).click()
            format_row = panel.locator(".feed-chip-row").filter(has_text=re.compile("^Format"))
            for _ in range(3):
                format_row.get_by_role("button", name=re.compile("^EPUB,")).click()
            panel.locator(".feed-cats summary").click()
            panel.get_by_label("Books", exact=True).uncheck()
            panel.get_by_label("Music", exact=True).uncheck()
            expect(format_row).to_have_count(0)
            panel.get_by_label("Music", exact=True).check()
            format_row.locator("input").fill("FLAC")
            format_row.locator("input").press("Enter")
            expect(format_row.locator(".category-tags")).to_have_text("Music")
            panel.get_by_role("button", name="Save", exact=True).click()
            expect(panel.locator("#dialog")).not_to_be_visible()
            assert control.feeds.get(rule["id"]).preferences.category_scopes["format"] == [3010]

            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def test_cancel_pending_preview_never_saves_and_repeated_save_is_locked(tmp_path):
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    from tests.test_feeds import Source, release
    from torrentlinker.web.app import create_app

    app = create_app(tmp_path / "config", password="test-password-long")
    source = Source()
    source.rows = [
        release("a", title="Good.1080p", metadata={"quality": "1080p"}),
        release("b", title="Other.720p", metadata={"quality": "720p"}),
    ]
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
            page = browser.new_page(viewport={"width": 1280, "height": 900}, locale="en-US")
            page.goto(f"http://127.0.0.1:{port}/")
            page.locator("#login-password").fill("test-password-long")
            page.locator("#login-form button").click()
            shell_navigate(page, "feeds")
            panel = page.frame_locator("#feeds-frame")
            panel.locator("#feeds-empty").get_by_role("button").click()
            expect(panel.locator(".feed-strip")).to_have_text("")
            pending = []

            def hold_preview(route):
                if route.request.post_data_json.get("path") == "feeds/preview":
                    pending.append(route)
                else:
                    route.continue_()

            page.route("**/api/feeds/workspace", hold_preview)
            editor = panel.locator("#dialog-content")
            editor.get_by_label("Title contains", exact=True).fill("changed")
            save = editor.get_by_role("button", name=re.compile(r"^Sav(e|ing)"))
            save.click()
            expect(save).to_be_disabled()
            editor.get_by_role("button", name="Cancel", exact=True).click()
            page.wait_for_timeout(100)
            assert pending
            for route in pending:
                route.fulfill(json={"rows": [], "evaluations": {}})
            page.wait_for_timeout(100)
            assert app.state.agent_service.feed_control.feeds.subscriptions() == []
            page.unroute("**/api/feeds/workspace", hold_preview)
            panel.locator("#feeds-empty").get_by_role("button").click()
            expect(panel.locator(".feed-strip")).to_have_text("")
            panel.get_by_role("button", name="Save", exact=True).dblclick()
            expect(panel.locator("#dialog")).not_to_be_visible()
            assert len(app.state.agent_service.feed_control.feeds.subscriptions()) == 1
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def test_rss_shows_each_clients_state_and_client_actions_for_torrents_already_in_one(tmp_path):
    from dataclasses import replace
    from pathlib import Path

    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    from tests.fake_qbit import FakeQbit
    from tests.test_feeds import Source, release
    from torrentlinker.domain import Torrent
    from torrentlinker.feeds import Subscription
    from torrentlinker.web.app import create_app

    app = create_app(tmp_path / "config", password="test-password-long")
    service = app.state.agent_service
    control = service.feed_control
    source = Source()
    source.rows = [release("a", title="Seeded film " + "x" * 120), release("b", title="Fresh film")]
    control.feeds.indexer = lambda: source
    settings = service.setup.settings
    settings.client_profiles.append(replace(settings.profile(), id="nas", name="NAS"))
    clients = {
        "default": FakeQbit(
            by_hash={"a" * 40: Torrent("a" * 40, "Seeded", Path("/d"), state="uploading")}
        ),
        "nas": FakeQbit(
            by_hash={
                "a" * 40: Torrent("a" * 40, "Seeded", Path("/d"), state="stoppedUP"),
            }
        ),
    }
    for name, fake in clients.items():
        target = service.for_client(name)
        target.setup.client = lambda fake=fake: fake  # type: ignore[method-assign]
        target.observed = list(fake.by_hash.values())
        target.connection_error = ""
        target.feed_observed_at = time.time()
    definition = Subscription(name="Films", categories=[2030], include_current=True)
    control.feeds.preview(definition)
    feed = control.save(definition)
    control.feeds.refresh(feed["id"])
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
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
            shell_navigate(page, "feeds")
            frame = page.frame_locator("#feeds-frame")
            frame.locator("#feeds-sidebar").get_by_role("button", name=re.compile("^Films")).click()
            rows = frame.locator("#feeds-results tbody tr")
            expect(rows).to_have_count(2)
            expect(frame.locator("#feeds-sidebar .tracker-badge").first).to_have_text("c411")
            seeded = rows.filter(has_text="Seeded film")
            expect(seeded.locator(".tracker-badge")).to_have_text(["c411"])
            expect(seeded.locator(".state-entry")).to_have_count(2)
            expect(seeded.locator(".state-badge.seeding + .client-badge")).to_have_text(
                "qBittorrent"
            )
            expect(seeded.locator(".state-badge.paused + .client-badge")).to_have_text("NAS")
            expect(seeded.locator(".link-button")).to_have_attribute(
                "title", re.compile("^Seeded film x")
            )
            heights = {round(row.bounding_box()["height"]) for row in rows.all()}
            assert len(heights) == 1
            seeded.locator("input[type=checkbox]").check()
            bar = frame.locator("#feeds-actions")
            for name in ("Show in Torrents", "Pause"):
                expect(bar.get_by_role("button", name=name, exact=True)).to_be_visible()
            for name in ("Save", "Save selection", "Add to queue"):
                expect(bar.get_by_role("button", name=name, exact=True)).to_be_hidden()
            rows.filter(has_text="Fresh film").locator("input[type=checkbox]").check()
            for name in ("Save", "Save selection", "Add to queue", "Pause"):
                expect(bar.get_by_role("button", name=name, exact=True)).to_be_visible()
            rows.filter(has_text="Fresh film").locator("input[type=checkbox]").uncheck()
            bar.get_by_role("button", name="Pause", exact=True).click()
            expect(seeded.locator(".state-badge.paused")).to_have_count(2)
            expect(bar.get_by_role("button", name="Resume", exact=True)).to_be_visible()
            assert clients["default"].by_hash["a" * 40].state == "stoppedUP"
            bar.get_by_role("button", name="Show in Torrents", exact=True).click()
            torrents = page.frame_locator("#torrents-frame")
            expect(torrents.locator("table.torrent-list tbody tr")).to_have_count(2)
            expect(torrents.locator("table.torrent-list tbody tr").first).to_contain_text("Seeded")
            assert not errors
            browser.close()
    finally:
        server.should_exit = True


def test_rss_editor_chooses_a_tracker_and_tr4ker_feed_options_from_the_backend(tmp_path):
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    from torrentlinker.web.app import create_app

    app = create_app(tmp_path / "config", password="test-password-long")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
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
            shell_navigate(page, "feeds")
            frame = page.frame_locator("#feeds-frame")
            frame.locator("#feeds-empty").get_by_role("button", name="New subscription").click()
            editor = frame.locator("#dialog-content")
            tracker = editor.get_by_label("Tracker", exact=True)
            expect(tracker).to_have_value("c411")
            expect(editor.get_by_label("Feed category")).to_be_hidden()
            tracker.select_option("tr4ker")
            category = editor.get_by_label("tr4ker feed category")
            expect(category).to_be_visible()
            expect(editor.get_by_label("Freeleech only")).to_be_visible()
            expect(category.locator("option[value=films-animation]")).to_have_count(1)
            category.select_option("films")
            editor.get_by_label("Title contains", exact=True).fill("dune")
            expect(editor.get_by_label("Freeleech only")).to_be_hidden()
            assert not errors
            browser.close()
    finally:
        server.should_exit = True


def test_rss_genre_chips_rows_and_review_line(tmp_path):
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    from tests.test_feeds import Source, release
    from torrentlinker.downloads import IndexerCategory
    from torrentlinker.web.app import create_app

    app = create_app(tmp_path / "config", password="test-password-long")
    source = Source()
    source.rows = [
        release("a", title="Alien.2160p", metadata={"genre": [27, 878, 18]}),
        release("b", title="Drame.2160p", metadata={"genre": [18]}),
        release("c", title="Inconnu.2160p"),
    ]
    control = app.state.agent_service.feed_control
    control.feeds.indexer = lambda: source
    control.service.setup.settings.indexer_categories = {2030: IndexerCategory("Films")}
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
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
            shell_navigate(page, "feeds")
            page.on("console", lambda m: m.type == "error" and errors.append(m.text))
            frame = page.frame_locator("#feeds-frame")
            frame.locator("#feeds-empty").get_by_role("button", name="New subscription").click()
            editor = frame.locator("#dialog-content")
            editor.get_by_label("Name", exact=True).fill("Horreur")
            editor.get_by_role("button", name="Films", exact=True).click()
            editor.get_by_role("button", name="Check again", exact=True).click()
            expect(editor.locator(".feed-strip")).to_contain_text("Would match now: 3 of 3")
            chip = editor.locator(".feed-chip").filter(has_text="Horror")
            expect(chip).to_have_count(1)
            chip.click()  # none -> Required (there is no Prefer step for a genre)
            expect(editor.locator(".feed-chip.must")).to_have_text("✓ Horror")
            expect(editor.locator(".feed-strip")).to_contain_text("Would match now: 1 of 3")
            expect(editor.locator(".feed-strip")).to_contain_text("1 wait in review: genre unknown")
            editor.locator(".feed-chip.must").click()  # Required -> Excluded
            expect(editor.locator(".feed-chip.avoid")).to_have_text("✕ Horror")
            expect(editor.locator(".feed-strip")).to_contain_text("Would match now: 1 of 3")
            editor.locator(".feed-chip.avoid").click()  # Excluded -> none
            expect(editor.locator(".feed-chip.must, .feed-chip.avoid")).to_have_count(0)
            editor.locator(".feed-chip").filter(has_text="Horror").click()
            editor.get_by_role("button", name="Save", exact=True).click()
            frame.locator("#feeds-sidebar").get_by_role(
                "button", name=re.compile("^Horreur")
            ).click()
            frame.locator("#feeds-header").get_by_role("button", name="Refresh now").click()
            rows = frame.locator("#feeds-results tbody tr")
            # Horror is required: Drame, known not to be horror, stays out of the inbox, and
            # Inconnu, whose genre is unknown, stays in it for you to settle.
            expect(rows).to_have_count(2)
            expect(rows.filter(has_text="Drame.2160p")).to_have_count(0)
            alien = rows.filter(has_text="Alien.2160p")
            expect(alien.locator(".tracker-badge.genre")).to_have_text(
                ["Horror", "Science Fiction +1"]
            )
            expect(
                rows.filter(has_text="Inconnu").locator(".tracker-badge.genre.unknown")
            ).to_have_text("genre ?")
            heights = {round(rows.nth(i).bounding_box()["height"]) for i in range(2)}
            assert len(heights) == 1
            assert not errors
            browser.close()
    finally:
        server.should_exit = True
