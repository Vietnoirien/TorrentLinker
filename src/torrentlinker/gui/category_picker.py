"""A category picker with expandable parents and selectable subcategories."""

from __future__ import annotations

from collections.abc import Mapping

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QResizeEvent, QShortcut
from PySide6.QtWidgets import (
    QFrame,
    QSizePolicy,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from torrentlinker.downloads import IndexerCategory


class CategoryPicker(QToolButton):
    category_changed = Signal(object)
    categories_changed = Signal(object, object)  # the mapping and the root colors

    def __init__(self) -> None:
        super().__init__()
        self.current_category: int | None = None
        self.colors: dict[int, str] = {}
        self.categories: dict[int, IndexerCategory] = {}
        self.items: dict[int, QTreeWidgetItem] = {}
        self._label = self.tr("All categories")
        self.setAccessibleName(self.tr("Category"))
        self.setArrowType(Qt.ArrowType.DownArrow)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.popup = QFrame(self, Qt.WindowType.Popup)
        layout = QVBoxLayout(self.popup)
        layout.setContentsMargins(4, 4, 4, 4)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setAccessibleName(self.tr("Categories and subcategories"))
        self.tree.setUniformRowHeights(True)
        self.tree.setIndentation(22)
        self.tree.setMinimumSize(340, 300)
        self.tree.setHorizontalScrollMode(QTreeWidget.ScrollMode.ScrollPerPixel)
        self.tree.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(self.tree.header().ResizeMode.ResizeToContents)
        layout.addWidget(self.tree)
        self.clicked.connect(self.show_popup)
        self.tree.itemClicked.connect(self._choose)
        self.tree.itemActivated.connect(self._choose)
        escape = QShortcut(QKeySequence(Qt.Key.Key_Escape), self.tree)
        escape.activated.connect(self.popup.hide)
        self.set_categories({})

    def set_categories(self, categories: Mapping[int, IndexerCategory]) -> None:
        expanded = {cid for cid, item in self.items.items() if item.isExpanded()}
        self.categories = dict(categories)
        self.tree.clear()
        self.items = {cid: QTreeWidgetItem([info.name]) for cid, info in categories.items()}
        self.all_item = QTreeWidgetItem([self.tr("All categories")])
        self.tree.addTopLevelItem(self.all_item)
        for cid in sorted(categories, key=lambda key: categories[key].name.casefold()):
            item = self.items[cid]
            item.setData(0, Qt.ItemDataRole.UserRole, cid)
            # Malformed cycles cannot be represented in a tree; show those as roots.
            ancestors = {cid}
            parent = categories[cid].parent
            ancestor = parent
            while ancestor is not None and ancestor in categories and ancestor not in ancestors:
                ancestors.add(ancestor)
                ancestor = categories[ancestor].parent
            if parent in self.items and ancestor not in ancestors:
                self.items[parent].addChild(item)
            else:
                self.tree.addTopLevelItem(item)
        for cid, item in self.items.items():
            item.setExpanded(cid in expanded)
            item.setToolTip(0, self._path(item))
        self.select_category(self.current_category)
        self.categories_changed.emit(self.categories, self.colors)

    def select_category(self, category: int | None) -> None:
        previous = self.current_category
        item = self.items.get(category) if category is not None else None
        self.current_category = category if item is not None else None
        item = item or self.all_item
        self._label = self._path(item)
        self.setToolTip(self._label)
        self.tree.setCurrentItem(item)
        self._fit_label()
        if previous != self.current_category:
            self.category_changed.emit(self.current_category)

    @staticmethod
    def _path(item: QTreeWidgetItem) -> str:
        names = [item.text(0)]
        parent = item.parent()
        while parent is not None:
            names.append(parent.text(0))
            parent = parent.parent()
        return " / ".join(reversed(names))

    def _fit_label(self) -> None:
        elided = self.fontMetrics().elidedText(
            self._label, Qt.TextElideMode.ElideRight, max(40, self.width() - 40)
        )
        self.setText(elided.replace("&", "&&"))  # a lone & would become a mnemonic

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._fit_label()

    def show_popup(self) -> None:
        if self.popup.isVisible():
            self.popup.hide()
            return
        item = (
            self.items.get(self.current_category, self.all_item)
            if self.current_category is not None
            else self.all_item
        )
        self.tree.setCurrentItem(item)
        parent = item.parent()
        while parent is not None:
            parent.setExpanded(True)
            parent = parent.parent()
        screen = self.screen().availableGeometry()
        width = min(max(self.width(), 440), screen.width())
        height = min(420, screen.height())
        self.popup.resize(width, height)
        position = self.mapToGlobal(self.rect().bottomLeft())
        position.setX(min(position.x(), screen.right() - width + 1))
        if position.y() + height > screen.bottom():
            position.setY(max(screen.top(), self.mapToGlobal(self.rect().topLeft()).y() - height))
        self.popup.move(position)
        self.popup.show()
        self.tree.scrollToItem(item)
        self.tree.setFocus()

    def _choose(self, item: QTreeWidgetItem) -> None:
        self.select_category(item.data(0, Qt.ItemDataRole.UserRole))
        self.popup.hide()
        self.setFocus()
