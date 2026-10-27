"""On-demand torrent description, images, file list and NFO preview."""

from __future__ import annotations

import html
import math
import re
import time
from collections.abc import Callable
from urllib.parse import urlsplit

import httpx
from PySide6.QtCore import (
    QBuffer,
    QByteArray,
    QCoreApplication,
    QDateTime,
    QIODevice,
    QSize,
    Qt,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QDesktopServices,
    QFontDatabase,
    QImage,
    QImageReader,
    QPixmap,
    QTextDocument,
)
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from torrentlinker.gui.controls import set_role
from torrentlinker.gui.errors import error_text
from torrentlinker.gui.feed_editor import Disclosure
from torrentlinker.gui.flow_layout import FlowLayout
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
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 14, 12)
        layout.setSpacing(14)
        scroll.setWidget(page)
        outer.addWidget(scroll, 1)
        crumb = QLabel(self.tr("Torrents  ›  {0}").format(candidate.title))
        crumb.setObjectName("detailCrumb")
        crumb.setTextFormat(Qt.TextFormat.PlainText)
        crumb.setWordWrap(True)
        layout.addWidget(crumb)
        # Header: what it is, how it stands, and the actions, as on c411.
        head = QHBoxLayout()
        self.badge = QLabel()
        self.badge.setObjectName("detailBadge")
        self.badge.hide()
        head.addWidget(self.badge)
        self.flags = FlowLayout(spacing=6)
        head.addLayout(self.flags, 1)
        self.website = QPushButton(self.tr("Open on website"))
        self.website.setEnabled(bool(website_url(candidate, indexer)))
        self.website.clicked.connect(lambda: self._open_link(QUrl(website_url(candidate, indexer))))
        head.addWidget(self.website)
        self.add_queue = QPushButton(self.tr("Add to queue"))
        self.download_now = QPushButton(self.tr("Download now"))
        set_role(self.download_now, "primary")
        self.add_queue.clicked.connect(lambda: self._download(False))
        self.download_now.clicked.connect(lambda: self._download(True))
        for action in (self.add_queue, self.download_now):
            action.setVisible(download is not None)
            head.addWidget(action)
        layout.addLayout(head)
        title = QLabel(candidate.title)
        title.setObjectName("detailTitle")
        title.setTextFormat(Qt.TextFormat.PlainText)
        title.setWordWrap(True)
        title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(title)
        self.byline = QLabel()
        self.byline.setProperty("role", "muted")
        self.byline.setTextFormat(Qt.TextFormat.PlainText)
        if candidate.published_at is not None:
            self.byline.setText(self._published(candidate.published_at))
        layout.addWidget(self.byline)
        self.banner = QFrame()
        self.banner.setObjectName("detailBanner")
        banner = QVBoxLayout(self.banner)
        self.banner_title = QLabel()
        self.banner_title.setStyleSheet("font-weight: 600")
        self.banner_text = QLabel()
        self.banner_text.setWordWrap(True)
        banner.addWidget(self.banner_title)
        banner.addWidget(self.banner_text)
        self.banner.hide()
        layout.addWidget(self.banner)
        # Facts: size and swarm, then ours, the Zen estimate.
        self.stats = FlowLayout(spacing=8)
        layout.addLayout(self.stats)
        self._stat("size", human_size(candidate.size))
        self._stat("up", self.tr("{0} seeders").format(candidate.seeders))
        self.summary = QLabel(
            self.tr("{0} Zen/day").format(zen) + self.tr(" · Note: {0}").format(torrent_note)
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
        self.hash_label = QLabel()
        self.hash_label.setTextFormat(Qt.TextFormat.PlainText)
        self.hash_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.hash_label.setProperty("role", "muted")
        if candidate.infohash:
            self.hash_label.setText(self.tr("Hash: {0}").format(candidate.infohash))
        layout.addWidget(self.hash_label)
        self.facts = FlowLayout(spacing=8)
        layout.addLayout(self.facts)
        # NFO and files open in place, as on c411.
        self.nfo = QPlainTextEdit()
        self.nfo.setReadOnly(True)
        self.nfo.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.nfo.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.nfo.setMinimumHeight(260)
        self.nfo_section = Disclosure(self.tr("Show the NFO"), self.nfo)
        layout.addWidget(self.nfo_section)
        self.files = QTableWidget(0, 2)
        self.files.setHorizontalHeaderLabels([self.tr("File"), self.tr("Size")])
        self.files.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        sortable_table(self.files)
        self.files.setColumnWidth(0, 560)
        self.files.setColumnWidth(1, 130)
        self.files.setMinimumHeight(200)
        self.files_section = Disclosure(self.tr("Show the files"), self.files)
        layout.addWidget(self.files_section)
        # The TMDB card.
        self.card = QFrame()
        self.card.setObjectName("detailCard")
        card = QHBoxLayout(self.card)
        card.setContentsMargins(14, 14, 14, 14)
        self.poster = QLabel()
        self.poster.setFixedSize(100, 150)
        self.poster.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.poster.setObjectName("detailPoster")
        card.addWidget(self.poster, 0, Qt.AlignmentFlag.AlignTop)
        card_text = QVBoxLayout()
        self.card_title = QLabel()
        self.card_title.setObjectName("detailCardTitle")
        self.card_title.setWordWrap(True)
        self.card_title.setTextFormat(Qt.TextFormat.PlainText)
        self.card_original = QLabel()
        self.card_original.setProperty("role", "muted")
        self.card_genres = FlowLayout(spacing=6)
        self.card_facts = QLabel()
        self.card_facts.setWordWrap(True)
        self.card_facts.setTextFormat(Qt.TextFormat.PlainText)
        self.card_cast = QLabel()
        self.card_cast.setWordWrap(True)
        self.card_cast.setProperty("role", "muted")
        self.card_cast.setTextFormat(Qt.TextFormat.PlainText)
        links = QHBoxLayout()
        self.tmdb_link = QPushButton(self.tr("View on TMDB"))
        self.imdb_link = QPushButton(self.tr("View on IMDb"))
        self._link_urls: dict[QPushButton, str] = {}
        for link in (self.tmdb_link, self.imdb_link):
            set_role(link, "quiet")
            link.clicked.connect(
                lambda _=False, b=link: self._open_link(QUrl(self._link_urls.get(b, "")))
            )
            links.addWidget(link)
        links.addStretch()
        for widget in (self.card_title, self.card_original):
            card_text.addWidget(widget)
        card_text.addLayout(self.card_genres)
        for widget in (self.card_facts, self.card_cast):
            card_text.addWidget(widget)
        card_text.addLayout(links)
        card_text.addStretch()
        card.addLayout(card_text, 1)
        self.card.hide()
        layout.addWidget(self.card)
        self.ids = FlowLayout(spacing=8)
        layout.addLayout(self.ids)
        # Community trust: read-only here, since voting needs a website session.
        self.trust_box = QFrame()
        self.trust_box.setObjectName("detailTrust")
        trust = QVBoxLayout(self.trust_box)
        trust_title = QLabel(self.tr("Community trust"))
        trust_title.setStyleSheet("font-weight: 600")
        self.trust_line = QLabel()
        self.trust_line.setTextFormat(Qt.TextFormat.PlainText)
        self.vote_link = QPushButton(self.tr("Vote on the website"))
        set_role(self.vote_link, "quiet")
        self.vote_link.setEnabled(bool(website_url(candidate, indexer)))
        self.vote_link.clicked.connect(
            lambda: self._open_link(QUrl(website_url(candidate, indexer)))
        )
        trust.addWidget(trust_title)
        trust.addWidget(self.trust_line)
        trust.addWidget(self.vote_link, 0, Qt.AlignmentFlag.AlignLeft)
        self.trust_box.hide()
        layout.addWidget(self.trust_box)
        self.description = DescriptionBrowser()
        self.description.setOpenLinks(False)
        self.description.setOpenExternalLinks(False)
        self.description.anchorClicked.connect(self._open_link)
        self.description.setFrameShape(QFrame.Shape.NoFrame)
        self.description.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.description.document().documentLayout().documentSizeChanged.connect(
            self._fit_description
        )
        layout.addWidget(self.description)
        layout.addStretch(1)
        # The bar that stays in view: status, folder and the two download actions.
        bar = QFrame()
        bar.setObjectName("detailBar")
        bar_layout = QVBoxLayout(bar)
        bar_layout.setContentsMargins(12, 8, 12, 8)
        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        bar_layout.addWidget(self.status)
        self.action_status = QLabel()
        self.action_status.setWordWrap(True)
        self.action_status.setTextFormat(Qt.TextFormat.PlainText)
        bar_layout.addWidget(self.action_status)
        self.folder = QLineEdit(folder)
        self.folder.setAccessibleName(self.tr("Download Folder"))
        self.folder.setPlaceholderText(self.tr("Choose a Download Folder"))
        download_controls = QWidget()
        dl = QHBoxLayout(download_controls)
        dl.setContentsMargins(0, 0, 0, 0)
        dl.addWidget(QLabel(self.tr("Download Folder")))
        dl.addWidget(self.folder, 1)
        browse = QPushButton(self.tr("Browse…"))
        browse.clicked.connect(self._browse)
        dl.addWidget(browse)
        download_controls.setVisible(download is not None)
        bar_layout.addWidget(download_controls)
        controls = QHBoxLayout()
        self.reload = QPushButton(self.tr("Reload details"))
        set_role(self.reload, "quiet")
        self.reload.clicked.connect(self.load)
        controls.addWidget(self.reload)
        self.retry_images = QPushButton(self.tr("Retry images"))
        set_role(self.retry_images, "quiet")
        self.retry_images.clicked.connect(self._retry_images)
        self.retry_images.hide()
        controls.addWidget(self.retry_images)
        controls.addStretch()
        close = QPushButton(self.tr("Close"))
        set_role(close, "quiet")
        close.clicked.connect(self.reject)
        controls.addWidget(close)
        bar_layout.addLayout(controls)
        outer.addWidget(bar)
        self.finished.connect(self._finish)
        self.load()

    @staticmethod
    def _published(timestamp: float) -> str:
        date = QDateTime.fromMSecsSinceEpoch(round(timestamp * 1000)).toLocalTime()
        return QCoreApplication.translate("TorrentDetailsDialog", "Published {0}").format(
            date.toString("yyyy-MM-dd HH:mm")
        )

    def _chip(self, layout: FlowLayout, kind: str, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("detailChip")
        label.setProperty("kind", kind)
        label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(label)
        return label

    def _stat(self, kind: str, text: str) -> QLabel:
        return self._chip(self.stats, kind, text)

    @staticmethod
    def _clear(layout: FlowLayout) -> None:
        while item := layout.takeAt(0):
            if widget := item.widget():
                widget.hide()
                widget.deleteLater()

    def _fit_description(self) -> None:
        """The description is as tall as its text, so the page scrolls, not the browser."""
        document = self.description.document()
        document.setTextWidth(max(200, self.description.viewport().width()))
        self.description.setFixedHeight(int(document.size().height()) + 12)

    def resizeEvent(self, event) -> None:  # noqa: ANN001
        super().resizeEvent(event)
        self._fit_description()

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
        self.card.hide()
        self.trust_box.hide()
        self.banner.hide()
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
        self.files_section.toggle.setText(
            self.tr("Show the files ({0})").format(len(details.files))
        )
        self._fill_header(details)
        self._image_failures = 0
        self._load_image(generation, 0)

    def _fill_header(self, details: TorrentDetails) -> None:
        for layout in (self.flags, self.facts, self.ids, self.card_genres):
            self._clear(layout)
        for stat in self.findChildren(QLabel, "detailChip"):
            if stat.property("kind") in {"down", "done", "wanted"}:
                self.stats.removeWidget(stat)
                stat.hide()
                stat.deleteLater()
        # Header: the type, then what c411 flags about this torrent.
        kind = details.subcategory or details.category
        self.badge.setVisible(bool(kind))
        self.badge.setText(kind.upper())
        if details.exclusive:
            self._chip(self.flags, "exclusive", "★ " + self.tr("Exclusive"))
        if details.low_bitrate:
            self._chip(self.flags, "warning", self.tr("Low bitrate"))
        trust = details.trust
        self._chip(
            self.flags,
            "tested" if trust.tested else "untested",
            self.tr("Tested") if trust.tested else self.tr("Not tested"),
        )
        # Byline and banner.
        parts = []
        if details.uploader:
            parts.append(self.tr("Sent by {0}").format(details.uploader))
        if details.team:
            parts.append(self.tr("Team {0}").format(details.team))
        if details.created_at is not None:
            parts.append(self._published(details.created_at))
        if parts:
            self.byline.setText(" · ".join(parts))
        if trust.status == "untested" or (trust.status and not trust.tested):
            self.banner_title.setText(self.tr("Torrent not tested by the community"))
            self.banner_text.setText(
                self.tr(
                    "This torrent has not yet received enough trust votes. "
                    "Be careful and check the content before use."
                )
            )
            self.banner.show()
        # Swarm numbers from the detail response are the live ones.
        if details.leechers is not None:
            self._stat("down", self.tr("{0} leechers").format(details.leechers))
        if details.completions is not None:
            self._stat("done", self.tr("{0} completed").format(details.completions))
        if details.seeders == 0:
            self._stat("wanted", self.tr("Seeds wanted"))
        if details.files:
            self.hash_label.setText(
                self.tr("Hash: {0}").format(self.candidate.infohash or "")
                + "  ·  "
                + self.tr("Files: {0}").format(len(details.files))
            )
        for name, values in details.facts:
            self._chip(self.facts, "fact", f"{name}: {', '.join(values)}")
        self._fill_card(details)
        if trust.status or trust.positive or trust.negative:
            line = self.tr("{0}  ·  👍 {1}  ·  👎 {2}").format(
                self.tr("Tested") if trust.tested else self.tr("Not tested"),
                trust.positive,
                trust.negative,
            )
            if trust.required and not trust.tested:
                line += "  ·  " + self.tr("({0} votes required)").format(trust.required)
            self.trust_line.setText(line)
            self.trust_box.show()

    def _fill_card(self, details: TorrentDetails) -> None:
        media = details.media
        if media is None or not (media.title or media.tmdb_id):
            return
        kinds = {"movie": self.tr("Film"), "tv": self.tr("TV series")}
        year = f" ({media.year})" if media.year else ""
        kind = kinds.get(media.kind, "")
        self.card_title.setText(f"{media.title}{year}" + (f"  ·  {kind}" if kind else ""))
        original = media.original_title if media.original_title != media.title else ""
        self.card_original.setText(original)
        self.card_original.setVisible(bool(original))
        for genre in media.genres:
            self._chip(self.card_genres, "fact", genre)
        facts = []
        if media.rating:
            facts.append(
                f"★ {media.rating:.1f}/10 TMDB"
                + (f" · {self.tr('{0} votes').format(media.votes)}" if media.votes else "")
            )
        if media.runtime:
            facts.append(self.tr("{0} min").format(media.runtime))
        if media.directors:
            facts.append(self.tr("Director: {0}").format(", ".join(media.directors)))
        self.card_facts.setText("  ·  ".join(facts))
        self.card_cast.setText(
            self.tr("With {0}…").format(", ".join(media.cast)) if media.cast else ""
        )
        self.card_cast.setVisible(bool(media.cast))
        path = "tv" if media.kind == "tv" else "movie"
        self._link(
            self.tmdb_link, f"https://www.themoviedb.org/{path}/{media.tmdb_id}", media.tmdb_id
        )
        self._link(self.imdb_link, f"https://www.imdb.com/title/{media.imdb_id}/", media.imdb_id)
        if media.tmdb_id:
            self._chip(self.ids, "id", f"TMDB {media.tmdb_id}")
        if media.imdb_id:
            self._chip(self.ids, "id", f"IMDb {media.imdb_id}")
        self.card.show()
        if details.poster:
            self._load_poster(details.poster)

    def _link(self, button: QPushButton, url: str, identifier: str) -> None:
        button.setVisible(bool(identifier))
        self._link_urls[button] = url

    def _load_poster(self, url: str) -> None:
        generation = self._generation

        def loaded(image: QImage) -> None:
            if self._active(generation) and not image.isNull():
                self.poster.setPixmap(
                    QPixmap.fromImage(
                        image.scaled(
                            100,
                            150,
                            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                    )
                )

        run_in_background(lambda: decode_preview(fetch_image(url)), loaded, lambda _error: None)

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
