"""The playing video's details under the picture, in the desktop Media tab."""

import os
import shutil
import subprocess
import sys
import threading

import pytest


def test_desktop_video_shows_its_details_under_the_picture(qtbot, tmp_path, request):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("ffmpeg is required for a real playable video fixture")
    # WebEngine needs its own Qt application and profile, as in the other panel tests.
    if not os.getenv("TL_PLAYER_DETAILS_CHILD"):
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", request.node.nodeid],
            env={
                **os.environ,
                "TL_PLAYER_DETAILS_CHILD": "1",
                "XDG_CONFIG_HOME": str(tmp_path / "qt"),
            },
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return
    from PIL import Image

    from tests.test_community_interfaces import js, wait_js
    from tests.test_media_api import media_app
    from torrentlinker.gui.media import MediaTab

    app, root = media_app(tmp_path)
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
            str(root / "Validation.Film.2026.MULTi.1080p.WEB.AAC.2.0.mp4"),
        ],
        check=True,
    )
    Image.new("RGB", (200, 300), "#cc5533").save(root / "poster.png")
    library = app.state.agent_service.media
    library.scan("default", threading.Event(), lambda _: None)
    item = library.listing("default", kind="video")["rows"][0]
    tab = MediaTab(lambda: app.state.assistant, lambda: "default", lambda: None)
    qtbot.addWidget(tab)
    tab.resize(1280, 900)
    tab.show()
    tab.activate()
    tab.command("play", media_ids=[item["id"]], index=0)
    details = tab.playing_details
    wait_js(qtbot, details, "document.querySelector('#title')?.textContent==='Validation Film'")
    assert js(qtbot, details, "document.querySelector('#meta').textContent").startswith("2026")
    flags = js(
        qtbot, details, "[...document.querySelectorAll('#flags li')].map(n=>n.textContent).join()"
    )
    assert flags.split(",")[0] == "1080p" and "AAC 2.0" in flags and "MULTI" in flags
    wait_js(qtbot, details, "document.querySelector('#poster img')?.naturalWidth===200")
    assert not tab.now_playing.isVisible()  # the title is in the details, not above them
    # The picture leaves room for the details below it.
    qtbot.waitUntil(lambda: details.height() > 150)
    qtbot.waitUntil(
        lambda: tab.video.height() + details.height() <= tab.media_column.height(), timeout=5000
    )
    if screenshot := os.getenv("TL_PLAYER_DETAILS_SCREENSHOT"):
        qtbot.wait(300)
        tab.grab().save(screenshot)
    tab.stop()
