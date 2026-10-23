"""Category-aware c411 search filters, loaded without blocking the window."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
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
from torrentlinker.gui.errors import error_text
from torrentlinker.gui.tasks import run_in_background
from torrentlinker.indexer import Indexer
from torrentlinker.torrent_search import SearchFacet, SearchTree, parse_facets, parse_tree


class MultiFilter(QToolButton):
    """A searchable checklist that stays open while choosing several values."""

    def __init__(self, label: str, choices: tuple[tuple[str, str], ...]) -> None:
        super().__init__()
        self.label = label
        self.setAccessibleName(label)
        self.setArrowType(Qt.ArrowType.DownArrow)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
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
        self.setToolTip(", ".join(selected) if selected else self.label)


class SearchFilters(QWidget):
    ready_changed = Signal()

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
        self.grid = QGridLayout()
        layout.addLayout(self.grid)
        global_filters = QHBoxLayout()
        self.year = QLineEdit()
        self.year.setPlaceholderText(self.tr("Year"))
        self.year.setAccessibleName(self.tr("Year"))
        self.year.setValidator(QIntValidator(1900, 2100, self))
        self.year.setMaximumWidth(85)
        self.uploader = QLineEdit()
        self.uploader.setPlaceholderText(self.tr("Uploader"))
        self.uploader.setAccessibleName(self.tr("Uploader"))
        self.uploader.setMaxLength(100)
        self.exclusive = QCheckBox(self.tr("Exclusive"))
        self.palliative = QComboBox()
        self.palliative.setAccessibleName(self.tr("Revival torrents"))
        for label, value in [
            (self.tr("Available torrents"), ""),
            (self.tr("Include soins palliatifs"), "include"),
            (self.tr("Soins palliatifs only"), "only"),
        ]:
            self.palliative.addItem(label, value)
        self.sort = QComboBox()
        self.sort.setAccessibleName(self.tr("Sort results by"))
        for label, key in [
            (self.tr("Newest"), "createdAt"),
            (self.tr("Seeders"), "seeders"),
            (self.tr("Leechers"), "leechers"),
            (self.tr("Size"), "size"),
            (self.tr("Completed downloads"), "completions"),
            (self.tr("Comments"), "comments"),
            (self.tr("Name"), "name"),
            (self.tr("Category"), "category"),
            (self.tr("Relevance"), "relevance"),
        ]:
            self.sort.addItem(label, key)
        self.order = QComboBox()
        self.order.setAccessibleName(self.tr("Sort direction"))
        self.order.addItem(self.tr("Descending"), "desc")
        self.order.addItem(self.tr("Ascending"), "asc")
        self.clear_button = QPushButton(self.tr("Clear filters"))
        self.clear_button.clicked.connect(self.clear)
        # Two rows keep filters usable at the minimum window width.
        for widget in (self.year, self.uploader, self.exclusive, self.palliative):
            global_filters.addWidget(widget)
        layout.addLayout(global_filters)
        footer = QHBoxLayout()
        footer.addWidget(self.sort)
        footer.addWidget(self.order)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        footer.addWidget(self.status, 1)
        self.retry = QPushButton(self.tr("Retry filters"))
        self.retry.clicked.connect(self._retry)
        self.retry.hide()
        footer.addWidget(self.retry)
        footer.addWidget(self.clear_button)
        layout.addLayout(footer)
        category.category_changed.connect(self._category_changed)
        self.hide()

    def configure(self, indexer: Indexer) -> None:
        if self.indexer is indexer:
            return
        self._generation += 1
        self.indexer = indexer
        self.tree = None
        self._cache.clear()
        self._root = None
        self._remove_controls()
        self.setVisible(indexer.is_c411)
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
        while self.grid.count():
            item = self.grid.takeAt(0)
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
            for facet in facets:
                if root == 1 and (
                    facet.slug == "langue"
                    or (facet.slug in {"saison", "episode"} and not tree.series(selected))
                ):
                    continue
                self.options[facet.slug] = MultiFilter(facet.label, facet.choices)
            for i, control in enumerate([*self.video.values(), *self.options.values()]):
                self.grid.addWidget(control, i // 6, i % 6)
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
            ("resolution", self.tr("Resolution"), "2160p,1080p,720p,SD"),
            ("source", self.tr("Source"), "BluRay,Remux,BDMV,WEB-DL,WEBRip,DVDRip,HDTV,SDTV"),
            ("codec", self.tr("Codec"), "H.265,H.264,H.263,H.262,AV1"),
            ("hdr", self.tr("HDR"), "SDR,HDR10,HDR10+,DV,DV.HDR10,DV.HDR10+"),
            ("audioType", self.tr("Audio"), "lossless,lossy"),
            ("channels", self.tr("Channels"), "7.1,5.1,2.0,1.0"),
            ("lang", self.tr("Language"), "MULTI,VFF,TRUEFRENCH,VOSTFR,VFQ,VF,MULTI.VF2,VF2"),
        ]
        for key, label, values in definitions:
            self.video[key] = MultiFilter(
                label, tuple((value, value) for value in values.split(","))
            )
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
        self.sort.setCurrentIndex(0)
        self.order.setCurrentIndex(0)
        for control in [*self.video.values(), *self.options.values()]:
            control.clear()
        self.category.select_category(None)

    def params(self, text: str) -> dict[str, str]:
        if not self.ready or self.tree is None:
            raise ValueError(self.tr("Wait for the search filters to load."))
        if self.year.text() and not self.year.hasAcceptableInput():
            raise ValueError(self.tr("Enter a year between 1900 and 2100."))
        params = {"sortBy": self.sort.currentData(), "sortOrder": self.order.currentData()}
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
        for key, control in self.video.items():
            if control.selected():
                params[key] = ",".join(control.selected())
        options = [value for control in self.options.values() for value in control.selected()]
        if options:
            params["options"] = ",".join(options)
        return params
