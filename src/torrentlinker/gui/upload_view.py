"""The Upload tab: Orphans no Candidate matches, made into c411 Drafts (ADR-0011)."""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QT_TRANSLATE_NOOP, QCoreApplication, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from torrentlinker.domain import ContentKind, ItemState
from torrentlinker.gui.errors import error_text, offer_whole_names
from torrentlinker.gui.library_model import human_size
from torrentlinker.gui.tasks import run_in_background, run_with_progress
from torrentlinker.indexer import Indexer
from torrentlinker.library import LibraryEntry
from torrentlinker.matching import IgnoreList
from torrentlinker.qbit import Qbit
from torrentlinker.review import CheckedCandidate
from torrentlinker.store import Store
from torrentlinker.upload import (
    PreparedUpload,
    Subcategory3D,
    UploadStopped,
    create_upload,
    nfo_3d,
    problems_3d,
    seed_upload,
    suggested_name,
    upload_files,
)

C411_UPLOAD_PAGE = "https://c411.org/upload"

SUBCATEGORY_LABELS = {
    Subcategory3D.OBJECTS: QT_TRANSLATE_NOOP("Subcategory3D", "Objects"),
    Subcategory3D.CHARACTERS: QT_TRANSLATE_NOOP("Subcategory3D", "Characters"),
    Subcategory3D.PACK: QT_TRANSLATE_NOOP("Subcategory3D", "Pack"),
}


class UploadTab(QWidget):
    """Pick an Orphan with no Match, name it by c411's rules, and save it as a Draft."""

    upload_started = Signal(object)  # Path of the Local Item, now being verified

    def __init__(
        self,
        store: Store,
        indexer: Callable[[], Indexer],
        qbit: Callable[[], Qbit],
        ignore: Callable[[], IgnoreList],
        announce: Callable[[], str],
        folder: Path,
    ) -> None:
        super().__init__()
        self.store = store
        self.indexer = indexer
        self.qbit = qbit
        self.ignore = ignore
        self.announce = announce
        self.folder = folder  # where the .torrent and .nfo files are kept
        self.entries: list[LibraryEntry] = []
        self.searched: dict[Path, list[CheckedCandidate]] = {}
        self.shown: list[LibraryEntry] = []
        self.entry: LibraryEntry | None = None
        self._name_edited = False
        self._stop = threading.Event()
        self._prepared: PreparedUpload | None = None

        layout = QVBoxLayout(self)
        self.notice = QLabel()
        self.notice.setWordWrap(True)
        layout.addWidget(self.notice)

        self.items = QTableWidget(0, 3)
        self.items.setHorizontalHeaderLabels([self.tr("Local Item"), self.tr("Size"), ""])
        self.items.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.items.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.items.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.items.verticalHeader().hide()
        header = self.items.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.items.itemSelectionChanged.connect(self._item_selected)

        form_box = QWidget()
        form_layout = QVBoxLayout(form_box)
        form_layout.setContentsMargins(0, 0, 0, 0)
        form = QFormLayout()
        self.source = QLineEdit()
        self.source.setPlaceholderText(self.tr("Where the model comes from; empty for NOTAG"))
        self.source.textChanged.connect(self._suggest_name)
        self.subcategory = QComboBox()
        for sub, label in SUBCATEGORY_LABELS.items():
            self.subcategory.addItem(QCoreApplication.translate("Subcategory3D", str(label)), sub)
        self.subcategory.currentIndexChanged.connect(self._suggest_name)
        self.name = QLineEdit()
        self.name.textEdited.connect(self._name_was_edited)
        self.name.textChanged.connect(self._preview)
        form.addRow(self.tr("Source"), self.source)
        form.addRow(self.tr("Subcategory"), self.subcategory)
        form.addRow(self.tr("Release name"), self.name)
        form_layout.addLayout(form)
        self.problems = QLabel()
        self.problems.setWordWrap(True)
        self.problems.setStyleSheet("color: #c0392b")
        form_layout.addWidget(self.problems)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        form_layout.addWidget(self.preview)
        actions = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.hide()
        actions.addWidget(self.progress, 1)
        self.stop_button = QPushButton(self.tr("Stop"))
        self.stop_button.clicked.connect(self._stop.set)
        self.stop_button.hide()
        actions.addWidget(self.stop_button)
        actions.addStretch()
        self.create_button = QPushButton(self.tr("Create Draft"))
        self.create_button.setToolTip(
            self.tr(
                "Make the torrent and NFO, save them as a Draft on c411, then seed from your "
                "files. You add the image and publish on c411."
            )
        )
        self.create_button.clicked.connect(self.create_draft)
        actions.addWidget(self.create_button)
        form_layout.addLayout(actions)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(self.items)
        split.addWidget(form_box)
        split.setSizes([500, 600])
        layout.addWidget(split, 1)

        drafts_box = QGroupBox(self.tr("Your c411 Drafts"))
        drafts_layout = QVBoxLayout(drafts_box)
        self.drafts = QTableWidget(0, 3)
        self.drafts.setHorizontalHeaderLabels(
            [self.tr("Draft"), self.tr("Category"), self.tr("Modified")]
        )
        self.drafts.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.drafts.verticalHeader().hide()
        self.drafts.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.drafts.setMaximumHeight(160)
        drafts_layout.addWidget(self.drafts)
        row = QHBoxLayout()
        self.drafts_status = QLabel()
        row.addWidget(self.drafts_status, 1)
        refresh = QPushButton(self.tr("Refresh"))
        refresh.clicked.connect(self.refresh_drafts)
        row.addWidget(refresh)
        open_page = QPushButton(self.tr("Open c411's upload page"))
        open_page.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(C411_UPLOAD_PAGE)))
        row.addWidget(open_page)
        drafts_layout.addLayout(row)
        layout.addWidget(drafts_box)
        self._fill()

    # The Library -----------------------------------------------------------

    def set_entries(self, entries: list[LibraryEntry]) -> None:
        self.entries = entries
        self._fill()

    def remember(self, entry: LibraryEntry, checked: list[CheckedCandidate]) -> None:
        """An Orphan's latest search, from the Library."""
        self.searched[entry.item.path] = checked
        self._fill()

    def candidates(self) -> list[LibraryEntry]:
        """3D-model Orphans, searched or not: only searched ones without a Match may go."""
        return [
            e
            for e in self.entries
            if e.folder.kind is ContentKind.MODEL_3D and e.state is ItemState.ORPHAN
        ]

    def why_not(self, entry: LibraryEntry) -> str | None:
        """Why this Orphan cannot be uploaded now; None when it can."""
        checked = self.searched.get(entry.item.path)
        if checked is None:
            return self.tr("Search it first: c411 may already have it")
        if any(v.match for v in checked):
            return self.tr("c411 already has it: Reseed it from the Library")
        if found := problems_3d(entry.item, self.ignore()):
            return "; ".join(found)
        return None

    def _fill(self) -> None:
        selected = self.entry.item.path if self.entry else None
        self.shown = self.candidates()
        self.items.blockSignals(True)
        self.items.setRowCount(len(self.shown))
        for r, e in enumerate(self.shown):
            reason = self.why_not(e)
            cells = [e.item.path.name, human_size(e.item.size), reason or self.tr("Ready")]
            for c, text in enumerate(cells):
                cell = QTableWidgetItem(text)
                if c == 2 and reason:
                    cell.setToolTip(reason)
                self.items.setItem(r, c, cell)
            if e.item.path == selected:
                self.items.selectRow(r)
        self.items.blockSignals(False)
        if not any(e.folder.kind is ContentKind.MODEL_3D for e in self.entries):
            self.notice.setText(
                self.tr(
                    "No Library Folder holds 3D models. Set a folder's Content Kind to "
                    "3D models in Settings → Library Folders."
                )
            )
        elif not self.announce():
            self.notice.setText(
                self.tr("Enter your Announce URL in Settings → Connections to make Uploads.")
            )
        else:
            self.notice.setText(
                self.tr(
                    "3D-model Orphans that a search found no Match for. Each Upload is saved "
                    "as a Draft on c411: you add an image and publish it there."
                )
            )
        self._update_actions()

    # The form --------------------------------------------------------------

    def _item_selected(self) -> None:
        rows = self.items.selectionModel().selectedRows()
        self.entry = self.shown[rows[0].row()] if rows else None
        self._prepared = None
        self._name_edited = False
        if self.entry is not None:
            pack = len(self.entry.item.files) > 1
            self.subcategory.setCurrentIndex(
                self.subcategory.findData(Subcategory3D.PACK if pack else Subcategory3D.OBJECTS)
            )
        self._suggest_name()

    def _name_was_edited(self) -> None:
        self._name_edited = True

    def _suggest_name(self) -> None:
        if self.entry is None:
            self.name.clear()
            self.preview.clear()
            self.problems.clear()
            self._update_actions()
            return
        if not self._name_edited:
            pack = self.subcategory.currentData() == Subcategory3D.PACK
            self.name.setText(
                suggested_name(self.entry.item, self.ignore(), self.source.text(), pack)
            )
        self._preview()

    def _preview(self) -> None:
        entry, title = self.entry, self.name.text().strip()
        self.problems.setText((self.why_not(entry) or "") if entry else "")
        if entry is None or not title:
            self.preview.clear()
            self._update_actions()
            return
        if " " in title or not title.isascii():
            self.problems.setText(
                self.tr("A release name has dots between words, no spaces and no accents.")
            )
        try:
            files = upload_files(entry.item, title, self.ignore())
        except ValueError as e:
            self.problems.setText(str(e))
            self.preview.clear()
        else:
            if files:
                self.preview.setPlainText(nfo_3d(title, files))
        self._update_actions()

    def _update_actions(self) -> None:
        title = self.name.text().strip()
        ready = (
            self.entry is not None
            and self.why_not(self.entry) is None
            and bool(title)
            and " " not in title
            and title.isascii()
            and bool(self.announce())
            and not self.progress.isVisible()
        )
        self.create_button.setEnabled(ready)

    # Making the Upload -----------------------------------------------------

    def create_draft(self) -> None:
        entry = self.entry
        if entry is None:
            return
        title = self.name.text().strip()
        subcategory = Subcategory3D(self.subcategory.currentData())
        store, ignore, announce = self.store, self.ignore(), self.announce()
        indexer, folder, stop = self.indexer(), self.folder, self._stop
        stop.clear()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.show()
        self.stop_button.show()
        self._update_actions()

        def work(report: Callable[[object], None]) -> PreparedUpload:
            return create_upload(
                entry.item,
                title,
                subcategory,
                announce,
                ignore,
                folder,
                indexer.save_draft,
                store,
                report=lambda done, total: report((done, total)),
                stopped=stop.is_set,
            )

        run_with_progress(
            work,
            self._hashing,
            lambda prepared: self._drafted(entry, prepared),
            self._failed,
        )

    def _hashing(self, value: tuple[int, int]) -> None:
        done, total = value
        self.progress.setValue(int(100 * done / total) if total else 100)

    def _drafted(self, entry: LibraryEntry, prepared: PreparedUpload) -> None:
        self._prepared = prepared
        self.progress.setRange(0, 0)
        self.stop_button.hide()
        self.refresh_drafts()
        self._seed(entry, prepared)

    def _seed(self, entry: LibraryEntry, prepared: PreparedUpload) -> None:
        qbit, store = self.qbit(), self.store
        run_in_background(
            lambda: seed_upload(qbit, store, entry.item, prepared),
            lambda _hash: self._seeding(entry, prepared),
            lambda e: self._seed_failed(entry, prepared, e),
        )

    def _seeding(self, entry: LibraryEntry, prepared: PreparedUpload) -> None:
        self._done()
        self.upload_started.emit(entry.item.path)
        QMessageBox.information(
            self,
            self.tr("Draft saved"),
            self.tr(
                "{0} is saved as a Draft on c411 and is being verified in your torrent "
                "client. Once it seeds, open c411's upload page, load the Draft, add an "
                "image and publish it."
            ).format(prepared.saved.title),
        )

    def _seed_failed(self, entry: LibraryEntry, prepared: PreparedUpload, error: Exception) -> None:
        self._done()
        if offer_whole_names(self, error, then=lambda: self._seed(entry, prepared)):
            return
        QMessageBox.warning(
            self,
            self.tr("Not seeding"),
            self.tr(
                "The Draft is saved on c411, but its torrent could not be added to your "
                "torrent client: {0}\n\nc411 refuses an upload whose uploader is not "
                "seeding: do not publish it before it seeds."
            ).format(error_text(error)),
        )

    def _failed(self, error: Exception) -> None:
        self._done()
        if isinstance(error, UploadStopped):
            return
        QMessageBox.warning(self, self.tr("Upload failed"), error_text(error))

    def _done(self) -> None:
        self.progress.hide()
        self.stop_button.hide()
        self._update_actions()

    # Drafts ----------------------------------------------------------------

    def refresh_drafts(self) -> None:
        if not self.announce():
            return
        indexer = self.indexer()
        self.drafts_status.setText(self.tr("Reading your Drafts…"))
        run_in_background(indexer.drafts, self._show_drafts, self._drafts_failed)

    def _show_drafts(self, drafts: list[dict[str, object]]) -> None:
        self.drafts.setRowCount(len(drafts))
        for r, d in enumerate(drafts):
            category = d.get("subcategory") or d.get("category") or ""
            if isinstance(category, dict):
                category = category.get("name", "")
            modified = str(d.get("updatedAt") or "")[:16].replace("T", " ")
            for c, text in enumerate([str(d.get("name") or ""), str(category), modified]):
                self.drafts.setItem(r, c, QTableWidgetItem(text))
        self.drafts_status.setText(self.tr("{0}/15 Drafts on c411").format(len(drafts)))

    def _drafts_failed(self, error: Exception) -> None:
        self.drafts_status.setText(error_text(error))
