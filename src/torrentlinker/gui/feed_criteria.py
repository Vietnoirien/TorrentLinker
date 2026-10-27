"""Release criteria as chips (Must / Prefer / Avoid) and a short ranking list."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from torrentlinker.feed_units import (
    NEXT_CHIP,
    STARTER_VALUES,
    chip_state,
    chip_values,
    move_preferred,
    move_priority,
    seen_values,
    set_chip,
)
from torrentlinker.feeds import MetadataField, Preferences
from torrentlinker.gui.controls import icon_button, set_role
from torrentlinker.gui.flow_layout import FlowLayout

COMMON: tuple[MetadataField, ...] = ("quality", "codec", "audio", "subtitles")
MORE: tuple[MetadataField, ...] = ("format", "bitrate", "platform", "license")


def retheme(widget: QWidget) -> None:
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)


class ChipRow(QWidget):
    """The values of one metadata field. A click cycles: not set, prefer, must, avoid."""

    clicked = Signal(str)
    menuRequested = Signal(str, object)

    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.label = QLabel(label)
        self.label.setMinimumWidth(110)
        self.label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        outer.addWidget(self.label)
        holder = QWidget()
        self.flow = FlowLayout(holder)
        outer.addWidget(holder, 1)
        self.chips: dict[str, QPushButton] = {}
        self.add = QLineEdit()
        self.add.setPlaceholderText(self.tr("Add…"))
        self.add.setMaximumWidth(90)
        self.add.returnPressed.connect(self.add_typed)
        self.flow.addWidget(self.add)
        self.added: list[str] = []

    def add_typed(self) -> None:
        text = self.add.text().strip()
        self.add.clear()
        if text:
            self.clicked.emit(text)

    def chip(self, value: str) -> QPushButton:
        if value not in self.chips:
            button = QPushButton(value)
            button.clicked.connect(lambda _checked=False, v=value: self.clicked.emit(v))
            button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            button.customContextMenuRequested.connect(
                lambda pos, v=value, b=button: self.menuRequested.emit(v, b.mapToGlobal(pos))
            )
            self.chips[value] = button
            self.flow.removeWidget(self.add)
            self.flow.addWidget(button)
            self.flow.addWidget(self.add)
        return self.chips[value]


class CriteriaEditor(QWidget):
    """Edits `required`, `preferred` and `excluded` for every metadata field."""

    changed = Signal()

    def __init__(self, prefs: Preferences, parent=None):
        super().__init__(parent)
        self.prefs = prefs
        self.suggestions: dict[str, list[str]] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.rows: dict[MetadataField, ChipRow] = {}
        titles = {
            "quality": self.tr("Quality"),
            "codec": self.tr("Codec"),
            "audio": self.tr("Audio"),
            "subtitles": self.tr("Subtitles"),
            "format": self.tr("Format"),
            "bitrate": self.tr("Bitrate"),
            "platform": self.tr("Platform"),
            "license": self.tr("License"),
        }
        hint = QLabel(
            self.tr(
                "Click a value to prefer it, again to require it, again to avoid it. "
                "Right-click a preferred value to rank it."
            )
        )
        hint.setWordWrap(True)
        hint.setProperty("role", "muted")
        layout.addWidget(hint)
        self.more = QWidget()
        more_layout = QVBoxLayout(self.more)
        more_layout.setContentsMargins(0, 0, 0, 0)
        for field in (*COMMON, *MORE):
            row = ChipRow(titles[field])
            row.clicked.connect(lambda value, f=field: self.cycle(f, value))
            row.menuRequested.connect(lambda value, pos, f=field: self.rank_menu(f, value, pos))
            self.rows[field] = row
            (layout if field in COMMON else more_layout).addWidget(row)
        self.refresh()

    def values_for(self, field: MetadataField) -> list[str]:
        shown = list(self.rows[field].chips)
        for value in [
            *chip_values(self.prefs, field),
            *STARTER_VALUES[field],
            *self.suggestions.get(field, []),
        ]:
            if value not in shown and value.casefold() not in {s.casefold() for s in shown}:
                shown.append(value)
        return shown

    def refresh(self) -> None:
        for field, row in self.rows.items():
            for value in self.values_for(field):
                button = row.chip(value)
                state = chip_state(self.prefs, field, value)
                rank = (
                    self.prefs.preferred[field].index(value) + 1
                    if state == "prefer" and value in self.prefs.preferred.get(field, [])
                    else 0
                )
                prefix = {"must": "✓ ", "avoid": "✕ "}.get(state, "") + (
                    f"{rank}. " if rank else ""
                )
                button.setText(prefix + value)
                button.setProperty("chip", state)
                button.setAccessibleName(f"{value}, {self.state_words(state)}")
                button.setToolTip(self.state_words(state))
                retheme(button)

    def state_words(self, state: str) -> str:
        return {
            "none": self.tr("Not set"),
            "prefer": self.tr("Preferred"),
            "must": self.tr("Required"),
            "avoid": self.tr("Avoided"),
        }[state]

    def cycle(self, field: MetadataField, value: str) -> None:
        known = next((v for v in self.values_for(field) if v.casefold() == value.casefold()), value)
        state = chip_state(self.prefs, field, known)
        self.prefs = set_chip(self.prefs, field, known, NEXT_CHIP[state])
        self.refresh()
        self.changed.emit()

    def rank_menu(self, field: MetadataField, value: str, position) -> None:
        if value not in self.prefs.preferred.get(field, []):
            return
        menu = QMenu(self)
        menu.addAction(self.tr("Rank higher"), lambda: self.rank(field, value, -1))
        menu.addAction(self.tr("Rank lower"), lambda: self.rank(field, value, 1))
        menu.exec(position)

    def rank(self, field: MetadataField, value: str, step: int) -> None:
        self.prefs = move_preferred(self.prefs, field, value, step)
        self.refresh()
        self.changed.emit()

    def suggest(self, rows: list[dict]) -> None:
        """Offer the values the source really uses, taken from a preview."""
        self.suggestions = {field: seen_values(rows, field) for field in self.rows}
        self.refresh()

    def replace(self, prefs: Preferences) -> None:
        self.prefs = prefs
        self.refresh()


class PriorityList(QWidget):
    """What matters most, in order. Moving a row changes which preference wins first."""

    changed = Signal()

    def __init__(self, editor: CriteriaEditor, parent=None):
        super().__init__(parent)
        self.editor = editor
        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(0, 0, 0, 0)
        self.names: dict[str, str] = {
            "quality": self.tr("Quality"),
            "codec": self.tr("Codec"),
            "audio": self.tr("Audio"),
            "subtitles": self.tr("Subtitles"),
            "format": self.tr("Format"),
            "bitrate": self.tr("Bitrate"),
            "platform": self.tr("Platform"),
            "license": self.tr("License"),
            "size": self.tr("Smaller size"),
            "seeders": self.tr("More seeders"),
        }
        self.rows_widget: QWidget | None = None
        adder = QHBoxLayout()
        self.missing = QComboBox()
        adder.addWidget(self.missing, 1)
        self.add_button = set_role(QPushButton(self.tr("Add to ranking")), "secondary")
        self.add_button.clicked.connect(self.add_priority)
        adder.addWidget(self.add_button)
        adder.addStretch(1)
        self.layout_.addLayout(adder)
        self.prefer_small = QCheckBox(self.tr("Prefer smaller releases"))
        self.prefer_small.setChecked(editor.prefs.prefer_small)
        self.prefer_small.toggled.connect(self.small_toggled)
        self.layout_.addWidget(self.prefer_small)
        self.refresh()

    def small_toggled(self, on: bool) -> None:
        prefs = self.editor.prefs
        self.editor.replace(Preferences.model_validate({**prefs.model_dump(), "prefer_small": on}))
        self.refresh()
        self.changed.emit()

    def refresh(self) -> None:
        prefs = self.editor.prefs
        if self.rows_widget is not None:
            self.rows_widget.deleteLater()
        self.rows_widget = QWidget()
        self.rows_box = QVBoxLayout(self.rows_widget)
        self.rows_box.setContentsMargins(0, 0, 0, 0)
        self.layout_.insertWidget(0, self.rows_widget)
        for index, key in enumerate(prefs.priorities):
            row = QHBoxLayout()
            text = f"{index + 1}. {self.names.get(key, key)}"
            if key == "size" and not prefs.prefer_small:
                text += " — " + self.tr("only when “Prefer smaller releases” is on")
            row.addWidget(QLabel(text), 1)
            up = icon_button("▲", self.tr("Move up"))
            up.setEnabled(index > 0)
            up.clicked.connect(lambda _c=False, k=key: self.shift(k, -1))
            down = icon_button("▼", self.tr("Move down"))
            down.setEnabled(index < len(prefs.priorities) - 1)
            down.clicked.connect(lambda _c=False, k=key: self.shift(k, 1))
            row.addWidget(up)
            row.addWidget(down)
            drop = icon_button("✕", self.tr("Remove from ranking"))
            drop.setEnabled(key not in prefs.preferred)
            drop.clicked.connect(lambda _c=False, k=key: self.remove(k))
            row.addWidget(drop)
            self.rows_box.addLayout(row)
        self.missing.clear()
        for option, name in self.names.items():
            if option not in prefs.priorities:
                self.missing.addItem(name, option)
        self.missing.setVisible(self.missing.count() > 0)
        self.add_button.setVisible(self.missing.count() > 0)

    def apply(self, order: list[str]) -> None:
        prefs = self.editor.prefs
        self.editor.replace(Preferences.model_validate({**prefs.model_dump(), "priorities": order}))
        self.refresh()
        self.changed.emit()

    def shift(self, key: str, step: int) -> None:
        self.editor.replace(move_priority(self.editor.prefs, key, step))
        self.refresh()
        self.changed.emit()

    def remove(self, key: str) -> None:
        self.apply([k for k in self.editor.prefs.priorities if k != key])

    def add_priority(self) -> None:
        key = self.missing.currentData()
        if key:
            self.apply([*self.editor.prefs.priorities, key])
