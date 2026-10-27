"""The message composer shared by the Assistant page and the Media Center chat panel.

One rounded field with a Send/Stop button inside it, and under it the model and mode
chips. The discussion header holds the settings. The host owns what sending, stopping
and the chips do.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QComboBox, QFrame, QHBoxLayout, QPlainTextEdit, QVBoxLayout

from torrentlinker.gui.controls import icon_button, set_role


class ChatPrompt(QPlainTextEdit):
    submitted = Signal()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (
            event.modifiers() & Qt.KeyboardModifier.ShiftModifier
        ):
            self.submitted.emit()
            event.accept()
        else:
            super().keyPressEvent(event)


class ChatComposer(QFrame):
    sendRequested = Signal()
    stopRequested = Signal()
    modeRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.field = QFrame()
        self.field.setObjectName("chatComposer")
        row = QHBoxLayout(self.field)
        row.setContentsMargins(12, 8, 8, 8)
        row.setSpacing(6)
        self.prompt = ChatPrompt()
        self.prompt.setPlaceholderText(self.tr("Give a task or ask a question…"))
        self.prompt.setAccessibleName(self.tr("Message"))
        # About two lines; longer messages scroll inside the field.
        self.prompt.setFixedHeight(56)
        self.prompt.submitted.connect(self._send_or_stop)
        row.addWidget(self.prompt, 1)
        self.send = icon_button("➤", self.tr("Send"))
        self.send.setObjectName("chatSend")
        self.send.clicked.connect(self._send_or_stop)
        row.addWidget(self.send, 0, Qt.AlignmentFlag.AlignBottom)
        layout.addWidget(self.field)
        chips = QHBoxLayout()
        chips.setContentsMargins(4, 0, 4, 0)
        chips.setSpacing(4)
        self.model = QComboBox()
        self.model.setObjectName("chatModelChip")
        self.model.setAccessibleName(self.tr("Model connection"))
        self.model.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.model.setMaximumWidth(300)
        chips.addWidget(self.model)
        self.mode = set_role(icon_button("", self.tr("Switch the discussion mode")), "quiet")
        self.mode.setObjectName("chatModeChip")
        self.mode.clicked.connect(self.modeRequested.emit)
        chips.addWidget(self.mode)
        chips.addStretch()
        layout.addLayout(chips)
        self.running = False
        self.can_send = False
        self.set_state(running=False, can_send=False)

    def _send_or_stop(self):
        if self.running:
            self.stopRequested.emit()
        elif self.can_send:
            self.sendRequested.emit()

    def set_state(self, *, running: bool, can_send: bool) -> None:
        self.running, self.can_send = running, can_send
        self.send.setText("■" if running else "➤")
        label = self.tr("Stop") if running else self.tr("Send")
        self.send.setToolTip(label)
        self.send.setAccessibleName(label)
        self.send.setEnabled(running or can_send)
        self.model.setEnabled(not running)

    def set_mode(self, execute: bool) -> None:
        self.mode.setText(
            self.tr("Execute within limits") if execute else self.tr("Proposals only")
        )
