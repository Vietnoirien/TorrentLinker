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


def test_download_folders_tab_flags_categories_left_without_a_folder(qtbot) -> None:  # type: ignore[no-untyped-def]
    from torrentlinker.downloads import DownloadFolders
    from torrentlinker.gui.settings_dialog import COL_FOLDER, COL_RESOLVED, SettingsDialog
    from torrentlinker.indexer import Caps

    dialog = SettingsDialog(Settings())
    qtbot.addWidget(dialog)
    dialog._set_categories(Caps({2000: "Films", 2030: "VO", 7000: "Ebook"}, {}, {2030: 2000}))
    dialog.download_table.item(0, COL_FOLDER).setText("/dl/films")  # type: ignore[union-attr]

    assert dialog._read_download_folders() == DownloadFolders({2000: "/dl/films"})
    used = [dialog.download_table.item(r, COL_RESOLVED).text() for r in range(3)]  # type: ignore[union-attr]
    assert used[:2] == ["/dl/films", "/dl/films"]
    assert "excluded" in used[2]


def test_zen_band_shows_the_balance_and_explains_a_key_without_profile_scope(qtbot) -> None:  # type: ignore[no-untyped-def]
    from torrentlinker.gui.zen_view import ZenBand
    from torrentlinker.profile import ProfileError, ProfileProblem, UserProfile
    from torrentlinker.zen import ZenClass

    band = ZenBand()
    qtbot.addWidget(band)
    band.show_profile(
        UserProfile("v", "tanker", ZenClass.TANKER, 0.02, 12.5, False, "insufficient_balance")
    )
    assert "12.5" in band.balance.text()
    assert "not enough Zen" in band.message.text()

    band.show_profile_error(ProfileError(ProfileProblem.MISSING_SCOPE))
    assert "Profil (lecture)" in band.message.text()


def test_profile_read_at_startup_fills_the_zen_profile(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from torrentlinker.profile import UserProfile
    from torrentlinker.zen import ZenClass

    window = MainWindow(Settings(), tmp_path / "settings.json", Store(tmp_path / "s.db"))
    qtbot.addWidget(window)
    refreshed = []
    window.zen_tab.seeding_view.refresh = lambda: refreshed.append(True)  # type: ignore[method-assign]
    window._profile_read(
        UserProfile("v", "swarm-keeper", ZenClass.SWARM_KEEPER, 0.04, 3, True, None)
    )

    assert window.settings.zen.zen_class is ZenClass.SWARM_KEEPER
    assert window.settings.zen.tree_bonus == 0.04
    assert Settings.load(tmp_path / "settings.json").zen == window.settings.zen
    assert refreshed  # the Seeding view is estimated again with the new Class


def test_class_comparison_highlights_the_current_class_and_labels_reuploader_rough(qtbot) -> None:  # type: ignore[no-untyped-def]
    from torrentlinker.gui.zen_view import ClassComparison
    from torrentlinker.zen import ZenClass, ZenProfile

    widget = ClassComparison(lambda: ZenProfile(ZenClass.SWARM_KEEPER), uploads=10)
    qtbot.addWidget(widget)

    assert "<b>" in widget.labels[ZenClass.SWARM_KEEPER].text()
    assert "<b>" not in widget.labels[ZenClass.TANKER].text()
    assert "rough" in widget.labels[ZenClass.REUPLOADER].text()
    assert "4.30" in widget.labels[ZenClass.REUPLOADER].text()
