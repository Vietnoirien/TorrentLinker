from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QItemSelection, Qt, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QTableView,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from torrentlinker.config import Settings
from torrentlinker.credentials import get_secret
from torrentlinker.domain import ContentKind, ItemState
from torrentlinker.gui.batch_runner import BatchRunner
from torrentlinker.gui.library_model import LibraryFilter, LibraryModel, state_label
from torrentlinker.gui.review_panel import ReviewPanel, Searcher
from torrentlinker.gui.settings_dialog import (
    INDEXER_API_KEY,
    QBIT_API_KEY,
    QBIT_PASSWORD,
    TMDB_API_KEY,
    SettingsDialog,
)
from torrentlinker.gui.tasks import run_in_background
from torrentlinker.gui.zen_view import ZenBand, ZenTab
from torrentlinker.indexer import Candidate, Indexer
from torrentlinker.library import LibraryEntry, auto_searchable, build_library
from torrentlinker.matching import MatchRules
from torrentlinker.paths import MappedQbit, PathMapper
from torrentlinker.profile import ProfileClient, UserProfile
from torrentlinker.qbit import QbitApi
from torrentlinker.queries import build_queries, find_ids
from torrentlinker.reseed import Outcome, check_verifications, pending_verifications
from torrentlinker.review import CheckedCandidate, check_candidates, search_candidates
from torrentlinker.seeding import Seeding, seeding
from torrentlinker.store import Store
from torrentlinker.tmdb import Tmdb

log = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings, settings_path: Path, store: Store) -> None:
        super().__init__()
        self.settings = settings
        self.settings_path = settings_path
        self.store = store
        self._indexer: Indexer | None = None
        self._profile: tuple[tuple[str, str], ProfileClient] | None = None
        self._qbit: tuple[tuple[str, str, str, str], QbitApi] | None = None
        self.setWindowTitle("TorrentLinker")
        self.resize(1200, 720)

        toolbar = self.addToolBar(self.tr("Main"))
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
        toolbar.addAction(self.scan_action)
        toolbar.addAction(self.rescan_action)
        toolbar.addSeparator()
        toolbar.addAction(self.batch_selected_action)
        toolbar.addAction(self.batch_all_action)
        toolbar.addAction(self.cancel_action)
        toolbar.addSeparator()
        toolbar.addAction(settings_action)
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
        self.library_view.setSortingEnabled(True)
        self.library_view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.library_view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        header = self.library_view.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        header.resizeSection(3, 160)
        self.library_view.selectionModel().selectionChanged.connect(self._selection_changed)

        filters = QHBoxLayout()
        self.state_filter = QComboBox()
        self.state_filter.addItem(self.tr("All states"), None)
        for state in ItemState:
            self.state_filter.addItem(state_label(state), state)
        self.folder_filter = QComboBox()
        self.state_filter.currentIndexChanged.connect(self._apply_filters)
        self.folder_filter.currentIndexChanged.connect(self._apply_filters)
        filters.addWidget(QLabel(self.tr("Show")))
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
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(library_pane)
        splitter.addWidget(self.review)
        splitter.setSizes([600, 600])
        self.zen_tab = ZenTab(self.seeding_loader)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.zen_tab, self.tr("Zen"))
        self.tabs.addTab(splitter, self.tr("Library"))
        self.band = ZenBand()
        self.band.refresh_requested.connect(self.refresh_profile)
        self.zen_tab.seeding_view.updated.connect(self.band.set_seeding)
        central = QWidget()
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.addWidget(self.band)
        central_layout.addWidget(self.tabs)
        self.setCentralWidget(central)
        self.statusBar().showMessage(self.tr("Ready"))

        self._checking = False
        self.verify_timer = QTimer(self)
        self.verify_timer.setInterval(3000)
        self.verify_timer.timeout.connect(self.check_verifications)
        if settings_path.exists():
            QTimer.singleShot(0, self.check_verifications)  # settle Reseeds from a past session
            QTimer.singleShot(0, self.zen_tab.seeding_view.refresh)
            QTimer.singleShot(0, self.refresh_profile)

    def qbit(self) -> MappedQbit:
        q = self.settings.qbit
        key = (q.host, q.username, get_secret(QBIT_PASSWORD), get_secret(QBIT_API_KEY))
        if self._qbit is None or self._qbit[0] != key:
            self._qbit = (key, QbitApi(*key))
        mappings = [f.mapping for f in self.settings.library_folders if f.mapping]
        return MappedQbit(self._qbit[1], PathMapper(mappings))

    def indexer(self) -> Indexer:
        """One Indexer instance, so every search shares the same rate limiter.

        Only call on the GUI thread; workers get the instance passed in.
        """
        url, key = self.settings.indexer.url, get_secret(INDEXER_API_KEY)
        if self._indexer is None or (self._indexer.url, self._indexer.api_key) != (url, key):
            self._indexer = Indexer(url, key, cache=self.store)
        return self._indexer

    def profile_client(self) -> ProfileClient:
        """One client, so its 30-second freshness window holds across refreshes."""
        wanted = (self.settings.indexer.url, get_secret(INDEXER_API_KEY))
        if self._profile is None or self._profile[0] != wanted:
            self._profile = (wanted, ProfileClient(*wanted))
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

    def seeding_loader(self) -> Callable[[], Seeding]:
        """Build on the GUI thread the work that reads the Seeding view from qBittorrent."""
        qbit, profile, url = self.qbit(), self.settings.zen, self.settings.indexer.url
        return lambda: seeding(profile, qbit.torrents(with_files=False), url)

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

    def open_settings(self) -> None:
        if SettingsDialog(self.settings, self).exec():
            self.settings.save(self.settings_path)
            log.info("settings written to %s", self.settings_path)
            self._fill_folder_filter()
            self.zen_tab.seeding_view.refresh()
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
            ItemState(state) if state else None, self.folder_filter.currentData()
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

    def _summary(self, checked: list[CheckedCandidate]) -> str:
        if any(v.match and v.match.is_full for v in checked):
            return self.tr("Full match found")
        if any(v.match for v in checked):
            return self.tr("Partial match found")
        if checked:
            return self.tr("No match")
        return self.tr("No Candidates")

    def _batch_error(self, entry: LibraryEntry, error: Exception) -> None:
        self.library_model.set_status(entry.item.path, self.tr("Search failed: {0}").format(error))

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
        run_in_background(
            lambda: build_library(folders, qbit.torrents(), ignore, store, refresh),
            self._scan_done,
            self._scan_failed,
        )

    def _scan_done(self, entries: list) -> None:  # type: ignore[type-arg]
        self.library_model.set_entries(entries)
        self.scan_action.setEnabled(True)
        self.rescan_action.setEnabled(True)
        self.statusBar().showMessage(self.tr("{0} Local Items").format(len(entries)))

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
            else:
                text = self.tr("Verification failed at {0}").format(f"{outcome.progress:.1%}")
            self.library_model.set_status(outcome.item_path, text)
        for path in pending:
            self.library_model.set_status(path, self.tr("Verifying…"))
        if pending:
            self.verify_timer.start()
        else:
            self.verify_timer.stop()

    def _verify_error(self, error: Exception) -> None:
        self._checking = False  # the timer keeps running: the next poll retries
        self.statusBar().showMessage(self.tr("Could not check Verifications: {0}").format(error))
