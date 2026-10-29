"""The account workspace is first and the manual companion flow is usable."""

import json
import os
import socket
import threading
import time

import pytest

from tests.test_web_profile import ORIGIN, prepared, snapshot

pytestmark = pytest.mark.skipif(os.getenv("TL_WEB_BROWSER") != "1", reason="opt-in browser test")


def test_profile_first_pair_snapshot_disconnect_browser(tmp_path, monkeypatch):
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    app, setup = prepared(tmp_path, monkeypatch)
    from pathlib import Path

    from fastapi.staticfiles import StaticFiles

    from torrentlinker import companion

    app.mount(
        "/extension-test",
        StaticFiles(directory=Path(companion.__file__).parent / "companion_extension"),
    )
    setup.profile_workspace().refresh(setup.settings.indexer.url, "fake-key")
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
            page = browser.new_page(viewport={"width": 1500, "height": 1100}, locale="en-US")
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/")
            page.locator("#login-password").fill("test-password-long")
            page.locator("#login-form button").click()
            page.locator("[data-view=zen]").first.click()
            expect(page.locator("#zen-profile-tab")).to_have_attribute("aria-selected", "true")
            expect(page.locator("#profile-identity")).to_contain_text("Demo account")
            expect(page.locator("#profile-stats")).to_contain_text("123.5")
            page.locator("#profile-pair").click()
            expect(page.locator("#profile-code")).to_be_visible()
            code = page.locator("#profile-code").input_value()
            assert code
            ext = {"Origin": ORIGIN}
            response = page.request.post(
                f"http://127.0.0.1:{port}/api/companion/pair",
                headers=ext,
                data={"code": code, "accountId": "42"},
            )
            assert response.ok
            ext["Authorization"] = "Bearer " + response.json()["token"]
            assert page.request.post(
                f"http://127.0.0.1:{port}/api/companion/snapshot", headers=ext, data=snapshot()
            ).ok
            expect(page.locator("#profile-advanced")).to_contain_text("42", timeout=10000)
            if output := os.getenv("TL_PROFILE_SCREENSHOTS"):
                from pathlib import Path

                target = Path(output)
                target.mkdir(parents=True, exist_ok=True)
                page.locator("#theme").select_option("dark")
                page.evaluate("window.scrollTo(0, 0)")
                page.screenshot(path=str(target / "web-profile.png"), full_page=True)
            page.locator("#profile-disconnect").click()
            expect(page.locator("#profile-advanced")).not_to_contain_text("42")
            page.locator("#zen-profile-tab").focus()
            page.keyboard.press("ArrowRight")
            expect(page.locator("#zen-seeding-tab")).to_have_attribute("aria-selected", "true")
            assert not errors

            # Exercise the shipped extension UI with a fake browser permission/collector
            # boundary. No live c411 tab, cookie or account is involved.
            extension = browser.new_page()
            extension.add_init_script(
                f"""window.chrome = {{
                permissions: {{request: async () => true}},
                scripting: {{executeScript: async () => [{{result: {json.dumps(snapshot())}}}]}}
            }};"""
            )
            calls = []

            def respond(route):
                request = route.request
                calls.append(request.url)
                if request.url.endswith("/pair"):
                    route.fulfill(status=200, json={"token": "fake-token", "expiresIn": 3600})
                else:
                    route.fulfill(status=403, json={"detail": "Pair again from the Profile tab."})

            extension.route("**/api/companion/*", respond)
            extension.goto(f"http://127.0.0.1:{port}/extension-test/companion.html?source=1")
            extension.locator("#read").click()
            extension.locator("#target").fill(f"http://127.0.0.1:{port}")
            extension.locator("#code").fill("fake-code")
            extension.locator("#pair").click()
            expect(extension.locator("#send")).to_be_enabled()
            extension.locator("#code").fill("replacement-code")
            extension.locator("#pair").click()
            expect(extension.locator("#status")).to_contain_text("Paired.")
            extension.locator("#send").click()
            expect(extension.locator("#status")).to_contain_text("Pair again")
            expect(extension.locator("#pair")).to_be_enabled()
            expect(extension.locator("#send")).to_be_disabled()
            extension.locator("#code").fill("new-code")
            extension.locator("#pair").click()
            expect(extension.locator("#send")).to_be_enabled()
            assert len([url for url in calls if url.endswith("/pair")]) == 3
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)
