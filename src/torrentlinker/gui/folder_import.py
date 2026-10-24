"""Review client folders and assign them to TorrentLinker Download Folders."""

from __future__ import annotations

import ntpath
import posixpath
from collections.abc import Mapping, Sequence

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from torrentlinker.category_tags import category_path
from torrentlinker.client_folders import ClientFolder, client_path
from torrentlinker.domain import PathMapping
from torrentlinker.downloads import DownloadFolders, IndexerCategory
from torrentlinker.gui.tables import style_table
from torrentlinker.paths import PathMapper


class FolderImportDialog(QDialog):
    def __init__(
        self,
        rows: Sequence[ClientFolder],
        categories: Mapping[int, IndexerCategory],
        current: DownloadFolders,
        mappings: Sequence[PathMapping],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Import folders from Torrent Client"))
        self.resize(1000, 500)
        self.rows = list(rows)
        self.current = current
        self.mapper = PathMapper(mappings)
        self.result_folders: DownloadFolders | None = None
        layout = QVBoxLayout(self)
        note = QLabel(
            self.tr(
                "Choose where to use each folder. Existing Path Mappings are applied. "
                "Temporary folders are shown for reference. This copies folder paths only; "
                "it does not change client settings, labels or move-completed rules. "
                "Save Settings afterwards to keep your changes."
            )
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        self.table = QTableWidget(len(rows), 5)
        self.table.setHorizontalHeaderLabels(
            [
                self.tr("Client setting"),
                self.tr("Client path"),
                self.tr("TorrentLinker path"),
                self.tr("Use for"),
                self.tr("Current folder"),
            ]
        )
        style_table(self.table)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        labels = {
            "default": self.tr("Default"),
            "category": self.tr("Category"),
            "completed": self.tr("Completed downloads"),
            "incomplete": self.tr("Incomplete downloads"),
        }
        names = {}
        for cid in categories:
            names[cid] = " / ".join(
                categories[c].name for c in category_path(cid, categories) if c in categories
            )
        self.choices: list[QComboBox] = []
        for r, folder in enumerate(rows):
            source = labels[folder.kind] + (": " + folder.name if folder.name else "")
            local = self.mapper.to_local(folder.path)
            for col, text in [(0, source), (1, folder.path), (2, local), (4, "")]:
                cell = QTableWidgetItem(text)
                cell.setToolTip(text)
                self.table.setItem(r, col, cell)
            choice = QComboBox()
            choice.addItem(self.tr("Do not import"), None)
            choice.addItem(self.tr("Default Download Folder"), "default")
            for cid, label in sorted(names.items(), key=lambda item: item[1].casefold()):
                choice.addItem(f"{label} ({cid})", cid)
            if folder.kind == "incomplete":
                choice.setEnabled(False)
            elif folder.kind == "default" and folder.path and not current.default:
                choice.setCurrentIndex(1)
            elif folder.name and folder.path:
                exact = [
                    cid
                    for cid in categories
                    if folder.name.strip().casefold()
                    in {categories[cid].name.strip().casefold(), names[cid].strip().casefold()}
                ]
                if len(exact) == 1 and not current.by_category.get(exact[0]):
                    choice.setCurrentIndex(choice.findData(exact[0]))
            self.table.setCellWidget(r, 3, choice)
            self.choices.append(choice)
            choice.currentIndexChanged.connect(self._validate)
        for col, width in enumerate([180, 220, 220, 240, 220]):
            self.table.setColumnWidth(col, width)
        layout.addWidget(self.table, 1)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.apply_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.apply_button.setText(self.tr("Use selected folders"))
        self.buttons.accepted.connect(self._apply)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self._validate()

    def _validate(self) -> None:
        selected: set[int | str] = set()
        error = ""
        replaced = 0
        for r, choice in enumerate(self.choices):
            target = choice.currentData()
            existing = (
                ""
                if target is None
                else (
                    self.current.default
                    if target == "default"
                    else self.current.by_category.get(target, "")
                )
            )
            cell = self.table.item(r, 4)
            assert cell is not None
            cell.setText(existing)
            cell.setToolTip(existing)
            if target is None:
                continue
            if target in selected:
                error = self.tr("Choose only one source folder for each destination.")
            selected.add(target)
            source = self.rows[r].path
            local = self.mapper.to_local(source)
            returned = client_path(self.mapper.to_qbit(local))
            expected = client_path(source)
            if ntpath.splitdrive(source)[0]:
                returned, expected = ntpath.normcase(returned), ntpath.normcase(expected)
            if returned != expected:
                error = self.tr(
                    "These Path Mappings do not lead back to the client folder. "
                    "Cancel and correct Client Paths before importing."
                )
            if not (
                posixpath.isabs(source) or (ntpath.splitdrive(source)[0] and ntpath.isabs(source))
            ):
                error = self.tr("The client folder must be an absolute path.")
            if existing and existing != local:
                replaced += 1
        self.apply_button.setEnabled(bool(selected) and not error)
        self.status.setText(
            error
            or self.tr("{0} folders selected · {1} existing values will be replaced.").format(
                len(selected), replaced
            )
        )

    def _apply(self) -> None:
        self._validate()
        if not self.apply_button.isEnabled():
            return
        result = DownloadFolders(dict(self.current.by_category), self.current.default)
        for row, choice in zip(self.rows, self.choices, strict=True):
            target = choice.currentData()
            if target == "default":
                result.default = self.mapper.to_local(row.path)
            elif isinstance(target, int):
                result.by_category[target] = self.mapper.to_local(row.path)
        self.result_folders = result
        self.accept()
