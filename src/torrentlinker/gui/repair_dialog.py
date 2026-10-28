"""Explicit copy/check/confirm workflow for experimental qBittorrent repairs."""

from __future__ import annotations

import threading

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from torrentlinker.gui.tasks import run_in_background
from torrentlinker.repair import Repairs


class RepairDialog(QDialog):
    def __init__(self, parent, repository: Repairs, client, *, diagnose=None):
        super().__init__(parent)
        self.repository, self.client = repository, client
        self.row = None
        self.busy = False
        self.stop = threading.Event()
        self.setWindowTitle(self.tr("Experimental repair on a copy"))
        self.resize(700, 500)
        layout = QVBoxLayout(self)
        note = QLabel(
            self.tr(
                "The original stays unchanged. Prepare an independent copy, "
                "wait for the client check, then confirm downloading. "
                "Source/team metadata and seeder counts are not guarantees."
            )
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        self.history = QComboBox()
        for row in repository.rows():
            self.history.addItem(f"{row['name']} · {row['status']}", row)
        self.history.currentIndexChanged.connect(
            lambda _: self.show_row(self.history.currentData())
        )
        layout.addWidget(self.history)
        self.report = QPlainTextEdit()
        self.report.setReadOnly(True)
        layout.addWidget(self.report)
        self.experimental = QCheckBox(
            self.tr("Enable experimental repair (real-library trials pending)")
        )
        self.experimental.toggled.connect(lambda _: self.show_row(self.row))
        layout.addWidget(self.experimental)
        self.prepare_button = QPushButton(self.tr("Prepare independent copy…"))
        self.prepare_button.clicked.connect(self.prepare)
        self.refresh_button = QPushButton(self.tr("Refresh verification"))
        self.refresh_button.clicked.connect(self.refresh)
        self.start_button = QPushButton(self.tr("Confirm download into copy…"))
        self.start_button.clicked.connect(self.start)
        for button in (self.prepare_button, self.refresh_button, self.start_button):
            layout.addWidget(button)
        self.show_row(self.history.currentData())
        if diagnose:
            self.run(lambda: diagnose(self.stop))

    def show_row(self, row):
        self.row = row
        if row:
            self.report.setPlainText(
                f"{row['name']} · {row['status']}\n"
                + self.tr("Original: ")
                + row["source"]
                + "\n"
                + self.tr("Copy: ")
                + row.get("copy", self.tr("Not prepared"))
                + "\n"
                + self.tr("Verified bytes: ")
                + f"{row['verified_bytes']:,} / {row['target_bytes']:,}\n"
                + self.tr("Estimated missing payload: ")
                + f"{row['missing_bytes']:,} bytes\n"
                + self.tr(
                    "Limits: 1% / 50 MiB size difference, 90% verified, 500 MiB missing, 2 seeders."
                )
            )
        self.prepare_button.setEnabled(
            bool(row and row["eligible"] and row["status"] == "awaiting-confirmation")
            and self.experimental.isChecked()
            and not self.busy
        )
        self.refresh_button.setEnabled(bool(row and row.get("copy")) and not self.busy)
        self.start_button.setEnabled(bool(row and row["status"] == "ready") and not self.busy)
        self.history.setEnabled(not self.busy)

    def run(self, work):
        self.busy = True
        self.show_row(self.row)

        def done(row):
            self.busy = False
            self.show_row(row)

        def failed(error):
            self.busy = False
            self.show_row(self.row)
            QMessageBox.warning(self, self.windowTitle(), str(error))

        run_in_background(work, done, failed)

    def prepare(self):
        if not self.row:
            return
        folder = QFileDialog.getExistingDirectory(self, self.tr("Destination for independent copy"))
        if not folder:
            return
        from pathlib import Path

        identifier = self.row["id"]
        self.run(
            lambda: self.repository.prepare(
                identifier, Path(folder), self.client, self.stop, experimental=True
            )
        )

    def refresh(self):
        if self.row:
            identifier = self.row["id"]
            self.run(lambda: self.repository.refresh(identifier, self.client))

    def start(self):
        if not self.row:
            return
        row = self.row
        text = (
            self.tr(
                "Download missing content into this copy? The original is retained. "
                "Network traffic may exceed the missing payload estimate."
            )
            + "\n"
            + row["copy"]
        )
        if (
            QMessageBox.question(
                self,
                self.windowTitle(),
                text,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        self.run(lambda: self.repository.start(row["id"], row["id"], self.client))

    def reject(self):
        if self.busy:
            self.stop.set()
            return
        super().reject()
