from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from torrentlinker.gui.library_model import human_size
from torrentlinker.gui.tasks import run_in_background
from torrentlinker.indexer import Candidate, Indexer, SearchQuery
from torrentlinker.library import LibraryEntry
from torrentlinker.queries import name_query
from torrentlinker.store import Store


class ReviewPanel(QWidget):
    """Candidates for the selected Orphan."""

    def __init__(self, store: Store, indexer: Callable[[], Indexer]) -> None:
        super().__init__()
        self.store = store
        self.indexer = indexer
        self.entry: LibraryEntry | None = None
        self.candidates: list[Candidate] = []

        layout = QVBoxLayout(self)
        self.title = QLabel(self.tr("Select a Local Item"))
        self.title.setWordWrap(True)
        layout.addWidget(self.title)

        row = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setPlaceholderText(self.tr("Search query"))
        self.query.returnPressed.connect(self.search)
        self.search_button = QPushButton(self.tr("Search"))
        self.search_button.clicked.connect(self.search)
        row.addWidget(self.query)
        row.addWidget(self.search_button)
        layout.addLayout(row)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(
            [self.tr("Candidate"), self.tr("Size"), self.tr("Seeders")]
        )
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table)
        self.set_entry(None)

    def set_entry(self, entry: LibraryEntry | None) -> None:
        self.entry = entry
        self.candidates = []
        self.table.setRowCount(0)
        enabled = entry is not None
        self.query.setEnabled(enabled)
        self.search_button.setEnabled(enabled)
        if entry is None:
            self.title.setText(self.tr("Select a Local Item"))
            self.query.clear()
            return
        self.title.setText(f"<b>{entry.item.path.name}</b> — {human_size(entry.item.size)}")
        self.query.setText(self.store.item_query(entry.item.path) or name_query(entry.item))

    def search(self) -> None:
        if self.entry is None:
            return
        entry = self.entry
        q = self.query.text().strip()
        if q != name_query(entry.item):
            self.store.set_item_query(entry.item.path, q)
        self.search_button.setEnabled(False)
        indexer = self.indexer()
        run_in_background(
            lambda: indexer.search(SearchQuery(q=q)),
            lambda result: self._show(entry, result),
            self._failed,
        )

    def _show(self, entry: LibraryEntry, candidates: list[Candidate]) -> None:
        self.search_button.setEnabled(True)
        if entry is not self.entry:
            return
        self.candidates = candidates
        self.table.setRowCount(len(candidates))
        for r, c in enumerate(candidates):
            self.table.setItem(r, 0, QTableWidgetItem(c.title))
            self.table.setItem(r, 1, QTableWidgetItem(human_size(c.size)))
            self.table.setItem(r, 2, QTableWidgetItem(str(c.seeders)))
        if not candidates:
            self.title.setText(self.title.text() + "<br>" + self.tr("No Candidates found"))

    def _failed(self, error: Exception) -> None:
        self.search_button.setEnabled(True)
        QMessageBox.warning(self, self.tr("Search failed"), str(error))
