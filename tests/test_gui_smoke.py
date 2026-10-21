from pathlib import Path

from torrentlinker.config import Settings
from torrentlinker.gui.main_window import MainWindow
from torrentlinker.store import Store


def test_main_window_opens(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    window = MainWindow(Settings(), tmp_path / "settings.json", Store(tmp_path / "s.db"))
    qtbot.addWidget(window)
    window.show()
    assert window.isVisible()


def test_settings_open_on_the_connections_tab_with_hidden_keys(qtbot) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QLineEdit

    from torrentlinker.gui.settings_dialog import SettingsDialog

    dialog = SettingsDialog(Settings())
    qtbot.addWidget(dialog)

    assert dialog.tabs.currentIndex() == 0
    assert dialog.indexer_key.echoMode() == QLineEdit.EchoMode.Password
    assert dialog.tmdb_key.echoMode() == QLineEdit.EchoMode.Password


def test_content_kind_chosen_in_settings_comes_back_as_a_content_kind(qtbot) -> None:  # type: ignore[no-untyped-def]
    from torrentlinker.domain import ContentKind, LibraryFolder
    from torrentlinker.gui.settings_dialog import SettingsDialog

    s = Settings()
    s.library_folders = [LibraryFolder(Path("/windocs/STL"), 1, ContentKind.MODEL_3D)]
    dialog = SettingsDialog(s)
    qtbot.addWidget(dialog)

    [folder] = dialog._read_folders()

    assert folder.kind is ContentKind.MODEL_3D


def test_library_state_filter_keeps_only_the_chosen_state(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from torrentlinker.domain import ItemState, LibraryFolder, LocalItem
    from torrentlinker.library import LibraryEntry

    window = MainWindow(Settings(), tmp_path / "settings.json", Store(tmp_path / "s.db"))
    qtbot.addWidget(window)
    folder = LibraryFolder(tmp_path)
    window.library_model.set_entries(
        [
            LibraryEntry(folder, LocalItem(tmp_path / "a"), ItemState.ORPHAN),
            LibraryEntry(folder, LocalItem(tmp_path / "b"), ItemState.SEEDED),
        ]
    )

    window.state_filter.setCurrentIndex(window.state_filter.findText("Orphan"))

    assert window.library_proxy.rowCount() == 1
