"""Shared torrent panel acceptance with simulated clients only."""

import json
import os
import socket
import threading
import time
from pathlib import Path

import pytest

from tests.shell_support import shell_close_drawer, shell_navigate, shell_open_navigation

pytestmark = pytest.mark.skipif(os.getenv("TL_WEB_BROWSER") != "1", reason="opt-in browser test")


def test_sort_filters_columns_and_refresh_preserve_selection(tmp_path):
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    from tests.fake_qbit import FakeQbit
    from torrentlinker.domain import Torrent
    from torrentlinker.web.app import create_app

    class Client(FakeQbit):
        def check(self):
            return "fake"

        def folder_settings(self):
            return []

    fake = Client(
        by_hash={
            f"{i:040x}": Torrent(
                f"{i:040x}",
                f"Book {i:04}",
                Path("/data"),
                size=(i + 1) * 1024**3,
                state="uploading",
                tracker="https://c411.org/private",
                swarm_seeders=i % 50,
                seeding_time=i * 86400,
            )
            for i in range(1200)
        }
    )
    app = create_app(
        tmp_path / "config", password="test-password-long", connector=lambda *args: fake
    )
    from tests.test_torrent_audit import Indexer, torrent

    audit = app.state.agent_service.torrents_workspace.audit
    audit.collect = lambda _: ("Studio", [torrent(1), torrent(2)])
    audit.indexer = lambda: Indexer({f"{1:040x}": [200], f"{2:040x}": [404, 404]})
    audit.confirm_after = 0
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
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1500, "height": 950})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))

            # A host can publish before the deferred view script has initialized.
            def early_environment(route):
                response = route.fetch()
                route.fulfill(
                    response=response,
                    body=(
                        "window.dispatchEvent(new CustomEvent('torrents-environment',"
                        "{detail:{client:'default',language:'en',active:false}}));\n"
                        + response.text()
                    ),
                )

            page.route("**/torrents/view.js", early_environment)

            def early_search_environment(route):
                response = route.fetch()
                route.fulfill(
                    response=response,
                    body=response.text()
                    + """
window.dispatchEvent(new MessageEvent('message', {
  source: parent, origin: location.origin,
  data: {type:'search-environment', value:{client:'default', language:'en', active:false}}
}));
""",
                )

            page.route("**/search/queue.js", early_search_environment)
            page.goto(f"http://127.0.0.1:{port}")
            assert not errors, errors
            page.locator("#login-password").fill("test-password-long")
            page.locator("#login-form button").click()
            expect(page.locator("#workspace")).to_be_visible()
            saved = page.request.post(
                f"http://127.0.0.1:{port}/api/setup/client",
                data={"client": "qbittorrent", "host": "http://fake"},
                headers={"X-TorrentLinker": "1"},
            )
            assert saved.ok, saved.text()
            page.reload()
            page.frame_locator("#shell-navigation-frame").locator("#language").select_option("en")
            page.frame_locator("#shell-navigation-frame").locator("#theme").select_option("dark")
            shell_navigate(page, "torrents")
            expect(page.frame_locator("#torrents-frame").locator("#client")).to_have_count(0)
            panel = page.frame_locator("#torrents-frame")
            try:
                expect(panel.locator("tbody tr")).to_have_count(100)
            except AssertionError:
                print("ERRORS", errors)
                print(panel.locator("body").inner_text())
                raise
            panel.locator("[data-sort=size]").click()
            panel.locator("[data-sort=size]").click()
            expect(panel.locator("tbody tr").first).to_contain_text("Book 1199")
            panel.locator("tbody input").first.check()
            panel.locator(".table-scroll").evaluate("(e)=>e.scrollTop=450")
            page.wait_for_timeout(5500)
            expect(panel.locator("tbody input").first).to_be_checked()
            assert panel.locator(".table-scroll").evaluate("(e)=>e.scrollTop") >= 440
            panel.locator(".metric-filters summary").click()
            panel.locator("[data-metric=daysMin]").fill("1199")
            page.wait_for_timeout(5500)
            expect(panel.locator("[data-metric=daysMin]")).to_have_value("1199")
            expect(panel.locator("[data-metric=daysMin]")).to_be_focused()
            panel.locator("[data-metric=daysMin]").press("Tab")
            expect(panel.locator("tbody tr")).to_have_count(1)
            expect(panel.locator("tbody")).to_contain_text("Book 1199")
            panel.locator("#columns").click()
            panel.locator("[data-col=weight]").check()
            panel.get_by_role("button", name="Done", exact=True).click()
            page.reload()
            panel = page.frame_locator("#torrents-frame")
            expect(panel.locator("[data-sort=weight]")).to_be_visible()
            panel.locator("#query").fill("Book 0007")
            expect(panel.locator("tbody tr")).to_have_count(1)
            expect(panel.locator("tbody")).to_contain_text("Book 0007")
            panel.locator("#query").fill("No such torrent")
            expect(panel.locator(".empty")).to_contain_text("No torrents match")
            panel.locator(".metric-filters summary").click()
            panel.locator("#clear-filters").click()
            expect(panel.locator("tbody tr")).to_have_count(100)
            panel.locator("[data-metric=sizeMin]").fill("1")
            panel.locator("[data-metric=sizeMin]").press("Tab")
            panel.locator("[data-unit=sizeMax]").click()
            expect(panel.locator("[data-unit=sizeMin]")).to_have_text("GiB")
            expect(panel.locator("[data-unit=sizeMax]")).to_have_text("MiB")
            panel.locator("[data-metric=sizeMax]").fill("2048")
            panel.locator("[data-metric=sizeMax]").press("Tab")
            expect(panel.locator("tbody tr")).to_have_count(2)
            panel.locator("[data-unit=sizeMax]").click()
            expect(panel.locator("[data-metric=sizeMax]")).to_have_value("2")
            expect(panel.locator("tbody tr")).to_have_count(2)
            panel.locator("[data-unit=sizeMin]").click()
            expect(panel.locator("[data-metric=sizeMin]")).to_have_value("1024")
            expect(panel.locator("[data-unit=sizeMax]")).to_have_text("GiB")
            if folder := os.getenv("TL_TORRENTS_SCREENSHOTS"):
                Path(folder).mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(Path(folder) / "torrents-dark.png"))
            panel.locator("#audit-history").click()
            panel.locator("#audit-start").click()
            expect(panel.locator("#dialog")).to_contain_text("Deleted (confirmed): 1")
            expect(panel.locator("#dialog")).not_to_contain_text("private-passkey")
            with page.expect_download() as download:
                panel.locator('[data-export="json"]').click()
            assert "deleted" in Path(download.value.path()).read_text()
            panel.locator("#audit-close").click()
            # A finished job's card goes away (#159): keep one running across the language change.
            client = page.evaluate("state.clientId")
            running = {
                "id": "refresh-1",
                "kind": "refresh",
                "status": "running",
                "client_id": client,
                "created": time.time(),
                "progress": {},
                "subject": {},
            }
            page.route(
                "**/api/jobs",
                lambda route: route.fulfill(
                    status=200, content_type="application/json", body=json.dumps([running])
                ),
            )
            try:
                expect(page.locator("#page-jobs")).to_contain_text("Refresh client")
                page.frame_locator("#shell-navigation-frame").locator("#language").select_option(
                    "fr"
                )
                expect(page.locator("#page-jobs")).to_contain_text("Actualiser le client")
                expect(page.locator("#page-jobs")).not_to_contain_text("Refresh client")
            finally:
                page.unroute("**/api/jobs")
            expect(panel.locator("#columns")).to_have_text("Colonnes")
            page.frame_locator("#shell-navigation-frame").locator("#theme").select_option("light")
            expect(panel.locator("html")).to_have_attribute("data-theme", "light")
            page.set_viewport_size({"width": 390, "height": 844})
            expect(panel.locator("#columns")).to_be_visible()
            # On a phone the sidebar opens over the page at full height; a tap beside it closes it.
            shell_open_navigation(page)
            page.wait_for_function(
                "Math.abs(document.querySelector('#shell-navigation-frame')"
                ".getBoundingClientRect().height - innerHeight) < 2"
            )
            shell_close_drawer(page)
            page.locator("#torrents-frame").scroll_into_view_if_needed()
            if folder := os.getenv("TL_TORRENTS_SCREENSHOTS"):
                Path(folder).mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(Path(folder) / "torrents-mobile.png"))
                page.set_viewport_size({"width": 1500, "height": 950})
                page.screenshot(path=str(Path(folder) / "torrents-web.png"))
            panel.locator("#audit-history").click()
            panel.locator("[data-audit]").first.click()
            expect(panel.locator("#dialog")).to_contain_text("Supprimé (confirmé): 1")
            if folder := os.getenv("TL_TORRENTS_SCREENSHOTS"):
                page.set_viewport_size({"width": 390, "height": 844})
                page.wait_for_timeout(250)  # let Chromium paint after the viewport resize
                page.screenshot(path=str(Path(folder) / "audit-mobile.png"))
            pending_reports = []

            def delay_audit_report(route):
                if route.request.post_data_json.get("action") == "audit-report":
                    pending_reports.append((route, route.fetch()))
                else:
                    route.continue_()

            page.route("**/api/torrents/workspace", delay_audit_report)
            panel.locator("body").evaluate("""() => {
              const original = showAudit;
              window.showAudit = async (...args) => {
                await original(...args); document.body.dataset.auditRequestFinished = "true";
              };
            }""")
            panel.locator("#audit-refresh").click()
            for _ in range(100):
                if pending_reports:
                    break
                page.wait_for_timeout(20)
            assert len(pending_reports) == 1
            page.keyboard.press("Escape")
            pending_reports[0][0].fulfill(response=pending_reports[0][1])
            expect(panel.locator("body")).to_have_attribute("data-audit-request-finished", "true")
            expect(panel.locator("#dialog")).not_to_be_visible()
            page.unroute("**/api/torrents/workspace", delay_audit_report)
            expect(page.locator(".tl-toast").filter(has_text="is not defined")).to_have_count(0)
            assert not errors, errors
            browser.close()
    finally:
        server.should_exit = True
        thread.join(10)


def test_tracker_preview_apply_and_dialog_cleanup(tmp_path):
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    from tests.fake_qbit import FakeQbit
    from tests.test_tracker_updates import OLD, SAVED, URL, Announce
    from torrentlinker.domain import Torrent
    from torrentlinker.web.app import create_app

    class Client(FakeQbit):
        def check(self):
            return "fixture"

        def folder_settings(self):
            return []

        def announce_entries(self, hash):
            return list(self.trackers)

        def apply_announces(self, hash, before, after):
            self.trackers = list(after)

        def reannounce(self, hash):
            self.announced.append(hash)

    fake = Client(
        by_hash={
            "a" * 40: Torrent(
                "a" * 40, "External c411 torrent", Path("/data"), tracker=URL, trackers=(URL,)
            )
        }
    )
    fake.trackers, fake.announced = [Announce(URL)], []
    app = create_app(
        tmp_path / "config", password="test-password-long", connector=lambda *args: fake
    )
    app.state.agent_service.setup.secrets.update({"announce-url": SAVED})
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
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1450, "height": 1000})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("dialog", lambda dialog: dialog.accept())
            page.goto(f"http://127.0.0.1:{port}")
            page.locator("#login-password").fill("test-password-long")
            page.locator("#login-form button").click()
            expect(page.locator("#workspace")).to_be_visible()
            assert page.request.post(
                f"http://127.0.0.1:{port}/api/setup/client",
                data={"client": "qbittorrent", "host": "http://fake"},
                headers={"X-TorrentLinker": "1"},
            ).ok
            page.reload()
            page.frame_locator("#shell-navigation-frame").locator("#language").select_option("en")
            shell_navigate(page, "torrents")
            panel = page.frame_locator("#torrents-frame")
            panel.locator("#tracker-updates").click()
            panel.locator("#tracker-preview").click()
            expect(panel.locator("#tracker-apply")).to_be_enabled(timeout=15000)
            expect(panel.locator("#tracker-report")).to_contain_text("c411.org")
            assert OLD not in panel.locator("#dialog").inner_text()
            page.screenshot(path="/tmp/tl120-tracker-preview.png")
            panel.locator("#tracker-apply").click()
            expect(panel.locator("#tracker-report")).to_contain_text(
                "Updated and reannounced", timeout=15000
            )
            assert fake.announced == ["a" * 40]
            panel.locator("#tracker-preview").click()
            expect(panel.locator("#tracker-report")).to_contain_text(
                "Current or unselected group", timeout=15000
            )
            expect(panel.locator("#tracker-apply")).to_be_disabled()
            panel.locator("#tracker-close").click()
            panel.locator("#columns").click()
            # The reused dialog must not retain tracker form callbacks.
            panel.locator("#dialog input[type=checkbox]").first.click()
            assert not errors, errors
            browser.close()
    finally:
        server.should_exit = True
        thread.join(10)


def test_a_slow_list_neither_chains_refreshes_nor_closes_an_open_filter(tmp_path):
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    from tests.fake_qbit import FakeQbit
    from torrentlinker.domain import Torrent
    from torrentlinker.web.app import create_app

    class Client(FakeQbit):
        def check(self):
            return "fake"

        def folder_settings(self):
            return []

    fake = Client(
        by_hash={
            f"{i:040x}": Torrent(f"{i:040x}", f"Book {i:04}", Path("/data"), state="uploading")
            for i in range(20)
        }
    )
    app = create_app(
        tmp_path / "config", password="test-password-long", connector=lambda *args: fake
    )
    workspace = app.state.agent_service.torrents_workspace
    answer = workspace.request
    slow = {"seconds": 0.0}
    lists: list[tuple[float, float]] = []

    # The live client answered a page in 5–6 s, longer than the 5 s refresh.
    def request(action, body=None):
        if action != "list":
            return answer(action, body)
        started = time.monotonic()
        time.sleep(slow["seconds"])
        try:
            return answer(action, body)
        finally:
            lists.append((started, time.monotonic()))

    workspace.request = request
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
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1500, "height": 950})
            page.goto(f"http://127.0.0.1:{port}")
            page.locator("#login-password").fill("test-password-long")
            page.locator("#login-form button").click()
            expect(page.locator("#workspace")).to_be_visible()
            saved = page.request.post(
                f"http://127.0.0.1:{port}/api/setup/client",
                data={"client": "qbittorrent", "host": "http://fake"},
                headers={"X-TorrentLinker": "1"},
            )
            assert saved.ok, saved.text()
            page.reload()
            shell_navigate(page, "torrents")
            panel = page.frame_locator("#torrents-frame")
            expect(panel.locator("tbody tr")).to_have_count(20)

            slow["seconds"] = 6.0
            lists.clear()
            page.wait_for_timeout(26000)
            assert len(lists) >= 2, lists
            gaps = [later[0] - earlier[1] for earlier, later in zip(lists, lists[1:], strict=False)]
            assert min(gaps) >= 4, gaps

            slow["seconds"] = 0.0
            page.wait_for_timeout(7000)
            state = panel.locator("[data-filter=state]")
            state.focus()
            state.evaluate("(e)=>e.dataset.kept='yes'")
            page.wait_for_timeout(6000)
            expect(panel.locator("[data-filter=state][data-kept=yes]")).to_have_count(1)
            browser.close()
    finally:
        server.should_exit = True
        thread.join(10)


def test_the_head_box_selects_every_match_and_the_table_scrolls_on(tmp_path):
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    from tests.fake_qbit import FakeQbit
    from torrentlinker.domain import Torrent
    from torrentlinker.web.app import create_app

    class Client(FakeQbit):
        def check(self):
            return "fake"

        def folder_settings(self):
            return []

    fake = Client(
        by_hash={
            f"{i:040x}": Torrent(
                f"{i:040x}",
                f"Book {i:04}",
                Path("/data"),
                state="pausedUP" if i % 4 == 0 else "uploading",
                category="Ebook" if i % 4 == 1 else "",
            )
            for i in range(1200)
        }
    )
    app = create_app(
        tmp_path / "config", password="test-password-long", connector=lambda *args: fake
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
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1500, "height": 950})
            page.goto(f"http://127.0.0.1:{port}")
            # A password manager keeps the Owner's password under this instance's own name, not
            # as any login of the main domain.
            expect(page.locator("#login-name")).to_have_value(f"owner@127.0.0.1:{port}")
            expect(page.locator("#login-name")).to_be_hidden()
            page.locator("#login-password").fill("test-password-long")
            page.locator("#login-form button").click()
            expect(page.locator("#workspace")).to_be_visible()
            saved = page.request.post(
                f"http://127.0.0.1:{port}/api/setup/client",
                data={"client": "qbittorrent", "host": "http://fake"},
                headers={"X-TorrentLinker": "1"},
            )
            assert saved.ok, saved.text()
            page.reload()
            page.frame_locator("#shell-navigation-frame").locator("#language").select_option("en")
            shell_navigate(page, "torrents")
            panel = page.frame_locator("#torrents-frame")
            expect(panel.locator("tbody tr")).to_have_count(100)
            expect(panel.locator("#prev")).to_have_count(0)

            panel.locator(".table-scroll").evaluate("(e)=>e.scrollTop=e.scrollHeight")
            expect(panel.locator("tbody tr")).to_have_count(200)
            expect(panel.locator(".status small")).to_contain_text("200 of 1,200 torrents shown")

            panel.locator("#select-page").check()
            expect(panel.locator(".status span").first).to_have_text(
                "All 1,200 matching torrents selected"
            )
            panel.locator("[data-filter=state]").select_option("paused")
            expect(panel.locator(".status span").first).to_have_text(
                "All 300 matching torrents selected"
            )
            panel.locator("tbody [data-select]").first.uncheck()
            expect(panel.locator(".status span").first).to_have_text("299 selected")
            expect(panel.locator("#select-page")).not_to_be_checked()

            panel.locator("#select-page").check()
            panel.locator("[data-action=resume]").click()
            expect(panel.locator("#dialog")).to_contain_text("300 torrents")
            panel.locator("#confirm").click()
            expect(panel.locator("#dialog")).not_to_be_visible()
            expect(panel.locator("tbody tr").first).to_contain_text("No torrents match")
            assert sum(t.state == "pausedUP" for t in fake.by_hash.values()) == 0

            # Removing every torrent of a category leaves no such category: the filter goes
            # back to all categories and the list shows what remains.
            panel.locator("[data-filter=state]").select_option("")
            panel.locator("[data-filter=category]").select_option("Ebook")
            panel.locator("#select-page").check()
            expect(panel.locator(".status span").first).to_have_text(
                "All 300 matching torrents selected"
            )
            panel.locator("[data-action=remove]").click()
            expect(panel.locator("#dialog")).to_contain_text("300 torrents")
            panel.locator("#confirm").click()
            expect(panel.locator("[data-filter=category]")).to_have_value("")
            expect(panel.locator("tbody tr")).to_have_count(100)
            expect(panel.locator(".status small")).to_contain_text("100 of 900 torrents shown")
            browser.close()
    finally:
        server.should_exit = True
        thread.join(10)
