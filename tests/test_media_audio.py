"""Real audio cleanup must not deadlock native widget construction."""

import os
import subprocess
import sys
import textwrap


def test_audio_cleanup_keeps_widget_construction_responsive(tmp_path):
    # A separate process is essential: this regression blocks the GUI while holding
    # the GIL, so neither qtbot's timeout nor a Python watchdog thread can recover.
    script = textwrap.dedent(
        """
        import faulthandler
        import gc
        from pathlib import Path
        import sys
        import time
        import wave

        from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop, QTimer, QUrl
        from PySide6.QtMultimedia import QMediaPlayer
        from PySide6.QtWidgets import QApplication, QPushButton, QWidget
        from shiboken6 import isValid
        from torrentlinker.gui.media_audio import create_audio_output

        faulthandler.dump_traceback_later(15)
        # Widen the real cleanup/construction race without changing app behavior.
        sys.setswitchinterval(0.05)
        app = QApplication([])
        app.setStyleSheet('QWidget { font-size: 13px; }')
        path = Path(sys.argv[1]) / 'silence.wav'
        with wave.open(str(path), 'wb') as track:
            track.setparams((1, 2, 22050, 0, 'NONE', 'not compressed'))
            track.writeframes(b'\\0\\0' * 22050 * 5)

        def wait(ms):
            loop = QEventLoop()
            QTimer.singleShot(ms, loop.quit)
            loop.exec()

        for iteration in range(80):
            print('cycle', iteration, flush=True)
            parent = QWidget()
            player = QMediaPlayer(parent)
            audio = create_audio_output(parent)
            children = audio.children()
            assert audio.parent() is parent
            audio.setVolume(0.25)
            audio.setMuted(True)
            gc.collect()
            assert audio.volume() == 0.25 and audio.isMuted()
            player.setAudioOutput(audio)
            player.setSource(QUrl.fromLocalFile(str(path)))
            player.play()
            deadline = time.monotonic() + 5
            while player.position() == 0 and time.monotonic() < deadline:
                wait(10)
            assert player.position() > 0, player.errorString()
            player.stop()
            for _ in range(200):
                QPushButton('Stopping playback', parent)
            assert player.playbackState() == QMediaPlayer.PlaybackState.StoppedState
            parent.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            assert not isValid(audio)
            assert all(not isValid(child) for child in children)
            wait(1)
        faulthandler.cancel_dump_traceback_later()
        print('Playback and cleanup completed', flush=True)
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Playback and cleanup completed" in result.stdout
