from __future__ import annotations

from typing import Any

from PySide6.QtCore import (
    QAbstractTableModel,
    QCoreApplication,
    QModelIndex,
    QPersistentModelIndex,
    Qt,
)

from torrentlinker.domain import ItemState
from torrentlinker.library import LibraryEntry


def tr(text: str) -> str:
    return QCoreApplication.translate("LibraryModel", text)


def state_label(state: ItemState) -> str:
    return {
        ItemState.SEEDED: tr("Seeded"),
        ItemState.PARTIALLY_SEEDED: tr("Partially seeded"),
        ItemState.ORPHAN: tr("Orphan"),
    }[state]


def human_size(n: float) -> str:
    for unit in ("B", "KiB", "MiB", "GiB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TiB"


class LibraryModel(QAbstractTableModel):
    COLUMNS = ("Name", "State", "Size", "Library Folder")

    def __init__(self) -> None:
        super().__init__()
        self.entries: list[LibraryEntry] = []

    def set_entries(self, entries: list[LibraryEntry]) -> None:
        self.beginResetModel()
        self.entries = entries
        self.endResetModel()

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.entries)

    def columnCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:
        return len(self.COLUMNS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = 0) -> Any:
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return tr(self.COLUMNS[section])
        return None

    def data(self, index: QModelIndex | QPersistentModelIndex, role: int = 0) -> Any:
        if not index.isValid():
            return None
        e = self.entries[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return (
                e.item.path.name,
                state_label(e.state),
                human_size(e.item.size),
                str(e.folder.path),
            )[index.column()]
        if role == Qt.ItemDataRole.UserRole:
            return e
        return None
