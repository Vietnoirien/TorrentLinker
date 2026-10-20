from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
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

from torrentlinker.domain import ItemState
from torrentlinker.gui.library_model import human_size
from torrentlinker.gui.tasks import run_in_background
from torrentlinker.indexer import Candidate, Indexer
from torrentlinker.library import LibraryEntry
from torrentlinker.qbit import Qbit
from torrentlinker.reseed import start_reseed
from torrentlinker.review import MatchRules, Verified, candidate_key, verify, verify_one
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

    reseed_started = Signal(object)  # Path of the Local Item

    def __init__(
        self,
        store: Store,
        indexer: Callable[[], Indexer],
        qbit: Callable[[], Qbit],
        rules: Callable[[], MatchRules],
        searcher: Callable[[LibraryEntry, str | None], list[Candidate]],
        default_query: Callable[[LibraryEntry], str],
    ) -> None:
        super().__init__()
        self.store = store
        self.indexer = indexer
        self.qbit = qbit
        self.rules = rules
        self.searcher = searcher
        self.default_query = default_query
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
        self.candidates.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.candidates.itemSelectionChanged.connect(self._candidate_selected)
        self.files = _readonly_table([self.tr("Torrent file"), self.tr("Local file"), ""])
        self.files.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)

        actions = QHBoxLayout()
        self.check_button = QPushButton(self.tr("Check files"))
        self.check_button.setToolTip(
            self.tr(
                "Download this Candidate's .torrent and compare. Needed for Candidates "
                "outside the size tolerance, e.g. a season pack you only partly have."
            )
        )
        self.check_button.clicked.connect(self._check_selected)
        actions.addWidget(self.check_button)
        self.reject_button = QPushButton(self.tr("Reject"))
        self.reject_button.setToolTip(self.tr("Not this Local Item: never propose it again"))
        self.reject_button.clicked.connect(self._reject_selected)
        actions.addWidget(self.reject_button)
        actions.addStretch()
        self.reseed_button = QPushButton(self.tr("Reseed"))
        self.reseed_button.setToolTip(
            self.tr("Add to qBittorrent against your files, verify, then seed")
        )
        self.reseed_button.clicked.connect(self._reseed_selected)
        actions.addWidget(self.reseed_button)
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
        searchable = entry is not None and entry.state is not ItemState.SEEDED
        self.query.setEnabled(searchable)
        self.search_button.setEnabled(searchable)
        partial = entry is not None and entry.state is ItemState.PARTIALLY_SEEDED
        self.search_button.setText(self.tr("Force search") if partial else self.tr("Search"))
        self._update_actions()
        if entry is None:
            self.title.setText(self.tr("Select a Local Item"))
            self.query.clear()
            return
        title = f"<b>{entry.item.path.name}</b> — {human_size(entry.item.size)}"
        if entry.state is ItemState.SEEDED:
            title += "<br>" + self.tr("Already seeded by qBittorrent.")
        elif partial:
            title += "<br>" + self.tr(
                "Some of these files are already seeded: a Match would overlap that torrent."
            )
        self.title.setText(title)
        self.query.setText(self.store.item_query(entry.item.path) or self.default_query(entry))

    def selected(self) -> Verified | None:
        """The Candidate whose files are shown: the current one among the selection."""
        rows = self.selected_all()
        current = self.candidates.currentRow()
        if 0 <= current < len(self.results) and self.results[current] in rows:
            return self.results[current]
        return rows[0] if rows else None

    def selected_all(self) -> list[Verified]:
        rows = sorted(i.row() for i in self.candidates.selectionModel().selectedRows())
        return [self.results[r] for r in rows]

    # Search ----------------------------------------------------------------

    def search(self) -> None:
        if self.entry is None:
            return
        entry = self.entry
        q = self.query.text().strip()
        override = q if q and q != self.default_query(entry) else None
        if override:
            self.store.set_item_query(entry.item.path, override)
        self.search_button.setEnabled(False)
        indexer, rules = self.indexer(), self.rules()
        rejections = self.store.rejections(entry.item.path)
        run_in_background(
            lambda: verify(indexer, entry.item, self.searcher(entry, override), rules, rejections),
            lambda results: self._show(entry, results),
            self._failed,
        )

    def _show(self, entry: LibraryEntry, results: list[Verified]) -> None:
        self.search_button.setEnabled(self.entry is not None)
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
        if v.match is not None and v.match.is_full:
            return self.tr("Full match"), GREEN
        if v.match is not None:
            return self.tr("Partial match ({0})").format(f"{v.match.coverage:.0%}"), ORANGE
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
        rows: list[tuple[str, str | None]] = list(cmp.pairs.items())
        rows += [(t, None) for t in cmp.unwanted]
        self.files.setRowCount(len(rows))
        for r, (t_path, local) in enumerate(sorted(rows)):
            self.files.setItem(r, 0, QTableWidgetItem(t_path))
            self.files.setItem(r, 1, QTableWidgetItem(local or ""))
            if local is None and t_path in cmp.skipped:
                status, color = self.tr("– ignored, not downloaded"), ORANGE
            elif local is None:
                status, color = self.tr("✗ missing, not downloaded"), RED
            elif local != t_path:
                status, color = self.tr("✓ renamed"), ORANGE
            else:
                status, color = self.tr("✓"), GREEN
            cell = QTableWidgetItem(status)
            cell.setForeground(color)
            self.files.setItem(r, 2, cell)

    def _update_actions(self) -> None:
        v, chosen = self.selected(), self.selected_all()
        self.check_button.setEnabled(v is not None and not v.checked)
        self.reject_button.setEnabled(bool(chosen))
        self.reseed_button.setEnabled(bool(chosen) and all(c.match for c in chosen))
        self.reseed_button.setText(
            self.tr("Reseed {0} Matches").format(len(chosen))
            if len(chosen) > 1
            else self.tr("Reseed")
        )

    def _reject_selected(self) -> None:
        if self.entry is None:
            return
        for v in self.selected_all():
            self.store.reject(self.entry.item.path, candidate_key(v.candidate), "Rejected by user")
            self.results.remove(v)
        self.candidates.clearSelection()
        self._fill_candidates()

    def _check_selected(self) -> None:
        v, entry = self.selected(), self.entry
        if v is None or entry is None:
            return
        self.check_button.setEnabled(False)
        indexer, rules = self.indexer(), self.rules()
        run_in_background(
            lambda: verify_one(indexer, entry.item, v.candidate, rules),
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

    def _reseed_selected(self) -> None:
        entry = self.entry
        chosen = [v for v in self.selected_all() if v.meta is not None and v.match is not None]
        if entry is None or not chosen:
            return
        for v in chosen:
            assert v.match is not None
            if not v.match.is_full and not self._confirm_partial(
                len(v.match.missing), v.match.coverage
            ):
                return
        renames = {k: n for v in chosen if v.match for k, n in v.match.renames.items()}
        if renames and not self._confirm_renames(renames):
            return
        self.reseed_button.setEnabled(False)
        qbit, store = self.qbit(), self.store

        def work() -> list[str]:
            hashes = []
            for v in chosen:
                assert v.meta is not None and v.match is not None
                key = candidate_key(v.candidate)
                hashes.append(start_reseed(qbit, store, entry.item, v.meta, v.match, key))
            return hashes

        run_in_background(
            work, lambda _hashes: self.reseed_started.emit(entry.item.path), self._reseed_failed
        )

    def _confirm_partial(self, missing: int, coverage: float) -> bool:
        answer = QMessageBox.question(
            self,
            self.tr("Partial Match"),
            self.tr(
                "You have {0} of this torrent. The {1} missing files will not be downloaded; "
                "only a few pieces shared with your files may be fetched again. Reseed?"
            ).format(f"{coverage:.0%}", missing),
        )
        return answer == QMessageBox.StandardButton.Yes

    def _confirm_renames(self, renames: dict[str, str]) -> bool:
        shown = sorted(renames.items())[:15]
        lines = "\n".join(f"{old}\n    → {new}" for old, new in shown)
        if len(renames) > len(shown):
            lines += "\n" + self.tr("…and {0} more").format(len(renames) - len(shown))
        answer = QMessageBox.question(
            self,
            self.tr("Rename inside the torrent"),
            self.tr(
                "These files will be renamed inside qBittorrent to match yours "
                "(your files are not touched):"
            )
            + "\n\n"
            + lines,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _reseed_failed(self, error: Exception) -> None:
        self._update_actions()
        QMessageBox.warning(self, self.tr("Reseed failed"), str(error) or type(error).__name__)
