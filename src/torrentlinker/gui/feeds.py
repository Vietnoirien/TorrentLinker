"""RSS inbox, rule editor and Search subscription preview."""

from __future__ import annotations

import json
from collections.abc import Callable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from torrentlinker.feeds import Preferences, Subscription, candidate
from torrentlinker.gui.controls import set_role
from torrentlinker.gui.tasks import run_in_background
from torrentlinker.gui.torrent_details import TorrentDetailsDialog


class FeedsTab(QWidget):
    def __init__(self, control: Callable, parent=None):
        super().__init__(parent)
        self.control = control
        self.feed_id = ""
        self.rows: list[dict] = []
        self.loaded = False
        layout = QVBoxLayout(self)
        bar = QHBoxLayout()
        for text, action in [
            (self.tr("New subscription"), self.edit),
            (self.tr("Edit"), lambda: self.edit(self.feed_id)),
            (self.tr("Refresh"), self.refresh),
            (self.tr("Pause / resume"), self.pause),
            (self.tr("Compare clients"), self.compare),
            (self.tr("Saved selections"), self.saved_selections),
            (self.tr("Process rules"), self.process),
            (self.tr("Delete"), self.delete),
        ]:
            button = QPushButton(text)
            button.clicked.connect(lambda _checked=False, fn=action: fn())
            bar.addWidget(button)
        layout.addLayout(bar)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        split = QSplitter()
        self.sidebar = QListWidget()
        self.sidebar.currentRowChanged.connect(self.choose)
        split.addWidget(self.sidebar)
        pane = QWidget()
        right = QVBoxLayout(pane)
        self.filter = QComboBox()
        self.filter.addItems(
            [
                self.tr("All"),
                self.tr("Unread"),
                self.tr("Saved"),
                self.tr("In client"),
                self.tr("Queued"),
            ]
        )
        self.filter.currentIndexChanged.connect(self.load_rows)
        right.addWidget(self.filter)
        actions = QHBoxLayout()
        for text, action in [
            (self.tr("Mark read"), lambda: self.mark("read")),
            (self.tr("Save"), lambda: self.mark("save")),
            (self.tr("Dismiss"), lambda: self.mark("dismiss")),
            (self.tr("Save selection"), self.select),
            (self.tr("Queue selected"), self.enqueue),
            (self.tr("Decisions"), self.decisions),
        ]:
            button = QPushButton(text)
            button.clicked.connect(lambda _checked=False, fn=action: fn())
            actions.addWidget(button)
        right.addLayout(actions)
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
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.cellDoubleClicked.connect(self.details)
        right.addWidget(self.table)
        split.addWidget(pane)
        split.setSizes([180, 850])
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

    def reload(self):
        try:
            control = self.control()
            feeds = control.feeds.subscriptions()
            self.sidebar.blockSignals(True)
            self.sidebar.clear()
            self.sidebar.addItem(self.tr("All feeds"))
            current = 0
            for i, feed in enumerate(feeds, 1):
                self.sidebar.addItem(f"{feed['name']} ({feed['unread_count']})")
                self.sidebar.item(i).setData(Qt.ItemDataRole.UserRole, feed["id"])
                if feed["id"] == self.feed_id:
                    current = i
            self.sidebar.setCurrentRow(current)
            self.sidebar.blockSignals(False)
            self.load_rows()
        except Exception as error:
            self.error(error)

    def choose(self, index):
        item = self.sidebar.item(index)
        self.feed_id = item.data(Qt.ItemDataRole.UserRole) or "" if item else ""
        self.load_rows()

    def load_rows(self):
        from datetime import datetime

        try:
            control = self.control()
            mode = self.filter.currentIndex()
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
                    f"{row['size'] / 1024**3:.2f} GiB",
                    str(row["seeders"]),
                    datetime.fromtimestamp(row["discovered_at"]).isoformat(timespec="minutes"),
                    datetime.fromtimestamp(row["published_at"]).isoformat(timespec="minutes")
                    if row["published_at"]
                    else "—",
                    row["queue_status"] or ", ".join(row["in_clients"]),
                ]
                for j, value in enumerate(values):
                    self.table.setItem(i, j, QTableWidgetItem(value))
            self.table.resizeColumnsToContents()
            feed = next((r for r in control.feeds.subscriptions() if r["id"] == self.feed_id), None)
            if feed:
                self.status.setText(
                    f"{feed['coverage']}\n{self.tr('Last success')}: "
                    f"{feed['last_success'] or '—'} {feed['error']}"
                )
            else:
                self.status.setText(
                    self.tr(
                        "Limited RSS discovery. History and gap-free updates are not guaranteed."
                    )
                )
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
        dialog = QDialog(self)
        dialog.setWindowTitle(self.tr("RSS subscription"))
        outer = QVBoxLayout(dialog)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        pane = QWidget()
        form = QFormLayout(pane)
        fields = {}

        def line(key, label, value):
            fields[key] = QLineEdit(str(value))
            form.addRow(label, fields[key])

        line("name", self.tr("Name"), feed.name)
        line("query", self.tr("Title query"), feed.query)
        line("categories", self.tr("Torznab category IDs"), ",".join(map(str, feed.categories)))
        note = QLabel(
            self.tr(
                "Film 2030, TV 5000, Music 3010, Books 7020, all 3D 8010. Native "
                "Search filters are not copied. Advanced criteria use verified "
                "metadata only."
            )
        )
        note.setWordWrap(True)
        form.addRow(note)
        client = QComboBox()
        folder = QComboBox()
        for profile in control.service.setup.settings.client_profiles:
            if profile.enabled:
                client.addItem(profile.name, profile.id)
        client.setCurrentIndex(max(0, client.findData(feed.client_id)))

        def folders():
            folder.clear()
            folder.addItem("")
            folder.addItems(
                sorted(control.service.for_client(client.currentData()).download_destinations())
            )
            folder.setCurrentText(feed.folder)

        client.currentIndexChanged.connect(folders)
        folders()
        form.addRow(self.tr("Torrent Client"), client)
        form.addRow(self.tr("Download Folder"), folder)
        mode = QComboBox()
        for label, value in [
            (self.tr("Review only"), "review_only"),
            (self.tr("App queue only"), "app_queue"),
            (self.tr("Automatic downloads"), "automatic_download"),
        ]:
            mode.addItem(label, value)
        mode.setCurrentIndex(mode.findData(feed.mode))
        form.addRow(self.tr("Mode"), mode)
        for key, label in [
            ("interval_minutes", self.tr("Poll interval, minutes")),
            ("wait_minutes", self.tr("Wait for alternatives, minutes")),
            ("daily_bytes", self.tr("Daily download bytes")),
            ("daily_torrents", self.tr("Daily download count")),
            ("reserve_bytes", self.tr("Disk reserve bytes")),
        ]:
            line(key, label, getattr(feed, key))
        line(
            "download_hours", self.tr("Allowed UTC hours"), ",".join(map(str, feed.download_hours))
        )
        include = QCheckBox(self.tr("Include currently available releases"))
        include.setChecked(feed.include_current)
        replace = QCheckBox(self.tr("Replace better matches while still pending"))
        replace.setChecked(feed.replace_pending)
        form.addRow(include)
        form.addRow(replace)
        preference_fields = {}
        for key, label, value in [
            ("min_size", self.tr("Minimum bytes"), feed.preferences.min_size),
            (
                "max_size",
                self.tr("Maximum bytes, blank for unlimited"),
                feed.preferences.max_size if feed.preferences.max_size is not None else "",
            ),
            ("min_seeders", self.tr("Minimum seeders"), feed.preferences.min_seeders),
            (
                "priorities",
                self.tr("Ranking priorities, comma separated"),
                ",".join(feed.preferences.priorities),
            ),
        ]:
            field = QLineEdit(str(value))
            preference_fields[key] = field
            form.addRow(label, field)
        prefer_small = QCheckBox(self.tr("Prefer smaller releases"))
        prefer_small.setChecked(feed.preferences.prefer_small)
        form.addRow(prefer_small)
        seeders_help = QLabel(
            self.tr(
                "Add seeders to the ranking priorities to prefer more seeders; move it "
                "before quality or codec to give availability priority."
            )
        )
        seeders_help.setWordWrap(True)
        form.addRow(seeders_help)
        for key in (
            "quality",
            "codec",
            "audio",
            "subtitles",
            "format",
            "bitrate",
            "platform",
            "license",
        ):
            for group, label in [
                ("required", self.tr("Required / accepted")),
                ("preferred", self.tr("Preferred in order")),
                ("excluded", self.tr("Excluded")),
            ]:
                field = QLineEdit(",".join(getattr(feed.preferences, group).get(key, [])))
                preference_fields[group + "-" + key] = field
                form.addRow(f"{key} · {label}", field)
        help_text = QLabel(
            self.tr(
                "required/excluded are hard constraints; preferred lists rank "
                "acceptable releases. Fields: quality, codec, audio, subtitles, "
                "format, bitrate, platform, license. priorities sets ranking order; "
                "prefer_small ranks size. Unknown required metadata blocks rules. Work "
                "identity must be verified."
            )
        )
        help_text.setWordWrap(True)
        form.addRow(help_text)
        approval = QCheckBox(
            self.tr("I explicitly authorize automatic downloads under these limits")
        )
        form.addRow(approval)
        preview = QTextEdit()
        preview.setReadOnly(True)
        form.addRow(preview)
        scroll.setWidget(pane)
        outer.addWidget(scroll)
        previewed = [""]

        def preference_definition():
            values = {
                "min_size": int(preference_fields["min_size"].text()),
                "max_size": int(preference_fields["max_size"].text())
                if preference_fields["max_size"].text().strip()
                else None,
                "min_seeders": int(preference_fields["min_seeders"].text()),
                "priorities": [
                    v.strip()
                    for v in preference_fields["priorities"].text().split(",")
                    if v.strip()
                ],
                "prefer_small": prefer_small.isChecked(),
            }
            for group in ("required", "preferred", "excluded"):
                values[group] = {}
                for key in (
                    "quality",
                    "codec",
                    "audio",
                    "subtitles",
                    "format",
                    "bitrate",
                    "platform",
                    "license",
                ):
                    selected = [
                        v.strip()
                        for v in preference_fields[group + "-" + key].text().split(",")
                        if v.strip()
                    ]
                    if selected:
                        values[group][key] = selected
            return Preferences.model_validate(values)

        def definition():
            values = {
                key: int(fields[key].text())
                for key in (
                    "interval_minutes",
                    "wait_minutes",
                    "daily_bytes",
                    "daily_torrents",
                    "reserve_bytes",
                )
            }
            return Subscription(
                **{
                    **feed.model_dump(),
                    **values,
                    "name": fields["name"].text(),
                    "query": fields["query"].text(),
                    "categories": [
                        int(v.strip()) for v in fields["categories"].text().split(",") if v.strip()
                    ],
                    "client_id": client.currentData(),
                    "folder": folder.currentText(),
                    "mode": mode.currentData(),
                    "include_current": include.isChecked(),
                    "replace_pending": replace.isChecked(),
                    "download_hours": [
                        int(v.strip())
                        for v in fields["download_hours"].text().split(",")
                        if v.strip()
                    ],
                    "preferences": preference_definition(),
                }
            )

        def preview_feed():
            try:
                value = definition()

                def done(result):
                    previewed[0] = value.model_dump_json()
                    preview.setPlainText(json.dumps(result, indent=2))

                run_in_background(
                    lambda: control.feeds.preview(value),
                    done,
                    lambda e: preview.setPlainText(str(e)),
                )
            except Exception as error:
                preview.setPlainText(str(error))

        def save():
            try:
                value = definition()
                if not identifier and previewed[0] != value.model_dump_json():
                    raise ValueError(self.tr("Preview this definition before saving."))
                control.save(value, approved=approval.isChecked())
                dialog.accept()
                self.reload()
            except Exception as error:
                preview.setPlainText(str(error))

        buttons = QHBoxLayout()
        for label, action in [
            (self.tr("Preview"), preview_feed),
            (self.tr("Save subscription"), save),
            (self.tr("Cancel"), dialog.reject),
        ]:
            button = QPushButton(label)
            button.clicked.connect(action)
            buttons.addWidget(button)
        outer.addLayout(buttons)
        dialog.resize(850, 750)
        dialog.exec()
