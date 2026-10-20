from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from torrentlinker.gui.library_model import human_size
from torrentlinker.gui.tasks import run_in_background
from torrentlinker.indexer import Indexer, SearchQuery
from torrentlinker.library import LibraryEntry
from torrentlinker.queries import name_query
from torrentlinker.review import Verified, verify, verify_one
from torrentlinker.store import Store

GREEN, ORANGE, RED = QColor("#2e7d32"), QColor("#ef6c00"), QColor("#c62828")


def _readonly_table(headers: list[str]) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.verticalHeader().setVisible(False)
    return table


class ReviewPanel(QWidget):
    """Candidates for the selected Orphan, and how a Candidate's files line up locally."""

    def __init__(
        self, store: Store, indexer: Callable[[], Indexer], tolerance: Callable[[], float]
    ) -> None:
        super().__init__()
        self.store = store
        self.indexer = indexer
        self.tolerance = tolerance
        self.entry: LibraryEntry | None = None
        self.results: list[Verified] = []

        layout = QVBoxLayout(self)
        self.title = QLabel()
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

        self.candidates = _readonly_table(
            [self.tr("Candidate"), self.tr("Size"), self.tr("Seeders"), self.tr("Match")]
        )
        self.candidates.itemSelectionChanged.connect(self._candidate_selected)
        self.files = _readonly_table([self.tr("Torrent file"), self.tr("Local file"), ""])
        self.files.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)

        actions = QHBoxLayout()
        self.check_button = QPushButton(self.tr("Check files"))
        self.check_button.setToolTip(self.tr("Download this Candidate's .torrent and compare"))
        self.check_button.clicked.connect(self._check_selected)
        actions.addWidget(self.check_button)
        actions.addStretch()
        self.action_row = actions

        lower = QWidget()
        lower_layout = QVBoxLayout(lower)
        lower_layout.setContentsMargins(0, 0, 0, 0)
        lower_layout.addWidget(self.files)
        lower_layout.addLayout(actions)

        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(self.candidates)
        split.addWidget(lower)
        layout.addWidget(split)
        self.set_entry(None)

    # Selection -------------------------------------------------------------

    def set_entry(self, entry: LibraryEntry | None) -> None:
        self.entry = entry
        self.results = []
        self.candidates.setRowCount(0)
        self.files.setRowCount(0)
        self.query.setEnabled(entry is not None)
        self.search_button.setEnabled(entry is not None)
        self._update_actions()
        if entry is None:
            self.title.setText(self.tr("Select a Local Item"))
            self.query.clear()
            return
        self.title.setText(f"<b>{entry.item.path.name}</b> — {human_size(entry.item.size)}")
        self.query.setText(self.store.item_query(entry.item.path) or name_query(entry.item))

    def selected(self) -> Verified | None:
        rows = self.candidates.selectionModel().selectedRows()
        return self.results[rows[0].row()] if rows else None

    # Search ----------------------------------------------------------------

    def search(self) -> None:
        if self.entry is None:
            return
        entry = self.entry
        q = self.query.text().strip()
        if q != name_query(entry.item):
            self.store.set_item_query(entry.item.path, q)
        self.search_button.setEnabled(False)
        indexer, tolerance = self.indexer(), self.tolerance()
        run_in_background(
            lambda: verify(indexer, entry.item, indexer.search(SearchQuery(q=q)), tolerance),
            lambda results: self._show(entry, results),
            self._failed,
        )

    def _show(self, entry: LibraryEntry, results: list[Verified]) -> None:
        self.search_button.setEnabled(True)
        if entry is not self.entry:
            return
        self.results = sorted(
            results, key=lambda v: (v.match is None, not v.checked, -v.candidate.seeders)
        )
        self._fill_candidates()
        if not results:
            self.title.setText(self.title.text() + "<br>" + self.tr("No Candidates found"))
        elif self.results[0].match is not None:
            self.candidates.selectRow(0)

    def _fill_candidates(self) -> None:
        self.candidates.setRowCount(len(self.results))
        for r, v in enumerate(self.results):
            c = v.candidate
            self.candidates.setItem(r, 0, QTableWidgetItem(c.title))
            self.candidates.setItem(r, 1, QTableWidgetItem(human_size(c.size)))
            self.candidates.setItem(r, 2, QTableWidgetItem(str(c.seeders)))
            label, color = self._match_label(v)
            cell = QTableWidgetItem(label)
            if color:
                cell.setForeground(color)
            self.candidates.setItem(r, 3, cell)

    def _match_label(self, v: Verified) -> tuple[str, QColor | None]:
        if not v.checked:
            return self.tr("Not checked"), None
        if v.match is not None:
            return self.tr("Full match"), GREEN
        return self.tr("No match"), RED

    def _failed(self, error: Exception) -> None:
        self.search_button.setEnabled(True)
        self.check_button.setEnabled(True)
        QMessageBox.warning(self, self.tr("Search failed"), str(error))

    # Candidate details -----------------------------------------------------

    def _candidate_selected(self) -> None:
        self.files.setRowCount(0)
        v = self.selected()
        self._update_actions()
        if v is None or v.comparison is None:
            return
        cmp = v.comparison
        rows = [(t, local) for t, local in cmp.pairs.items()] + [(t, None) for t in cmp.missing]
        self.files.setRowCount(len(rows))
        for r, (t_path, local) in enumerate(sorted(rows)):
            self.files.setItem(r, 0, QTableWidgetItem(t_path))
            self.files.setItem(r, 1, QTableWidgetItem(local or ""))
            if local is None:
                status, color = self.tr("✗ missing"), RED
            elif local != t_path:
                status, color = self.tr("✓ renamed"), ORANGE
            else:
                status, color = self.tr("✓"), GREEN
            cell = QTableWidgetItem(status)
            cell.setForeground(color)
            self.files.setItem(r, 2, cell)

    def _update_actions(self) -> None:
        v = self.selected()
        self.check_button.setEnabled(v is not None and not v.checked)

    def _check_selected(self) -> None:
        v, entry = self.selected(), self.entry
        if v is None or entry is None:
            return
        self.check_button.setEnabled(False)
        indexer = self.indexer()
        run_in_background(
            lambda: verify_one(indexer, entry.item, v.candidate),
            lambda checked: self._replace(entry, v, checked),
            self._failed,
        )

    def _replace(self, entry: LibraryEntry, old: Verified, new: Verified) -> None:
        if entry is not self.entry or old not in self.results:
            return
        i = self.results.index(old)
        self.results[i] = new
        self._fill_candidates()
        self.candidates.selectRow(i)
