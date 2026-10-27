"""RSS inbox, rule editor and Search subscription preview."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from datetime import datetime

from PySide6.QtCore import QLocale, Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from torrentlinker.feed_units import age, format_size, when
from torrentlinker.feeds import Subscription, candidate
from torrentlinker.gui.controls import icon_button, set_role
from torrentlinker.gui.feed_editor import FeedEditor
from torrentlinker.gui.tasks import run_in_background
from torrentlinker.gui.torrent_details import TorrentDetailsDialog

FEED_NAME = Qt.ItemDataRole.UserRole + 1
FEED_UNREAD = Qt.ItemDataRole.UserRole + 2


class FeedRow(QWidget):
    """A sidebar entry: name and mode on two lines, the unread count on the right."""

    def __init__(self, name: str, detail: str, unread: int, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 5, 8, 5)
        texts = QVBoxLayout()
        texts.setSpacing(0)
        title = QLabel(name)
        title.setTextFormat(Qt.TextFormat.PlainText)
        texts.addWidget(title)
        sub = QLabel(detail)
        sub.setProperty("role", "muted")
        sub.setTextFormat(Qt.TextFormat.PlainText)
        texts.addWidget(sub)
        layout.addLayout(texts, 1)
        if unread:
            badge = QLabel(str(unread))
            font = badge.font()
            font.setBold(True)
            badge.setFont(font)
            layout.addWidget(badge)


class FeedsTab(QWidget):
    def __init__(self, control: Callable, parent=None):
        super().__init__(parent)
        self.control = control
        self.feed_id = ""
        self.feeds: list[dict] = []
        self.rows: list[dict] = []
        self.loaded = False
        layout = QVBoxLayout(self)
        split = QSplitter()
        side = QWidget()
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_head = QHBoxLayout()
        heading = QLabel(self.tr("Subscriptions"))
        heading.setProperty("role", "muted")
        side_head.addWidget(heading, 1)
        self.add_button = icon_button("＋", self.tr("New subscription"))
        self.add_button.clicked.connect(lambda: self.edit())
        side_head.addWidget(self.add_button)
        side_layout.addLayout(side_head)
        self.sidebar = QListWidget()
        self.sidebar.currentRowChanged.connect(self.choose)
        side_layout.addWidget(self.sidebar, 1)
        split.addWidget(side)
        self.stack = QStackedWidget()
        pane = QWidget()
        right = QVBoxLayout(pane)
        right.setContentsMargins(0, 0, 0, 0)
        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        self.title = QLabel()
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        font = self.title.font()
        font.setPointSizeF(font.pointSizeF() * 1.35)
        font.setBold(True)
        self.title.setFont(font)
        titles.addWidget(self.title)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setProperty("role", "muted")
        titles.addWidget(self.status)
        head.addLayout(titles, 1)
        self.coverage = icon_button("ⓘ", self.tr("Limited discovery"))
        self.coverage.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        head.addWidget(self.coverage, 0, Qt.AlignmentFlag.AlignTop)
        self.main_action = set_role(QPushButton(), "primary")
        self.main_action.clicked.connect(lambda: self.main_clicked())
        head.addWidget(self.main_action, 0, Qt.AlignmentFlag.AlignTop)
        self.more_menu = QMenu(self)
        self.more_button = icon_button("⋯", self.tr("More"))
        self.more_button.setMenu(self.more_menu)
        self.more_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        head.addWidget(self.more_button, 0, Qt.AlignmentFlag.AlignTop)
        right.addLayout(head)
        filters = QHBoxLayout()
        self.filter_group = QButtonGroup(self)
        self.filter_group.setExclusive(True)
        for index, text in enumerate(
            [
                self.tr("All"),
                self.tr("Unread"),
                self.tr("Saved"),
                self.tr("In client"),
                self.tr("Queued"),
            ]
        ):
            button = QPushButton(text)
            button.setCheckable(True)
            set_role(button, "tab")
            self.filter_group.addButton(button, index)
            filters.addWidget(button)
        self.filter_group.button(0).setChecked(True)
        self.filter_group.idClicked.connect(lambda _index: self.load_rows())
        filters.addStretch(1)
        right.addLayout(filters)
        self.selection_bar = QWidget()
        actions = QHBoxLayout(self.selection_bar)
        actions.setContentsMargins(0, 0, 0, 0)
        self.selection_count = QLabel()
        self.selection_count.setProperty("role", "muted")
        actions.addWidget(self.selection_count)
        actions.addStretch(1)
        for text, action, role in [
            (self.tr("Mark read"), lambda: self.mark("read"), "quiet"),
            (self.tr("Save"), lambda: self.mark("save"), "quiet"),
            (self.tr("Dismiss"), lambda: self.mark("dismiss"), "quiet"),
            (self.tr("Save selection"), self.select, "secondary"),
            (self.tr("Add to queue"), self.enqueue, "primary"),
        ]:
            action_button = set_role(QPushButton(text), role)
            action_button.clicked.connect(lambda _checked=False, fn=action: fn())
            actions.addWidget(action_button)
        self.selection_bar.hide()
        right.addWidget(self.selection_bar)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            [
                self.tr("Title"),
                self.tr("Size"),
                self.tr("Seeds"),
                self.tr("Discovered"),
                self.tr("Published"),
                self.tr("State"),
            ]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.cellDoubleClicked.connect(self.details)
        self.table.itemSelectionChanged.connect(self.selection_changed)
        right.addWidget(self.table, 1)
        self.stack.addWidget(pane)
        empty = QWidget()
        empty_layout = QVBoxLayout(empty)
        empty_layout.addStretch(1)
        sentence = QLabel(
            self.tr("Follow a search to see new releases here, or let rules queue them for you.")
        )
        sentence.setWordWrap(True)
        sentence.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sentence.setProperty("role", "muted")
        empty_layout.addWidget(sentence)
        create = set_role(QPushButton(self.tr("New subscription")), "primary")
        create.clicked.connect(lambda: self.edit())
        empty_layout.addWidget(create, 0, Qt.AlignmentFlag.AlignCenter)
        empty_layout.addStretch(1)
        self.stack.addWidget(empty)
        split.addWidget(self.stack)
        split.setStretchFactor(1, 1)
        split.setSizes([240, 800])
        layout.addWidget(split)
        self.timer = QTimer(self)
        self.timer.setInterval(30_000)
        self.timer.timeout.connect(lambda: self.reload() if self.isVisible() else None)
        self.timer.start()

    def showEvent(self, event):
        super().showEvent(event)
        if not self.loaded:
            self.loaded = True
            self.reload()

    def error(self, error):
        self.status.setText(str(error))

    def work(self, fn, done=None):
        run_in_background(fn, done or (lambda _: self.reload()), self.error)

    def mode_text(self, mode):
        return {
            "review_only": self.tr("Notify me"),
            "app_queue": self.tr("Add to queue"),
            "automatic_download": self.tr("Download automatically"),
        }.get(mode, mode)

    def current_feed(self):
        return next((f for f in self.feeds if f["id"] == self.feed_id), None)

    def filter_index(self):
        return self.filter_group.checkedId()

    def set_filter(self, index):
        self.filter_group.button(index).setChecked(True)
        self.load_rows()

    def reload(self):
        try:
            control = self.control()
            self.feeds = control.feeds.subscriptions()
            self.sidebar.blockSignals(True)
            self.sidebar.clear()
            self.add_sidebar_row(
                self.tr("All feeds"), "", sum(f["unread_count"] for f in self.feeds), ""
            )
            current = 0
            for i, feed in enumerate(self.feeds, 1):
                detail = self.mode_text(feed["mode"])
                if feed["paused"]:
                    detail = f"{self.tr('Paused')} · {detail}"
                self.add_sidebar_row(feed["name"], detail, feed["unread_count"], feed["id"])
                if feed["id"] == self.feed_id:
                    current = i
            self.sidebar.setCurrentRow(current)
            self.sidebar.blockSignals(False)
            self.stack.setCurrentIndex(0 if self.feeds else 1)
            self.choose(current)
        except Exception as error:
            self.error(error)

    def add_sidebar_row(self, name, detail, unread, identifier):
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, identifier)
        item.setData(FEED_NAME, name)
        item.setData(FEED_UNREAD, unread)
        row = FeedRow(name, detail, unread)
        item.setSizeHint(row.sizeHint())
        self.sidebar.addItem(item)
        self.sidebar.setItemWidget(item, row)

    def choose(self, index):
        item = self.sidebar.item(index)
        self.feed_id = item.data(Qt.ItemDataRole.UserRole) or "" if item else ""
        self.refresh_header()
        self.load_rows()

    def main_clicked(self):
        if self.feed_id:
            self.refresh()
        else:
            self.edit()

    def refresh_header(self):
        feed = self.current_feed()
        self.title.setText(feed["name"] if feed else self.tr("All feeds"))
        self.main_action.setText(self.tr("Refresh now") if feed else self.tr("New subscription"))
        self.coverage.setToolTip(
            (feed and feed["coverage"])
            or self.tr("Limited RSS discovery. History and gap-free updates are not guaranteed.")
        )
        if feed and feed["error"]:
            text = feed["error"]
        elif feed and feed["last_success"]:
            count, unit = age(time.time() - feed["last_success"])
            text = self.age_text(count, unit)
        elif feed:
            text = self.tr("Waiting for the first update")
        else:
            text = self.tr("Subscriptions: %1").replace("%1", str(len(self.feeds)))
        if feed and feed["paused"] and not feed["error"]:
            text = f"{self.tr('Paused')} · {text}"
        self.status.setText(text)
        self.more_menu.clear()
        if feed:
            self.more_menu.addAction(self.tr("Edit…"), lambda: self.edit(self.feed_id))
            self.more_menu.addAction(
                self.tr("Resume") if feed["paused"] else self.tr("Pause"), self.pause
            )
            self.more_menu.addAction(self.tr("Process rules"), self.process)
            self.more_menu.addAction(self.tr("Decisions"), self.decisions)
            self.more_menu.addAction(self.tr("Delete…"), self.confirm_delete)
        else:
            self.more_menu.addAction(self.tr("Refresh all"), self.refresh)
        self.more_menu.addSeparator()
        self.more_menu.addAction(self.tr("Compare clients…"), self.compare)
        self.more_menu.addAction(self.tr("Saved selections"), self.saved_selections)

    def age_text(self, count, unit):
        text = {
            "minute": self.tr("Updated %1 min ago"),
            "hour": self.tr("Updated %1 h ago"),
            "day": self.tr("Updated %1 d ago"),
        }[unit]
        return text.replace("%1", str(count))

    def when_text(self, timestamp):
        if not timestamp:
            return "—"
        kind, moment = when(timestamp)
        clock = QLocale().toString(moment.time(), QLocale.FormatType.ShortFormat)
        if kind == "today":
            return self.tr("Today %1").replace("%1", clock)
        if kind == "yesterday":
            return self.tr("Yesterday %1").replace("%1", clock)
        pattern = "d MMM" if moment.year == datetime.now().year else "d MMM yyyy"
        return QLocale().toString(moment.date(), pattern)

    def confirm_delete(self):
        feed = self.current_feed()
        if feed and (
            QMessageBox.question(
                self,
                self.tr("Delete subscription"),
                self.tr("Delete “%1”? Its releases leave the inbox.").replace("%1", feed["name"]),
            )
            == QMessageBox.StandardButton.Yes
        ):
            self.delete()

    def selection_changed(self):
        count = len(self.table.selectionModel().selectedRows())
        self.selection_bar.setVisible(count > 0)
        self.selection_count.setText(self.tr("%1 selected").replace("%1", str(count)))

    def load_rows(self):
        try:
            control = self.control()
            mode = self.filter_index()
            rows = control.inbox(feed_id=self.feed_id, unread=mode == 1, saved=mode == 2)
            if mode == 3:
                rows = [r for r in rows if r["in_clients"]]
            if mode == 4:
                rows = [r for r in rows if r["queued"]]
            self.rows = rows
            self.table.setRowCount(len(rows))
            for i, row in enumerate(rows):
                values = [
                    ("● " if row["unread"] else "") + row["title"],
                    format_size(row["size"]),
                    str(row["seeders"]),
                    self.when_text(row["discovered_at"]),
                    self.when_text(row["published_at"]),
                    row["queue_status"] or ", ".join(row["in_clients"]),
                ]
                for j, value in enumerate(values):
                    self.table.setItem(i, j, QTableWidgetItem(value))
            self.table.resizeColumnsToContents()
            self.table.horizontalHeader().setSectionResizeMode(
                0, QHeaderView.ResizeMode.Interactive
            )
            self.table.setColumnWidth(0, max(self.table.columnWidth(0), 360))
            self.selection_changed()
        except Exception as error:
            self.error(error)

    def hashes(self):
        return [self.rows[i.row()]["infohash"] for i in self.table.selectionModel().selectedRows()]

    def refresh(self):
        identifiers = (
            [self.feed_id]
            if self.feed_id
            else [r["id"] for r in self.control().feeds.subscriptions()]
        )
        self.work(lambda: [self.control().feeds.refresh(identifier) for identifier in identifiers])

    def pause(self):
        if self.feed_id:
            control = self.control()
            feed = control.feeds.get(self.feed_id)
            # Pausing cannot enable automatic downloads or change their approved rule.
            control.set_paused(feed.id, not feed.paused)
            self.reload()

    def compare(self):
        dialog = QDialog(self)
        layout = QVBoxLayout(dialog)
        clients = QListWidget()
        for profile in self.control().service.setup.settings.client_profiles:
            if profile.enabled:
                clients.addItem(profile.name)
                item = clients.item(clients.count() - 1)
                item.setData(Qt.ItemDataRole.UserRole, profile.id)
                item.setCheckState(Qt.CheckState.Checked)
        layout.addWidget(clients)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec():
            selected = [
                clients.item(i).data(Qt.ItemDataRole.UserRole)
                for i in range(clients.count())
                if clients.item(i).checkState() == Qt.CheckState.Checked
            ]
            if selected:
                self.work(
                    lambda: self.control().inventory(refresh=True, client_ids=selected), self.report
                )

    def process(self):
        if self.feed_id:
            self.work(lambda: self.control().process(self.feed_id), self.report)

    def delete(self):
        if self.feed_id:
            self.control().delete(self.feed_id)
            self.feed_id = ""
            self.reload()

    def mark(self, action):
        self.control().feeds.mark(self.hashes(), feed_id=self.feed_id, action=action)
        self.reload()

    def select(self):
        self.report(self.control().feeds.select(self.hashes()))

    def report(self, value):
        dialog = QDialog(self)
        dialog.setWindowTitle(self.tr("RSS review"))
        layout = QVBoxLayout(dialog)
        text = QTextEdit()
        text.setReadOnly(True)
        text.setPlainText(json.dumps(value, indent=2, ensure_ascii=False))
        layout.addWidget(text)
        if isinstance(value, dict) and value.get("id") and "hashes" in value:
            queue = QPushButton(self.tr("Queue selected"))
            set_role(queue, "primary")
            queue.clicked.connect(lambda: self.enqueue(value["id"]))
            layout.addWidget(queue)
        dialog.resize(800, 600)
        dialog.exec()

    def decisions(self):
        self.report(self.control().decisions(self.feed_id))

    def saved_selections(self):
        dialog = QDialog(self)
        dialog.setWindowTitle(self.tr("Saved selections"))
        layout = QVBoxLayout(dialog)
        selections = QListWidget()
        for saved in self.control().feeds.selections():
            selections.addItem(f"{saved['name']} · {len(saved['hashes'])}")
            selections.item(selections.count() - 1).setData(Qt.ItemDataRole.UserRole, saved["id"])
        selections.itemDoubleClicked.connect(
            lambda item: self.report(
                self.control().feeds.selection(item.data(Qt.ItemDataRole.UserRole))
            )
        )
        layout.addWidget(selections)
        dialog.resize(500, 450)
        dialog.exec()

    def enqueue(self, selection_id=""):
        control = self.control()
        hashes = self.hashes()
        if not hashes and not selection_id:
            return
        saved = (
            control.feeds.selection(selection_id) if selection_id else control.feeds.select(hashes)
        )
        dialog = QDialog(self)
        layout = QFormLayout(dialog)
        client = QComboBox()
        folder = QComboBox()
        for profile in control.service.setup.settings.client_profiles:
            if profile.enabled:
                client.addItem(profile.name, profile.id)

        def folders():
            folder.clear()
            folder.addItems(
                sorted(control.service.for_client(client.currentData()).download_destinations())
            )

        client.currentIndexChanged.connect(folders)
        folders()
        layout.addRow(self.tr("Torrent Client"), client)
        layout.addRow(self.tr("Download Folder"), folder)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)
        if dialog.exec() and folder.currentText():
            self.work(
                lambda: control.feeds.enqueue_selection(
                    saved["id"],
                    control.service.setup.store,
                    client.currentData(),
                    folder.currentText(),
                )
            )

    def details(self, row, column=0):
        value = candidate(self.rows[row])
        dialog = TorrentDetailsDialog(value, self.control().feeds.indexer(), "—", "", self)
        dialog.exec()

    def edit(self, identifier="", query=""):
        control = self.control()
        feed = (
            control.feeds.get(identifier)
            if identifier
            else Subscription(
                name="RSS", query=query, client_id=control.service.setup.settings.active_client_id
            )
        )
        FeedEditor(control, feed, identifier, self.reload, self).exec()
