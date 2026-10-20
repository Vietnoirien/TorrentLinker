from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QItemSelection, QSortFilterProxyModel, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QTableView,
)

from torrentlinker.config import Settings
from torrentlinker.credentials import get_secret
from torrentlinker.gui.library_model import LibraryModel
from torrentlinker.gui.review_panel import ReviewPanel
from torrentlinker.gui.settings_dialog import INDEXER_API_KEY, QBIT_PASSWORD, SettingsDialog
from torrentlinker.gui.tasks import run_in_background
from torrentlinker.indexer import Indexer
from torrentlinker.library import build_library
from torrentlinker.qbit import QbitApi
from torrentlinker.store import Store


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings, settings_path: Path, store: Store) -> None:
        super().__init__()
        self.settings = settings
        self.settings_path = settings_path
        self.store = store
        self._indexer: Indexer | None = None
        self.setWindowTitle("TorrentLinker")
        self.resize(1200, 720)

        toolbar = self.addToolBar(self.tr("Main"))
        self.scan_action = QAction(self.tr("Scan"), self)
        self.scan_action.triggered.connect(self.scan)
        settings_action = QAction(self.tr("Settings"), self)
        settings_action.triggered.connect(self.open_settings)
        toolbar.addAction(self.scan_action)
        toolbar.addAction(settings_action)

        self.library_model = LibraryModel()
        self.library_proxy = QSortFilterProxyModel()
        self.library_proxy.setSourceModel(self.library_model)
        self.library_view = QTableView()
        self.library_view.setModel(self.library_proxy)
        self.library_view.setSortingEnabled(True)
        self.library_view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.library_view.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.library_view.selectionModel().selectionChanged.connect(self._selection_changed)

        self.review = ReviewPanel(store, self.indexer)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.library_view)
        splitter.addWidget(self.review)
        splitter.setSizes([600, 600])
        self.setCentralWidget(splitter)
        self.statusBar().showMessage(self.tr("Ready"))

    def qbit(self) -> QbitApi:
        q = self.settings.qbit
        return QbitApi(q.host, q.username, get_secret(QBIT_PASSWORD))

    def indexer(self) -> Indexer:
        """One Indexer instance, so every search shares the same rate limiter."""
        url, key = self.settings.indexer.url, get_secret(INDEXER_API_KEY)
        if self._indexer is None or (self._indexer.url, self._indexer.api_key) != (url, key):
            self._indexer = Indexer(url, key, cache=self.store)
        return self._indexer

    def open_settings(self) -> None:
        if SettingsDialog(self.settings, self).exec():
            self.settings.save(self.settings_path)

    def _selection_changed(self, selected: QItemSelection, _deselected: QItemSelection) -> None:
        rows = self.library_view.selectionModel().selectedRows()
        entry = self.library_proxy.data(rows[0], Qt.ItemDataRole.UserRole) if rows else None
        self.review.set_entry(entry)

    def scan(self) -> None:
        if not self.settings.library_folders:
            self.open_settings()
            return
        self.scan_action.setEnabled(False)
        self.statusBar().showMessage(self.tr("Scanning…"))
        folders = list(self.settings.library_folders)
        qbit = self.qbit()
        run_in_background(
            lambda: build_library(folders, qbit.torrents()),
            self._scan_done,
            self._scan_failed,
        )

    def _scan_done(self, entries: list) -> None:  # type: ignore[type-arg]
        self.library_model.set_entries(entries)
        self.scan_action.setEnabled(True)
        self.statusBar().showMessage(self.tr("{0} Local Items").format(len(entries)))

    def _scan_failed(self, error: Exception) -> None:
        self.scan_action.setEnabled(True)
        self.statusBar().showMessage(self.tr("Scan failed"))
        QMessageBox.warning(self, self.tr("Scan failed"), str(error))
