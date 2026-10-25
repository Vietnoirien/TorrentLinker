"""Readable chat cards, with explicit access to tool receipts."""

from __future__ import annotations

from urllib.parse import unquote, urlsplit

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QDesktopServices,
    QImage,
    QPalette,
    QTextBlockFormat,
    QTextCursor,
    QTextDocument,
)
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from torrentlinker.assistant.markdown import documentation_link, render
from torrentlinker.gui.chat_images import ChatImages
from torrentlinker.gui.request_details import RequestDetails


class MessageText(QTextBrowser):
    def __init__(self, text, parent=None, *, images=None):
        super().__init__(parent)
        self.images = images if images is not None else ChatImages(self)
        self.images.ready.connect(self.image_ready)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.document().setDocumentMargin(0)
        font = self.font()
        font.setPointSizeF(max(10.5, font.pointSizeF()))
        self.setFont(font)
        # Raw HTML stays disabled. Only the bounded public-image loader supplies resources.
        self.setHtml(render(text, proxy_images=False))
        block = self.document().begin()
        while block.isValid():
            cursor = QTextCursor(block)
            formatting = block.blockFormat()
            formatting.setBottomMargin(10)
            fragment = block.begin()
            has_image = False
            while not fragment.atEnd():
                has_image |= fragment.fragment().charFormat().isImageFormat()
                fragment += 1
            formatting.setLineHeight(
                100 if has_image else 135, QTextBlockFormat.LineHeightTypes.ProportionalHeight.value
            )
            cursor.setBlockFormat(formatting)
            block = block.next()
        self.setStyleSheet("QTextBrowser { background: transparent; border: none; padding: 0; }")
        self.anchorClicked.connect(self.open_link)
        QTimer.singleShot(0, self.fit_content)

    def loadResource(self, kind, url):
        if kind == QTextDocument.ResourceType.ImageResource:
            return self.images.request(url.toString())
        return None

    def open_link(self, url):
        if documentation_link(url.toString()):
            from torrentlinker.gui.documentation import show_guide

            parsed = urlsplit(url.toString())
            show_guide(
                self.window(), parsed.path.removeprefix("/documentation/"), unquote(parsed.fragment)
            )
            return
        if url.scheme() in {"http", "https"}:
            QDesktopServices.openUrl(url)

    def image_ready(self, url, image):
        if not isValid(self):
            return
        if image is not None:
            self.document().addResource(QTextDocument.ResourceType.ImageResource, QUrl(url), image)
        else:
            empty = QImage(1, 1, QImage.Format.Format_ARGB32)
            empty.fill(Qt.GlobalColor.transparent)
            self.document().addResource(QTextDocument.ResourceType.ImageResource, QUrl(url), empty)
        self.fit_content()

    def fit_content(self):
        if not isValid(self):
            return
        width = max(80, self.viewport().width())
        block = self.document().begin()
        while block.isValid():
            part = block.begin()
            while not part.atEnd():
                fragment = part.fragment()
                if fragment.isValid() and fragment.charFormat().isImageFormat():
                    fmt = fragment.charFormat().toImageFormat()
                    image = self.images.images.get(fmt.name())
                    if image is not None:
                        fmt.setWidth(min(width, image.width()))
                        fmt.setHeight(fmt.width() * image.height() / image.width())
                        cursor = QTextCursor(self.document())
                        cursor.setPosition(fragment.position())
                        cursor.setPosition(
                            fragment.position() + fragment.length(), QTextCursor.MoveMode.KeepAnchor
                        )
                        cursor.setCharFormat(fmt)
                part += 1
            block = block.next()
        self.document().setTextWidth(width)
        self.document().markContentsDirty(0, self.document().characterCount())
        self.setFixedHeight(max(28, int(self.document().size().height()) + 8))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit_content()


class ChatTranscript(QScrollArea):
    anchorClicked = Signal(QUrl)
    decisionSubmitted = Signal(str, int, bool)
    answerSubmitted = Signal(str, int, str)

    def __init__(self, parent=None, *, presentation_page=None, presentation_item=None):
        super().__init__(parent)
        self.presentation_page = presentation_page
        self.presentation_item = presentation_item
        self.presentation_pages = {}
        self.presentation_offsets = {}
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setStyleSheet("ChatTranscript { border: none; background: transparent; }")
        self.expanded = set()
        self.expanded_commands = set()
        self.expanded_events = set()
        self.plain_text = ""
        self.images = ChatImages(self)
        self.follow_bottom = True
        self.verticalScrollBar().rangeChanged.connect(self.follow_layout)
        self.verticalScrollBar().sliderMoved.connect(self.user_scrolled)

    def user_scrolled(self, value):
        self.follow_bottom = value >= self.verticalScrollBar().maximum() - 10

    def wheelEvent(self, event):
        super().wheelEvent(event)
        self.user_scrolled(self.verticalScrollBar().value())

    def follow_layout(self, minimum, maximum):
        if self.follow_bottom:
            self.verticalScrollBar().setValue(maximum)

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

    def add_message(self, layout, message, dark):
        user = message["role"] == "user"
        row = QHBoxLayout()
        if user:
            row.addStretch(2)
        card = QFrame()
        card.setObjectName("chatMessage")
        card.setProperty("role", message["role"])
        card.setMaximumWidth(700 if user else 860)
        background = ("#263f65" if dark else "#e8eef8") if user else "transparent"
        card.setStyleSheet(
            f"QFrame#chatMessage {{ background: {background}; border: none; border-radius: 18px; }}"
        )
        contents = QVBoxLayout(card)
        contents.setContentsMargins(
            18 if user else 2, 12 if user else 4, 18 if user else 2, 12 if user else 4
        )
        message_text = MessageText(message["content"], card, images=self.images)
        message_text.setStyleSheet(
            message_text.styleSheet()
            + "QTextBrowser { color: "
            + ("#e8edf3" if dark else "#172b33")
            + "; }"
        )
        contents.addWidget(message_text)
        row.addWidget(card, 10)
        if not user:
            row.addStretch(1)
        layout.addLayout(row)

    def add_activity(self, layout, run, indexed_events, anchor, status_text, dark):
        from torrentlinker.gui.tool_activity import ToolActivity

        assistant_bg = "#202b37" if dark else "#ffffff"
        border = "#344453" if dark else "#d4dfdf"
        activity = ToolActivity(
            run,
            indexed_events,
            (run["id"], anchor),
            self.expanded,
            self.expanded_events,
            status_text,
            lambda i: self.anchorClicked.emit(QUrl(f"receipt:{run['id']}:{i}")),
            dark=dark,
        )
        layout.addWidget(activity)
        for i, event in indexed_events:
            result = event.get("result", {})
            if (
                event.get("tool") == "present_selection"
                and result.get("presentation_id")
                and self.presentation_page
            ):
                from torrentlinker.gui.selection_cards import SelectionCards

                layout.addWidget(
                    SelectionCards(
                        result["presentation_id"],
                        self.presentation_page,
                        self.presentation_item,
                        self.images,
                        self.presentation_pages,
                        self.presentation_offsets,
                    )
                )
            if (
                event.get("status") == "waiting"
                and result.get("requires_owner_approval")
                and "decision" not in event
            ):
                panel = QFrame()
                panel.setObjectName("approvalCard")
                panel.setStyleSheet(
                    f"QFrame#approvalCard {{ background: {assistant_bg}; "
                    f"border: 1px solid {border}; border-radius: 10px; }}"
                )
                box = QVBoxLayout(panel)
                box.setContentsMargins(16, 14, 16, 14)
                heading = QLabel(self.tr("Action requires your approval"))
                heading.setStyleSheet("font-weight: 600;")
                box.addWidget(heading)
                command_id = (run["id"], i)
                request = RequestDetails(event, expanded=command_id in self.expanded_commands)
                request.toggle.toggled.connect(
                    lambda checked, key=command_id: (
                        self.expanded_commands.add(key)
                        if checked
                        else self.expanded_commands.discard(key)
                    )
                )
                box.addWidget(request)
                for title, approve in (
                    (self.tr("Approve once"), True),
                    (self.tr("Reject"), False),
                ):
                    button = QPushButton(title)
                    button.clicked.connect(
                        lambda checked=False, r=run["id"], n=i, yes=approve: (
                            self.decisionSubmitted.emit(r, n, yes)
                        )
                    )
                    box.addWidget(button)
                layout.addWidget(panel)
            if event.get("status") == "waiting" and event.get("question") and "answer" not in event:
                panel = QFrame()
                panel.setObjectName("questionCard")
                box = QVBoxLayout(panel)
                label = QLabel(event["question"]["question"])
                label.setTextFormat(Qt.TextFormat.PlainText)
                label.setWordWrap(True)
                box.addWidget(label)
                options = QComboBox()
                options.addItem(self.tr("Choose an answer…"), "")
                for option in event["question"]["options"]:
                    options.addItem(option, option)
                box.addWidget(options)
                custom = QLineEdit()
                custom.setPlaceholderText(self.tr("Or enter your own answer"))
                box.addWidget(custom)
                submit = QPushButton(self.tr("Submit answer"))
                submit.setEnabled(False)

                def enable_answer(_=None, button=submit, field=custom, choices=options):
                    button.setEnabled(bool(field.text().strip() or choices.currentData()))

                custom.textChanged.connect(enable_answer)
                options.currentIndexChanged.connect(enable_answer)
                submit.clicked.connect(
                    lambda checked=False, r=run["id"], n=i, field=custom, choices=options: (
                        self.answerSubmitted.emit(
                            r,
                            n,
                            field.text() if field.text().strip() else choices.currentData(),
                        )
                    )
                )
                box.addWidget(submit)
                layout.addWidget(panel)

    def set_runs(self, rows, status_text):
        self.plain_text = "\n".join(
            [m["content"] for r in reversed(rows) for m in r["messages"]]
            + [r["error"] for r in rows if r["error"]]
        )
        if not rows:
            self.welcome()
            return
        layout = self.content()
        dark = QApplication.palette().color(QPalette.ColorRole.Window).lightness() < 128
        for run in reversed(rows):
            messages = run["messages"]
            fallback = len(messages) - 1
            if messages and messages[-1]["role"] == "assistant":
                fallback -= 1
            groups = {}
            for index, event in enumerate(run["events"]):
                anchor = event.get("after_message_index", fallback)
                anchor = max(-1, min(anchor, len(messages) - 1))
                groups.setdefault(anchor, []).append((index, event))
            if -1 in groups:
                self.add_activity(layout, run, groups[-1], -1, status_text, dark)
            for index, message in enumerate(messages):
                self.add_message(layout, message, dark)
                if index in groups:
                    self.add_activity(layout, run, groups[index], index, status_text, dark)
            if not run["events"]:
                self.add_activity(layout, run, [], len(messages), status_text, dark)
            if run["error"]:
                error = QLabel(run["error"])
                error.setTextFormat(Qt.TextFormat.PlainText)
                error.setWordWrap(True)
                error.setStyleSheet("color: #dc756d; padding: 12px;")
                layout.addWidget(error)
            if run["status"] in {"queued", "running"}:
                busy = QLabel(self.tr("Working…"))
                busy.setStyleSheet("color: #62bdb8; padding: 4px;")
                layout.addWidget(busy)
        layout.addStretch()
