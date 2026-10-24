"""The Seeding list grouped by the Indexer's category hierarchy."""

from __future__ import annotations

from PySide6.QtCore import QItemSelectionModel, QSettings, QSignalBlocker, Qt
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTreeWidget, QTreeWidgetItem

from torrentlinker.category_tags import category_path
from torrentlinker.gui.library_model import human_size
from torrentlinker.gui.tables import EmptyState
from torrentlinker.seeding import Seeding

IDENTITY_ROLE = Qt.ItemDataRole.UserRole + 1
SEARCH_ROLE = Qt.ItemDataRole.UserRole + 2


class SeedingItem(QTreeWidgetItem):
    def __lt__(self, other: QTreeWidgetItem) -> bool:
        tree = self.treeWidget()
        column = tree.sortColumn() if tree else 0
        mine, theirs = (
            self.data(column, Qt.ItemDataRole.UserRole),
            other.data(column, Qt.ItemDataRole.UserRole),
        )
        if isinstance(mine, int | float) and isinstance(theirs, int | float):
            return mine < theirs
        return self.text(column).casefold() < other.text(column).casefold()

    def number(self, column: int, text: str, value: float) -> None:
        self.setText(column, text)
        self.setData(column, Qt.ItemDataRole.UserRole, value)
        self.setTextAlignment(column, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)


class SeedingTree(QTreeWidget):
    def __init__(self, settings: QSettings | None = None) -> None:
        super().__init__()
        self.setColumnCount(6)
        self.setHeaderLabels(
            [
                self.tr("Category / Torrent"),
                self.tr("Size"),
                self.tr("Seeders"),
                self.tr("Seed age (days)"),
                self.tr("≈ Zen/day"),
                self.tr("≈ Note"),
            ]
        )
        self.setAccessibleName(self.tr("Seeding by category"))
        self.setAlternatingRowColors(True)
        self.setUniformRowHeights(True)
        self.setIndentation(20)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        header = self.header()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(40)
        header.setDefaultSectionSize(130)
        header.resizeSection(0, 420)
        self.setSortingEnabled(True)
        self.sortItems(4, Qt.SortOrder.DescendingOrder)
        self.groups: dict[tuple[int, ...], SeedingItem] = {}
        self.torrents: dict[str, SeedingItem] = {}
        self._query = ""
        self._settings = settings if settings is not None else QSettings()
        saved = self._settings.value("zen/expanded_categories", [], type=list)
        self._expanded: set[str] = (
            {identity for identity in saved if isinstance(identity, str)}
            if isinstance(saved, list)
            else set()
        )
        self.itemExpanded.connect(self._remember_expansion)
        self.itemCollapsed.connect(self._remember_expansion)
        self.empty_state = EmptyState(
            self, self.tr("Refresh to see your seeding torrents and Zen estimates.")
        )
        self.headerItem().setToolTip(
            3, self.tr("Your torrent client's recorded seeding time; c411 may count more.")
        )
        self.headerItem().setToolTip(
            5,
            self.tr(
                "Estimated contribution note for your Class, category, swarm and seed age. "
                "Categories show the average across all their torrents and subcategories; "
                "unavailable notes are excluded."
            ),
        )

    def _save_expansion(self) -> None:
        self._settings.setValue("zen/expanded_categories", sorted(self._expanded))
        self._settings.sync()

    def _remember_expansion(self, item: QTreeWidgetItem) -> None:
        identity = item.data(0, IDENTITY_ROLE)
        if not isinstance(identity, str) or not identity.startswith("category:"):
            return
        if item.isExpanded():
            self._expanded.add(identity)
        else:
            self._expanded.discard(identity)
        self._save_expansion()

    def expandAll(self) -> None:
        with QSignalBlocker(self):
            super().expandAll()
        self._expanded.update(item.data(0, IDENTITY_ROLE) for item in self.groups.values())
        self._save_expansion()

    def collapseAll(self) -> None:
        with QSignalBlocker(self):
            super().collapseAll()
        self._expanded.clear()
        self._save_expansion()

    def show_seeding(self, view: Seeding) -> None:
        selected = {item.data(0, IDENTITY_ROLE) for item in self.selectedItems()}
        current = self.currentItem()
        current_id = current.data(0, IDENTITY_ROLE) if current else None
        current_column = self.currentColumn()
        scroll = self.verticalScrollBar().value()
        self.setUpdatesEnabled(False)
        self.setSortingEnabled(False)
        with QSignalBlocker(self):
            self.clear()
        self.groups = {}
        self.torrents = {}
        totals: dict[tuple[int, ...], list[float]] = {}
        for row in view.rows:
            path = category_path(row.category, view.categories)
            keys = [path[:length] for length in range(1, len(path) + 1)] or [()]
            parent = None
            names = []
            for key in keys:
                info = view.categories.get(key[-1]) if key else None
                name = (
                    info.name
                    if info
                    else self.tr("Category {0}").format(key[-1])
                    if key
                    else self.tr("Unknown category")
                )
                names.append(name)
                if key not in self.groups:
                    item = SeedingItem([name])
                    item.setData(0, IDENTITY_ROLE, "category:" + "/".join(map(str, key)))
                    item.setData(0, SEARCH_ROLE, name.casefold())
                    font = item.font(0)
                    font.setBold(True)
                    for col in (0, 1, 4, 5):
                        item.setFont(col, font)
                    if parent is None:
                        self.addTopLevelItem(item)
                    else:
                        parent.addChild(item)
                    self.groups[key] = item
                    totals[key] = [0, 0, 0, 0, 0]
                parent = self.groups[key]
                totals[key][0] += 1
                totals[key][1] += row.torrent.total_size
                totals[key][2] += row.zen or 0
                if row.note is not None:
                    totals[key][3] += row.note
                    totals[key][4] += 1
            assert parent is not None
            torrent = row.torrent
            item = SeedingItem([torrent.name])
            item.setData(0, IDENTITY_ROLE, "torrent:" + torrent.hash)
            item.setData(0, SEARCH_ROLE, " ".join([torrent.name, *names]).casefold())
            item.number(1, human_size(torrent.total_size), torrent.total_size)
            item.number(
                2,
                str(torrent.swarm_seeders) if torrent.swarm_seeders >= 0 else "–",
                torrent.swarm_seeders,
            )
            days = torrent.seeding_time / 86400
            item.number(3, f"{days:.0f}", days)
            item.number(
                4,
                f"≈ {row.zen:.2f}" if row.zen is not None else "–",
                row.zen if row.zen is not None else -1,
            )
            item.number(
                5,
                f"≈ {row.note:.2f}" if row.note is not None else "–",
                row.note if row.note is not None else -1,
            )
            tooltip = " / ".join(names)
            if row.provisional_category:
                tooltip += "\n" + self.tr(
                    "Category from the Catalogue snapshot; subcategory not confirmed."
                )
            item.setToolTip(0, torrent.name + "\n" + tooltip)
            if row.zen is None:
                item.setToolTip(4, self.tr("Not seeding: earns no Zen"))
            parent.addChild(item)
            self.torrents[torrent.hash] = item
        for key, item in self.groups.items():
            count, size, zen, note_sum, note_count = totals[key]
            item.setText(0, self.tr("{0} ({1})").format(item.text(0), int(count)))
            item.number(1, human_size(size), size)
            item.number(4, f"≈ {zen:.2f}", zen)
            average_note = note_sum / note_count if note_count else None
            item.number(
                5,
                f"≈ {average_note:.2f}" if average_note is not None else "–",
                average_note if average_note is not None else -1,
            )
            item.setToolTip(5, self.headerItem().toolTip(5))
            item.setToolTip(
                0,
                self.tr("{0} torrents; size and Zen/day include all subcategories.").format(
                    int(count)
                ),
            )
        self.setSortingEnabled(True)
        with QSignalBlocker(self):
            for item in [*self.groups.values(), *self.torrents.values()]:
                identity = item.data(0, IDENTITY_ROLE)
                if identity == current_id:
                    self.setCurrentItem(
                        item, current_column, QItemSelectionModel.SelectionFlag.NoUpdate
                    )
                item.setSelected(identity in selected)
            for item in self.groups.values():
                item.setExpanded(item.data(0, IDENTITY_ROLE) in self._expanded)
        self.filter(self._query)
        self.verticalScrollBar().setValue(scroll)
        self.setUpdatesEnabled(True)
        self.empty_state.update()

    def filter(self, text: str) -> None:
        query = text.strip().casefold()
        self._query = query
        # Opening matching branches is temporary, not a change to the user's layout.
        with QSignalBlocker(self):
            self._filter_rows(query)

    def _filter_rows(self, query: str) -> None:
        for item in self.torrents.values():
            item.setHidden(bool(query and query not in item.data(0, SEARCH_ROLE)))
        for key in sorted(self.groups, key=len, reverse=True):
            item = self.groups[key]
            visible = any(
                child is not None and not child.isHidden()
                for i in range(item.childCount())
                for child in [item.child(i)]
            )
            item.setHidden(not visible)
            if query and visible:
                item.setExpanded(True)
            elif not query:
                item.setExpanded(item.data(0, IDENTITY_ROLE) in self._expanded)
