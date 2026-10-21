"""The Zen tab: the Seeding view and, later, the Plan."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QT_TRANSLATE_NOOP, QCoreApplication, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
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
from torrentlinker.profile import ProfileError, ProfileProblem, UserProfile
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


KEYS_URL = "https://c411.org/user/integrations"
WARNING = QColor("#c62828")


class ZenBand(QFrame):
    """Across the top of every tab: Zen Balance, what seeding earns, Plan and Catalogue."""

    refresh_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setFrameShape(QFrame.Shape.StyledPanel)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 4, 8, 4)
        row = QHBoxLayout()
        self.balance = QLabel()
        self.seeding = QLabel()
        self.plan = QLabel()
        self.catalogue = QLabel()
        for label in (self.balance, self.seeding, self.plan, self.catalogue):
            row.addWidget(label)
            row.addSpacing(16)
        row.addStretch()
        self.refresh_button = QPushButton(self.tr("Refresh profile"))
        self.refresh_button.setToolTip(self.tr("Read your Zen Balance and Class from c411"))
        self.refresh_button.clicked.connect(self.refresh_requested)
        row.addWidget(self.refresh_button)
        outer.addLayout(row)
        self.message = QLabel()
        self.message.setWordWrap(True)
        self.message.setOpenExternalLinks(True)
        self.message.setStyleSheet(f"color: {WARNING.name()}")
        self.message.hide()
        outer.addWidget(self.message)
        self.set_balance(None)
        self.set_seeding(None)
        self.set_plan(None)
        self.set_catalogue(None)

    def set_balance(self, balance: float | None) -> None:
        value = f"{balance:.1f}" if balance is not None else "–"
        self.balance.setText(self.tr("Zen Balance: <b>{0}</b>").format(value))

    def set_seeding(self, view: Seeding | None) -> None:
        value = zen_text(view.day.total) if view is not None else "–"
        self.seeding.setText(self.tr("Seeding: <b>{0}</b> Zen/day").format(value))

    def set_plan(self, added: float | None) -> None:
        value = f"+{added:.2f}" if added is not None else "–"
        self.plan.setText(self.tr("with Plan: {0}").format(value))

    def set_catalogue(self, text: str | None) -> None:
        self.catalogue.setText(self.tr("Catalogue: {0}").format(text or "–"))

    def busy(self, busy: bool) -> None:
        self.refresh_button.setEnabled(not busy)

    def show_profile(self, profile: UserProfile) -> None:
        self.busy(False)
        self.set_balance(profile.balance)
        notes = []
        if not profile.download_allowed:
            if profile.blocked_reason == "insufficient_balance":
                notes.append(self.tr("Downloads are blocked on c411: not enough Zen."))
            else:
                notes.append(
                    self.tr("Downloads are blocked on c411 ({0}).").format(
                        profile.blocked_reason or "?"
                    )
                )
        if profile.zen_class is None:
            notes.append(
                self.tr(
                    "c411 Class “{0}” is not known here: enter your Zen Profile in Settings → Zen."
                ).format(profile.class_slug or self.tr("none"))
            )
        self._message(" ".join(notes))

    def show_profile_error(self, error: Exception) -> None:
        self.busy(False)
        problem = error.problem if isinstance(error, ProfileError) else ProfileProblem.FAILED
        texts = {
            ProfileProblem.NO_KEY: self.tr(
                "Enter your c411 key in Settings → Connections to see your Zen Balance."
            ),
            ProfileProblem.UNAUTHORIZED: self.tr(
                "c411 refused the key: check it in Settings → Connections."
            ),
            ProfileProblem.MISSING_SCOPE: self.tr(
                'Your c411 key cannot read your profile: create one with the "Profil '
                '(lecture)" scope at <a href="{0}">{0}</a>. Until then, enter your Zen '
                "Profile in Settings → Zen."
            ).format(KEYS_URL),
            ProfileProblem.RATE_LIMITED: self.tr(
                "c411 is limiting requests: refresh your profile in a minute."
            ),
        }
        self._message(
            texts.get(problem) or self.tr("Could not read your c411 profile: {0}").format(error)
        )

    def _message(self, text: str) -> None:
        self.message.setText(text)
        self.message.setVisible(bool(text))
