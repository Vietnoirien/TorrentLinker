"""Offline illustrated guides, using Qt's Markdown reader."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSignalBlocker, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QImage, QTextBlockFormat, QTextCursor, QTextDocument
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QSplitter,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from torrentlinker import documentation as docs


class GuideBrowser(QTextBrowser):
    def __init__(self) -> None:
        super().__init__()
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)
        self.setMinimumWidth(180)
        self.document().setDocumentMargin(22)
        self.sourceChanged.connect(self._format_page)
        font = self.font()
        font.setPointSize(11)
        self.setFont(font)
        self._resizing_images = False
        self.resize_timer = QTimer(self)
        self.resize_timer.setSingleShot(True)
        self.resize_timer.timeout.connect(self._resize_images)

    def loadResource(self, kind: int, url: QUrl | str):  # type: ignore[no-untyped-def]
        url = QUrl(url)
        try:
            path = docs.document_path(str(Path(url.toLocalFile()).relative_to(docs.root())))
        except (ValueError, OSError):
            return None
        if kind == QTextDocument.ResourceType.ImageResource:
            image = QImage(str(path))
            return (
                image.scaledToWidth(
                    min(image.width(), 660, max(80, self.viewport().width() - 64)),
                    Qt.TransformationMode.SmoothTransformation,
                )
                if not image.isNull()
                else image
            )
        if kind == QTextDocument.ResourceType.MarkdownResource:
            return path.read_text(encoding="utf-8")
        return None

    def _format_page(self) -> None:
        block = self.document().begin()
        while block.isValid():
            format = block.blockFormat()
            heading = format.headingLevel()
            format.setTopMargin(22 if heading and block.position() else 8)
            format.setBottomMargin(14 if heading else 12)
            format.setLineHeight(
                110 if format.nonBreakableLines() else 140,
                QTextBlockFormat.LineHeightTypes.ProportionalHeight.value,
            )
            if block.text().strip() == "\ufffc":
                format.setLineHeight(100, QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
                format.setAlignment(Qt.AlignmentFlag.AlignHCenter)
                format.setTopMargin(18)
                format.setBottomMargin(20)
            QTextCursor(block).setBlockFormat(format)
            block = block.next()

    def resizeEvent(self, event):  # type: ignore[no-untyped-def]
        super().resizeEvent(event)
        if not self._resizing_images and event.size().width() != event.oldSize().width():
            self.resize_timer.start(150)

    def _resize_images(self) -> None:
        if self.source().isEmpty():
            return
        position = self.verticalScrollBar().value()
        # Reloading briefly removes scrollbars. Ignore the resulting viewport resizes,
        # otherwise each reload schedules another one and flashes Qt's wait cursor.
        self._resizing_images = True
        try:
            self.reload()
            self._format_page()
            self.verticalScrollBar().setValue(position)
        finally:
            self._resizing_images = False


class DocumentationTab(QWidget):
    def __init__(self, language: str = "en") -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        title = QLabel(self.tr("Documentation"))
        title.setProperty("role", "heading")
        toolbar.addWidget(title)
        toolbar.addStretch()
        self.language = QComboBox()
        self.language.addItem("Français", "fr")
        self.language.addItem("English", "en")
        self.language.setCurrentIndex(self.language.findData(language))
        self.language.setAccessibleName(self.tr("Guide language"))
        toolbar.addWidget(self.language)
        layout.addLayout(toolbar)
        split = QSplitter()
        side = QWidget()
        left = QVBoxLayout(side)
        left.setContentsMargins(0, 0, 8, 0)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText(self.tr("Find a guide…"))
        left.addWidget(self.filter)
        self.chapters = QListWidget()
        self.chapters.setSpacing(3)
        left.addWidget(self.chapters)
        split.addWidget(side)
        content = QWidget()
        right = QVBoxLayout(content)
        right.setContentsMargins(0, 0, 0, 0)
        navigation = QHBoxLayout()
        back = QPushButton(self.tr("Back"))
        forward = QPushButton(self.tr("Forward"))
        online = QPushButton(self.tr("Open online"))
        navigation.addWidget(back)
        navigation.addWidget(forward)
        navigation.addStretch()
        navigation.addWidget(online)
        right.addLayout(navigation)
        self.browser = GuideBrowser()
        right.addWidget(self.browser, 1)
        split.addWidget(content)
        split.setSizes([240, 900])
        split.setChildrenCollapsible(False)
        layout.addWidget(split, 1)
        back.clicked.connect(self.browser.backward)
        forward.clicked.connect(self.browser.forward)
        self.browser.backwardAvailable.connect(back.setEnabled)
        self.browser.forwardAvailable.connect(forward.setEnabled)
        back.setEnabled(False)
        forward.setEnabled(False)
        online.clicked.connect(self._online)
        self.browser.anchorClicked.connect(self._follow)
        self.browser.sourceChanged.connect(self._source_changed)
        self.language.currentIndexChanged.connect(self._chapters)
        self.chapters.currentRowChanged.connect(self._select)
        self.filter.textChanged.connect(self._filter)
        self._chapters()

    def _chapters(self) -> None:
        index = max(0, self.chapters.currentRow())
        self.pages = docs.guides(self.language.currentData())
        self.chapters.clear()
        self.chapters.addItems([p["title"] for p in self.pages])
        self.chapters.setCurrentRow(index)
        self._filter(self.filter.text())

    def _source_changed(self, url: QUrl) -> None:
        try:
            name = Path(url.toLocalFile()).relative_to(docs.root()).as_posix()
        except (ValueError, OSError):
            return
        parts = name.split("/")
        with QSignalBlocker(self.chapters):
            if len(parts) > 2 and parts[0] == "guide" and parts[1] in {"fr", "en"}:
                if self.language.currentData() != parts[1]:
                    with QSignalBlocker(self.language):
                        self.language.setCurrentIndex(self.language.findData(parts[1]))
                    self.pages = docs.guides(parts[1])
                    self.chapters.clear()
                    self.chapters.addItems([p["title"] for p in self.pages])
                    self._filter(self.filter.text())
            for index, page in enumerate(self.pages):
                if page["path"] == name:
                    self.chapters.setCurrentRow(index)
                    break
            else:
                self.chapters.clearSelection()

    def _filter(self, text: str) -> None:
        for index in range(self.chapters.count()):
            item = self.chapters.item(index)
            item.setHidden(text.casefold() not in item.text().casefold())

    def _select(self, index: int) -> None:
        if index >= 0:
            self.open_guide(self.pages[index]["path"])

    def open_guide(self, name: str, fragment: str = "") -> None:
        try:
            url = QUrl.fromLocalFile(str(docs.document_path(name)))
        except (ValueError, OSError):
            self.browser.setPlainText(self.tr("Guide unavailable. Use Open online to read it."))
            return
        if fragment:
            url.setFragment(fragment)
        self.browser.setSource(url, QTextDocument.ResourceType.MarkdownResource)
        if fragment:
            self._scroll_to_heading(fragment)
            # The dialog may not have a laid-out viewport until the next event loop turn.
            QTimer.singleShot(0, self.browser, lambda: self._scroll_to_heading(fragment))

    def _scroll_to_heading(self, fragment: str) -> None:
        if self.browser.source().fragment() != fragment:
            return
        # QTextDocument's Markdown importer does not create named heading anchors.
        block = self.browser.document().begin()
        seen: dict[str, int] = {}
        while block.isValid():
            if block.blockFormat().headingLevel():
                anchor = docs.heading_anchor(block.text())
                number = seen.get(anchor, 0)
                seen[anchor] = number + 1
                if anchor + ("-" + str(number) if number else "") == fragment:
                    self.browser.setTextCursor(QTextCursor(block))
                    self.browser.ensureCursorVisible()
                    break
            block = block.next()

    def _follow(self, url: QUrl) -> None:
        if url.scheme() in {"http", "https"}:
            QDesktopServices.openUrl(url)
            return
        try:
            resolved = self.browser.source().resolved(url)
            path = Path(resolved.toLocalFile()).resolve()
            if path in {docs.root().parent / "README.md", docs.root().parent / "README.en.md"}:
                QDesktopServices.openUrl(QUrl(docs.ONLINE + "../" + path.name))
                return
            name = path.relative_to(docs.root()).as_posix()
        except (ValueError, OSError):
            return
        try:
            docs.document_path(name)
        except (ValueError, OSError):
            QDesktopServices.openUrl(QUrl(docs.ONLINE + name))
            return
        self.open_guide(name, resolved.fragment())

    def _online(self) -> None:
        try:
            name = Path(self.browser.source().toLocalFile()).relative_to(docs.root()).as_posix()
        except (ValueError, OSError):
            name = "README.md"
        QDesktopServices.openUrl(QUrl(docs.ONLINE + name))


def show_guide(parent: QWidget, name: str, fragment: str = "") -> QDialog:
    """Open an allowlisted guide in a nonmodal reader for an Assistant citation."""
    allowed = {g["path"] for language in ("en", "fr") for g in docs.guides(language)}
    if name not in allowed:
        raise ValueError("Not a bundled guide.")
    docs.document_path(name)
    dialog = QDialog(parent)
    dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    dialog.setWindowTitle("TorrentLinker documentation")
    dialog.resize(1000, 750)
    layout = QVBoxLayout(dialog)
    language = name.split("/")[1]
    reader = DocumentationTab(language)
    layout.addWidget(reader)
    reader.open_guide(name, fragment)
    dialog.show()
    return dialog
