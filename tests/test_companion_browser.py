"""Real extension APIs, with a fake c411 website and a local test receiver."""

import os
import socket
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tests.shell_support import settings_tab, shell_navigate
from tests.test_profile import PROFILE
from tests.test_web_profile import prepared, snapshot

pytestmark = pytest.mark.skipif(os.getenv("TL_WEB_BROWSER") != "1", reason="opt-in browser test")


def test_connect_click_pairs_and_syncs_without_extension_confirmation(tmp_path, monkeypatch):
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    from torrentlinker import companion

    (tmp_path / "server").mkdir()
    app, setup = prepared(tmp_path / "server", monkeypatch)
    workspace = setup.profile_workspace()
    workspace.refresh(setup.settings.indexer.url, "fake-key")
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
    extension = Path(companion.__file__).parent / "companion_extension"
    account = {**PROFILE, "username": "Demo account"}
    reads = []
    from tests.torrents import make_torrent
    from torrentlinker.torrent_meta import read_torrent

    sample = tmp_path / "sample.txt"
    sample.write_text("Companion metadata fixture")
    descriptor = make_torrent(sample)
    infohash = read_torrent(descriptor).infohash

    def tracker(route):
        path = route.request.url
        reads.append(path)
        if "/api/user/profile" in path:
            route.fulfill(json=account)
        elif path.endswith("/check-integrity"):
            route.fulfill(json={"ok": True})
        elif path.endswith("/download"):
            route.fulfill(content_type="application/x-bittorrent", body=descriptor)
        elif "/api/profile/detailed-stats" in path:
            route.fulfill(json={"stats": snapshot()["details"]})
        elif "/api/profile/active-seeds" in path:
            route.fulfill(json={"meta": {"total": 42}})
        elif "/api/tokens/history" in path:
            # c411's reason and id stay in the browser; only date and amount are sent.
            now = datetime.now(UTC)
            ledger = [(now, 23), (now - timedelta(days=1), 50)]
            route.fulfill(
                json={
                    "success": True,
                    "history": [
                        {"id": i, "createdAt": at.isoformat(), "reason": "daily", "delta": d}
                        for i, (at, d) in enumerate(ledger)
                    ],
                    "total": None,
                }
            )
        else:
            route.fulfill(content_type="text/html", body="<h1>Fake c411 account</h1>")

    try:
        with sync_playwright() as pw:
            context = pw.chromium.launch_persistent_context(
                str(tmp_path / "browser"),
                channel="chromium",
                headless=True,
                args=[f"--disable-extensions-except={extension}", f"--load-extension={extension}"],
            )
            context.route("https://c411.org/**", tracker)
            tracker_tab = context.new_page()
            tracker_tab.goto("https://c411.org/")
            page = context.new_page()
            page.goto(f"http://127.0.0.1:{port}/")
            page.locator("#login-password").fill("test-password-long")
            page.locator("#login-form button").click()
            page.frame_locator("#shell-navigation-frame").locator("#language").select_option("en")
            shell_navigate(page, "setup")
            settings = page.frame_locator("#settings-frame")
            settings.get_by_role("button", name="Connections", exact=True).click()
            settings_tab(settings, "Companion").click()
            with context.expect_page() as handoff_opened:
                settings.get_by_role("button", name="Pair", exact=True).click()
            handoff = handoff_opened.value
            expect(handoff.locator("h1")).to_have_css("color", "rgb(101, 212, 202)")
            # This is the only user action after installing the companion.
            for _ in range(150):
                if (workspace.state().get("companion") or {}).get("activeSeeds"):
                    break
                page.wait_for_timeout(100)
            assert workspace.state()["companion"]["activeSeeds"] == {"total": 42}
            assert workspace.state()["paired"]
            assert reads.count("https://c411.org/api/user/profile") == 2
            yesterday = workspace.history_days()[0]
            balance = workspace.state()["companion"]["profile"]["balance"]
            assert yesterday.ledger and yesterday.values["balance"] == balance - 23
            page.bring_to_front()
            expect(settings.get_by_role("checkbox")).to_be_enabled(timeout=10000)
            settings.get_by_role("checkbox").check()
            expect(settings.get_by_role("checkbox")).to_be_enabled()
            expect(settings.get_by_role("checkbox")).to_be_checked()
            assert workspace.state()["downloads"]["enabled"]
            # Public owner API -> real extension -> fake tracker -> verified summary.
            worker = context.service_workers[0]
            job = page.request.post(
                f"http://127.0.0.1:{port}/api/zen/profile/download-tests",
                headers={"X-TorrentLinker": "1"},
                data={"infohash": infohash, "request_id": "browser-test"},
            ).json()
            assert "id" in job, job
            worker.evaluate("chrome.alarms.create('companion-commands', {delayInMinutes: 0.001})")
            for _ in range(100):
                result = page.request.get(
                    f"http://127.0.0.1:{port}/api/zen/profile/download-tests/{job['id']}"
                ).json()
                if result["status"] not in ("pending", "running"):
                    break
                page.wait_for_timeout(100)
            assert result["status"] == "complete", str(result)
            assert result["bytes"] == len(descriptor)
            assert result["discarded"]
            assert len([url for url in reads if url.endswith("/download")]) == 1

            # Closing extension/app tabs and restarting the browser retains consent.
            before_restart = workspace.state()["received_at"]
            for opened in context.pages:
                opened.close()
            context.close()
            context = pw.chromium.launch_persistent_context(
                str(tmp_path / "browser"),
                channel="chromium",
                headless=True,
                args=[f"--disable-extensions-except={extension}", f"--load-extension={extension}"],
            )
            context.route("https://c411.org/**", tracker)
            tracker_tab = context.new_page()
            tracker_tab.goto("https://c411.org/")
            worker = (
                context.service_workers[0]
                if context.service_workers
                else context.wait_for_event("serviceworker")
            )
            # Advance the service worker's clock and fire the browser alarm. Neither
            # the app nor the extension's own sync functions are called by the test.
            worker.evaluate("""() => {
                const clock = Date.now;
                Date.now = () => clock() + 120001;
                return chrome.alarms.create('profile-sync', {delayInMinutes: 0.001});
            }""")
            extension_page = context.new_page()
            extension_page.goto(worker.url.replace("background.js", "companion.html"))
            expect(extension_page.locator("#status")).to_contain_text("Connected.", timeout=15000)
            assert workspace.state()["received_at"] > before_restart

            # A different signed-in browser account must never overwrite the app.
            account["id"] = 99
            last_sync = workspace.state()["received_at"]
            worker.evaluate("""() => {
                const clock = Date.now;
                Date.now = () => clock() + 120001;
                return chrome.alarms.create('profile-sync', {delayInMinutes: 0.001});
            }""")
            expect(extension_page.locator("#status")).to_contain_text(
                "Different c411 account", timeout=15000
            )
            assert workspace.state()["received_at"] == last_sync
            account["id"] = 42

            page = context.new_page()
            page.goto(f"http://127.0.0.1:{port}/")
            shell_navigate(page, "setup")
            settings = page.frame_locator("#settings-frame")
            settings.get_by_role("button", name="Connections", exact=True).click()
            settings_tab(settings, "Companion").click()
            settings.get_by_role("button", name="Disconnect & clear", exact=True).click()
            for _ in range(50):
                if not workspace.state()["paired"]:
                    break
                page.wait_for_timeout(100)
            assert not workspace.state()["paired"]
            worker.evaluate("""() => {
                const clock = Date.now;
                Date.now = () => clock() + 120001;
                return chrome.alarms.create('profile-sync', {delayInMinutes: 0.001});
            }""")
            expect(extension_page.locator("#destination")).to_have_text(
                "Not connected", timeout=15000
            )
            context.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def test_tr4ker_pairs_from_its_own_tab_and_a_c411_tab_never_answers_for_it(tmp_path, monkeypatch):
    import json
    from urllib.parse import quote

    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    from tests.test_tr4ker_companion import ME, SECRETS, STATS
    from torrentlinker import companion

    (tmp_path / "server").mkdir()
    app, setup = prepared(tmp_path / "server", monkeypatch)
    workspace = setup.profile_workspace()
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
    extension = Path(companion.__file__).parent / "companion_extension"
    account = dict(ME)
    requests = []

    def tr4ker(route):
        request = route.request
        requests.append((request.method, request.url))
        path = request.url.removeprefix("https://tr4ker.net")
        if path == "/api/me":
            route.fulfill(json=account)
        elif path == "/api/me/stats":
            route.fulfill(json=STATS)
        elif path == "/api/shop":
            route.fulfill(
                json={"items": [{"id": 1, "name": "+25 GB", "price": 400, "bonus_bytes": 1}]}
            )
        elif path.startswith("/api/me/sw-rewards"):
            route.fulfill(
                json={
                    "entries": [{"id": 5, "amount": 12, "seeders": 3, "size_bytes": 9}],
                    "total": 1,
                }
            )
        else:
            route.fulfill(content_type="text/html", body="<h1>Fake tr4ker</h1>")

    def c411(route):
        requests.append(("c411", route.request.url))
        route.fulfill(content_type="text/html", body="<h1>Fake c411</h1>")

    try:
        with sync_playwright() as pw:
            context = pw.chromium.launch_persistent_context(
                str(tmp_path / "browser"),
                channel="chromium",
                headless=True,
                args=[f"--disable-extensions-except={extension}", f"--load-extension={extension}"],
            )
            context.route("https://tr4ker.net/**", tr4ker)
            context.route("https://c411.org/**", c411)
            context.new_page().goto("https://tr4ker.net/")
            code = workspace.pairing("tr4ker")["code"]
            payload = {"target": f"http://127.0.0.1:{port}", "code": code, "tracker": "tr4ker"}
            handoff = context.new_page()
            handoff.goto(f"http://127.0.0.1:{port}/companion/connect#{quote(json.dumps(payload))}")
            for _ in range(150):
                state = workspace.state()["tr4ker"]
                if state["available"] and state["payouts"]["count"]:
                    break
                handoff.wait_for_timeout(100)
            state = workspace.state()["tr4ker"]
            assert state["paired"] and state["account"]["username"] == "demo_t4k"
            assert state["profile"]["money"] == 250 and state["shop"][0]["price"] == 400
            assert state["payouts"]["count"] == 1
            assert not workspace.state()["paired"]  # c411 stays unpaired
            dump = (tmp_path / "server" / "tr4ker-companion.json").read_text()
            assert not any(secret in dump + json.dumps(workspace.state()) for secret in SECRETS)
            # Only fixed GETs reach tr4ker, never the key route, and c411 was never asked.
            assert {method for method, url in requests if url.startswith("https://tr4ker.net")} <= {
                "GET"
            }
            assert not any("api-key" in url for _, url in requests)
            assert not any(method == "c411" for method, _ in requests)
            worker = context.service_workers[0]
            extension_page = context.new_page()
            extension_page.goto(worker.url.replace("background.js", "companion.html"))
            expect(extension_page.locator("#t4k-destination")).to_contain_text("Account 7")
            # Another signed-in tr4ker account must never overwrite the app.
            account["id"] = 99
            last = workspace.state()["tr4ker"]["received_at"]
            worker.evaluate("""() => {
                const clock = Date.now;
                Date.now = () => clock() + 120001;
                return chrome.alarms.create('profile-sync', {delayInMinutes: 0.001});
            }""")
            expect(extension_page.locator("#t4k-status")).to_contain_text(
                "Different tr4ker account", timeout=15000
            )
            assert workspace.state()["tr4ker"]["received_at"] == last
            extension_page.locator("#t4k-forget").click()
            for _ in range(50):
                if not workspace.state()["tr4ker"]["paired"]:
                    break
                extension_page.wait_for_timeout(100)
            assert not workspace.state()["tr4ker"]["paired"]
            context.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)
