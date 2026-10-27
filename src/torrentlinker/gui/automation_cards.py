"""The Assistant's scheduled tasks as cards: name, schedule, state and one main action."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from torrentlinker.gui.controls import icon_button


class AutomationCards(QScrollArea):
    editRequested = Signal(dict)
    toggleRequested = Signal(dict)
    runRequested = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.snapshot: list[dict] | None = None
        self.set_rows([])

    def schedule_text(self, task):
        if task.get("frequency") == "interval":
            return self.tr("Every %1 min").replace("%1", str(task.get("interval_minutes", 60)))
        at = task.get("at", "09:00")
        if task.get("frequency") == "weekly":
            names = (
                self.tr("Mon"),
                self.tr("Tue"),
                self.tr("Wed"),
                self.tr("Thu"),
                self.tr("Fri"),
                self.tr("Sat"),
                self.tr("Sun"),
            )
            days = ", ".join(names[d] for d in sorted(task.get("weekdays", [])) if 0 <= d < 7)
            return self.tr("Weekly, %1 at %2").replace("%1", days).replace("%2", at)
        return self.tr("Daily at %1").replace("%1", at)

    def state_text(self, task):
        if not task.get("enabled"):
            return self.tr("Paused")
        if task.get("blocked"):
            return self.tr("Waiting for its actions or your review")
        when = datetime.fromtimestamp(task["next_at"]).astimezone().strftime("%d/%m %H:%M")
        return self.tr("Next run %1").replace("%1", when)

    def set_rows(self, rows):
        if rows == self.snapshot:
            return
        self.snapshot = rows
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 4, 8, 4)
        layout.setSpacing(10)
        if not rows:
            empty = QLabel(self.tr("No automations yet. Create one to run a task on a schedule."))
            empty.setWordWrap(True)
            empty.setProperty("role", "muted")
            layout.addWidget(empty)
        for task in rows:
            layout.addWidget(self.card(task))
        layout.addStretch()
        self.setWidget(body)

    def card(self, task):
        card = QFrame()
        card.setObjectName("automationCard")
        row = QHBoxLayout(card)
        row.setContentsMargins(16, 12, 10, 12)
        text = QVBoxLayout()
        text.setSpacing(3)
        name = QLabel(task["name"])
        name.setObjectName("automationName")
        name.setTextFormat(Qt.TextFormat.PlainText)
        text.addWidget(name)
        detail = QLabel(self.schedule_text(task) + " · " + self.state_text(task))
        detail.setProperty("role", "muted")
        text.addWidget(detail)
        if task.get("last_error"):
            error = QLabel(task["last_error"])
            error.setWordWrap(True)
            error.setTextFormat(Qt.TextFormat.PlainText)
            error.setProperty("role", "error")
            text.addWidget(error)
        row.addLayout(text, 1)
        if task.get("enabled"):
            main = QPushButton(self.tr("Run now"))
            main.setEnabled(not task.get("blocked"))
            main.clicked.connect(lambda: self.runRequested.emit(task))
        else:
            main = QPushButton(self.tr("Enable"))
            main.clicked.connect(lambda: self.toggleRequested.emit(task))
        row.addWidget(main, 0, Qt.AlignmentFlag.AlignVCenter)
        menu = QMenu(card)
        menu.addAction(self.tr("Edit"), lambda: self.editRequested.emit(task))
        menu.addAction(
            self.tr("Pause") if task.get("enabled") else self.tr("Enable"),
            lambda: self.toggleRequested.emit(task),
        )
        more = icon_button("⋯", self.tr("More"))
        more.setMenu(menu)
        more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        row.addWidget(more, 0, Qt.AlignmentFlag.AlignVCenter)
        return card
