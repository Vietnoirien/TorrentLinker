"""Owner controls for MCP tokens, proposals and activity."""

from __future__ import annotations

import json
import os
from typing import Any

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from torrentlinker.agent.access import Grant
from torrentlinker.gui.controls import set_role
from torrentlinker.gui.request_details import RequestDetails
from torrentlinker.gui.tasks import run_in_background


class AgentAccess(QWidget):
    approval_requested = Signal(str)

    def __init__(self, service, endpoint: str, parent=None):
        super().__init__(parent)
        self.service = service
        layout = QVBoxLayout(self)
        self.enabled = QCheckBox(self.tr("Enable agent access"))
        self.enabled.setChecked(service.access.enabled)
        self.enabled.toggled.connect(self.enable)
        layout.addWidget(self.enabled)
        address = QLineEdit(endpoint)
        address.setReadOnly(True)
        layout.addWidget(address)
        help_text = QLabel(
            self.tr(
                "New connections only propose changes. Approve proposals here, or allow selected "
                "actions within daily limits. Removal and file deletion always need your approval."
            )
        )
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        tabs = self.tabs = QTabWidget()
        layout.addWidget(tabs, 1)
        connections = QWidget()
        connection_layout = QVBoxLayout(connections)
        self.connections = QListWidget()
        self.connections.setAccessibleName(self.tr("Connections"))
        self.connection_details = QPlainTextEdit()
        self.connection_details.setReadOnly(True)
        self.connection_details.setAccessibleName(self.tr("Connection details"))
        connection_split = QSplitter()
        connection_split.addWidget(self.connections)
        connection_split.addWidget(self.connection_details)
        connection_split.setStretchFactor(1, 2)
        connection_layout.addWidget(connection_split, 1)
        self.connection_empty = QLabel(
            self.tr("No connections yet. Choose New connection to create one.")
        )
        self.connection_empty.setWordWrap(True)
        connection_layout.addWidget(self.connection_empty)
        self.revoke = QPushButton(self.tr("Revoke connection"))
        self.revoke.clicked.connect(self.revoke_selected)
        connection_layout.addWidget(self.revoke, 0, Qt.AlignmentFlag.AlignRight)
        tabs.addTab(connections, self.tr("Connections"))
        self.connections.currentRowChanged.connect(self.connection_selected)
        create = QWidget()
        form = QFormLayout(create)
        self.name = QLineEdit()
        self.name.setMaxLength(100)
        form.addRow(self.tr("Connection name"), self.name)
        self.clients = []
        for p in service.setup.settings.client_profiles:
            if p.enabled:
                check = QCheckBox(p.name)
                check.setChecked(p.id == service.setup.settings.active_client_id)
                self.clients.append((p.id, check))
                form.addRow(check)
        self.mode = QComboBox()
        self.mode.addItem(self.tr("Proposals only"), "propose")
        self.mode.addItem(self.tr("Execute permitted actions"), "execute")
        form.addRow(self.tr("Mode"), self.mode)
        self.permissions = []
        for key, title in (
            ("controls", self.tr("Pause, recheck and resume completed torrents")),
            ("queue", self.tr("Prepare and edit download queue")),
            ("downloads", self.tr("Start downloads")),
            ("reseed", self.tr("Reseed")),
            ("uploads", self.tr("Upload drafts and seeding")),
            ("media", self.tr("Media playback, queues and playlists")),
        ):
            check = QCheckBox(title)
            check.setEnabled(False)
            self.permissions.append((key, check))
            form.addRow(check)

        def mode_changed():
            for _, check in self.permissions:
                check.setEnabled(self.mode.currentData() == "execute")

        self.mode.currentIndexChanged.connect(mode_changed)
        self.budget, self.count, self.reserve = QSpinBox(), QSpinBox(), QSpinBox()
        for field, maximum, value in (
            (self.budget, 100000, 10),
            (self.count, 1000, 20),
            (self.reserve, 100000, 0),
        ):
            field.setRange(0, maximum)
            field.setValue(value)
        form.addRow(self.tr("Daily download budget (GiB)"), self.budget)
        form.addRow(self.tr("Torrents per day"), self.count)
        self.reserve.setSpecialValueText(self.tr("No extra reserve"))
        form.addRow(self.tr("Keep free (GiB)"), self.reserve)
        button = QPushButton(self.tr("Create connection"))
        set_role(button, "primary")
        button.clicked.connect(self.create)
        form.addRow(button)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(create)
        tabs.addTab(scroll, self.tr("New connection"))
        panel = QWidget()
        review = QVBoxLayout(panel)
        split = QSplitter()
        self.items = QListWidget()
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        split.addWidget(self.items)
        split.addWidget(self.details)
        split.setStretchFactor(1, 2)
        review.addWidget(split)
        actions = QHBoxLayout()
        self.approve = QPushButton(self.tr("Approve proposal"))
        set_role(self.approve, "primary")
        self.reject_button = QPushButton(self.tr("Reject proposal"))
        self.cancel_job = QPushButton(self.tr("Cancel job"))
        refresh = QPushButton(self.tr("Refresh"))
        set_role(refresh, "quiet")
        for b in (self.approve, self.reject_button, self.cancel_job, refresh):
            actions.addWidget(b)
        review.addLayout(actions)
        self.release_storage = QPushButton(self.tr("Release uncertain storage reservation"))
        self.release_storage.clicked.connect(self.release_selected)
        review.addWidget(self.release_storage)
        tabs.addTab(panel, self.tr("Proposals and activity"))
        self.items.currentRowChanged.connect(self.selected)
        self.approve.clicked.connect(self.approve_selected)
        self.reject_button.clicked.connect(self.reject_selected)
        self.cancel_job.clicked.connect(self.cancel_selected)
        refresh.clicked.connect(self.refresh)
        self.status = QLabel(
            self.tr(
                "Connection changes apply immediately. "
                "Approved proposals run after Settings closes."
            )
        )
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.connection_records: list[dict[str, Any]] = []
        self.records: list[tuple[str, dict[str, Any]]] = []
        self.refresh()
        self.timer = QTimer(self)
        self.timer.setInterval(3000)
        self.timer.timeout.connect(self.refresh)

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()
        self.timer.start()

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)

    def enable(self, enabled):
        self.service.enable(enabled)

    def error(self, error):
        QMessageBox.warning(self, self.tr("Agent access"), str(error))

    def create(self):
        try:
            grant = self.service.access.create(
                Grant(
                    name=self.name.text().strip(),
                    clients=[i for i, c in self.clients if c.isChecked()],
                    mode=self.mode.currentData(),
                    permissions=[
                        k
                        for k, c in self.permissions
                        if c.isChecked() and self.mode.currentData() == "execute"
                    ],
                    daily_bytes=self.budget.value() * 1024**3,
                    daily_torrents=self.count.value(),
                    reserve_bytes=self.reserve.value() * 1024**3,
                )
            )
        except ValueError:
            self.error(self.tr("Enter a name and select at least one client."))
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(self.tr("Copy your agent token"))
        box = QVBoxLayout(dialog)
        label = QLabel(
            self.tr(
                "Shown only once. Keep this token private. Use it as the Bearer "
                "token or TL_MCP_TOKEN for the stdio bridge."
            )
        )
        label.setWordWrap(True)
        box.addWidget(label)
        token = QLineEdit(grant["token"])
        token.setReadOnly(True)
        box.addWidget(token)
        copy = QPushButton(self.tr("Copy token"))
        set_role(copy, "quiet")
        copy.clicked.connect(lambda: QApplication.clipboard().setText(token.text()))
        box.addWidget(copy)
        save_token = QPushButton(self.tr("Save token to file…"))
        save_token.clicked.connect(lambda: self.save_token(token.text()))
        box.addWidget(save_token)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        box.addWidget(buttons)
        dialog.exec()
        token.clear()
        self.refresh()

    def save_token(self, token: str) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, self.tr("Save token to file…"), "torrentlinker-token.txt"
        )
        if not path:
            return
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as target:
                if os.name != "nt":
                    os.fchmod(target.fileno(), 0o600)
                target.write(token + "\n")
        except OSError as error:
            self.error(error)

    def refresh(self):
        selection = (
            self.items.currentItem().data(Qt.ItemDataRole.UserRole)
            if self.items.currentItem()
            else None
        )
        if not self.service.access.lock.acquire(blocking=False):
            return
        try:
            state = self.service.access.snapshot()
        finally:
            self.service.access.lock.release()
        selected_connection = self.connections.currentItem()
        identifier = (
            selected_connection.data(Qt.ItemDataRole.UserRole) if selected_connection else None
        )
        self.connection_records = [
            r for r in state["connections"] if not r["id"].startswith("assistant-")
        ]
        self.connections.blockSignals(True)
        self.connections.clear()
        for record in self.connection_records:
            status = self.tr("Revoked") if record["revoked"] else self.tr("Active")
            self.connections.addItem(f"{record['name']} · {status}")
            item = self.connections.item(self.connections.count() - 1)
            item.setData(Qt.ItemDataRole.UserRole, record["id"])
            if record["id"] == identifier:
                self.connections.setCurrentItem(item)
        if self.connections.currentRow() < 0 and self.connection_records:
            self.connections.setCurrentRow(0)
        self.connections.blockSignals(False)
        self.connection_empty.setVisible(not self.connection_records)
        self.connection_selected()
        self.records = [("proposal", r) for r in state["proposals"]]
        self.records += [("goal", r) for r in state["goals"]]
        self.records += [("activity", r) for r in state["activity"]]
        self.items.blockSignals(True)
        self.items.clear()
        for kind, record in self.records:
            title = record.get(
                "name", record.get("action", record.get("body", {}).get("kind", kind))
            )
            self.items.addItem(f"{title} · {record.get('status', kind)}")
            item = self.items.item(self.items.count() - 1)
            item.setData(Qt.ItemDataRole.UserRole, (kind, record["id"]))
            if (kind, record["id"]) == selection:
                self.items.setCurrentItem(item)
        self.items.blockSignals(False)
        self.selected(self.items.currentRow())

    def current(self):
        index = self.items.currentRow()
        return self.records[index] if 0 <= index < len(self.records) else ("", {})

    def selected(self, index):
        kind, record = self.current()
        self.details.setPlainText(json.dumps(record, indent=2, ensure_ascii=False, default=str))
        self.approve.setEnabled(kind == "proposal" and record["status"] == "pending")
        self.reject_button.setEnabled(self.approve.isEnabled())
        self.cancel_job.setEnabled(kind == "proposal" and bool(record.get("job_id")))
        self.release_storage.setEnabled(
            kind == "proposal" and record["body"]["kind"] == "send-queue"
        )
        if kind == "proposal" and record.get("job_id"):
            if not self.service.jobs.lock.acquire(blocking=False):
                return
            try:
                self.details.appendPlainText(
                    json.dumps(
                        self.service.jobs.get(record["job_id"]), indent=2, ensure_ascii=False
                    )
                )
            except KeyError:
                pass
            finally:
                self.service.jobs.lock.release()

    def release_selected(self):
        kind, record = self.current()
        if kind != "proposal":
            return
        if (
            QMessageBox.question(
                self,
                self.tr("Release storage reservation"),
                self.tr(
                    "Check the Torrent Client first. Confirm that this send has finished or "
                    "did not start. This releases uncertain storage only; "
                    "daily spending stays counted."
                ),
                defaultButton=QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        try:
            self.service.release_storage(record["id"])
            self.refresh()
        except (ValueError, KeyError) as error:
            self.error(error)

    def approve_selected(self):
        kind, record = self.current()
        if kind != "proposal":
            return

        def reviewed(preview):
            operation = preview.get("operation", {})
            queue_removal = (
                operation.get("kind") == "edit-queue-selection"
                and operation.get("queue_action") == "remove"
            )
            if "local_draft" in preview or "groups" in preview or queue_removal:
                dialog = QDialog(self)
                dialog.setWindowTitle(self.tr("Approve proposal"))
                dialog.resize(720, 520)
                layout = QVBoxLayout(dialog)
                if "groups" in preview:
                    lines = [preview.get("warning", "")]
                    for group in preview["groups"]:
                        lines.append(
                            f"\n{group['client']} ({group['client_id']}): "
                            f"{group['torrent_instance_count']} torrents, "
                            f"{group['metadata_size_bytes']:,} metadata bytes"
                        )
                        lines.extend(
                            f"{target['name']} [{target['hash']}]\n{target['folder']}"
                            for target in group["targets"]
                        )
                    content = "\n".join(lines)
                else:
                    content = json.dumps(preview, indent=2, ensure_ascii=False)
                if queue_removal:
                    layout.addWidget(RequestDetails({"review": preview}))
                else:
                    text = QPlainTextEdit(content)
                    text.setReadOnly(True)
                    layout.addWidget(text)
                buttons = QDialogButtonBox(
                    QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
                )
                buttons.accepted.connect(dialog.accept)
                buttons.rejected.connect(dialog.reject)
                layout.addWidget(buttons)
                if dialog.exec() != QDialog.DialogCode.Accepted:
                    return
            if "torrents" in preview:
                text = (
                    preview["client"]
                    + "\n"
                    + preview["warning"]
                    + "\n\n"
                    + "\n".join(t["name"] + "\n" + t["folder"] for t in preview["torrents"])
                )
                if (
                    QMessageBox.question(
                        self,
                        self.tr("Confirm removal"),
                        text,
                        defaultButton=QMessageBox.StandardButton.No,
                    )
                    != QMessageBox.StandardButton.Yes
                ):
                    return
            if self.service.suspended:
                self.approval_requested.emit(record["id"])
                self.status.setText(
                    self.tr("Approval queued. Close Settings to run the approved proposal.")
                )
                return
            run_in_background(
                lambda: self.service.execute(record["id"], approved=True),
                lambda _: self.refresh(),
                self.error,
            )

        run_in_background(lambda: self.service.review(record["id"]), reviewed, self.error)

    def reject_selected(self):
        kind, record = self.current()
        if kind == "proposal":
            self.service.reject(record["id"])
        self.refresh()

    def connection_selected(self, _index=-1):
        index = self.connections.currentRow()
        record = (
            self.connection_records[index] if 0 <= index < len(self.connection_records) else None
        )
        self.revoke.setEnabled(bool(record and not record["revoked"]))
        if not record:
            self.connection_details.clear()
            return
        names = {p.id: p.name for p in self.service.setup.settings.client_profiles}
        mode = (
            self.tr("Proposals only")
            if record["mode"] == "propose"
            else self.tr("Execute permitted actions")
        )
        permissions = dict((key, check.text()) for key, check in self.permissions)
        self.connection_details.setPlainText(
            "\n".join(
                [
                    record["name"],
                    self.tr("Revoked") if record["revoked"] else self.tr("Active"),
                    mode,
                    self.tr("Torrent Clients: {0}").format(
                        ", ".join(names.get(i, i) for i in record["clients"])
                    ),
                    self.tr("Permissions: {0}").format(
                        ", ".join(permissions.get(p, p) for p in record["permissions"])
                        or self.tr("Proposals only")
                    ),
                    self.tr("Daily download budget (GiB)")
                    + f": {record['daily_bytes'] / 1024**3:g}",
                    self.tr("Torrents per day") + f": {record['daily_torrents']}",
                    self.tr("Keep free (GiB)") + f": {record['reserve_bytes'] / 1024**3:g}",
                    "",
                    self.tr(
                        "Tokens are shown only when created. "
                        "Revoke a lost token and create a new connection."
                    ),
                ]
            )
        )

    def revoke_selected(self):
        index = self.connections.currentRow()
        if 0 <= index < len(self.connection_records):
            self.service.revoke(self.connection_records[index]["id"])
        self.refresh()

    def cancel_selected(self):
        kind, record = self.current()
        if kind == "proposal" and record.get("job_id"):
            self.service.jobs.cancel(record["job_id"])
        self.refresh()
