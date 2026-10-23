"""On-demand torrent description, images, file list and NFO preview."""

from __future__ import annotations

import html
import math
import re
import time
from collections.abc import Callable
from urllib.parse import urlsplit

import httpx
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFontDatabase, QImage, QImageReader, QTextDocument
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from torrentlinker.gui.errors import error_text
from torrentlinker.gui.library_model import human_size
from torrentlinker.gui.settings_dialog import choose_directory
from torrentlinker.gui.tables import NumberItem, sortable_table
from torrentlinker.gui.tasks import run_in_background
from torrentlinker.indexer import Candidate, Indexer
from torrentlinker.torrent_details import (
    TorrentDetails,
    fetch_image,
    parse_details,
    preview_html,
    web_url,
    website_url,
)


class DescriptionBrowser(QTextBrowser):
    def loadResource(self, kind: int, url: QUrl | str) -> object:
        # Only explicitly fetched images enter the document through addResource.
        # QTextDocument must never read local paths or fetch arbitrary resources.
        return None


def decode_preview(data: bytes) -> QImage:
    buffer = QBuffer()
    buffer.setData(QByteArray(data))
    buffer.open(QIODevice.OpenModeFlag.ReadOnly)
    reader = QImageReader(buffer)
    size = reader.size()
    if not size.isValid() or size.width() * size.height() > 40_000_000:
        raise ValueError("Image dimensions exceed preview limit")
    if size.width() > 1200 or size.height() > 1600:
        reader.setScaledSize(size.scaled(QSize(1200, 1600), Qt.AspectRatioMode.KeepAspectRatio))
    image = reader.read()
    if image.isNull():
        raise ValueError("Could not decode image")
    return image


class TorrentDetailsDialog(QDialog):
    close_requested = Signal()

    def __init__(
        self,
        candidate: Candidate,
        indexer: Indexer,
        zen: str,
        assumptions: str,
        parent: QWidget | None = None,
        *,
        download: Callable[[str, bool], str] | None = None,
        folder: str = "",
        embedded: bool = False,
        torrent_note: str = "–",
    ) -> None:
        super().__init__(parent)
        self.embedded = embedded
        if embedded:
            self.setWindowFlags(Qt.WindowType.Widget)
        self.candidate, self.indexer = candidate, indexer
        self.download_action = download
        self._closed = False
        self._generation = 0
        self._html = ""
        self._images: tuple[str, ...] = ()
        self._image_failures = 0
        self._loaded_images: dict[int, QImage] = {}
        self._image_errors: dict[int, str] = {}
        self._host_retry: dict[str, float] = {}
        self._images_busy = False
        self.retry_timer = QTimer(self)
        self.retry_timer.setSingleShot(True)
        self.retry_timer.timeout.connect(self._update_image_retry)
        self.setWindowTitle(self.tr("Torrent details"))
        self.resize(900, 740)
        layout = QVBoxLayout(self)
        title = QLabel(candidate.title)
        title.setTextFormat(Qt.TextFormat.PlainText)
        title.setWordWrap(True)
        title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        title.setStyleSheet("font-size: 16px; font-weight: bold")
        layout.addWidget(title)
        self.summary = QLabel(
            self.tr("{0} · {1} seeders · {2} Zen/day").format(
                human_size(candidate.size), candidate.seeders, zen
            )
            + self.tr(" · Note: {0}").format(torrent_note)
        )
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        info = QFrame()
        info.setObjectName("estimateInfo")
        info_layout = QVBoxLayout(info)
        info_layout.setContentsMargins(10, 5, 10, 8)
        toggle = QToolButton()
        toggle.setObjectName("estimateToggle")
        toggle.setText(self.tr("About this estimate"))
        toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        toggle.setArrowType(Qt.ArrowType.RightArrow)
        toggle.setCheckable(True)
        info_layout.addWidget(toggle, 0, Qt.AlignmentFlag.AlignLeft)
        estimate = QLabel(assumptions)
        estimate.setTextFormat(Qt.TextFormat.PlainText)
        estimate.setWordWrap(True)
        estimate.setProperty("role", "muted")
        estimate.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        estimate.hide()
        toggle.toggled.connect(estimate.setVisible)
        toggle.toggled.connect(
            lambda expanded: toggle.setArrowType(
                Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
            )
        )
        info_layout.addWidget(estimate)
        info.setVisible(bool(assumptions))
        layout.addWidget(info)
        self.tabs = QTabWidget()
        self.description = DescriptionBrowser()
        self.description.setOpenLinks(False)
        self.description.setOpenExternalLinks(False)
        self.description.anchorClicked.connect(self._open_link)
        self.tabs.addTab(self.description, self.tr("Description"))
        self.nfo = QPlainTextEdit()
        self.nfo.setReadOnly(True)
        self.nfo.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.nfo.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.tabs.addTab(self.nfo, self.tr("NFO"))
        self.files = QTableWidget(0, 2)
        self.files.setHorizontalHeaderLabels([self.tr("File"), self.tr("Size")])
        self.files.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        sortable_table(self.files)
        self.files.setColumnWidth(0, 630)
        self.files.setColumnWidth(1, 130)
        self.tabs.addTab(self.files, self.tr("Files"))
        layout.addWidget(self.tabs, 1)
        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.action_status = QLabel()
        self.action_status.setWordWrap(True)
        self.action_status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.action_status)
        self.folder = QLineEdit(folder)
        self.folder.setAccessibleName(self.tr("Download Folder"))
        self.folder.setPlaceholderText(self.tr("Choose a Download Folder"))
        self.add_queue = QPushButton(self.tr("Add to queue"))
        self.download_now = QPushButton(self.tr("Download now"))
        self.download_now.setProperty("primary", True)
        self.add_queue.clicked.connect(lambda: self._download(False))
        self.download_now.clicked.connect(lambda: self._download(True))
        download_controls = QWidget()
        dl = QHBoxLayout(download_controls)
        dl.setContentsMargins(0, 0, 0, 0)
        dl.addWidget(QLabel(self.tr("Download Folder")))
        dl.addWidget(self.folder, 1)
        browse = QPushButton(self.tr("Browse…"))
        browse.clicked.connect(self._browse)
        dl.addWidget(browse)
        dl.addWidget(self.add_queue)
        dl.addWidget(self.download_now)
        download_controls.setVisible(download is not None)
        layout.addWidget(download_controls)
        controls = QHBoxLayout()
        self.reload = QPushButton(self.tr("Reload details"))
        self.reload.clicked.connect(self.load)
        controls.addWidget(self.reload)
        self.retry_images = QPushButton(self.tr("Retry images"))
        self.retry_images.clicked.connect(self._retry_images)
        self.retry_images.hide()
        controls.addWidget(self.retry_images)
        self.website = QPushButton(self.tr("Open on website"))
        self.website.setEnabled(bool(website_url(candidate, indexer)))
        self.website.clicked.connect(lambda: self._open_link(QUrl(website_url(candidate, indexer))))
        controls.addWidget(self.website)
        controls.addStretch()
        close = QPushButton(self.tr("Close"))
        close.clicked.connect(self.reject)
        controls.addWidget(close)
        layout.addLayout(controls)
        self.finished.connect(self._finish)
        self.load()

    def reject(self) -> None:
        if self.embedded:
            self.close_requested.emit()
        else:
            super().reject()

    def dispose(self) -> None:
        self._finish(0)
        self.hide()
        self.deleteLater()

    def _browse(self) -> None:
        folder = choose_directory(self, self.tr("Download Folder"), self.folder.text())
        if folder:
            self.folder.setText(folder)

    def _download(self, now: bool) -> None:
        if self.download_action:
            try:
                message = self.download_action(self.folder.text().strip(), now)
            except Exception as error:
                message = error_text(error)
            self.action_status.setText(message)

    def _finish(self, _result: int) -> None:
        self._closed = True
        self.retry_timer.stop()
        self._generation += 1

    @staticmethod
    def _open_link(url: QUrl) -> None:
        value = web_url(url.toString())
        if value:
            QDesktopServices.openUrl(QUrl(value))

    def load(self) -> None:
        self._generation += 1
        generation = self._generation
        h = self.candidate.infohash
        if not self.indexer.is_c411 or not h:
            self.description.setPlainText(
                self.tr(
                    "In-app details are available for c411 torrents. "
                    "Use Open on website for this Indexer."
                )
            )
            self.nfo.setPlainText(self.tr("NFO unavailable."))
            self.reload.setEnabled(False)
            return
        self.reload.setEnabled(False)
        self._images_busy = True
        self.retry_images.setEnabled(False)
        self.retry_timer.stop()
        self.status.setText(self.tr("Loading torrent details…"))
        self.description.clear()
        self.nfo.clear()
        self.files.setRowCount(0)
        run_in_background(
            lambda: parse_details(self.indexer.torrent_json(h.lower())),
            lambda details: self._loaded(generation, details),
            lambda error: self._failed(generation, error),
        )

    def _active(self, generation: int) -> bool:
        return not self._closed and isValid(self) and generation == self._generation

    def _failed(self, generation: int, error: Exception) -> None:
        if not self._active(generation):
            return
        self.reload.setEnabled(True)
        self.status.setText(error_text(error))
        self.description.setPlainText(
            self.tr("Could not load details. Retry or open the torrent on the website.")
        )

    def _loaded(self, generation: int, details: TorrentDetails) -> None:
        if not self._active(generation):
            return
        self.reload.setEnabled(True)
        self._html, self._images = preview_html(
            details.description or self.tr("No description available."), details.poster
        )
        self._loaded_images.clear()
        self._image_errors.clear()
        self._render_description()
        self.nfo.setPlainText(
            details.nfo
            or (
                self.tr(
                    "The tracker lists an NFO but did not provide its contents. "
                    "Open the website to view it."
                )
                if details.has_nfo
                else self.tr("No NFO supplied for this torrent.")
            )
        )
        self.files.setSortingEnabled(False)
        self.files.setRowCount(len(details.files))
        for row, (path, size) in enumerate(details.files):
            self.files.setItem(row, 0, QTableWidgetItem(path))
            self.files.setItem(row, 1, NumberItem(human_size(size), size))
        self.files.setSortingEnabled(True)
        self.tabs.setTabText(2, self.tr("Files ({0})").format(len(details.files)))
        self._image_failures = 0
        self._load_image(generation, 0)

    def _render_description(self) -> None:
        def substitute(match: re.Match[str]) -> str:
            position = int(match[1])
            if position in self._loaded_images:
                return match[0]
            label = self._image_errors.get(position, self.tr("Loading image…"))
            url = html.escape(self._images[position], quote=True)
            return f'<a href="{url}">{html.escape(label)}</a>'

        scroll = self.description.verticalScrollBar().value()
        self.description.setHtml(
            re.sub(r'<img src="preview-image:(\d+)" width="\d+">', substitute, self._html)
        )
        for position, image in self._loaded_images.items():
            self.description.document().addResource(
                QTextDocument.ResourceType.ImageResource, QUrl(f"preview-image:{position}"), image
            )
        self.description.document().markContentsDirty(
            0, self.description.document().characterCount()
        )
        self.description.viewport().update()
        self.description.verticalScrollBar().setValue(scroll)

    def _update_image_retry(self) -> None:
        self.retry_images.setVisible(bool(self._image_errors))
        delays = [
            max(0.0, self._host_retry.get(urlsplit(self._images[p]).netloc, 0) - time.monotonic())
            for p in self._image_errors
        ]
        delay = min(delays, default=0)
        self.retry_images.setEnabled(bool(delays) and delay == 0 and not self._images_busy)
        if delay and not self._images_busy:
            self.retry_timer.start(min(2_000_000_000, int(delay * 1000) + 1))

    def _retry_images(self) -> None:
        if self._images_busy:
            return
        self._image_errors = {
            position: error
            for position, error in self._image_errors.items()
            if self._host_retry.get(urlsplit(self._images[position]).netloc, 0) > time.monotonic()
        }
        self._render_description()
        self._load_image(self._generation, 0)

    def _load_image(self, generation: int, position: int) -> None:
        if not self._active(generation):
            return
        while position < len(self._images):
            if position in self._loaded_images:
                position += 1
                continue
            host = urlsplit(self._images[position]).netloc
            if self._host_retry.get(host, 0) > time.monotonic():
                self._image_errors[position] = self.tr(
                    "Image host temporarily unavailable ({0})."
                ).format(host)
                position += 1
                continue
            break
        self._images_busy = position < len(self._images)
        self._update_image_retry()
        if not self._images_busy:
            self._image_failures = len(self._image_errors)
            self._render_description()
            self.status.setText(
                self.tr(
                    "{0} images unavailable. Retry later or click their links to open them."
                ).format(self._image_failures)
                if self._image_failures
                else ""
            )
            return
        self.status.setText(
            self.tr("Loading image {0} of {1}…").format(position + 1, len(self._images))
        )
        url = self._images[position]

        def loaded(image: QImage) -> None:
            if not self._active(generation):
                return
            self._loaded_images[position] = image
            self._image_errors.pop(position, None)
            self._render_description()
            self._load_image(generation, position + 1)

        def failed(error: Exception) -> None:
            if not self._active(generation):
                return
            host = urlsplit(url).netloc
            reason = self.tr("Image unavailable ({0}).").format(host)
            if isinstance(error, httpx.HTTPStatusError):
                code = error.response.status_code
                reason = self.tr("Image unavailable ({0}, HTTP {1}).").format(host, code)
                if code == 429:
                    try:
                        wait = max(60.0, float(error.response.headers.get("Retry-After", "60")))
                    except ValueError:
                        wait = 60.0
                    if not math.isfinite(wait):
                        wait = 60.0
                    self._host_retry[host] = time.monotonic() + wait
            self._image_errors[position] = reason
            self._load_image(generation, position + 1)

        run_in_background(lambda: decode_preview(fetch_image(url)), loaded, failed)
