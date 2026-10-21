"""The Zen tab: the Seeding view and, later, the Plan."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QT_TRANSLATE_NOOP, QCoreApplication, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from torrentlinker.gui.library_model import human_size
from torrentlinker.gui.tasks import run_in_background
from torrentlinker.seeding import Seeding
from torrentlinker.zen import ZenClass

CLASS_LABELS = {
    ZenClass.TANKER: QT_TRANSLATE_NOOP("ZenClass", "Tanker"),
    ZenClass.SWARM_KEEPER: QT_TRANSLATE_NOOP("ZenClass", "Swarm Keeper"),
    ZenClass.REUPLOADER: QT_TRANSLATE_NOOP("ZenClass", "Reuploader"),
}


def class_label(zen_class: ZenClass) -> str:
    return QCoreApplication.translate("ZenClass", str(CLASS_LABELS[zen_class]))


def zen_text(value: float) -> str:
    return f"≈ {value:.2f}"


class NumberItem(QTableWidgetItem):
    """A cell that sorts by the number it holds, not by its text."""

    def __init__(self, text: str, value: float) -> None:
        super().__init__(text)
        self.setData(Qt.ItemDataRole.UserRole, value)
        self.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    def __lt__(self, other: QTableWidgetItem) -> bool:
        mine, theirs = self.data(Qt.ItemDataRole.UserRole), other.data(Qt.ItemDataRole.UserRole)
        if isinstance(mine, int | float) and isinstance(theirs, int | float):
            return mine < theirs
        return super().__lt__(other)


def readonly_table(headers: list[str]) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.verticalHeader().setVisible(False)
    return table


class SeedingView(QWidget):
    """The user's Indexer torrents in qBittorrent, with a Zen Estimate each."""

    updated = Signal(object)  # Seeding

    def __init__(self, load: Callable[[], Callable[[], Seeding]]) -> None:
        super().__init__()
        self.load = load
        self.seeding: Seeding | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        top = QHBoxLayout()
        self.title = QLabel(self.tr("<b>Seeding</b>"))
        top.addWidget(self.title)
        top.addStretch()
        self.refresh_button = QPushButton(self.tr("Refresh"))
        self.refresh_button.setToolTip(self.tr("Read your torrents from qBittorrent again"))
        self.refresh_button.clicked.connect(self.refresh)
        top.addWidget(self.refresh_button)
        layout.addLayout(top)
        self.table = readonly_table(
            [
                self.tr("Torrent"),
                self.tr("Size"),
                self.tr("Seeders"),
                self.tr("Seed age (days)"),
                self.tr("≈ Zen/day"),
            ]
        )
        age = self.table.horizontalHeaderItem(3)
        if age:
            age.setToolTip(
                self.tr(
                    "From qBittorrent's seeding time: a lower bound of c411's count, which "
                    "also includes time seeded before the torrent was added again."
                )
            )
        self.table.horizontalHeader().setSortIndicator(4, Qt.SortOrder.DescendingOrder)
        self.table.setSortingEnabled(True)
        layout.addWidget(self.table)
        self.total = QLabel()
        layout.addWidget(self.total)
        self._show_total()

    def refresh(self) -> None:
        self.refresh_button.setEnabled(False)
        self.total.setText(self.tr("Reading qBittorrent…"))
        run_in_background(self.load(), self.show_seeding, self._failed)

    def show_seeding(self, view: Seeding) -> None:
        self.refresh_button.setEnabled(True)
        self.seeding = view
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(view.rows))
        for r, row in enumerate(view.rows):
            t = row.torrent
            days = t.seeding_time / 86400
            self.table.setItem(r, 0, QTableWidgetItem(t.name))
            self.table.setItem(r, 1, NumberItem(human_size(t.total_size), t.total_size))
            self.table.setItem(r, 2, NumberItem(str(t.swarm_seeders), t.swarm_seeders))
            self.table.setItem(r, 3, NumberItem(f"{days:.0f}", days))
            zen = row.zen
            cell = NumberItem(zen_text(zen) if zen is not None else "–", zen or -1.0)
            if zen is None:
                cell.setToolTip(self.tr("Not seeding: earns no Zen"))
            self.table.setItem(r, 4, cell)
        self.table.setSortingEnabled(True)
        self._show_total()
        self.updated.emit(view)

    def _show_total(self) -> None:
        view = self.seeding
        if view is None:
            self.total.setText(self.tr("Refresh to read your c411 torrents from qBittorrent."))
            return
        self.total.setText(
            self.tr("{0} torrents seeding · {1} Zen/day (paid ≈ {2}) · estimates").format(
                view.count, zen_text(view.day.total), view.day.paid
            )
        )

    def _failed(self, error: Exception) -> None:
        self.refresh_button.setEnabled(True)
        self._show_total()
        QMessageBox.warning(self, self.tr("qBittorrent"), str(error) or type(error).__name__)


class ZenTab(QWidget):
    """Everything about Zen: what the user's seeding earns, and what to seed next."""

    def __init__(self, load_seeding: Callable[[], Callable[[], Seeding]]) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        self.seeding_view = SeedingView(load_seeding)
        layout.addWidget(self.seeding_view)
