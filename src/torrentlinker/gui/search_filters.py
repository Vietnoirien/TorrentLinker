"""Category-aware c411 search filters, loaded without blocking the window."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from torrentlinker.gui.category_picker import CategoryPicker
from torrentlinker.gui.controls import set_role
from torrentlinker.gui.errors import error_text
from torrentlinker.gui.flow_layout import FlowLayout
from torrentlinker.gui.search_widgets import SortChips
from torrentlinker.gui.tasks import run_in_background
from torrentlinker.indexer import Indexer
from torrentlinker.indexer_search import VIDEO_FILTERS, visible_facets
from torrentlinker.torrent_search import SearchFacet, SearchTree, parse_facets, parse_tree


class MultiFilter(QToolButton):
    """A searchable checklist that stays open while choosing several values."""

    def __init__(self, label: str, choices: tuple[tuple[str, str], ...]) -> None:
        super().__init__()
        self.label = label
        self.setAccessibleName(label)
        self.setArrowType(Qt.ArrowType.DownArrow)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.setProperty("chip", "filter")
        self.popup = QFrame(self, Qt.WindowType.Popup)
        layout = QVBoxLayout(self.popup)
        find = QLineEdit()
        find.setPlaceholderText(self.tr("Filter choices…"))
        find.setAccessibleName(self.tr("Filter choices"))
        layout.addWidget(find)
        self.items = QListWidget()
        self.items.setMinimumSize(240, 220)
        for title, value in choices:
            item = QListWidgetItem(title, self.items)
            item.setData(Qt.ItemDataRole.UserRole, value)
            item.setCheckState(Qt.CheckState.Unchecked)
        layout.addWidget(self.items)
        clear = QPushButton(self.tr("Clear"))
        set_role(clear, "quiet")
        clear.clicked.connect(self.clear)
        layout.addWidget(clear)
        find.textChanged.connect(self._filter)
        self.items.itemChanged.connect(self._label)
        self.clicked.connect(self._open)
        self._label()

    def _filter(self, text: str) -> None:
        for row in range(self.items.count()):
            item = self.items.item(row)
            item.setHidden(text.casefold() not in item.text().casefold())

    def _open(self) -> None:
        screen = self.screen().availableGeometry()
        self.popup.adjustSize()
        pos = self.mapToGlobal(self.rect().bottomLeft())
        pos.setX(max(screen.left(), min(pos.x(), screen.right() - self.popup.width())))
        if pos.y() + self.popup.height() > screen.bottom():
            pos.setY(
                max(screen.top(), self.mapToGlobal(self.rect().topLeft()).y() - self.popup.height())
            )
        self.popup.move(pos)
        self.popup.show()
        self.items.setFocus()

    def selected(self) -> list[str]:
        return [
            self.items.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.items.count())
            if self.items.item(i).checkState() == Qt.CheckState.Checked
        ]

    def clear(self) -> None:
        for row in range(self.items.count()):
            self.items.item(row).setCheckState(Qt.CheckState.Unchecked)

    def _label(self) -> None:
        selected = [
            self.items.item(i).text()
            for i in range(self.items.count())
            if self.items.item(i).checkState() == Qt.CheckState.Checked
        ]
        self.setText(self.label + (f" · {len(selected)}" if selected else ""))
        self.setProperty("active", bool(selected))
        self.style().unpolish(self)
        self.style().polish(self)
        self.setToolTip(", ".join(selected) if selected else self.label)


class SearchFilters(QWidget):
    ready_changed = Signal()
    sort_changed = Signal()

    def __init__(self, category: CategoryPicker) -> None:
        super().__init__()
        self.category = category
        self.indexer: Indexer | None = None
        self.tree: SearchTree | None = None
        self.ready = True
        self._generation = 0
        self._root: int | None = None
        self._cache: dict[int, list[SearchFacet]] = {}
        self.options: dict[str, MultiFilter] = {}
        self.video: dict[str, MultiFilter] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        global_filters = QHBoxLayout()
        global_filters.setSpacing(8)
        self.year = QLineEdit()
        self.year.setPlaceholderText(self.tr("Year"))
        self.year.setAccessibleName(self.tr("Year"))
        self.year.setValidator(QIntValidator(1900, 2100, self))
        self.year.setMaximumWidth(90)
        self.uploader = QLineEdit()
        self.uploader.setPlaceholderText(self.tr("Uploader"))
        self.uploader.setAccessibleName(self.tr("Uploader"))
        self.uploader.setMaxLength(100)
        self.uploader.setMaximumWidth(150)
        for field in (self.year, self.uploader):
            field.setProperty("chip", "filter")
        self.exclusive = QPushButton(self.tr("Exclusive"))
        self.exclusive.setCheckable(True)
        self.exclusive.setProperty("chip", "filter")
        self.palliative = QComboBox()
        self.palliative.setProperty("chip", "filter")
        self.palliative.setAccessibleName(self.tr("Revival torrents"))
        for label, value in [
            (self.tr("Available torrents"), ""),
            (self.tr("Include soins palliatifs"), "include"),
            (self.tr("Soins palliatifs only"), "only"),
        ]:
            self.palliative.addItem(label, value)
        self.crew = QPushButton(self.tr("Cast && crew"))
        self.crew.setCheckable(True)
        self.crew.setProperty("chip", "filter")
        self.crew.setToolTip(self.tr("Also search actors, directors and screenwriters."))
        self.crew.hide()
        self.sort = SortChips()
        self.sort.changed.connect(self.sort_changed)
        self.clear_button = QPushButton(self.tr("Clear all"))
        set_role(self.clear_button, "quiet")
        self.clear_button.clicked.connect(self.clear)
        category.setMaximumWidth(260)
        category.setProperty("chip", "filter")
        global_filters.addWidget(category)
        # Everything but the category menu needs c411's native search.
        self.native_controls = (self.year, self.uploader, self.exclusive, self.palliative)
        for widget in self.native_controls:
            global_filters.addWidget(widget)
            widget.hide()
        global_filters.addStretch()
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        global_filters.addWidget(self.status)
        self.retry = QPushButton(self.tr("Retry filters"))
        self.retry.clicked.connect(self._retry)
        self.retry.hide()
        global_filters.addWidget(self.retry)
        # The page puts its own actions (Follow in RSS) between the filters and Clear all.
        self.action_row = global_filters
        global_filters.addWidget(self.clear_button)
        layout.addLayout(global_filters)
        self.flow = FlowLayout(spacing=8)
        layout.addLayout(self.flow)
        category.category_changed.connect(self._category_changed)

    def configure(self, indexer: Indexer) -> None:
        if self.indexer is indexer:
            return
        self._generation += 1
        self.indexer = indexer
        self.tree = None
        self._cache.clear()
        self._root = None
        self._remove_controls()
        self.category.colors = {}
        for widget in self.native_controls:
            widget.setVisible(indexer.is_c411)
        if not indexer.is_c411:
            self.category.setEnabled(True)
            self._set_ready(True)
            return
        self.category.blockSignals(True)
        self.category.select_category(None)
        self.category.blockSignals(False)
        self._load_tree()

    def _set_ready(self, ready: bool, message: str = "") -> None:
        self.ready = ready
        self.status.setText(message)
        self.ready_changed.emit()

    def _load_tree(self) -> None:
        indexer = self.indexer
        if indexer is None:
            return
        self._generation += 1
        generation = self._generation
        self.retry.hide()
        self.category.setEnabled(False)
        self._set_ready(False, self.tr("Loading categories…"))

        def done(tree: SearchTree) -> None:
            if generation != self._generation:
                return
            self.tree = tree
            self.category.colors = tree.colors
            self.category.set_categories(tree.categories)
            self.category.setEnabled(True)
            self._set_ready(True)

        run_in_background(
            lambda: parse_tree(indexer.search_categories()),
            done,
            lambda error: self._failed(generation, error),
        )

    def _failed(self, generation: int, error: Exception) -> None:
        if generation != self._generation:
            return
        self.retry.show()
        self._set_ready(False, error_text(error))

    def _retry(self) -> None:
        if self.tree is None:
            self._load_tree()
        else:
            self._category_changed(self.category.current_category)

    def _remove_controls(self) -> None:
        while self.flow.count():
            item = self.flow.takeAt(0)
            widget = item.widget() if item else None
            if widget:
                widget.hide()
                widget.deleteLater()
        self.options.clear()
        self.video.clear()

    def _category_changed(self, selected: int | None) -> None:
        tree, indexer = self.tree, self.indexer
        if tree is None or indexer is None or not indexer.is_c411:
            return
        root = tree.root(selected)
        keep_video = (
            {key: control.selected() for key, control in self.video.items()}
            if root == self._root
            else {}
        )
        self._root = root
        self.crew.setVisible(root == 1)
        if root != 1:
            self.crew.setChecked(False)
        self._generation += 1
        generation = self._generation
        self._remove_controls()
        self.retry.hide()

        def done(facets: list[SearchFacet]) -> None:
            if generation != self._generation:
                return
            if root is not None:
                self._cache[root] = facets
            if root == 1:
                self._video_controls()
                for key, values in keep_video.items():
                    control = self.video[key]
                    for i in range(control.items.count()):
                        item = control.items.item(i)
                        if item.data(Qt.ItemDataRole.UserRole) in values:
                            item.setCheckState(Qt.CheckState.Checked)
            for facet in visible_facets(tree, selected, facets):
                self.options[facet.slug] = MultiFilter(facet.label, facet.choices)
            for control in [*self.video.values(), *self.options.values()]:
                self.flow.addWidget(control)
            self.flow.invalidate()
            self._set_ready(True)

        if root is None:
            done([])
        elif root in self._cache:
            done(self._cache[root])
        else:
            self._set_ready(False, self.tr("Loading category filters…"))
            run_in_background(
                lambda: parse_facets(indexer.search_filter_options(root)),
                done,
                lambda error: self._failed(generation, error),
            )

    def _video_controls(self) -> None:
        # First-party values verified 2026-10-23; docs/research/search-filters.md.
        definitions = [
            ("resolution", self.tr("Resolution"), VIDEO_FILTERS["resolution"]),
            ("source", self.tr("Source"), VIDEO_FILTERS["source"]),
            ("codec", self.tr("Codec"), VIDEO_FILTERS["codec"]),
            ("hdr", self.tr("HDR"), VIDEO_FILTERS["hdr"]),
            ("audioType", self.tr("Audio"), VIDEO_FILTERS["audioType"]),
            ("channels", self.tr("Channels"), VIDEO_FILTERS["channels"]),
            ("lang", self.tr("Language"), VIDEO_FILTERS["lang"]),
        ]
        for key, label, values in definitions:
            self.video[key] = MultiFilter(label, tuple((value, value) for value in values))
        self.video["profile"] = MultiFilter(
            self.tr("Profile"),
            (
                (self.tr("Compatibility"), "compatibility"),
                (self.tr("Home Cinema Pure"), "pure"),
                (self.tr("Home Cinema Optimized"), "hc_optimized"),
                (self.tr("Optimization"), "optimization"),
            ),
        )

    def clear(self) -> None:
        self.year.clear()
        self.uploader.clear()
        self.exclusive.setChecked(False)
        self.palliative.setCurrentIndex(0)
        self.crew.setChecked(False)
        self.sort.reset()
        for control in [*self.video.values(), *self.options.values()]:
            control.clear()
        self.category.select_category(None)

    def params(self, text: str) -> dict[str, str]:
        if not self.ready or self.tree is None:
            raise ValueError(self.tr("Wait for the search filters to load."))
        if self.year.text() and not self.year.hasAcceptableInput():
            raise ValueError(self.tr("Enter a year between 1900 and 2100."))
        params = {"sortBy": self.sort.key, "sortOrder": self.sort.order}
        if text:
            params["name"] = text[:200]
        elif params["sortBy"] == "relevance":
            params["sortBy"] = "createdAt"
        selected = self.category.current_category
        root = self.tree.root(selected)
        if root is not None:
            params["category"] = str(root)
        if selected is not None and selected < 0:
            params["subcat"] = str(-selected)
        for key, value in (
            ("year", self.year.text()),
            ("uploader", self.uploader.text().strip()),
            ("palliative", self.palliative.currentData()),
        ):
            if value:
                params[key] = value
        if self.exclusive.isChecked():
            params["exclusive"] = "true"
        if root == 1 and self.crew.isChecked() and text:
            params["crew"] = "true"
        for key, control in self.video.items():
            if control.selected():
                params[key] = ",".join(control.selected())
        options = [value for control in self.options.values() for value in control.selected()]
        if options:
            params["options"] = ",".join(options)
        return params
