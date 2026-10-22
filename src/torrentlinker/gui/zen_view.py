"""The Zen tab: the Seeding view and, later, the Plan."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QT_TRANSLATE_NOOP, QCoreApplication, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from torrentlinker.gui.library_model import human_size
from torrentlinker.gui.tasks import run_in_background
from torrentlinker.plan import Plan, PlanGoal, PlanOptions
from torrentlinker.profile import ProfileError, ProfileProblem, UserProfile
from torrentlinker.seeding import Seeding
from torrentlinker.zen import GB, ZenClass, ZenProfile, compare_classes

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
        self._quiet = False
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

    def refresh(self, *, quiet: bool = False) -> None:
        if not self.refresh_button.isEnabled():
            return
        self._quiet = quiet
        self.refresh_button.setEnabled(False)
        if not quiet:
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
            self.table.setItem(
                r,
                2,
                NumberItem(str(t.swarm_seeders) if t.swarm_seeders >= 0 else "–", t.swarm_seeders),
            )
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
        if not self._quiet:
            QMessageBox.warning(self, self.tr("qBittorrent"), str(error) or type(error).__name__)


class ClassComparison(QGroupBox):
    """Current seeding estimated in every Class, to help choose during c411's window."""

    uploads_changed = Signal(int)

    def __init__(self, profile: Callable[[], ZenProfile], uploads: int) -> None:
        super().__init__(self.tr("Class comparison"))
        self.profile = profile
        self.seeding: Seeding | None = None
        layout = QHBoxLayout(self)
        self.labels: dict[ZenClass, QLabel] = {}
        for c in ZenClass:
            label = QLabel()
            label.setTextFormat(Qt.TextFormat.RichText)
            self.labels[c] = label
            layout.addWidget(label)
            layout.addSpacing(24)
        self.labels[ZenClass.REUPLOADER].setToolTip(
            self.tr(
                "Rough: a Reuploader is paid per upload, counted here at the guide's "
                "upper figure of about 0.43 Zen per upload a day."
            )
        )
        layout.addStretch()
        layout.addWidget(QLabel(self.tr("Your uploads")))
        self.uploads = QSpinBox()
        self.uploads.setRange(0, 100_000)
        self.uploads.setValue(uploads)
        self.uploads.valueChanged.connect(self._uploads_edited)
        layout.addWidget(self.uploads)
        self.show_seeding(None)

    def _uploads_edited(self, value: int) -> None:
        self.uploads_changed.emit(value)
        self.show_seeding(self.seeding)

    def show_seeding(self, view: Seeding | None) -> None:
        self.seeding = view
        profile = self.profile()
        days = compare_classes(profile, view.active if view else [], self.uploads.value())
        for c, label in self.labels.items():
            text = self.tr("{0}: {1} Zen/day").format(class_label(c), zen_text(days[c].total))
            if c is ZenClass.REUPLOADER:
                text += " " + self.tr("(rough)")
            if c is profile.zen_class:
                text = "<b>" + text + "</b> " + self.tr("← your Class")
            label.setText(text)


class CatalogueBox(QGroupBox):
    """Fetch the whole Catalogue on demand, with progress, pause and resume."""

    start_requested = Signal()
    pause_requested = Signal()

    def __init__(self) -> None:
        super().__init__(self.tr("Catalogue"))
        layout = QHBoxLayout(self)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status, 1)
        self.fetch_button = QPushButton()
        self.fetch_button.setToolTip(
            self.tr(
                "Fetch the available torrents in every category. You can pause and resume "
                "after closing the app. The Indexer may limit how far the Catalogue can be read."
            )
        )
        self.fetch_button.clicked.connect(self._clicked)
        layout.addWidget(self.fetch_button)
        self.running = False
        self.set_state(False, False)

    def _clicked(self) -> None:
        (self.pause_requested if self.running else self.start_requested).emit()

    def set_state(self, running: bool, paused: bool) -> None:
        self.running = running
        if running:
            self.fetch_button.setText(self.tr("Pause"))
        elif paused:
            self.fetch_button.setText(self.tr("Resume fetching all categories"))
        else:
            self.fetch_button.setText(self.tr("Fetch all categories"))

    def set_status(self, text: str) -> None:
        self.status.setText(text)


class PlanView(QGroupBox):
    """The Plan: what to download and seed next for the most Zen."""

    make_requested = Signal()
    send_requested = Signal()
    categories_changed = Signal(object)  # set[int] | None
    stop_fetch_requested = Signal()
    options_changed = Signal(object)  # PlanOptions

    def __init__(self) -> None:
        super().__init__(self.tr("Plan"))
        self.plan: Plan | None = None
        layout = QVBoxLayout(self)
        self._busy = False
        self.summary = QLabel(
            self.tr(
                "Choose whether to prioritize Zen/day or torrent notes, within your "
                "download limit and available disk space."
            )
        )
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        options = QHBoxLayout()
        self.goal = QComboBox()
        self.goal.addItem(self.tr("Zen/day"), PlanGoal.ZEN.value)
        self.goal.addItem(self.tr("Note"), PlanGoal.NOTE.value)
        self.goal.setToolTip(
            self.tr(
                "Zen/day maximizes estimated earnings. "
                "Note prefers the highest-note torrents first."
            )
        )
        label = QLabel(self.tr("Optimize for"))
        label.setBuddy(self.goal)
        options.addWidget(label)
        options.addWidget(self.goal)
        self.download_limit = QDoubleSpinBox()
        self.download_limit.setRange(0, 1_000_000)
        self.download_limit.setDecimals(2)
        self.download_limit.setSuffix(self.tr(" GB"))
        self.download_limit.setSpecialValueText(self.tr("No limit"))
        self.download_limit.setToolTip(
            self.tr(
                "Maximum total download size for this Plan. 1 GB = 1,000,000,000 bytes. "
                "Reseeds use no download budget."
            )
        )
        label = QLabel(self.tr("Download limit"))
        label.setBuddy(self.download_limit)
        options.addWidget(label)
        options.addWidget(self.download_limit)
        options.addStretch()
        layout.addLayout(options)
        limits = QHBoxLayout()
        self.limit_torrents = QCheckBox(self.tr("Limit torrents"))
        self.torrent_limit = QSpinBox()
        self.torrent_limit.setRange(1, 1_000_000)
        self.torrent_limit.setValue(100)
        self.torrent_limit.setToolTip(
            self.tr(
                "Maximum torrents added by this Plan, including Reseeds. "
                "Your overall torrent cap still applies."
            )
        )
        self.torrent_limit.setEnabled(False)
        limits.addWidget(self.limit_torrents)
        limits.addWidget(self.torrent_limit)
        limits.addSpacing(16)
        self.low_seeders = QCheckBox(self.tr("Low seeders only"))
        self.seeder_limit = QSpinBox()
        self.seeder_limit.setRange(1, 1_000_000)
        self.seeder_limit.setValue(10)
        self.seeder_limit.setSuffix(self.tr(" seeders max."))
        tooltip = self.tr(
            "Only include torrents with at most this many current seeders, before you join. "
            "Applies to downloads and Reseeds, in both Note and Zen/day modes."
        )
        self.low_seeders.setToolTip(tooltip)
        self.seeder_limit.setToolTip(tooltip)
        self.seeder_limit.setEnabled(False)
        limits.addWidget(self.low_seeders)
        limits.addWidget(self.seeder_limit)
        limits.addStretch()
        layout.addLayout(limits)
        top = QHBoxLayout()
        self.categories_button = QToolButton()
        self.categories_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.categories_button.setToolTip(self.tr("Categories this Plan draws from"))
        self.categories_menu = QMenu(self.categories_button)
        self.categories_button.setMenu(self.categories_menu)
        self.category_options: list[tuple[int, str, bool]] = []
        self.chosen_categories: set[int] | None = None
        top.addWidget(self.categories_button)
        self._refresh_categories_label()
        self.make_button = QPushButton(self.tr("Make a Plan"))
        self.make_button.clicked.connect(self.make_requested)
        top.addWidget(self.make_button)
        self.stop_fetch_button = QPushButton(self.tr("Stop fetching and plan now"))
        self.stop_fetch_button.setToolTip(
            self.tr("Make the Plan from the Catalogue fetched so far; the fetch resumes next time")
        )
        self.stop_fetch_button.clicked.connect(self.stop_fetch_requested)
        self.stop_fetch_button.hide()
        top.addWidget(self.stop_fetch_button)
        self.send_button = QPushButton(self.tr("Send to qBittorrent…"))
        self.send_button.setToolTip(
            self.tr(
                "Download each .torrent directly from c411 and add it to its Download "
                "Folder. A torrent whose files already exist there is refused."
            )
        )
        self.send_button.setEnabled(False)
        self.send_button.clicked.connect(self.send_requested)
        top.addWidget(self.send_button)
        self.action_row = top
        top.addStretch()
        layout.addLayout(top)
        self.space_table = readonly_table(
            [
                self.tr("Disk / Download Folder"),
                self.tr("Free now"),
                self.tr("Reserved"),
                self.tr("Plan downloads"),
                self.tr("Free after Plan"),
            ]
        )
        self.space_table.setToolTip(
            self.tr(
                "Free after Plan includes the reserved disk-space margin. "
                "Download Folders on the same disk are counted once."
            )
        )
        self.space_table.setMaximumHeight(150)
        self.space_table.hide()
        layout.addWidget(self.space_table)
        self.table = readonly_table(
            [
                self.tr("Torrent"),
                self.tr("Size"),
                self.tr("Seeders"),
                self.tr("Note"),
                self.tr("≈ Zen/day"),
                self.tr("Download Folder"),
            ]
        )
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Interactive)
        # Plan order first: Reseeds, then downloads; a header click sorts.
        self.table.horizontalHeader().setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
        self.table.setSortingEnabled(True)
        layout.addWidget(self.table)
        self.goal.currentIndexChanged.connect(self._options_changed)
        self.download_limit.valueChanged.connect(self._options_changed)
        self.limit_torrents.toggled.connect(self._options_changed)
        self.torrent_limit.valueChanged.connect(self._options_changed)
        self.low_seeders.toggled.connect(self._options_changed)
        self.seeder_limit.valueChanged.connect(self._options_changed)

    def set_options(self, value: PlanOptions) -> None:
        controls = [
            self.goal,
            self.download_limit,
            self.limit_torrents,
            self.torrent_limit,
            self.low_seeders,
            self.seeder_limit,
        ]
        for control in controls:
            control.blockSignals(True)
        try:
            self.goal.setCurrentIndex(self.goal.findData(value.goal.value))
            self.download_limit.setValue(value.max_download_bytes / GB)
            self.limit_torrents.setChecked(value.max_torrents is not None)
            self.torrent_limit.setValue(value.max_torrents or 100)
            self.torrent_limit.setEnabled(not self._busy and value.max_torrents is not None)
            self.low_seeders.setChecked(value.max_seeders is not None)
            self.seeder_limit.setValue(value.max_seeders if value.max_seeders is not None else 10)
            self.seeder_limit.setEnabled(not self._busy and value.max_seeders is not None)
        finally:
            for control in controls:
                control.blockSignals(False)

    def _options_changed(self) -> None:
        self.torrent_limit.setEnabled(not self._busy and self.limit_torrents.isChecked())
        self.seeder_limit.setEnabled(not self._busy and self.low_seeders.isChecked())
        self.options_changed.emit(
            PlanOptions(
                PlanGoal(self.goal.currentData()),
                round(self.download_limit.value() * GB),
                self.torrent_limit.value() if self.limit_torrents.isChecked() else None,
                self.seeder_limit.value() if self.low_seeders.isChecked() else None,
            )
        )

    def invalidate(self) -> None:
        self.begin()
        self.busy(False)
        self.summary.setText(self.tr("Plan options changed. Make a new Plan to apply them."))

    # Categories ------------------------------------------------------------

    def set_category_options(
        self, options: list[tuple[int, str, bool]], chosen: set[int] | None
    ) -> None:
        """Offer these (id, name, is_subcategory) categories; `chosen` None means all."""
        self.category_options = options
        self.chosen_categories = chosen
        self.categories_menu.clear()
        everything = self.categories_menu.addAction(self.tr("All categories"))
        everything.setCheckable(True)
        everything.setChecked(chosen is None)
        everything.triggered.connect(lambda: self._choose(None))
        self.categories_menu.addSeparator()
        for cid, name, sub in options:
            action = self.categories_menu.addAction(("    " if sub else "") + name)
            action.setCheckable(True)
            action.setChecked(chosen is not None and cid in chosen)
            action.toggled.connect(lambda on, cid=cid: self._toggle(cid, on))
        self._refresh_categories_label()

    def _toggle(self, cid: int, on: bool) -> None:
        chosen = set(self.chosen_categories or ())
        chosen.add(cid) if on else chosen.discard(cid)
        self._choose(chosen or None)

    def _choose(self, chosen: set[int] | None) -> None:
        self.set_category_options(self.category_options, chosen)
        self.categories_changed.emit(chosen)

    def _refresh_categories_label(self) -> None:
        chosen = self.chosen_categories
        if chosen is None:
            text = self.tr("All categories")
        else:
            names = [name for cid, name, _sub in self.category_options if cid in chosen]
            text = (
                ", ".join(names)
                if len(names) <= 2
                else self.tr("{0} categories").format(len(names))
            )
        self.categories_button.setText(text + " ▾")

    def fetching(self, fetching: bool) -> None:
        """While the Plan's categories are fetched, offer to stop and plan right away."""
        self.stop_fetch_button.setVisible(fetching)
        self.stop_fetch_button.setEnabled(fetching)

    def begin(self) -> None:
        """Clear the previous result while a new Plan is being prepared."""
        self.plan = None
        self.table.setRowCount(0)
        self.space_table.setRowCount(0)
        self.space_table.hide()
        self.busy(True)

    def busy(self, busy: bool, text: str | None = None) -> None:
        self._busy = busy
        self.make_button.setEnabled(not busy)
        self.goal.setEnabled(not busy)
        self.download_limit.setEnabled(not busy)
        self.limit_torrents.setEnabled(not busy)
        self.torrent_limit.setEnabled(not busy and self.limit_torrents.isChecked())
        self.low_seeders.setEnabled(not busy)
        self.seeder_limit.setEnabled(not busy and self.low_seeders.isChecked())
        self.categories_button.setEnabled(not busy)
        self.send_button.setEnabled(not busy and bool(self.plan and self.plan.items))
        if busy:
            self.summary.setText(text or self.tr("Making a Plan…"))

    def show_plan(self, plan: Plan) -> None:
        self.plan = plan
        self.busy(False)
        self.table.setSortingEnabled(False)
        self.table.horizontalHeader().setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
        self.table.setRowCount(len(plan.items))
        for r, item in enumerate(plan.items):
            c = item.candidate
            size_text = self.tr("Reseed (0 Go)") if c.reseed else human_size(c.size)
            self.table.setItem(r, 0, QTableWidgetItem(c.title))
            self.table.setItem(r, 1, NumberItem(size_text, c.download_size))
            self.table.setItem(r, 2, NumberItem(str(c.seeders), c.seeders))
            self.table.setItem(
                r,
                3,
                NumberItem(f"{item.note:.2f}" if item.note is not None else "–", item.note or 0),
            )
            self.table.setItem(r, 4, NumberItem(zen_text(item.zen), item.zen))
            self.table.setItem(r, 5, QTableWidgetItem(str(c.folder) if c.folder else ""))
        self.table.setSortingEnabled(True)
        self.space_table.setRowCount(len(plan.disk_spaces))
        for row, space in enumerate(plan.disk_spaces):
            self.space_table.setItem(row, 0, QTableWidgetItem(str(space.folder)))
            for col, amount in enumerate(
                (space.free, space.reserved, space.download, space.after_plan), 1
            ):
                self.space_table.setItem(row, col, NumberItem(human_size(amount), amount))
        self.space_table.setVisible(bool(plan.disk_spaces))
        self.space_table.setFixedHeight(
            min(
                150,
                self.space_table.horizontalHeader().height()
                + sum(self.space_table.rowHeight(i) for i in range(len(plan.disk_spaces)))
                + 2,
            )
        )
        if not plan.items:
            self.summary.setText(
                self.tr(
                    "Nothing to add: fetch the Catalogue, set Download Folders, or free some space."
                )
            )
            return
        payback = plan.payback_days
        self.summary.setText(
            self.tr(
                "{0} torrents · ≈ +{1} Zen/day · {2} Go to download · paid back in ≈ {3} days"
            ).format(
                len(plan.items),
                f"{plan.zen_added:.2f}",
                f"{plan.download_size / 1e9:.1f}",
                f"{payback:.0f}" if payback is not None else "–",
            )
            + (
                self.tr(" · average note {0}").format(f"{plan.average_note:.2f}")
                if plan.average_note is not None
                else ""
            )
        )

    def failed(self, error: Exception) -> None:
        self.busy(False)
        self.summary.setText(self.tr("Could not make a Plan: {0}").format(error))


class ZenTab(QWidget):
    """Everything about Zen: what the user's seeding earns, and what to seed next."""

    def __init__(
        self,
        load_seeding: Callable[[], Callable[[], Seeding]],
        profile: Callable[[], ZenProfile],
        uploads: int = 0,
    ) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        self.seeding_view = SeedingView(load_seeding)
        self.comparison = ClassComparison(profile, uploads)
        self.seeding_view.updated.connect(self.comparison.show_seeding)
        self.catalogue = CatalogueBox()
        self.plan_view = PlanView()
        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(self.seeding_view)
        split.addWidget(self.plan_view)
        layout.addWidget(split, 1)
        layout.addWidget(self.comparison)
        layout.addWidget(self.catalogue)


KEYS_URL = "https://c411.org/user/integrations"
WARNING = QColor("#c62828")


class ZenBand(QFrame):
    """Across the top of every tab: Zen Balance, what seeding earns, Plan and Catalogue."""

    refresh_requested = Signal()
    catalogue_changed = Signal(str)

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
        self.catalogue_changed.emit(self.catalogue.text())

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
