"""Native Assistant UI. Model/network work never runs on the Qt event thread."""

from __future__ import annotations

import html
import json
from datetime import datetime
from typing import Any

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
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
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from torrentlinker.assistant.models import Conversation, Schedule
from torrentlinker.assistant.providers import PRESETS, Provider
from torrentlinker.assistant.research import SearchSettings
from torrentlinker.gui.tasks import run_in_background


class AssistantEditor(QDialog):
    def __init__(self, service, *, task=False, initial=None, parent=None):
        super().__init__(parent)
        self.service, self.task = service, task
        self.initial = initial or {}
        self.setWindowTitle(self.tr("Scheduled task") if task else self.tr("New discussion"))
        self.resize(620, 700)
        layout = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        pane = QWidget()
        form = QFormLayout(pane)
        scroll.setWidget(pane)
        layout.addWidget(scroll)
        self.name = QLineEdit(self.initial.get("name", ""))
        self.name.setAccessibleName(self.tr("Name"))
        form.addRow(self.tr("Name"), self.name)
        self.provider = QComboBox()
        for p in service.setup()["providers"]:
            self.provider.addItem(p["name"] + " · " + p["model"], p["id"])
        if self.initial.get("provider_id"):
            self.provider.setCurrentIndex(self.provider.findData(self.initial["provider_id"]))
        form.addRow(self.tr("Model connection"), self.provider)
        policy = self.initial.get("policy", {})
        self.mode = QComboBox()
        self.mode.addItem(self.tr("Proposals only"), "propose")
        self.mode.addItem(self.tr("Execute within limits"), "execute")
        self.mode.setCurrentIndex(self.mode.findData(policy.get("mode", "propose")))
        form.addRow(self.tr("Action policy"), self.mode)
        self.clients = []
        clients = QWidget()
        choices = QVBoxLayout(clients)
        for p in service.agent.setup.settings.client_profiles:
            if p.enabled:
                check = QCheckBox(p.name)
                check.setChecked(
                    p.id in policy.get("clients", [service.agent.setup.settings.default_client_id])
                )
                choices.addWidget(check)
                self.clients.append((p.id, check))
        form.addRow(self.tr("Allowed Torrent Clients"), clients)
        self.web = QCheckBox(self.tr("Allow public Web research"))
        self.web.setChecked(self.initial.get("web", False))
        form.addRow(self.web)
        advanced = QGroupBox(self.tr("Permissions and limits"))
        advanced.setCheckable(True)
        advanced.setChecked(False)
        al = QVBoxLayout(advanced)
        self.options = QWidget()
        af = QFormLayout(self.options)
        al.addWidget(self.options)
        self.options.hide()
        advanced.toggled.connect(self.options.setVisible)
        self.permissions = []
        for value, label in [
            ("downloads", self.tr("Downloads")),
            ("controls", self.tr("Torrent controls")),
            ("reseed", self.tr("Reseeds")),
            ("uploads", self.tr("Uploads")),
        ]:
            check = QCheckBox(label)
            check.setChecked(value in policy.get("permissions", []))
            af.addRow(check)
            self.permissions.append((value, check))
        self.mode.currentIndexChanged.connect(self.policy_changed)
        self.policy_changed()
        self.daily_bytes = self.number(
            af,
            self.tr("Downloads per day, GiB"),
            policy.get("daily_bytes", 10 * 1024**3) // 1024**3,
            0,
            1000000,
        )
        self.daily_torrents = self.number(
            af, self.tr("Torrents per day"), policy.get("daily_torrents", 20), 0, 1000
        )
        self.reserve = self.number(
            af,
            self.tr("Keep free, GiB"),
            policy.get("reserve_bytes", 10 * 1024**3) // 1024**3,
            0,
            1000000,
        )
        self.calls = self.number(
            af, self.tr("Model calls per run"), self.initial.get("max_calls", 12), 1, 40
        )
        self.seconds = self.number(
            af, self.tr("Maximum duration, seconds"), self.initial.get("max_seconds", 300), 10, 1800
        )
        self.tokens = self.number(
            af, self.tr("Token limit per run"), self.initial.get("max_tokens", 60000), 1024, 500000
        )
        form.addRow(advanced)
        if task:
            self.instruction = QPlainTextEdit(self.initial.get("instruction", ""))
            self.instruction.setMaximumHeight(130)
            form.addRow(self.tr("Instructions"), self.instruction)
            self.kind = QComboBox()
            for label, value in [
                (self.tr("Model task"), "model"),
                (self.tr("Refresh torrents (no model)"), "refresh"),
                (self.tr("Refresh Catalogue (no model)"), "catalogue"),
            ]:
                self.kind.addItem(label, value)
            self.kind.setCurrentIndex(self.kind.findData(self.initial.get("kind", "model")))
            self.kind.currentIndexChanged.connect(
                lambda: self.provider.setEnabled(self.kind.currentData() == "model")
            )
            self.provider.setEnabled(self.kind.currentData() == "model")
            form.addRow(self.tr("Task type"), self.kind)
            self.frequency = QComboBox()
            for label, value in [
                (self.tr("Every X minutes"), "interval"),
                (self.tr("Daily"), "daily"),
                (self.tr("Weekly"), "weekly"),
            ]:
                self.frequency.addItem(label, value)
            self.frequency.setCurrentIndex(
                self.frequency.findData(self.initial.get("frequency", "daily"))
            )
            form.addRow(self.tr("Frequency"), self.frequency)
            self.interval = self.number(
                form,
                self.tr("Interval, minutes"),
                self.initial.get("interval_minutes", 60),
                5,
                525600,
            )
            self.at = QLineEdit(self.initial.get("at", "09:00"))
            self.zone = QLineEdit(self.initial.get("timezone", "Europe/Paris"))
            days = QWidget()
            days_layout = QHBoxLayout(days)
            days_layout.setContentsMargins(0, 0, 0, 0)
            self.days = []
            for index, label in enumerate(
                [
                    self.tr("Mon"),
                    self.tr("Tue"),
                    self.tr("Wed"),
                    self.tr("Thu"),
                    self.tr("Fri"),
                    self.tr("Sat"),
                    self.tr("Sun"),
                ]
            ):
                check = QCheckBox(label)
                check.setChecked(index in self.initial.get("weekdays", [0]))
                days_layout.addWidget(check)
                self.days.append(check)
            form.addRow(self.tr("Time (HH:MM)"), self.at)
            form.addRow(self.tr("Timezone"), self.zone)
            form.addRow(self.tr("Days"), days)

            def frequency_changed():
                value = self.frequency.currentData()
                for widget, visible in [
                    (self.interval, value == "interval"),
                    (self.at, value != "interval"),
                    (self.zone, value != "interval"),
                    (days, value == "weekly"),
                ]:
                    form.setRowVisible(widget, visible)

            self.frequency.currentIndexChanged.connect(frequency_changed)
            frequency_changed()
            self.enabled = QCheckBox(self.tr("Enable schedule"))
            self.enabled.setChecked(self.initial.get("enabled", False))
            form.addRow(self.enabled)
            preview = QPushButton(self.tr("Preview next run"))
            preview.clicked.connect(self.preview)
            form.addRow(preview)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.saved = ""

    def number(self, form, label, value, minimum, maximum):
        widget = QSpinBox()
        widget.setRange(minimum, maximum)
        widget.setValue(value)
        form.addRow(label, widget)
        return widget

    def policy_changed(self):
        for _, check in self.permissions:
            check.setEnabled(self.mode.currentData() == "execute")

    def value(self):
        data = dict(
            name=self.name.text().strip(),
            provider_id=self.provider.currentData() or "",
            web=self.web.isChecked(),
            max_calls=self.calls.value(),
            max_seconds=self.seconds.value(),
            max_tokens=self.tokens.value(),
            policy=dict(
                name=self.name.text().strip(),
                clients=[v for v, c in self.clients if c.isChecked()],
                mode=self.mode.currentData(),
                permissions=[v for v, c in self.permissions if c.isEnabled() and c.isChecked()],
                daily_bytes=self.daily_bytes.value() * 1024**3,
                daily_torrents=self.daily_torrents.value(),
                reserve_bytes=self.reserve.value() * 1024**3,
            ),
        )
        if self.task:
            data.update(
                instruction=self.instruction.toPlainText(),
                kind=self.kind.currentData(),
                frequency=self.frequency.currentData(),
                interval_minutes=self.interval.value(),
                at=self.at.text(),
                timezone=self.zone.text(),
                weekdays=[i for i, check in enumerate(self.days) if check.isChecked()],
                enabled=self.enabled.isChecked(),
            )
        return Schedule(**data) if self.task else Conversation(**data)

    def preview(self):
        import time

        try:
            value = self.value()
            QMessageBox.information(
                self,
                self.tr("Next run"),
                datetime.fromtimestamp(value.next_at(time.time())).astimezone().isoformat(),
            )
        except Exception as error:
            QMessageBox.warning(self, self.tr("Assistant"), str(error))

    def save(self):
        try:
            value = self.value()
            result = (
                self.service.save_schedule(value, self.initial.get("id", ""))
                if self.task
                else self.service.create_conversation(value)
            )
            self.saved = result["id"]
            self.accept()
        except Exception as error:
            QMessageBox.warning(self, self.tr("Assistant"), str(error))


class AssistantTab(QWidget):
    def status_text(self, value):
        return {
            "queued": self.tr("Queued"),
            "running": self.tr("Running"),
            "completed": self.tr("Completed"),
            "failed": self.tr("Failed"),
            "cancelled": self.tr("Cancelled"),
            "interrupted": self.tr("Interrupted"),
            "awaiting_approval": self.tr("Awaiting approval"),
            "finished": self.tr("Finished"),
        }.get(value, value)

    def __init__(self, get_service, parent=None):
        super().__init__(parent)
        self.get_service = get_service
        self.service: Any = None
        self.conversation_id = ""
        self.run_id = ""
        self.render_key = ""
        self.task_data = []
        self.provider_data = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.notice = QLabel(
            self.tr(
                "Connect a model to discuss tasks and create automations. "
                "Proposals are the default."
            )
        )
        self.notice.setWordWrap(True)
        layout.addWidget(self.notice)
        self.pages = QTabWidget()
        layout.addWidget(self.pages, 1)
        chat = QWidget()
        cl = QVBoxLayout(chat)
        splitter = QSplitter()
        left = QWidget()
        ll = QVBoxLayout(left)
        new = QPushButton(self.tr("New discussion"))
        new.clicked.connect(lambda: self.edit(False))
        ll.addWidget(new)
        self.conversations = QListWidget()
        self.conversations.currentRowChanged.connect(self.select_conversation)
        ll.addWidget(self.conversations)
        splitter.addWidget(left)
        right = QWidget()
        rl = QVBoxLayout(right)
        self.transcript = QTextBrowser()
        self.transcript.setOpenLinks(False)
        self.transcript.anchorClicked.connect(self.open_receipt)
        rl.addWidget(self.transcript, 1)
        self.prompt = QPlainTextEdit()
        self.prompt.setPlaceholderText(self.tr("Give a task or ask a question…"))
        self.prompt.setMaximumHeight(115)
        self.prompt.setAccessibleName(self.tr("Message"))
        rl.addWidget(self.prompt)
        controls = QHBoxLayout()
        self.send = QPushButton(self.tr("Send"))
        self.send.clicked.connect(self.send_message)
        controls.addWidget(self.send)
        stop = QPushButton(self.tr("Stop"))
        stop.clicked.connect(self.stop_run)
        controls.addWidget(stop)
        controls.addStretch()
        rl.addLayout(controls)
        splitter.addWidget(right)
        splitter.setSizes([220, 760])
        cl.addWidget(splitter)
        self.pages.addTab(chat, self.tr("Discussion"))
        tasks = QWidget()
        tl = QVBoxLayout(tasks)
        help_text = QLabel(
            self.tr(
                "Keep TorrentLinker open to run scheduled tasks. Missed intervals "
                "are combined into one run. Review interrupted runs before using "
                "Run now."
            )
        )
        help_text.setWordWrap(True)
        tl.addWidget(help_text)
        self.tasks = QListWidget()
        tl.addWidget(self.tasks)
        task_buttons = QHBoxLayout()
        for label, action in [
            (self.tr("Create task"), lambda: self.edit(True)),
            (self.tr("Edit"), self.edit_task),
            (self.tr("Pause / Enable"), self.toggle_task),
            (self.tr("Run now"), self.run_task),
        ]:
            b = QPushButton(label)
            b.clicked.connect(action)
            task_buttons.addWidget(b)
        tl.addLayout(task_buttons)
        self.pages.addTab(tasks, self.tr("Automations"))
        self.history = QTextBrowser()
        self.history.setOpenLinks(False)
        self.history.anchorClicked.connect(self.open_receipt)
        self.pages.addTab(self.history, self.tr("History"))
        connections = QWidget()
        pl = QVBoxLayout(connections)
        info = QLabel(
            self.tr(
                "Hosted providers receive messages and tool results. No automatic "
                "fallback to a hosted model. Limit: 200 calls per connection per "
                "UTC day."
            )
        )
        info.setWordWrap(True)
        pl.addWidget(info)
        self.providers = QListWidget()
        pl.addWidget(self.providers)
        row = QHBoxLayout()
        for label, action in [
            (self.tr("Add connection"), lambda: self.provider_editor()),
            (self.tr("Edit"), self.edit_provider),
            (self.tr("Test tools"), self.test_provider),
            (self.tr("Web research"), self.research_editor),
        ]:
            b = QPushButton(label)
            b.clicked.connect(action)
            row.addWidget(b)
        pl.addLayout(row)
        self.pages.addTab(connections, self.tr("Connections"))
        self.timer = QTimer(self)
        self.timer.setInterval(1500)
        self.timer.timeout.connect(self.refresh_run)
        self.timer.start()

    def activate(self):
        try:
            self.service = self.get_service()
            self.refresh()
        except Exception as error:
            self.notice.setText(str(error))

    def perform(self, action):
        try:
            if self.service:
                result = action()
                self.refresh()
                return result
        except Exception as error:
            QMessageBox.warning(self, self.tr("Assistant"), str(error))

    def refresh(self):
        if not self.service:
            return
        self.conversation_data = self.service.conversations()
        self.conversations.blockSignals(True)
        self.conversations.clear()
        for c in self.conversation_data:
            self.conversations.addItem(c["name"])
            if c["id"] == self.conversation_id:
                self.conversations.setCurrentRow(self.conversations.count() - 1)
        self.conversations.blockSignals(False)
        self.task_data = self.service.schedules()
        task_row = self.tasks.currentRow()
        self.tasks.clear()
        for t in self.task_data:
            date = (
                datetime.fromtimestamp(t["next_at"]).astimezone().strftime("%d/%m %H:%M")
                if t["enabled"]
                else self.tr("Paused")
            )
            self.tasks.addItem(
                f"{t['name']} · {date}" + (f"\n{t['last_error']}" if t["last_error"] else "")
            )
        self.tasks.setCurrentRow(task_row)
        self.provider_data = self.service.setup()["providers"]
        selected = self.providers.currentRow()
        self.providers.clear()
        for p in self.provider_data:
            self.providers.addItem(p["name"] + " · " + p["model"])
        self.providers.setCurrentRow(selected)
        self.render_key = ""
        self.refresh_run()

    def select_conversation(self, row):
        if 0 <= row < len(self.conversation_data):
            conversation = self.conversation_data[row]
            self.conversation_id = conversation["id"]
            policy = (
                self.tr("Proposals only")
                if conversation["policy"]["mode"] == "propose"
                else self.tr("Execute within limits")
            )
            profiles = {p.id: p.name for p in self.service.agent.setup.settings.client_profiles}
            names = [profiles.get(i, i) for i in conversation["policy"]["clients"]]
            self.notice.setText(conversation["name"] + " · " + policy + " · " + ", ".join(names))
            self.render_key = ""
            self.refresh_run()

    def edit(self, task, initial=None):
        if not self.service:
            self.activate()
        if self.service:
            editor = AssistantEditor(self.service, task=task, initial=initial, parent=self)
            if editor.exec():
                if not task:
                    self.conversation_id = editor.saved
                self.refresh()

    def edit_task(self):
        row = self.tasks.currentRow()
        if 0 <= row < len(self.task_data):
            self.edit(True, self.task_data[row])

    def toggle_task(self):
        row = self.tasks.currentRow()
        if 0 <= row < len(self.task_data):
            task = self.task_data[row]
            body = {k: v for k, v in task.items() if k in Schedule.model_fields}
            body["enabled"] = not task["enabled"]
            self.perform(lambda: self.service.save_schedule(Schedule(**body), task["id"]))

    def run_task(self):
        row = self.tasks.currentRow()
        if 0 <= row < len(self.task_data):
            self.perform(lambda: self.service.run_schedule(self.task_data[row]["id"]))
            self.pages.setCurrentIndex(2)

    def stop_run(self):
        if self.service and self.run_id:
            self.perform(lambda: self.service.cancel(self.run_id))

    def send_message(self):
        if self.conversation_id and self.prompt.toPlainText().strip():
            result = self.perform(
                lambda: self.service.start(self.conversation_id, self.prompt.toPlainText())
            )
            if result:
                self.run_id = result["id"]
                self.prompt.clear()

    def render_transcript(self, rows):
        parts = ["<style>p{line-height:1.6;}pre{white-space:pre-wrap;}a{color:#55bdb7;}</style>"]
        for run in reversed(rows):
            parts.append(
                "<p><small>"
                + html.escape(
                    self.status_text(run["status"])
                    + " · "
                    + self.tr("%1 calls · %2 tokens")
                    .replace("%1", str(run["calls"]))
                    .replace("%2", str(run["tokens"]))
                )
                + "</small></p>"
            )
            for m in run["messages"]:
                parts.append(
                    "<p><b>"
                    + html.escape(self.tr("You") if m["role"] == "user" else "Assistant")
                    + "</b></p><p>"
                    + html.escape(m["content"]).replace("\n", "<br>")
                    + "</p>"
                )
            if run["error"]:
                parts.append("<p>" + html.escape(run["error"]) + "</p>")
            for i, event in enumerate(run["events"]):
                parts.append(
                    f'<p><a href="receipt:{run["id"]}:{i}">'
                    + html.escape(event["tool"] + " · " + self.status_text(event["status"]))
                    + "</a></p>"
                )
                result = event.get("result", {})
                if result.get("requires_owner_approval"):
                    parts.append(
                        f'<p><a href="proposal:{result["id"]}">'
                        + html.escape(self.tr("Review proposal"))
                        + "</a></p>"
                    )
        return "".join(parts)

    def refresh_run(self):
        if not self.service or not self.isVisible():
            return
        rows = self.service.history(self.conversation_id) if self.conversation_id else []
        all_rows = self.service.history() if self.pages.currentIndex() == 2 else []
        key = json.dumps([rows, all_rows])
        if key == self.render_key:
            return
        self.render_key = key
        bar = self.transcript.verticalScrollBar()
        position, bottom = bar.value(), bar.value() >= bar.maximum() - 10
        self.transcript.setHtml(self.render_transcript(rows))
        bar.setValue(bar.maximum() if bottom else position)
        active = next((r for r in rows if r["status"] in {"queued", "running"}), None)
        self.send.setEnabled(not active and bool(self.conversation_id))
        self.run_id = active["id"] if active else self.run_id
        if all_rows:
            self.history.setHtml(self.render_transcript(all_rows))

    def open_receipt(self, url):
        try:
            parts = url.toString().split(":")
            if parts[0] == "proposal":
                run_in_background(
                    lambda: self.service.agent.review(parts[1]),
                    lambda review: self.review_dialog(parts[1], review),
                    self.error,
                )
                return
            event = self.service.run(parts[1])["events"][int(parts[2])]
            dialog = QDialog(self)
            dialog.resize(720, 520)
            layout = QVBoxLayout(dialog)
            text = QPlainTextEdit(json.dumps(event, indent=2, ensure_ascii=False))
            text.setReadOnly(True)
            layout.addWidget(text)
            result = event.get("result", {})
            if result.get("job_id"):
                progress = QPushButton(self.tr("Job progress"))
                progress.clicked.connect(
                    lambda: text.setPlainText(
                        json.dumps(
                            self.service.agent.jobs.get(result["job_id"]),
                            indent=2,
                            ensure_ascii=False,
                        )
                    )
                )
                layout.addWidget(progress)
            dialog.exec()
        except Exception as error:
            self.error(error)

    def review_dialog(self, identifier, review):
        dialog = QDialog(self)
        dialog.setWindowTitle(self.tr("Review proposal"))
        dialog.resize(720, 520)
        layout = QVBoxLayout(dialog)
        text = QPlainTextEdit(json.dumps(review, indent=2, ensure_ascii=False))
        text.setReadOnly(True)
        layout.addWidget(text)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        approve = buttons.addButton(
            self.tr("Approve this action"), QDialogButtonBox.ButtonRole.AcceptRole
        )
        reject = buttons.addButton(self.tr("Reject"), QDialogButtonBox.ButtonRole.DestructiveRole)
        approve.clicked.connect(
            lambda: run_in_background(
                lambda: self.service.agent.execute(identifier, approved=True),
                lambda _: dialog.accept(),
                self.error,
            )
        )

        def decline():
            self.service.agent.reject(identifier)
            dialog.accept()

        reject.clicked.connect(decline)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()

    def error(self, error):
        detail = self.service.secrets.redact(str(error)) if self.service else str(error)
        QMessageBox.warning(self, self.tr("Assistant"), detail)

    def edit_provider(self):
        row = self.providers.currentRow()
        if 0 <= row < len(self.provider_data):
            self.provider_editor(self.provider_data[row])

    def provider_editor(self, existing=None):
        if not self.service:
            return
        existing = existing or {}
        dialog = QDialog(self)
        dialog.setWindowTitle(self.tr("Model connection"))
        dialog.resize(600, 360)
        form = QFormLayout(dialog)
        name = QLineEdit(existing.get("name", ""))
        kind = QComboBox()
        kind.addItems(list(PRESETS))
        kind.setCurrentText(existing.get("kind", "ollama"))
        address = QLineEdit(existing.get("url", PRESETS["ollama"]))
        model = QComboBox()
        model.setEditable(True)
        model.setEditText(existing.get("model", ""))
        key = QLineEdit()
        key.setEchoMode(QLineEdit.EchoMode.Password)
        key.setPlaceholderText(self.tr("Leave blank to keep the saved key"))
        for label, widget in [
            (self.tr("Name"), name),
            (self.tr("Provider"), kind),
            (self.tr("Base URL"), address),
            (self.tr("Model ID"), model),
            (self.tr("API key"), key),
        ]:
            form.addRow(label, widget)
        kind.currentTextChanged.connect(lambda value: address.setText(PRESETS[value]))
        hint = QLabel(
            self.tr(
                "Use an address reachable by TorrentLinker. In Docker, localhost "
                "is the container. Changing the address clears the saved key "
                "unless you enter a new one."
            )
        )
        hint.setWordWrap(True)
        form.addRow(hint)
        fetch = QPushButton(self.tr("List models"))

        def discover():
            try:
                connection = Provider.model_validate(
                    dict(
                        name=name.text() or "Discovery",
                        kind=kind.currentText(),
                        url=address.text(),
                        model=model.currentText() or "discovery",
                    )
                )
                credential = key.text()
                if not credential and existing and connection.url == existing.get("url"):
                    credential = self.service.secrets.get("assistant:" + existing["id"])
                run_in_background(
                    lambda: self.service.models.models(connection, credential),
                    lambda values: model.addItems(values),
                    self.error,
                )
            except Exception as error:
                self.error(error)

        fetch.clicked.connect(discover)
        form.addRow(fetch)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        form.addRow(buttons)

        def save():
            try:
                p = Provider.model_validate(
                    dict(
                        name=name.text(),
                        kind=kind.currentText(),
                        url=address.text(),
                        model=model.currentText(),
                        api_key=key.text() or None,
                    )
                )
                self.service.save_provider(p, existing.get("id", ""))
                dialog.accept()
                self.refresh()
            except Exception as error:
                self.error(error)

        buttons.accepted.connect(save)
        buttons.rejected.connect(dialog.reject)
        dialog.exec()

    def test_provider(self):
        row = self.providers.currentRow()
        if 0 <= row < len(self.provider_data):
            identifier = self.provider_data[row]["id"]
            self.notice.setText(self.tr("Testing connection and tool round trip…"))
            run_in_background(
                lambda: self.service.test_provider(identifier),
                lambda result: self.notice.setText(result["message"]),
                self.error,
            )

    def research_editor(self):
        if not self.service:
            return
        current = self.service.research_settings()
        dialog = QDialog(self)
        dialog.setWindowTitle(self.tr("Web research"))
        form = QFormLayout(dialog)
        hint = QLabel(
            self.tr(
                "Use Brave Search or SearXNG for search. Page reading and book "
                "metadata need no search key. Film metadata uses your TMDb key."
            )
        )
        hint.setWordWrap(True)
        form.addRow(hint)
        url = QLineEdit(current.get("searxng_url", ""))
        key = QLineEdit()
        key.setEchoMode(QLineEdit.EchoMode.Password)
        key.setPlaceholderText(self.tr("Leave blank to keep the saved key"))
        form.addRow("SearXNG URL", url)
        form.addRow("Brave Search API key", key)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        form.addRow(buttons)
        buttons.rejected.connect(dialog.reject)

        def save():
            try:
                self.service.save_research(
                    SearchSettings(searxng_url=url.text(), brave_key=key.text() or None)
                )
                dialog.accept()
            except Exception as error:
                self.error(error)

        buttons.accepted.connect(save)
        dialog.exec()
