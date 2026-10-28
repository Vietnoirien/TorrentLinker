"""Opt-in real-browser tests against a temporary server and fake Torrent Client."""

import os
import re
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
                    swarm_seeders=42,
                    swarm_peers=13,
                )
            ]

        def torrent(self, hash, **kwargs):
            return self.torrents()[0]

        def file_listing(self, hash):
            from torrentlinker.domain import TorrentFile

            return [TorrentFile(0, "Example book.epub", 1048576, True)]

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
            expect(page.locator("#torrent-table")).to_contain_text("3 (42)")
            expect(page.locator("#torrent-table")).to_contain_text("2 (13)")
            # Actions wait for a selection, as on the desktop; a row is selected by clicking it.
            expect(page.locator("[data-action=pause]")).to_be_disabled()
            page.locator("#torrent-table tbody tr").click()
            expect(page.locator("#torrent-table tbody tr.selected")).to_have_count(1)
            expect(page.locator("#torrent-details")).to_contain_text("Example book.epub")
            page.locator("#torrent-details").get_by_role("button", name="Files").click()
            expect(page.locator("#torrent-details tbody")).to_contain_text("Example book.epub")
            page.locator("#torrent-details").get_by_role("button", name="Information").click()
            page.locator("[data-action=pause]").click()
            expect(page.locator("#torrent-table")).to_contain_text("Paused", timeout=10000)
            page.locator("#torrent-details").get_by_role("button", name="Activity").click()
            expect(page.locator("#torrent-details")).to_contain_text("pause: 1")
            # Assistant writes use a separate connection while this view stays open.
            from torrentlinker.download_queue import enqueue, entries
            from torrentlinker.indexer import Candidate, Indexer
            from torrentlinker.store import Store

            writer = Store(tmp_path / "config" / "catalogue.sqlite")
            indexer = Indexer("https://example.test/api", "key")
            candidate = Candidate(
                "Assistant queue entry", 1024, "https://example.test/a", 2, "b" * 40
            )
            page.locator("[data-view=queue]").click()
            enqueue(writer, indexer, candidate, tmp_path)
            expect(page.locator("#queue-table")).to_contain_text(candidate.title, timeout=6000)
            checkbox = page.locator("#queue-table tbody input[type=checkbox]")
            checkbox.check()
            writer.download_outcome(entries(writer)[0].key, "sent")
            expect(page.locator("#queue-table")).to_contain_text("sent", timeout=6000)
            expect(checkbox).to_be_checked()
            expect(page.locator("#queue-summary")).to_contain_text(
                "1 total · 0 queued · 0 sending · 1 sent"
            )
            expect(page.locator("#start-queue")).to_be_disabled()
            page.locator("#queue-table tbody tr").click(button="right")
            expect(page.locator("#queue-menu")).to_be_visible()
            expect(
                page.locator("#queue-menu").get_by_role("menuitem", name="Retry selected")
            ).to_be_disabled()
            if screenshot:
                page.screenshot(path=str(Path(screenshot) / "queue-web-context-menu.png"))
            page.keyboard.press("Escape")
            expect(page.locator("#queue-menu")).to_be_hidden()
            checkbox.focus()
            page.keyboard.press("Shift+F10")
            expect(page.locator("#queue-menu")).to_be_visible()
            page.locator("#queue-menu").get_by_role("menuitem", name="Remove selected").click()
            expect(page.locator("#queue-summary")).to_contain_text("0 total")
            expect(page.locator("#remove-queue")).to_be_disabled()
            assert entries(writer) == []
            page.locator("[data-view=torrents]").click()
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
            # The second profile is independent of the existing form and default.
            page.locator("[data-view=setup][data-i18n=settings]").click()
            page.locator("[data-step=client]").click()
            page.locator("#add-client").click()
            page.locator("#client-name").fill("Remote Deluge")
            page.locator("#client-kind").select_option("deluge")
            page.locator("#client-host").fill("https://other-seedbox.example")
            page.locator("#client-password").fill("second-password")
            page.locator("#client-form button.primary").click()
            expect(page.locator("#step-storage")).to_be_visible()
            expect(page.locator("#target-client option:checked")).to_have_text("Remote Deluge")
            page.locator("#target-client").select_option("default")
            page.locator("[data-step=client]").click()
            expect(page.locator("#client-kind")).to_have_value("qbittorrent")
            expect(page.locator("#client-host")).to_have_value(
                "https://seedbox.example/qbittorrent"
            )
            page.locator("#target-client").select_option("all")
            expect(page.locator("#view-torrents")).to_be_visible()
            expect(page.locator("#torrent-table")).to_contain_text("Remote Deluge")
            page.locator("#target-client").select_option("default")
            page.locator("[data-view=zen]").click()
            expect(page.locator("#zen-seeding-panel")).to_be_visible()
            page.locator("#zen-plan-tab").click()
            expect(page.locator("#plan-clients")).to_contain_text("Remote Deluge")
            if screenshot:
                page.set_viewport_size({"width": 1100, "height": 850})
                page.locator("#plan-clients").locator("..").locator("summary").click()
                for language in ("en", "fr"):
                    page.locator("#language").select_option(language)
                    page.screenshot(path=str(Path(screenshot) / f"multi-clients-{language}.png"))
            page.locator("[data-view=setup][data-i18n=settings]").click()
            page.locator("#language").select_option("en")
            page.locator("[data-settings-section=agents]").click()
            expect(page.locator("#view-agents")).to_be_visible()
            expect(page.locator("#agents-enabled")).not_to_be_checked()
            page.locator("#agents-enabled").check()
            expect(page.locator("#view-setup")).to_be_visible()
            expect(page.locator("#page-title")).to_have_text("Settings")
            expect(page.locator("#agent-connections")).to_contain_text("No connections yet")
            page.locator("[data-agent-tab=new]").click()
            page.locator("#agent-name").fill("My assistant")
            expect(page.locator("#agent-mode")).to_have_value("propose")
            page.locator("#agent-form button.primary").click()
            expect(page.locator("#agent-token-box")).to_be_visible()
            token = page.locator("#agent-token").input_value()
            with page.expect_download() as download:
                page.locator("#agent-token-save").click()
            assert download.value.suggested_filename == "torrentlinker-token.txt"
            assert Path(download.value.path()).read_text() == token + "\n"
            page.locator("[data-agent-tab=connections]").click()
            expect(page.locator("#agent-token")).to_have_value("")
            expect(page.locator("#agent-token-box")).to_be_hidden()
            expect(page.locator("#agent-connections")).to_contain_text("My assistant")
            expect(page.locator("#agent-connections")).to_contain_text("Proposals only")
            expect(page.locator("#agent-connections")).to_contain_text("qBittorrent")
            expect(page.locator("#agent-connections")).to_contain_text("10.0 GiB")
            expect(page.locator("#agent-connections")).to_contain_text("None")
            page.locator("#language").select_option("fr")
            expect(page.locator("#agent-connections")).to_contain_text("Propositions uniquement")
            page.locator("#language").select_option("en")
            page.locator("[data-agent-tab=new]").click()
            expect(page.locator("#agent-token")).to_have_value("")
            page.locator("#agent-name").fill("Upload helper")
            page.locator("#agent-mode").select_option("execute")
            page.locator("#agent-permissions input[value=uploads]").check()
            page.locator("#agent-form button.primary").click()
            expect(page.locator("#agent-token-box")).to_be_visible()
            page.locator("[data-settings-section=interface]").click()
            expect(page.locator("#settings-media-layout")).to_be_visible()
            expect(page.locator("#agent-token")).to_have_value("")
            page.locator("[data-settings-section=agents]").click()
            page.locator("[data-agent-tab=connections]").click()
            expect(page.locator("#agent-connections")).to_contain_text("Upload drafts and seeding")
            page.locator("#agent-connections .card").filter(has_text="My assistant").get_by_role(
                "button"
            ).click()
            expect(page.locator("#agent-connections")).to_contain_text("Revoked")
            expect(page.locator("#agent-connections").get_by_role("button")).to_have_count(1)
            for width in (600, 390):
                page.set_viewport_size({"width": width, "height": 850})
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            if screenshot:
                page.screenshot(
                    path=str(Path(screenshot) / "agent-settings-mobile.png"), full_page=True
                )
                page.set_viewport_size({"width": 1440, "height": 1000})
                for language in ("en", "fr"):
                    page.locator("#language").select_option(language)
                    expect(page.locator("#agent-connections")).to_contain_text(
                        "Revoked" if language == "en" else "Révoquée"
                    )
                    page.evaluate("window.scrollTo(0, 0)")
                    page.screenshot(
                        path=str(Path(screenshot) / f"agent-access-{language}.png"), full_page=True
                    )
                page.locator("#language").select_option("en")
                page.locator("#theme").select_option("light")
                page.screenshot(
                    path=str(Path(screenshot) / "agent-settings-light.png"), full_page=True
                )
                page.locator("[data-agent-tab=new]").click()
                page.screenshot(
                    path=str(Path(screenshot) / "agent-settings-new.png"), full_page=True
                )
                page.locator("[data-agent-tab=activity]").click()
                page.screenshot(
                    path=str(Path(screenshot) / "agent-settings-activity.png"), full_page=True
                )
            # A late create response must not restore a token after leaving its panel.
            page.locator("[data-agent-tab=new]").click()
            page.locator("#agent-name").fill("Delayed connection")
            pending = []

            def delay_creation(route):
                if route.request.method == "POST":
                    pending.append((route, route.fetch()))
                else:
                    route.continue_()

            page.route("**/api/agents", delay_creation)
            page.locator("#agent-form button.primary").click()
            for _ in range(50):
                if pending:
                    break
                page.wait_for_timeout(20)
            assert pending
            page.locator("[data-agent-tab=connections]").click()
            pending[0][0].fulfill(response=pending[0][1])
            expect(page.locator("#toast")).to_contain_text("token was dismissed")
            page.locator("[data-agent-tab=new]").click()
            expect(page.locator("#agent-token")).to_have_value("")
            expect(page.locator("#agent-token-box")).to_be_hidden()
            page.unroute("**/api/agents", delay_creation)
            # A persistent tab button may keep focus without blocking background refresh.
            page.locator("[data-agent-tab=connections]").click()
            created_elsewhere = page.request.post(
                f"http://127.0.0.1:{port}/api/agents",
                headers={"X-TorrentLinker": "1"},
                data={"name": "Another window", "clients": ["default"]},
            )
            assert created_elsewhere.ok
            expect(page.locator("#agent-connections")).to_contain_text(
                "Another window", timeout=7000
            )
            assert not errors, errors
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def test_local_upload_queue_review_edit_and_explicit_send(tmp_path, monkeypatch):
    import httpx
    import uvicorn
    from fastapi.testclient import TestClient
    from playwright.sync_api import expect, sync_playwright

    from tests.test_upload_completeness import complete_description
    from tests.test_upload_queue import UploadClient
    from tests.test_web_jobs import finished, login
    from torrentlinker.web.app import create_app

    posted = []

    def response(request):
        if request.method == "POST":
            posted.append(request)
            return httpx.Response(200, json={"data": {"id": 321}})
        if request.url.params.get("t") == "caps":
            return httpx.Response(200, text="<caps><categories/></caps>")
        return httpx.Response(200, json={"data": []})

    monkeypatch.setattr(
        "torrentlinker.net.client",
        lambda **kw: httpx.Client(transport=httpx.MockTransport(response)),
    )
    root = tmp_path / "models"
    root.mkdir()
    item = root / "Cable holder.stl"
    item.write_text("solid model\nendsolid model\n")

    def application():
        return create_app(
            tmp_path / "config",
            password="test-password-long",
            roots=(root,),
            connector=lambda *args: UploadClient(),
        )

    with TestClient(application()) as owner:
        login(owner)
        owner.post(
            "/api/setup/client", json={"client": "qbittorrent", "host": "https://client.example"}
        )
        owner.post(
            "/api/setup/folder",
            json={"local": str(root), "client_path": "/models", "kind": "3d-model"},
        )
        owner.post(
            "/api/setup/indexer",
            json={"url": "https://c411.org/api/torznab", "api_key": "fake-key"},
        )
        owner.post("/api/setup/announce", json={"value": "https://c411.org/announce/fake"})
        scan = owner.post("/api/jobs", json={"kind": "scan"}).json()
        assert finished(owner, scan["id"])["status"] == "completed"
        saved = owner.post(
            "/api/jobs",
            json={
                "kind": "upload-queue",
                "path": str(item),
                "upload": {
                    "title": "Cable.Holder.NOTAG.STL",
                    "description": "[b]A small cable holder[/b]",
                    "image": "https://images.example/holder.png",
                },
            },
        ).json()
        assert finished(owner, saved["id"])["status"] == "completed"
    app = application()
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
            page = browser.new_page(viewport={"width": 1000, "height": 780}, locale="en-US")
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"http://127.0.0.1:{port}/")
            page.locator("#login-password").fill("test-password-long")
            page.locator("#login-form button").click()
            page.locator("#navigation-toggle").click()
            page.locator('[data-view="upload"]').click()
            expect(page.locator("#upload-local-queue")).to_contain_text("Cable.Holder.NOTAG.STL")
            page.locator("#upload-local-queue button").first.click()
            page.locator("[data-upload-section=description]").click()
            expect(page.locator("#upload-description")).to_have_value(
                re.compile("A small cable holder")
            )
            page.locator("#upload-description").fill(
                complete_description(
                    text="Reviewed cable holder description for a generated test object."
                )
            )
            page.locator("#upload-save-local").click()
            expect(page.locator("#toast")).to_contain_text("Saved locally")
            assert posted == []
            assert not list((tmp_path / "config" / "uploads").glob("**/*.torrent"))
            page.set_viewport_size({"width": 600, "height": 800})
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            screenshots = os.getenv("TL_WEB_SCREENSHOTS")
            if screenshots:
                target = Path(screenshots)
                target.mkdir(parents=True, exist_ok=True)
                page.locator("#toast").evaluate("e => e.hidden = true")
                page.set_viewport_size({"width": 1280, "height": 900})
                for lang in ("en", "fr"):
                    page.locator("#language").select_option(lang)
                    for theme in ("dark", "light"):
                        page.locator("#theme").select_option(theme)
                        for section in ("details", "files", "description", "artwork", "review"):
                            page.locator(f"[data-upload-section={section}]").click()
                            page.mouse.move(1, 1)
                            page.wait_for_timeout(160)
                            page.screenshot(
                                path=str(target / f"web-upload-{section}-{lang}-{theme}.png")
                            )
                page.locator("#language").select_option("en")
                page.locator("#theme").select_option("dark")
            page.on("dialog", lambda dialog: dialog.accept())
            page.locator("[data-upload-section=review]").click()
            page.locator("#upload-reviewed").check()
            page.locator("#upload-send-local").click()
            expect(page.locator("#upload-local-queue")).to_contain_text(
                "Sent to c411", timeout=10000
            )
            page.locator("[data-upload-view=remote]").click()
            expect(page.locator("#upload-remote-list")).to_contain_text("No drafts on c411")
            if screenshots:
                page.screenshot(path=str(target / "web-upload-c411-en-dark.png"))
                page.locator("#upload-new").click()
                expect(page.locator("#upload-sources")).to_be_visible()
                page.screenshot(path=str(target / "web-upload-new-en-dark.png"))
            assert len(posted) == 1
            assert "Reviewed cable holder description" in posted[0].content.decode()
            assert not errors
            browser.close()
    finally:
        server.should_exit = True
        thread.join(10)
