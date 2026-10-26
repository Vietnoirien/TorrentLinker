"""Saved selection cards; detail and image requests stay off the Qt thread."""

import json
from urllib.parse import urlsplit

from PySide6.QtCore import QCoreApplication, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QPixmap, QTextDocument
from PySide6.QtWidgets import (
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from torrentlinker.gui.library_model import human_size
from torrentlinker.gui.tasks import run_in_background
from torrentlinker.gui.torrent_details import DescriptionBrowser
from torrentlinker.torrent_details import preview_html


def plain_label(text, name=""):
    label = QLabel(str(text))
    label.setObjectName(name)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    return label


def scores(item):
    def number(value, digits):
        return f"{value:.{digits}f}" if isinstance(value, (int, float)) else "—"

    text = QCoreApplication.translate("SelectionCards", "Note %1 · ≈ %2 Zen/day")
    label = plain_label(
        text.replace("%1", number(item.get("torrent_note"), 2)).replace(
            "%2", number(item.get("estimated_zen_per_day"), 3)
        ),
        "selectionScores",
    )
    label.setStyleSheet("font-weight: 600;")
    label.setToolTip(item.get("zen_assumptions") or "")
    return label


def upload_summary(item):
    status = {
        "queued": QCoreApplication.translate("UploadCards", "Awaiting review"),
        "sending": QCoreApplication.translate("UploadCards", "Sending to c411"),
        "sent": QCoreApplication.translate("UploadCards", "Sent to c411"),
        "uncertain": QCoreApplication.translate("UploadCards", "Check c411 before retrying"),
    }.get(
        (item.get("saved_status") if item.get("draft_changed") else item.get("current_status"))
        or item.get("saved_status"),
        QCoreApplication.translate("UploadCards", "Saved draft"),
    )
    lines = [
        QCoreApplication.translate("UploadCards", "Upload draft · revision {0} · {1}").format(
            item["draft_revision"], status
        )
    ]
    review = item.get("review_summary") or {}
    lines.append(
        QCoreApplication.translate("UploadCards", "{0} refusals · {1} warnings").format(
            review.get("refusals", 0), review.get("warnings", 0)
        )
    )
    if item.get("draft_deleted"):
        lines.append(
            QCoreApplication.translate(
                "UploadCards", "Draft removed. This is a saved review snapshot."
            )
        )
    elif item.get("draft_changed"):
        lines.append(
            QCoreApplication.translate(
                "UploadCards", "Draft changed. Review the current revision before sending."
            )
        )
    return "\n".join(lines)


def card_size(item):
    size = item.get("size_bytes")
    text = (
        human_size(size)
        if size is not None
        else QCoreApplication.translate("SelectionCards", "Unknown size")
    )
    if item.get("presentation_type") != "upload_drafts":
        text += " · " + QCoreApplication.translate("SelectionCards", "%1 seeders").replace(
            "%1", str(item["seeders"] if item.get("seeders") is not None else "—")
        )
    return text


class Artwork(QLabel):
    def __init__(self, item, images, *, large=False):
        super().__init__()
        self.url = item.get("image_url") or ""
        self.setObjectName("selectionArtwork")
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        square = item.get("kind") in {"music", "software", "model3d", "other"}
        self.setFixedHeight((300 if large else 190) if not square else (240 if large else 150))
        self.setMinimumWidth(120)
        self.setStyleSheet(
            "background: palette(alternate-base); border-radius: 8px;"
            "color: palette(mid); font-size: 13px; padding: 6px;"
        )
        self.setText(item.get("category") or self.tr("No artwork"))
        images.ready.connect(self.ready)
        if self.url:
            self.ready(self.url, images.request(self.url))

    def ready(self, url, image):
        if isValid(self) and url == self.url and image is not None:
            self.setPixmap(
                QPixmap.fromImage(image).scaled(
                    230,
                    self.height() - 12,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )


class SelectionDetail(QDialog):
    def __init__(self, presentation_id, item_id, loader, images, parent):
        super().__init__(parent)
        self.setObjectName("selectionDetail")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle(self.tr("Selection details"))
        self.resize(680, 720)
        self.layout_box = QVBoxLayout(self)
        self.status = plain_label(self.tr("Loading details…"))
        self.layout_box.addWidget(self.status)
        close = QPushButton(self.tr("Close"))
        close.clicked.connect(self.close)
        self.layout_box.addWidget(close)
        self.images = images
        run_in_background(lambda: loader(presentation_id, item_id), self.loaded, self.failed)

    def failed(self, error):
        if isValid(self):
            self.status.setText(str(error))
            self.status.setStyleSheet("color: #d45d67;")

    def loaded(self, item):
        if not isValid(self):
            return
        self.status.hide()
        body = QWidget()
        box = QVBoxLayout(body)
        title = plain_label(item.get("content_title") or item["title"], "selectionDetailTitle")
        title.setStyleSheet("font-size: 20px; font-weight: 600;")
        box.addWidget(title)
        upload = item.get("presentation_type") == "upload_drafts"
        row = QHBoxLayout()
        artwork = Artwork(item, self.images, large=not upload)
        if upload:
            self.resize(900, 860)
            artwork.setFixedHeight(150)
            artwork.setMaximumWidth(130)
        row.addWidget(artwork, 1)
        info = QVBoxLayout()
        info.addWidget(plain_label(item["title"]))
        info.addWidget(plain_label(card_size(item)))
        if upload:
            self.setWindowTitle(self.tr("Upload draft review"))
            info.addWidget(plain_label(upload_summary(item)))
        else:
            info.addWidget(scores(item))
        if item.get("zen_assumptions"):
            info.addWidget(plain_label(item["zen_assumptions"]))
        for name, value in (item.get("facts") or {}).items():
            info.addWidget(plain_label(f"{name}: {value}"))
        if item.get("note"):
            info.addWidget(plain_label(item["note"]))
        info.addStretch()
        row.addLayout(info, 2)
        box.addLayout(row)
        description = DescriptionBrowser()
        description.setObjectName("selectionDescription")
        description.setOpenLinks(False)
        description.anchorClicked.connect(self.open_source)
        # Re-sanitize even persisted markup. DescriptionBrowser never fetches embedded resources.
        if upload:
            from torrentlinker.agent.upload_presentations import draft_preview

            markup, urls = draft_preview(item.get("upload_form") or {})
            description.setHtml(markup)
            self.description = description
            self.description_urls = urls
            self.images.ready.connect(self.description_image)
            for url in urls:
                self.description_image(url, self.images.request(url))
        else:
            description.setHtml(
                preview_html(
                    item.get("description_html")
                    or item.get("description")
                    or self.tr("No description available.")
                )[0]
            )
        description.setMinimumHeight(280 if upload else 160)
        if upload:
            tabs = QTabWidget()
            tabs.setObjectName("uploadReviewTabs")
            tabs.addTab(description, self.tr("Description"))
            review = item.get("upload_review") or {}
            review_text = self.tr("Reviewing these cards does not approve or send the draft.")
            for label, key in (
                (self.tr("Refusals"), "refusals"),
                (self.tr("Warnings"), "warnings"),
            ):
                review_text += "\n\n" + label + "\n" + "\n".join(review.get(key, []))
            fields = [
                (self.tr("NFO"), item.get("nfo", "")),
                (
                    self.tr("Files"),
                    "\n".join(
                        f"{file['path']} · {human_size(file['size'])}"
                        for file in item.get("files", [])
                    ),
                ),
                (
                    self.tr("Category options"),
                    json.dumps(
                        (item.get("upload_form") or {}).get("options", {}),
                        ensure_ascii=False,
                        indent=2,
                    ),
                ),
                (self.tr("Review"), review_text),
            ]
            for label, text in fields:
                editor = QPlainTextEdit()
                editor.setReadOnly(True)
                editor.setPlainText(text)
                tabs.addTab(editor, label)
            box.addWidget(tabs, 1)
        else:
            box.addWidget(description, 1)
        source = item.get("source_url") or ""
        if urlsplit(source).scheme in {"https", "http"}:
            link = QPushButton(self.tr("Open source"))
            link.clicked.connect(lambda: self.open_source(QUrl(source)))
            box.addWidget(link)
        self.layout_box.insertWidget(0, body, 1)

    def description_image(self, url, image):
        if not isValid(self) or image is None or url not in self.description_urls:
            return
        document = self.description.document()
        document.addResource(
            QTextDocument.ResourceType.ImageResource,
            QUrl(f"preview-image:{self.description_urls.index(url)}"),
            image,
        )
        document.markContentsDirty(0, document.characterCount())
        self.description.viewport().update()

    @staticmethod
    def open_source(url):
        if url.scheme() in {"https", "http"}:
            QDesktopServices.openUrl(url)


class CardButton(QPushButton):
    def sizeHint(self):
        return self.layout().sizeHint() if self.layout() else super().sizeHint()

    def minimumSizeHint(self):
        return self.layout().minimumSize() if self.layout() else super().minimumSizeHint()


class SelectionCards(QWidget):
    def __init__(self, identifier, page_loader, item_loader, images, pages, offsets, parent=None):
        super().__init__(parent)
        self.setObjectName("selectionCards")
        self.identifier = identifier
        self.page_loader, self.item_loader = page_loader, item_loader
        self.images, self.pages, self.offsets = images, pages, offsets
        self.cards = []
        self.columns = 0
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(0, 8, 0, 8)
        self.heading = plain_label(self.tr("Loading selection…"), "selectionTitle")
        self.heading.setStyleSheet("font-size: 17px; font-weight: 600;")
        self.box.addWidget(self.heading)
        self.status = plain_label("")
        self.box.addWidget(self.status)
        self.grid = QGridLayout()
        self.grid.setSpacing(12)
        self.box.addLayout(self.grid)
        footer = QHBoxLayout()
        self.previous = QPushButton(self.tr("Previous"))
        self.next = QPushButton(self.tr("Next"))
        self.next.setObjectName("selectionNext")
        self.previous.clicked.connect(lambda: self.load(max(0, self.offset - 12)))
        self.next.clicked.connect(lambda: self.load(self.next_offset))
        footer.addWidget(self.previous)
        footer.addStretch()
        footer.addWidget(self.next)
        self.box.addLayout(footer)
        self.offset = offsets.get(identifier, 0)
        self.load(self.offset)

    def load(self, offset):
        self.offset = offset
        self.offsets[self.identifier] = offset
        self.previous.setEnabled(False)
        self.next.setEnabled(False)
        self.status.setText(self.tr("Loading…"))
        key = (self.identifier, offset)
        if key in self.pages:
            self.loaded(self.pages[key])
            return

        def done(page):
            if page.get("presentation_type") != "upload_drafts":
                self.pages[key] = page
            while len(self.pages) > 64:
                self.pages.pop(next(iter(self.pages)))
            if isValid(self) and self.offset == offset:
                self.loaded(page)

        run_in_background(
            lambda: self.page_loader(self.identifier, offset=offset, limit=12),
            done,
            self.failed,
        )

    def failed(self, error):
        if isValid(self):
            self.status.setText(str(error))
            self.previous.setEnabled(self.offset > 0)

    def loaded(self, page):
        self.heading.setText(page["title"])
        items = page["items"]
        total = page["count"]
        if page.get("presentation_type") == "upload_drafts":
            self.status.setText(
                self.tr("%1–%2 of %3 · saved Upload drafts")
                .replace("%1", str(self.offset + 1 if items else 0))
                .replace("%2", str(self.offset + len(items)))
                .replace("%3", str(total))
            )
        else:
            self.status.setText(
                self.tr("%1–%2 of %3 · saved revision %4")
                .replace("%1", str(self.offset + 1 if items else 0))
                .replace("%2", str(self.offset + len(items)))
                .replace("%3", str(total))
                .replace("%4", str(page.get("revision", "")))
            )
        for card in self.cards:
            self.grid.removeWidget(card)
            card.setParent(None)
            card.deleteLater()
        self.cards = []
        for item in items:
            card = CardButton()
            card.setObjectName("selectionCard")
            card.setProperty("kind", item["kind"])
            card.setAccessibleName(item.get("content_title") or item["title"])
            card.setToolTip(item["title"])
            card.setMinimumWidth(175)
            card.setStyleSheet(
                "QPushButton#selectionCard { border: 1px solid palette(mid);"
                "border-radius: 10px; padding: 10px; text-align: left; }"
                "QPushButton#selectionCard:hover { border-color: #27a79d; }"
            )
            content = QVBoxLayout(card)
            content.addWidget(Artwork(item, self.images))
            title = plain_label(item.get("content_title") or item["title"])
            title.setStyleSheet("font-weight: 600;")
            content.addWidget(title)
            if item.get("subtitle"):
                content.addWidget(plain_label(item["subtitle"]))
            content.addWidget(plain_label(card_size(item)))
            if item.get("presentation_type") == "upload_drafts":
                content.addWidget(plain_label(upload_summary(item)))
            else:
                content.addWidget(scores(item))
            if item.get("note"):
                content.addWidget(plain_label(item["note"]))
            content.addStretch()
            for child in card.findChildren(QLabel):
                child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            card.clicked.connect(lambda checked=False, i=item["item_id"]: self.open_item(i))
            self.cards.append(card)
        self.next_offset = page.get("next_offset")
        self.previous.setEnabled(self.offset > 0)
        self.next.setEnabled(bool(page["has_more"]))
        self.reflow()

    def reflow(self):
        columns = max(1, min(4, self.width() // 200))
        for index, card in enumerate(self.cards):
            self.grid.addWidget(card, index // columns, index % columns, Qt.AlignmentFlag.AlignTop)
        for column in range(4):
            self.grid.setColumnStretch(column, 1 if column < columns else 0)
        self.columns = columns

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if max(1, min(4, self.width() // 200)) != self.columns:
            self.reflow()

    def open_item(self, item_id):
        if self.item_loader:
            dialog = SelectionDetail(
                self.identifier, item_id, self.item_loader, self.images, self.window()
            )
            dialog.open()
