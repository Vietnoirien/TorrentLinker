"""Opt-in browser playback through owner HTTP APIs and real local media."""

import os
import re
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.getenv("TL_WEB_BROWSER") != "1", reason="opt-in browser test")


def test_media_playback_survives_browsing_and_contextual_chat(tmp_path):
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    from torrentlinker.config import Settings
    from torrentlinker.domain import LibraryFolder
    from torrentlinker.web.app import create_app

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("ffmpeg is required for a real playable video fixture")
    root = tmp_path / "media"
    root.mkdir()
    subprocess.run(
        [
            ffmpeg,
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=160x120:r=10",
            "-t",
            "20",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(root / "Validation.Film.2026.mp4"),
        ],
        check=True,
    )
    shutil.copy(Path(__file__).parent / "fixtures/audio/track16.flac", root / "Validation.flac")
    shutil.copy(Path(__file__).parent / "fixtures/audio/track24.flac", root / "Second.flac")
    (root / "Unsupported.Video.mp4").write_bytes(b"An unsupported local media container")
    edition = root / "Different edition"
    edition.mkdir()
    shutil.copy(root / "Validation.flac", edition / "Validation.flac")
    config = tmp_path / "config"
    config.mkdir()
    settings = Settings()
    settings.library_folders = [LibraryFolder(root)]
    settings.save(config / "settings.json")
    app = create_app(
        config, password="test-password-long", roots=(root,), monitor_verifications=False
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
            browser = pw.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
            page = browser.new_page(viewport={"width": 1280, "height": 900}, locale="en-US")
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"http://127.0.0.1:{port}/")
            page.locator("#login-password").fill("test-password-long")
            page.locator("#login-form button").click()
            page.locator('[data-view="media"]').click()
            page.locator("#media-refresh").click()
            expect(page.locator("#media-results")).to_contain_text("Validation", timeout=15000)
            page.locator(".media-card").filter(has_text="Validation Film").get_by_role(
                "button", name="Play", exact=True
            ).click()
            video = page.locator("#media-video")
            page.wait_for_function("() => document.querySelector('#media-video').currentTime > 0.1")
            source = video.get_attribute("src")
            page.locator("#media-chat").click()
            expect(page.locator("#media-chat-panel")).to_be_visible()
            expect(page.locator("#assistant-prompt")).to_be_visible()
            assert video.get_attribute("src") == source
            screenshots = os.getenv("TL_WEB_SCREENSHOTS")
            if screenshots:
                Path(screenshots).mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(Path(screenshots) / "media-contextual-chat.png"))
            page.locator("#media-chat-close").click()
            page.locator('[data-view="library"]').click()
            expect(video).to_be_visible()
            assert video.get_attribute("src") == source
            page.locator('[data-view="media"]').click()
            video.evaluate("node => { node.pause(); node.currentTime = 5; }")
            page.wait_for_timeout(1300)
            page.reload()
            page.locator('[data-view="media"]').click()
            page.wait_for_function(
                "() => document.querySelector('#media-video').currentTime >= 4.9"
            )
            assert video.evaluate("node => node.paused") is True
            with page.expect_popup() as opening:
                page.evaluate("() => window.open(location.href)")
            other = opening.value
            other.locator('[data-view="media"]').click()
            expect(other.locator("#media-player-shell")).to_be_hidden()
            other.locator(".media-card").filter(has_text="Validation Film").get_by_role(
                "button", name="Play", exact=True
            ).click()
            other.wait_for_function("() => document.querySelector('#media-video').currentTime > 0")
            assert video.evaluate("node => node.paused && node.currentTime >= 4.9")
            other.close()
            page.locator("#media-music-tab").click()
            expect(page.locator("#media-results article")).to_have_count(2)
            assert video.get_attribute("src") == source
            page.locator(".media-card").filter(has_text="2 tracks").get_by_role(
                "button", name="Details", exact=True
            ).click()
            expect(page.locator("#media-details li")).to_have_count(2)
            page.get_by_role("button", name="Close details").click()
            page.locator(".media-card").filter(has_text="1 track").get_by_role(
                "button", name="Play", exact=True
            ).click()
            page.wait_for_function("() => document.querySelector('#media-audio').currentTime > 0")
            page.locator("#media-player-shell summary").click()
            expect(page.locator("#media-player-queue li")).to_have_count(1)
            page.locator("#media-audio").evaluate("node => node.pause()")
            page.locator(".media-card").filter(has_text="1 track").get_by_role(
                "button", name="Add to queue"
            ).click()
            expect(page.locator("#media-player-queue li")).to_have_count(2)
            page.locator("#media-player-queue li").nth(1).get_by_role(
                "button", name="Remove"
            ).click()
            expect(page.locator("#media-player-queue li")).to_have_count(1)
            assert page.locator("#media-audio").evaluate("node => node.paused") is True
            page.locator("#media-playlist-name").fill("Evening listening")
            page.locator("#media-save-playlist button").click()
            expect(page.locator("#media-playlist-list")).to_contain_text("Evening listening")
            page.reload()
            page.locator('[data-view="media"]').click()
            page.locator("#media-music-tab").click()
            expect(page.locator("#media-playlist-list")).to_contain_text("Evening listening")
            page.set_viewport_size({"width": 600, "height": 800})
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            page.locator("#media-video-tab").click()
            page.locator(".media-card").filter(has_text="Unsupported Video").get_by_role(
                "button", name="Play", exact=True
            ).click()
            expect(page.locator("#media-codec-error")).to_be_visible()
            expect(page.locator("#media-external")).to_have_attribute("href", re.compile("/stream"))
            assert not errors, errors
            browser.close()
    finally:
        server.should_exit = True
        thread.join(10)


def test_explicit_fixed_prefix_video_preview_can_refresh_and_stop(tmp_path):
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    from torrentlinker.config import Settings
    from torrentlinker.domain import LibraryFolder, Torrent
    from torrentlinker.web.app import create_app

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("ffmpeg is required for a playable partial video fixture")
    root = tmp_path / "media"
    root.mkdir()
    video_file = root / "Preview.Film.mp4"
    subprocess.run(
        [
            ffmpeg,
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x240:rate=15",
            "-t",
            "20",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(video_file),
        ],
        check=True,
    )
    shutil.copy(video_file, root / "Complete.Film.mp4")
    shutil.copy(video_file, root / "Other.Film.mp4")
    size = video_file.stat().st_size
    piece_size = 16384
    piece_count = (size + piece_size - 1) // piece_size

    class Client:
        verified = piece_count // 2

        def check(self):
            return "qBittorrent preview fixture"

        def folder_settings(self):
            return []

        def torrents(self, **kwargs):
            return [
                Torrent(
                    "a" * 40,
                    video_file.name,
                    root,
                    files={video_file.name: size},
                    size=size,
                    progress=0.5,
                    state="downloading",
                )
            ]

        def torrent(self, hash, **kwargs):
            return self.torrents()[0]

        def media_preview_state(self, hash):
            return {
                "sequential": True,
                "files": [
                    {"name": video_file.name, "size": size, "piece_range": [0, piece_count - 1]}
                ],
                "piece_size": piece_size,
                "piece_states": [2] * self.verified + [0] * (piece_count - self.verified),
            }

    client = Client()
    config = tmp_path / "config"
    config.mkdir()
    settings = Settings()
    settings.library_folders = [LibraryFolder(root)]
    settings.save(config / "settings.json")
    (config / "client.ready").write_text("connected")
    app = create_app(
        config,
        password="test-password-long",
        roots=(root,),
        connector=lambda *args: client,
        monitor_verifications=False,
    )
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", log_config=None))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.02)
        with sync_playwright() as pw:
            browser = pw.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
            page = browser.new_page(locale="en-US")
            page.goto(f"http://127.0.0.1:{listener.getsockname()[1]}/")
            page.locator("#login-password").fill("test-password-long")
            page.locator("#login-form button").click()
            page.locator('[data-view="media"]').click()
            page.locator("#media-refresh").click()
            card = page.locator(".media-card").filter(has_text="Preview Film")
            expect(card).to_be_visible(timeout=15000)
            expect(card.get_by_role("button", name="Play", exact=True)).to_be_disabled()
            card.get_by_role("button", name="Details", exact=True).click()
            page.get_by_role("button", name="Preview downloaded portion", exact=True).click()
            page.wait_for_function("() => document.querySelector('#media-video').currentTime > .1")
            expect(page.locator("#media-preview-state")).to_contain_text("fixed")
            screenshots = os.getenv("TL_WEB_SCREENSHOTS")
            if screenshots:
                Path(screenshots).mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(Path(screenshots) / "media-partial-preview.png"))
            preview_source = page.locator("#media-video").evaluate("node => node.src")
            assert "/previews/" in preview_source
            prefix = page.request.get(preview_source)
            assert len(prefix.body()) == client.verified * piece_size
            client.verified += 1
            # The old preview remains fixed even when the Torrent Client downloads more.
            assert len(page.request.get(preview_source).body()) == len(prefix.body())
            page.get_by_role("button", name="Refresh preview", exact=True).click()
            page.wait_for_function(
                "old => document.querySelector('#media-video').src !== "
                "new URL(old, location.href).href",
                arg=preview_source,
            )
            refreshed = page.locator("#media-video").evaluate("node => node.src")
            assert len(page.request.get(refreshed).body()) == client.verified * piece_size
            page.locator(".media-card").filter(has_text="Complete Film").get_by_role(
                "button", name="Play", exact=True
            ).click()
            page.wait_for_function(
                "() => document.querySelector('#media-video').src.includes('/items/')"
            )
            expect(page.locator("#media-preview-state")).to_be_hidden()
            assert page.request.get(refreshed).status >= 400
            page.get_by_role("button", name="Preview downloaded portion", exact=True).click()
            expect(page.locator("#media-preview-state")).to_be_visible()
            stopped_source = page.locator("#media-video").evaluate("node => node.src")
            page.get_by_role("button", name="Stop", exact=True).click()
            expect(page.locator("#media-preview-state")).to_be_hidden()
            assert page.request.get(stopped_source).status >= 400
            assert page.locator("#media-video").get_attribute("src") is None
            # The same cancellation rule applies while ordinary item metadata is delayed.
            normal_metadata = []

            def delay_metadata(route):
                normal_metadata.append((route, route.fetch()))

            page.locator(".media-card").filter(has_text="Complete Film").get_by_role(
                "button", name="Play", exact=True
            ).click()
            page.wait_for_function(
                "() => document.querySelector('#media-video').src.includes('/items/')"
            )
            normal_id = (
                page.locator("#media-video")
                .evaluate("node => node.src")
                .split("/items/", 1)[1]
                .split("/", 1)[0]
            )
            metadata_pattern = f"**/api/media/items/{normal_id}?*"
            page.route(metadata_pattern, delay_metadata)
            for decision in ("stop", "play"):
                page.locator(".media-card").filter(has_text="Other Film").get_by_role(
                    "button", name="Play", exact=True
                ).click()
                expect(page.locator("#media-now-playing")).to_have_text("Other Film")
                replacement_source = page.locator("#media-video").get_attribute("src")
                page.locator(".media-card").filter(has_text="Complete Film").get_by_role(
                    "button", name="Play", exact=True
                ).click()
                for _ in range(100):
                    if normal_metadata:
                        break
                    page.wait_for_timeout(50)
                assert normal_metadata, "Ordinary playback metadata was not requested"
                route, response = normal_metadata.pop()
                if decision == "stop":
                    page.get_by_role("button", name="Stop", exact=True).click()
                else:
                    page.locator(".media-card").filter(has_text="Other Film").get_by_role(
                        "button", name="Play", exact=True
                    ).click()
                route.fulfill(response=response)
                page.wait_for_timeout(250)
                assert page.locator("#media-video").get_attribute("src") == (
                    None if decision == "stop" else replacement_source
                )
            page.unroute(metadata_pattern, delay_metadata)
            # A preview response can arrive after a later playback decision.
            held = []

            def delay_preview(route):
                held.append((route, route.fetch()))

            page.route("**/api/media/items/*/preview", delay_preview)
            for decision in ("stop", "play", "client"):
                page.locator(".media-card").filter(has_text="Complete Film").get_by_role(
                    "button", name="Play", exact=True
                ).click()
                expect(page.locator("#media-now-playing")).to_have_text("Complete Film")
                normal_source = page.locator("#media-video").get_attribute("src")
                page.get_by_role("button", name="Preview downloaded portion", exact=True).click()
                for _ in range(100):
                    if held:
                        break
                    page.wait_for_timeout(50)
                assert held, "Preview creation request was not received"
                route, response = held.pop()
                preview_id = response.json()["preview_id"]
                if decision == "stop":
                    page.get_by_role("button", name="Stop", exact=True).click()
                elif decision == "play":
                    page.locator(".media-card").filter(has_text="Complete Film").get_by_role(
                        "button", name="Play", exact=True
                    ).click()
                else:
                    page.locator("#target-client").select_option("all")
                print("before fulfill", decision, page.evaluate("() => ({generation: media.playbackGeneration, source: document.querySelector('#media-video').getAttribute('src'), queue: media.queue.length})"))
                with page.expect_response(
                    lambda reply, expected=preview_id: (
                        reply.request.method == "DELETE" and f"/previews/{expected}" in reply.url
                    ),
                    timeout=4000,
                ):
                    route.fulfill(response=response)
                print("after fulfill", decision, page.evaluate("() => ({generation: media.playbackGeneration, source: document.querySelector('#media-video').getAttribute('src'), queue: media.queue.length})"))
                expect(page.locator("#media-preview-state")).to_be_hidden()
                assert page.locator("#media-video").get_attribute("src") == (
                    None if decision == "stop" else normal_source
                )

            browser.close()
    finally:
        server.should_exit = True
        thread.join(10)
