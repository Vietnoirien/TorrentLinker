"""Video browsing through the shared desktop panel and public Media services."""

import os
import subprocess
import sys

from fastapi.testclient import TestClient

from tests.shell_support import shell_navigate
from tests.test_media_api import login, media_app, scan


def test_desktop_video_browsing_details_and_host_playback(qtbot, tmp_path, request):
    if not os.getenv("TL_VIDEO_PANEL_CHILD"):
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", request.node.nodeid],
            env={
                **os.environ,
                "TL_VIDEO_PANEL_CHILD": "1",
                "XDG_CONFIG_HOME": str(tmp_path / "qt"),
            },
            capture_output=True,
            text=True,
            timeout=90,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return
    from tests.test_community_interfaces import js, wait_js
    from torrentlinker.gui.media import MediaTab

    app, root = media_app(tmp_path)
    (root / "A Journey.2024.mp4").write_bytes(b"\0" * 64)
    from PIL import Image

    Image.new("RGB", (200, 300), "#cc5533").save(root / "poster.png")
    with TestClient(app) as browser:
        login(browser)
        scan(browser)
        item = browser.get("/api/media?client_id=default&kind=video").json()["rows"][0]
        library = app.state.agent_service.media
        session = library.open_session("default", "desktop")
        library.session(
            session["id"],
            session["token"],
            report={
                "current_id": item["id"],
                "queue": [item["id"]],
                "position": 589,
                "duration": 7200,
                "paused": True,
            },
        )
        actions = []
        tab = MediaTab(lambda: app.state.assistant, lambda: "default", lambda: None)
        qtbot.addWidget(tab)
        tab.resize(1280, 720)
        tab.show()
        tab.activate()
        panel = tab.browser
        panel.hostRequested.connect(lambda action, body: actions.append((action, body)))
        wait_js(
            qtbot,
            panel,
            "document.querySelector('#media-feature')?.innerText.includes('A Journey')",
        )
        wait_js(
            qtbot, panel, "document.querySelector('.media-feature-poster img')?.naturalWidth===200"
        )
        wait_js(qtbot, panel, "document.querySelector('.media-resume-remove')?.textContent==='×'")
        js(qtbot, panel, "document.querySelector('.media-resume-remove').click()")
        wait_js(qtbot, panel, "document.querySelector('#media-continue').hidden")
        assert library.detail("default", item["id"])["position"] == 0
        assert not any(action == "play" for action, _ in actions)
        assert js(
            qtbot,
            panel,
            "document.querySelector('.media-feature-poster').getBoundingClientRect().right < "
            "document.querySelector('#media-feature h2').getBoundingClientRect().left",
        )
        js(
            qtbot,
            panel,
            "[...document.querySelectorAll('#media-feature button')]"
            ".find(b=>b.textContent==='Details').click()",
        )
        wait_js(qtbot, panel, "document.querySelector('#media-details')?.open")
        assert "A Journey" in js(qtbot, panel, "document.querySelector('#media-details').innerText")
        if os.getenv("QT_QPA_PLATFORM") == "wayland":
            qtbot.wait(250)
            panel.grab().save("/tmp/media108-wayland.png")
        js(
            qtbot,
            panel,
            "[...document.querySelectorAll('#media-details button')]"
            ".find(b=>b.textContent==='Mark watched').click()",
        )
        qtbot.waitUntil(
            lambda: browser.get(f"/api/media/items/{item['id']}?client_id=default").json()[
                "watched"
            ]
        )
        js(
            qtbot,
            panel,
            "[...document.querySelectorAll('#media-details button')]"
            ".find(b=>b.textContent==='Play').click()",
        )
        qtbot.waitUntil(lambda: any(action == "play" for action, _ in actions))
        assert ("play", {"media_ids": [item["id"]], "index": 0}) in actions
        tab.stop()
        assert browser.get("/api/queue").json() == []


def test_web_video_library_uses_the_shared_panel(tmp_path):
    import socket
    import threading
    import time

    import pytest

    if os.getenv("TL_WEB_BROWSER") != "1":
        pytest.skip("opt-in browser test")
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    app, root = media_app(tmp_path)
    for name in ("A Journey.2024.mp4", "Show.S01E01.mkv", "Show.S02E01.mkv"):
        (root / name).write_bytes(b"\0" * 64)
    app.state.agent_service.media.scan("default", threading.Event(), lambda _: None)
    library = app.state.agent_service.media
    video = library.listing("default", kind="video")["rows"][0]
    session = library.open_session("default", "web")
    library.session(
        session["id"],
        session["token"],
        report={
            "current_id": video["id"],
            "queue": [video["id"]],
            "position": 589,
            "duration": 7200,
            "paused": True,
        },
    )
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", log_config=None))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.02)
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1280, "height": 900}, locale="en-US")
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"http://127.0.0.1:{port}")
            page.locator("#login-password").fill("test-password-long")
            page.locator("#login-form button").click()
            shell_navigate(page, "media")
            panel = page.frame_locator("#media-frame")
            expect(panel.locator("#media-feature")).to_contain_text("A Journey")
            remove = panel.get_by_role("button", name="Remove from Continue watching", exact=True)
            expect(remove).to_be_visible()
            expect(remove).to_have_text("×")
            panel.locator("#media-continue").screenshot(path="/tmp/media-resume-cross.png")
            remove.click()
            expect(panel.locator("#media-continue")).to_be_hidden()
            assert library.detail("default", video["id"])["position"] == 0
            assert (root / "A Journey.2024.mp4").exists()
            panel.get_by_role("button", name="Details", exact=True).first.click()
            expect(panel.locator("#media-details")).to_be_visible()
            panel.get_by_role("button", name="Mark watched", exact=True).click()
            expect(panel.get_by_role("button", name="Mark unwatched", exact=True)).to_be_visible()
            panel.get_by_role("button", name="Close details", exact=True).click()
            panel.locator('[data-media-view="series"]').click()
            expect(panel.locator("#media-home-rows")).to_contain_text("Show")
            panel.locator(".media-row-card").first.click()
            expect(panel.get_by_role("button", name="Season 2", exact=True)).to_be_visible()
            page.frame_locator("#shell-navigation-frame").locator("#theme").select_option("dark")
            panel.locator("body").evaluate("() => window.scrollTo(0,0)")
            page.screenshot(path="/tmp/media108-web-dark.png")
            page.frame_locator("#shell-navigation-frame").locator("#theme").select_option("light")
            page.frame_locator("#shell-navigation-frame").locator("#language").select_option("fr")
            expect(panel.get_by_role("tab", name="Musique", exact=True)).to_be_visible()
            expect(panel.get_by_role("button", name="Lire", exact=True)).to_be_visible()
            expect(panel.get_by_role("button", name="Saison 2", exact=True)).to_be_visible()
            page.screenshot(path="/tmp/media108-web-light-fr.png")
            page.frame_locator("#shell-navigation-frame").locator("#language").select_option("en")
            panel.get_by_role("tab", name="Music", exact=True).click()
            expect(page.locator("#media-frame")).to_be_visible()
            expect(panel.locator("#media-results")).to_contain_text("track")
            panel.locator("#media-video-tab").click()
            expect(page.locator("#media-frame")).to_be_visible()
            expect(panel.locator("#media-home-rows")).to_contain_text("Show")
            # Media navigation uses the same readable size as the shared panels.
            for selector in ("#media-video-tab", '[data-media-view="films"]'):
                assert (
                    panel.locator(selector).evaluate(
                        "node => parseFloat(getComputedStyle(node).fontSize)"
                    )
                    >= 14
                )
            assert not errors, errors
            browser.close()
    finally:
        server.should_exit = True
        thread.join(10)
        listener.close()
