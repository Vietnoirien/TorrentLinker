from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from torrentlinker.domain import ContentKind, ItemState, LocalItem
from torrentlinker.gui.errors import error_text, offer_whole_names
from torrentlinker.gui.library_model import human_size
from torrentlinker.gui.tasks import run_in_background, run_with_progress
from torrentlinker.indexer import Candidate, Indexer
from torrentlinker.library import LibraryEntry
from torrentlinker.matching import MatchRules
from torrentlinker.qbit import Qbit
from torrentlinker.reseed import start_reseed
from torrentlinker.review import (
    CheckedCandidate,
    candidate_key,
    check_candidate,
    check_candidates,
    remember_candidates,
    unpack_and_reseed,
)
from torrentlinker.store import Store
from torrentlinker.transmission import PartialNamesOn

Searcher = Callable[[LibraryEntry, str | None], list[Candidate]]
"""Searches an Indexer for a Local Item, optionally with a user-edited query."""

GREEN, ORANGE, RED = QColor("#2e7d32"), QColor("#ef6c00"), QColor("#c62828")


def _readonly_table(headers: list[str]) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.verticalHeader().setVisible(False)
    return table


class ReviewPanel(QWidget):
    """Candidates for the selected Orphan, and how a Candidate's files line up locally."""

    reseed_started = Signal(object)  # Path of the Local Item
    unpacked = Signal(object)  # Path of the new folder: the Library needs a Scan
    candidates_checked = Signal(object, object)  # LibraryEntry, list[CheckedCandidate]
    upload_requested = Signal(object)  # LibraryEntry to make an Upload of

    def __init__(
        self,
        store: Store,
        indexer: Callable[[], Indexer],
        qbit: Callable[[], Qbit],
        rules: Callable[[], MatchRules],
        searcher: Callable[[], Searcher],
        default_query: Callable[[LibraryEntry], str],
    ) -> None:
        super().__init__()
        self.store = store
        self.indexer = indexer
        self.qbit = qbit
        self.rules = rules
        self.searcher = searcher
        self.default_query = default_query
        # Why the entry cannot be an Upload, None when it can; set by the window.
        self.upload_blocker: Callable[[LibraryEntry], str | None] = lambda e: ""
        self.entry: LibraryEntry | None = None
        self.checked: list[CheckedCandidate] = []
        self.cache: dict[
            Path, list[CheckedCandidate]
        ] = {}  # last Candidates checked per Local Item

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
        self.upload_button = QPushButton(self.tr("Upload…"))
        self.upload_button.clicked.connect(
            lambda: self.entry is not None and self.upload_requested.emit(self.entry)
        )
        actions.addWidget(self.upload_button)
        actions.addStretch()
        self.reseed_button = QPushButton(self.tr("Reseed"))
        self.reseed_button.setToolTip(
            self.tr("Add to your torrent client against your files, verify, then seed")
        )
        self.reseed_button.clicked.connect(self._reseed_selected)
        actions.addWidget(self.reseed_button)
        self.action_row = actions
        self.unpack_progress = QProgressBar()
        self.unpack_progress.hide()

        lower = QWidget()
        lower_layout = QVBoxLayout(lower)
        lower_layout.setContentsMargins(0, 0, 0, 0)
        lower_layout.addWidget(self.files)
        lower_layout.addLayout(actions)
        lower_layout.addWidget(self.unpack_progress)

        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(self.candidates)
        split.addWidget(lower)
        layout.addWidget(split)
        self.set_entry(None)

    # Selection -------------------------------------------------------------

    def set_entry(self, entry: LibraryEntry | None) -> None:
        self.entry = entry
        self.checked = []
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
            title += "<br>" + self.tr("Already seeded for c411 by your torrent client.")
        elif partial:
            title += "<br>" + self.tr(
                "Some of these files are already seeded: a Match would overlap that torrent."
            )
        self.title.setText(title)
        self.query.setText(self.store.item_query(entry.item.path) or self.default_query(entry))
        if entry.item.path in self.cache:
            self._show(entry, self.cache[entry.item.path])

    def selected(self) -> CheckedCandidate | None:
        """The Candidate whose files are shown: the current one among the selection."""
        rows = self.selected_all()
        current = self.candidates.currentRow()
        if 0 <= current < len(self.checked) and self.checked[current] in rows:
            return self.checked[current]
        return rows[0] if rows else None

    def selected_all(self) -> list[CheckedCandidate]:
        rows = sorted(i.row() for i in self.candidates.selectionModel().selectedRows())
        return [self.checked[r] for r in rows]

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
        indexer, rules, searcher = self.indexer(), self.rules(), self.searcher()
        store = self.store
        rejections = store.rejections(entry.item.path)

        def work() -> list[CheckedCandidate]:
            found = searcher(entry, override)
            remember_candidates(store, indexer, entry.item.path, found)
            return check_candidates(indexer, entry.item, found, rules, rejections)

        run_in_background(work, lambda checked: self._show(entry, checked), self._failed)

    def remember(self, entry: LibraryEntry, checked: list[CheckedCandidate]) -> None:
        """Keep Candidates checked elsewhere (batch search) for when the item is selected."""
        self.cache[entry.item.path] = checked
        self.candidates_checked.emit(entry, checked)
        if self.entry is not None and self.entry.item.path == entry.item.path:
            self._show(self.entry, checked)

    def _show(self, entry: LibraryEntry, checked: list[CheckedCandidate]) -> None:
        self.search_button.setEnabled(self.entry is not None)
        self.cache[entry.item.path] = checked
        self.candidates_checked.emit(entry, checked)
        if entry is not self.entry:
            return
        self.checked = sorted(
            checked, key=lambda v: (v.match is None, not v.compared, -v.candidate.seeders)
        )
        self._fill_candidates()
        self._update_actions()
        if not checked:
            self.title.setText(self.title.text() + "<br>" + self.tr("No Candidates found"))
        elif self.checked[0].match is not None:
            self.candidates.selectRow(0)

    def _fill_candidates(self) -> None:
        self.candidates.setRowCount(len(self.checked))
        for r, v in enumerate(self.checked):
            c = v.candidate
            self.candidates.setItem(r, 0, QTableWidgetItem(c.title))
            self.candidates.setItem(r, 1, QTableWidgetItem(human_size(c.size)))
            self.candidates.setItem(r, 2, QTableWidgetItem(str(c.seeders)))
            label, color = self._match_label(v)
            cell = QTableWidgetItem(label)
            if color:
                cell.setForeground(color)
            self.candidates.setItem(r, 3, cell)

    def _match_label(self, v: CheckedCandidate) -> tuple[str, QColor | None]:
        if not v.compared:
            return self.tr("Not checked"), None
        if v.match is not None and v.unpack is not None:
            if v.match.is_full:
                return self.tr("Full match inside the archive"), GREEN
            return self.tr("Partial match inside the archive ({0})").format(
                f"{v.match.coverage:.0%}"
            ), ORANGE
        if v.match is not None and v.match.is_full:
            return self.tr("Full match"), GREEN
        if v.match is not None:
            return self.tr("Partial match ({0})").format(f"{v.match.coverage:.0%}"), ORANGE
        return self.tr("No match"), RED

    def _failed(self, error: Exception) -> None:
        self.search_button.setEnabled(True)
        self.check_button.setEnabled(True)
        QMessageBox.warning(self, self.tr("Search failed"), error_text(error))

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
                status, color = self.tr("✗ absent, not downloaded"), RED
            elif v.unpack is not None:
                status, color = self.tr("✓ in the archive"), GREEN
            elif local != t_path:
                status, color = self.tr("✓ renamed"), ORANGE
            else:
                status, color = self.tr("✓"), GREEN
            cell = QTableWidgetItem(status)
            cell.setForeground(color)
            self.files.setItem(r, 2, cell)

    def _update_actions(self) -> None:
        v, chosen = self.selected(), self.selected_all()
        self.check_button.setEnabled(v is not None and not v.compared)
        self.reject_button.setEnabled(bool(chosen))
        archive = any(c.unpack for c in chosen)
        blocker = self.upload_blocker(self.entry) if self.entry is not None else ""
        self.upload_button.setVisible(
            self.entry is not None and self.entry.folder.kind is ContentKind.MODEL_3D
        )
        self.upload_button.setEnabled(blocker is None)
        self.upload_button.setToolTip(
            blocker or self.tr("c411 does not have it: make it a c411 Draft in the Upload tab")
        )
        self.reseed_button.setEnabled(
            bool(chosen)
            and all(c.match for c in chosen)
            and not (archive and len(chosen) > 1)
            and self.unpack_progress.isHidden()
        )
        if archive:
            self.reseed_button.setText(self.tr("Unpack and Reseed…"))
        else:
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
            self.checked.remove(v)
        self.cache[self.entry.item.path] = list(self.checked)
        self.candidates_checked.emit(self.entry, self.checked)
        self.candidates.clearSelection()
        self._fill_candidates()

    def _check_selected(self) -> None:
        v, entry = self.selected(), self.entry
        if v is None or entry is None:
            return
        self.check_button.setEnabled(False)
        indexer, rules = self.indexer(), self.rules()
        run_in_background(
            lambda: check_candidate(indexer, entry.item, v.candidate, rules),
            lambda checked: self._replace(entry, v, checked),
            self._failed,
        )

    def _replace(self, entry: LibraryEntry, old: CheckedCandidate, new: CheckedCandidate) -> None:
        if entry is not self.entry or old not in self.checked:
            return
        i = self.checked.index(old)
        self.checked[i] = new
        self.cache[entry.item.path] = list(self.checked)
        self.candidates_checked.emit(entry, self.checked)
        self._fill_candidates()
        self.candidates.selectRow(i)

    def _reseed_selected(self) -> None:
        entry = self.entry
        chosen = [v for v in self.selected_all() if v.meta is not None and v.match is not None]
        if entry is None or not chosen:
            return
        if len(chosen) == 1 and chosen[0].unpack is not None:
            self._unpack_and_reseed(entry, chosen[0])
            return
        for v in chosen:
            assert v.match is not None
            if not v.match.is_full and not self._confirm_partial(
                len(v.match.absent), v.match.coverage
            ):
                return
        renames = {k: n for v in chosen if v.match for k, n in v.match.renames.items()}
        if renames and not self._confirm_renames(renames):
            return
        self.reseed_button.setEnabled(False)
        qbit, store = self.qbit(), self.store

        def work() -> tuple[list[str], list[str], Exception | None]:
            """Reseed each Match; one failing must not hide the ones already added."""
            hashes: list[str] = []
            errors: list[str] = []
            for v in chosen:
                assert v.meta is not None and v.match is not None
                key = candidate_key(v.candidate)
                try:
                    hashes.append(start_reseed(qbit, store, entry.item, v.meta, v.match, key))
                except PartialNamesOn as e:
                    return hashes, errors, e  # the user may let Transmission change, then retry
                except Exception as e:  # noqa: BLE001 - reported to the user below
                    errors.append(f"{v.candidate.title}: {e or type(e).__name__}")
            return hashes, errors, None

        run_in_background(work, lambda done: self._reseeded(entry, *done), self._reseed_failed)

    def _reseeded(
        self,
        entry: LibraryEntry,
        hashes: list[str],
        errors: list[str],
        refused: Exception | None = None,
    ) -> None:
        if hashes:
            self.reseed_started.emit(entry.item.path)
        if refused is not None:
            self._update_actions()
            if offer_whole_names(self, refused, then=self._reseed_selected):
                return
        if errors:
            self._reseed_failed(RuntimeError("\n".join(errors)))

    # Archives --------------------------------------------------------------

    def _unpack_and_reseed(self, entry: LibraryEntry, v: CheckedCandidate) -> None:
        u = v.unpack
        assert u is not None and v.match is not None
        folder = u.item.path
        if folder.exists():
            QMessageBox.information(
                self,
                self.tr("Unpack and Reseed"),
                self.tr(
                    "{0} already exists. If it holds this archive unpacked, scan the Library "
                    "and search that folder to Reseed it."
                ).format(folder),
            )
            return
        free = shutil.disk_usage(u.archive.parent).free
        if free < u.size:
            QMessageBox.warning(
                self,
                self.tr("Unpack and Reseed"),
                self.tr("Unpacking needs {0}, but only {1} is free on that disk.").format(
                    human_size(u.size), human_size(free)
                ),
            )
            return
        if not v.match.is_full and not self._confirm_partial(len(v.match.absent), v.match.coverage):
            return
        answer = QMessageBox.question(
            self,
            self.tr("Unpack and Reseed"),
            self.tr(
                "Unpack {0} into the new folder\n{1}?\n\n"
                "It writes {2} in {3} files; {4} is free on that disk. Nothing is "
                "overwritten.\n\nThe torrent is then added to your torrent client against the "
                "unpacked files, and verified before it seeds. Once it is verified, you are "
                "offered to move the archive to the trash."
            ).format(
                u.archive.name,
                folder,
                human_size(u.size),
                len(u.item.files),
                human_size(free),
            ),
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        qbit, store, rules = self.qbit(), self.store, self.rules()
        self.unpack_progress.setRange(0, 1000)
        self.unpack_progress.setValue(0)
        self.unpack_progress.setFormat(self.tr("Unpacking %p%"))
        self.unpack_progress.show()
        self._update_actions()

        def work(report: Callable[[object], None]) -> tuple[str, LocalItem]:
            return unpack_and_reseed(
                qbit, store, v, rules, lambda done, total: report((done, total))
            )

        run_with_progress(
            work,
            self._unpack_progress,
            lambda result: self._unpacked(entry, result[1].path),
            self._unpack_failed,
        )

    def _unpack_progress(self, value: tuple[int, int]) -> None:
        done, total = value
        self.unpack_progress.setValue(round(1000 * done / total) if total else 0)
        self.unpack_progress.setFormat(
            self.tr("Unpacking: {0} of {1}").format(human_size(done), human_size(total))
        )

    def _unpacked(self, entry: LibraryEntry, folder: Path) -> None:
        self.unpack_progress.hide()
        self._update_actions()
        self.unpacked.emit(folder)
        self.reseed_started.emit(folder)

    def _unpack_failed(self, error: Exception) -> None:
        self.unpack_progress.hide()
        self._update_actions()
        QMessageBox.warning(
            self,
            self.tr("Unpack and Reseed"),
            self.tr("Could not unpack and Reseed: {0}").format(error_text(error)),
        )

    def _confirm_partial(self, missing: int, coverage: float) -> bool:
        answer = QMessageBox.question(
            self,
            self.tr("Partial Match"),
            self.tr(
                "You have {0} of this torrent. The {1} absent files will not be downloaded. "
                "After Verification the torrent is left stopped: starting it in your torrent "
                "client would fetch the few pieces it shares with your files. Reseed?"
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
                "These files will be renamed inside your torrent client to match yours "
                "(your files are not touched):"
            )
            + "\n\n"
            + lines,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _reseed_failed(self, error: Exception) -> None:
        self._update_actions()
        QMessageBox.warning(self, self.tr("Reseed failed"), str(error) or type(error).__name__)
