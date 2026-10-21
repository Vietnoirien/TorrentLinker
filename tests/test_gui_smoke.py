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


def test_a_typed_folder_path_is_added_to_the_library_folders(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from torrentlinker.gui.settings_dialog import SettingsDialog

    dialog = SettingsDialog(Settings())
    qtbot.addWidget(dialog)
    dialog.typed_folder.setText(str(tmp_path))
    dialog._add_typed_folder()

    assert [f.path for f in dialog._read_folders()] == [tmp_path]


def test_zen_profile_entered_in_settings_comes_back(qtbot) -> None:  # type: ignore[no-untyped-def]
    from torrentlinker.gui.settings_dialog import SettingsDialog
    from torrentlinker.zen import ZenClass, ZenProfile

    s = Settings()
    s.zen = ZenProfile(ZenClass.SWARM_KEEPER, 0.02, 20, 300)
    dialog = SettingsDialog(s)
    qtbot.addWidget(dialog)

    assert dialog._read_zen() == s.zen
    dialog.zen_class.setCurrentIndex(2)
    assert dialog._read_zen().zen_class is ZenClass.REUPLOADER


def test_main_window_opens_on_the_zen_tab_and_shows_the_seeding_view(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from torrentlinker.domain import Torrent
    from torrentlinker.seeding import seeding
    from torrentlinker.zen import GB, ZenProfile

    window = MainWindow(Settings(), tmp_path / "settings.json", Store(tmp_path / "s.db"))
    qtbot.addWidget(window)
    t = Torrent(
        "h",
        "Film",
        tmp_path,
        tracker="https://c411.org/a",
        swarm_seeders=100,
        seeding_time=90 * 86400,
        size=4 * GB,
        state="uploading",
    )

    window.zen_tab.seeding_view.show_seeding(seeding(ZenProfile(), [t], "https://c411.org/api"))

    assert window.tabs.currentWidget() is window.zen_tab
    assert window.tabs.tabText(1) == "Library"
    assert window.zen_tab.seeding_view.table.rowCount() == 1
    assert "≈" in window.zen_tab.seeding_view.table.item(0, 4).text()  # type: ignore[union-attr]
