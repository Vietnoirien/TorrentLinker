"""Painted cells for the comfortable Search results: title and tags, seeders bar, age."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import (
    QCoreApplication,
    QModelIndex,
    QPersistentModelIndex,
    QPointF,
    QRect,
    QRectF,
    QSize,
    Qt,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QFontMetrics,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QApplication, QStyle, QStyledItemDelegate, QStyleOptionViewItem

from torrentlinker.torrent_search import ListingRow

ROW_HEIGHT = 88
COMPACT_HEIGHT = 56
TAG_COLORS = {
    "lang": "#10b981",
    "resolution": "#3b82f6",
    "source": "#06b6d4",
    "audio": "#f59e0b",
    "codec": "#94a3b8",
    "hdr": "#a855f7",
}
GOLD, GREEN, RED = "#f5b301", "#22b573", "#ef4444"


@dataclass(frozen=True)
class RowView:
    """What a comfortable row shows, gathered by the Search tab for one result."""

    title: str  # the release name
    label: str  # the category path, for the type badge
    size: str
    seeders: int
    age: str
    details: ListingRow | None = None
    revival: bool = False
    color: str = "#64748b"
    zen: str = ""
    state: str = ""  # "client" when the torrent client has it, "queued" when our queue does
    poster: QPixmap | None = None


Lookup = Callable[[QModelIndex | QPersistentModelIndex], RowView | None]


def _points(font: QFont) -> float:
    """The font's size in points; a style sheet that sets pixels leaves it at -1."""
    return font.pointSizeF() if font.pointSizeF() > 0 else 10.0


def _dark(option: QStyleOptionViewItem) -> bool:
    return option.palette.base().color().lightness() < 128


def _readable(color: str, option: QStyleOptionViewItem) -> QColor:
    base = QColor(color)
    return base if _dark(option) else base.darker(140)


def _chip(
    painter: QPainter, x: int, y: int, text: str, color: QColor, font: QFont, height: int = 18
) -> int:
    """Draw a rounded tag at x,y and return the x after it."""
    metrics = QFontMetrics(font)
    width = metrics.horizontalAdvance(text) + 14
    fill = QColor(color)
    fill.setAlpha(38)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(fill)
    painter.drawRoundedRect(QRectF(x, y, width, height), 5, 5)
    painter.setPen(color)
    painter.setFont(font)
    painter.drawText(QRect(x, y, width, height), Qt.AlignmentFlag.AlignCenter, text)
    return x + width + 6


class _Delegate(QStyledItemDelegate):
    def __init__(self, lookup: Lookup, parent=None) -> None:
        super().__init__(parent)
        self.lookup = lookup

    def sizeHint(self, option, index) -> QSize:  # noqa: ANN001
        return QSize(option.rect.width(), ROW_HEIGHT)

    def _background(self, painter: QPainter, option: QStyleOptionViewItem) -> None:
        QApplication.style().drawPrimitive(
            QStyle.PrimitiveElement.PE_PanelItemViewItem, option, painter, option.widget
        )


def state_chip(
    painter: QPainter, option: QStyleOptionViewItem, right: int, y: int, state: str, small: QFont
) -> None:
    """The In client / Queued mark, right-aligned at `right`."""
    label, shade = (
        (QCoreApplication.translate("TitleDelegate", "In client"), GREEN)
        if state == "client"
        else (QCoreApplication.translate("TitleDelegate", "Queued"), GOLD)
    )
    width = QFontMetrics(small).horizontalAdvance("● " + label) + 14
    _chip(painter, right - width, y, "● " + label, _readable(shade, option), small)


class CompactMarkDelegate(QStyledItemDelegate):
    """The plain compact title cell, plus the In client / Queued mark at its right edge."""

    def __init__(self, lookup: Lookup, parent=None) -> None:
        super().__init__(parent)
        self.lookup = lookup

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:  # noqa: ANN001
        super().paint(painter, option, index)
        view = self.lookup(index)
        if view is None or not view.state:
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        small = QFont(option.font)
        small.setPointSizeF(max(8.0, _points(option.font) - 2))
        state_chip(
            painter,
            option,
            option.rect.right() - 6,
            option.rect.top() + (option.rect.height() - 18) // 2,
            view.state,
            small,
        )
        painter.restore()


class TitleDelegate(_Delegate):
    """Cover placeholder, type badge, title, year, rating, release name and tags."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:  # noqa: ANN001
        view = self.lookup(index)
        if view is None:
            return super().paint(painter, option, index)
        self._background(painter, option)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = option.rect
        text = option.palette.color(QPalette.ColorRole.Text)
        muted = option.palette.color(QPalette.ColorRole.PlaceholderText)
        details = view.details
        cover = QRectF(rect.left() + 10, rect.top() + 12, 52, 64)
        small = QFont(option.font)
        small.setPointSizeF(max(8.0, _points(option.font) - 2))
        if view.poster is not None and not view.poster.isNull():
            # The poster fills the cover frame, cropped to its shape.
            clip = QPainterPath()
            clip.addRoundedRect(cover, 6, 6)
            painter.save()
            painter.setClipPath(clip)
            scale = max(cover.width() / view.poster.width(), cover.height() / view.poster.height())
            width, height = view.poster.width() * scale, view.poster.height() * scale
            painter.drawPixmap(
                QRectF(
                    cover.center().x() - width / 2, cover.center().y() - height / 2, width, height
                ),
                view.poster,
                QRectF(view.poster.rect()),
            )
            painter.restore()
        else:
            # No poster: the category color with the first letters of the type.
            fill = QColor(view.color)
            fill.setAlpha(46)
            painter.setPen(QColor(view.color))
            painter.setBrush(fill)
            painter.drawRoundedRect(cover, 6, 6)
            painter.setFont(option.font)
            painter.setPen(_readable(view.color, option))
            painter.drawText(
                cover,
                Qt.AlignmentFlag.AlignCenter,
                (view.label.split(" / ")[-1] or "?")[:2].upper(),
            )
        left = rect.left() + 74
        right = rect.right() - 10
        # Line 1: type badge, title, year, rating, marks.
        x, y = left, rect.top() + 12
        badge = view.label.split(" / ")[-1]
        if badge:
            x = _chip(painter, x, y, badge, _readable(view.color, option), small)
        bold = QFont(option.font)
        bold.setBold(True)
        bold.setPointSizeF(_points(option.font) + 1)
        name = (details.title if details and details.title else view.title) or view.title
        extras = 0
        year = f"{details.year}" if details and details.year else ""
        rating = f"★ {details.rating:.1f}".replace(".", ".") if details and details.rating else ""
        if year:
            extras += QFontMetrics(small).horizontalAdvance(year) + 10
        if rating:
            extras += QFontMetrics(small).horizontalAdvance(rating) + 22
        marks = ("♥ " if view.revival else "") + ("★ " if details and details.exclusive else "")
        metrics = QFontMetrics(bold)
        shown = metrics.elidedText(
            name, Qt.TextElideMode.ElideRight, max(40, right - x - extras - 30)
        )
        painter.setFont(bold)
        painter.setPen(text)
        painter.drawText(QRect(x, y - 2, right - x, 22), Qt.AlignmentFlag.AlignVCenter, shown)
        x += metrics.horizontalAdvance(shown) + 8
        if year:
            painter.setFont(small)
            painter.setPen(muted)
            painter.drawText(QRect(x, y - 2, 60, 22), Qt.AlignmentFlag.AlignVCenter, year)
            x += QFontMetrics(small).horizontalAdvance(year) + 10
        if rating:
            x = _chip(painter, x, y, rating, QColor(GOLD), small)
        if marks:
            painter.setFont(small)
            painter.setPen(QColor(RED) if view.revival else QColor(GOLD))
            painter.drawText(QRect(x, y - 2, 40, 22), Qt.AlignmentFlag.AlignVCenter, marks.strip())
        if view.state:
            state_chip(painter, option, right, y, view.state, small)
        # Line 2: the release name in monospace.
        mono = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        mono.setPointSizeF(max(8.0, _points(option.font) - 1))
        painter.setFont(mono)
        painter.setPen(option.palette.color(QPalette.ColorRole.Link))
        release = QFontMetrics(mono).elidedText(
            view.title, Qt.TextElideMode.ElideMiddle, max(40, right - left)
        )
        painter.drawText(
            QRect(left, rect.top() + 36, right - left, 18), Qt.AlignmentFlag.AlignVCenter, release
        )
        # Line 3: tags.
        x, y = left, rect.top() + 58
        for kind, label in details.tags if details else ():
            if x > right - 40:
                break
            x = _chip(
                painter, x, y, label, _readable(TAG_COLORS.get(kind, "#94a3b8"), option), small
            )
        painter.restore()


class StatsDelegate(_Delegate):
    """Size, seeders and leechers, and a bar showing their balance."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:  # noqa: ANN001
        view = self.lookup(index)
        if view is None:
            return super().paint(painter, option, index)
        self._background(painter, option)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = option.rect.adjusted(8, 0, -8, 0)
        leechers = view.details.leechers if view.details else 0
        bold = QFont(option.font)
        bold.setBold(True)
        painter.setFont(bold)
        painter.setPen(_readable(GREEN, option))
        painter.drawText(
            QRect(rect.left(), rect.top() + 14, rect.width(), 20),
            Qt.AlignmentFlag.AlignVCenter,
            view.size,
        )
        painter.setFont(option.font)
        painter.setPen(_readable(GREEN, option))
        painter.drawText(
            QRect(rect.left(), rect.top() + 36, rect.width() // 2, 18),
            Qt.AlignmentFlag.AlignVCenter,
            f"↑ {view.seeders}",
        )
        painter.setPen(_readable(RED, option))
        painter.drawText(
            QRect(rect.left() + rect.width() // 2, rect.top() + 36, rect.width() // 2, 18),
            Qt.AlignmentFlag.AlignVCenter,
            f"↓ {leechers}",
        )
        bar = QRectF(rect.left(), rect.top() + 60, rect.width(), 5)
        painter.setPen(Qt.PenStyle.NoPen)
        total = view.seeders + leechers
        if total == 0:
            painter.setBrush(option.palette.color(QPalette.ColorRole.Mid))
            painter.drawRoundedRect(bar, 2.5, 2.5)
        else:
            painter.setBrush(QColor(RED))
            painter.drawRoundedRect(bar, 2.5, 2.5)
            share = bar.width() * view.seeders / total
            painter.setBrush(QColor(GREEN))
            painter.drawRoundedRect(QRectF(bar.left(), bar.top(), share, bar.height()), 2.5, 2.5)
        painter.restore()


class AgeDelegate(_Delegate):
    """Age, completed downloads and the uploader."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:  # noqa: ANN001
        view = self.lookup(index)
        if view is None:
            return super().paint(painter, option, index)
        self._background(painter, option)
        painter.save()
        rect = option.rect.adjusted(8, 0, -10, 0)
        muted = option.palette.color(QPalette.ColorRole.PlaceholderText)
        text = option.palette.color(QPalette.ColorRole.Text)
        details = view.details
        right = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        painter.setFont(option.font)
        painter.setPen(text)
        painter.drawText(QRect(rect.left(), rect.top() + 14, rect.width(), 20), right, view.age)
        painter.setPen(muted)
        if details:
            painter.drawText(
                QRect(rect.left(), rect.top() + 36, rect.width(), 18),
                right,
                self.tr("{0} compl.").format(details.completions),
            )
            if details.uploader:
                shown = QFontMetrics(option.font).elidedText(
                    details.uploader, Qt.TextElideMode.ElideRight, rect.width()
                )
                painter.drawText(
                    QRect(rect.left(), rect.top() + 58, rect.width(), 18), right, shown
                )
        painter.restore()


class ZenDelegate(_Delegate):
    """The Zen estimate as a small pill; the table cell keeps the number for sorting."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:  # noqa: ANN001
        text = index.data(Qt.ItemDataRole.DisplayRole)
        if not text or text == "–":
            return super().paint(painter, option, index)
        self._background(painter, option)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        small = QFont(option.font)
        small.setPointSizeF(max(8.0, _points(option.font) - 1))
        label = f"{text} {self.tr('Zen/day')}"
        width = QFontMetrics(small).horizontalAdvance(label) + 14
        x = option.rect.left() + max(6, (option.rect.width() - width) // 2)
        _chip(
            painter,
            x,
            option.rect.top() + (option.rect.height() - 20) // 2,
            label,
            _readable("#14b8a6", option),
            small,
            20,
        )
        painter.restore()


class DownloadDelegate(_Delegate):
    """A square download button; the table's click handler queues the row."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:  # noqa: ANN001
        self._background(painter, option)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        side = 34
        box = QRectF(
            option.rect.center().x() - side / 2, option.rect.center().y() - side / 2, side, side
        )
        painter.setPen(option.palette.color(QPalette.ColorRole.Mid))
        painter.setBrush(option.palette.color(QPalette.ColorRole.Button))
        painter.drawRoundedRect(box, 8, 8)
        pen = QPen(option.palette.color(QPalette.ColorRole.Link), 2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        cx, cy = box.center().x(), box.center().y()
        painter.drawLine(QPointF(cx, cy - 8), QPointF(cx, cy + 3))
        painter.drawPolyline(
            [QPointF(cx - 5, cy - 2), QPointF(cx, cy + 4), QPointF(cx + 5, cy - 2)]
        )
        painter.drawLine(QPointF(cx - 8, cy + 9), QPointF(cx + 8, cy + 9))
        painter.restore()


class TypeBadgeDelegate(_Delegate):
    """The compact view's first column: the subcategory as a colored badge, like c411's."""

    def sizeHint(self, option, index) -> QSize:  # noqa: ANN001
        return QSize(option.rect.width(), COMPACT_HEIGHT)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:  # noqa: ANN001
        view = self.lookup(index)
        if view is None:
            return super().paint(painter, option, index)
        self._background(painter, option)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        box = QRectF(option.rect.left() + 8, option.rect.center().y() - 16, 92, 32)
        base = QColor(view.color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(base.red(), base.green(), base.blue(), 70))
        painter.drawRoundedRect(box, 6, 6)
        font = QFont(option.font)
        font.setBold(True)
        font.setPointSizeF(max(8.0, _points(option.font) - 2))
        painter.setFont(font)
        painter.setPen(_readable(view.color, option))
        label = (view.label.split(" / ")[-1] or "?").upper()
        shown = QFontMetrics(font).elidedText(label, Qt.TextElideMode.ElideRight, 84)
        painter.drawText(box, Qt.AlignmentFlag.AlignCenter, shown)
        painter.restore()


class CompactNameDelegate(_Delegate):
    """The release name, with c411's short tags under it: EXCLU, language, quality."""

    def sizeHint(self, option, index) -> QSize:  # noqa: ANN001
        return QSize(option.rect.width(), COMPACT_HEIGHT)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:  # noqa: ANN001
        view = self.lookup(index)
        if view is None:
            return super().paint(painter, option, index)
        self._background(painter, option)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = option.rect
        left, right = rect.left() + 8, rect.right() - 8
        small = QFont(option.font)
        small.setPointSizeF(max(8.0, _points(option.font) - 2))
        width = 0
        if view.state:
            width = 96
        painter.setFont(option.font)
        painter.setPen(option.palette.color(QPalette.ColorRole.Link))
        name = QFontMetrics(option.font).elidedText(
            view.title, Qt.TextElideMode.ElideRight, max(40, right - left - width)
        )
        painter.drawText(
            QRect(left, rect.top() + 6, right - left - width, 20),
            Qt.AlignmentFlag.AlignVCenter,
            name,
        )
        if view.state:
            state_chip(painter, option, right, rect.top() + 8, view.state, small)
        x, y = left, rect.top() + 30
        details = view.details
        if details and details.exclusive:
            x = _chip(painter, x, y, self.tr("EXCLU"), QColor(GOLD).darker(110), small)
        if view.revival:
            x = _chip(painter, x, y, "♥", QColor(RED), small)
        if details and details.language:
            x = _chip(painter, x, y, details.language, _readable("#3b82f6", option), small)
        if details and details.quality:
            x = _chip(painter, x, y, details.quality, _readable("#a855f7", option), small)
        painter.restore()


class ColoredNumberDelegate(QStyledItemDelegate):
    """A centered number in a fixed color: green seeders, red leechers, muted the rest."""

    def __init__(self, color: str | None, parent=None) -> None:
        super().__init__(parent)
        self.color = color

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:  # noqa: ANN001
        QApplication.style().drawPrimitive(
            QStyle.PrimitiveElement.PE_PanelItemViewItem, option, painter, option.widget
        )
        text = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        painter.save()
        if self.color is None:
            painter.setPen(option.palette.color(QPalette.ColorRole.PlaceholderText))
        elif text not in ("0", "–"):
            painter.setPen(_readable(self.color, option))
        else:
            painter.setPen(option.palette.color(QPalette.ColorRole.PlaceholderText))
        painter.setFont(option.font)
        painter.drawText(option.rect, Qt.AlignmentFlag.AlignCenter, text)
        painter.restore()
