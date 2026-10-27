"""One horizontal row of the video home: a title, its cards and a way to see all of it."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QListView,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from torrentlinker.gui.controls import icon_button, set_role

CARD = QSize(180, 248)  # the same cards as the library grid
POSTER = QSize(128, 170)


class RowCards(QListWidget):
    """Cards side by side. A vertical wheel scrolls the page, not the row."""

    def wheelEvent(self, event):
        delta = event.angleDelta()
        if abs(delta.x()) > abs(delta.y()):
            super().wheelEvent(event)
        else:
            event.ignore()


class MediaRow(QWidget):
    chosen = Signal(str)
    activated = Signal(str)
    seeAll = Signal()

    def __init__(self, title: str, total: int, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("mediaRow")
        box = QVBoxLayout(self)
        box.setContentsMargins(24, 0, 24, 0)
        box.setSpacing(6)
        header = QHBoxLayout()
        header.setSpacing(6)
        self.title = QLabel(title)
        self.title.setObjectName("mediaSection")
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        header.addWidget(self.title)
        self.count = QLabel(self.tr("{0} titles").format(total))
        self.count.setStyleSheet("color: #9aa9ad; font-size: 11px;")
        header.addWidget(self.count, 0, Qt.AlignmentFlag.AlignBottom)
        header.addStretch()
        self.back = icon_button("‹", self.tr("Scroll left"))
        self.forward = icon_button("›", self.tr("Scroll right"))
        self.back.clicked.connect(lambda: self._page(-1))
        self.forward.clicked.connect(lambda: self._page(1))
        header.addWidget(self.back)
        header.addWidget(self.forward)
        self.see_all = QPushButton(self.tr("See all"))
        set_role(self.see_all, "quiet")
        self.see_all.clicked.connect(self.seeAll.emit)
        header.addWidget(self.see_all)
        box.addLayout(header)
        self.cards = RowCards()
        self.cards.setObjectName("mediaPosters")
        self.cards.setViewMode(QListView.ViewMode.IconMode)
        self.cards.setFlow(QListView.Flow.LeftToRight)
        self.cards.setWrapping(False)
        self.cards.setMovement(QListView.Movement.Static)
        self.cards.setUniformItemSizes(True)
        self.cards.setWordWrap(True)
        self.cards.setSpacing(8)
        self.cards.setGridSize(CARD)
        self.cards.setIconSize(POSTER)
        self.cards.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.cards.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.cards.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.cards.setFixedHeight(CARD.height() + 12)
        self.cards.itemClicked.connect(lambda item: self.chosen.emit(self._id(item)))
        self.cards.itemDoubleClicked.connect(lambda item: self.activated.emit(self._id(item)))
        self.cards.itemActivated.connect(lambda item: self.activated.emit(self._id(item)))
        box.addWidget(self.cards)

    @staticmethod
    def _id(item: QListWidgetItem) -> str:
        return str(item.data(Qt.ItemDataRole.UserRole))

    def _page(self, direction: int) -> None:
        bar = self.cards.horizontalScrollBar()
        bar.setValue(bar.value() + direction * max(CARD.width(), self.cards.width() - CARD.width()))

    def set_rows(
        self,
        rows: list[dict[str, Any]],
        title: Callable[[dict[str, Any]], str],
        icon: Callable[[dict[str, Any]], QIcon],
    ) -> None:
        self.cards.clear()
        for row in rows:
            item = QListWidgetItem(title(row))
            item.setToolTip(row["title"])
            item.setIcon(icon(row))
            item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
            item.setSizeHint(QSize(CARD.width() - 4, CARD.height() - 8))
            item.setData(Qt.ItemDataRole.UserRole, row["id"])
            self.cards.addItem(item)
        QTimer.singleShot(0, self._update_arrows)

    def set_icon(self, identifier: str, icon: QIcon) -> None:
        for index in range(self.cards.count()):
            item = self.cards.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == identifier:
                item.setIcon(icon)

    def clear_choice(self) -> None:
        self.cards.clearSelection()

    def _update_arrows(self) -> None:
        # The arrows appear only when the row is wider than the window.
        overflow = self.cards.horizontalScrollBar().maximum() > 0
        self.back.setVisible(overflow)
        self.forward.setVisible(overflow)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_arrows()
