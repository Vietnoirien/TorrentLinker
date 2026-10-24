"""Readable chat cards, with explicit access to tool receipts."""

from __future__ import annotations

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QPalette, QTextBlockFormat, QTextCursor, QTextDocument
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


class MessageText(QTextBrowser):
    def __init__(self, text, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.document().setDocumentMargin(0)
        font = self.font()
        font.setPointSizeF(max(10.5, font.pointSizeF()))
        self.setFont(font)
        # Disable embedded HTML and all resource loading from model/user text.
        self.document().setMarkdown(text, QTextDocument.MarkdownFeature.MarkdownNoHTML)
        block = self.document().begin()
        while block.isValid():
            cursor = QTextCursor(block)
            formatting = block.blockFormat()
            formatting.setBottomMargin(10)
            formatting.setLineHeight(135, QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
            cursor.setBlockFormat(formatting)
            block = block.next()
        self.setStyleSheet("QTextBrowser { background: transparent; border: none; padding: 0; }")
        self.anchorClicked.connect(self.open_link)

    def loadResource(self, kind, url):
        return None

    def open_link(self, url):
        if url.scheme() in {"http", "https"}:
            QDesktopServices.openUrl(url)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.document().setTextWidth(max(80, self.viewport().width()))
        self.setFixedHeight(max(28, int(self.document().size().height()) + 8))


class ChatTranscript(QScrollArea):
    anchorClicked = Signal(QUrl)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setStyleSheet("ChatTranscript { border: none; background: transparent; }")
        self.expanded = set()
        self.plain_text = ""

    def toPlainText(self):
        return self.plain_text

    def content(self):
        old = self.takeWidget()
        if old:
            old.deleteLater()
        outer = QWidget()
        row = QHBoxLayout(outer)
        row.setContentsMargins(12, 12, 12, 12)
        column = QWidget()
        column.setMaximumWidth(900)
        layout = QVBoxLayout(column)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)
        row.addStretch(1)
        row.addWidget(column, 20)
        row.addStretch(1)
        self.setWidget(outer)
        return layout

    def welcome(self):
        self.plain_text = self.tr("What would you like to do?")
        layout = self.content()
        layout.addStretch()
        title = QLabel(self.plain_text)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 24px; font-weight: 600; padding: 12px;")
        layout.addWidget(title)
        subtitle = QLabel(self.tr("Find films, prepare an Upload or build your next Zen Plan."))
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)
        layout.addStretch()

    def set_runs(self, rows, status_text):
        self.plain_text = "\n".join(
            [m["content"] for r in reversed(rows) for m in r["messages"]]
            + [r["error"] for r in rows if r["error"]]
        )
        if not rows:
            self.welcome()
            return
        layout = self.content()
        palette = self.palette()
        dark = palette.color(QPalette.ColorRole.Window).lightness() < 128
        assistant_bg = "#202b37" if dark else "#ffffff"
        user_bg = "#234750" if dark else "#e0f1ef"
        border = "#344453" if dark else "#d4dfdf"
        for run in reversed(rows):
            for message in run["messages"]:
                user = message["role"] == "user"
                row = QHBoxLayout()
                if user:
                    row.addStretch(1)
                card = QFrame()
                card.setObjectName("chatMessage")
                card.setMaximumWidth(760 if user else 860)
                card.setStyleSheet(
                    f"QFrame#chatMessage {{ background: {user_bg if user else assistant_bg}; "
                    f"border: 1px solid {border}; border-radius: 14px; }}"
                )
                contents = QVBoxLayout(card)
                contents.setContentsMargins(18, 14, 18, 14)
                contents.setSpacing(8)
                role = QLabel(self.tr("You") if user else "Assistant")
                role.setStyleSheet("font-weight: 600; color: #62bdb8; background: transparent;")
                contents.addWidget(role)
                contents.addWidget(MessageText(message["content"], card))
                row.addWidget(card, 12)
                if not user:
                    row.addStretch(1)
                layout.addLayout(row)
            if run["error"]:
                error = QLabel(run["error"])
                error.setTextFormat(Qt.TextFormat.PlainText)
                error.setWordWrap(True)
                error.setStyleSheet(
                    "background: #442d2e; color: #ffd5cf; border: 1px solid #785052; "
                    "border-radius: 10px; padding: 14px;"
                )
                layout.addWidget(error)
            if run["status"] in {"queued", "running"}:
                busy = QLabel(self.tr("Working…"))
                busy.setStyleSheet("color: #62bdb8; padding: 4px;")
                layout.addWidget(busy)
            activity = QWidget()
            al = QVBoxLayout(activity)
            al.setContentsMargins(4, 0, 4, 0)
            toggle = QToolButton()
            toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            toggle.setText(
                self.tr("Activity") + f" · {len(run['events'])} · " + status_text(run["status"])
            )
            toggle.setCheckable(True)
            toggle.setChecked(run["id"] in self.expanded)
            details = QWidget()
            dl = QVBoxLayout(details)
            dl.setContentsMargins(12, 6, 0, 6)
            stats = QLabel(
                self.tr("%1 calls · %2 tokens")
                .replace("%1", str(run["calls"]))
                .replace("%2", str(run["tokens"]))
            )
            dl.addWidget(stats)
            if run.get("compactions"):
                dl.addWidget(QLabel(self.tr("Context compacted; full history retained.")))
            for i, event in enumerate(run["events"]):
                link = QPushButton(event["tool"] + " · " + status_text(event["status"]))
                link.setFlat(True)
                link.clicked.connect(
                    lambda checked=False, url=f"receipt:{run['id']}:{i}": self.anchorClicked.emit(
                        QUrl(url)
                    )
                )
                dl.addWidget(link)
                result = event.get("result", {})
                if result.get("requires_owner_approval"):
                    approval = QPushButton(self.tr("Review proposal"))
                    approval.clicked.connect(
                        lambda checked=False, identifier=result["id"]: self.anchorClicked.emit(
                            QUrl("proposal:" + identifier)
                        )
                    )
                    # Approval never disappears behind the collapsed activity section.
                    layout.addWidget(approval)

            def expand(value, identifier=run["id"], panel=details, button=toggle):
                panel.setVisible(value)
                button.setArrowType(Qt.ArrowType.DownArrow if value else Qt.ArrowType.RightArrow)
                self.expanded.add(identifier) if value else self.expanded.discard(identifier)

            toggle.toggled.connect(expand)
            expand(toggle.isChecked())
            al.addWidget(toggle)
            al.addWidget(details)
            layout.addWidget(activity)
        layout.addStretch()
