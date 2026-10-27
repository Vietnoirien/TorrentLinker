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


EPISODE_CARD = QSize(232, 186)
EPISODE_STILL = QSize(216, 122)


class SeriesEpisodes(QWidget):
    """A chosen series unfolds here: one tab per season, then its episodes as a row of cards."""

    play = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("seriesEpisodes")
        self.episodes: list[dict[str, Any]] = []
        box = QVBoxLayout(self)
        box.setContentsMargins(24, 0, 24, 0)
        box.setSpacing(8)
        header = QHBoxLayout()
        self.title = QLabel(self.tr("Episodes"))
        self.title.setObjectName("mediaSection")
        header.addWidget(self.title)
        header.addSpacing(16)
        self.seasons = QHBoxLayout()
        self.seasons.setSpacing(14)
        header.addLayout(self.seasons)
        header.addStretch()
        self.back = icon_button("‹", self.tr("Scroll left"))
        self.forward = icon_button("›", self.tr("Scroll right"))
        self.back.clicked.connect(lambda: self._page(-1))
        self.forward.clicked.connect(lambda: self._page(1))
        header.addWidget(self.back)
        header.addWidget(self.forward)
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
        self.cards.setGridSize(EPISODE_CARD)
        self.cards.setIconSize(EPISODE_STILL)
        self.cards.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.cards.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.cards.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.cards.setFixedHeight(EPISODE_CARD.height() + 12)
        self.cards.itemDoubleClicked.connect(lambda item: self.play.emit(self._id(item)))
        self.cards.itemActivated.connect(lambda item: self.play.emit(self._id(item)))
        box.addWidget(self.cards)
        self.season_buttons: dict[int, QPushButton] = {}
        self.icon: Callable[[dict[str, Any]], QIcon] = lambda _row: QIcon()

    @staticmethod
    def _id(item: QListWidgetItem) -> str:
        return str(item.data(Qt.ItemDataRole.UserRole))

    def _page(self, direction: int) -> None:
        bar = self.cards.horizontalScrollBar()
        step = max(EPISODE_CARD.width(), self.cards.width() - EPISODE_CARD.width())
        bar.setValue(bar.value() + direction * step)

    def set_episodes(
        self,
        episodes: list[dict[str, Any]],
        time: Callable[[float], str],
        season: int | None,
        icon: Callable[[dict[str, Any]], QIcon],
    ) -> None:
        self.episodes = episodes
        self.time = time
        self.icon = icon
        for button in self.season_buttons.values():
            button.deleteLater()
        self.season_buttons = {}
        seasons = sorted({e["season"] for e in episodes if e.get("season") is not None})
        for number in seasons:
            button = QPushButton(self.tr("Season {0}").format(number))
            set_role(button, "tab")
            button.setCheckable(True)
            button.clicked.connect(lambda _checked=False, n=number: self.show_season(n))
            self.seasons.addWidget(button)
            self.season_buttons[number] = button
        if season not in seasons:
            season = seasons[0] if seasons else None
        self.show_season(season)

    def show_season(self, season: int | None) -> None:
        for number, button in self.season_buttons.items():
            button.setChecked(number == season)
        self.cards.clear()
        for episode in self.episodes:
            if season is not None and episode.get("season") != season:
                continue
            position = episode.get("episode")
            if episode.get("episode_title"):
                name = f"{position}. " if position is not None else ""
                name += str(episode["episode_title"])
            elif position is not None:
                name = self.tr("Episode {0}").format(position)
            else:
                name = str(episode.get("release") or episode["title"])
            facts = []
            if episode.get("duration"):
                facts.append(self.time(float(episode["duration"])))
            if episode.get("watched"):
                facts.append(self.tr("watched"))
            elif episode.get("position"):
                facts.append(self.tr("resume at {0}").format(self.time(float(episode["position"]))))
            if not episode.get("available", True):
                facts.append(self.tr("unavailable"))
            item = QListWidgetItem(name + ("\n" + " · ".join(facts) if facts else ""))
            item.setToolTip(str(episode.get("release") or name))
            item.setIcon(self.icon(episode))
            item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
            item.setSizeHint(QSize(EPISODE_CARD.width() - 4, EPISODE_CARD.height() - 8))
            item.setData(Qt.ItemDataRole.UserRole, episode["id"])
            self.cards.addItem(item)
        QTimer.singleShot(0, self._update_arrows)

    def _update_arrows(self) -> None:
        overflow = self.cards.horizontalScrollBar().maximum() > 0
        self.back.setVisible(overflow)
        self.forward.setVisible(overflow)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_arrows()
