"""Media user flows through the native player and saved library interfaces."""

from pathlib import Path

from torrentlinker.config import Settings
from torrentlinker.gui.main_window import MainWindow
from torrentlinker.store import Store


def test_media_workspace_opens_without_starting_connected_services(qtbot, tmp_path: Path):
    window = MainWindow(Settings(), tmp_path / "settings.json", Store(tmp_path / "s.db"))
    qtbot.addWidget(window)
    assert "Media" in [window.tabs.tabText(i) for i in range(window.tabs.count())]
    assert window.agent_runtime is None
    assert window.media_tab.player is None


def test_native_track_playback_seek_and_browsing_keep_the_same_player(qtbot, tmp_path, monkeypatch):
    import math
    import struct
    import threading
    import wave

    from PySide6.QtCore import Qt
    from PySide6.QtMultimedia import QMediaPlayer
    from PySide6.QtWidgets import QListView

    from torrentlinker.domain import LibraryFolder
    from torrentlinker.gui.media import MediaTab
    from torrentlinker.web.app import create_app

    root = tmp_path / "music"
    root.mkdir()
    with wave.open(str(root / "tone.wav"), "wb") as track:
        track.setparams((1, 2, 22050, 0, "NONE", "not compressed"))
        track.writeframes(
            b"".join(struct.pack("<h", int(3000 * math.sin(i / 10))) for i in range(22050 * 12))
        )
    import shutil

    shutil.copy(root / "tone.wav", root / "second.wav")
    shutil.copy(root / "tone.wav", root / "third.wav")
    settings = Settings()
    settings.library_folders = [LibraryFolder(root)]
    config = tmp_path / "config"
    config.mkdir()
    settings.save(config / "settings.json")
    app = create_app(
        config, password="test-password-long", roots=(root,), monitor_verifications=False
    )
    service = app.state.assistant
    service.agent.media.scan("default", threading.Event(), lambda _progress: None)
    tab = MediaTab(lambda: service, lambda: "default", lambda: None)
    qtbot.addWidget(tab)
    tab.show()
    tab.activate()
    tab.kind.setCurrentIndex(tab.kind.findData("music"))
    qtbot.waitUntil(lambda: tab.results.count() == 3)
    qtbot.waitUntil(lambda: tab.results.count() > 0 and tab.results.isEnabled())
    assert tab.results.viewMode() == QListView.ViewMode.ListMode
    for view in ("albums", "artists"):
        tab.view.setCurrentIndex(tab.view.findData(view))
        qtbot.waitUntil(
            lambda: (
                tab.results.isEnabled() and tab.results.viewMode() == QListView.ViewMode.IconMode
            )
        )
        assert not tab.results.item(0).icon().isNull()
        assert tab.results.iconSize().width() >= 128
    tab.view.setCurrentIndex(tab.view.findData("tracks"))
    qtbot.waitUntil(
        lambda: tab.results.isEnabled() and tab.results.viewMode() == QListView.ViewMode.ListMode
    )
    tab.results.item(0).setSelected(True)
    qtbot.mouseClick(tab.play_button, Qt.LeftButton)
    qtbot.waitUntil(lambda: tab.player.duration() == 12000, timeout=15000)
    qtbot.waitUntil(lambda: tab.player.position() > 0, timeout=10000)
    tab.command("seek", position=5)
    qtbot.waitUntil(lambda: tab.player.position() >= 5000)
    tab.results.clearSelection()
    tab.results.item(1).setSelected(True)
    tab.results.item(2).setSelected(True)
    qtbot.mouseClick(tab.enqueue_button, Qt.LeftButton)
    assert tab.queue.count() == 3
    from PySide6.QtWidgets import QInputDialog

    monkeypatch.setattr(QInputDialog, "getText", lambda *_args: ("Evening", True))
    qtbot.mouseClick(tab.save_playlist, Qt.LeftButton)
    qtbot.waitUntil(lambda: tab.playlists.currentText() == "Evening")
    assert len(service.agent.media.playlists("default")[0]["media_ids"]) == 3
    source = tab.player.source()
    tab.search.setText("no such track")
    tab.kind.setCurrentIndex(tab.kind.findData("video"))
    qtbot.waitUntil(lambda: tab.results.count() == 0)
    assert tab.player.source() == source
    assert tab.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
    qtbot.mouseClick(tab.chat, Qt.LeftButton)
    assert tab.assistant.conversation_id == tab.conversation_id
    assert isinstance(tab.conversation_id, str)
    first_conversation = tab.conversation_id
    qtbot.mouseClick(tab.chat, Qt.LeftButton)
    assert tab.conversation_id == first_conversation
    assert tab.player.source() == source
    assert tab.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
    tab.command("pause")
    tab.report()
    saved = service.agent.media.detail("default", tab.state["current_id"])
    assert saved["position"] >= 5
    tab.command("shuffle", shuffle=True)
    tab.command("repeat", repeat="all")
    tab.command("play", media_ids=tab.state["queue"], index=1)
    qtbot.waitUntil(lambda: tab.player.duration() == 12000)
    playing = tab.player.source()
    tab.queue.setCurrentRow(0)
    tab.remove_from_queue()
    assert tab.player.source() == playing
    assert tab.state["index"] == 0
    assert tab.queue.count() == 2
    tab.stop()
    restored = MediaTab(lambda: service, lambda: "default", lambda: None)
    qtbot.addWidget(restored)
    restored.activate()
    assert restored.session_id == tab.session_id
    assert restored.state["queue"] == tab.state["queue"]
    assert restored.shuffle.isChecked()
    assert restored.repeat.currentData() == "all"
    assert restored.conversation_id == first_conversation
    qtbot.waitUntil(lambda: restored.player.duration() == 12000)
    assert restored.player.source() == playing
    assert restored.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState
    restored.stop()


def test_native_video_plays_with_local_subtitles(qtbot, tmp_path):
    import shutil
    import subprocess
    import threading

    import pytest
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QListView

    from torrentlinker.domain import LibraryFolder
    from torrentlinker.gui.media import MediaTab
    from torrentlinker.web.app import create_app

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("ffmpeg fixture generator unavailable")
    root = tmp_path / "video"
    root.mkdir()
    subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=160x120:r=10",
            "-t",
            "6",
            "-c:v",
            "mpeg4",
            str(root / "Clip.mp4"),
        ],
        check=True,
        capture_output=True,
    )
    (root / "Clip.srt").write_text("1\n00:00:01,000 --> 00:00:05,000\nA local caption\n")
    config = tmp_path / "config"
    config.mkdir()
    settings = Settings()
    settings.library_folders = [LibraryFolder(root)]
    settings.save(config / "settings.json")
    app = create_app(
        config, password="test-password-long", roots=(root,), monitor_verifications=False
    )
    service = app.state.assistant
    service.agent.media.scan("default", threading.Event(), lambda _progress: None)
    tab = MediaTab(lambda: service, lambda: "default", lambda: None)
    qtbot.addWidget(tab)
    tab.show()
    tab.activate()
    qtbot.waitUntil(lambda: tab.results.count() > 0 and tab.results.isEnabled())
    assert tab.results.viewMode() == QListView.ViewMode.IconMode
    assert tab.results.gridSize().width() >= 180
    assert tab.results.iconSize().height() >= 170
    assert not tab.results.item(0).icon().isNull()
    tab.results.item(0).setSelected(True)
    qtbot.mouseClick(tab.play_button, Qt.LeftButton)
    qtbot.waitUntil(lambda: tab.player.hasVideo(), timeout=15000)
    qtbot.waitUntil(lambda: tab.subtitles.count() == 2)
    tab.subtitles.setCurrentIndex(1)
    tab.command("seek", position=2)
    qtbot.waitUntil(lambda: tab.caption.text() == "A local caption")
    qtbot.waitUntil(lambda: tab.player.videoSink().videoFrame().isValid(), timeout=10000)
    tab.stop()


def test_native_explicit_preview_decodes_h264_without_reading_missing_pieces(qtbot, tmp_path):
    import math
    import shutil
    import subprocess
    import threading

    import pytest
    from PySide6.QtCore import QCoreApplication, Qt, QThreadPool

    from torrentlinker.domain import LibraryFolder, Torrent
    from torrentlinker.gui.media import MediaTab, VerifiedPrefixDevice
    from torrentlinker.web.app import create_app

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("ffmpeg fixture generator unavailable")
    root = tmp_path / "video"
    root.mkdir()
    source = root / "Downloading.mp4"
    subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=160x120:rate=10",
            "-t",
            "12",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-g",
            "10",
            "-movflags",
            "+faststart",
            str(source),
        ],
        check=True,
        capture_output=True,
    )
    total = source.stat().st_size
    pieces = math.ceil(total / 4096)
    verified_pieces = pieces // 2
    verified_bytes = verified_pieces * 4096

    class SequentialQbit:
        delay = False
        entered = threading.Event()
        release = threading.Event()

        def torrents(self, **_kwargs):
            return [self.torrent("a" * 40)]

        def torrent(self, _hash, **_kwargs):
            return Torrent("a" * 40, source.name, root, {source.name: total}, progress=0.5)

        def media_preview_state(self, _hash):
            if self.delay:
                self.delay = False
                self.entered.set()
                assert self.release.wait(10), "The delayed preview fixture was not released"
            return {
                "sequential": True,
                "files": [{"name": source.name, "size": total, "piece_range": [0, pieces - 1]}],
                "piece_size": 4096,
                "piece_states": [2] * verified_pieces + [0] + [2] * (pieces - verified_pieces - 1),
            }

    config = tmp_path / "config"
    config.mkdir()
    settings = Settings()
    settings.library_folders = [LibraryFolder(root)]
    settings.save(config / "settings.json")
    app = create_app(
        config, password="test-password-long", roots=(root,), monitor_verifications=False
    )
    service = app.state.assistant
    client = SequentialQbit()
    service.agent.setup._client = client
    service.agent.setup.configured = True
    service.agent.media.scan("default", threading.Event(), lambda _progress: None)
    tab = MediaTab(lambda: service, lambda: "default", lambda: None)
    qtbot.addWidget(tab)
    tab.show()
    tab.activate()
    qtbot.waitUntil(lambda: tab.results.count() > 0 and tab.results.isEnabled())
    tab.results.item(0).setSelected(True)
    assert tab.preview_button.isVisible()
    qtbot.mouseClick(tab.preview_button, Qt.LeftButton)
    qtbot.waitUntil(lambda: tab.preview_device is not None, timeout=10000)
    qtbot.waitUntil(lambda: tab.player.videoSink().videoFrame().isValid(), timeout=15000)
    assert tab.player.sourceDevice().size() == verified_bytes
    assert tab.player.source().toString() == "verified-preview.mp4"
    assert tab.refresh_preview.isVisible()
    tab.command("seek", position=1)
    qtbot.waitUntil(lambda: tab.player.position() >= 1000)
    assert tab.preview_device.size() == verified_bytes
    completed = root / "Complete.mp4"
    shutil.copy(source, completed)
    service.agent.media.scan("default", threading.Event(), lambda _progress: None)
    tab.refresh()
    qtbot.waitUntil(lambda: tab.results.count() == 2 and tab.results.isEnabled())

    def select_release(name):
        tab.results.clearSelection()
        index = next(i for i, row in enumerate(tab.rows) if row["release"] == name)
        tab.results.item(index).setSelected(True)

    def delayed_preview():
        client.entered.clear()
        client.release.clear()
        client.delay = True
        select_release(source.name)
        qtbot.mouseClick(tab.preview_button, Qt.LeftButton)
        qtbot.waitUntil(client.entered.is_set)

    delayed_preview()
    select_release(completed.name)
    qtbot.mouseClick(tab.play_button, Qt.LeftButton)
    expected = tab.player.source()
    assert expected.toLocalFile() == str(completed)
    client.release.set()
    qtbot.waitUntil(lambda: QThreadPool.globalInstance().activeThreadCount() == 0)
    QCoreApplication.processEvents()
    assert tab.player.source() == expected
    assert tab.preview_id == ""
    assert tab.preview_device is None
    delayed_preview()
    tab.stop()
    client.release.set()
    qtbot.waitUntil(lambda: QThreadPool.globalInstance().activeThreadCount() == 0)
    QCoreApplication.processEvents()
    assert tab.preview_id == ""
    assert tab.preview_device is None
    assert tab.player.playbackState() == tab.player.PlaybackState.StoppedState
    capped = VerifiedPrefixDevice(source, verified_bytes)
    assert not capped.seek(verified_bytes + 1)
    assert capped.readAll().data() == source.read_bytes()[:verified_bytes]
    assert capped.atEnd()
    assert capped.read(100).isEmpty()
    capped.close()


def test_media_profile_editor_keeps_the_player_and_media_workspace(qtbot, tmp_path, request):
    from PySide6.QtCore import QCoreApplication, QEvent, Qt, QTimer
    from PySide6.QtWidgets import QApplication, QDialogButtonBox
    from shiboken6 import isValid

    from torrentlinker.web.app import create_app

    config = tmp_path / "config"
    config.mkdir()
    settings = Settings()
    settings.save(config / "settings.json")
    app = create_app(config, password="test-password-long", monitor_verifications=False)
    window = MainWindow(settings, config / "settings.json", Store(config / "state.db"))
    windows = [window]

    def cleanup():
        for widget in windows:
            if isValid(widget):
                widget.close()
                widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    request.addfinalizer(cleanup)
    window.media_tab.get_service = lambda: app.state.assistant
    window.show()
    window.navigation.setCurrentRow(window.tabs.indexOf(window.media_tab))
    tab = window.media_tab
    qtbot.waitUntil(lambda: tab.results.isEnabled())
    tab.command("shuffle", shuffle=True)
    tab.command("repeat", repeat="all")
    player = tab.player

    def save_editor():
        dialog = QApplication.activeModalWidget()
        buttons = dialog.findChild(QDialogButtonBox)
        qtbot.mouseClick(buttons.button(QDialogButtonBox.Save), Qt.LeftButton)

    QTimer.singleShot(0, save_editor)
    window.open_client_profiles()
    replacement = QApplication.instance().torrentlinker_window
    windows.append(replacement)
    assert replacement.tabs.currentWidget() is tab
    assert replacement.media_tab.player is player
    assert tab.heartbeat.isActive()
    assert tab.shuffle.isChecked()
    assert tab.repeat.currentData() == "all"
    cleanup()
