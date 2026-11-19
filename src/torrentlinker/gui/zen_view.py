"""The Zen tab: the Seeding view and, later, the Plan."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QT_TRANSLATE_NOOP, QCoreApplication, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from torrentlinker.catalogue_workspace import CategoryCard as CategoryCard
from torrentlinker.gui.catalogue_view import CatalogueBox as CatalogueBox
from torrentlinker.gui.controls import icon_button
from torrentlinker.gui.plan_view import PlanView as PlanView
from torrentlinker.gui.profile_view import ProfileView
from torrentlinker.gui.seeding_view import SeedingView as SeedingView
from torrentlinker.profile import ProfileError, ProfileProblem, UserProfile
from torrentlinker.seeding import Seeding
from torrentlinker.send import SendProgress
from torrentlinker.zen import ZenClass, ZenProfile

CLASS_LABELS = {
    ZenClass.TANKER: QT_TRANSLATE_NOOP("ZenClass", "Tanker"),
    ZenClass.SWARM_KEEPER: QT_TRANSLATE_NOOP("ZenClass", "Swarm Keeper"),
    ZenClass.REUPLOADER: QT_TRANSLATE_NOOP("ZenClass", "Reuploader"),
}


def class_label(zen_class: ZenClass) -> str:
    return QCoreApplication.translate("ZenClass", str(CLASS_LABELS[zen_class]))


def zen_text(value: float) -> str:
    return f"≈ {value:.2f}"


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
        self.seeding_view = SeedingView(load_seeding, profile, uploads)
        self.catalogue = CatalogueBox()
        self.plan_view = PlanView()
        layout.setContentsMargins(0, 0, 0, 0)
        from torrentlinker.gui.workspace_tabs import WorkspaceTabs

        self.pages = WorkspaceTabs()
        self.profile_view = ProfileView()
        self.pages.addTab(self.profile_view, self.tr("Profile"))
        catalogue_page = self.catalogue_page = self.catalogue
        self.pages.addTab(self.seeding_view, self.tr("Seeding"))
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
