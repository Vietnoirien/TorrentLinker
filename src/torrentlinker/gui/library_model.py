from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import (
    QT_TRANSLATE_NOOP,
    QAbstractTableModel,
    QCoreApplication,
    QModelIndex,
    QPersistentModelIndex,
    QSortFilterProxyModel,
    Qt,
)
from PySide6.QtGui import QColor

from torrentlinker.domain import ItemState
from torrentlinker.library import LibraryEntry

STATE_LABELS = {
    ItemState.SEEDED: QT_TRANSLATE_NOOP("LibraryModel", "Seeded"),
    ItemState.PARTIALLY_SEEDED: QT_TRANSLATE_NOOP("LibraryModel", "Partially seeded"),
    ItemState.ORPHAN: QT_TRANSLATE_NOOP("LibraryModel", "Orphan"),
}


def state_label(state: ItemState) -> str:
    return QCoreApplication.translate("LibraryModel", str(STATE_LABELS[state]))


def human_size(n: float) -> str:
    for unit in ("B", "KiB", "MiB", "GiB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TiB"


STATE_COLORS = {
    ItemState.SEEDED: QColor("#2e7d32"),
    ItemState.PARTIALLY_SEEDED: QColor("#ef6c00"),
}


class LibraryModel(QAbstractTableModel):
    COLUMNS = (
        QT_TRANSLATE_NOOP("LibraryModel", "Name"),
        QT_TRANSLATE_NOOP("LibraryModel", "State"),
        QT_TRANSLATE_NOOP("LibraryModel", "Size"),
        QT_TRANSLATE_NOOP("LibraryModel", "Library Folder"),
    )

    def __init__(self) -> None:
        super().__init__()
        self.entries: list[LibraryEntry] = []
        self.status: dict[Path, str] = {}

    def set_entries(self, entries: list[LibraryEntry]) -> None:
        self.beginResetModel()
        self.entries = entries
        self.endResetModel()

    def set_status(self, path: Path, text: str | None) -> None:
        """Overlay a transient status (Verifying, Reseeded, Failed…) on a Local Item."""
        if text is None:
            self.status.pop(path, None)
        else:
            self.status[path] = text
        for row, e in enumerate(self.entries):
            if e.item.path == path:
                i = self.index(row, 1)
                self.dataChanged.emit(i, i)

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.entries)

    def columnCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:
        return len(self.COLUMNS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = 0) -> Any:
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return QCoreApplication.translate("LibraryModel", str(self.COLUMNS[section]))
        return None

    def data(self, index: QModelIndex | QPersistentModelIndex, role: int = 0) -> Any:
        if not index.isValid():
            return None
        e = self.entries[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return (
                e.item.path.name,
                self.status.get(e.item.path) or state_label(e.state),
                human_size(e.item.size),
                str(e.folder.path),
            )[index.column()]
        if role == Qt.ItemDataRole.ForegroundRole and index.column() == 1:
            return STATE_COLORS.get(e.state)
        if role == Qt.ItemDataRole.UserRole:
            return e
        return None


class LibraryFilter(QSortFilterProxyModel):
    """Filter the Library by state and by Library Folder; sorts sizes numerically."""

    def __init__(self) -> None:
        super().__init__()
        self.state: ItemState | None = None
        self.folder: Path | None = None

    def set_filters(self, state: ItemState | None, folder: Path | None) -> None:
        if hasattr(self, "beginFilterChange"):  # Qt >= 6.9
            self.beginFilterChange()
            self.state, self.folder = state, folder
            self.endFilterChange()
        else:
            self.state, self.folder = state, folder
            self.invalidateFilter()

    def filterAcceptsRow(
        self, source_row: int, source_parent: QModelIndex | QPersistentModelIndex
    ) -> bool:
        model = self.sourceModel()
        assert isinstance(model, LibraryModel)
        e = model.entries[source_row]
        return (self.state is None or e.state is self.state) and (
            self.folder is None or e.folder.path == self.folder
        )

    def lessThan(
        self,
        left: QModelIndex | QPersistentModelIndex,
        right: QModelIndex | QPersistentModelIndex,
    ) -> bool:
        model = self.sourceModel()
        assert isinstance(model, LibraryModel)
        if left.column() == 2:
            return model.entries[left.row()].item.size < model.entries[right.row()].item.size
        return super().lessThan(left, right)
