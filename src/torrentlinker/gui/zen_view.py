"""The Zen tab: the Seeding view and, later, the Plan."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QT_TRANSLATE_NOOP, QCoreApplication, Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from torrentlinker.catalogue_workspace import CategoryCard as CategoryCard
from torrentlinker.gui.catalogue_view import CatalogueBox as CatalogueBox
from torrentlinker.gui.controls import ScrollSpinBox as QSpinBox
from torrentlinker.gui.controls import icon_button, set_role
from torrentlinker.gui.plan_view import PlanView as PlanView
from torrentlinker.gui.profile_view import ProfileView
from torrentlinker.gui.seeding_tree import SeedingTree
from torrentlinker.gui.tables import sortable_table
from torrentlinker.gui.tasks import run_in_background
from torrentlinker.profile import ProfileError, ProfileProblem, UserProfile
from torrentlinker.seeding import Seeding
from torrentlinker.send import SendProgress
from torrentlinker.zen import ZenClass, ZenProfile, compare_classes

CLASS_LABELS = {
    ZenClass.TANKER: QT_TRANSLATE_NOOP("ZenClass", "Tanker"),
    ZenClass.SWARM_KEEPER: QT_TRANSLATE_NOOP("ZenClass", "Swarm Keeper"),
    ZenClass.REUPLOADER: QT_TRANSLATE_NOOP("ZenClass", "Reuploader"),
}


def class_label(zen_class: ZenClass) -> str:
    return QCoreApplication.translate("ZenClass", str(CLASS_LABELS[zen_class]))


def zen_text(value: float) -> str:
    return f"≈ {value:.2f}"


def readonly_table(headers: list[str]) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    sortable_table(table)
    return table


def clear_rows(table: QTableWidget, rows: int) -> None:
    """Empty the table, then size it for `rows` new rows.

    Replacing the items of a filled table resizes its columns to their contents after
    every cell: about 100 s for 1,300 rows. Filling empty rows takes a fraction of a
    second.
    """
    table.setSortingEnabled(False)
    table.setRowCount(0)
    table.setRowCount(rows)


class SeedingView(QWidget):
    """The user's Indexer torrents in qBittorrent, with a Zen Estimate each."""

    updated = Signal(object)  # Seeding
    unavailable = Signal()

    def __init__(self, load: Callable[[], Callable[[], Seeding]]) -> None:
        super().__init__()
        self.load = load
        self.seeding: Seeding | None = None
        self._quiet = False
        # The tree is costly to rebuild. While the main window says it is out of sight, the
        # newest data waits here and the tree is rebuilt when the page is shown again.
        self.defer_tree: Callable[[], bool] = lambda: False
        self._tree_dirty = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        top = QHBoxLayout()
        self.title = QLabel(self.tr("<b>Seeding</b>"))
        top.addWidget(self.title)
        top.addStretch()
        self.refresh_button = QPushButton(self.tr("Refresh"))
        set_role(self.refresh_button, "quiet")
        self.refresh_button.setToolTip(self.tr("Read your torrents from your torrent client again"))
        self.refresh_button.clicked.connect(self.refresh)
        top.addWidget(self.refresh_button)
        layout.addLayout(top)
        self.search = QLineEdit()
        self.search.setAccessibleName(self.tr("Filter torrents or categories"))
        self.search.setClearButtonEnabled(True)
        layout.addWidget(self.search)
        self.table = SeedingTree()
        self.search.textChanged.connect(self.table.filter)
        self.search.setPlaceholderText(self.tr("Filter torrents or categories…"))
        self.expand_button = QPushButton(self.tr("Expand all"))
        set_role(self.expand_button, "quiet")
        self.expand_button.clicked.connect(self.table.expandAll)
        self.collapse_button = QPushButton(self.tr("Collapse all"))
        set_role(self.collapse_button, "quiet")
        self.collapse_button.clicked.connect(self.table.collapseAll)
        top.insertWidget(1, self.expand_button)
        top.insertWidget(2, self.collapse_button)
        layout.addWidget(self.table)
        self.total = QLabel()
        layout.addWidget(self.total)
        self.tag_status = QLabel()
        self.tag_status.setWordWrap(True)
        self.tag_status.setProperty("role", "muted")
        layout.addWidget(self.tag_status)
        self._show_total()

    def refresh(self, *, quiet: bool = False) -> None:
        if not self.refresh_button.isEnabled():
            return
        self._quiet = quiet
        self.refresh_button.setEnabled(False)
        if not quiet:
            self.total.setText(self.tr("Reading your torrent client…"))
        run_in_background(self.load(), self.show_seeding, self._failed)

    def show_seeding(self, view: Seeding) -> None:
        self.refresh_button.setEnabled(True)
        self.seeding = view
        if self.defer_tree():
            self._tree_dirty = True
        else:
            self._tree_dirty = False
            self.table.show_seeding(view)
        report = view.tag_sync
        self.tag_status.setToolTip("")
        if report is None:
            self.tag_status.clear()
        elif not report.supported:
            self.tag_status.setText(
                self.tr(
                    "Category tags: Deluge's single label is kept for Verification. "
                    "The category tree is available here."
                )
            )
        elif report.failed:
            self.tag_status.setText(
                self.tr("Category tags: {0} updated, {1} failed; the next refresh retries.").format(
                    report.updated, report.failed
                )
            )
            self.tag_status.setToolTip("\n".join(report.errors))
        else:
            self.tag_status.setText(
                self.tr(
                    "Category tags: {0} updated, {1} already set, {2} without a known category."
                ).format(report.updated, report.unchanged, report.unknown)
            )
            self.tag_status.setToolTip("")
        self._show_total()
        self.updated.emit(view)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._tree_dirty:
            # Let the page appear first; the rebuild follows on the next turn of the event loop.
            QTimer.singleShot(0, self._rebuild_tree)

    def _rebuild_tree(self) -> None:
        if self._tree_dirty and self.seeding is not None and self.isVisible():
            self._tree_dirty = False
            self.table.show_seeding(self.seeding)

    def _show_total(self) -> None:
        view = self.seeding
        if view is None:
            self.total.setText(
                self.tr("Refresh to read your c411 torrents from your torrent client.")
            )
            return
        self.total.setText(
            self.tr("{0} torrents seeding · {1} Zen/day (paid ≈ {2}) · estimates").format(
                view.count, zen_text(view.day.total), view.day.paid
            )
        )

    def _failed(self, error: Exception) -> None:
        self.unavailable.emit()
        self.refresh_button.setEnabled(True)
        self._show_total()
        if not self._quiet:
            QMessageBox.warning(self, self.tr("Torrent client"), str(error) or type(error).__name__)


class ClassComparison(QGroupBox):
    """Current seeding estimated in every Class, to help choose during c411's window."""

    uploads_changed = Signal(int)

    def __init__(self, profile: Callable[[], ZenProfile], uploads: int) -> None:
        super().__init__(self.tr("Class comparison"))
        self.profile = profile
        self.seeding: Seeding | None = None
        # The estimate for every Class takes about a second on a large library. Like the
        # seeding tree it waits while out of sight, and the page computes it off the GUI thread.
        self.defer: Callable[[], bool] = lambda: False
        self.background = False
        self._dirty = False
        self._generation = 0
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
        if self.defer():
            self._dirty = True
            return
        self._compute()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._dirty:
            QTimer.singleShot(0, self._compute)

    def _compute(self) -> None:
        if not isValid(self):
            return
        self._dirty = False
        profile = self.profile()
        active = self.seeding.active if self.seeding else []
        uploads = self.uploads.value()
        if not self.background:
            self._show_days(profile, compare_classes(profile, active, uploads))
            return
        self._generation += 1
        generation = self._generation

        def done(days) -> None:
            if isValid(self) and generation == self._generation:
                self._show_days(profile, days)

        run_in_background(lambda: compare_classes(profile, active, uploads), done, lambda _e: None)

    def _show_days(self, profile: ZenProfile, days) -> None:
        for c, label in self.labels.items():
            text = self.tr("{0}: {1} Zen/day").format(class_label(c), zen_text(days[c].total))
            if c is ZenClass.REUPLOADER:
                text += " " + self.tr("(rough)")
            if c is profile.zen_class:
                text = "<b>" + text + "</b> " + self.tr("← your Class")
            label.setText(text)


def duration_text(seconds: float) -> str:
    minutes = round(seconds / 60)
    if minutes >= 48 * 60:
        return QCoreApplication.translate("PlanView", "{0} days").format(f"{minutes / 1440:.1f}")
    if minutes < 60:
        return QCoreApplication.translate("PlanView", "{0} min").format(max(minutes, 1))
    return QCoreApplication.translate("PlanView", "{0} h {1:02d}").format(
        minutes // 60, minutes % 60
    )


class ZenTab(QWidget):
    """Everything about Zen: what the user's seeding earns, and what to seed next."""

    def defer_while_hidden(self, hidden: Callable[[], bool]) -> None:
        """Hold back the costly seeding views while `hidden()` says the page is out of sight."""
        self.seeding_view.defer_tree = hidden
        self.comparison.defer = hidden

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
        self.comparison.background = True
        self.catalogue = CatalogueBox()
        self.plan_view = PlanView()
        layout.setContentsMargins(0, 0, 0, 0)
        from torrentlinker.gui.workspace_tabs import WorkspaceTabs

        self.pages = WorkspaceTabs()
        self.profile_view = ProfileView()
        self.pages.addTab(self.profile_view, self.tr("Profile"))
        seeding_page = QWidget()
        seeding_layout = QVBoxLayout(seeding_page)
        seeding_layout.setContentsMargins(0, 0, 0, 0)
        seeding_layout.addWidget(self.seeding_view, 1)
        seeding_layout.addWidget(self.comparison)
        catalogue_page = self.catalogue_page = self.catalogue
        self.pages.addTab(seeding_page, self.tr("Seeding"))
        self.pages.addTab(self.plan_view, self.tr("Plan"))
        self.pages.addTab(catalogue_page, self.tr("Catalogue"))
        layout.addWidget(self.pages)


KEYS_URL = "https://c411.org/user/integrations"
WARNING = QColor("#c62828")


class ZenBand(QFrame):
    """In the window's footer, on the right: Zen Balance, what seeding earns, Plan and
    Catalogue. `message`, for profile problems, goes above the workspace instead."""

    refresh_requested = Signal()
    catalogue_changed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("zenBand")
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 4, 0)
        row.setSpacing(6)
        self.balance = QLabel()
        self.seeding = QLabel()
        self.plan = QLabel()
        self.catalogue = QLabel()
        for i, label in enumerate((self.balance, self.seeding, self.plan, self.catalogue)):
            if i:
                row.addWidget(QLabel("·"))
            row.addWidget(label)
        self.refresh_button = icon_button("⟳", self.tr("Refresh profile"))
        self.refresh_button.setToolTip(self.tr("Read your Zen Balance and Class from c411"))
        self.refresh_button.clicked.connect(self.refresh_requested)
        row.addWidget(self.refresh_button)
        self.message = QLabel()
        self.message.setWordWrap(True)
        self.message.setOpenExternalLinks(True)
        self.message.setProperty("role", "error")
        self.message.hide()
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

    def set_sending(self, progress: SendProgress | None, added: float | None = None) -> None:
        """Sending progress after the Plan's Zen; with None, the Plan's Zen alone."""
        self.set_plan(added)
        if progress is None:
            return
        self.plan.setText(
            self.plan.text()
            + " · "
            + self.tr("Sending the Plan: <b>{0}/{1}</b>").format(progress.done, progress.total)
            + (" " + self.tr("(c411 limit, waiting)") if progress.retry_at is not None else "")
        )

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
        self.message.setVisible(bool(text) and not self.isHidden())  # hidden with the band
