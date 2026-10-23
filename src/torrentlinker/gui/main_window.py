from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QFile, QItemSelection, Qt, QTimer
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableView,
    QTabWidget,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from torrentlinker import net
from torrentlinker.catalogue import (
    STARTUP_PAGES,
    CrawlProgress,
    Progress,
    age,
    candidate,
    crawl_categories,
    plan_categories,
    startup_categories,
)
from torrentlinker.catalogue_sync import SNAPSHOT_NAME, sync_catalogue
from torrentlinker.category_tags import sync_category_tags
from torrentlinker.clients import connect
from torrentlinker.config import Settings
from torrentlinker.credentials import get_secret
from torrentlinker.domain import ContentKind, ItemState, LibraryFolder, TorrentClient
from torrentlinker.downloads import IndexerCategory
from torrentlinker.gui.batch_runner import BatchRunner
from torrentlinker.gui.catalogue_runner import CatalogueRunner
from torrentlinker.gui.errors import error_text
from torrentlinker.gui.library_model import LibraryFilter, LibraryModel, human_size, state_label
from torrentlinker.gui.review_panel import ReviewPanel, Searcher
from torrentlinker.gui.search_view import SearchTab
from torrentlinker.gui.send_runner import SendRunner
from torrentlinker.gui.settings_dialog import (
    ANNOUNCE_URL,
    DELUGE_PASSWORD,
    INDEXER_API_KEY,
    PROXY_PASSWORD,
    QBIT_API_KEY,
    QBIT_PASSWORD,
    TMDB_API_KEY,
    TRANSMISSION_PASSWORD,
    SettingsDialog,
    choose_directory,
    extra_indexer_keys,
)
from torrentlinker.gui.tables import EmptyState, style_table
from torrentlinker.gui.tasks import run_in_background
from torrentlinker.gui.theme import set_theme
from torrentlinker.gui.update_notice import UpdateNotice
from torrentlinker.gui.upload_view import UploadTab
from torrentlinker.gui.zen_view import ZenBand, ZenTab
from torrentlinker.indexer import Candidate, Indexer
from torrentlinker.library import (
    LibraryEntry,
    auto_searchable,
    build_library,
    indexer_contents,
)
from torrentlinker.matching import MatchRules
from torrentlinker.paths import MappedQbit, PathMapper
from torrentlinker.plan import (
    Plan,
    PlanCandidate,
    PlanOptions,
    ReseedSource,
    catalogue_candidates,
    disk_of,
    disk_space,
    make_plan,
    on_disk,
    reseed_candidates,
    restore_plan,
    saved_items,
)
from torrentlinker.profile import ProfileClient, UserProfile
from torrentlinker.qbit import ClientApi
from torrentlinker.queries import build_queries, find_ids
from torrentlinker.reseed import (
    Outcome,
    check_verifications,
    pending_verifications,
    start_reseed,
)
from torrentlinker.review import (
    CheckedCandidate,
    candidate_key,
    check_candidates,
    match_zen,
    remember_candidates,
    remembered_candidates,
    restore_checked,
    search_candidates,
)
from torrentlinker.scan import scan
from torrentlinker.seeding import Seeding, indexer_torrents, observe_swarm, seeding
from torrentlinker.send import SendProgress, SendReport, send_plan
from torrentlinker.speedtest import measure_download_speed
from torrentlinker.store import CatalogueRow, Store
from torrentlinker.tmdb import Tmdb
from torrentlinker.updates import check_for_update, installed_version

log = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings, settings_path: Path, store: Store) -> None:
        super().__init__()
        self.settings = settings
        self.settings_path = settings_path
        self.store = store
        self._indexer: Indexer | None = None
        # Kept connections, with what they were made for, the proxy in use included.
        self._profile: tuple[tuple[object, ...], ProfileClient] | None = None
        self._qbit: tuple[tuple[str, ...], ClientApi, tuple[str | None, str | None]] | None = None
        self.apply_proxy()
        self._indexer_proxy = net.current()  # what the Indexer, once made, goes through
        self.setWindowTitle(f"TorrentLinker {installed_version()}")
        self.resize(1280, 800)

        toolbar = QToolBar(self.tr("Library"), self)
        toolbar.setMovable(False)
        self.scan_action = QAction(self.tr("Scan"), self)
        self.scan_action.triggered.connect(lambda: self.scan())
        self.rescan_action = QAction(self.tr("Rescan everything"), self)
        self.rescan_action.setToolTip(
            self.tr("Walk every file again, ignoring the scan cache (slower)")
        )
        self.rescan_action.triggered.connect(lambda: self.scan(refresh=True))
        settings_action = QAction(self.tr("Settings"), self)
        settings_action.triggered.connect(self.open_settings)
        self.batch_selected_action = QAction(self.tr("Search selected"), self)
        self.batch_selected_action.triggered.connect(lambda: self.start_batch(selected_only=True))
        self.batch_all_action = QAction(self.tr("Search all Orphans"), self)
        self.batch_all_action.triggered.connect(lambda: self.start_batch(selected_only=False))
        self.cancel_action = QAction(self.tr("Cancel search"), self)
        self.cancel_action.triggered.connect(self.cancel_batch)
        self.cancel_action.setEnabled(False)
        scan_button = QToolButton()
        scan_button.setDefaultAction(self.scan_action)
        scan_button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        scan_menu = QMenu(scan_button)
        scan_menu.addAction(self.rescan_action)
        scan_button.setMenu(scan_menu)
        toolbar.addWidget(scan_button)
        toolbar.addSeparator()
        toolbar.addAction(self.batch_selected_action)
        toolbar.addAction(self.batch_all_action)
        toolbar.addAction(self.cancel_action)

        self.batch: BatchRunner | None = None
        self.batch_text = ""
        self.countdown = QTimer(self)
        self.countdown.setInterval(250)
        self.countdown.timeout.connect(self._show_batch_progress)

        self.library_model = LibraryModel()
        self.library_proxy = LibraryFilter()
        self.library_proxy.setSourceModel(self.library_model)
        self.library_view = QTableView()
        self.library_view.setModel(self.library_proxy)
        style_table(self.library_view)
        self.library_view.setAccessibleName(self.tr("Library"))
        self.library_empty = EmptyState(
            self.library_view,
            self.tr("No Local Items to show. Adjust the filters or scan your Library Folders."),
        )
        self.library_view.setSortingEnabled(True)
        self.library_view.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self.library_view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.library_view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        header = self.library_view.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        header.resizeSection(3, 160)
        self.library_view.selectionModel().selectionChanged.connect(self._selection_changed)

        self.library_search = QLineEdit()
        self.library_search.setPlaceholderText(self.tr("Filter Local Items…"))
        self.library_search.setAccessibleName(self.tr("Filter Local Items"))
        self.library_search.setClearButtonEnabled(True)
        self.library_search.textChanged.connect(self._apply_filters)
        filters = QHBoxLayout()
        self.state_filter = QComboBox()
        self.state_filter.addItem(self.tr("All states"), None)
        for state in ItemState:
            self.state_filter.addItem(state_label(state), state)
        self.folder_filter = QComboBox()
        self.state_filter.currentIndexChanged.connect(self._apply_filters)
        self.folder_filter.currentIndexChanged.connect(self._apply_filters)
        filters.addWidget(self.library_search, 2)
        filters.addWidget(self.state_filter)
        filters.addWidget(self.folder_filter, 1)
        library_pane = QWidget()
        library_layout = QVBoxLayout(library_pane)
        library_layout.setContentsMargins(0, 0, 0, 0)
        library_layout.addLayout(filters)
        library_layout.addWidget(self.library_view)
        self._fill_folder_filter()

        self.review = ReviewPanel(
            store, self.indexer, self.qbit, self.match_rules, self.searcher, self.default_query
        )
        self.review.reseed_started.connect(self._reseed_started)
        self.review.unpacked.connect(lambda _folder: self.scan())  # show the new folder
        self.review.candidates_checked.connect(self._show_match_zen)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(library_pane)
        splitter.addWidget(self.review)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(2)
        splitter.setSizes([660, 520])
        self.zen_tab = ZenTab(self.seeding_loader, lambda: self.settings.zen, settings.uploads)
        self.zen_tab.comparison.uploads_changed.connect(self._uploads_changed)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.zen_tab, self.tr("Zen"))
        library_page = QWidget()
        library_page_layout = QVBoxLayout(library_page)
        library_page_layout.setContentsMargins(0, 0, 0, 0)
        library_page_layout.addWidget(toolbar)
        library_page_layout.addWidget(splitter, 1)
        self.tabs.addTab(library_page, self.tr("Library"))
        self.upload_tab = UploadTab(
            store,
            self.indexer,
            self.qbit,
            lambda: self.settings.matching.ignore,
            lambda: get_secret(ANNOUNCE_URL),
            store.torrent_dir.parent / "uploads",
        )
        self.review.candidates_checked.connect(self.upload_tab.remember)
        self.review.upload_blocker = self.upload_tab.why_not
        self.review.upload_requested.connect(self._open_upload)
        self.upload_tab.upload_started.connect(self._reseed_started)
        self.upload_tab.unpacked.connect(lambda _folder: self.scan())  # show the new folder
        self.tabs.addTab(self.upload_tab, self.tr("Upload"))
        self.search_tab = SearchTab(store, settings, self.indexer, self.qbit)
        self.tabs.addTab(self.search_tab, self.tr("Search"))
        self.band = ZenBand()
        self.band.refresh_requested.connect(self.refresh_profile)
        self.zen_tab.seeding_view.updated.connect(self.band.set_seeding)
        self.zen_tab.seeding_view.updated.connect(self.search_tab.set_seeding)
        self.tabs.tabBar().hide()
        self.navigation = QListWidget()
        self.navigation.setObjectName("navigation")
        self.navigation.setAccessibleName(self.tr("Workspaces"))
        self.navigation.addItems(
            [self.tr("Zen"), self.tr("Library"), self.tr("Upload"), self.tr("Search")]
        )
        self.navigation.setCurrentRow(0)
        self.navigation.currentRowChanged.connect(self.tabs.setCurrentIndex)
        self.tabs.currentChanged.connect(self.navigation.setCurrentRow)
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(172)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(16, 24, 16, 16)
        brand = QLabel("TorrentLinker")
        brand.setProperty("role", "brand")
        side.addWidget(brand)
        side.addSpacing(24)
        side.addWidget(self.navigation, 1)
        settings_button = QPushButton(self.tr("Settings"))
        settings_button.clicked.connect(self.open_settings)
        side.addWidget(settings_button)
        central = QWidget()
        shell = QHBoxLayout(central)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        shell.addWidget(sidebar)
        content = QWidget()
        central_layout = QVBoxLayout(content)
        central_layout.setContentsMargins(24, 20, 24, 12)
        central_layout.setSpacing(16)
        self.page_title = QLabel()
        self.page_title.setProperty("role", "heading")
        self.page_description = QLabel()
        self.page_description.setProperty("role", "muted")
        self.page_description.setWordWrap(True)
        central_layout.addWidget(self.page_title)
        central_layout.addWidget(self.page_description)
        self.update_notice = UpdateNotice()
        central_layout.addWidget(self.update_notice)
        central_layout.addWidget(self.band)
        central_layout.addWidget(self.tabs, 1)
        shell.addWidget(content, 1)
        self.tabs.currentChanged.connect(self._workspace_changed)
        self._workspace_changed(0)
        self.setCentralWidget(central)
        settings_action.setShortcut("Ctrl+,")
        self.addAction(settings_action)
        for index in range(self.tabs.count()):
            action = QAction(self.tabs.tabText(index), self)
            action.setShortcut(f"Ctrl+{index + 1}")
            action.triggered.connect(lambda checked=False, i=index: self.tabs.setCurrentIndex(i))
            self.addAction(action)
        find = QAction(self.tr("Filter Local Items"), self)
        find.setShortcut("Ctrl+F")
        find.triggered.connect(self._focus_search)
        self.addAction(find)
        self.statusBar().showMessage(self.tr("Ready"))

        self._checking = False
        self.catalogue_runner: CatalogueRunner | None = None
        self.send_runner: SendRunner | None = None
        self._crawl_position = [0, 0]  # category being crawled, of how many (worker writes)
        self.zen_tab.plan_view.make_requested.connect(self.make_plan)
        self.zen_tab.plan_view.categories_changed.connect(self._plan_categories_changed)
        self.zen_tab.plan_view.set_options(self.settings.plan_options)
        self.zen_tab.plan_view.options_changed.connect(self._plan_options_changed)
        self.zen_tab.plan_view.stop_fetch_requested.connect(self._stop_plan_fetch)
        self.offer_plan_categories()
        self.zen_tab.plan_view.send_requested.connect(self.confirm_send)
        self.zen_tab.plan_view.stop_send_requested.connect(self.stop_sending)
        self.zen_tab.plan_view.speed_test_requested.connect(self.test_speed)
        self.zen_tab.plan_view.set_speed(settings.download_speed, settings.download_speed_tested)
        self.zen_tab.plan_view.keys = 1 + len(extra_indexer_keys())
        self._after_catalogue: Callable[[], None] | None = None
        self._after_catalogue_always: Callable[[], None] | None = None
        self._pending_plan: Callable[[], None] | None = None
        self._last_crawl_progress: CrawlProgress | None = None
        self.crawl_ticker = QTimer(self)
        self.crawl_ticker.setInterval(500)
        self.crawl_ticker.timeout.connect(self._show_crawl_progress)
        self._planning = False
        self.zen_tab.catalogue.start_requested.connect(self.crawl_catalogue)
        self.zen_tab.catalogue.pause_requested.connect(self.pause_catalogue)
        self._show_catalogue_age()
        self.verify_timer = QTimer(self)
        self.verify_timer.setInterval(3000)
        self.verify_timer.timeout.connect(self.check_verifications)
        self.seeding_timer = QTimer(self)
        self.seeding_timer.setInterval(30_000)
        self.seeding_timer.timeout.connect(lambda: self.zen_tab.seeding_view.refresh(quiet=True))
        self.seeding_timer.start()
        self.show_saved_plan(interrupted=bool((saved := store.saved_plan()) and saved.sending))
        if settings_path.exists():
            QTimer.singleShot(0, self.check_verifications)  # settle Reseeds from a past session
            QTimer.singleShot(0, self.zen_tab.seeding_view.refresh)
            QTimer.singleShot(0, self.refresh_profile)
            QTimer.singleShot(0, self.upload_tab.refresh_drafts)
            QTimer.singleShot(0, lambda: self.refresh_categories(then=self.update_catalogue))
            if settings.library_folders:
                QTimer.singleShot(0, self.scan)  # the Library as it was, with its last searches

    def check_for_updates(self) -> None:
        cache = self.settings_path.parent / "release-check.json"
        run_in_background(
            lambda: check_for_update(cache),
            self.update_notice.show_release,
            lambda error: log.debug("release check unavailable: %s", error),
        )

    def _workspace_changed(self, index: int) -> None:
        self.page_title.setText(self.tabs.tabText(index))
        descriptions = [
            self.tr("Track your earnings and plan what to seed next."),
            self.tr("Find Orphans, compare Candidates and Reseed your files."),
            self.tr("Prepare an Upload, then review and publish its Draft on c411."),
            self.tr("Search torrents and queue the ones you want to download."),
        ]
        self.page_description.setText(descriptions[index])

    def _focus_search(self) -> None:
        if self.tabs.currentWidget() is self.search_tab:
            self.search_tab.focus_search()
            return
        self.tabs.setCurrentIndex(1)
        self.library_search.setFocus()
        self.library_search.selectAll()

    def apply_proxy(self) -> None:
        """Make every connection from now on go through the proxy set in Settings."""
        p = self.settings.proxy
        try:
            proxy = net.proxy_url(p.address, p.username, get_secret(PROXY_PASSWORD))
        except ValueError as e:
            log.warning("proxy ignored: %s", e)
            proxy = None
        net.configure(proxy, p.torrent_client)
        log.info("proxy: %s", net.redacted(proxy) or "none")

    def qbit(self) -> MappedQbit:
        """The Torrent Client the user chose, through Path Mappings."""
        s = self.settings
        if s.client is TorrentClient.DELUGE:
            key: tuple[str, ...] = (s.client, s.deluge.host, "", get_secret(DELUGE_PASSWORD))
        elif s.client is TorrentClient.TRANSMISSION:
            t = s.transmission
            key = (s.client, t.host, t.username, get_secret(TRANSMISSION_PASSWORD))
        else:
            q = s.qbit
            key = (s.client, q.host, q.username, get_secret(QBIT_PASSWORD))
            key += (get_secret(QBIT_API_KEY),)
        if self._qbit is None or self._qbit[2] != net.current() or self._qbit[0] != key:
            self._qbit = (key, connect(s.client, *key[1:]), net.current())
        return MappedQbit(self._qbit[1], PathMapper(s.path_mappings))

    def indexer(self) -> Indexer:
        """One Indexer instance, so every search shares the same rate limiter.

        Only call on the GUI thread; workers get the instance passed in.
        """
        url, key = self.settings.indexer.url, get_secret(INDEXER_API_KEY)
        extra = tuple(extra_indexer_keys())
        current = self._indexer
        if (
            current is None
            or self._indexer_proxy != net.current()
            or (
                current.url,
                current.api_key,
                tuple(getattr(current, "extra_keys", ())),  # test stubs have none
            )
            != (url, key, extra)
        ):
            current = self._indexer = Indexer(url, key, cache=self.store, extra_keys=extra)
            self._indexer_proxy = net.current()
        return current

    def profile_client(self) -> ProfileClient:
        """One client, so its 30-second freshness window holds across refreshes."""
        wanted = (self.settings.indexer.url, get_secret(INDEXER_API_KEY))
        if self._profile is None or self._profile[0] != (*wanted, net.current()):
            self._profile = ((*wanted, net.current()), ProfileClient(*wanted))
        return self._profile[1]

    def refresh_profile(self) -> None:
        """Read the c411 profile; only at startup and when the user asks."""
        self.band.busy(True)
        run_in_background(self.profile_client().fetch, self._profile_read, self._profile_failed)

    def _profile_read(self, profile: UserProfile) -> None:
        self.band.show_profile(profile)
        filled = profile.apply(self.settings.zen)
        if filled != self.settings.zen:
            self.settings.zen = filled
            self.settings.save(self.settings_path)
            log.info("Zen Profile filled from c411: %s", filled)
            self.zen_tab.seeding_view.refresh()

    def _profile_failed(self, error: Exception) -> None:
        log.info("c411 profile not read: %s", error)
        self.band.show_profile_error(error)

    # Plan ------------------------------------------------------------------

    def make_plan(self, then: Callable[[], None] | None = None) -> None:
        """Refresh new torrents in the Plan's categories, then make the Plan."""
        self._use_cached_plan = False
        self.store.clear_plan()
        self.zen_tab.plan_view.begin()
        self.band.set_plan(None)
        if self.catalogue_runner is not None:

            def resume() -> None:
                if self._use_cached_plan:
                    self._build_plan(then)
                else:
                    self.make_plan(then)

            self._pending_plan = resume
            self._planning = True
            self.zen_tab.plan_view.busy(
                True, self.tr("Waiting for the Catalogue refresh to finish…")
            )
            self.zen_tab.plan_view.fetching(True)
            return
        s = self.settings
        chosen = set(s.plan_categories) if s.plan_categories is not None else None
        targets = plan_categories(chosen, s.download_folders, s.indexer_categories)
        if not targets or not get_secret(INDEXER_API_KEY):
            self._build_plan(then)
            return
        indexer, store, categories = self.indexer(), self.store, dict(s.indexer_categories)

        def work(stop: Callable[[], bool], progress: Progress) -> None:
            log.info("Fetching Catalogue categories for the Plan: %s", targets)
            sync_catalogue(
                indexer,
                store,
                targets,
                full=False,
                bootstrap=True,
                stop=stop,
                progress=progress,
                categories=categories,
            )

        self._planning = True
        self.zen_tab.plan_view.busy(True, self.tr("Fetching the Catalogue for the Plan…"))
        self.zen_tab.plan_view.fetching(True)

        def after_fetch() -> None:
            if self._catalogue_error is not None and not self._use_cached_plan:
                self._planning = False
                self.zen_tab.plan_view.fetching(False)
                self.zen_tab.plan_view.failed(self._catalogue_error)
            else:
                self._build_plan(then)

        self._after_catalogue_always = after_fetch
        self._run_catalogue(work)

    def _stop_plan_fetch(self) -> None:
        self._use_cached_plan = True
        if self.catalogue_runner is not None:
            self.catalogue_runner.stop()
        self.zen_tab.plan_view.fetching(False)

    def _build_plan(self, then: Callable[[], None] | None = None) -> None:
        self._planning = False
        self.zen_tab.plan_view.fetching(False)
        self.zen_tab.plan_view.busy(True)

        def done(plan: Plan) -> None:
            self._planning = False
            self.zen_tab.plan_view.fetching(False)
            self._plan_made(plan)
            if then is not None and plan.items:
                then()

        run_in_background(self.plan_maker(), done, self.zen_tab.plan_view.failed)

    def offer_plan_categories(self) -> None:
        """Offer every category and subcategory, marking those without a Download Folder."""
        s = self.settings
        cats, folders = s.indexer_categories, s.download_folders
        options = []
        for cid, cat in sorted(cats.items()):
            if cat.parent is None:
                options.append((cid, cat.name, False))
                options += [
                    (sid, sub.name, True) for sid, sub in sorted(cats.items()) if sub.parent == cid
                ]
        without = {cid for cid, _name, _sub in options if folders.resolve(cid, cats) is None}
        chosen = set(s.plan_categories) if s.plan_categories is not None else None
        self.zen_tab.plan_view.set_category_options(options, chosen, without)

    def _plan_categories_changed(self, chosen: set[int] | None) -> None:
        before = set(self.settings.plan_categories or ())
        added = sorted(chosen - before) if chosen is not None else []
        if added:
            self.prefetch_categories(added)  # fetched while the user picks folders
        refused = {cid for cid in added if not self.ensure_download_folder(cid)}
        if chosen is not None and refused:
            chosen = (chosen - refused) or None
        self.settings.plan_categories = sorted(chosen) if chosen is not None else None
        self.settings.save(self.settings_path)
        self.offer_plan_categories()

    def ensure_download_folder(self, cid: int) -> bool:
        """Whether the Plan can draw from `cid`; asks for its Download Folder if needed."""
        s = self.settings
        cats, folders = s.indexer_categories, s.download_folders
        if folders.resolve(cid, cats) is not None:
            return True
        name = cats[cid].name if cid in cats else str(cid)
        covered = [
            c.name
            for sid, c in sorted(cats.items())
            if c.parent == cid and folders.resolve(sid, cats) is not None
        ]
        if covered:
            answer = QMessageBox.question(
                self,
                self.tr("Download Folder"),
                self.tr(
                    "{0} has no Download Folder, but {1} have theirs. Choose a folder for "
                    "its other subcategories? Otherwise the Plan draws only from those."
                ).format(name, ", ".join(covered)),
            )
            if answer != QMessageBox.StandardButton.Yes:
                return True
        path = choose_directory(self, self.tr("Download Folder for {0}").format(name))
        if not path:
            return bool(covered)
        folders.by_category[cid] = path
        s.save(self.settings_path)
        log.info("Download Folder of category %s set to %s", cid, path)
        return True

    def prefetch_categories(self, categories: list[int]) -> None:
        """Start fetching the Catalogue of newly chosen categories, in the background."""
        if self.catalogue_runner is not None or not get_secret(INDEXER_API_KEY):
            return  # the update under way, or the next Plan, fetches them
        indexer, store, known = self.indexer(), self.store, dict(self.settings.indexer_categories)

        def work(stop: Callable[[], bool], progress: Progress) -> None:
            log.info("Fetching the Catalogue of newly chosen categories: %s", categories)
            sync_catalogue(
                indexer,
                store,
                categories,
                full=False,
                bootstrap=True,
                stop=stop,
                progress=progress,
                categories=known,
            )

        self._run_catalogue(work)

    def _plan_options_changed(self, options: PlanOptions) -> None:
        self.settings.plan_options = options
        self.settings.save(self.settings_path)
        self.store.clear_plan()
        self.zen_tab.plan_view.invalidate()
        self.band.set_plan(None)

    def plan_maker(self) -> Callable[[], Plan]:
        """Build on the GUI thread the work that makes a Plan (no Indexer request)."""
        s = self.settings
        qbit, store, profile, url = self.qbit(), self.store, s.zen, s.indexer.url
        folders, categories, margin = (
            s.download_folders,
            dict(s.indexer_categories),
            s.free_space_margin,
        )
        only = set(s.plan_categories) if s.plan_categories is not None else None
        options = s.plan_options
        planned_folders = {
            folder
            for c in plan_categories(only, folders, categories)
            if (folder := folders.resolve(c, categories)) is not None
        }
        if only is None and folders.default.strip():
            planned_folders.add(Path(folders.default))
        # Orphans whose Matches searches found, for Reseed rows (read on the GUI thread)
        found = [
            (e, list(self.review.cache[e.item.path]))
            for e in self.library_model.entries
            if e.state is ItemState.ORPHAN and e.item.path in self.review.cache
        ]
        local_items = [e.item for e in self.library_model.entries]
        # Download Folders hold books too, maybe from torrents removed from qBittorrent.
        libraries = [f.path for f in s.library_folders]
        unlisted = sorted(
            f for f in planned_folders if not any(f.is_relative_to(r) for r in libraries)
        )

        def work() -> Plan:
            torrents = qbit.torrents(with_files=False)
            cached = observe_swarm(store, torrents, url)
            view = seeding(profile, torrents, url, catalogue=cached)
            in_client = {t.hash.lower() for t in torrents}
            candidates = reseed_candidates(
                profile,
                found,
                in_client,
                view.active,
                options=options,
            )
            downloads = catalogue_candidates(
                store.catalogue(),
                folders,
                categories,
                in_client,
                disk_of,
                only,
            )
            on_disk_items = list(local_items)
            for folder in unlisted:
                try:
                    on_disk_items += scan(LibraryFolder(folder), store)
                except OSError as e:
                    log.info("Download Folder not scanned for books on disk: %s", e)
            already = on_disk(downloads, on_disk_items)
            left_out = {d.infohash for d in already}
            candidates += [c for c in downloads if c.infohash not in left_out]
            if already:
                log.info(
                    "Plan leaves out %d torrents that seem to be on disk, e.g. %s",
                    len(already),
                    "; ".join(f"{d.title} <- {d.path}" for d in already[:5]),
                )
            spaces = disk_space(
                sorted(planned_folders | {c.folder for c in candidates if c.folder}, key=str),
                margin,
            )
            budgets = {space.disk: space.available for space in spaces}
            slots = max(0, profile.torrent_cap - view.count) if profile.torrent_cap else None
            plan = make_plan(
                profile,
                candidates,
                budgets,
                view.active,
                slots,
                options=options,
                disk_spaces=spaces,
            )
            return replace(plan, on_disk=tuple(already))

        return work

    def _plan_made(self, plan: Plan) -> None:
        self.store.save_plan(saved_items(plan), zen_added=plan.zen_added)
        self.zen_tab.plan_view.show_plan(plan)
        s = self.settings
        targets = plan_categories(s.plan_categories, s.download_folders, s.indexer_categories)
        if self.store.limited_categories().intersection(targets):
            summary = self.zen_tab.plan_view.summary
            summary.setText(
                summary.text()
                + "\n"
                + self.tr("Based on an incomplete Catalogue; older torrents may be missing.")
            )
        if plan.items:
            summary = self.zen_tab.plan_view.summary
            summary.setText(
                summary.text()
                + "\n"
                + self.tr(
                    "Provisional estimates from cached metadata. Seeder counts update from "
                    "your torrent client after tracker responses."
                )
            )
        self.band.set_plan(plan.zen_added if plan.items else None)

    def confirm_send(self) -> None:
        """Summary before sending, with the choice to refresh the Catalogue first."""
        plan = self.zen_tab.plan_view.plan
        if plan is None or not plan.items:
            return
        payback = plan.payback_days
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(self.tr("Send the Plan to your torrent client"))
        box.setText(
            self.tr(
                "{0} torrents · {1} Go to download · ≈ +{2} Zen/day · paid back in ≈ {3} "
                "days.\nCatalogue: {4}.\n\nEach .torrent is downloaded directly from c411 "
                "with your key and added to its Download Folder. A torrent whose files "
                "already exist there is refused."
            ).format(
                len(plan.items),
                f"{plan.download_size / 1e9:.1f}",
                f"{plan.zen_added:.2f}",
                f"{payback:.0f}" if payback is not None else "–",
                self.catalogue_age(),
            )
            + "\n\n"
            + self.zen_tab.plan_view.times.text()
        )
        send = box.addButton(self.tr("Send"), QMessageBox.ButtonRole.AcceptRole)
        refresh = box.addButton(self.tr("Refresh first"), QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        if box.clickedButton() is send:
            self.send_plan(plan)
        elif box.clickedButton() is refresh:
            self.make_plan(then=self.confirm_send)  # fetches the Plan's categories first

    def test_speed(self) -> None:
        self.zen_tab.plan_view.speed_testing()
        run_in_background(measure_download_speed, self._speed_measured, self._speed_failed)

    def _speed_measured(self, speed: float) -> None:
        self.settings.download_speed = speed
        self.settings.download_speed_tested = datetime.now().isoformat(timespec="minutes")
        self.settings.save(self.settings_path)
        log.info("Download speed tested: %.0f Mbit/s", speed * 8 / 1e6)
        view = self.zen_tab.plan_view
        view.set_speed(speed, self.settings.download_speed_tested)

    def _speed_failed(self, error: Exception) -> None:
        view = self.zen_tab.plan_view
        view.set_speed(self.settings.download_speed, self.settings.download_speed_tested)
        QMessageBox.warning(
            self,
            self.tr("Speed test"),
            self.tr("The speed test failed: {0}").format(str(error) or type(error).__name__),
        )

    def send_plan(self, plan: Plan) -> None:
        self.tabs.setCurrentWidget(self.zen_tab)
        self.zen_tab.pages.setCurrentIndex(1)
        if self.send_runner is not None:
            return
        qbit, indexer, reseeder = self.qbit(), self.indexer(), self.plan_reseeder()

        def fetch(c: PlanCandidate) -> bytes:
            assert isinstance(c.source, CatalogueRow)
            return indexer.fetch_torrent(candidate(indexer, c.source), retry=False)

        store = self.store

        def record(c: PlanCandidate, outcome: str, reason: str) -> None:
            store.mark_plan_item(c.infohash, outcome, reason)

        def work(stop: threading.Event, progress: Callable[[SendProgress], None]) -> SendReport:
            with indexer.background():  # the user's own searches and Reseeds go first
                return send_plan(
                    plan, qbit, fetch, reseeder, on_progress=progress, on_outcome=record, stop=stop
                )

        runner = SendRunner(work)
        runner.signals.progress.connect(self._send_progress)
        runner.signals.finished.connect(self._plan_sent)
        runner.signals.failed.connect(self._send_failed)
        self.send_runner = runner
        store.set_plan_sending(True)
        log.info("Sending a Plan of %d torrents", len(plan.items))
        self._send_progress(SendProgress(0, len(plan.items), "", 0, 0, 0))
        runner.start()

    def stop_sending(self) -> None:
        if self.send_runner is not None:
            self.send_runner.stop()

    def _send_progress(self, progress: SendProgress) -> None:
        self.zen_tab.plan_view.sending(progress)
        plan = self.zen_tab.plan_view.plan
        self.band.set_sending(progress, plan.zen_added if plan and plan.items else None)

    def _send_ended(self) -> None:
        self.send_runner = None
        self.store.set_plan_sending(False)
        self.zen_tab.plan_view.sending(None)
        self.band.set_sending(None)

    def _send_failed(self, error: Exception) -> None:
        self._send_ended()
        if not self.show_saved_plan():
            self.zen_tab.plan_view.show_plan(Plan())
        self.zen_tab.plan_view.failed(error)

    def show_saved_plan(self, interrupted: bool = False) -> bool:
        """Show what is left to send of the saved Plan; False if nothing is left."""
        saved = self.store.saved_plan()
        if saved is None:
            return False
        pending = saved.pending
        rows = {r.infohash: r for r in self.store.catalogue([i.infohash for i in pending])}
        plan = restore_plan(saved, rows)
        if not plan.items:
            self.store.clear_plan()
            return False
        view = self.zen_tab.plan_view
        view.show_plan(plan)
        left = (
            self.tr(
                "Sending was interrupted: {0} torrents of this Plan are left. "
                "Send to the torrent client to continue."
            )
            if interrupted
            else self.tr("Saved Plan: {0} torrents left to send.")
        )
        view.summary.setText(view.summary.text() + "\n" + left.format(len(plan.items)))
        self.band.set_plan(plan.zen_added)
        return True

    def plan_reseeder(self) -> Callable[[PlanCandidate], None]:
        """Reseed rows run the normal Reseed flow, with Verification (ADR-0002)."""
        qbit, store = self.qbit(), self.store

        def reseed(c: PlanCandidate) -> None:
            assert isinstance(c.source, ReseedSource)
            v = c.source.checked
            assert v.meta is not None and v.match is not None
            start_reseed(
                qbit, store, c.source.entry.item, v.meta, v.match, candidate_key(v.candidate)
            )

        return reseed

    def _plan_sent(self, report: SendReport) -> None:
        self._send_ended()
        total = len(self.zen_tab.plan_view.plan.items) if self.zen_tab.plan_view.plan else 0
        log.info(
            "Plan sent: %d added, %d Reseeds, %d refused, %d failed%s",
            len(report.added),
            len(report.reseeded),
            len(report.refused),
            len(report.failed),
            ", stopped" if report.stopped else "",
        )
        if not self.show_saved_plan():
            self.zen_tab.plan_view.show_plan(Plan())
        lines = [self.tr("{0} torrents added to your torrent client.").format(len(report.added))]
        if report.reseeded:
            lines.append(self.tr("{0} Reseeds started.").format(len(report.reseeded)))
        if report.stopped:
            lines.append(
                self.tr(
                    "Stopped after {0} of {1} torrents. The rest of the Plan is saved: "
                    "send it again to continue, even after restarting the app."
                ).format(report.handled, total)
            )
        problems = [self.tr("Refused: {0} ({1})").format(t, why) for t, why in report.refused]
        problems += [self.tr("Failed: {0} ({1})").format(t, why) for t, why in report.failed]
        box = QMessageBox(
            QMessageBox.Icon.Information, self.tr("Plan sent"), "\n".join(lines), parent=self
        )
        if problems:
            box.setInformativeText(
                self.tr("{0} refused, {1} failed: see the details.").format(
                    len(report.refused), len(report.failed)
                )
            )
            box.setDetailedText("\n".join(problems))
        box.exec()
        self.zen_tab.seeding_view.refresh()
        if report.reseeded:
            self.check_verifications()  # shows them as Verifying… and keeps polling

    # Catalogue -------------------------------------------------------------

    def refresh_categories(self, then: Callable[[], object] | None = None) -> None:
        """Read the Indexer's category tree (caps) and keep it in the settings if it changed."""
        if not get_secret(INDEXER_API_KEY):
            if then is not None:
                then()
            return
        indexer = self.indexer()

        def work() -> dict[int, IndexerCategory]:
            caps = indexer.caps()
            return {c: IndexerCategory(n, caps.parents.get(c)) for c, n in caps.categories.items()}

        def done(categories: dict[int, IndexerCategory]) -> None:
            if categories and categories != self.settings.indexer_categories:
                log.info("Indexer categories updated: %d", len(categories))
                self.settings.indexer_categories = categories
                self.search_tab.refresh_categories()
                self.settings.save(self.settings_path)
                self.offer_plan_categories()
            if then is not None:
                then()

        def failed(error: Exception) -> None:
            log.info("Indexer categories not refreshed: %s", error)
            if then is not None:
                then()

        run_in_background(work, done, failed)

    def update_catalogue(self, then: Callable[[], None] | None = None) -> bool:
        """Fetch the newest torrents of the user's categories (at startup, or before
        sending a Plan); `then` runs once it is done. False if it could not start."""
        if self.catalogue_runner is not None or not get_secret(INDEXER_API_KEY):
            return False
        self._after_catalogue = then
        indexer, store, qbit = self.indexer(), self.store, self.qbit()
        url, folders = self.settings.indexer.url, self.settings.download_folders
        categories = dict(self.settings.indexer_categories)

        def work(stop: Callable[[], bool], progress: Progress) -> None:
            try:
                seeded = [t.hash for t in indexer_torrents(qbit.torrents(with_files=False), url)]
            except Exception as e:  # noqa: BLE001 - qBittorrent may be down; folders still count
                log.info("Catalogue update without qBittorrent: %s", e)
                seeded = []
            wanted = startup_categories(folders, categories, seeded, store)
            log.info("Catalogue update of categories %s", wanted)
            sync_catalogue(
                indexer,
                store,
                wanted,
                max_pages=STARTUP_PAGES,
                stop=stop,
                progress=progress,
                categories=categories,
            )

        self._run_catalogue(work)
        return True

    def crawl_catalogue(self) -> None:
        """Fetch every category of the Indexer, resuming a paused crawl (user action)."""
        if self.catalogue_runner is not None:
            self.statusBar().showMessage(self.tr("The Catalogue is already being updated"))
            return
        if not get_secret(INDEXER_API_KEY):
            QMessageBox.information(
                self, self.tr("Catalogue"), self.tr("Enter your Indexer API key in Settings first.")
            )
            return
        indexer, store = self.indexer(), self.store
        known = dict(self.settings.indexer_categories)
        position = self._crawl_position

        def work(stop: Callable[[], bool], progress: Progress) -> None:
            categories = known or {
                c: IndexerCategory(name, caps.parents.get(c))
                for caps in [indexer.caps()]
                for c, name in caps.categories.items()
            }
            wanted = crawl_categories(categories)
            for i, category in enumerate(wanted, 1):
                if stop():
                    return
                position[:] = [i, len(wanted)]
                sync_catalogue(
                    indexer,
                    store,
                    [category],
                    full=True,
                    stop=stop,
                    progress=progress,
                    categories=categories,
                )

        self._crawl_position[:] = [0, 0]
        self.zen_tab.catalogue.set_state(True, False)
        self._run_catalogue(work)

    def pause_catalogue(self) -> None:
        if self.catalogue_runner is not None:
            self.catalogue_runner.stop()
            self.zen_tab.catalogue.set_status(self.tr("Pausing after the current page…"))

    def _run_catalogue(self, work: Callable[[Callable[[], bool], Progress], None]) -> None:
        indexer = self.indexer()

        def in_background(stop: Callable[[], bool], progress: Progress) -> None:
            with indexer.background():  # the user's own searches go first
                work(stop, progress)

        runner = CatalogueRunner(in_background)
        self._catalogue_added: dict[int, int] = {}
        self._last_crawl_progress = None
        self._catalogue_error: Exception | None = None
        self.crawl_ticker.start()
        runner.signals.progress.connect(self._catalogue_progress)
        runner.signals.failed.connect(self._catalogue_failed)
        runner.signals.finished.connect(self._catalogue_finished)
        self.catalogue_runner = runner
        runner.start()

    def _catalogue_progress(self, p: CrawlProgress) -> None:
        self._catalogue_added[p.category] = p.added
        self._last_crawl_progress = p
        self._show_crawl_progress()

    def _show_crawl_progress(self) -> None:
        """Also redrawn twice a second while fetching, for the countdown and the total."""
        p = self._last_crawl_progress
        if p is None:
            return
        if p.source == SNAPSHOT_NAME:
            text = self.tr("Importing Zen Lab metadata: {0} torrents (+{1})").format(
                p.offset, p.added
            )
            self.band.set_catalogue(text)
            self.zen_tab.catalogue.set_status(text)
            self.statusBar().showMessage(text)
            if self._planning:
                self.zen_tab.plan_view.busy(True, text)
            return
        name = self.settings.indexer_categories.get(p.category)
        label = name.name if name else str(p.category)
        if name is not None and name.parent is not None:
            parent = self.settings.indexer_categories.get(name.parent)
            if parent is not None:
                label = f"{parent.name} / {label}"
        text = self.tr("updating {0}, page {1} (+{2})").format(label, p.pages, p.added)
        self.band.set_catalogue(text)
        wait = self._indexer.next_request_in() if self._indexer else 0
        suffix = self.tr(" · next request in {0} s").format(f"{wait:.0f}") if wait > 0.5 else ""
        size = self.store.catalogue_size()
        if self.zen_tab.catalogue.running:
            done, total = self._crawl_position
            status = self.tr("Category {0}/{1}: {2} · {3} torrents in the Catalogue").format(
                done, total, text, size
            )
        elif self._planning and self._pending_plan is None:
            status = self.tr(
                "Updating selected categories: {0} · {1} torrents in the Catalogue"
            ).format(text, size)
        else:  # a startup update may cover more categories than a queued Plan
            status = self.tr(
                "Updating your categories: {0} · {1} torrents in the Catalogue"
            ).format(text, size)
        self.zen_tab.catalogue.set_status(status + suffix)
        self.statusBar().showMessage(self.tr("Catalogue: {0}").format(status) + suffix)
        if self._planning:
            if self._pending_plan is not None:
                self.zen_tab.plan_view.busy(
                    True,
                    self.tr("Waiting for the Catalogue refresh to finish…") + " " + status + suffix,
                )
                return
            self.zen_tab.plan_view.busy(
                True, self.tr("Fetching the Catalogue for the Plan: {0}").format(status + suffix)
            )

    def _catalogue_failed(self, error: Exception) -> None:
        self._catalogue_error = error
        log.warning("Catalogue update failed: %s", error)
        self.statusBar().showMessage(
            self.tr("Catalogue update failed: {0}").format(error_text(error))
        )

    def _catalogue_finished(self, stopped: bool) -> None:
        self.catalogue_runner = None
        self.crawl_ticker.stop()
        self._show_catalogue_age()
        added, size = sum(self._catalogue_added.values()), self.store.catalogue_size()
        log.info(
            "Catalogue %s: +%d torrents, %d in total",
            "paused" if stopped else "updated",
            added,
            size,
        )
        message = (
            self.tr("Catalogue paused: +{0} torrents · {1} in total")
            if stopped
            else self.tr("Catalogue updated: +{0} torrents · {1} in total")
        )
        result = message.format(added, size)
        error = getattr(self, "_catalogue_error", None)
        if error is not None:
            result = self.tr("Catalogue update failed: {0}").format(error_text(error))
        if self.store.limited_categories():
            result += " · " + self.tr("Catalogue incomplete: the Indexer stopped paging.")
        self.statusBar().showMessage(result, 15000)
        then, self._after_catalogue = self._after_catalogue, None
        always, self._after_catalogue_always = self._after_catalogue_always, None
        pending, self._pending_plan = self._pending_plan, None
        if then is not None and not stopped and error is None:
            then()
        if always is not None:
            always()  # e.g. a Plan: paused, it is made from the Catalogue fetched so far
        if pending is not None:
            if self.catalogue_runner is None:
                pending()
            else:
                self._pending_plan = pending

    def _show_catalogue_age(self) -> None:
        self.band.set_catalogue(self.catalogue_age())
        paused = self.store.crawl_paused()
        self.zen_tab.catalogue.set_state(False, paused)
        self.zen_tab.catalogue.set_status(
            self.catalogue_age()
            + (" · " + self.tr("whole-catalogue fetch paused") if paused else "")
            + (
                " · " + self.tr("Catalogue incomplete: the Indexer stopped paging.")
                if self.store.limited_categories()
                else ""
            )
            + (
                " · " + self.tr("Zen Lab snapshot imported; c411 data takes priority")
                if self.store.feed_state(SNAPSHOT_NAME).updated_at is not None
                else ""
            )
        )

    def catalogue_age(self) -> str:
        how_old = age(self.store.catalogue_updated_at(), time.time())
        if how_old is None:
            return self.tr("not fetched yet")
        amount, unit = how_old
        units = {"min": self.tr("{0} min"), "h": self.tr("{0} h"), "d": self.tr("{0} d")}
        return self.tr("{0} torrents, {1} old").format(
            self.store.catalogue_size(), units[unit].format(amount)
        )

    def closeEvent(self, event: QCloseEvent) -> None:
        self.search_tab.stop()
        self.seeding_timer.stop()
        self._pending_plan = None
        if self.catalogue_runner is not None:
            self.catalogue_runner.stop()
        if self.send_runner is not None:
            self.send_runner.stop()
        super().closeEvent(event)

    def seeding_loader(self) -> Callable[[], Seeding]:
        """Build on the GUI thread the work that reads the Seeding view from qBittorrent."""
        qbit, profile, url = self.qbit(), self.settings.zen, self.settings.indexer.url
        uploads = self.settings.uploads
        categories = dict(self.settings.indexer_categories)
        store = self.store

        def work() -> Seeding:
            torrents = qbit.torrents(with_files=False)
            cached = observe_swarm(store, torrents, url)
            view = seeding(profile, torrents, url, uploads, catalogue=cached, categories=categories)
            report = sync_category_tags(
                qbit, ((r.torrent, r.category) for r in view.rows), categories
            )
            if report.updated or report.failed:
                log.info(
                    "Category tags: %d updated, %d failed, %d unknown",
                    report.updated,
                    report.failed,
                    report.unknown,
                )
            return replace(view, tag_sync=report)

        return work

    def _uploads_changed(self, uploads: int) -> None:
        self.settings.uploads = uploads
        if self.settings_path.exists():
            self.settings.save(self.settings_path)

    def default_query(self, entry: LibraryEntry) -> str:
        kind = entry.folder.kind
        last = build_queries(entry.item, kind, (), find_ids(entry.item), None)[-1]
        return last.q

    def searcher(self) -> Searcher:
        """Build on the GUI thread a search function that workers can call safely."""
        indexer = self.indexer()
        tmdb_key = get_secret(TMDB_API_KEY)
        tmdb = Tmdb(tmdb_key) if tmdb_key else None
        categories = {k: self.settings.categories(k) for k in ContentKind}

        def search(entry: LibraryEntry, override: str | None) -> list[Candidate]:
            kind = entry.folder.kind
            return search_candidates(
                indexer,
                entry.item,
                kind,
                categories[kind],
                indexer.supported_modes(),
                tmdb,
                override,
            )

        return search

    def match_rules(self) -> MatchRules:
        return self.settings.matching.rules()

    def _open_upload(self, entry: LibraryEntry) -> None:
        self.tabs.setCurrentWidget(self.upload_tab)
        self.upload_tab.select(entry.item.path)

    def open_settings(self) -> None:
        folders = list(self.settings.library_folders)
        if SettingsDialog(self.settings, self).exec():
            self.settings.save(self.settings_path)
            log.info("settings written to %s", self.settings_path)
            self.apply_proxy()
            set_theme(self.settings.theme)
            self.search_tab.refresh_categories()
            self.search_tab.refresh_estimates()
            self._fill_folder_filter()
            self.offer_plan_categories()
            self.zen_tab.seeding_view.refresh()
            self.upload_tab.set_entries(self.upload_tab.entries)  # the Announce URL
            self.zen_tab.plan_view.keys = 1 + len(extra_indexer_keys())
            if self.settings.library_folders != folders:
                self.scan()  # a new folder, depth or Content Kind changes every entry
        else:
            log.info("settings dialog cancelled")

    def _fill_folder_filter(self) -> None:
        current = self.folder_filter.currentData()
        self.folder_filter.blockSignals(True)
        self.folder_filter.clear()
        self.folder_filter.addItem(self.tr("All Library Folders"), None)
        for f in self.settings.library_folders:
            self.folder_filter.addItem(str(f.path), f.path)
        index = self.folder_filter.findData(current)
        self.folder_filter.setCurrentIndex(max(index, 0))
        self.folder_filter.blockSignals(False)
        self._apply_filters()

    def _apply_filters(self) -> None:
        state = self.state_filter.currentData()  # Qt hands enum data back as plain str
        self.library_proxy.set_filters(
            ItemState(state) if state else None,
            self.folder_filter.currentData(),
            self.library_search.text(),
        )

    def selected_entries(self) -> list[LibraryEntry]:
        rows = self.library_view.selectionModel().selectedRows()
        return [self.library_proxy.data(r, Qt.ItemDataRole.UserRole) for r in rows]

    def _selection_changed(self, selected: QItemSelection, _deselected: QItemSelection) -> None:
        current = self.library_view.currentIndex()
        chosen = self.selected_entries()
        entry = None
        if current.isValid() and self.library_view.selectionModel().isRowSelected(
            current.row(), current.parent()
        ):
            entry = self.library_proxy.data(current.siblingAtColumn(0), Qt.ItemDataRole.UserRole)
        elif chosen:
            entry = chosen[0]
        if self.review.entry is not entry:
            self.review.set_entry(entry)

    # Batch search ----------------------------------------------------------

    def start_batch(self, selected_only: bool) -> None:
        if self.batch is not None:
            return
        pool = self.selected_entries() if selected_only else self.library_model.entries
        entries = auto_searchable(pool)
        if not entries:
            self.statusBar().showMessage(self.tr("No Orphans to search"))
            return
        rules, indexer, searcher, store = (
            self.match_rules(),
            self.indexer(),
            self.searcher(),
            self.store,
        )

        def search(entry: LibraryEntry) -> list[CheckedCandidate]:
            found = searcher(entry, store.item_query(entry.item.path))
            remember_candidates(store, indexer, entry.item.path, found)
            rejections = store.rejections(entry.item.path)
            return check_candidates(indexer, entry.item, found, rules, rejections)

        self.batch = BatchRunner(entries, search)
        self.batch.signals.searched.connect(self._batch_result)
        self.batch.signals.error.connect(self._batch_error)
        self.batch.signals.finished.connect(self._batch_finished)
        self._set_batch_running(True)
        self.batch_text = self.tr("Searching {0} Orphans…").format(len(entries))
        self.batch.start()

    def cancel_batch(self) -> None:
        if self.batch is not None:
            self.batch.cancel()
            self.batch_text = self.tr("Cancelling after the current item…")

    def _set_batch_running(self, running: bool) -> None:
        self.batch_selected_action.setEnabled(not running)
        self.batch_all_action.setEnabled(not running)
        self.cancel_action.setEnabled(running)
        if running:
            self.countdown.start()
        else:
            self.countdown.stop()

    def _show_batch_progress(self) -> None:
        wait = self._indexer.next_request_in() if self._indexer else 0
        suffix = self.tr(" · next request in {0} s").format(f"{wait:.1f}") if wait > 0.05 else ""
        self.statusBar().showMessage(self.batch_text + suffix)

    def _batch_result(
        self, index: int, total: int, entry: LibraryEntry, checked: list[CheckedCandidate]
    ) -> None:
        self.batch_text = self.tr("Searched {0}/{1}: {2}").format(
            index, total, entry.item.path.name
        )
        self.review.remember(entry, checked)
        self.library_model.set_status(entry.item.path, self._summary(checked))

    def _show_match_zen(self, entry: LibraryEntry, checked: list[CheckedCandidate]) -> None:
        seeding = self.zen_tab.seeding_view.seeding
        alongside = seeding.active if seeding else []
        self.library_model.set_zen(
            entry.item.path, match_zen(self.settings.zen, checked, alongside)
        )

    def _summary(self, checked: list[CheckedCandidate]) -> str:
        if any(v.match and v.match.is_full and not v.unpack for v in checked):
            return self.tr("Full match found")
        if any(v.match and v.match.is_full for v in checked):
            return self.tr("Full match inside the archive")
        if any(v.match for v in checked):
            return self.tr("Partial match found")
        if checked:
            return self.tr("No match")
        return self.tr("No Candidates")

    def _batch_error(self, entry: LibraryEntry, error: Exception) -> None:
        self.library_model.set_status(
            entry.item.path, self.tr("Search failed: {0}").format(error_text(error))
        )

    def _batch_finished(self, done: int) -> None:
        self.batch = None
        self._set_batch_running(False)
        self.statusBar().showMessage(self.tr("Batch search finished: {0} searched").format(done))

    def scan(self, refresh: bool = False) -> None:
        if not self.settings.library_folders:
            self.open_settings()
            return
        self.scan_action.setEnabled(False)
        self.rescan_action.setEnabled(False)
        self.statusBar().showMessage(self.tr("Scanning…"))
        folders = list(self.settings.library_folders)
        qbit, ignore, store = self.qbit(), self.settings.matching.ignore, self.store
        url = self.settings.indexer.url
        run_in_background(
            lambda: build_library(
                folders, indexer_contents(qbit, store, url), ignore, store, refresh
            ),
            self._scan_done,
            self._scan_failed,
        )

    def _scan_done(self, entries: list) -> None:  # type: ignore[type-arg]
        self.library_model.set_entries(entries)
        self.upload_tab.set_entries(entries)
        self.scan_action.setEnabled(True)
        self.rescan_action.setEnabled(True)
        self.statusBar().showMessage(self.tr("{0} Local Items").format(len(entries)))
        self.restore_searches(entries)

    def restore_searches(self, entries: list[LibraryEntry]) -> None:
        """Show each Local Item's last search again, from cached .torrent files only."""
        indexer, rules, store = self.indexer(), self.match_rules(), self.store
        searched = [e for e in entries if e.state is not ItemState.SEEDED]

        def work() -> list[tuple[LibraryEntry, list[CheckedCandidate]]]:
            restored = []
            for entry in searched:
                found = remembered_candidates(store, indexer, entry.item.path)
                if found is None:
                    continue
                rejections = store.rejections(entry.item.path)
                restored.append(
                    (entry, restore_checked(indexer, entry.item, found, rules, rejections))
                )
            return restored

        run_in_background(work, self._searches_restored, self._restore_failed)

    def _searches_restored(
        self, restored: list[tuple[LibraryEntry, list[CheckedCandidate]]]
    ) -> None:
        for entry, checked in restored:
            if entry in self.library_model.entries:
                self.review.remember(entry, checked)
                self.library_model.set_status(entry.item.path, self._summary(checked))

    def _restore_failed(self, error: Exception) -> None:
        log.warning("could not restore previous searches: %s", error)

    def _scan_failed(self, error: Exception) -> None:
        self.scan_action.setEnabled(True)
        self.rescan_action.setEnabled(True)
        self.statusBar().showMessage(self.tr("Scan failed"))
        QMessageBox.warning(self, self.tr("Scan failed"), str(error))

    # Verification ----------------------------------------------------------

    def _reseed_started(self, path: Path) -> None:
        self.library_model.set_status(path, self.tr("Verifying…"))
        self.verify_timer.start()

    def check_verifications(self) -> None:
        if self._checking:
            return
        self._checking = True
        qbit, store = self.qbit(), self.store

        def work() -> tuple[list[Outcome], list[Path]]:
            return check_verifications(qbit, store), pending_verifications(qbit, store)

        run_in_background(work, self._verified, self._verify_error)

    def _verified(self, result: tuple[list[Outcome], list[Path]]) -> None:
        self._checking = False
        outcomes, pending = result
        for outcome in outcomes:
            if outcome.verified and outcome.started:
                text = self.tr("Reseeded")
            elif outcome.verified:
                text = self.tr("Verified, left stopped: some files are absent")
            elif outcome.problem:
                text = self.tr("Reseed undone: {0}").format(outcome.problem)
            else:
                text = self.tr("Verification failed at {0}").format(f"{outcome.progress:.1%}")
            self.library_model.set_status(outcome.item_path, text)
        unpacked = [(o, self.store.take_unpacked(o.item_path)) for o in outcomes]
        for path in pending:
            self.library_model.set_status(path, self.tr("Verifying…"))
        if pending:
            self.verify_timer.start()
        else:
            self.verify_timer.stop()
        for outcome, archive in unpacked:
            if archive is not None and outcome.verified and outcome.started:
                self.offer_archive_removal(outcome.item_path, archive)

    def offer_archive_removal(self, folder: Path, archive: Path) -> None:
        """After an unpacked archive's Reseed is verified, offer to put the archive in the
        trash: its contents now seed from `folder` (ADR-0007)."""
        if not archive.is_file() or not folder.is_dir():
            return
        box = QMessageBox(
            QMessageBox.Icon.Question,
            self.tr("Unpack and Reseed"),
            self.tr(
                "{0} now seeds: your torrent client verified every file. They are the contents of "
                "{1}, so the archive ({2}) is no longer needed.\n\nMove it to the trash?"
            ).format(folder.name, archive.name, human_size(archive.stat().st_size)),
            parent=self,
        )
        trash = box.addButton(self.tr("Move to the trash"), QMessageBox.ButtonRole.AcceptRole)
        box.addButton(self.tr("Keep the archive"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is not trash:
            log.info("archive kept after unpacking: %s", archive)
            return
        if QFile.moveToTrash(str(archive)):
            log.info("archive moved to the trash after unpacking: %s", archive)
        else:
            answer = QMessageBox.question(
                self,
                self.tr("Unpack and Reseed"),
                self.tr(
                    "That disk has no trash. Delete {0} permanently? This cannot be undone."
                ).format(archive.name),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                log.info("archive kept, no trash on its disk: %s", archive)
                return
            archive.unlink()
            log.info("archive deleted after unpacking: %s", archive)
        self.statusBar().showMessage(self.tr("{0} removed").format(archive.name), 10000)
        self.scan()  # the archive leaves the Library

    def _verify_error(self, error: Exception) -> None:
        self._checking = False  # the timer keeps running: the next poll retries
        self.statusBar().showMessage(self.tr("Could not check Verifications: {0}").format(error))
