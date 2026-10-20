from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSortFilterProxyModel
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QMainWindow, QMessageBox, QTableView

from torrentlinker.config import Settings
from torrentlinker.credentials import get_secret
from torrentlinker.gui.library_model import LibraryModel
from torrentlinker.gui.settings_dialog import QBIT_PASSWORD, SettingsDialog
from torrentlinker.gui.tasks import run_in_background
from torrentlinker.library import build_library
from torrentlinker.qbit import QbitApi


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings, settings_path: Path) -> None:
        super().__init__()
        self.settings = settings
        self.settings_path = settings_path
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
        self.setCentralWidget(self.library_view)
        self.statusBar().showMessage(self.tr("Ready"))

    def qbit(self) -> QbitApi:
        q = self.settings.qbit
        return QbitApi(q.host, q.username, get_secret(QBIT_PASSWORD))

    def open_settings(self) -> None:
        if SettingsDialog(self.settings, self).exec():
            self.settings.save(self.settings_path)

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
