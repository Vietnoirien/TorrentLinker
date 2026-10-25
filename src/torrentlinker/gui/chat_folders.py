"""Conversation folders with stable selection and user-controlled expansion."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QStyle, QTreeWidget, QTreeWidgetItem


class ChatFolders(QTreeWidget):
    conversationSelected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderHidden(True)
        self.setIndentation(18)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.setStyleSheet(
            "QTreeWidget { border: none; background: transparent; } "
            "QTreeWidget::item { padding: 9px 3px; border-radius: 6px; }"
        )
        self.currentItemChanged.connect(self.selected)
        self.snapshot = None
        self.collapsed = set()
        self.itemCollapsed.connect(lambda item: self.collapsed.add(item.data(0, Qt.UserRole + 1)))
        self.itemExpanded.connect(
            lambda item: self.collapsed.discard(item.data(0, Qt.UserRole + 1))
        )

    def folder_label(self, folder):
        return {
            "": self.tr("General"),
            "uploads": self.tr("Uploads"),
            "film_research": self.tr("Film research"),
            "series_research": self.tr("Series research"),
            "troubleshooting": self.tr("Troubleshooting"),
        }.get(folder, folder)

    def selected(self, item, previous):
        if item and (identifier := item.data(0, Qt.UserRole)):
            self.conversationSelected.emit(identifier)

    def set_rows(self, rows, current=""):
        snapshot = [(r["id"], r["name"], r.get("folder", "")) for r in rows]
        if snapshot == self.snapshot:
            self.select_id(current)
            return
        self.snapshot = snapshot
        self.blockSignals(True)
        self.clear()
        groups = {}
        for identifier, name, folder in snapshot:
            if folder not in groups:
                group = QTreeWidgetItem(self, [self.folder_label(folder)])
                group.setData(0, Qt.UserRole + 1, folder)
                group.setFlags(group.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                group.setIcon(0, self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon))
                group.setExpanded(folder not in self.collapsed)
                groups[folder] = group
            child = QTreeWidgetItem(groups[folder], [name])
            child.setData(0, Qt.UserRole, identifier)
            child.setToolTip(0, name)
        self.blockSignals(False)
        self.select_id(current)

    def select_id(self, identifier):
        self.blockSignals(True)
        self.clearSelection()
        self.setCurrentItem(None)
        for index in range(self.topLevelItemCount()):
            group = self.topLevelItem(index)
            for row in range(group.childCount()):
                child = group.child(row)
                if child.data(0, Qt.UserRole) == identifier:
                    self.setCurrentItem(child)
        self.blockSignals(False)
