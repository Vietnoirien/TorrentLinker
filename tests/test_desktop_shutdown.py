"""Desktop exit waits for workers before Qt destroys their signal objects."""

import os
import subprocess
import sys
import textwrap

import pytest


@pytest.mark.parametrize("mode", ["success", "failure", "progress", "smoke-failure", "dialog"])
def test_application_exit_finishes_workers_before_returning(tmp_path, mode):
    script = textwrap.dedent(
        """
        import sys
        import threading
        from pathlib import Path
        from PySide6.QtWidgets import QMessageBox, QWidget
        from PySide6.QtCore import QThreadPool
        from torrentlinker import app
        from torrentlinker.gui.tasks import run_in_background, run_with_progress

        mode, directory = sys.argv[1], Path(sys.argv[2])
        finished = threading.Event()
        started = threading.Event()
        delivered = threading.Event()
        progress = []
        queued = threading.Event()
        followup = threading.Event()
        QThreadPool.globalInstance().setMaxThreadCount(1)
        def work(report=None):
            started.set()
            threading.Event().wait(0.8)
            finished.set()
            if report:
                report('saved progress')
            if mode == 'failure':
                raise ValueError('controlled failure')
            return 'finished'

        def done(result):
            assert threading.current_thread() is threading.main_thread()
            if mode == 'dialog':
                assert QMessageBox.warning(None, 'Finished', 'Closing the application') == (
                    QMessageBox.StandardButton.NoButton
                )
            delivered.set()
            run_in_background(followup.set, lambda result: None, lambda error: None)
            run_with_progress(lambda report: followup.set(), lambda value: None,
                              lambda result: None, lambda error: None)

        def smoke():
            if mode == 'progress':
                run_with_progress(work, progress.append, done, done)
            else:
                run_in_background(work, done, done)
            assert started.wait(1)
            run_in_background(queued.set, lambda result: None, lambda error: None)
            if mode == 'smoke-failure':
                raise ValueError('controlled smoke failure')

        app.MainWindow = lambda *args: QWidget()
        app.data_dir = lambda: directory
        app.smoke_checks = smoke
        sys.argv = ['torrentlinker', '--smoke-test']
        original_hook = sys.excepthook
        result = app.main()
        sys.excepthook = original_hook
        assert result == (1 if mode == 'smoke-failure' else 0)
        assert finished.is_set(), 'Application returned before its desktop worker finished'
        assert delivered.is_set(), 'Completed work lost its GUI callback during exit'
        assert not queued.is_set(), 'Queued work started after application exit'
        assert not followup.is_set(), 'Completion callback started new work during exit'
        assert progress == (['saved progress'] if mode == 'progress' else [])
        print('Worker finished before application exit', flush=True)
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script, mode, str(tmp_path)],
        env={
            **os.environ,
            "QT_QPA_PLATFORM": "offscreen",
            "XDG_DATA_HOME": str(tmp_path / "data"),
            "XDG_CONFIG_HOME": str(tmp_path / "config"),
            "XDG_CACHE_HOME": str(tmp_path / "cache"),
        },
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Worker finished before application exit" in result.stdout
