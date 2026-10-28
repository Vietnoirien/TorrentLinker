"""Visible archive confirmation, cancellation and completion on an isolated server."""

import os
import socket
import threading
import time
from pathlib import Path

import pytest

from tests.test_web_archives import archive_app

pytestmark = pytest.mark.skipif(os.getenv("TL_WEB_BROWSER") != "1", reason="opt-in browser test")


@pytest.mark.parametrize("language", ["en", "fr"])
def test_archive_review_cancel_then_confirm(tmp_path, language):
    def label(en, fr):
        return fr if language == "fr" else en

    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    with archive_app(tmp_path) as (api, archive, _, candidate, client, _):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        server = uvicorn.Server(
            uvicorn.Config(
                api.app, host="127.0.0.1", port=port, log_level="warning", lifespan="off"
            )
        )
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.02)
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                page = browser.new_page(
                    viewport={"width": 1600, "height": 1000}, locale="en-US", color_scheme="dark"
                )
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(f"http://127.0.0.1:{port}/")
                page.locator("#login-password").fill("test-password-long")
                page.locator("#login-form button").click()
                page.locator("#language").select_option(language)
                page.locator("[data-view=library]").first.click()
                page.locator("#library-table").get_by_role(
                    "button", name="Kaneda.zip", exact=True
                ).click()
                action = page.locator("#candidate-actions").get_by_role(
                    "button", name=label("Unpack and reseed…", "Extraire et seeder…"), exact=True
                )
                expect(action).to_be_enabled()
                action.click()
                dialog = page.locator("#dialog")
                expect(dialog).to_contain_text(
                    label(
                        "Extraction happens on the TorrentLinker server",
                        "L’extraction a lieu sur le serveur TorrentLinker",
                    )
                )
                expect(dialog).to_contain_text(str(archive.parent / "Kaneda"))
                expect(dialog).to_contain_text(label("3 files", "3 fichiers"))
                if destination := os.getenv("TL_WEB_SCREENSHOTS"):
                    Path(destination).mkdir(parents=True, exist_ok=True)
                    page.screenshot(
                        path=str(Path(destination) / f"web-archive-confirmation-{language}.png"),
                        full_page=False,
                    )
                dialog.get_by_role("button", name=label("Cancel", "Annuler"), exact=True).click()
                expect(dialog).not_to_be_visible()
                assert not (archive.parent / "Kaneda").exists()
                assert not client.by_hash
                action.click()
                dialog.get_by_role(
                    "button", name=label("Unpack and reseed", "Extraire et seeder"), exact=True
                ).click()
                expect(dialog).to_contain_text(
                    label("Verification started", "Vérification lancée"), timeout=15000
                )
                assert archive.is_file()
                assert client.rechecked == [candidate.infohash]
                assert not client.started
                assert not errors
                browser.close()
        finally:
            server.should_exit = True
            thread.join(5)
