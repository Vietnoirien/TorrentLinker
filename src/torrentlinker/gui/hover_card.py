"""The card that opens when the pointer rests on a result row, like c411's."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPixmap,
)
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from torrentlinker.torrent_search import ListingRow

CARD_WIDTH = 360
HEADER_HEIGHT = 226
BACKDROP = (720, 280)
POSTER = (176, 264)


def runtime_text(minutes: int | None) -> str:
    if not minutes:
        return ""
    return f"{minutes // 60}h{minutes % 60:02d}" if minutes >= 60 else f"{minutes} min"


class _Header(QWidget):
    """Backdrop with the type and rating on it, the poster, and the title beside it."""

    def __init__(self) -> None:
        super().__init__()
        self.setFixedSize(CARD_WIDTH, HEADER_HEIGHT)
        self.backdrop: QPixmap | None = None
        self.poster: QPixmap | None = None
        self.kind, self.rating, self.title, self.subtitle, self.meta = "", "", "", "", ""

    def paintEvent(self, event) -> None:  # noqa: ANN001
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width, top = self.width(), 128
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, width, self.height() + 12), 12, 12)
        painter.setClipPath(path)
        if self.backdrop is not None and not self.backdrop.isNull():
            scale = max(width / self.backdrop.width(), top / self.backdrop.height())
            w, h = self.backdrop.width() * scale, self.backdrop.height() * scale
            painter.drawPixmap(
                QRectF((width - w) / 2, (top - h) / 2, w, h),
                self.backdrop,
                QRectF(self.backdrop.rect()),
            )
        else:
            painter.fillRect(QRect(0, 0, width, top), QColor("#233c46"))
        fade = QLinearGradient(0, 0, 0, top)
        fade.setColorAt(0.0, QColor(0, 0, 0, 60))
        fade.setColorAt(1.0, QColor(10, 24, 28, 255))
        painter.fillRect(QRect(0, 0, width, top), fade)
        painter.fillRect(QRect(0, top, width, self.height() - top), QColor("#0a181c"))
        small = QFont(self.font())
        small.setPixelSize(11)
        small.setBold(True)
        painter.setFont(small)
        for text, x, align in ((self.kind, 14, "l"), (self.rating, width - 14, "r")):
            if not text:
                continue
            chip_w = painter.fontMetrics().horizontalAdvance(text) + 18
            chip = QRectF(x if align == "l" else x - chip_w, 12, chip_w, 24)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 0, 0, 150))
            painter.drawRoundedRect(chip, 7, 7)
            painter.setPen(QColor("#f5b301") if align == "r" else QColor("#d7e4e6"))
            painter.drawText(chip, Qt.AlignmentFlag.AlignCenter, text)
        box = QRectF(16, 56, 88, 132)
        if self.poster is not None and not self.poster.isNull():
            clip = QPainterPath()
            clip.addRoundedRect(box, 6, 6)
            painter.save()
            painter.setClipPath(clip)
            scale = max(box.width() / self.poster.width(), box.height() / self.poster.height())
            w, h = self.poster.width() * scale, self.poster.height() * scale
            painter.drawPixmap(
                QRectF(box.center().x() - w / 2, box.center().y() - h / 2, w, h),
                self.poster,
                QRectF(self.poster.rect()),
            )
            painter.restore()
        else:
            painter.setPen(QColor("#3a6a70"))
            painter.setBrush(QColor("#173238"))
            painter.drawRoundedRect(box, 6, 6)
        painter.setPen(QColor("#ffffff"))
        bold = QFont(self.font())
        bold.setPixelSize(14)
        bold.setBold(True)
        painter.setFont(bold)
        text_box = QRect(116, 132, width - 130, 58)
        painter.drawText(
            text_box, Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWrapAnywhere, self.title
        )
        small.setBold(False)
        painter.setFont(small)
        painter.setPen(QColor("#9fb3b6"))
        painter.drawText(
            QRect(116, 192, width - 130, 16), Qt.AlignmentFlag.AlignLeft, self.subtitle
        )
        painter.drawText(QRect(116, 208, width - 130, 16), Qt.AlignmentFlag.AlignLeft, self.meta)


class HoverCard(QFrame):
    """Shown beside a row after a short rest; it never takes the pointer or focus."""

    def __init__(self) -> None:
        super().__init__(None, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setObjectName("hoverCard")
        self.setFixedWidth(CARD_WIDTH)
        self.setStyleSheet(
            "QFrame#hoverCard { background: #0a181c; border: 1px solid #1f4a4d;"
            " border-radius: 12px; }"
            "QFrame#hoverCard QLabel { background: transparent; color: #d7e4e6; }"
            "QLabel#hoverChip { background: #12343a; border: 1px solid #1f6a64;"
            " border-radius: 9px; padding: 2px 8px; color: #7fe3d3; }"
            "QLabel#hoverCast { color: #d7e4e6; } QLabel#hoverRole { color: #8aa0a3; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 12)
        layout.setSpacing(8)
        self.header = _Header()
        layout.addWidget(self.header)
        body = QWidget()
        inner = QVBoxLayout(body)
        inner.setContentsMargins(14, 0, 14, 0)
        inner.setSpacing(8)
        self.genres = QHBoxLayout()
        self.genres.setSpacing(6)
        inner.addLayout(self.genres)
        self.overview = QLabel()
        self.overview.setWordWrap(True)
        self.overview.setTextFormat(Qt.TextFormat.PlainText)
        inner.addWidget(self.overview)
        self.cast = QVBoxLayout()
        self.cast.setSpacing(6)
        inner.addLayout(self.cast)
        layout.addWidget(body)

    def fill(
        self,
        info: ListingRow,
        release: str,
        kind: str,
        poster: QPixmap | None,
        backdrop: QPixmap | None,
    ) -> None:
        header = self.header
        header.kind = kind.upper()
        header.rating = f"★ {info.rating:.1f}" if info.rating else ""
        header.title = release
        header.subtitle = info.original_title if info.original_title != info.title else ""
        header.meta = " · ".join(
            part
            for part in (
                str(info.year) if info.year else "",
                runtime_text(info.runtime),
                info.directors[0] if info.directors else "",
            )
            if part
        )
        header.poster, header.backdrop = poster, backdrop
        header.update()
        while self.genres.count():
            item = self.genres.takeAt(0)
            widget = item.widget() if item else None
            if widget is not None:
                widget.hide()
                widget.deleteLater()
        for genre in info.genres[:3]:
            chip = QLabel(
                QFontMetrics(self.font()).elidedText(genre, Qt.TextElideMode.ElideRight, 96)
            )
            chip.setObjectName("hoverChip")
            self.genres.addWidget(chip)
        self.genres.addStretch()
        text = info.overview
        if len(text) > 260:
            text = text[:257].rsplit(" ", 1)[0] + "…"
        self.overview.setText(text)
        self.overview.setVisible(bool(text))
        while self.cast.count():
            item = self.cast.takeAt(0)
            widget = item.widget() if item else None
            if widget is not None:
                widget.hide()
                widget.deleteLater()
        for name in info.cast[:3]:
            row = QLabel(name)
            row.setObjectName("hoverCast")
            row.setTextFormat(Qt.TextFormat.PlainText)
            self.cast.addWidget(row)
        self.setFixedSize(CARD_WIDTH, self._height_for_content(info))

    def _height_for_content(self, info: ListingRow) -> int:
        """Counted piece by piece: a wrapped label's own estimate is not reliable in a layout."""
        height = HEADER_HEIGHT + 8
        if info.genres:
            height += 26 + 8
        if self.overview.isVisible() or self.overview.text():
            height += self.overview.heightForWidth(CARD_WIDTH - 28) + 8
        height += self.cast.count() * (QFontMetrics(self.font()).height() + 8)
        return height + 12

    def place(self, anchor: QRect, bounds: QRect) -> None:
        """Inside the app window, over the right end of the row, so it never leaves the app."""
        x = min(anchor.right() - self.width() - 12, bounds.right() - self.width() - 8)
        x = max(bounds.left() + 8, x)
        y = min(max(bounds.top() + 8, anchor.top() - 20), bounds.bottom() - self.height() - 8)
        self.move(QPoint(x, max(bounds.top() + 8, y)))
