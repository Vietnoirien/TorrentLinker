from pathlib import Path

import pytest

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


def test_periodic_qbit_refresh_updates_estimates_after_a_tracker_response(
    qtbot, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    from tests.fake_qbit import FakeQbit
    from torrentlinker.domain import Torrent
    from torrentlinker.plan import Plan
    from torrentlinker.store import CatalogueRow
    from torrentlinker.zen import GB, ZenClass, ZenProfile

    settings = Settings(zen=ZenProfile(ZenClass.SWARM_KEEPER))
    store = Store(tmp_path / "s.db")
    row = CatalogueRow("a" * 40, "Book", 4 * GB, 100, 7000, "u", "d", 123, "zen-lab")
    store.save_catalogue([row])
    t = Torrent(
        row.infohash,
        "Book",
        tmp_path,
        state="uploading",
        tracker="https://tracker.c411.org/announce",
        swarm_seeders=-1,
        size=4 * GB,
    )
    qbit = FakeQbit({row.infohash: t})
    window = MainWindow(settings, tmp_path / "settings.json", store)
    qtbot.addWidget(window)
    window.qbit = lambda: qbit  # type: ignore[assignment,method-assign,return-value]
    view = window.zen_tab.seeding_view
    view.show_seeding(window.seeding_loader()())
    before = view.seeding.day.total
    assert view.table.item(0, 2).text() == "–"
    assert store.catalogue()[0].seeders == 100

    window.zen_tab.plan_view.show_plan(Plan())
    qbit._set(row.infohash, swarm_seeders=5)
    with qtbot.waitSignal(view.updated, timeout=5000):
        window.seeding_timer.timeout.emit()

    assert view.table.item(0, 2).text() == "5"
    assert view.seeding.day.total > before
    cached = store.catalogue()[0]
    assert cached.seeders == 4  # the current user is already one of the five seeders
    assert cached.source == "zen-lab" and cached.seen_at == 123
    assert window.seeding_timer.interval() == 30_000


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
    serve = fake.handler

    def pause_after_first_page(request):  # type: ignore[no-untyped-def]
        assert window.catalogue_runner is not None
        window.catalogue_runner.stop()  # what the Pause button does; only sets a flag
        return serve(request)

    fake.handler = pause_after_first_page  # type: ignore[method-assign]
    window._indexer = Indexer(
        s.indexer.url, "K", http=fake.client(), clock=clock.time, sleep=clock.sleep
    )
    box = window.zen_tab.catalogue

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


def test_the_plan_estimates_sending_and_downloading_times_from_a_speed_test(
    qtbot,  # type: ignore[no-untyped-def]
    tmp_path: Path,
    monkeypatch,  # type: ignore[no-untyped-def]
) -> None:
    from torrentlinker.gui import main_window
    from torrentlinker.plan import Plan, PlanCandidate, PlanItem
    from torrentlinker.zen import GB

    window = MainWindow(Settings(), tmp_path / "settings.json", Store(tmp_path / "s.db"))
    qtbot.addWidget(window)
    view = window.zen_tab.plan_view
    c = PlanCandidate("aa" * 20, "Book", 360 * GB // 1000, 4, 7000, tmp_path, 1)
    window._plan_made(Plan([PlanItem(c, 0.01)] * 1000, 10))

    assert "Sending to qBittorrent: ≈ 1 h 08" in view.times.text()  # 1000 × 4.1 s
    assert "test your speed" in view.times.text()

    monkeypatch.setattr(main_window, "measure_download_speed", lambda: 100_000_000.0)
    view.speed_button.click()
    qtbot.waitUntil(lambda: window.settings.download_speed is not None, timeout=5000)

    assert "Downloading the data: ≈ 1 h 00 at best" in view.times.text()  # 360 GB at 100 MB/s
    assert "800 Mbit/s" in view.times.text()
    assert Settings.load(tmp_path / "settings.json").download_speed == 100_000_000.0


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


def test_sending_the_plan_adds_its_torrents_and_reports(qtbot, tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QMessageBox

    from tests.fake_qbit import FakeQbit
    from tests.torrents import make_torrent
    from torrentlinker.plan import Plan, PlanCandidate, PlanItem
    from torrentlinker.send import ZEN_TAG
    from torrentlinker.store import CatalogueRow
    from torrentlinker.torrent_meta import read_torrent

    src = tmp_path / "src" / "Film"
    src.mkdir(parents=True)
    (src / "f.mkv").write_bytes(b"x" * 1000)
    data = make_torrent(src)
    meta = read_torrent(data)
    row = CatalogueRow(meta.infohash, "Film", 1000, 3, 2000, "https://c411.example/dl/1", "", 0)
    plan = Plan(
        [
            PlanItem(
                PlanCandidate(meta.infohash, "Film", 1000, 3, 2000, tmp_path / "dl", 1, source=row),
                0.1,
            )
        ],
        0.1,
    )

    class StubIndexer:
        url, api_key = Settings().indexer.url, ""
        fetched: list[str] = []

        def fetch_torrent(self, c, retry=True):  # type: ignore[no-untyped-def]
            self.fetched.append(c.download_url)
            return data

        def next_request_in(self) -> float:
            return 0

        def unredact(self, text: str) -> str:
            return text

    qbit, stub = FakeQbit(), StubIndexer()
    window = MainWindow(Settings(), tmp_path / "settings.json", Store(tmp_path / "s.db"))
    qtbot.addWidget(window)
    window.qbit = lambda: qbit  # type: ignore[assignment,method-assign,return-value]
    window._indexer = stub  # type: ignore[assignment]
    window.zen_tab.seeding_view.refresh = lambda: None  # type: ignore[method-assign]
    shown: list[str] = []
    monkeypatch.setattr(QMessageBox, "exec", lambda box: shown.append(box.text()))
    window.zen_tab.plan_view.show_plan(plan)

    window.send_plan(plan)
    assert window.zen_tab.plan_view.send_progress.isVisibleTo(window)
    assert window.zen_tab.plan_view.stop_send_button.isVisibleTo(window)
    qtbot.waitUntil(lambda: bool(shown), timeout=5000)

    assert stub.fetched == ["https://c411.example/dl/1"], shown
    [t] = qbit.torrents()
    assert ZEN_TAG in t.tags and t.save_path == tmp_path / "dl"
    assert "1 torrents added" in shown[0]
    assert not window.zen_tab.plan_view.send_progress.isVisibleTo(window)
    assert window.send_runner is None


def test_sending_shows_progress_and_the_c411_limit_and_can_be_stopped(
    qtbot,  # type: ignore[no-untyped-def]
    tmp_path: Path,
    monkeypatch,  # type: ignore[no-untyped-def]
) -> None:
    from PySide6.QtWidgets import QMessageBox

    from tests.fake_qbit import FakeQbit
    from torrentlinker.indexer import RateLimited
    from torrentlinker.plan import Plan, PlanCandidate, PlanItem
    from torrentlinker.store import CatalogueRow

    rows = [
        CatalogueRow(f"{i:040x}", f"Book {i}", 1000, 3, 7020, f"https://c411.example/{i}", "", 0)
        for i in range(3)
    ]
    plan = Plan(
        [
            PlanItem(PlanCandidate(r.infohash, r.title, 1000, 3, 7020, tmp_path, 1, source=r), 0.1)
            for r in rows
        ],
        0.3,
    )

    class LimitedIndexer:
        url, api_key = Settings().indexer.url, ""

        def fetch_torrent(self, c, retry=True):  # type: ignore[no-untyped-def]
            raise RateLimited(30)

        def unredact(self, text: str) -> str:
            return text

    window = MainWindow(Settings(), tmp_path / "settings.json", Store(tmp_path / "s.db"))
    qtbot.addWidget(window)
    window.qbit = lambda: FakeQbit()  # type: ignore[assignment,method-assign,return-value]
    window._indexer = LimitedIndexer()  # type: ignore[assignment]
    window.zen_tab.seeding_view.refresh = lambda: None  # type: ignore[method-assign]
    shown: list[str] = []
    monkeypatch.setattr(QMessageBox, "exec", lambda box: shown.append(box.text()))
    view = window.zen_tab.plan_view
    view.show_plan(plan)

    window.send_plan(plan)
    qtbot.waitUntil(lambda: "limiting downloads" in view.summary.text(), timeout=5000)
    assert "0 of 3" in view.summary.text()
    assert "3" in window.band.plan.text() and "waiting" in window.band.plan.text()

    view.stop_send_button.click()
    qtbot.waitUntil(lambda: bool(shown), timeout=5000)

    assert "Stopped after 0 of 3" in shown[0]
    assert window.send_runner is None
    assert view.make_button.isEnabled()


def test_refreshing_a_long_seeding_list_again_is_quick(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    import time

    from PySide6.QtWidgets import QApplication

    from torrentlinker.domain import Torrent
    from torrentlinker.gui.zen_view import SeedingView
    from torrentlinker.seeding import Seeding, SeedingRow
    from torrentlinker.zen import ZenDay

    rows = [
        SeedingRow(Torrent(f"{i:040x}", f"Book.{i}.epub", tmp_path, {"b.epub": 1000 + i}), i / 1e4)
        for i in range(1300)
    ]
    view = SeedingView(lambda: lambda: Seeding([], ZenDay(), []))
    qtbot.addWidget(view)
    view.resize(900, 600)
    view.show()
    qtbot.waitExposed(view)
    view.show_seeding(Seeding(rows, ZenDay([r.zen or 0 for r in rows]), []))
    QApplication.processEvents()

    started = time.monotonic()
    view.show_seeding(Seeding(rows, ZenDay([r.zen or 0 for r in rows]), []))

    assert time.monotonic() - started < 5  # replacing filled cells took over a minute
    assert view.table.rowCount() == 1300


def test_plan_lists_reseeds_first_and_sends_them_through_verification(
    qtbot, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    from tests.fake_qbit import FakeQbit
    from tests.torrents import make_torrent
    from torrentlinker.domain import ItemState, LibraryFolder, LocalItem
    from torrentlinker.indexer import Candidate
    from torrentlinker.library import LibraryEntry
    from torrentlinker.matching import match
    from torrentlinker.reseed import VERIFYING
    from torrentlinker.review import CheckedCandidate
    from torrentlinker.torrent_meta import read_torrent

    lib = tmp_path / "lib"
    lib.mkdir()
    f = lib / "book.epub"
    f.write_bytes(b"b" * 3000)
    item = LocalItem(f, {f.name: 3000})
    meta = read_torrent(make_torrent(f))
    m = match(item, meta.files)
    entry = LibraryEntry(LibraryFolder(lib), item, ItemState.ORPHAN)
    qbit = FakeQbit()
    window = MainWindow(Settings(), tmp_path / "settings.json", Store(tmp_path / "s.db"))
    qtbot.addWidget(window)
    window.qbit = lambda: qbit  # type: ignore[assignment,method-assign,return-value]
    window.library_model.set_entries([entry])
    window.review.remember(
        entry, [CheckedCandidate(Candidate("Book", 3000, "u", 4, meta.infohash), meta, m, m)]
    )

    plan = window.plan_maker()()
    window.zen_tab.plan_view.show_plan(plan)

    [row] = plan.items
    assert row.candidate.reseed and plan.download_size == 0 and plan.zen_added > 0
    assert window.zen_tab.plan_view.table.item(0, 1).text() == "Reseed (0 Go)"  # type: ignore[union-attr]
    window.plan_reseeder()(row.candidate)
    [t] = qbit.torrents()
    assert VERIFYING in t.tags and t.save_path == lib
    assert qbit.rechecked == [t.hash]


def test_the_plan_offers_categories_with_a_download_folder_and_remembers_the_choice(
    qtbot,
    tmp_path: Path,  # type: ignore[no-untyped-def]
) -> None:
    from torrentlinker.downloads import DownloadFolders, IndexerCategory

    s = Settings()
    s.indexer_categories = {
        2000: IndexerCategory("Films"),
        2030: IndexerCategory("Films étrangers", parent=2000),
        7000: IndexerCategory("Ebook"),
    }
    s.download_folders = DownloadFolders({2000: str(tmp_path / "films")})
    window = MainWindow(s, tmp_path / "settings.json", Store(tmp_path / "s.db"))
    qtbot.addWidget(window)
    view = window.zen_tab.plan_view

    assert [cid for cid, _name, _sub in view.category_options] == [2000, 2030]

    view._toggle(2030, True)

    assert Settings.load(tmp_path / "settings.json").plan_categories == [2030]


def test_a_catalogue_update_shows_its_progress_and_its_result(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from torrentlinker.catalogue import CrawlProgress
    from torrentlinker.downloads import IndexerCategory

    s = Settings()
    s.indexer_categories = {2030: IndexerCategory("Film", 2000)}
    window = MainWindow(s, tmp_path / "settings.json", Store(tmp_path / "s.db"))
    qtbot.addWidget(window)
    window._catalogue_added = {}

    window._catalogue_progress(CrawlProgress(2030, pages=3, added=250, offset=300))
    assert "Film" in window.statusBar().currentMessage()
    assert "Film" in window.zen_tab.catalogue.status.text()

    window._catalogue_finished(stopped=False)
    assert "+250" in window.statusBar().currentMessage()


@pytest.mark.parametrize("count,paging_window", [(350, None), (1000, 600)])
def test_making_a_plan_fetches_its_categories_and_discloses_limits(
    qtbot, tmp_path: Path, count: int, paging_window: int | None
) -> None:  # type: ignore[no-untyped-def]
    from tests.fake_qbit import FakeQbit
    from tests.fake_torznab import FakeTorznab
    from torrentlinker.credentials import set_secret
    from torrentlinker.downloads import DownloadFolders, IndexerCategory
    from torrentlinker.gui.settings_dialog import INDEXER_API_KEY
    from torrentlinker.indexer import Indexer
    from torrentlinker.paths import MappedQbit, PathMapper

    films = tmp_path / "films"
    films.mkdir()
    s = Settings()
    s.indexer_categories = {2030: IndexerCategory("Film")}
    s.indexer.url = "https://c411.example/api/torznab"
    s.download_folders = DownloadFolders({2030: str(films)})
    store = Store(tmp_path / "s.db")
    window = MainWindow(s, tmp_path / "settings.json", store)
    qtbot.addWidget(window)
    set_secret(INDEXER_API_KEY, "K")
    torznab = FakeTorznab(window=paging_window)
    torznab.add(2030, count)
    window._indexer = Indexer(
        s.indexer.url, "K", http=torznab.client(), cache=store, sleep=lambda _s: None
    )
    window.qbit = lambda: MappedQbit(FakeQbit(), PathMapper([]))  # type: ignore[method-assign]

    window.make_plan()
    qtbot.waitUntil(lambda: window.zen_tab.plan_view.plan is not None, timeout=10_000)

    assert store.catalogue_size() == min(count, paging_window or count)
    assert window.zen_tab.plan_view.plan.items
    if paging_window is not None:
        assert "incomplete Catalogue" in window.zen_tab.plan_view.summary.text()
        assert "Catalogue incomplete" in window.zen_tab.catalogue.status.text()
    else:
        assert "incomplete Catalogue" not in window.zen_tab.plan_view.summary.text()


@pytest.mark.parametrize("stop_early", [False, True])
def test_a_plan_waits_for_an_active_refresh_then_refreshes_its_own_categories(
    qtbot, tmp_path: Path, monkeypatch, stop_early: bool
) -> None:  # type: ignore[no-untyped-def]
    import threading

    from torrentlinker.credentials import set_secret
    from torrentlinker.downloads import DownloadFolders, IndexerCategory
    from torrentlinker.gui.settings_dialog import INDEXER_API_KEY
    from torrentlinker.plan import Plan

    settings = Settings()
    settings.indexer.url = "https://c411.example/api/torznab"
    settings.indexer_categories = {7000: IndexerCategory("Ebook")}
    settings.download_folders = DownloadFolders({7000: str(tmp_path)})
    window = MainWindow(settings, tmp_path / "settings.json", Store(tmp_path / "s.db"))
    qtbot.addWidget(window)
    set_secret(INDEXER_API_KEY, "K")
    started, release, planned = threading.Event(), threading.Event(), threading.Event()
    order: list[str] = []

    def active_refresh(stop, progress) -> None:  # type: ignore[no-untyped-def]
        started.set()
        release.wait(timeout=5)
        order.append("active refresh finished")

    def plan_refresh(indexer, store, targets, **kw) -> None:  # type: ignore[no-untyped-def]
        assert targets == [7000] and not kw["full"] and kw["bootstrap"]
        order.append("Plan categories refreshed")

    def build() -> Plan:
        order.append("Plan built")
        planned.set()
        return Plan()

    monkeypatch.setattr("torrentlinker.gui.main_window.sync_catalogue", plan_refresh)
    window.plan_maker = lambda **kw: build  # type: ignore[method-assign]
    window.zen_tab.plan_view.show_plan(Plan())  # a result from a previous request
    window._after_catalogue = lambda: order.append("active refresh callback")
    window._run_catalogue(active_refresh)
    assert started.wait(timeout=1)
    try:
        window.make_plan()
        assert window.zen_tab.plan_view.plan is None
        assert not window.zen_tab.plan_view.make_button.isEnabled()
        assert not planned.wait(timeout=0.2), (
            "Plan was built while the Catalogue was still refreshing"
        )
        if stop_early:
            window._stop_plan_fetch()
    finally:
        release.set()
        qtbot.waitUntil(lambda: window.catalogue_runner is None, timeout=5000)

    qtbot.waitUntil(lambda: window.zen_tab.plan_view.plan is not None, timeout=5000)
    expected = ["active refresh finished", "active refresh callback"]
    # Stopping explicitly allows planning from what was fetched so far.
    if not stop_early:
        expected += ["Plan categories refreshed"]
    # A stopped refresh does not run its success-only callback.
    else:
        expected.remove("active refresh callback")
    assert order == [*expected, "Plan built"]


def test_a_failed_plan_refresh_does_not_build_from_the_old_catalogue(
    qtbot, tmp_path: Path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    from torrentlinker.credentials import set_secret
    from torrentlinker.downloads import DownloadFolders, IndexerCategory
    from torrentlinker.gui.settings_dialog import INDEXER_API_KEY
    from torrentlinker.plan import Plan

    settings = Settings()
    settings.indexer.url = "https://c411.example/api/torznab"
    settings.indexer_categories = {7000: IndexerCategory("Ebook")}
    settings.download_folders = DownloadFolders({7000: str(tmp_path)})
    window = MainWindow(settings, tmp_path / "settings.json", Store(tmp_path / "s.db"))
    qtbot.addWidget(window)
    set_secret(INDEXER_API_KEY, "K")
    builds = []

    def failed(*args, **kw) -> None:  # type: ignore[no-untyped-def]
        raise ValueError("Catalogue refresh failed")

    def build() -> Plan:
        builds.append(True)
        return Plan()

    monkeypatch.setattr("torrentlinker.gui.main_window.sync_catalogue", failed)
    window.plan_maker = lambda **kw: build  # type: ignore[method-assign]
    window.make_plan()
    qtbot.waitUntil(lambda: window.catalogue_runner is None, timeout=5000)

    assert not builds
    assert window.zen_tab.plan_view.plan is None
    assert "Could not make a Plan" in window.zen_tab.plan_view.summary.text()
    assert window.zen_tab.plan_view.make_button.isEnabled()


@pytest.mark.parametrize("pending", [False, True])
def test_plan_progress_identifies_ebook_audio_and_its_selected_scope(
    qtbot, tmp_path: Path, pending: bool
) -> None:  # type: ignore[no-untyped-def]
    from torrentlinker.catalogue import CrawlProgress
    from torrentlinker.downloads import IndexerCategory

    settings = Settings()
    settings.indexer_categories = {
        7000: IndexerCategory("Ebook"),
        3030: IndexerCategory("Audio", 7000),
        3000: IndexerCategory("Audio"),
    }
    settings.plan_categories = [7000]
    window = MainWindow(settings, tmp_path / "settings.json", Store(tmp_path / "s.db"))
    qtbot.addWidget(window)
    window._planning = True
    window._catalogue_added = {}
    window._pending_plan = (lambda: None) if pending else None

    window._catalogue_progress(CrawlProgress(3000 if pending else 3030, 6, 0, 600, "c411-json"))

    text = window.zen_tab.plan_view.summary.text()
    if pending:
        assert text.startswith("Waiting for the Catalogue refresh to finish")
        assert "Fetching the Catalogue for the Plan" not in text
    else:
        assert "Ebook / Audio" in text
        assert "selected categories" in text


def test_plan_controls_save_both_limits_and_change_the_actual_plan(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from tests.fake_qbit import FakeQbit
    from torrentlinker.downloads import DownloadFolders, IndexerCategory
    from torrentlinker.plan import PlanGoal, PlanOptions
    from torrentlinker.store import CatalogueRow
    from torrentlinker.zen import GB

    settings = Settings()
    settings.indexer_categories = {7000: IndexerCategory("Ebook")}
    settings.download_folders = DownloadFolders({7000: str(tmp_path)})
    store = Store(tmp_path / "s.db")
    store.save_catalogue(
        [CatalogueRow(f"{i:040x}", f"Book {i}", GB, 5, 7000, "u", "d", 0) for i in range(4)]
    )
    path = tmp_path / "settings.json"
    window = MainWindow(settings, path, store)
    qtbot.addWidget(window)
    window.qbit = lambda: FakeQbit()  # type: ignore[assignment,method-assign,return-value]
    view = window.zen_tab.plan_view
    view.goal.setCurrentIndex(view.goal.findData("note"))
    view.download_limit.setValue(2)

    assert not view.torrent_limit.isEnabled()
    assert settings.plan_options == PlanOptions(PlanGoal.NOTE, 2 * GB)
    assert len(window.plan_maker()().items) == 2

    view.limit_torrents.setChecked(True)
    view.torrent_limit.setValue(1)
    assert view.torrent_limit.isEnabled()
    assert Settings.load(path).plan_options == PlanOptions(PlanGoal.NOTE, 2 * GB, 1)
    assert len(window.plan_maker()().items) == 1

    # Changing an option invalidates a previous result instead of sending an old Plan.
    window._plan_made(window.plan_maker()())
    assert view.send_button.isEnabled()
    view.download_limit.setValue(3)
    assert view.plan is None and not view.send_button.isEnabled()
    assert not view.seeder_limit.isEnabled()
    view.low_seeders.setChecked(True)
    assert view.seeder_limit.isEnabled()
    assert settings.plan_options.max_seeders == 10
    view.seeder_limit.setValue(4)
    assert Settings.load(path).plan_options.max_seeders == 4
    assert not window.plan_maker()().items  # every test torrent has five seeders
    view.seeder_limit.setValue(5)
    assert len(window.plan_maker()().items) == 1
    restored = type(view)()
    qtbot.addWidget(restored)
    restored.set_options(Settings.load(path).plan_options)
    assert restored.low_seeders.isChecked() and restored.seeder_limit.value() == 5
    view.low_seeders.setChecked(False)
    assert not view.seeder_limit.isEnabled() and settings.plan_options.max_seeders is None
    assert len(window.plan_maker()().items) == 1
    view.busy(True)
    assert not view.goal.isEnabled() and not view.download_limit.isEnabled()
    assert not view.limit_torrents.isEnabled() and not view.torrent_limit.isEnabled()
    assert not view.low_seeders.isEnabled() and not view.seeder_limit.isEnabled()


def test_plan_view_shows_notes_and_unused_disk_space_including_the_reserve(qtbot) -> None:  # type: ignore[no-untyped-def]
    from torrentlinker.gui.zen_view import PlanView
    from torrentlinker.plan import DiskSpace, Plan, PlanCandidate, PlanItem
    from torrentlinker.zen import GB

    view = PlanView()
    qtbot.addWidget(view)
    c = PlanCandidate("a" * 40, "Book", 4 * GB, 5, 7000, Path("/books"), "disk")
    plan = Plan(
        [PlanItem(c, 0.5, 1.35)],
        0.5,
        disk_spaces=(DiskSpace("disk", Path("/books"), 10 * GB, 2 * GB, 4 * GB),),
    )

    view.show_plan(plan)

    assert view.table.item(0, 3).text() == "1.35"
    assert "average note 1.35" in view.summary.text()
    assert view.space_table.rowCount() == 1
    assert view.space_table.item(0, 4).data(256) == 6 * GB
