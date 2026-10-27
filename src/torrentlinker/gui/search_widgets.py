"""Category pills and sort chips for the Search page."""

from __future__ import annotations

from collections.abc import Mapping

from PySide6.QtCore import QLocale, QSize, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QButtonGroup, QPushButton, QWidget

from torrentlinker.downloads import IndexerCategory
from torrentlinker.gui.flow_layout import FlowLayout

# Used when the Indexer sends no color for a root category.
FALLBACK_COLORS = ("#3b82f6", "#f59e0b", "#a855f7", "#6366f1", "#10b981", "#8b5cf6", "#ef4444")


def dot(color: str) -> QIcon:
    pixmap = QPixmap(10, 10)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor(color))
    painter.setPen(QColor(0, 0, 0, 0))
    painter.drawEllipse(0, 0, 10, 10)
    painter.end()
    return QIcon(pixmap)


class CategoryPills(QWidget):
    """One pill per root category, plus All. A pill picks the root; the Category menu picks
    a subcategory. Counts are the Indexer's global totals and do not follow the query."""

    category_chosen = Signal(object)  # int | None

    def __init__(self) -> None:
        super().__init__()
        self.flow = FlowLayout(self, 8)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: dict[int | None, QPushButton] = {}
        self._names: dict[int | None, str] = {}
        self._parents: dict[int, int | None] = {}
        self._counts: dict[int, int] = {}
        self._current: int | None = None
        self._colors: dict[str, str] = {}
        self.set_categories({})

    def set_categories(
        self, categories: Mapping[int, IndexerCategory], colors: Mapping[int, str] | None = None
    ) -> None:
        for button in self.buttons.values():
            self.group.removeButton(button)
            self.flow.removeWidget(button)
            button.hide()  # until the deferred delete runs, it must not paint at a stale place
            button.deleteLater()
        self.buttons.clear()
        self._parents = {cid: info.parent for cid, info in categories.items()}
        roots = [cid for cid, info in categories.items() if info.parent not in categories]
        self._names = {None: self.tr("All"), **{cid: categories[cid].name for cid in roots}}
        self._colors = {}
        for index, key in enumerate(self._names):
            button = QPushButton()
            button.setProperty("chip", "pill")
            button.setCheckable(True)
            color = (colors or {}).get(key or 0) or FALLBACK_COLORS[index % len(FALLBACK_COLORS)]
            button.setIcon(dot(color))
            if key is not None:
                self._colors[self._names[key]] = color
            button.setIconSize(QSize(10, 10))
            button.clicked.connect(lambda _=False, k=key: self.category_chosen.emit(k))
            self.group.addButton(button)
            self.flow.addWidget(button)
            self.buttons[key] = button
        self.set_counts(self._counts)
        self.select(self._current)
        self.setVisible(len(roots) > 0)

    def color_for(self, root_name: str) -> str | None:
        """The pill color of a root category, by name; the result rows reuse it."""
        return self._colors.get(root_name)

    def set_counts(self, counts: Mapping[int, int]) -> None:
        self._counts = dict(counts)
        locale = QLocale()
        for key, button in self.buttons.items():
            name = self._names[key]
            count = (
                sum(self._counts.get(cid, 0) for cid in self.buttons if cid is not None)
                if key is None
                else self._counts.get(key)
            )
            shown = count if self._counts else None
            label = name.replace("&", "&&")  # a lone & would become a mnemonic
            button.setText(label if shown is None else f"{label}  {locale.toString(shown)}")
        self.flow.invalidate()

    def select(self, category: int | None) -> None:
        """Highlight the root of the chosen category (a subcategory lights its parent)."""
        self._current = category
        seen: set[int] = set()
        root = category
        while root is not None and self._parents.get(root) is not None and root not in seen:
            seen.add(root)
            root = self._parents[root]
        button = self.buttons.get(root) or self.buttons.get(None)
        if button is not None:
            button.setChecked(True)


class SortChips(QWidget):
    """Sort by one column; clicking the active chip flips the direction."""

    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.key, self.order = "createdAt", "desc"
        self.flow = FlowLayout(self, 4)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.labels = {
            "createdAt": self.tr("Age"),
            "seeders": self.tr("Seeders"),
            "leechers": self.tr("Leechers"),
            "size": self.tr("Size"),
            "completions": self.tr("Completed"),
            "comments": self.tr("Comments"),
            "name": self.tr("Name"),
            "category": self.tr("Type"),
            "relevance": self.tr("Relevance"),
        }
        self.buttons: dict[str, QPushButton] = {}
        for key in self.labels:
            button = QPushButton()
            button.setProperty("chip", "sort")
            button.setCheckable(True)
            button.clicked.connect(lambda _=False, k=key: self._clicked(k))
            self.group.addButton(button)
            self.flow.addWidget(button)
            self.buttons[key] = button
        self.set_relevance_available(False)
        self._paint()

    def _clicked(self, key: str) -> None:
        if key == self.key:
            self.order = "asc" if self.order == "desc" else "desc"
        else:
            self.key, self.order = key, "asc" if key == "name" else "desc"
        self._paint()
        self.changed.emit()

    def _paint(self) -> None:
        for key, button in self.buttons.items():
            arrow = (" ↓" if self.order == "desc" else " ↑") if key == self.key else ""
            button.setText(self.labels[key] + arrow)
            button.setChecked(key == self.key)

    def set_relevance_available(self, available: bool) -> None:
        """Relevance only means something while there is a text query."""
        self.buttons["relevance"].setVisible(available)
        if not available and self.key == "relevance":
            self.key, self.order = "createdAt", "desc"
            self._paint()
        self.flow.invalidate()

    def reset(self) -> None:
        self.key, self.order = "createdAt", "desc"
        self._paint()
