"""Same-process native Library rescan coverage for the Windows freeze report."""

import threading

from PySide6.QtCore import QTimer

from tests.fake_qbit import FakeQbit
from tests.test_library_folders import window_for
from torrentlinker.domain import LibraryFolder
from torrentlinker.gui import tasks
from torrentlinker.gui.main_window import MainWindow


def test_ten_rescans_keep_ui_responsive_and_preserve_files(qtbot, tmp_path, monkeypatch):
    window, _ = window_for(qtbot, tmp_path, monkeypatch)
    folder = tmp_path / "Library"
    folder.mkdir()
    expected = {folder / f"Book-{index}.epub": b"book" * (index + 1) for index in range(25)}
    for path, contents in expected.items():
        path.write_bytes(contents)
    window.settings.library_folders = [LibraryFolder(folder)]
    client = FakeQbit()
    released = threading.Event()
    reads = []
    main_thread = threading.get_ident()

    def torrents(**kwargs):
        reads.append(threading.get_ident())
        assert released.wait(2), "GUI heartbeat did not release the simulated client read"
        return []

    client.torrents = torrents
    monkeypatch.setattr(window, "qbit", lambda: client)
    beats = []
    timer = QTimer(window)
    timer.setInterval(10)

    def heartbeat():
        beats.append(True)
        released.set()

    timer.timeout.connect(heartbeat)
    timer.start()
    try:
        for iteration in range(10):
            if iteration % 2:
                changed = folder / "Book-0.epub"
                expected[changed] = b"updated" * (iteration + 1)
                changed.write_bytes(expected[changed])
            released.clear()
            before = len(beats)
            MainWindow.scan(window, refresh=bool(iteration % 2))
            assert not window.scan_action.isEnabled()
            qtbot.waitUntil(lambda: window.scan_action.isEnabled(), timeout=5000)
            qtbot.waitUntil(lambda: not tasks._alive, timeout=5000)
            assert len(beats) > before
            assert window.rescan_action.isEnabled()
            assert window.add_folder_action.isEnabled()
            assert {entry.item.path: entry.item.size for entry in window.library_model.entries} == {
                path: len(data) for path, data in expected.items()
            }
        assert len(reads) == 10
        assert all(thread != main_thread for thread in reads)
        assert {path: path.read_bytes() for path in expected} == expected
        window.close()
        assert not tasks._alive
    finally:
        released.set()
        timer.stop()
