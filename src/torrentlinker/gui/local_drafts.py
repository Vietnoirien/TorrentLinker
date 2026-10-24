"""Owner review of local Upload drafts, shared with MCP and the web UI."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFormLayout,
    QGridLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from torrentlinker.bbcode import bbcode_to_html
from torrentlinker.gui.errors import error_text
from torrentlinker.gui.library_model import human_size
from torrentlinker.gui.tasks import run_in_background
from torrentlinker.upload import category_name
from torrentlinker.upload_queue import reset_local


class LocalDrafts(QWidget):
    sent = Signal(object)

    def __init__(self, store, save, send):
        super().__init__()
        self.store, self.save_callback, self.send_callback = store, save, send
        self.record = None
        self.busy = False
        layout = QVBoxLayout(self)
        note = QLabel(self.tr("Saved only on this device/server. Review before sending to c411."))
        note.setWordWrap(True)
        layout.addWidget(note)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(
            [self.tr("Title"), self.tr("Category"), self.tr("Status")]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self.selected)
        editor = QWidget()
        right = QVBoxLayout(editor)
        fields = QFormLayout()
        self.title = QLineEdit()
        self.image = QLineEdit()
        fields.addRow(self.tr("Title"), self.title)
        fields.addRow(self.tr("Image URL"), self.image)
        right.addLayout(fields)
        self.details = QLabel()
        self.details.setTextFormat(Qt.TextFormat.PlainText)
        self.details.setWordWrap(True)
        right.addWidget(self.details)
        pages = QTabWidget()
        self.description = QPlainTextEdit()
        self.preview = QTextBrowser()
        self.nfo = QPlainTextEdit()
        self.files = QPlainTextEdit()
        self.files.setReadOnly(True)
        pages.addTab(self.description, self.tr("Description"))
        pages.addTab(self.preview, self.tr("Preview"))
        pages.addTab(self.nfo, self.tr("NFO"))
        pages.addTab(self.files, self.tr("Files"))
        self.description.textChanged.connect(
            lambda: self.preview.setHtml(bbcode_to_html(self.description.toPlainText()))
        )
        right.addWidget(pages, 1)
        split = QSplitter()
        split.addWidget(self.table)
        split.addWidget(editor)
        split.setSizes([300, 650])
        layout.addWidget(split, 1)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        actions = QGridLayout()
        self.refresh_button = QPushButton(self.tr("Refresh"))
        self.refresh_button.clicked.connect(self.refresh)
        self.save_button = QPushButton(self.tr("Save changes locally"))
        self.save_button.clicked.connect(self.save)
        self.send_button = QPushButton(self.tr("Send to c411…"))
        self.send_button.clicked.connect(self.send)
        self.remove_button = QPushButton(self.tr("Remove from local queue"))
        self.remove_button.clicked.connect(self.remove)
        self.reset_button = QPushButton(self.tr("Allow retry after checking c411…"))
        self.reset_button.clicked.connect(self.reset)
        for index, button in enumerate(
            (
                self.refresh_button,
                self.save_button,
                self.send_button,
                self.remove_button,
                self.reset_button,
            )
        ):
            actions.addWidget(button, index // 3, index % 3)
        layout.addLayout(actions)
        self.timer = QTimer(self)
        self.timer.setInterval(5000)
        self.timer.timeout.connect(
            lambda: self.refresh() if self.isVisible() and not self.busy else None
        )
        self.timer.start()
        self.refresh()
        self.buttons()

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
            for col, value in enumerate(
                (
                    record["form"]["title"],
                    category_name(record["form"]["category"]),
                    self.status_text(record["status"]),
                )
            ):
                cell = QTableWidgetItem(str(value))
                cell.setData(Qt.ItemDataRole.UserRole, record)
                self.table.setItem(row, col, cell)
            if record["id"] == selected:
                self.table.selectRow(row)
        self.table.blockSignals(False)
        if selected and not any(r["id"] == selected for r in rows):
            self.record = None
        self.buttons()

    def selected(self):
        if self.busy:
            return
        cells = self.table.selectedItems()
        if not cells:
            return
        self.record = cells[0].data(Qt.ItemDataRole.UserRole)
        self.load()

    def load(self):
        record = self.record
        if record is None:
            return
        form = record["form"]
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
        self.status.setText(
            "\n".join(
                [
                    record.get("result", {}).get("message", ""),
                    *record.get("review", {}).get("refusals", []),
                    *record.get("review", {}).get("warnings", []),
                ]
            )
        )
        self.buttons()

    def buttons(self):
        state = self.record["status"] if self.record else ""
        editable = state == "queued" and not self.busy
        for widget in (
            self.title,
            self.image,
            self.description,
            self.nfo,
            self.save_button,
            self.send_button,
        ):
            widget.setEnabled(editable)
        self.table.setEnabled(not self.busy)
        self.remove_button.setEnabled(bool(state) and state != "sending" and not self.busy)
        self.reset_button.setEnabled(state in {"sending", "uncertain"} and not self.busy)

    def form(self):
        return {
            **self.record["form"],
            "title": self.title.text().strip(),
            "image": self.image.text().strip(),
            "description": self.description.toPlainText(),
            "nfo": self.nfo.toPlainText(),
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
        if not self.record:
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
