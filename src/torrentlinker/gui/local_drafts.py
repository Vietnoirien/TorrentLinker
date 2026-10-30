"""Owner review of local Upload drafts, shared with MCP and the web UI."""

from __future__ import annotations

from PySide6.QtCore import QSettings, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from torrentlinker.agent.upload_presentations import draft_item
from torrentlinker.bbcode import bbcode_to_html
from torrentlinker.gui.chat_images import ChatImages
from torrentlinker.gui.controls import icon_button, set_role
from torrentlinker.gui.errors import error_text
from torrentlinker.gui.library_model import human_size
from torrentlinker.gui.selection_cards import SelectionDetail
from torrentlinker.gui.tasks import run_in_background
from torrentlinker.gui.upload_rules import stored_rule_text
from torrentlinker.torrent_details import web_url
from torrentlinker.upload import PROFILES, category_name
from torrentlinker.upload_presentation import assess
from torrentlinker.upload_queue import reset_local


class LocalDrafts(QWidget):
    sent = Signal(object)

    def __init__(self, store, save, send, edit_details=None, options=None):
        super().__init__()
        self.store, self.save_callback, self.send_callback = store, save, send
        self.edit_details = edit_details
        self.options_callback = options
        self.option_choices = {}
        self.option_generation = 0
        self.option_widgets = {}
        self.stale = False
        self.record = None
        self.busy = False
        self.loading = False
        self.images = ChatImages(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 12, 0, 0)
        left = QWidget()
        sidebar = QVBoxLayout(left)
        sidebar.setContentsMargins(0, 0, 12, 0)
        search_row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(self.tr("Find a draft…"))
        self.search.setAccessibleName(self.tr("Find a draft…"))
        self.search.textChanged.connect(self.filter_rows)
        search_row.addWidget(self.search, 1)
        self.refresh_button = icon_button("↻", self.tr("Refresh"))
        self.refresh_button.clicked.connect(self.refresh)
        search_row.addWidget(self.refresh_button)
        sidebar.addLayout(search_row)
        self.table = QTableWidget(0, 1)
        self.table.setHorizontalHeaderLabels([self.tr("Local drafts")])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().hide()
        self.table.setShowGrid(False)
        self.table.setWordWrap(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self.selected)
        self.table.itemClicked.connect(lambda _item: self.selected())
        self.table.itemActivated.connect(lambda _item: self.selected())
        sidebar.addWidget(self.table, 1)
        self.empty = QLabel(self.tr("No local drafts. Choose New draft to prepare a Library item."))
        self.empty.setWordWrap(True)
        sidebar.addWidget(self.empty)
        self.editor = QWidget()
        right = QVBoxLayout(self.editor)
        right.setContentsMargins(12, 0, 0, 0)
        header = QHBoxLayout()
        self.heading = QLabel(self.tr("Select a local draft"))
        font = self.heading.font()
        font.setPointSize(font.pointSize() + 3)
        self.heading.setFont(font)
        self.heading.setObjectName("detailTitle")
        self.heading.setWordWrap(True)
        header.addWidget(self.heading, 1)
        menu_button = icon_button("⋯", self.tr("Draft actions"))
        menu = QMenu(menu_button)
        self.remove_button = menu.addAction(self.tr("Remove from local queue"), self.remove)
        self.reset_button = menu.addAction(self.tr("Allow retry after checking c411…"), self.reset)
        menu_button.setMenu(menu)
        menu_button.setPopupMode(menu_button.ToolButtonPopupMode.InstantPopup)
        header.addWidget(menu_button)
        right.addLayout(header)
        self.revision_label = QLabel()
        self.revision_label.setWordWrap(True)
        self.revision_label.setProperty("role", "muted")
        right.addWidget(self.revision_label)
        self.pages = QTabWidget()
        details_page = QWidget()
        fields = QFormLayout(details_page)
        fields.setContentsMargins(12, 16, 12, 12)
        self.title = QLineEdit()
        fields.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        fields.addRow(self.tr("Upload name"), self.title)
        self.category = QComboBox()
        for cid in PROFILES:
            self.category.addItem(category_name(cid), cid)
        fields.addRow(self.tr("Category"), self.category)
        self.subcategory = QComboBox()
        fields.addRow(self.tr("Subcategory"), self.subcategory)
        self.source = QLineEdit()
        fields.addRow(self.tr("Source"), self.source)
        self.options_form = QFormLayout()
        fields.addRow(self.options_form)
        self.options_status = QLabel()
        self.options_status.setWordWrap(True)
        fields.addRow(self.options_status)
        self.category.currentIndexChanged.connect(self.category_changed)
        self.subcategory.currentIndexChanged.connect(self.load_options)
        self.details = QLabel()
        self.details.setTextFormat(Qt.TextFormat.PlainText)
        self.details.setWordWrap(True)
        fields.addRow(self.details)
        self.edit_button = QPushButton(self.tr("Open model tools…"))
        set_role(self.edit_button, "quiet")
        self.edit_button.clicked.connect(self.open_details)

        self.pages.addTab(details_page, self.tr("Details"))
        file_page = QWidget()
        file_layout = QVBoxLayout(file_page)
        self.files = QPlainTextEdit()
        self.files.setReadOnly(True)
        self.nfo = QPlainTextEdit()
        file_layout.addWidget(self.files, 1)
        file_layout.addWidget(QLabel(self.tr("NFO")))
        file_layout.addWidget(self.nfo, 1)
        self.pages.addTab(file_page, self.tr("Files && NFO"))
        description_page = QWidget()
        description_layout = QVBoxLayout(description_page)
        self.description = QPlainTextEdit()
        self.preview = QTextBrowser()
        description_modes = QTabWidget()
        description_modes.addTab(self.description, self.tr("Edit"))
        description_modes.addTab(self.preview, self.tr("Preview"))
        description_layout.addWidget(description_modes)
        self.pages.addTab(description_page, self.tr("Description"))
        artwork = QWidget()
        artwork_layout = QFormLayout(artwork)
        self.image = QLineEdit()
        self.image.setPlaceholderText("https://…")
        artwork_layout.addRow(self.tr("Hosted image URL"), self.image)
        host = QPushButton(self.tr("Host image…"))
        set_role(host, "quiet")
        host.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://postimages.org/")))
        artwork_layout.addRow(host)
        artwork_layout.addRow(self.edit_button)
        image_note = QLabel(
            self.tr("Use a direct image URL. Model tools open the preparation editor.")
        )
        image_note.setWordWrap(True)
        artwork_layout.addRow(image_note)
        self.pages.addTab(artwork, self.tr("Artwork"))
        review_page = QWidget()
        review_layout = QVBoxLayout(review_page)
        self.status = QLabel()
        self.status.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        review_scroll = QScrollArea()
        review_scroll.setWidgetResizable(True)
        review_scroll.setWidget(self.status)
        review_layout.addWidget(review_scroll, 1)
        self.reviewed = QCheckBox(
            self.tr("I reviewed this saved revision, its files and category warnings.")
        )
        self.reviewed.toggled.connect(self.buttons)
        review_layout.addWidget(self.reviewed)
        note = QLabel(self.tr("Sending creates a c411 draft. Final publication happens on c411."))
        note.setWordWrap(True)
        review_layout.addWidget(note)
        self.preview_button = QPushButton(self.tr("Preview saved draft"))
        set_role(self.preview_button, "quiet")
        self.preview_button.clicked.connect(self.open_preview)
        review_layout.addWidget(self.preview_button, 0, Qt.AlignmentFlag.AlignLeft)
        self.pages.addTab(review_page, self.tr("Review"))
        self.pages.currentChanged.connect(self.buttons)
        right.addWidget(self.pages, 1)
        footer = QHBoxLayout()
        self.save_button = QPushButton(self.tr("Save locally"))
        self.save_button.clicked.connect(self.save)
        footer.addWidget(self.save_button)
        footer.addStretch()
        self.review_button = QPushButton(self.tr("Review draft"))
        set_role(self.review_button, "primary")
        self.review_button.clicked.connect(lambda: self.pages.setCurrentIndex(4))
        footer.addWidget(self.review_button)
        self.send_button = QPushButton(self.tr("Send to c411…"))
        set_role(self.send_button, "primary")
        self.send_button.clicked.connect(self.send)
        footer.addWidget(self.send_button)
        right.addLayout(footer)
        self.splitter = QSplitter()
        self.splitter.addWidget(left)
        self.splitter.addWidget(self.editor)
        self.splitter.setChildrenCollapsible(False)
        width = QSettings().value("upload/sidebar_width", 280, int)
        self.splitter.setSizes([width, 750])
        self.splitter.splitterMoved.connect(
            lambda *_: QSettings().setValue("upload/sidebar_width", self.splitter.sizes()[0])
        )
        layout.addWidget(self.splitter, 1)
        self.description.textChanged.connect(
            lambda: self.preview.setHtml(bbcode_to_html(self.description.toPlainText()))
        )
        for field in (self.title, self.image, self.description, self.nfo, self.source):
            field.textChanged.connect(self.changed)
        self.timer = QTimer(self)
        self.timer.setInterval(5000)
        self.timer.timeout.connect(
            lambda: self.refresh() if self.isVisible() and not self.busy else None
        )
        self.timer.start()
        self.refresh()
        self.buttons()

    def dirty(self):
        return bool(self.record and self.form() != {**self.record["form"], "reviewed": False})

    def changed(self):
        if self.loading:
            return
        self.reviewed.setChecked(False)
        self.buttons()

    def filter_rows(self):
        query = self.search.text().casefold()
        for row in range(self.table.rowCount()):
            self.table.setRowHidden(row, query not in self.table.item(row, 0).text().casefold())

    def category_changed(self):
        if self.loading:
            return
        self.loading = True
        self.subcategory.clear()
        for sub in PROFILES[self.category.currentData()].subcategories:
            self.subcategory.addItem(str(sub.label), int(sub.id))
        self.option_choices = {}
        self.loading = False
        self.load_options()
        self.changed()

    def load_options(self):
        if self.loading or not self.record or not self.options_callback:
            return
        self.option_generation += 1
        generation = self.option_generation
        subcategory = self.subcategory.currentData()
        self.option_widgets = {}
        while self.options_form.rowCount():
            self.options_form.removeRow(0)
        self.options_status.setText(self.tr("Loading category options…"))
        self.changed()

        def done(types):
            if generation != self.option_generation:
                return
            self.options_status.clear()
            self.loading = True
            for kind in types:
                selected = self.option_choices.get(kind.id, [])
                if kind.multiple:
                    widget = QListWidget()
                    widget.setMaximumHeight(100)
                    for value in kind.values:
                        item = QListWidgetItem(value.label)
                        item.setData(Qt.ItemDataRole.UserRole, value.id)
                        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                        item.setCheckState(
                            Qt.CheckState.Checked
                            if value.id in selected
                            else Qt.CheckState.Unchecked
                        )
                        widget.addItem(item)
                    widget.itemChanged.connect(self.options_changed)
                else:
                    widget = QComboBox()
                    widget.addItem("—", None)
                    for value in kind.values:
                        widget.addItem(value.label, value.id)
                    widget.setCurrentIndex(
                        max(0, widget.findData(selected[0] if selected else None))
                    )
                    widget.currentIndexChanged.connect(self.options_changed)
                self.option_widgets[kind.id] = widget
                self.options_form.addRow(kind.name + (" *" if kind.required else ""), widget)
            self.loading = False
            self.buttons()

        def failed(error):
            if generation == self.option_generation:
                self.options_status.setText(error_text(error))
                self.buttons()

        run_in_background(lambda: self.options_callback(subcategory), done, failed)

    def options_changed(self):
        if self.loading:
            return
        for identifier, widget in self.option_widgets.items():
            if isinstance(widget, QListWidget):
                self.option_choices[identifier] = [
                    widget.item(i).data(Qt.ItemDataRole.UserRole)
                    for i in range(widget.count())
                    if widget.item(i).checkState() == Qt.CheckState.Checked
                ]
            else:
                self.option_choices[identifier] = (
                    [widget.currentData()] if widget.currentData() else []
                )
        self.changed()

    def open_details(self):
        if self.record and self.edit_details:
            if self.dirty():
                self.status.setText(
                    self.tr("Save your changes locally before opening model tools.")
                )
                self.pages.setCurrentIndex(4)
                return
            self.edit_details(self.record)

    def status_text(self, value):
        return {
            "queued": self.tr("Awaiting review"),
            "sending": self.tr("Sending to c411"),
            "sent": self.tr("Sent to c411"),
            "uncertain": self.tr("Check c411 before retrying"),
        }.get(value, value)

    def refresh(self):
        if self.busy:
            return
        selected = self.record["id"] if self.record else ""
        rows = self.store.local_drafts()
        self.table.blockSignals(True)
        self.table.setRowCount(len(rows))
        for row, record in enumerate(rows):
            cell = QTableWidgetItem(
                "\n".join(
                    (
                        record["form"]["title"],
                        category_name(record["form"]["category"]),
                        self.status_text(record["status"]),
                    )
                )
            )
            cell.setData(Qt.ItemDataRole.UserRole, record)
            self.table.setItem(row, 0, cell)
            self.table.setRowHeight(row, 78)
            if record["id"] == selected:
                self.table.selectRow(row)
        self.table.blockSignals(False)
        if selected and not any(r["id"] == selected for r in rows):
            self.record = None
        if self.record:
            current = next((r for r in rows if r["id"] == self.record["id"]), None)
            self.stale = bool(
                current
                and (
                    current["revision"] != self.record["revision"]
                    or current["status"] != self.record["status"]
                )
            )
            if self.stale:
                self.reviewed.setChecked(False)
                self.status.setText(
                    self.tr("Draft changed elsewhere. Reopen it from the list before sending.")
                )
        self.empty.setVisible(not rows)
        self.filter_rows()
        self.buttons()

    def selected(self):
        if self.busy:
            return
        cells = self.table.selectedItems()
        if not cells:
            return
        candidate = cells[0].data(Qt.ItemDataRole.UserRole)
        if self.record and candidate["id"] == self.record["id"] and not self.stale:
            return
        if (
            self.dirty()
            and QMessageBox.question(
                self,
                self.tr("Unsaved changes"),
                self.tr("Discard unsaved changes and open another draft?"),
            )
            != QMessageBox.StandardButton.Yes
        ):
            self.refresh()
            return
        self.record = candidate
        self.load()

    def load(self):
        record = self.record
        if record is None:
            return
        self.loading = True
        self.stale = False
        self.reviewed.setChecked(False)
        form = record["form"]
        self.category.setCurrentIndex(self.category.findData(form["category"]))
        self.subcategory.clear()
        for sub in PROFILES[form["category"]].subcategories:
            self.subcategory.addItem(str(sub.label), int(sub.id))
        self.subcategory.setCurrentIndex(self.subcategory.findData(form["subcategory"]))
        self.source.setText(form.get("source", ""))
        self.option_choices = {
            int(k) if str(k).isdigit() else k: v for k, v in form.get("options", {}).items()
        }
        self.heading.setText(form["title"])
        self.title.setText(form["title"])
        self.image.setText(form.get("image", ""))
        self.description.setPlainText(form["description"])
        self.nfo.setPlainText(form["nfo"])
        self.files.setPlainText(
            "\n".join(f"{f['path']}   {human_size(f['size'])}" for f in record["files"])
        )
        self.details.setText(
            self.tr("{0} · subcategory {1} · {2} files\n{3}").format(
                category_name(form["category"]),
                form["subcategory"],
                len(record["files"]),
                record["path"],
            )
        )
        findings = [
            record.get("result", {}).get("message", ""),
            *(stored_rule_text(r) for r in record.get("review", {}).get("refusals", [])),
            *(
                f"{row['field']}: {row['message']}"
                for row in assess(form, record.get("review", {}).get("file_facts"), local=True)[
                    "missing_fields"
                ]
            ),
            *(stored_rule_text(w) for w in record.get("review", {}).get("warnings", [])),
        ]
        self.status.setText("\n".join(dict.fromkeys(finding for finding in findings if finding)))
        self.loading = False
        self.load_options()
        self.buttons()

    def buttons(self):
        state = self.record["status"] if self.record else ""
        editable = state == "queued" and not self.busy and not self.stale
        for widget in (
            self.title,
            self.image,
            self.description,
            self.nfo,
            self.save_button,
            self.edit_button,
            self.category,
            self.subcategory,
            self.source,
            *self.option_widgets.values(),
        ):
            widget.setEnabled(editable)
        self.editor.setEnabled(bool(state))
        self.preview_button.setEnabled(bool(state) and not self.busy)
        self.table.setEnabled(not self.busy)
        self.remove_button.setEnabled(bool(state) and state != "sending" and not self.busy)
        self.reset_button.setEnabled(state in {"sending", "uncertain"} and not self.busy)
        review = self.pages.currentIndex() == 4
        self.review_button.setVisible(not review)
        self.review_button.setEnabled(bool(state) and not self.busy)
        self.send_button.setVisible(review)
        clean = not self.dirty() and not self.stale
        self.reviewed.setEnabled(editable and clean)
        ready = False
        if self.record:
            form = self.record["form"]
            missing = assess(form, self.record.get("review", {}).get("file_facts"), local=True)[
                "missing_fields"
            ]
            ready = (
                not missing
                and not self.record.get("review", {}).get("refusals")
                and bool(web_url(form.get("image", "")))
            )
            self.revision_label.setText(
                self.tr("Unsaved changes")
                if not clean
                else self.tr("Saved locally · Revision {0} · {1}").format(
                    self.record["revision"], self.status_text(state)
                )
            )
        self.send_button.setEnabled(editable and clean and ready and self.reviewed.isChecked())

    def open_preview(self):
        if not self.record:
            return
        identifier, revision = self.record["id"], self.record["revision"]

        def load(_presentation, _item):
            current = self.store.local_draft(identifier)
            if current["revision"] != revision:
                raise ValueError(self.tr("Draft changed. Refresh the queue and preview it again."))
            return draft_item(current, "0", self.store)

        dialog = SelectionDetail("", "0", load, self.images, self)
        dialog.open()

    def form(self):
        return {
            **self.record["form"],
            "category": self.category.currentData(),
            "subcategory": self.subcategory.currentData(),
            "source": self.source.text(),
            "options": {str(k): v for k, v in self.option_choices.items()},
            "title": self.title.text().strip(),
            "image": self.image.text().strip(),
            "description": self.description.toPlainText(),
            "nfo": self.nfo.toPlainText(),
            "nfo_origin": "original"
            if self.nfo.toPlainText() != self.record["form"].get("nfo")
            else self.record["form"].get("nfo_origin", ""),
            "reviewed": False,
        }

    def work(self, fn, done):
        self.busy = True
        self.buttons()

        def success(value):
            self.busy = False
            done(value)
            self.refresh()
            self.buttons()

        def failed(error):
            self.busy = False
            self.status.setText(error_text(error))
            if self.record:
                self.record = self.store.local_draft(self.record["id"])
            self.refresh()
            self.buttons()

        run_in_background(fn, success, failed)

    def save(self):
        if self.record:
            record, form = self.record, self.form()

            def saved(value):
                self.record = value
                self.load()
                self.status.setText(
                    self.tr("Saved locally. Nothing sent to c411.") + "\n" + self.status.text()
                )

            self.work(lambda: self.save_callback(record, form), saved)

    def send(self):
        if not self.record or not self.reviewed.isChecked():
            return
        if self.form() != {**self.record["form"], "reviewed": False}:
            self.status.setText(self.tr("Save your changes locally before sending."))
            return
        if (
            QMessageBox.question(
                self,
                self.tr("Send to c411"),
                self.tr(
                    "Send this saved description, category, NFO and files to c411 as a Draft? "
                    "It will not be published."
                ),
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        record = self.record

        def sent(prepared):
            self.record = self.store.local_draft(record["id"])
            self.load()
            self.sent.emit(prepared)

        self.work(lambda: self.send_callback(record), sent)

    def remove(self):
        if not self.record:
            return
        if (
            QMessageBox.question(
                self,
                self.tr("Remove from local queue"),
                self.tr("Remove this local record? Files and any c411 Draft will be kept."),
            )
            == QMessageBox.StandardButton.Yes
        ):
            try:
                self.store.remove_local_draft(self.record["id"], self.record["revision"])
                self.record = None
                self.refresh()
            except ValueError as error:
                self.status.setText(str(error))

    def reset(self):
        if not self.record:
            return
        if (
            QMessageBox.question(
                self,
                self.tr("Allow another attempt"),
                self.tr(
                    "Check c411 and wait for any running send to finish first. "
                    "Confirm that no Draft was created and another attempt is needed."
                ),
            )
            == QMessageBox.StandardButton.Yes
        ):
            try:
                self.record = reset_local(self.store, self.record["id"], self.record["revision"])
                self.load()
                self.refresh()
            except ValueError as error:
                self.status.setText(str(error))
