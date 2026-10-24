"""Paginated book surface shared by EPUB text and illustrated pages."""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, QSizeF, Qt, QVariantAnimation, Signal
from PySide6.QtGui import (
    QAbstractTextDocumentLayout,
    QColor,
    QImage,
    QKeyEvent,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPalette,
    QPixmap,
    QResizeEvent,
    QTextDocument,
)
from PySide6.QtWidgets import QWidget


class BookPages(QWidget):
    turn_requested = Signal(int)
    changed = Signal()
    resized = Signal()
    link_clicked = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(100, 100)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.document: QTextDocument | None = None
        self.image = QImage()
        self.leaf = 0
        self.spread = 1
        self.page_size = QSizeF(500, 700)
        self._old = QPixmap()
        self._direction = 1
        self.animation = QVariantAnimation(self)
        self.animation.setDuration(240)
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(1.0)
        self.animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self.animation.valueChanged.connect(lambda _: self.update())
        self.animation.finished.connect(self._finish)

    @property
    def count(self) -> int:
        return self.document.pageCount() if self.document is not None else 1

    @property
    def fraction(self) -> float:
        return self.leaf / max(1, self.count - 1)

    def capture_turn(self, direction: int) -> None:
        self.animation.stop()
        self._old = QPixmap()
        self._old = self.grab()
        self._direction = direction

    def animate(self) -> None:
        if not self._old.isNull():
            self.animation.start()

    def _finish(self) -> None:
        self._old = QPixmap()
        self.update()

    def set_document(self, document: QTextDocument, fraction: float = 0) -> None:
        self.document = document
        self.image = QImage()
        self.reflow(fraction)

    def show_image(self, image: QImage) -> None:
        self.document = None
        self.image = image
        self.leaf = 0
        self.reflow()

    def reflow(self, fraction: float | None = None) -> None:
        if fraction is None:
            fraction = self.fraction
        text_page = self.document is not None and bool(
            self.document.toPlainText().replace("\ufffc", "").strip()
        )
        self.spread = 2 if text_page and self.width() >= 1050 else 1
        height = max(100, self.height() - 40)
        width = min(640, max(100, (self.width() - 48) / self.spread))
        if not self.image.isNull():
            width = min(
                max(100, self.width() - 48), height * self.image.width() / self.image.height()
            )
        self.page_size = QSizeF(width, height)
        if self.document is not None:
            self.document.setPageSize(self.page_size)
            self.leaf = min(self.count - 1, round(fraction * max(0, self.count - 1)))
        self.update()
        self.changed.emit()

    def turn(self, direction: int) -> bool:
        target = self.leaf + direction * self.spread
        if not 0 <= target < self.count:
            return False
        self.capture_turn(direction)
        self.leaf = target
        self.changed.emit()
        self.animate()
        return True

    def page_rect(self, slot: int = 0) -> QRectF:
        width, height = self.page_size.width(), self.page_size.height()
        return QRectF(
            (self.width() - width * self.spread) / 2 + slot * width,
            (self.height() - height) / 2,
            width,
            height,
        )

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        dark = self.palette().color(QPalette.ColorRole.Window).lightness() < 128
        paper = QColor("#292b2b" if dark else "#fffaf0")
        ink = QColor("#e5dfd1" if dark else "#302b24")
        for slot in range(self.spread):
            rect = self.page_rect(slot)
            painter.fillRect(rect.translated(3, 5), QColor(0, 0, 0, 50))
            painter.fillRect(rect, paper)
            if self.document is not None and self.leaf + slot < self.count:
                painter.save()
                painter.setClipRect(rect)
                painter.translate(rect.left(), rect.top() - (self.leaf + slot) * rect.height())
                context = QAbstractTextDocumentLayout.PaintContext()
                context.palette.setColor(QPalette.ColorRole.Text, ink)
                context.clip = QRectF(
                    0, (self.leaf + slot) * rect.height(), rect.width(), rect.height()
                )
                self.document.documentLayout().draw(painter, context)
                painter.restore()
            elif not self.image.isNull():
                target = QRectF(
                    QPointF(),
                    QSizeF(self.image.size()).scaled(
                        rect.size() - QSizeF(12, 12), Qt.AspectRatioMode.KeepAspectRatio
                    ),
                )
                target.moveCenter(rect.center())
                painter.drawImage(target, self.image)
            gradient = QLinearGradient(rect.left(), 0, rect.left() + 18, 0)
            gradient.setColorAt(0, QColor(0, 0, 0, 35))
            gradient.setColorAt(1, QColor(0, 0, 0, 0))
            painter.fillRect(QRectF(rect.left(), rect.top(), 18, rect.height()), gradient)
            if self.document is not None and self.leaf + slot < self.count:
                painter.setPen(ink)
                painter.drawText(
                    rect.adjusted(0, rect.height() - 28, 0, -6),
                    Qt.AlignmentFlag.AlignCenter,
                    str(self.leaf + slot + 1),
                )
        if self.animation.state() == QVariantAnimation.State.Running and not self._old.isNull():
            progress = float(self.animation.currentValue())
            sheet = self.page_rect(0).united(self.page_rect(self.spread - 1))
            width = sheet.width() * (1 - progress)
            left = sheet.left() if self._direction > 0 else sheet.right() - width
            painter.drawPixmap(QRectF(left, sheet.top(), width, sheet.height()), self._old, sheet)
            painter.fillRect(
                QRectF(
                    left + width - 12 if self._direction > 0 else left,
                    sheet.top(),
                    12,
                    sheet.height(),
                ),
                QColor(0, 0, 0, int(80 * (1 - progress))),
            )
        painter.end()

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        self.animation.stop()
        self._old = QPixmap()
        self.reflow()
        self.resized.emit()
        super().resizeEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Right, Qt.Key.Key_PageDown, Qt.Key.Key_Space):
            self.turn_requested.emit(1)
        elif event.key() in (Qt.Key.Key_Left, Qt.Key.Key_PageUp):
            self.turn_requested.emit(-1)
        else:
            super().keyPressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self.document is not None:
            for slot in range(self.spread):
                rect = self.page_rect(slot)
                if rect.contains(event.position()):
                    point = (
                        event.position()
                        - rect.topLeft()
                        + QPointF(0, (self.leaf + slot) * rect.height())
                    )
                    link = self.document.documentLayout().anchorAt(point)
                    if link:
                        self.link_clicked.emit(link)
                        return
        self.turn_requested.emit(-1 if event.position().x() < self.width() / 2 else 1)
