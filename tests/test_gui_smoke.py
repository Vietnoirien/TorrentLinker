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


def test_library_shows_zen_per_day_for_orphans_with_a_match_and_sorts_it(
    qtbot, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtCore import Qt

    from torrentlinker.domain import ItemState, LibraryFolder, LocalItem
    from torrentlinker.gui.library_model import LibraryModel
    from torrentlinker.indexer import Candidate
    from torrentlinker.library import LibraryEntry
    from torrentlinker.matching import Match
    from torrentlinker.review import CheckedCandidate
    from torrentlinker.zen import GB

    window = MainWindow(Settings(), tmp_path / "settings.json", Store(tmp_path / "s.db"))
    qtbot.addWidget(window)
    folder = LibraryFolder(tmp_path)
    entries = [
        LibraryEntry(folder, LocalItem(tmp_path / n), ItemState.ORPHAN) for n in ("a", "b", "c")
    ]
    window.library_model.set_entries(entries)
    full = Match({"x": "x"}, [], [], 1.0)
    window.review.remember(entries[0], [CheckedCandidate(Candidate("s", GB, "u", 3), match=full)])
    window.review.remember(
        entries[1], [CheckedCandidate(Candidate("b", 40 * GB, "u", 3), match=full)]
    )
    window.review.remember(entries[2], [CheckedCandidate(Candidate("n", GB, "u", 3))])

    col = LibraryModel.ZEN_COLUMN
    texts = [window.library_model.index(r, col).data() for r in range(3)]
    assert texts[0].startswith("≈") and texts[1].startswith("≈") and texts[2] == ""
    window.library_proxy.sort(col, Qt.SortOrder.DescendingOrder)
    top = window.library_proxy.index(0, 0).data(Qt.ItemDataRole.UserRole)
    assert top is entries[1]


def test_band_shows_the_catalogue_age(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    import time

    from torrentlinker.store import CatalogueRow, CrawlState

    store = Store(tmp_path / "s.db")
    store.save_catalogue([CatalogueRow("aa" * 20, "Book", 1, 1, 7000, "u", "d", 0)])
    store.save_crawl_state(CrawlState(7000, updated_at=time.time() - 7200))

    window = MainWindow(Settings(), tmp_path / "settings.json", store)
    qtbot.addWidget(window)

    assert "1 torrents, 2 h old" in window.band.catalogue.text()


def test_catalogue_update_runs_off_the_gui_thread_and_reports_progress(
    qtbot, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    from tests.fake_torznab import FakeTorznab
    from tests.test_indexer import FakeClock
    from torrentlinker.catalogue import update_categories
    from torrentlinker.indexer import Indexer

    fake, clock = FakeTorznab(), FakeClock()
    fake.add(7000, 150)
    indexer = Indexer(
        "https://c411.example/api/torznab",
        "K",
        http=fake.client(),
        clock=clock.time,
        sleep=clock.sleep,
    )
    store = Store(tmp_path / "s.db")
    window = MainWindow(Settings(), tmp_path / "settings.json", store)
    qtbot.addWidget(window)

    with qtbot.waitSignal(
        window.band.catalogue_changed, timeout=5000, check_params_cb=lambda t: "old" in t
    ):
        window._run_catalogue(
            lambda stop, progress: update_categories(
                indexer, store, [7000], stop=stop, progress=progress
            )
        )

    assert store.catalogue_size() == 150


def test_whole_catalogue_fetch_can_be_paused_and_offers_to_resume(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from tests.fake_torznab import FakeTorznab
    from tests.test_indexer import FakeClock
    from torrentlinker.credentials import set_secret
    from torrentlinker.downloads import IndexerCategory
    from torrentlinker.gui.settings_dialog import INDEXER_API_KEY
    from torrentlinker.indexer import Indexer

    fake, clock = FakeTorznab(), FakeClock()
    fake.add(2000, 1000)
    s = Settings()
    s.indexer.url = "https://c411.example/api/torznab"
    s.indexer_categories = {2000: IndexerCategory("Films")}
    set_secret(INDEXER_API_KEY, "K")
    store = Store(tmp_path / "s.db")
    window = MainWindow(s, tmp_path / "settings.json", store)
    qtbot.addWidget(window)
    window._indexer = Indexer(
        s.indexer.url, "K", http=fake.client(), clock=clock.time, sleep=clock.sleep
    )
    box = window.zen_tab.catalogue
    window._catalogue_progress = lambda p: window.pause_catalogue()  # type: ignore[method-assign]

    with qtbot.waitSignal(
        window.band.catalogue_changed, timeout=5000, check_params_cb=lambda t: "old" in t
    ):
        box.fetch_button.click()

    assert 0 < store.catalogue_size() < 1000
    assert store.crawl_paused()
    assert "Resume" in box.fetch_button.text()


def test_plan_view_shows_zen_added_size_and_payback_and_the_band_follows(
    qtbot, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    from torrentlinker.plan import Plan, PlanCandidate, PlanItem
    from torrentlinker.zen import GB

    window = MainWindow(Settings(), tmp_path / "settings.json", Store(tmp_path / "s.db"))
    qtbot.addWidget(window)
    c = PlanCandidate("aa" * 20, "Film", 8 * GB, 4, 2000, tmp_path, 1)
    window._plan_made(Plan([PlanItem(c, 0.4)], 0.4))

    summary = window.zen_tab.plan_view.summary.text()
    assert "≈ +0.40 Zen/day" in summary and "8.0 Go" in summary and "20 days" in summary
    assert "+0.40" in window.band.plan.text()
    assert window.zen_tab.plan_view.table.rowCount() == 1


def test_plan_maker_plans_catalogue_torrents_into_download_folders(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from tests.fake_qbit import FakeQbit
    from torrentlinker.downloads import DownloadFolders, IndexerCategory
    from torrentlinker.store import CatalogueRow

    s = Settings()
    s.indexer_categories = {2000: IndexerCategory("Films"), 7000: IndexerCategory("Ebook")}
    s.download_folders = DownloadFolders({2000: str(tmp_path / "films")})
    store = Store(tmp_path / "s.db")
    store.save_catalogue(
        [
            CatalogueRow("aa" * 20, "Film", 1_000_000, 5, 2000, "u", "d", 0),
            CatalogueRow("bb" * 20, "Book", 1_000_000, 5, 7000, "u", "d", 0),
        ]
    )
    window = MainWindow(s, tmp_path / "settings.json", store)
    qtbot.addWidget(window)
    window.qbit = lambda: FakeQbit()  # type: ignore[assignment,method-assign,return-value]

    plan = window.plan_maker()()

    assert [i.candidate.title for i in plan.items] == ["Film"]
    assert plan.items[0].candidate.folder == tmp_path / "films"
