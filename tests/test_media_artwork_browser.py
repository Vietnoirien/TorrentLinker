"""The Web Médias loads posters as plain lazy images of the right size, and keeps them."""

import os
import re
import socket
import threading
import time

import pytest
from fastapi import FastAPI
from PIL import Image

from tests.shell_support import shell_navigate
from tests.test_media_api import media_app

pytestmark = pytest.mark.skipif(os.getenv("TL_WEB_BROWSER") != "1", reason="opt-in browser test")


class Requests:
    """Counts what reaches the server, by artwork size."""

    def __init__(self, app):
        self.app, self.sizes = app, []

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"].endswith("/artwork"):
            self.sizes.append(scope["query_string"].decode())
        await self.app(scope, receive, send)


@pytest.mark.parametrize("root_path", ["", "/tl"])
def test_posters_are_lazy_sized_images_and_survive_a_reload(tmp_path, root_path):
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    app, root = media_app(tmp_path)
    (root / "A Journey.2024.mp4").write_bytes(b"\0" * 64)
    Image.new("RGB", (1000, 1500), "#cc5533").save(root / "poster.png")
    counted = Requests(app)
    served = counted
    if root_path:
        served = FastAPI()
        served.mount(root_path, counted)
    app.state.agent_service.media.scan("default", threading.Event(), lambda _p: None)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    server = uvicorn.Server(uvicorn.Config(served, log_level="warning", log_config=None))
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
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            page.goto(f"http://127.0.0.1:{listener.getsockname()[1]}{root_path}/")
            page.locator("#login-password").fill("test-password-long")
            page.locator("#login-form button").click()
            shell_navigate(page, "media")
            panel = page.frame_locator("#media-frame")
            feature = panel.locator("#media-feature")
            expect(feature).to_contain_text("A Journey")
            for selector in (".media-feature-art img", ".media-feature-poster img"):
                image = feature.locator(selector)
                assert "size=hero" in image.get_attribute("src")
                assert image.get_attribute("loading") == "lazy"
                assert image.get_attribute("decoding") == "async"
                expect(image).to_have_js_property("complete", True)
                assert image.evaluate("i => i.naturalWidth") == 780
            row = panel.locator("#media-home-rows img").first
            expect(row).to_have_attribute("src", re.compile("size=grid"))
            expect(row).to_have_js_property("complete", True)
            assert row.evaluate("i => i.naturalWidth") == 342
            first = len(counted.sizes)
            assert first >= 2 and any("size=grid" in q for q in counted.sizes)
            assert all("size=" in q and "&v=" in q for q in counted.sizes)
            page.reload()
            shell_navigate(page, "media")
            reloaded = page.frame_locator("#media-frame").locator("#media-feature img").first
            expect(reloaded).to_have_js_property("complete", True)
            assert len(counted.sizes) == first, (
                counted.sizes
            )  # kept by the browser, not fetched again
            assert not [e for e in errors if "401" not in e], errors
            browser.close()
    finally:
        server.should_exit = True
        thread.join(5)
