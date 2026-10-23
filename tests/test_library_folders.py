from pathlib import Path

import pytest
from PySide6.QtWidgets import QDialog, QMessageBox

from torrentlinker.config import Settings
from torrentlinker.domain import ContentKind, LibraryFolder
from torrentlinker.gui import main_window
from torrentlinker.gui.library_folder_dialog import LibraryFolderDialog
from torrentlinker.store import Store


def window_for(qtbot, tmp_path, monkeypatch):
    window = main_window.MainWindow(
        Settings(), tmp_path / "settings.json", Store(tmp_path / "s.db")
    )
    qtbot.addWidget(window)
    scans = []
    monkeypatch.setattr(window, "scan", lambda: scans.append(True))
    return window, scans


def test_library_add_folder_saves_kind_depth_and_shows_it(qtbot, tmp_path, monkeypatch):
    window, scans = window_for(qtbot, tmp_path, monkeypatch)
    folder = tmp_path / "films"
    folder.mkdir()
    monkeypatch.setattr(main_window, "choose_directory", lambda *args: str(folder))

    def configure(dialog):
        dialog.kind.setCurrentIndex(dialog.kind.findData(ContentKind.MOVIE))
        dialog.scan_depth.setValue(2)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(LibraryFolderDialog, "exec", configure)
    window.library_search.setText("old filter")
    window.add_folder_action.trigger()
    expected = [LibraryFolder(folder, 2, ContentKind.MOVIE)]
    assert window.settings.library_folders == expected
    assert Settings.load(window.settings_path).library_folders == expected
    assert scans == [True]
    assert window.folder_filter.currentData() == folder
    assert window.library_search.text() == ""

    messages = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: messages.append(args[2]))
    monkeypatch.setattr(main_window, "choose_directory", lambda *args: str(folder / "."))
    window.add_folder_action.trigger()
    assert window.settings.library_folders == expected
    assert scans == [True]
    assert messages == ["This folder is already in the Library."]


@pytest.mark.parametrize("cancel_picker", [True, False])
def test_cancel_add_folder_does_not_save_or_scan(qtbot, tmp_path, monkeypatch, cancel_picker):
    window, scans = window_for(qtbot, tmp_path, monkeypatch)
    monkeypatch.setattr(
        main_window, "choose_directory", lambda *args: "" if cancel_picker else str(tmp_path)
    )
    monkeypatch.setattr(LibraryFolderDialog, "exec", lambda self: QDialog.DialogCode.Rejected)
    window.add_folder_action.trigger()
    assert window.settings.library_folders == []
    assert not window.settings_path.exists()
    assert not scans


def test_folder_save_failure_keeps_current_settings(qtbot, tmp_path, monkeypatch):
    window, scans = window_for(qtbot, tmp_path, monkeypatch)
    monkeypatch.setattr(main_window, "choose_directory", lambda *args: str(tmp_path))
    monkeypatch.setattr(LibraryFolderDialog, "exec", lambda self: QDialog.DialogCode.Accepted)

    def fail_save(self, path: Path):
        raise OSError("disk full")

    messages = []
    monkeypatch.setattr(Settings, "save", fail_save)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: messages.append(args[2]))
    window.add_folder_action.trigger()
    assert window.settings.library_folders == []
    assert not scans
    assert "disk full" in messages[0]
