"""Native Assistant UI. Model/network work never runs on the Qt event thread."""

from __future__ import annotations

import html
import json
from datetime import datetime
from typing import Any

from PySide6.QtCore import Qt, QTimer, Signal
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
    QVBoxLayout,
    QWidget,
)

from torrentlinker.assistant.models import Conversation, Schedule
from torrentlinker.assistant.providers import PRESETS, Provider
from torrentlinker.assistant.research import SearchSettings
from torrentlinker.gui.chat_folders import ChatFolders
from torrentlinker.gui.chat_transcript import ChatTranscript
from torrentlinker.gui.request_details import JsonCode, RequestDetails
from torrentlinker.gui.tasks import run_in_background


class ChatPrompt(QPlainTextEdit):
    submitted = Signal()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (
            event.modifiers() & Qt.KeyboardModifier.ShiftModifier
        ):
            self.submitted.emit()
            event.accept()
        else:
            super().keyPressEvent(event)


class AssistantEditor(QDialog):
    def __init__(self, service, *, task=False, initial=None, defaults=False, parent=None):
        super().__init__(parent)
        self.service, self.task, self.defaults = service, task, defaults
        self.initial = initial or {}
        self.setWindowTitle(
            self.tr("Scheduled task")
            if task
            else self.tr("Chat defaults")
            if defaults
            else self.tr("Discussion settings")
        )
        self.resize(620, 700 if task else 440)
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
        if defaults:
            form.setRowVisible(self.name, False)
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
            ("queue", self.tr("Prepare and edit download queue")),
            ("downloads", self.tr("Start downloads")),
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
            af,
            self.tr("Model calls per run"),
            self.initial.get("max_calls", 12 if task else 0),
            1 if task else 0,
            40 if task else 200,
        )
        self.seconds = self.number(
            af,
            self.tr("Maximum duration, seconds"),
            self.initial.get("max_seconds", 300 if task else 0),
            10 if task else 0,
            1800,
        )
        if not task:
            self.calls.setSpecialValueText(self.tr("No limit"))
            self.seconds.setSpecialValueText(self.tr("No limit"))
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
            max_output_tokens=self.initial.get("max_output_tokens", 2048),
            max_calls=self.calls.value(),
            max_seconds=self.seconds.value(),
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
            if self.task:
                result = self.service.save_schedule(value, self.initial.get("id", ""))
            elif self.defaults:
                result = self.service.save_chat_defaults(value)
            else:
                result = self.service.update_conversation(self.initial["id"], value)
            self.saved = result.get("id", "")
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
            "awaiting_user": self.tr("Awaiting your answer"),
            "waiting_settings": self.tr("Waiting for settings to finish updating"),
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
        self.drafts = {}
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
        left.setMaximumWidth(280)
        ll = QVBoxLayout(left)
        new = QPushButton(self.tr("New discussion"))
        new.clicked.connect(self.new_discussion)
        ll.addWidget(new)
        delete = QPushButton(self.tr("Delete discussion"))
        delete.clicked.connect(self.delete_discussion)
        ll.addWidget(delete)
        self.conversations = ChatFolders()
        self.conversations.conversationSelected.connect(self.select_conversation)
        ll.addWidget(self.conversations)
        self.move_chat = QPushButton(self.tr("Move to folder…"))
        self.move_chat.clicked.connect(self.move_conversation)
        ll.addWidget(self.move_chat)
        splitter.addWidget(left)
        right = QWidget()
        rl = QVBoxLayout(right)
        self.transcript = ChatTranscript(
            presentation_page=lambda *a, **kw: self.service.presentation_page(*a, **kw),
            presentation_item=lambda *a, **kw: self.service.presentation_item(*a, **kw),
        )
        self.transcript.decisionSubmitted.connect(self.submit_decision)
        self.transcript.answerSubmitted.connect(self.submit_answer)
        self.transcript.anchorClicked.connect(self.open_receipt)
        rl.addWidget(self.transcript, 1)
        self.prompt = ChatPrompt()
        self.prompt.submitted.connect(self.send_message)
        self.prompt.setPlaceholderText(self.tr("Give a task or ask a question…"))
        self.prompt.setMaximumHeight(96)
        self.prompt.setMinimumHeight(72)
        self.prompt.setStyleSheet("QPlainTextEdit { border-radius: 12px; padding: 12px; }")
        self.prompt.setAccessibleName(self.tr("Message"))
        rl.addWidget(self.prompt)
        self.connect_model = QPushButton(self.tr("Connect a model"))
        self.connect_model.clicked.connect(lambda: self.pages.setCurrentIndex(3))
        rl.addWidget(self.connect_model)
        controls = QHBoxLayout()
        self.chat_model = QComboBox()
        self.chat_model.setAccessibleName(self.tr("Model connection"))
        self.chat_model.setMinimumWidth(120)
        self.chat_model.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.chat_model.activated.connect(self.change_chat_model)
        self.chat_model.setMaximumWidth(380)
        controls.addWidget(self.chat_model, 1)
        self.chat_settings = QPushButton(self.tr("Discussion settings"))
        self.chat_settings.clicked.connect(self.edit_chat_settings)
        controls.addWidget(self.chat_settings)
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
        self.history = ChatTranscript(
            presentation_page=lambda *a, **kw: self.service.presentation_page(*a, **kw),
            presentation_item=lambda *a, **kw: self.service.presentation_item(*a, **kw),
        )
        self.history.anchorClicked.connect(self.open_receipt)
        self.history.decisionSubmitted.connect(self.submit_decision)
        self.history.answerSubmitted.connect(self.submit_answer)
        self.pages.addTab(self.history, self.tr("History"))
        connections = QWidget()
        pl = QVBoxLayout(connections)
        info = QLabel(
            self.tr(
                "Hosted providers receive messages and tool results. No automatic "
                "fallback to a hosted model."
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
            (self.tr("Chat defaults"), lambda: self.edit_chat_settings(defaults=True)),
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
        self.conversations.set_rows(self.conversation_data, self.conversation_id)
        self.move_chat.setEnabled(bool(self.conversation_id))
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
            assessment = p.get("assessment")
            self.providers.item(self.providers.count() - 1).setToolTip(
                "\n".join(
                    f"{name}: {check['status']}. {check['reason']}"
                    for name, check in (assessment or {}).get("checks", {}).items()
                )
                or self.tr("Capabilities untested")
            )
        self.providers.setCurrentRow(selected)
        current = next((c for c in self.conversation_data if c["id"] == self.conversation_id), None)
        chosen = (
            current["provider_id"]
            if current
            else self.chat_model.currentData() or self.service.chat_defaults().provider_id
        )
        self.chat_model.blockSignals(True)
        self.chat_model.clear()
        for p in self.provider_data:
            self.chat_model.addItem(p["name"] + " · " + p["model"], p["id"])
        index = self.chat_model.findData(chosen)
        if index >= 0:
            self.chat_model.setCurrentIndex(index)
        self.chat_model.blockSignals(False)
        self.connect_model.setVisible(not self.provider_data)
        self.render_key = ""
        self.refresh_run()

    def change_chat_model(self):
        if self.service and self.conversation_id:
            body, _ = self.service.conversation(self.conversation_id)
            body.provider_id = self.chat_model.currentData() or ""
            self.perform(lambda: self.service.update_conversation(self.conversation_id, body))
            self.refresh()

    def edit_chat_settings(self, *, defaults=False):
        if not self.service:
            return
        defaults = defaults or not self.conversation_id
        if defaults:
            initial = self.service.chat_defaults().model_dump()
            initial["provider_id"] = self.chat_model.currentData() or initial["provider_id"]
        else:
            body, _ = self.service.conversation(self.conversation_id)
            initial = {"id": self.conversation_id, **body.model_dump()}
        editor = AssistantEditor(self.service, initial=initial, defaults=defaults, parent=self)
        if editor.exec():
            if defaults and not self.conversation_id:
                self.chat_model.setCurrentIndex(
                    self.chat_model.findData(editor.provider.currentData())
                )
            self.refresh()

    def delete_discussion(self):
        if not self.service or not self.conversation_id:
            return
        if (
            QMessageBox.question(
                self,
                self.tr("Delete discussion"),
                self.tr(
                    "Delete this discussion and its history? Pending proposals will be rejected. "
                    "Torrents and files will not be removed."
                ),
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        try:
            identifier = self.conversation_id
            self.service.delete_conversation(identifier)
            self.new_discussion()
            self.drafts.pop(identifier, None)
            self.refresh()
        except Exception as error:
            self.error(error)

    def move_conversation(self):
        if not self.service or not self.conversation_id:
            return
        current = next(c for c in self.conversation_data if c["id"] == self.conversation_id)
        dialog = QDialog(self)
        dialog.setWindowTitle(self.tr("Move to folder…"))
        layout = QFormLayout(dialog)
        folder = QComboBox()
        folder.setEditable(True)
        folder.lineEdit().setMaxLength(80)
        choices = dict.fromkeys(
            ["", "uploads", "film_research", "series_research", "troubleshooting"]
            + [c.get("folder", "") for c in self.conversation_data]
        )
        for value in choices:
            folder.addItem(self.conversations.folder_label(value), value)
        folder.setCurrentIndex(folder.findData(current.get("folder", "")))
        layout.addRow(self.tr("Folder"), folder)
        automatic = QCheckBox(self.tr("Let the assistant organize this conversation"))
        automatic.setChecked(current.get("folder_source", "auto") == "auto")
        # Choosing a folder manually pins it; opting back in permits future classification.
        folder.editTextChanged.connect(lambda _: automatic.setChecked(False))
        layout.addRow(automatic)
        actions = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        actions.accepted.connect(dialog.accept)
        actions.rejected.connect(dialog.reject)
        layout.addRow(actions)
        if dialog.exec():
            index = folder.currentIndex()
            value = (
                folder.itemData(index)
                if index >= 0 and folder.itemText(index) == folder.currentText()
                else folder.currentText().strip()
            )
            self.perform(
                lambda: self.service.move_conversation(
                    self.conversation_id, value, automatic=automatic.isChecked()
                )
            )

    def new_discussion(self):
        self.drafts[self.conversation_id] = self.prompt.toPlainText()
        self.drafts.pop("", None)
        self.conversation_id = ""
        self.run_id = ""
        self.prompt.clear()
        self.conversations.select_id("")
        self.move_chat.setEnabled(False)
        self.chat_model.setCurrentIndex(
            self.chat_model.findData(self.service.chat_defaults().provider_id)
        )
        self.notice.setText(self.tr("New discussion"))
        self.render_key = ""
        self.refresh_run()
        self.prompt.setFocus()

    def select_conversation(self, identifier):
        conversation = next((c for c in self.conversation_data if c["id"] == identifier), None)
        if conversation:
            self.drafts[self.conversation_id] = self.prompt.toPlainText()
            self.conversation_id = conversation["id"]
            self.move_chat.setEnabled(True)
            self.chat_model.setCurrentIndex(self.chat_model.findData(conversation["provider_id"]))
            self.prompt.setPlainText(self.drafts.get(self.conversation_id, ""))
            self.run_id = ""
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
        message = self.prompt.toPlainText().strip()
        if not self.service or not self.send.isEnabled() or not message:
            return

        def submit():
            if not self.conversation_id:
                body = self.service.chat_defaults()
                body.provider_id = self.chat_model.currentData() or ""
                body.name = "Discussion"
                self.conversation_id = self.service.create_conversation(body)["id"]
            return self.service.start(self.conversation_id, message)

        result = self.perform(submit)
        if result:
            self.run_id = result["id"]
            self.drafts.pop(self.conversation_id, None)
            self.drafts.pop("", None)
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
        self.conversation_data = self.service.conversations()
        self.conversations.set_rows(self.conversation_data, self.conversation_id)
        rows = self.service.history(self.conversation_id) if self.conversation_id else []
        all_rows = self.service.history() if self.pages.currentIndex() == 2 else []
        key = json.dumps([rows, all_rows])
        if key == self.render_key:
            return
        self.render_key = key
        bar = self.transcript.verticalScrollBar()
        position, bottom = bar.value(), bar.value() >= bar.maximum() - 10
        self.transcript.follow_bottom = bottom
        self.transcript.set_runs(rows, self.status_text)

        def restore_scroll():
            if self.render_key == key:
                bar.setValue(bar.maximum() if bottom else position)

        QTimer.singleShot(0, self, restore_scroll)
        active = next(
            (
                r
                for r in rows
                if r["status"]
                in {"queued", "running", "awaiting_approval", "awaiting_user", "waiting_settings"}
            ),
            None,
        )
        self.send.setEnabled(not active and bool(self.chat_model.currentData()))
        self.chat_model.setEnabled(not active)
        self.chat_settings.setEnabled(not active and bool(self.provider_data))
        body = (
            self.service.conversation(self.conversation_id)[0]
            if self.conversation_id
            else self.service.chat_defaults()
        )
        self.notice.setText(
            self.tr("Proposals only")
            if body.policy.mode == "propose"
            else self.tr("Execute within limits")
        )
        self.run_id = active["id"] if active else self.run_id
        if all_rows:
            self.history.set_runs(all_rows, self.status_text)

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
            text = JsonCode(event)
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

    def submit_decision(self, run, index, approve):
        run_in_background(
            lambda: self.service.decide(run, index, approve),
            lambda _: self.refresh_run(),
            self.error,
        )

    def submit_answer(self, run, index, answer):
        run_in_background(
            lambda: self.service.answer(run, index, answer),
            lambda _: self.refresh_run(),
            self.error,
        )

    def review_dialog(self, identifier, review):
        dialog = QDialog(self)
        dialog.setWindowTitle(self.tr("Review proposal"))
        dialog.resize(720, 520)
        layout = QVBoxLayout(dialog)
        layout.addWidget(RequestDetails({"review": review}))
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
        context_window = QSpinBox()
        context_window.setRange(512, 2000000)
        context_window.setValue(existing.get("context_window", 32768))
        context_auto = QCheckBox(self.tr("Detect context automatically"))
        context_auto.setChecked(existing.get("context_auto", True))
        key = QLineEdit()
        key.setEchoMode(QLineEdit.EchoMode.Password)
        key.setPlaceholderText(self.tr("Leave blank to keep the saved key"))
        for label, widget in [
            (self.tr("Name"), name),
            (self.tr("Provider"), kind),
            (self.tr("Base URL"), address),
            (self.tr("Model ID"), model),
            ("", context_auto),
            (self.tr("Context window (tokens)"), context_window),
            (self.tr("API key"), key),
        ]:
            form.addRow(label, widget)
        context_hint = QLabel(
            self.tr(
                "Automatic detection runs before each task. The value above is used "
                "when the server does not report its limit. Disable detection to use it manually."
            )
        )
        context_hint.setWordWrap(True)
        form.addRow(context_hint)
        context_status = QLabel()
        context_status.setWordWrap(True)
        form.addRow(context_status)
        check_context = QPushButton(self.tr("Check context"))
        form.addRow(check_context)

        def context_selection():
            return (
                kind.currentText(),
                address.text(),
                model.currentText(),
                context_auto.isChecked(),
                context_window.value(),
                key.text(),
            )

        def check():
            try:
                selection = context_selection()
                connection = Provider(
                    name=name.text() or "Discovery",
                    kind=selection[0],
                    url=selection[1],
                    model=selection[2],
                    context_auto=selection[3],
                    context_window=selection[4],
                    api_key=selection[5] or None,
                )
                check_context.setEnabled(False)
                context_status.setText(self.tr("Checking server context…"))

                def done(result):
                    from shiboken6 import isValid

                    if not isValid(dialog) or not dialog.isVisible():
                        return
                    check_context.setEnabled(True)
                    if context_selection() != selection:
                        return
                    label = {
                        "server": self.tr("Server context: %1 tokens"),
                        "provider": self.tr("Provider context: %1 tokens"),
                        "fallback": self.tr("Not reported. Fallback: %1 tokens"),
                        "manual": self.tr("Manual context: %1 tokens"),
                    }[result["source"]]
                    context_status.setText(label.replace("%1", str(result["context_window"])))

                def failed(error):
                    from shiboken6 import isValid

                    if isValid(dialog) and dialog.isVisible():
                        check_context.setEnabled(True)
                        self.error(error)

                run_in_background(
                    lambda: self.service.context_preview(connection, existing.get("id", "")),
                    done,
                    failed,
                )
            except Exception as error:
                self.error(error)

        check_context.clicked.connect(check)
        for field in (address, key):
            field.textChanged.connect(context_status.clear)
        model.currentTextChanged.connect(context_status.clear)
        context_auto.toggled.connect(context_status.clear)
        context_window.valueChanged.connect(context_status.clear)
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
                        context_window=context_window.value(),
                        context_auto=context_auto.isChecked(),
                    )
                )
                saved = self.service.save_provider(p, existing.get("id", ""))
                dialog.accept()
                self.refresh()
                if not existing or any(
                    existing.get(k) != getattr(p, k) for k in ("kind", "url", "model")
                ):
                    self.notice.setText(self.tr("Assessing model capabilities…"))
                    run_in_background(
                        lambda: self.service.test_provider(saved["id"]),
                        lambda result: self.notice.setText(
                            "\n".join(
                                f"{name}: {check['status']}. {check['reason']}"
                                for name, check in result["checks"].items()
                            )
                        ),
                        self.error,
                    )
            except Exception as error:
                self.error(error)

        buttons.accepted.connect(save)
        buttons.rejected.connect(dialog.reject)
        dialog.exec()

    def test_provider(self):
        row = self.providers.currentRow()
        if 0 <= row < len(self.provider_data):
            identifier = self.provider_data[row]["id"]
            self.notice.setText(self.tr("Assessing model capabilities…"))
            run_in_background(
                lambda: self.service.test_provider(identifier),
                lambda result: self.notice.setText(
                    "\n".join(
                        f"{name}: {check['status']}. {check['reason']}"
                        for name, check in result.get("checks", {}).items()
                    )
                ),
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
