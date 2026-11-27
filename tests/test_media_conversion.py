"""Compatible playback through authenticated HTTP, using generated local media."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.test_media_api import login, media_app, scan


def video(path, seconds=2):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg is needed for compatible playback fixtures")
    subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=s=320x180:r=10",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440",
            "-t",
            str(seconds),
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-metadata:s:a:0",
            "language=fra",
            str(path),
        ],
        check=True,
        timeout=20,
    )


def test_compatible_playback_exposes_choices_and_streams_without_changing_original(tmp_path):
    app, root = media_app(tmp_path)
    path = root / "Example.2024.mkv"
    video(path)
    original = path.read_bytes()
    with TestClient(app) as browser:
        login(browser)
        scan(browser)
        row = browser.get("/api/media?kind=video").json()["rows"][0]
        endpoint = f"/api/media/items/{row['id']}/playback"
        choices = browser.get(endpoint)
        assert choices.status_code == 200, choices.text
        assert choices.json()["qualities"] == ["original", "360", "480", "720", "1080"]
        assert choices.json()["audio"][0]["language"] == "fr"
        # What a device needs to tell whether it plays the original as it is.
        assert choices.json()["container"] == "matroska"
        assert choices.json()["video_codec"] == "h264"
        assert choices.json()["bit_depth"] == 8
        response = browser.get(
            endpoint + "/stream",
            params={
                "quality": "360",
                "start": 0.5,
                "audio": 0,
                "playback_id": "test-player",
            },
        )
        assert response.status_code == 200, response.text
        assert response.headers["content-type"].startswith("video/mp4")
        assert b"ftyp" in response.content[:64]
        assert b"moof" in response.content
        assert path.read_bytes() == original
        assert browser.delete(endpoint + "/test-player").status_code == 200


def test_playback_requires_login_and_rejects_invalid_choices(tmp_path):
    app, root = media_app(tmp_path)
    video(root / "Example.2024.mkv")
    with TestClient(app) as browser:
        endpoint = "/api/media/items/guessed/playback"
        assert browser.get(endpoint).status_code == 401
        assert browser.get(endpoint + "/stream?playback_id=test-player").status_code == 401
        assert browser.delete(endpoint + "/test-player").status_code in {401, 403}
        login(browser)
        scan(browser)
        row = browser.get("/api/media?kind=video").json()["rows"][0]
        endpoint = f"/api/media/items/{row['id']}/playback/stream"
        for values in ({"quality": "4k"}, {"start": -1}, {"audio": -1}, {"playback_id": "../x"}):
            response = browser.get(endpoint, params={"playback_id": "test-player", **values})
            assert response.status_code == 422, response.text
        for values in ({"start": 20}, {"audio": 90}):
            response = browser.get(endpoint, params={"playback_id": "test-player", **values})
            assert response.status_code == 409, response.text
            assert str(root) not in response.text


@pytest.mark.skipif(os.name == "nt", reason="Realtime encoder wrapper uses a POSIX shell")
def test_http_conversion_capacity_cancellation_and_disconnect(tmp_path, monkeypatch):
    import socket
    import threading
    import time

    import httpx
    import uvicorn

    app, root = media_app(tmp_path)
    video(root / "Example.2024.mkv", seconds=30)
    app.state.agent_service.media.scan("default", threading.Event(), lambda _p: None)
    # Keep the external encoder running while HTTP clients exercise its lifecycle.
    # The wrapper still decodes the generated file with real FFmpeg, at realtime speed.
    which = shutil.which
    executable = which("ffmpeg")
    wrapper = tmp_path / "realtime-ffmpeg"
    wrapper.write_text(f'#!/bin/sh\nexec "{executable}" -re "$@"\n')
    wrapper.chmod(0o700)
    monkeypatch.setattr(
        shutil, "which", lambda name: str(wrapper) if name == "ffmpeg" else which(name)
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
        with httpx.Client(
            base_url=f"http://127.0.0.1:{listener.getsockname()[1]}", timeout=15
        ) as client:
            login(client)
            row = client.get("/api/media?kind=video").json()["rows"][0]
            endpoint = f"/api/media/items/{row['id']}/playback"
            with client.stream(
                "GET", endpoint + "/stream?quality=360&playback_id=player-one"
            ) as one:
                assert one.status_code == 200
                with client.stream(
                    "GET", endpoint + "/stream?quality=360&playback_id=player-two"
                ) as two:
                    assert two.status_code == 200
                    blocked = client.get(endpoint + "/stream?quality=360&playback_id=player-three")
                    assert blocked.status_code == 409
                    assert client.delete(endpoint + "/player-one").status_code == 200
                    with client.stream(
                        "GET", endpoint + "/stream?quality=360&playback_id=player-three"
                    ) as replacement:
                        assert replacement.status_code == 200
                        assert b"ftyp" in next(replacement.iter_bytes())[:64]
                # Both remaining connections disconnected. Capacity must be reusable.
                for _ in range(100):
                    with client.stream(
                        "GET", endpoint + "/stream?quality=360&playback_id=player-four"
                    ) as last:
                        status = last.status_code
                        if status == 200:
                            break
                    time.sleep(0.02)
                assert status == 200
    finally:
        server.should_exit = True
        thread.join(timeout=15)
        listener.close()


def source_facts(width=3840, height=2160):
    return {
        "available": True,
        "duration": 600.0,
        "audio": [],
        "width": width,
        "height": height,
        "hdr": False,
    }


def command_of(quality, facts, limit=None):
    from torrentlinker.media_conversion import PlaybackChoice

    return PlaybackChoice(quality, 0, 0, limit).command(Path("/films/a.mkv"), facts)


def test_the_source_quality_keeps_the_films_own_resolution(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")
    command = command_of("source", source_facts(1280, 720))
    filters = command[command.index("-vf") + 1]
    assert "scale=trunc(iw/2)*2:trunc(ih/2)*2" in filters and "min(" not in filters
    assert command[command.index("-b:v") + 1] == "1778k"  # the 1080p rate, by pixels
    # A 4K film keeps its size too, at a rate that follows it.
    command = command_of("source", source_facts())
    assert "min(" not in command[command.index("-vf") + 1]
    assert command[command.index("-b:v") + 1] == "16000k"


def test_the_source_quality_is_lowered_only_to_a_members_limit(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")
    command = command_of("source", source_facts(1920, 1080), limit=720)
    assert "scale=w=-2:h=720:" in command[command.index("-vf") + 1]
    assert command[command.index("-b:v") + 1] == "1778k"
    # A limit above the film leaves it alone.
    command = command_of("source", source_facts(1280, 720), limit=1080)
    assert "scale=trunc(iw/2)*2" in command[command.index("-vf") + 1]


def test_the_sound_quality_copies_the_picture_and_converts_only_the_audio(monkeypatch):
    # A film whose picture plays but whose AC-3 or DTS sound does not keeps its picture.
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")
    facts = source_facts(1920, 1080) | {"video_codec": "h264", "sound": True}
    command = command_of("sound", facts)
    assert command[command.index("-c:v") + 1] == "copy"
    assert "-vf" not in command
    assert command[command.index("-c:a") + 1] == "aac"
    # An HEVC picture is copied too, tagged the way a browser's stream reader expects.
    hevc = source_facts(1920, 1080) | {"video_codec": "hevc", "sound": True}
    command = command_of("sound", hevc)
    assert command[command.index("-tag:v") + 1] == "hvc1"
    # Another picture codec cannot be copied into the stream the browser reads.
    with pytest.raises(ValueError):
        command_of("sound", source_facts(1920, 1080) | {"video_codec": "mpeg4", "sound": False})
    # A Member limited below the film's height gets no copy of its full picture.
    with pytest.raises(ValueError):
        command_of("sound", facts, limit=720)


def test_the_container_and_bit_depth_are_named_as_a_device_asks_for_them():
    from torrentlinker.media_conversion import _bit_depth, _container

    assert _container("matroska,webm", Path("a.mkv")) == "matroska"
    assert _container("matroska,webm", Path("a.WebM")) == "webm"
    assert _container("mov,mp4,m4a,3gp,3g2,mj2", Path("a.mp4")) == "mp4"
    assert _container("avi", Path("a.avi")) == "avi"
    assert _bit_depth({"pix_fmt": "yuv420p10le"}) == 10
    assert _bit_depth({"pix_fmt": "yuv420p"}) == 8
    assert _bit_depth({"pix_fmt": "p010le"}) == 10
    assert _bit_depth({"bits_per_raw_sample": "10"}) == 10
