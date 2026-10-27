"""The RSS subscription editor: plain sections, units and local time instead of raw fields."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTextEdit,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from torrentlinker.downloads import IndexerCategory
from torrentlinker.feed_units import (
    INTERVALS,
    NIGHT_HOURS,
    SizeUnit,
    bytes_to_size,
    hours_preset,
    local_offset_minutes,
    local_to_utc_hours,
    size_to_bytes,
    utc_to_local_hours,
)
from torrentlinker.feeds import Preferences, Subscription, candidate, evaluate
from torrentlinker.gui.controls import set_role
from torrentlinker.gui.feed_criteria import CriteriaEditor, PriorityList, retheme
from torrentlinker.gui.tasks import run_in_background


def heading(text: str) -> QLabel:
    label = QLabel(text)
    font = label.font()
    font.setPointSizeF(font.pointSizeF() * 1.15)
    font.setBold(True)
    label.setFont(font)
    return label


def muted(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setProperty("role", "muted")
    return label


class Disclosure(QWidget):
    """A titled section that opens and closes."""

    def __init__(self, title: str, content: QWidget, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.toggle = QToolButton()
        self.toggle.setText(title)
        self.toggle.setCheckable(True)
        self.toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        set_role(self.toggle, "quiet")
        layout.addWidget(self.toggle, 0, Qt.AlignmentFlag.AlignLeft)
        self.content = content
        content.setVisible(False)
        layout.addWidget(content)
        self.toggle.toggled.connect(self.set_open)

    def set_open(self, opened: bool) -> None:
        self.toggle.setChecked(opened)
        self.toggle.setArrowType(Qt.ArrowType.DownArrow if opened else Qt.ArrowType.RightArrow)
        self.content.setVisible(opened)


class SizeField(QWidget):
    """A size as a number with a MiB or GiB unit. Untouched, it keeps its exact stored bytes."""

    changed = Signal()

    def __init__(self, size: int | None, *, unlimited: bool = False, parent=None):
        super().__init__(parent)
        self.unlimited = unlimited
        self.bytes_value = size
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.number = QDoubleSpinBox()
        self.number.setDecimals(1)
        self.number.setRange(0, 1_000_000)
        self.number.setSingleStep(0.5)
        if unlimited:
            self.number.setSpecialValueText(self.tr("No limit"))
        self.unit = QComboBox()
        self.unit.addItems(["MiB", "GiB"])
        layout.addWidget(self.number, 1)
        layout.addWidget(self.unit)
        value, unit = bytes_to_size(size or 0)
        self.number.setValue(value)
        self.unit.setCurrentText(unit if size else "GiB")
        self.number.valueChanged.connect(self.edited)
        self.unit.currentIndexChanged.connect(self.edited)

    def edited(self) -> None:
        number = self.number.value()
        unit: SizeUnit = "GiB" if self.unit.currentText() == "GiB" else "MiB"
        self.bytes_value = None if self.unlimited and number == 0 else size_to_bytes(number, unit)
        self.changed.emit()

    def value(self) -> int | None:
        return self.bytes_value


class HoursField(QWidget):
    """Allowed hours in local time, stored as UTC. Untouched, it keeps the stored UTC hours."""

    def __init__(self, utc_hours: list[int], parent=None):
        super().__init__(parent)
        self.offset = local_offset_minutes()
        self.utc = list(utc_hours)
        local = utc_to_local_hours(utc_hours, self.offset)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.preset = QComboBox()
        self.preset.addItem(self.tr("Any time"), "any")
        self.preset.addItem(self.tr("Night only (1:00–7:00)"), "night")
        self.preset.addItem(self.tr("Custom hours"), "custom")
        layout.addWidget(self.preset)
        self.grid_box = QWidget()
        grid = QGridLayout(self.grid_box)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(2)
        self.cells: list[QToolButton] = []
        for hour in range(24):
            cell = QToolButton()
            cell.setText(str(hour))
            cell.setCheckable(True)
            cell.setChecked(hour in local)
            cell.setAccessibleName(self.tr("Hour %1").replace("%1", str(hour)))
            cell.toggled.connect(self.cell_toggled)
            grid.addWidget(cell, hour // 12, hour % 12)
            self.cells.append(cell)
        layout.addWidget(self.grid_box)
        layout.addWidget(muted(self.tr("Local time. Downloads start only in the hours you tick.")))
        self.preset.setCurrentIndex(self.preset.findData(hours_preset(local)))
        self.grid_box.setVisible(self.preset.currentData() == "custom")
        self.preset.currentIndexChanged.connect(self.preset_changed)

    def preset_changed(self) -> None:
        kind = self.preset.currentData()
        self.grid_box.setVisible(kind == "custom")
        if kind != "custom":
            wanted = set(range(24)) if kind == "any" else set(NIGHT_HOURS)
            for hour, cell in enumerate(self.cells):
                cell.blockSignals(True)
                cell.setChecked(hour in wanted)
                cell.blockSignals(False)
            self.edited()

    def cell_toggled(self) -> None:
        self.edited()

    def edited(self) -> None:
        local = [h for h, cell in enumerate(self.cells) if cell.isChecked()]
        self.utc = local_to_utc_hours(local, self.offset)

    def value(self) -> list[int]:
        return self.utc


class CategoryChecklist(QToolButton):
    """Pick any number of indexer categories by name. Unknown stored IDs are kept."""

    changed = Signal()

    def __init__(self, categories: Mapping[int, IndexerCategory], selected: list[int]):
        super().__init__()
        self.categories = dict(categories)
        self.selected = list(selected)
        self.setArrowType(Qt.ArrowType.DownArrow)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAccessibleName(self.tr("Categories"))
        self.popup = QFrame(self, Qt.WindowType.Popup)
        layout = QVBoxLayout(self.popup)
        layout.setContentsMargins(4, 4, 4, 4)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setMinimumSize(340, 300)
        layout.addWidget(self.tree)
        self.items: dict[int, QTreeWidgetItem] = {}
        self.build()
        self.tree.itemChanged.connect(self.item_changed)
        self.clicked.connect(self.show_popup)
        self.summarize()

    def build(self) -> None:
        cats = self.categories
        for cid in sorted(cats, key=lambda key: cats[key].name.casefold()):
            item = QTreeWidgetItem([cats[cid].name])
            item.setData(0, Qt.ItemDataRole.UserRole, cid)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                0, Qt.CheckState.Checked if cid in self.selected else Qt.CheckState.Unchecked
            )
            self.items[cid] = item
        for cid, item in self.items.items():
            parent = cats[cid].parent
            if parent in self.items and parent != cid:
                self.items[parent].addChild(item)
            else:
                self.tree.addTopLevelItem(item)

    def item_changed(self, item: QTreeWidgetItem) -> None:
        cid = item.data(0, Qt.ItemDataRole.UserRole)
        checked = item.checkState(0) == Qt.CheckState.Checked
        if checked and cid not in self.selected:
            self.selected.append(cid)
        if not checked and cid in self.selected:
            self.selected.remove(cid)
        self.summarize()
        self.changed.emit()

    def label_for(self, cid: int) -> str:
        known = self.categories.get(cid)
        return known.name if known else f"#{cid}"

    def summarize(self) -> None:
        text = (
            ", ".join(self.label_for(c) for c in self.selected)
            if self.selected
            else self.tr("All categories")
        )
        self.setToolTip(text)
        self.setText(self.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, 380))

    def show_popup(self) -> None:
        if self.popup.isVisible():
            self.popup.hide()
            return
        self.popup.resize(max(self.width(), 440), 380)
        self.popup.move(self.mapToGlobal(self.rect().bottomLeft()))
        self.popup.show()
        self.tree.setFocus()

    def value(self) -> list[int]:
        return list(self.selected)


class ChoiceCard(QFrame):
    """A selectable card: a radio button, one line of what will happen."""

    clicked = Signal()

    def __init__(self, title: str, description: str, parent=None):
        super().__init__(parent)
        self.setObjectName("choiceCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        self.radio = QRadioButton(title)
        layout.addWidget(self.radio)
        text = muted(description)
        text.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(text)

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", selected)
        self.style().unpolish(self)
        self.style().polish(self)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.radio.click()
        super().mouseReleaseEvent(event)


class ModeCards(QWidget):
    changed = Signal(str)

    def __init__(self, mode: str, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.group = QButtonGroup(self)
        self.cards: dict[str, ChoiceCard] = {}
        for value, title, description in [
            (
                "review_only",
                self.tr("Notify me"),
                self.tr("New releases appear in the RSS inbox. Nothing is queued."),
            ),
            (
                "app_queue",
                self.tr("Add to queue"),
                self.tr(
                    "Matching releases join TorrentLinker's queue. "
                    "Nothing reaches your client until you start it."
                ),
            ),
            (
                "automatic_download",
                self.tr("Download automatically"),
                self.tr(
                    "Matching releases are sent to your client on their own, within your limits."
                ),
            ),
        ]:
            card = ChoiceCard(title, description)
            self.group.addButton(card.radio)
            card.radio.toggled.connect(lambda on, v=value: self.select(v) if on else None)
            layout.addWidget(card)
            self.cards[value] = card
        self.mode = mode if mode in self.cards else "review_only"
        self.cards[self.mode].radio.setChecked(True)
        self.paint()

    def select(self, mode: str) -> None:
        self.mode = mode
        self.paint()
        self.changed.emit(mode)

    def paint(self) -> None:
        for value, card in self.cards.items():
            card.set_selected(value == self.mode)

    def value(self) -> str:
        return self.mode


class FeedEditor(QDialog):
    """Create or edit a subscription. `definition()` builds the model from the widgets."""

    def __init__(
        self,
        control,
        feed: Subscription,
        identifier: str,
        on_saved: Callable[[], None],
        parent=None,
        *,
        live: bool = True,
    ):
        super().__init__(parent)
        self.control = control
        self.feed = feed
        self.identifier = identifier
        self.on_saved = on_saved
        self.previewed = ""
        self.previewed_at = 0.0
        self.preview_rows: list[dict] = []
        self.preview_token = 0
        self.live = live
        self.setWindowTitle(self.tr("RSS subscription"))
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        pane = QWidget()
        self.body = QVBoxLayout(pane)
        self.body.setSpacing(10)
        self.body.setContentsMargins(0, 0, 12, 0)
        self.build_follow()
        self.build_accept()
        self.build_action()
        self.build_schedule()
        self.build_advanced()
        self.body.addStretch(1)
        scroll.setWidget(pane)
        outer.addWidget(scroll, 1)
        strip = QHBoxLayout()
        texts = QVBoxLayout()
        texts.setSpacing(2)
        self.strip = QLabel()
        self.strip.setWordWrap(True)
        self.strip.setTextFormat(Qt.TextFormat.PlainText)
        texts.addWidget(self.strip)
        self.strip_titles = QLabel()
        self.strip_titles.setProperty("role", "muted")
        self.strip_titles.setTextFormat(Qt.TextFormat.PlainText)
        self.strip_titles.hide()
        texts.addWidget(self.strip_titles)
        strip.addLayout(texts, 1)
        self.recheck = set_role(QPushButton(self.tr("Check again")), "quiet")
        self.recheck.clicked.connect(lambda: self.run_preview())
        strip.addWidget(self.recheck, 0, Qt.AlignmentFlag.AlignTop)
        outer.addLayout(strip)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        for label, role, action in [
            (self.tr("Cancel"), "quiet", self.reject),
            (self.tr("Save"), "primary", self.save),
        ]:
            button = set_role(QPushButton(label), role)
            button.clicked.connect(lambda _checked=False, fn=action: fn())
            buttons.addWidget(button)
        outer.addLayout(buttons)
        self.resize(780, 780)
        self.mode_changed(self.modes.value())
        if live:
            QTimer.singleShot(200, self.run_preview)

    def section(self, title: str) -> QFormLayout:
        self.body.addWidget(heading(title))
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self.body.addLayout(form)
        return form

    def build_follow(self) -> None:
        form = self.section(self.tr("What to follow"))
        self.name = QLineEdit(self.feed.name)
        form.addRow(self.tr("Name"), self.name)
        self.query = QLineEdit(self.feed.query)
        self.query.setPlaceholderText(self.tr("Words the title must contain"))
        form.addRow(self.tr("Title contains"), self.query)
        settings = self.control.service.setup.settings
        self.categories = CategoryChecklist(settings.indexer_categories, self.feed.categories)
        form.addRow(self.tr("Categories"), self.categories)
        if not settings.indexer_categories:
            form.addRow(
                muted(self.tr("Category names appear once the indexer has been connected."))
            )

    def build_accept(self) -> None:
        form = self.section(self.tr("What you accept"))
        prefs = self.feed.preferences
        self.min_size = SizeField(prefs.min_size)
        form.addRow(self.tr("At least"), self.min_size)
        self.max_size = SizeField(prefs.max_size, unlimited=True)
        form.addRow(self.tr("At most"), self.max_size)
        self.min_seeders = QSpinBox()
        self.min_seeders.setRange(0, 1_000_000)
        self.min_seeders.setValue(prefs.min_seeders)
        form.addRow(self.tr("Minimum seeders"), self.min_seeders)
        self.criteria = CriteriaEditor(prefs)
        self.criteria.changed.connect(self.criteria_changed)
        self.body.addWidget(self.criteria)
        self.body.addWidget(Disclosure(self.tr("More criteria"), self.criteria.more))
        self.priorities = PriorityList(self.criteria)
        self.priorities.changed.connect(self.criteria_changed)
        self.body.addWidget(Disclosure(self.tr("What matters most"), self.priorities))
        self.min_size.changed.connect(self.criteria_changed)
        self.max_size.changed.connect(self.criteria_changed)
        self.min_seeders.valueChanged.connect(self.criteria_changed)

    def build_action(self) -> None:
        self.body.addWidget(heading(self.tr("What happens")))
        self.modes = ModeCards(self.feed.mode)
        self.modes.changed.connect(self.mode_changed)
        self.body.addWidget(self.modes)
        self.where = QWidget()
        form = QFormLayout(self.where)
        form.setContentsMargins(0, 0, 0, 0)
        self.client = QComboBox()
        self.folder = QComboBox()
        for profile in self.control.service.setup.settings.client_profiles:
            if profile.enabled:
                self.client.addItem(profile.name, profile.id)
        self.client.setCurrentIndex(max(0, self.client.findData(self.feed.client_id)))
        self.client.currentIndexChanged.connect(self.load_folders)
        self.load_folders()
        form.addRow(self.tr("Torrent Client"), self.client)
        form.addRow(self.tr("Download Folder"), self.folder)
        self.body.addWidget(self.where)
        self.limits = QWidget()
        limits = QFormLayout(self.limits)
        limits.setContentsMargins(0, 0, 0, 0)
        self.daily_size = SizeField(self.feed.daily_bytes)
        limits.addRow(self.tr("Per day, at most"), self.daily_size)
        self.daily_count = QSpinBox()
        self.daily_count.setRange(0, 1000)
        self.daily_count.setValue(self.feed.daily_torrents)
        limits.addRow(self.tr("Torrents per day"), self.daily_count)
        self.reserve = SizeField(self.feed.reserve_bytes)
        limits.addRow(self.tr("Keep free on disk"), self.reserve)
        self.hours = HoursField(self.feed.download_hours)
        limits.addRow(self.tr("Allowed hours"), self.hours)
        self.approval = QCheckBox(
            self.tr("I explicitly authorize automatic downloads under these limits")
        )
        limits.addRow(self.approval)
        self.body.addWidget(self.limits)

    def build_advanced(self) -> None:
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(1200)
        self.timer.timeout.connect(lambda: self.run_preview())
        self.query.textChanged.connect(self.source_changed)
        self.categories.changed.connect(self.source_changed)
        self.advanced_text = QTextEdit()
        self.advanced_text.setReadOnly(True)
        self.advanced_text.setMinimumHeight(220)
        self.advanced = Disclosure(self.tr("Advanced: full definition"), self.advanced_text)
        self.advanced.toggle.toggled.connect(lambda _on: self.update_advanced())
        self.body.addWidget(self.advanced)

    def build_schedule(self) -> None:
        content = QWidget()
        form = QFormLayout(content)
        self.interval = QComboBox()
        values = sorted({*INTERVALS, self.feed.interval_minutes})
        for minutes in values:
            self.interval.addItem(self.interval_text(minutes), minutes)
        self.interval.setCurrentIndex(self.interval.findData(self.feed.interval_minutes))
        form.addRow(self.tr("Check every"), self.interval)
        self.wait = QSpinBox()
        self.wait.setRange(0, 10080)
        self.wait.setSuffix(self.tr(" min"))
        self.wait.setValue(self.feed.wait_minutes)
        form.addRow(self.tr("Wait for better releases"), self.wait)
        self.include = QCheckBox(self.tr("Include currently available releases"))
        self.include.setChecked(self.feed.include_current)
        form.addRow(self.include)
        self.replace = QCheckBox(self.tr("Replace better matches while still pending"))
        self.replace.setChecked(self.feed.replace_pending)
        form.addRow(self.replace)
        self.body.addWidget(Disclosure(self.tr("How often"), content))

    def interval_text(self, minutes: int) -> str:
        if minutes % 60 == 0:
            return self.tr("%1 h").replace("%1", str(minutes // 60))
        return self.tr("%1 min").replace("%1", str(minutes))

    def load_folders(self) -> None:
        self.folder.clear()
        self.folder.addItem("")
        self.folder.addItems(
            sorted(
                self.control.service.for_client(self.client.currentData()).download_destinations()
            )
        )
        if self.feed.folder and self.folder.findText(self.feed.folder) < 0:
            self.folder.addItem(self.feed.folder)
        self.folder.setCurrentText(self.feed.folder)

    def mode_changed(self, mode: str) -> None:
        self.where.setVisible(mode != "review_only")
        self.limits.setVisible(mode == "automatic_download")

    def preferences(self) -> Preferences:
        return Preferences.model_validate(
            {
                **self.criteria.prefs.model_dump(),
                "min_size": self.min_size.value() or 0,
                "max_size": self.max_size.value(),
                "min_seeders": self.min_seeders.value(),
            }
        )

    def definition(self) -> Subscription:
        mode = self.modes.value()
        hours = self.hours.value()
        if mode == "automatic_download" and not hours:
            raise ValueError(self.tr("Choose at least one hour for automatic downloads."))
        return Subscription(
            **{
                **self.feed.model_dump(),
                "name": self.name.text(),
                "query": self.query.text(),
                "categories": self.categories.value(),
                "client_id": self.client.currentData(),
                "folder": self.folder.currentText(),
                "mode": mode,
                "interval_minutes": self.interval.currentData(),
                "wait_minutes": self.wait.value(),
                "include_current": self.include.isChecked(),
                "replace_pending": self.replace.isChecked(),
                "daily_bytes": self.daily_size.value() or 0,
                "daily_torrents": self.daily_count.value(),
                "reserve_bytes": self.reserve.value() or 0,
                "download_hours": hours,
                "preferences": self.preferences(),
            }
        )

    def source_changed(self) -> None:
        """The query or categories changed: ask the source again, once typing pauses."""
        if self.live:
            self.timer.start()

    def criteria_changed(self) -> None:
        self.priorities.refresh()
        self.update_strip()
        self.update_advanced()

    def run_preview(self, then=None) -> None:
        try:
            value = self.definition()
        except Exception as error:
            self.show_strip(str(error), warning=True)
            return
        self.preview_token += 1
        token = self.preview_token
        self.show_strip(self.tr("Checking the source…"))

        def done(result):
            if token != self.preview_token:
                return
            self.previewed = value.model_dump_json()
            self.previewed_at = time.time()
            self.preview_rows = result["rows"]
            self.criteria.suggest(self.preview_rows)
            self.update_strip()
            if then:
                then(value)

        def failed(error):
            if token == self.preview_token:
                self.show_strip(str(error), warning=True)

        run_in_background(lambda: self.control.feeds.preview(value), done, failed)

    def show_strip(self, text: str, titles: str = "", *, warning: bool = False) -> None:
        self.strip.setText(text)
        self.strip.setProperty("role", "warning" if warning else "")
        retheme(self.strip)
        self.strip_titles.setText(titles)
        self.strip_titles.setVisible(bool(titles))

    def update_strip(self) -> None:
        """Re-judge the rows already fetched against the current criteria; no network call."""
        if not self.preview_rows:
            return
        try:
            prefs = self.preferences()
        except Exception as error:
            self.show_strip(str(error), warning=True)
            return
        rows = [candidate(raw) for raw in self.preview_rows]
        judged = [(row, evaluate(row, prefs)) for row in rows]
        matching = sorted((j for j in judged if j[1]["eligible"]), key=lambda j: j[1]["rank"])
        unknown = sum(1 for _, e in judged if e["unknown"] and not e["excluded"])
        text = (
            self.tr("Would match now: %1 of %2 releases")
            .replace("%1", str(len(matching)))
            .replace("%2", str(len(rows)))
        )
        if unknown:
            text += " · " + self.tr("%1 can't be checked (missing details)").replace(
                "%1", str(unknown)
            )
        self.show_strip(text, "\n".join(row.title for row, _ in matching[:3]))

    def update_advanced(self) -> None:
        if not self.advanced.toggle.isChecked():
            return
        try:
            self.advanced_text.setPlainText(self.definition().model_dump_json(indent=2))
        except Exception as error:
            self.advanced_text.setPlainText(str(error))

    def needs_preview(self, value: Subscription) -> bool:
        """Mirrors FeedControl.save: a new feed or a changed source needs a fresh preview."""
        changed = value.query != self.feed.query or value.categories != self.feed.categories
        return not self.identifier or changed

    def save(self) -> None:
        try:
            value = self.definition()
            current = (
                self.previewed == value.model_dump_json() and time.time() - self.previewed_at < 840
            )
            if self.needs_preview(value) and not current:
                self.run_preview(then=self.finish_save)
                return
            self.finish_save(value)
        except Exception as error:
            self.show_strip(str(error), warning=True)

    def finish_save(self, value: Subscription) -> None:
        try:
            self.control.save(value, approved=self.approval.isChecked())
            self.accept()
            self.on_saved()
        except Exception as error:
            self.show_strip(str(error), warning=True)
