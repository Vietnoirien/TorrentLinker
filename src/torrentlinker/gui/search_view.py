"""Search the Indexer and build a persistent queue of selected downloads."""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlsplit

from PySide6.QtCore import QDateTime, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QShowEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from torrentlinker.category_tags import category_path
from torrentlinker.config import Settings
from torrentlinker.download_queue import QueueEntry, enqueue, entries, queue_key, run_queue
from torrentlinker.gui.browser_tabs import BrowserTabs
from torrentlinker.gui.category_picker import CategoryPicker
from torrentlinker.gui.errors import error_text
from torrentlinker.gui.library_model import human_size
from torrentlinker.gui.search_filters import SearchFilters
from torrentlinker.gui.send_runner import SendRunner
from torrentlinker.gui.settings_dialog import choose_directory
from torrentlinker.gui.tables import EmptyState, NumberItem, sortable_table
from torrentlinker.gui.tasks import run_in_background
from torrentlinker.gui.torrent_details import TorrentDetailsDialog
from torrentlinker.indexer import Candidate, Indexer, SearchQuery
from torrentlinker.qbit import Qbit
from torrentlinker.seeding import Seeding
from torrentlinker.send import SendProgress, SendReport
from torrentlinker.store import Store
from torrentlinker.torrent_details import website_url
from torrentlinker.torrent_search import SearchPage, native_search
from torrentlinker.zen import ZenTorrent, added_values, note

PAGE_SIZE = 100


class SearchTab(QWidget):
    def __init__(
        self,
        store: Store,
        settings: Settings,
        indexer: Callable[[], Indexer],
        client: Callable[[], Qbit],
    ) -> None:
        super().__init__()
        self.store, self.settings = store, settings
        self.indexer, self.client = indexer, client
        self.runner: SendRunner | None = None
        self._searching = False
        self._seeding: Seeding | None = None
        self._results: list[Candidate] = []
        self._offset = 0
        self._query = SearchQuery()
        self._native_params: dict[str, str] = {}
        self._native_page: SearchPage | None = None
        self._result_indexer: Indexer | None = None
        for entry in entries(store):
            if entry.status == "sending":
                store.download_outcome(entry.key, "queued")
        workspace = QVBoxLayout(self)
        workspace.setContentsMargins(0, 0, 0, 0)
        queue_access = QHBoxLayout()
        self.queue_notice = QLabel()
        self.queue_notice.setWordWrap(True)
        self.queue_notice.setTextFormat(Qt.TextFormat.PlainText)
        queue_access.addWidget(self.queue_notice, 1)
        self.view_queue = QPushButton()
        self.view_queue.clicked.connect(self.show_queue)
        queue_access.addWidget(self.view_queue)
        workspace.addLayout(queue_access)
        self.home = QWidget()
        self.browser = BrowserTabs(self.home)
        self.browser.close_requested.connect(self.close_detail)
        workspace.addWidget(self.browser)
        self._detail_tabs: dict[str, TorrentDetailsDialog] = {}
        layout = QVBoxLayout(self.home)
        layout.setContentsMargins(0, 8, 0, 0)
        search = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setPlaceholderText(self.tr("Search torrents by title…"))
        self.query.setAccessibleName(self.tr("Search torrents"))
        self.query.setClearButtonEnabled(True)
        self.query.setMaxLength(200)
        self.query.returnPressed.connect(lambda: self.search())
        self.category = CategoryPicker()
        self.category.setAccessibleName(self.tr("Category"))
        self.search_button = QPushButton(self.tr("Search"))
        self.search_button.setProperty("primary", True)
        self.search_button.clicked.connect(lambda: self.search())
        search.addWidget(self.query, 2)
        search.addWidget(self.category, 1)
        search.addWidget(self.search_button)
        layout.addLayout(search)
        self.filters = SearchFilters(self.category)
        layout.addWidget(self.filters)
        self.pages = QTabWidget()
        layout.addWidget(self.pages, 1)
        results_page = QWidget()
        results_layout = QVBoxLayout(results_page)
        results_layout.setContentsMargins(0, 0, 0, 0)
        self.results = self._table(
            [
                self.tr("Torrent"),
                self.tr("Size"),
                self.tr("Seeders"),
                self.tr("Category"),
                self.tr("Revival"),
                self.tr("≈ Zen/day"),
                self.tr("≈ Note"),
                self.tr("Age"),
            ]
        )
        for column, width in enumerate((420, 100, 80, 240, 150, 110, 90, 160)):
            self.results.setColumnWidth(column, width)
        self.results.horizontalHeader().moveSection(5, 3)
        self.results.horizontalHeader().moveSection(6, 4)
        self.results.horizontalHeader().moveSection(7, 3)
        published_header = self.results.horizontalHeaderItem(7)
        assert published_header is not None
        published_header.setToolTip(
            self.tr("Time since publication. Hover for the exact date. Sorts by publication time.")
        )
        self.results_empty = EmptyState(
            self.results, self.tr("Search for torrents, then select the ones to download.")
        )
        results_layout.addWidget(self.results, 1)
        self.result_status = QLabel()
        self.result_status.setWordWrap(True)
        self.result_status.setTextFormat(Qt.TextFormat.PlainText)
        results_layout.addWidget(self.result_status)
        paging = QHBoxLayout()
        self.previous = QPushButton(self.tr("Previous page"))
        self.next = QPushButton(self.tr("Next page"))
        self.previous.clicked.connect(lambda: self.search(max(0, self._offset - PAGE_SIZE)))
        self.next.clicked.connect(lambda: self.search(self._offset + PAGE_SIZE))
        paging.addWidget(self.previous)
        paging.addWidget(self.next)
        paging.addStretch()
        self.details_button = QPushButton(self.tr("Open in tabs"))
        self.details_button.clicked.connect(self.show_details)
        self.website_button = QPushButton(self.tr("Open on website"))
        self.website_button.clicked.connect(self.open_website)
        paging.addWidget(self.details_button)
        paging.addWidget(self.website_button)
        self.results.itemDoubleClicked.connect(self._open_result_item)
        results_layout.addLayout(paging)
        destination = QHBoxLayout()
        destination.addWidget(QLabel(self.tr("Download Folder")))
        self.folder = QLineEdit()
        self.folder.setPlaceholderText(self.tr("Use category folders from Settings"))
        self.folder.setAccessibleName(self.tr("Download Folder"))
        browse = QPushButton(self.tr("Browse…"))
        browse.clicked.connect(self._browse)
        self.add_button = QPushButton(self.tr("Add selected to queue"))
        self.add_button.clicked.connect(self.add_selected)
        destination.addWidget(self.folder, 1)
        destination.addWidget(browse)
        destination.addWidget(self.add_button)
        results_layout.addLayout(destination)
        tab_actions = QHBoxLayout()
        self.tab_count = QLabel()
        tab_actions.addWidget(self.tab_count, 1)
        self.queue_tabs = QPushButton(self.tr("Queue all tabs"))
        self.queue_tabs.setToolTip(
            self.tr("Queue the torrents in open tabs without starting downloads.")
        )
        self.queue_tabs.clicked.connect(lambda: self.queue_open_tabs(False))
        self.download_tabs = QPushButton(self.tr("Download all tabs"))
        self.download_tabs.setProperty("primary", True)
        self.download_tabs.setToolTip(
            self.tr("Download only the torrents in open tabs. Other queued torrents stay waiting.")
        )
        self.download_tabs.clicked.connect(lambda: self.queue_open_tabs(True))
        tab_actions.addWidget(self.queue_tabs)
        tab_actions.addWidget(self.download_tabs)
        results_layout.addLayout(tab_actions)
        self.pages.addTab(results_page, self.tr("Results"))
        queue_page = QWidget()
        queue_layout = QVBoxLayout(queue_page)
        queue_layout.setContentsMargins(0, 0, 0, 0)
        hint = QLabel(
            self.tr(
                "Start sends queued torrents to your torrent client. "
                "Pause stops further sends; existing downloads continue there."
            )
        )
        hint.setWordWrap(True)
        queue_layout.addWidget(hint)
        self.queue = self._table(
            [
                self.tr("Torrent"),
                self.tr("Size"),
                self.tr("≈ Zen/day"),
                self.tr("≈ Note"),
                self.tr("Download Folder"),
                self.tr("Status"),
                self.tr("Details"),
            ]
        )
        self.queue_empty = EmptyState(
            self.queue, self.tr("Your queue is empty. Add torrents from the search results.")
        )
        for column, width in enumerate((330, 100, 100, 90, 230, 140, 230)):
            self.queue.setColumnWidth(column, width)
        queue_layout.addWidget(self.queue, 1)
        controls = QHBoxLayout()
        self.start = QPushButton(self.tr("Start queue"))
        self.start.setProperty("primary", True)
        self.start.clicked.connect(lambda: self.start_queue())
        self.pause = QPushButton(self.tr("Pause"))
        self.pause.clicked.connect(self.stop)
        self.retry = QPushButton(self.tr("Retry selected"))
        self.retry.clicked.connect(self.retry_selected)
        self.remove = QPushButton(self.tr("Remove selected"))
        self.remove.clicked.connect(self.remove_selected)
        self.clear_done = QPushButton(self.tr("Clear sent"))
        self.clear_done.clicked.connect(self.clear_sent)
        for button in (self.start, self.pause, self.retry, self.remove, self.clear_done):
            controls.addWidget(button)
        controls.addStretch()
        queue_layout.addLayout(controls)
        self.queue_status = QLabel(self.tr("Queue saved. Press Start queue when ready."))
        self.queue_status.setTextFormat(Qt.TextFormat.PlainText)
        self.queue_status.setWordWrap(True)
        queue_layout.addWidget(self.queue_status)
        self.pages.addTab(queue_page, self.tr("Download queue"))
        self.results.itemSelectionChanged.connect(self._buttons)
        self.queue.itemSelectionChanged.connect(self._buttons)
        self.filters.ready_changed.connect(self._buttons)
        self.refresh_categories()
        self.refresh_queue()
        self.age_timer = QTimer(self)
        self.age_timer.setInterval(60_000)
        self.age_timer.timeout.connect(self.refresh_ages)
        self.age_timer.start()

    def _table(self, headings: list[str]) -> QTableWidget:
        table = QTableWidget(0, len(headings))
        table.setHorizontalHeaderLabels(headings)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        sortable_table(table)
        table.horizontalHeader().resizeSection(0, 380)
        return table

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._configure_filters()
        self.refresh_ages()

    def _configure_filters(self) -> Indexer | None:
        try:
            indexer = self.indexer()
            if not indexer.api_key:
                raise ValueError(self.tr("Set your Indexer API key in Settings first."))
            self.filters.configure(indexer)
            if not indexer.is_c411:
                self.category.set_categories(self.settings.indexer_categories)
            return indexer
        except Exception as error:
            self.result_status.setText(error_text(error))
            return None

    def refresh_categories(self) -> None:
        if self.filters.tree is None:
            self.category.set_categories(self.settings.indexer_categories)
        if self.isVisible():
            self._configure_filters()

    def search(self, offset: int | None = None) -> None:
        if self._searching:
            return
        indexer = self._configure_filters()
        if indexer is None or not self.filters.ready:
            return
        # A changed Indexer cannot page through the previous Indexer's results.
        if self._result_indexer is not None and self._result_indexer is not indexer:
            offset = None
        if offset is None:
            cid = self.category.current_category
            self._query = SearchQuery(
                self.query.text().strip(),
                categories=(cid,) if cid is not None else (),
                limit=PAGE_SIZE,
            )
            if indexer.is_c411:
                try:
                    self._native_params = self.filters.params(self.query.text().strip())
                except ValueError as error:
                    self.result_status.setText(str(error))
                    return
            offset = 0
        self._offset = offset
        from dataclasses import replace

        query = replace(self._query, offset=offset)
        self._searching = True
        self.result_status.setText(self.tr("Searching…"))
        self._buttons()
        if indexer.is_c411:
            params = dict(self._native_params)
            page = offset // PAGE_SIZE + 1
            run_in_background(
                lambda: native_search(indexer, params, page),
                lambda result: self._show_native(result, indexer),
                self._search_failed,
            )
        else:
            self._native_page = None
            run_in_background(
                lambda: indexer.search(query, cached=False),
                lambda rows: self._show_results(rows, indexer),
                self._search_failed,
            )

    def _show_native(self, page: SearchPage, indexer: Indexer) -> None:
        self._native_page = page
        self._offset = (page.page - 1) * PAGE_SIZE
        self._show_results(page.rows, indexer)
        message = self.tr("{0} results · {1} matches · page {2} of {3}").format(
            len(page.rows), page.total, page.page, max(1, page.total_pages)
        )
        if page.limited:
            message += " · " + self.tr(
                "c411 limits this search to {0} accessible results. Narrow your filters."
            ).format(page.per_page * page.total_pages)
        self.result_status.setText(message)

    def _search_failed(self, error: Exception) -> None:
        self._searching = False
        # Avoid offering paging against a new query whose request failed.
        self._results = []
        self._native_page = None
        self._offset = 0
        self.results.setRowCount(0)
        self.result_status.setText(error_text(error))
        self._buttons()

    def _show_results(self, rows: list[Candidate], indexer: Indexer) -> None:
        self._searching = False
        self._results, self._result_indexer = rows, indexer
        self.results.setSortingEnabled(False)
        self.results.setRowCount(len(rows))
        cats = self.settings.indexer_categories
        for row, c in enumerate(rows):
            item = QTableWidgetItem(c.title)
            item.setData(Qt.ItemDataRole.UserRole, row)
            item.setToolTip(c.title)
            self.results.setItem(row, 0, item)
            self.results.setItem(row, 1, NumberItem(human_size(c.size), c.size))
            self.results.setItem(row, 2, NumberItem(str(c.seeders), c.seeders))
            if c.published_at is not None:
                date = QDateTime.fromMSecsSinceEpoch(round(c.published_at * 1000)).toLocalTime()
                published = NumberItem(self._age(c.published_at, time.time()), c.published_at)
                published.setToolTip(date.toString("yyyy-MM-dd HH:mm:ss t"))
            else:
                published = NumberItem("–", float("-inf"))
                published.setToolTip(self.tr("Publication date unavailable."))
            self.results.setItem(row, 7, published)
            self.results.setItem(
                row,
                3,
                QTableWidgetItem(
                    self._native_page.labels.get(c.infohash or "", "")
                    if self._native_page
                    else " / ".join(
                        cats[cid].name if cid in cats else str(cid) for cid in c.categories
                    )
                ),
            )
            revival = bool(self._native_page and c.infohash in self._native_page.palliative)
            self.results.setItem(
                row, 4, QTableWidgetItem(self.tr("Soins palliatifs") if revival else "")
            )
        self.results.setSortingEnabled(True)
        self.result_status.setText(
            self.tr("{0} results · page {1}").format(len(rows), self._offset // PAGE_SIZE + 1)
        )
        self.pages.setCurrentIndex(0)
        self.refresh_estimates()
        self._buttons()

    def _age(self, published_at: float, now: float) -> str:
        seconds = now - published_at
        if seconds < -60:
            return self.tr("Future date")
        if seconds < 60:
            return self.tr("Just now")
        for unit, singular, plural in (
            (365 * 86400, self.tr("1 year"), self.tr("{0} years")),
            (30 * 86400, self.tr("1 month"), self.tr("{0} months")),
            (86400, self.tr("1 day"), self.tr("{0} days")),
            (3600, self.tr("1 hour"), self.tr("{0} hours")),
            (60, self.tr("1 minute"), self.tr("{0} minutes")),
        ):
            count = int(seconds // unit)
            if count:
                return singular if count == 1 else plural.format(count)
        return self.tr("Just now")

    def refresh_ages(self) -> None:
        if not self.isVisible():
            return
        now = time.time()
        # Keep the stored timestamp, selection and ordering while refreshing labels.
        self.results.setSortingEnabled(False)
        for row in range(self.results.rowCount()):
            item = self.results.item(row, 7)
            if item is not None:
                timestamp = item.data(Qt.ItemDataRole.UserRole)
                if timestamp != float("-inf"):
                    item.setText(self._age(timestamp, now))
        self.results.setSortingEnabled(True)

    def set_seeding(self, view: Seeding) -> None:
        self._seeding = view
        self.refresh_estimates()

    def refresh_estimates(self) -> None:
        indexer = self._result_indexer
        if indexer is not None:
            self._refresh_table_estimates(
                self.results,
                {i: (candidate, indexer.is_c411) for i, candidate in enumerate(self._results)},
                5,
                6,
            )
        self._refresh_queue_estimates()

    def _refresh_queue_estimates(self) -> None:
        # Use each saved origin, before any search and after changing Indexers.
        self._refresh_table_estimates(
            self.queue,
            {
                entry.key: (entry.candidate, urlsplit(entry.indexer_url).hostname == "c411.org")
                for entry in entries(self.store)
            },
            2,
            3,
        )

    def _refresh_table_estimates(
        self,
        table: QTableWidget,
        candidates: dict[int | str, tuple[Candidate, bool]],
        zen_column: int,
        note_column: int,
    ) -> None:
        alongside = self._seeding.active if self._seeding else []
        current = (
            {row.torrent.hash.lower(): row.zen for row in self._seeding.rows if row.zen is not None}
            if self._seeding
            else {}
        )
        current_notes = (
            {
                row.torrent.hash.lower(): note(self.settings.zen.zen_class, torrent)
                for row, torrent in zip(
                    (row for row in self._seeding.rows if row.zen is not None),
                    self._seeding.active,
                    strict=True,
                )
            }
            if self._seeding
            else {}
        )
        prospective = {
            identity: ZenTorrent(
                c.size, c.seeders + 1, category=c.categories[-1] if c.categories else None
            )
            for identity, (c, _) in candidates.items()
        }
        values = dict(
            zip(
                candidates,
                added_values(self.settings.zen, list(prospective.values()), alongside),
                strict=True,
            )
        )
        table.setSortingEnabled(False)
        for row in range(table.rowCount()):
            title = table.item(row, 0)
            if title is None:
                continue
            identity = title.data(Qt.ItemDataRole.UserRole)
            candidate, is_c411 = candidates[identity]
            existing = current.get((candidate.infohash or "").lower())
            value = existing if existing is not None else values[identity]
            if not is_c411:
                item = NumberItem("–", float("-inf"))
                tooltip = self.tr("Zen estimates are available for c411 torrents.")
            else:
                item = NumberItem(f"≈ {value:.2f}", value)
                tooltip = (
                    self.tr("Already seeding: current Zen Estimate, including your seed age.")
                    if existing is not None
                    else self.tr(
                        "Estimated once downloaded and seeding, starting at zero seed age. "
                        "Swarm includes you."
                    )
                )
                tooltip += "\n" + self.tr(
                    "Uses your Zen Profile and {0} seed hours/day. Revival payouts are separate."
                ).format(self.settings.zen.seed_hours)
                if self._seeding is None:
                    tooltip += "\n" + self.tr(
                        "Current seeding count unavailable; Class count bonus is provisional."
                    )
            item.setToolTip(tooltip)
            table.setItem(row, zen_column, item)
            torrent_note = current_notes.get(
                (candidate.infohash or "").lower(),
                note(self.settings.zen.zen_class, prospective[identity]),
            )
            note_item = (
                NumberItem(f"≈ {torrent_note:.2f}", torrent_note)
                if is_c411
                else NumberItem("–", float("-inf"))
            )
            note_item.setToolTip(
                self.tr("Estimated contribution note for your Class, category, swarm and seed age.")
                + "\n"
                + tooltip
                if is_c411
                else tooltip
            )
            table.setItem(row, note_column, note_item)
        table.setSortingEnabled(True)

    def open_website(self) -> None:
        selected = self.selected_results()
        if len(selected) == 1 and self._result_indexer:
            url = website_url(selected[0], self._result_indexer)
            if url:
                QDesktopServices.openUrl(QUrl(url))

    def focus_search(self) -> None:
        self.browser.setCurrentWidget(self.home)
        self.pages.setCurrentIndex(0)
        self.query.setFocus()
        self.query.selectAll()

    def show_queue(self) -> None:
        self.browser.setCurrentWidget(self.home)
        self.pages.setCurrentIndex(1)

    def _open_result_item(self, clicked: QTableWidgetItem) -> None:
        item = self.results.item(clicked.row(), 0)
        if item is not None:
            self.open_details(self._results[item.data(Qt.ItemDataRole.UserRole)])

    def show_details(self) -> None:
        for candidate in self.selected_results():
            self.open_details(candidate)

    def open_details(self, candidate: Candidate) -> None:
        indexer = self._result_indexer
        if indexer is None:
            return
        key = queue_key(indexer, candidate)
        existing = self._detail_tabs.get(key)
        if existing is not None:
            self.browser.setCurrentWidget(existing)
            return
        estimate = None
        torrent_note = None
        for row in range(self.results.rowCount()):
            item = self.results.item(row, 0)
            if item and self._results[item.data(Qt.ItemDataRole.UserRole)] == candidate:
                estimate = self.results.item(row, 5)
                torrent_note = self.results.item(row, 6)
                break
        page = TorrentDetailsDialog(
            candidate,
            indexer,
            estimate.text() if estimate else "–",
            estimate.toolTip() if estimate else "",
            self,
            download=lambda folder, now: self.download_candidate(candidate, indexer, folder, now),
            folder=str(self._download_folder(candidate) or ""),
            embedded=True,
            torrent_note=torrent_note.text() if torrent_note else "–",
        )
        page.close_requested.connect(lambda: self.close_detail(page))
        self._detail_tabs[key] = page
        self.browser.add_preview(page, candidate.title)
        self.browser.setCurrentWidget(page)
        self._buttons()

    def close_detail(self, page: QWidget) -> None:
        if not isinstance(page, TorrentDetailsDialog):
            return
        key = queue_key(page.indexer, page.candidate)
        self._detail_tabs.pop(key, None)
        self.browser.removeTab(self.browser.indexOf(page))
        page.dispose()
        self._buttons()

    def queue_open_tabs(self, now: bool) -> None:
        pages = [self.browser.widget(i) for i in range(self.browser.count())]
        details = [page for page in pages if isinstance(page, TorrentDetailsDialog)]
        if not details:
            return
        # Validate the entire selection before writing anything to the queue.
        prepared = []
        for page in details:
            try:
                prepared.append(
                    (
                        page,
                        self._prepare_download(
                            page.candidate, page.indexer, page.folder.text().strip()
                        ),
                    )
                )
            except Exception as error:
                message = error_text(error)
                page.action_status.setText(message)
                self.result_status.setText(message)
                self.queue_notice.setText(self.tr("Could not queue tabs: {0}").format(message))
                self.browser.setCurrentWidget(page)
                page.folder.setFocus()
                return
        added = 0
        pending: set[str] = set()
        for page, (indexer, destination, key, existing) in prepared:
            if existing and existing.status == "sent":
                page.action_status.setText(self.tr("Already sent to the torrent client."))
                continue
            added += enqueue(self.store, indexer, page.candidate, destination)
            if now:
                self.store.download_outcome(key, "queued")
                pending.add(key)
            page.action_status.setText(
                self.tr("Added to queue.") if existing is None else self.tr("Already in the queue.")
            )
        self.refresh_queue()
        message = self.tr("{0} added to the queue; {1} already listed.").format(
            added, len(details) - added
        )
        self.result_status.setText(message)
        self.queue_notice.setText(message)
        self.queue_status.setText(
            message + " " + self.tr("Queue saved. Press Start queue when ready.")
        )
        self.show_queue()
        if now and pending:
            self.start_queue(only=pending)

    def _browse(self) -> None:
        folder = choose_directory(self, self.tr("Download Folder"), self.folder.text())
        if folder:
            self.folder.setText(folder)

    def selected_results(self) -> list[Candidate]:
        return [
            self._results[item.data(Qt.ItemDataRole.UserRole)]
            for i in self.results.selectionModel().selectedRows()
            if (item := self.results.item(i.row(), 0)) is not None
        ]

    def _download_folder(self, candidate: Candidate) -> Path | None:
        cats = self.settings.indexer_categories
        cid = max(
            candidate.categories, key=lambda value: len(category_path(value, cats)), default=0
        )
        return (
            Path(self.folder.text().strip()).expanduser()
            if self.folder.text().strip()
            else self.settings.download_folders.resolve(cid, cats)
        )

    def _prepare_download(
        self, candidate: Candidate, indexer: Indexer, folder: str
    ) -> tuple[Indexer, Path, str, QueueEntry | None]:
        if self.runner:
            raise ValueError(
                self.tr(
                    "A queue send is running. Wait or pause it before starting another download."
                )
            )
        current = self.indexer()
        if current.url != indexer.url:
            raise ValueError(
                self.tr("The Indexer changed. Search again before downloading this torrent.")
            )
        if not candidate.download_url:
            raise ValueError(self.tr("This torrent has no download link."))
        key = queue_key(indexer, candidate)
        existing = next((entry for entry in entries(self.store) if entry.key == key), None)
        if existing and existing.status == "sent":
            return current, existing.folder, key, existing
        destination = Path(folder).expanduser() if folder else None
        if destination is None or not destination.is_dir():
            raise ValueError(self.tr("Choose an accessible Download Folder."))
        destination = destination.resolve()
        if existing and existing.status != "sent" and existing.folder != destination:
            raise ValueError(
                self.tr(
                    "This torrent is already queued to {0}. Remove that entry to change its folder."
                ).format(existing.folder)
            )
        return current, destination, key, existing

    def download_candidate(
        self, candidate: Candidate, indexer: Indexer, folder: str, now: bool
    ) -> str:
        current, destination, key, existing = self._prepare_download(candidate, indexer, folder)
        if existing and existing.status == "sent":
            return self.tr("Already sent to the torrent client.")
        added = enqueue(self.store, current, candidate, destination)
        if now:
            self.store.download_outcome(key, "queued")
            self.refresh_queue()
            if not self.start_queue(only={key}):
                return self.queue_status.text()
            return self.tr("Download started. See Download queue for progress.")
        self.refresh_queue()
        if existing and existing.status in {"failed", "refused"}:
            return self.tr(
                "Already listed with an error. Use Download now to retry, or review Download queue."
            )
        return self.tr("Added to queue.") if added else self.tr("Already in the queue.")

    def add_selected(self) -> None:
        indexer = self._result_indexer
        if indexer is None or self.runner:
            return
        chosen = self.selected_results()
        destinations = []
        for c in chosen:
            folder = self._download_folder(c)
            if folder is None or not folder.is_dir():
                self.result_status.setText(
                    self.tr(
                        "Choose an accessible Download Folder, "
                        "or configure category folders in Settings."
                    )
                )
                return
            if not c.download_url:
                self.result_status.setText(self.tr("This torrent has no download link."))
                return
            destinations.append((c, folder.resolve()))
        added = sum(enqueue(self.store, indexer, c, folder) for c, folder in destinations)
        self.result_status.setText(
            self.tr("{0} added to the queue; {1} already listed.").format(
                added, len(chosen) - added
            )
        )
        self.refresh_queue()

    def selected_keys(self) -> list[str]:
        return [
            item.data(Qt.ItemDataRole.UserRole)
            for i in self.queue.selectionModel().selectedRows()
            if (item := self.queue.item(i.row(), 0)) is not None
        ]

    def refresh_queue(self) -> None:
        selected = set(self.selected_keys())
        rows = entries(self.store)
        labels = {
            "queued": self.tr("Queued"),
            "sending": self.tr("Sending…"),
            "sent": self.tr("Sent to client"),
            "failed": self.tr("Failed"),
            "refused": self.tr("Skipped"),
        }
        self.queue.blockSignals(True)
        self.queue.setSortingEnabled(False)
        self.queue.setRowCount(len(rows))
        for row, entry in enumerate(rows):
            item = QTableWidgetItem(entry.candidate.title)
            item.setData(Qt.ItemDataRole.UserRole, entry.key)
            self.queue.setItem(row, 0, item)
            self.queue.setItem(
                row, 1, NumberItem(human_size(entry.candidate.size), entry.candidate.size)
            )
            self.queue.setItem(row, 2, QTableWidgetItem())
            self.queue.setItem(row, 3, QTableWidgetItem())
            self.queue.setItem(row, 4, QTableWidgetItem(str(entry.folder)))
            self.queue.setItem(row, 5, QTableWidgetItem(labels.get(entry.status, entry.status)))
            self.queue.setItem(row, 6, QTableWidgetItem(entry.reason))
            for column in range(7):
                cell = self.queue.item(row, column)
                assert cell is not None
                cell.setSelected(entry.key in selected)
                cell.setToolTip(cell.text())
        self._refresh_queue_estimates()
        self.queue.blockSignals(False)
        count = sum(e.status == "queued" for e in rows)
        self.pages.setTabText(1, self.tr("Download queue ({0})").format(count))
        self.view_queue.setText(self.tr("Download queue ({0})").format(count))
        self._buttons()

    def start_queue(self, *, only: set[str] | None = None) -> bool:
        if self.runner:
            return False
        try:
            indexer, client = self.indexer(), self.client()
            if not indexer.api_key:
                raise ValueError(self.tr("Set your Indexer API key in Settings first."))
        except Exception as error:
            self.queue_status.setText(error_text(error))
            return False
        categories = dict(self.settings.indexer_categories)
        self.runner = SendRunner(
            lambda stop, progress: run_queue(
                self.store, indexer, client, categories, stop, progress, only=only
            )
        )
        self.runner.signals.progress.connect(self._progress)
        self.runner.signals.finished.connect(self._finished)
        self.runner.signals.failed.connect(self._failed)
        self._buttons()
        self.runner.start()
        return True

    def _progress(self, progress: SendProgress) -> None:
        self.refresh_queue()
        message = self.tr("{0}/{1} processed · {2}").format(
            progress.done, progress.total, progress.title
        )
        if progress.retry_at:
            message += self.tr(" · waiting until {0}").format(
                time.strftime("%H:%M:%S", time.localtime(progress.retry_at))
            )
        self.queue_status.setText(message)

    def _finished(self, report: SendReport) -> None:
        self.runner = None
        self.refresh_queue()
        self.queue_status.setText(
            self.tr("{0} sent · {1} skipped · {2} failed").format(
                len(report.added), len(report.refused), len(report.failed)
            )
        )

    def _failed(self, error: Exception) -> None:
        self.runner = None
        for entry in entries(self.store):
            if entry.status == "sending":
                self.store.download_outcome(entry.key, "queued")
        self.refresh_queue()
        self.queue_status.setText(error_text(error))

    def stop(self) -> None:
        if self.runner:
            self.runner.stop()
            self.pause.setEnabled(False)
            self.queue_status.setText(self.tr("Pausing after the current request…"))

    def retry_selected(self) -> None:
        if self.runner:
            return
        selected = set(self.selected_keys())
        for entry in entries(self.store):
            if entry.key in selected and entry.status in ("failed", "refused"):
                self.store.download_outcome(entry.key, "queued")
        self.refresh_queue()

    def remove_selected(self) -> None:
        if not self.runner:
            self.store.remove_downloads(self.selected_keys())
            self.refresh_queue()

    def clear_sent(self) -> None:
        if not self.runner:
            self.store.remove_downloads([e.key for e in entries(self.store) if e.status == "sent"])
            self.refresh_queue()

    def _buttons(self) -> None:
        busy = self.runner is not None
        can_search = not self._searching and self.filters.ready
        self.search_button.setEnabled(can_search)
        self.previous.setEnabled(can_search and self._offset > 0)
        more = self._native_page.has_more if self._native_page else len(self._results) == PAGE_SIZE
        self.next.setEnabled(can_search and more)
        selected_results = self.selected_results()
        one = len(selected_results) == 1 and not self._searching
        self.details_button.setEnabled(bool(selected_results) and not self._searching)
        count = len(self._detail_tabs)
        self.tab_count.setText(self.tr("{0} torrent tabs open").format(count))
        self.queue_tabs.setEnabled(count > 0 and not busy)
        self.download_tabs.setEnabled(count > 0 and not busy)
        self.website_button.setEnabled(
            bool(
                one
                and self._result_indexer
                and website_url(selected_results[0], self._result_indexer)
            )
        )
        self.add_button.setEnabled(
            not busy and not self._searching and bool(self.results.selectionModel().selectedRows())
        )
        self.start.setEnabled(not busy and any(e.status == "queued" for e in entries(self.store)))
        self.pause.setEnabled(busy)
        selected = bool(self.queue.selectionModel().selectedRows())
        self.retry.setEnabled(not busy and selected)
        self.remove.setEnabled(not busy and selected)
        self.clear_done.setEnabled(not busy)
