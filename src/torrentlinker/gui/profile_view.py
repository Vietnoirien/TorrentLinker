"""The account workspace, shared in structure with the WebUI Profile tab."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from torrentlinker.gui.controls import set_role
from torrentlinker.gui.library_model import human_size


def number(value: Any) -> str:
    return f"{value:,.1f}".removesuffix(".0") if type(value) in (int, float) else "—"


def size(value: Any) -> str:
    return human_size(int(value)) if type(value) in (int, float) else "—"


def timestamp(value: Any) -> str:
    return datetime.fromtimestamp(value).astimezone().strftime("%d %b %Y, %H:%M") if value else "—"


class ProfileView(QWidget):
    refresh_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 16, 8, 8)
        layout.setSpacing(16)
        heading = QHBoxLayout()
        heading_label = QLabel(self.tr("Your c411 profile"))
        heading_label.setProperty("role", "heading")
        heading.addWidget(heading_label)
        heading.addStretch()
        self.refresh_button = QPushButton(self.tr("Refresh profile"))
        set_role(self.refresh_button, "primary")
        self.refresh_button.clicked.connect(self.refresh_requested)
        heading.addWidget(self.refresh_button)
        layout.addLayout(heading)
        self.notice = self.label()
        layout.addWidget(self.notice)
        identity = QFrame()
        identity.setObjectName("zenBand")
        identity_layout = QVBoxLayout(identity)
        self.identity = self.label()
        self.identity.setProperty("role", "brand")
        self.meta = self.label()
        identity_layout.addWidget(self.identity)
        identity_layout.addWidget(self.meta)
        layout.addWidget(identity)
        cards = QHBoxLayout()
        self.balance, self.class_level, self.access = (self.label() for _ in range(3))
        for label in (self.balance, self.class_level, self.access):
            label.setProperty("role", "brand")
        for title, value in (
            (self.tr("Zen balance"), self.balance),
            (self.tr("Class & level"), self.class_level),
            (self.tr("Download access"), self.access),
        ):
            box = QGroupBox(title.replace("&", "&&"))
            content = QVBoxLayout(box)
            content.addWidget(value)
            cards.addWidget(box, 1)
        layout.addLayout(cards)
        columns = QHBoxLayout()
        progress = QGroupBox(self.tr("Progression"))
        content = QVBoxLayout(progress)
        self.progress = self.label()
        self.xp = QProgressBar()
        self.xp.setRange(0, 100)
        content.addWidget(self.progress)
        content.addWidget(self.xp)
        self.quests = self.label()
        content.addWidget(self.quests)
        self.paths = self.label()
        content.addWidget(self.paths)
        content.addStretch()
        columns.addWidget(progress, 1)
        transfers = QGroupBox(self.tr("Transfers · API"))
        grid = QGridLayout(transfers)
        self.transfers: dict[str, QLabel] = {}
        for col, text in enumerate(("", self.tr("Uploaded"), self.tr("Downloaded"))):
            grid.addWidget(QLabel(text), 0, col)
        for row, (key, title) in enumerate(
            (
                ("actual", self.tr("Actual")),
                ("credit", self.tr("Credit")),
                ("total", self.tr("Total")),
            ),
            1,
        ):
            grid.addWidget(QLabel(title), row, 0)
            for col, direction in enumerate(("uploaded", "downloaded"), 1):
                label = self.label()
                self.transfers[f"{direction}_{key}"] = label
                grid.addWidget(label, row, col)
        columns.addWidget(transfers, 1)
        layout.addLayout(columns)
        advanced = QGroupBox(self.tr("Advanced activity · Browser companion"))
        content = QVBoxLayout(advanced)
        self.advanced_status = self.label()
        self.advanced_values = self.label()
        content.addWidget(self.advanced_status)
        self.advanced_metrics = QWidget()
        metrics = QHBoxLayout(self.advanced_metrics)
        metrics.setContentsMargins(0, 0, 0, 0)
        self.active_seeds, self.validated_uploads, self.total_seed_time = (
            self.label() for _ in range(3)
        )
        for title, value in (
            (self.tr("Active seeds"), self.active_seeds),
            (self.tr("Validated uploads"), self.validated_uploads),
            (self.tr("Total seed time"), self.total_seed_time),
        ):
            box = QGroupBox(title)
            metric_layout = QVBoxLayout(box)
            value.setProperty("role", "brand")
            metric_layout.addWidget(value)
            metrics.addWidget(box, 1)
        content.addWidget(self.advanced_metrics)
        content.addWidget(self.advanced_values)
        content.addWidget(
            self.label_with(
                self.tr(
                    "Connect and manage the companion in Settings → Companion. "
                    "Your login stays in the browser."
                )
            )
        )
        layout.addWidget(advanced)
        layout.addStretch()
        self.show_state({})

    def label_with(self, text: str) -> QLabel:
        label = self.label()
        label.setText(text)
        return label

    def label(self) -> QLabel:
        label = QLabel()
        label.setWordWrap(True)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        return label

    def show_state(self, state: dict[str, Any]) -> None:
        api = state.get("api") or {}
        errors = {
            "no-key": self.tr("Add an API key with profile:read access in Settings → Indexer."),
            "unauthorized": self.tr("API key refused. Check Settings → Indexer and refresh."),
            "missing-scope": self.tr("The API key needs profile:read access."),
            "rate-limited": self.tr("The tracker asked us to wait. Try refreshing later."),
            "failed": self.tr("Profile unavailable. Check your connection and refresh."),
        }
        self.notice.setText(
            errors.get(state.get("error") or "", "")
            or (
                self.tr("Waiting for an API update. Retrying automatically.")
                if state.get("api_stale")
                else self.tr(
                    "Account information from the c411 API. "
                    "Updates automatically every two minutes."
                )
            )
        )
        self.identity.setText(api.get("username") or self.tr("Connect your c411 account"))
        self.meta.setText(
            self.tr("Account {0} · Member since {1} · API updated {2}").format(
                api.get("account_id") or "—",
                (api.get("member_since") or "—")[:10],
                timestamp(state.get("api_updated_at")),
            )
        )
        self.balance.setText(
            self.tr("{0} Zen\nEarned {1} · Spent {2}").format(
                number(api.get("balance")),
                number(api.get("total_earned")),
                number(api.get("total_spent")),
            )
        )
        self.class_level.setText(
            self.tr("{0}\nLevel {1} · Tree bonus {2}%").format(
                (api.get("class_slug") or "—").replace("_", " ").title(),
                number(api.get("level")),
                number(api.get("tree_bonus", 0) * 100) if api else "—",
            )
        )
        access = self.tr("Allowed") if api.get("download_allowed") else self.tr("Blocked")
        self.access.setText(
            (access if api else "—")
            + "\n"
            + (
                str(api.get("blocked_reason") or "")
                if api.get("download_allowed") is False
                else self.tr("Freeleech active")
                if api.get("freeleech")
                else self.tr("Standard download rules")
            )
        )
        into, remaining = api.get("xp_into_level"), api.get("xp_to_next_level")
        self.progress.setText(
            self.tr("{0} XP in this level · {1} XP to next level").format(
                number(into), number(remaining)
            )
        )
        self.xp.setValue(
            round(100 * into / (into + remaining))
            if isinstance(into, (int, float))
            and isinstance(remaining, (int, float))
            and into + remaining > 0
            else 0
        )
        self.xp.setVisible(into is not None and remaining is not None)
        self.quests.setText(
            self.tr("Quests {0} / {1} · Stars {2}").format(
                number(api.get("quests_completed")),
                number(api.get("quests_total")),
                number(api.get("stars")),
            )
        )
        for key, label in self.transfers.items():
            label.setText(size(api.get(key)))
        names = {
            "seed": self.tr("Seeding"),
            "upload": self.tr("Uploading"),
            "specialization": self.tr("Specialization"),
            "competitivity": self.tr("Competitiveness"),
        }
        paths = [api.get("grade", "").title()]
        for key, title in names.items():
            quest = api.get("quests", {}).get(key) or {}
            paths.append(
                f"{title}    {number(quest.get('questsCompleted'))}"
                f" / {number(quest.get('questsTotal'))}"
            )
        self.paths.setText("\n".join(paths))
        companion = state.get("companion")
        self.advanced_metrics.setVisible(bool(companion))
        if companion:
            freshness = (
                self.tr("Waiting for a browser update")
                if state.get("stale")
                else self.tr("Automatic sync connected")
            )
            self.advanced_status.setText(
                self.tr("{0} · c411 browser · Last sync {1}").format(
                    freshness, timestamp(state.get("received_at"))
                )
            )
            details = companion.get("details") or {}
            self.active_seeds.setText(number((companion.get("activeSeeds") or {}).get("total")))
            self.validated_uploads.setText(number(details.get("validatedUploadsCount")))
            self.total_seed_time.setText(
                self.tr("{0} days").format(
                    number(details["totalSeedingTimeSec"] / 86400)
                    if details.get("totalSeedingTimeSec") is not None
                    else "—"
                )
            )
            self.advanced_values.setText(
                self.tr(
                    "Actual upload {0} · Actual download {1}\n"
                    "Credited upload {2} · Credited download {3}"
                ).format(
                    size(details.get("actualUploaded")),
                    size(details.get("actualDownloaded")),
                    size(details.get("creditedUploaded")),
                    size(details.get("creditedDownloaded")),
                )
            )
        else:
            self.advanced_status.setText(
                self.tr("Connected. Waiting for the first automatic browser update.")
                if state.get("paired")
                else self.tr("Connect the companion to see advanced activity.")
            )
            self.advanced_values.setText(
                self.tr(
                    "Active seeds, validated uploads and total seed time "
                    "require a browser snapshot."
                )
            )
