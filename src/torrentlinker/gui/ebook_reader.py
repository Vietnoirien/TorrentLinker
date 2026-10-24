"""The reading room: a local bookshelf alongside an EPUB, PDF and comic reader."""

from __future__ import annotations

import html
import threading
import zipfile
from collections.abc import Sequence
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from PySide6.QtCore import QByteArray, QSignalBlocker, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QFont, QImage, QTextBlockFormat, QTextCursor, QTextDocument
from PySide6.QtPdf import QPdfDocument
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from torrentlinker.ebooks import (
    BookError,
    BookLibrary,
    ComicBook,
    EpubBook,
    ReadingProgress,
    discover_books,
    member_path,
)
from torrentlinker.gui.book_pages import BookPages
from torrentlinker.gui.tasks import run_in_background


class _BookHtml(HTMLParser):
    """Keep readable markup; all resources stay inside the selected EPUB."""

    allowed = {
        "p",
        "div",
        "span",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "br",
        "hr",
        "em",
        "strong",
        "b",
        "i",
        "u",
        "s",
        "sub",
        "sup",
        "blockquote",
        "pre",
        "code",
        "ul",
        "ol",
        "li",
        "table",
        "tr",
        "td",
        "th",
        "a",
        "img",
    }

    def __init__(self, source: str, base: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base = base
        self.parts: list[str] = []
        self.skip = 0
        self.feed(source)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "image":
            tag = "img"
            attrs = [
                ("src" if key in {"href", "xlink:href"} else key, value) for key, value in attrs
            ]
        if tag in {"script", "style", "head", "iframe", "object"}:
            self.skip += 1
        if self.skip or tag not in self.allowed:
            return
        kept = []
        for key, value in attrs:
            if value is None:
                continue
            if key in {"id", "name", "alt", "colspan", "rowspan"}:
                kept.append(f'{key}="{html.escape(value, quote=True)}"')
            elif (tag, key) in {("img", "src"), ("a", "href")}:
                try:
                    path = member_path(self.base, value)
                except BookError:
                    continue
                fragment = QUrl(value).fragment()
                url = QUrl()
                url.setScheme("book")
                url.setPath("/" + path)
                url.setFragment(fragment)
                kept.append(f'{key}="{html.escape(url.toString(), quote=True)}"')
        self.parts.append(f"<{tag} {' '.join(kept)}>")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "head", "iframe", "object"}:
            self.skip = max(0, self.skip - 1)
        elif not self.skip and tag in self.allowed:
            self.parts.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.parts.append(html.escape(data))


class _EpubDocument(QTextDocument):
    def loadResource(self, kind: int, name: QUrl | str) -> Any:  # noqa: N802
        owner = self.parent()
        assert isinstance(owner, EpubText)
        return owner.loadResource(kind, name)


class EpubText(QWidget):
    anchorClicked = Signal(QUrl)

    def __init__(self) -> None:
        super().__init__()
        self.book: EpubBook | None = None
        self._document = _EpubDocument(self)
        self.document().setDocumentMargin(40)
        self.image_bounds = QSize(500, 700)
        self.document().setDefaultStyleSheet(
            "p { margin-top: 0; margin-bottom: 12px; line-height: 145%; }"
            "h1, h2, h3 { margin-top: 20px; margin-bottom: 24px; }"
        )
        self.setFont(QFont("serif", 16))

    def document(self) -> QTextDocument:
        return self._document

    def setHtml(self, source: str) -> None:  # noqa: N802
        self._document.setHtml(source)

    def toPlainText(self) -> str:  # noqa: N802
        return self._document.toPlainText()

    def clear(self) -> None:
        self._document.clear()

    def setFont(self, font: QFont | str | Sequence[str]) -> None:  # noqa: N802
        super().setFont(font)
        self._document.setDefaultFont(self.font())

    def loadResource(self, kind: int, name: QUrl | str) -> Any:  # noqa: N802 - Qt override
        name = QUrl(name)
        if self.book is None or name.scheme() != "book":
            return QByteArray()
        try:
            path = name.path().lstrip("/")
            if kind == QTextDocument.ResourceType.ImageResource:
                image = QImage.fromData(self.book.read(path))
                return image
        except (OSError, ValueError, BookError, KeyError, RuntimeError, zipfile.BadZipFile):
            pass
        return QByteArray()


class BookReader(QWidget):
    library_toggled = Signal()

    def __init__(self, progress_path: Path) -> None:
        super().__init__()
        self.progress = ReadingProgress(progress_path)
        self.path: Path | None = None
        self.book: EpubBook | ComicBook | None = None
        self.page = 0
        self._section_count = 1
        self._generation = 0
        self._loading = False
        self._anchor = ""
        self.title = QLabel(self.tr("Choose a book from your library"))
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        self.title.setMinimumWidth(0)
        self.title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        title_font = self.title.font()
        title_font.setPointSize(12)
        title_font.setBold(True)
        self.title.setFont(title_font)
        self.notice = QLabel(self.tr("A quiet place for the books you keep alive."))
        self.notice.setTextFormat(Qt.TextFormat.PlainText)
        self.notice.setWordWrap(True)
        self.notice.setProperty("role", "muted")
        self.previous = QPushButton("‹")
        self.next = QPushButton("›")
        self.previous.setAccessibleName(self.tr("Previous"))
        self.previous.setToolTip(self.tr("Previous"))
        self.next.setAccessibleName(self.tr("Next"))
        self.next.setToolTip(self.tr("Next"))
        self.previous.clicked.connect(lambda: self.turn(-1))
        self.next.clicked.connect(lambda: self.turn(1))
        self.position = QSpinBox()
        self.position.setAccessibleName(self.tr("Page"))
        self.position.setRange(1, 1)
        self.position.valueChanged.connect(self._jump_page)
        self.total = QLabel()
        self.chapters = QComboBox()
        self.chapters.setMinimumWidth(0)
        self.chapters.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.chapters.setAccessibleName(self.tr("Chapters"))
        self.chapters.activated.connect(self.go)
        self.smaller = QPushButton("−")
        self.smaller.setAccessibleName(self.tr("Zoom out"))
        self.larger = QPushButton("+")
        self.larger.setAccessibleName(self.tr("Zoom in"))
        self.smaller.clicked.connect(lambda: self.zoom(-1))
        self.larger.clicked.connect(lambda: self.zoom(1))
        self.library_toggle = QPushButton(self.tr("Bookshelf"))
        self.library_toggle.clicked.connect(self.library_toggled)
        self.library_toggle.setToolTip(self.tr("Show or hide the bookshelf"))
        self.chapters.setFixedWidth(110)
        self.chapters.setToolTip(self.tr("Chapters"))
        self.title.setToolTip(self.title.text())
        toolbar = QHBoxLayout()
        for widget in (self.library_toggle, self.title, self.chapters, self.smaller, self.larger):
            toolbar.addWidget(widget, 1 if widget is self.title else 0)
        self.text = EpubText()
        self.text.setParent(self)
        self.text.hide()
        self.text.anchorClicked.connect(self._link)
        self.paper = BookPages()
        self.comic = BookPages()
        self.pdf = BookPages()
        self.pdf_document = QPdfDocument(self)
        self.pages = QStackedWidget()
        for surface in (self.paper, self.pdf, self.comic):
            self.pages.addWidget(surface)
            surface.turn_requested.connect(self.turn)
        self.paper.changed.connect(self._leaf_changed)
        self.paper.resized.connect(self._resize_text)
        self.paper.link_clicked.connect(lambda link: self._link(QUrl(link)))
        self.page_info = QLabel()
        controls = QHBoxLayout()
        controls.addWidget(self.notice, 1)
        for control in (self.previous, self.position, self.total, self.next):
            controls.addWidget(control)
        controls.addWidget(self.page_info, 1)
        self.page_info.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        for button in (self.previous, self.next, self.smaller, self.larger):
            button.setFixedWidth(36)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addLayout(toolbar)
        layout.addWidget(self.pages, 1)
        layout.addLayout(controls)
        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.setInterval(500)
        self.save_timer.timeout.connect(self.save_position)
        self._controls(False)

    def _controls(self, ready: bool) -> None:
        count = self._section_count
        self.previous.setEnabled(
            ready and (self.page > 0 or (isinstance(self.book, EpubBook) and self.paper.leaf > 0))
        )
        self.next.setEnabled(
            ready
            and (
                self.page + 1 < count
                or (
                    isinstance(self.book, EpubBook)
                    and self.paper.leaf + self.paper.spread < self.paper.count
                )
            )
        )
        for control in (self.position, self.chapters):
            control.setEnabled(ready)
        for button in (self.smaller, self.larger):
            button.setVisible(isinstance(self.book, EpubBook))
            button.setEnabled(ready)
        self.chapters.setVisible(isinstance(self.book, EpubBook))

    def open_book(self, path: Path) -> None:
        self.clear()
        self.path = path
        self.title.setText(path.stem.replace("_", " "))
        self.notice.setText(self.tr("Opening book…"))
        self._loading = True
        generation = self._generation
        page, fraction = self.progress.get(path)
        if path.suffix.lower() == ".pdf":
            result = self.pdf_document.load(str(path))
            if result != QPdfDocument.Error.None_:
                self._failed(generation, BookError(self.tr("Unreadable or password-protected PDF")))
                return
            self.pages.setCurrentWidget(self.pdf)
            self._ready(self.pdf_document.pageCount(), page, 0)
            return

        def loaded(book: EpubBook | ComicBook) -> None:
            if generation != self._generation:
                return
            self.book = book
            if isinstance(book, EpubBook):
                self.title.setText(book.title)
                self.text.book = book
                self.chapters.addItems([chapter.title for chapter in book.chapters])
                self.pages.setCurrentWidget(self.paper)
                self._ready(len(book.chapters), page, fraction)
            else:
                self.pages.setCurrentWidget(self.comic)
                self._ready(len(book.pages), page, fraction)

        run_in_background(
            lambda: EpubBook(path) if path.suffix.lower() == ".epub" else ComicBook(path),
            loaded,
            lambda error: self._failed(generation, error),
        )

    def _ready(self, count: int, page: int, fraction: float) -> None:
        if count < 1:
            self._failed(self._generation, BookError(self.tr("This book has no readable pages")))
            return
        self._section_count = count
        with QSignalBlocker(self.position):
            self.position.setMaximum(count)
        self.total.setText(self.tr("of {0}").format(count))
        self.go(min(page, count - 1), fraction=fraction)

    def go(self, page: int, *, fraction: float = 0) -> None:
        if self.path is None or not 0 <= page < self._section_count:
            return
        self.save_position()
        surface = self.pages.currentWidget()
        if isinstance(surface, BookPages) and not self._loading:
            surface.capture_turn(1 if page >= self.page else -1)
        self._generation += 1
        generation = self._generation
        self.page = page
        self._loading = True
        self._controls(False)
        with QSignalBlocker(self.position):
            self.position.setValue(page + 1)
        self.chapters.setCurrentIndex(page)
        book = self.book
        if self.pages.currentWidget() is self.pdf:
            size = (
                self.pdf_document.pagePointSize(page)
                .toSize()
                .scaled(QSize(1600, 2200), Qt.AspectRatioMode.KeepAspectRatio)
            )
            self.pdf.show_image(self.pdf_document.render(page, size))
            self._page_ready(fraction)
            return
        self.notice.setText(self.tr("Loading page…"))

        def work() -> str | QImage:
            if isinstance(book, EpubBook):
                chapter = book.chapters[page]
                return "".join(
                    _BookHtml(
                        book.read(chapter.name).decode("utf-8-sig", errors="replace"), chapter.name
                    ).parts
                )
            assert isinstance(book, ComicBook)
            image = QImage.fromData(book.read(book.pages[page]))
            if image.isNull():
                raise BookError(self.tr("This image could not be decoded"))
            return image

        def loaded(content: str | QImage) -> None:
            if generation != self._generation:
                return
            if isinstance(content, str):
                self._render_text(content, fraction)
            else:
                self.comic.show_image(content)
            self._page_ready(fraction)

        run_in_background(work, loaded, lambda error: self._failed(generation, error))

    def _page_ready(self, fraction: float) -> None:
        self.notice.setText(
            self.tr("Chapter {0} / {1}").format(self.page + 1, self._section_count)
            if isinstance(self.book, EpubBook)
            else self.tr("Page")
        )
        generation = self._generation

        def restore() -> None:
            if generation != self._generation:
                return
            self._loading = False
            self._controls(True)
            self.title.setToolTip(self.title.text())
            surface = self.pages.currentWidget()
            if isinstance(surface, BookPages):
                surface.animate()
                surface.setFocus()
            if self._anchor:
                self._scroll_to_anchor(self._anchor)
                self._anchor = ""
            self._leaf_changed()
            self._schedule_save()

        QTimer.singleShot(0, restore)

    def _failed(self, generation: int, error: Exception) -> None:
        if generation != self._generation:
            return
        self._loading = True  # do not overwrite the last good reading position
        self.notice.setText(self.tr("Could not open this book: {0}").format(str(error)))
        self._controls(self.book is not None)

    def _link(self, url: QUrl) -> None:
        if not isinstance(self.book, EpubBook) or url.scheme() != "book":
            return
        name = url.path().lstrip("/")
        for i, chapter in enumerate(self.book.chapters):
            if chapter.name == name:
                if self.page == i:
                    self._scroll_to_anchor(url.fragment())
                else:
                    self._anchor = url.fragment()
                    self.go(i)
                break

    def _scroll_to_anchor(self, anchor: str) -> None:
        block = self.text.document().begin()
        while block.isValid():
            fragment = block.begin()
            while not fragment.atEnd():
                if anchor in fragment.fragment().charFormat().anchorNames():
                    y = self.text.document().documentLayout().blockBoundingRect(block).top()
                    self.paper.leaf = min(
                        self.paper.count - 1, int(y / self.paper.page_size.height())
                    )
                    self.paper.update()
                    self._leaf_changed()
                    return
                fragment += 1
            block = block.next()

    def _render_text(self, content: str, fraction: float) -> None:
        self._content = content
        self.text.image_bounds = QSize(
            max(80, int(self.paper.page_size.width()) - 80),
            max(80, int(self.paper.page_size.height()) - 100),
        )
        self.text.setHtml(content)
        block = self.text.document().begin()
        while block.isValid():
            cursor = QTextCursor(block)
            fmt = block.blockFormat()
            fmt.setLineHeight(145, QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
            iterator = block.begin()
            has_image = False
            while not iterator.atEnd():
                fragment = iterator.fragment()
                if fragment.charFormat().isImageFormat():
                    has_image = True
                    image_format = fragment.charFormat().toImageFormat()
                    image = self.text.document().resource(
                        QTextDocument.ResourceType.ImageResource, QUrl(image_format.name())
                    )
                    if isinstance(image, QImage) and not image.isNull():
                        size = image.size().scaled(
                            self.text.image_bounds, Qt.AspectRatioMode.KeepAspectRatio
                        )
                        image_format.setWidth(size.width())
                        image_format.setHeight(size.height())
                        image_cursor = QTextCursor(self.text.document())
                        image_cursor.setPosition(fragment.position())
                        image_cursor.setPosition(
                            fragment.position() + fragment.length(), QTextCursor.MoveMode.KeepAnchor
                        )
                        image_cursor.setCharFormat(image_format)
                iterator += 1
            if has_image:
                fmt.setLineHeight(100, QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
                fmt.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cursor.setBlockFormat(fmt)
            block = block.next()
        self.paper.set_document(self.text.document(), fraction)

    def _resize_text(self) -> None:
        if isinstance(self.book, EpubBook) and hasattr(self, "_content") and not self._loading:
            self._render_text(self._content, self.paper.fraction)

    def _leaf_changed(self) -> None:
        if not hasattr(self, "save_timer"):
            return
        if isinstance(self.book, EpubBook):
            with QSignalBlocker(self.position):
                self.position.setMaximum(self.paper.count)
                self.position.setValue(self.paper.leaf + 1)
            self.total.setText(self.tr("of {0}").format(self.paper.count))
            last = min(self.paper.leaf + self.paper.spread, self.paper.count)
            self.page_info.setText(
                self.tr("Pages {0}–{1}").format(self.paper.leaf + 1, last)
                if last > self.paper.leaf + 1
                else ""
            )
            self._controls(not self._loading)
        else:
            self.page_info.clear()
        self._schedule_save()

    def _jump_page(self, value: int) -> None:
        if isinstance(self.book, EpubBook):
            if self._loading:
                return
            self.paper.capture_turn(1 if value - 1 > self.paper.leaf else -1)
            self.paper.leaf = max(0, min(value - 1, self.paper.count - 1))
            self.paper.animate()
            self.paper.update()
            self._leaf_changed()
        else:
            self.go(value - 1)

    def turn(self, direction: int) -> None:
        if self._loading:
            return
        if isinstance(self.book, EpubBook) and self.paper.turn(direction):
            return
        self.go(self.page + direction, fraction=1 if direction < 0 else 0)

    def _schedule_save(self) -> None:
        if not self._loading and self.path is not None:
            self.save_timer.start()

    def save_position(self) -> None:
        self.save_timer.stop()
        if self.path is None or self._loading:
            return
        fraction = self.paper.fraction if isinstance(self.book, EpubBook) else 0
        try:
            self.progress.save(self.path, self.page, fraction)
        except OSError:
            self.notice.setText(self.tr("Reading position could not be saved"))

    def zoom(self, step: int) -> None:
        if isinstance(self.book, EpubBook):
            fraction = self.paper.fraction
            font = self.text.font()
            font.setPointSize(max(12, min(28, font.pointSize() + step)))
            self.text.setFont(font)
            self._render_text(self._content, fraction)

    def clear(self) -> None:
        self.save_position()
        self._generation += 1
        self.path = None
        self.book = None
        self.page = 0
        self._section_count = 1
        self._anchor = ""
        self._loading = False
        self.title.setText(self.tr("Choose a book from your library"))
        self.notice.setText(self.tr("A quiet place for the books you keep alive."))
        self.text.book = None
        self.text.clear()
        self.paper.show_image(QImage())
        self.pdf.show_image(QImage())
        self.pdf_document.close()
        self.comic.show_image(QImage())
        self.chapters.clear()
        self.position.setMaximum(1)
        self.total.clear()
        self._controls(False)


class ReadingRoom(QWidget):
    settings_requested = Signal()

    def __init__(self, progress_path: Path) -> None:
        super().__init__()
        self.roots: tuple[Path, ...] = ()
        self.categories: dict[Path, tuple[str, ...]] = {}
        self.book_items: list[QTreeWidgetItem] = []
        self.branches: dict[tuple[str, ...], QTreeWidgetItem] = {}
        self._expanded_before_search: set[tuple[str, ...]] | None = None
        self._cancel = threading.Event()
        self._generation = 0
        self._scanned = False
        self.filter = QLineEdit()
        self.filter.setPlaceholderText(self.tr("Find a book…"))
        self.filter.setClearButtonEnabled(True)
        self.filter.setAccessibleName(self.tr("Find a book"))
        self.filter.textChanged.connect(self._filter)
        self.refresh = QPushButton(self.tr("Refresh library"))
        self.refresh.clicked.connect(self.scan)
        self.library = QTreeWidget()
        self.library.setHeaderHidden(True)
        self.library.setUniformRowHeights(True)
        self.library.setIndentation(16)
        self.library.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.library.setAccessibleName(self.tr("Ebook library"))
        self.library.itemActivated.connect(self._open)
        self.library.itemClicked.connect(self._open)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.configure = QPushButton(self.tr("Folders…"))
        self.configure.setToolTip(self.tr("Configure local folders…"))
        self.configure.clicked.connect(self.settings_requested)
        self.reader = BookReader(progress_path)
        side = QWidget()
        self.bookshelf = side
        self.reader.library_toggled.connect(lambda: side.setVisible(side.isHidden()))
        side.setMinimumWidth(160)
        layout = QVBoxLayout(side)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.filter)
        layout.addWidget(self.refresh)
        layout.addWidget(self.library, 1)
        layout.addWidget(self.status)
        layout.addWidget(self.configure)
        self.splitter = QSplitter()
        self.splitter.setHandleWidth(10)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.addWidget(side)
        self.splitter.addWidget(self.reader)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([260, 900])
        overall = QVBoxLayout(self)
        overall.setContentsMargins(0, 0, 0, 0)
        overall.addWidget(self.splitter)

    def set_roots(
        self, roots: tuple[Path, ...], categories: dict[Path, tuple[str, ...]] | None = None
    ) -> None:
        if roots != self.roots or (categories or {}) != self.categories:
            # A hidden room can still have an older scan in flight. Its result
            # must not mark the updated category metadata as already scanned.
            self._cancel.set()
            self._generation += 1
            self.refresh.setEnabled(True)
            self.roots = roots
            self.categories = categories or {}
            self._scanned = False
            if self.isVisible():
                self.scan()

    def activate(self) -> None:
        if not self._scanned:
            self.scan()

    def scan(self) -> None:
        self._cancel.set()
        self._cancel = threading.Event()
        cancel = self._cancel
        self._generation += 1
        generation = self._generation
        roots = self.roots
        categories = self.categories.copy()
        self.refresh.setEnabled(False)
        self.status.setText(self.tr("Looking for local books…"))

        def loaded(result: BookLibrary) -> None:
            if generation != self._generation:
                return
            self.refresh.setEnabled(True)
            self._scanned = True
            expanded = {key for key, item in self.branches.items() if item.isExpanded()}
            first = not self.branches
            self.library.clear()
            self.book_items.clear()
            self.branches.clear()
            self.library.setUpdatesEnabled(False)
            counts: dict[tuple[str, ...], int] = {}
            for book in result.books:
                category = book.category or (self.tr("Uncategorized"),)
                if len(book.category) == 1:
                    category = (*book.category, self.tr("Other / unspecified"))
                parent = self.library.invisibleRootItem()
                for depth in range(1, len(category) + 1):
                    key = category[:depth]
                    if key not in self.branches:
                        branch = QTreeWidgetItem(parent, [category[depth - 1]])
                        branch.setData(0, Qt.ItemDataRole.UserRole + 1, key)
                        font = branch.font(0)
                        font.setBold(True)
                        branch.setFont(0, font)
                        branch.setExpanded(key in expanded or (first and depth == 1))
                        self.branches[key] = branch
                    parent = self.branches[key]
                    counts[key] = counts.get(key, 0) + 1
                item = QTreeWidgetItem(parent, [f"{book.title}  ·  {book.path.suffix[1:].upper()}"])
                item.setData(0, Qt.ItemDataRole.UserRole, book.path)
                item.setToolTip(0, str(book.path))
                self.book_items.append(item)
            for key, branch in self.branches.items():
                branch.setText(0, f"{key[-1]} ({counts[key]})")
                branch.setToolTip(0, " / ".join(key))
            self.library.sortItems(0, Qt.SortOrder.AscendingOrder)
            self.library.setUpdatesEnabled(True)
            self._filter(self.filter.text())
            status = self.tr("{0} books").format(len(result.books))
            if not result.books or result.unavailable:
                status += "\n" + self.tr(
                    "Books must be accessible on this computer. "
                    "Check Library Folders and Client Paths in Settings."
                )
            self.status.setText(status)

        def failed(_error: Exception) -> None:
            if generation == self._generation:
                self.refresh.setEnabled(True)
                self.status.setText(self.tr("Could not scan the ebook folders. Check Settings."))

        run_in_background(lambda: discover_books(roots, cancel.is_set, categories), loaded, failed)

    def _filter(self, text: str) -> None:
        query = text.strip().casefold()
        if query and self._expanded_before_search is None:
            self._expanded_before_search = {
                key for key, item in self.branches.items() if item.isExpanded()
            }
        counts: dict[tuple[str, ...], int] = {}
        for item in self.book_items:
            parent = item.parent()
            assert parent is not None
            key = parent.data(0, Qt.ItemDataRole.UserRole + 1)
            visible = query in (item.text(0) + " " + " / ".join(key)).casefold()
            item.setHidden(not visible)
            if visible:
                for depth in range(1, len(key) + 1):
                    counts[key[:depth]] = counts.get(key[:depth], 0) + 1
        for key, item in self.branches.items():
            count = counts.get(key, 0)
            item.setHidden(count == 0)
            item.setText(0, f"{key[-1]} ({count})")
            if query and count:
                item.setExpanded(True)
            elif not query and self._expanded_before_search is not None:
                item.setExpanded(key in self._expanded_before_search)
        if not query:
            self._expanded_before_search = None

    def _open(self, item: QTreeWidgetItem, column: int = 0) -> None:
        path = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(path, Path) and path != self.reader.path:
            self.reader.open_book(path)

    def stop(self) -> None:
        self._generation += 1
        self._cancel.set()
        self.reader.clear()
        self.refresh.setEnabled(True)
        self._scanned = False
