"""Desktop bridge for the bundled owner Settings editor."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError
from PySide6.QtCore import QCoreApplication, Signal, Slot
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QMessageBox, QVBoxLayout
from shiboken6 import isValid

from torrentlinker.gui.community_view import BundledView, ViewBridge
from torrentlinker.gui.tasks import run_in_background
from torrentlinker.settings_workspace import SettingsWorkspace


class SettingsBridge(ViewBridge):
    response = Signal(int, str)

    def __init__(self, view: SettingsView):
        super().__init__()
        self.view = view

    @Slot(int, str, str)
    def requestAsync(self, identifier: int, action: str, payload: str) -> None:
        view = self.view
        workspace = view.workspace
        view.pending += 1

        def done(value):
            view.pending -= 1
            if not isValid(self):
                return
            self.response.emit(identifier, json.dumps({"data": value}))
            if action in {"save", "clients"} or (
                action == "storage"
                and body.get("action")
                in {"save", "download", "mapping", "remove", "remove-mapping", "categories"}
            ):
                view.changed.emit()
                view.refresh()

        def failed(error):
            view.pending -= 1
            if isinstance(error, ValidationError):
                error = ValueError(
                    "Check Settings fields: "
                    + ", ".join(
                        ".".join(str(part) for part in row["loc"]) for row in error.errors()
                    )
                )
            if isValid(self):
                self.response.emit(
                    identifier, json.dumps({"error": workspace.setup.secrets.redact(str(error))})
                )

        try:
            body = json.loads(payload)
            if (
                not isinstance(body, dict)
                or body.pop("_client", None) != workspace.setup.settings.active_client_id
            ):
                raise ValueError("The target client changed. Reopen Settings.")
            if action == "section":
                view.section = str(body.get("section", "connections"))
                done(None)
                return
            if action == "select-client":
                root = workspace.setup._root or workspace.setup
                view.workspace = SettingsWorkspace(root.for_client(body["client_id"]))
                view.section = "connections"
                view.refresh()
                done(None)
                return
            if action == "diagnostics":
                view.diagnostics_requested.emit()
                done(None)
                return
            if action == "choose-folder":
                from torrentlinker.gui.settings_common import choose_directory

                path = choose_directory(
                    view,
                    QCoreApplication.translate("SettingsView", "Choose folder"),
                    body.get("path", ""),
                )
                done(path)
                return
            if action == "save-token":
                from PySide6.QtWidgets import QFileDialog

                path, _ = QFileDialog.getSaveFileName(
                    view,
                    QCoreApplication.translate("SettingsView", "Save token"),
                    "torrentlinker-token.txt",
                    "Text (*.txt)",
                )
                if path and body.get("token"):
                    from torrentlinker.web.security import atomic_private

                    atomic_private(Path(path), (str(body["token"]) + "\n").encode("utf-8"))
                done(None)
                return
            if action == "agents":
                from torrentlinker.agent.settings_panel import AgentSettingsService

                if view.agent_service is None:
                    raise ValueError("Agent access is unavailable.")
                service = view.agent_service()

                def work():
                    return AgentSettingsService(service, view.queue_approval).request(
                        body["path"], body.get("body"), body.get("method", "GET")
                    )
            elif action == "companion":
                if view.companion_action is None:
                    raise ValueError("Companion controls are unavailable.")
                done(view.companion_action(body))
                return
            elif action == "assistant":
                from torrentlinker.assistant.settings_panel import AssistantSettingsService

                if view.assistant_service is None:
                    raise ValueError("Assistant service is unavailable.")
                service = view.assistant_service()

                def work():
                    from fastapi.encoders import jsonable_encoder

                    return jsonable_encoder(
                        AssistantSettingsService(service).request(
                            body["path"], body.get("body"), body.get("method", "GET")
                        )
                    )
            elif action == "snapshot":
                work = workspace.snapshot
            elif action == "save":

                def work():
                    return workspace.save(body["group"], body["value"])
            elif action == "test-connection":

                def work():
                    return workspace.test_connection(body["group"], body.get("value", {}))
            elif action == "storage":

                def work():
                    value = body.get("value", {})
                    # An explicit owner edit may introduce a desktop folder. The
                    # candidate lasts only for validation of this request.
                    with workspace.setup.lock:
                        setup = workspace.setup
                        if hasattr(setup, "_folder_candidate") and value.get("local"):
                            setup._folder_candidate = Path(value["local"]).expanduser().resolve()
                        try:
                            return workspace.storage(body["action"], value)
                        finally:
                            if hasattr(setup, "_folder_candidate"):
                                setup._folder_candidate = None
            elif action == "clients":

                def work():
                    if view.agent_approvals:
                        raise ValueError(
                            "Close Settings to finish the queued Agent approvals first."
                        )
                    return workspace.clients(body["action"], body["value"])
            else:
                raise ValueError("Unknown Settings operation.")
            run_in_background(work, done, failed)
        except Exception as error:
            failed(error)


class SettingsView(BundledView):
    changed = Signal()
    diagnostics_requested = Signal()

    def __init__(
        self,
        workspace: SettingsWorkspace,
        *,
        section: str = "connections",
        assistant_service=None,
        companion_action=None,
        agent_service=None,
        agent_endpoint="",
    ):
        self.workspace = workspace
        self.pending = 0
        self.assistant_service = assistant_service
        self.companion_action = companion_action
        self.agent_service = agent_service
        self.agent_endpoint = agent_endpoint
        self.agent_approvals: list[str] = []
        self.section = section
        super().__init__(
            SettingsBridge(self),
            Path(__file__).parents[1] / "web" / "static" / "settings",
            "settings",
            workspace.setup.settings.language,
        )

    def queue_approval(self, identifier: str) -> dict:
        if identifier not in self.agent_approvals:
            self.agent_approvals.append(identifier)
        return {"queued": True}

    def refresh(self) -> None:
        self.language = self.workspace.setup.settings.language
        theme = self.workspace.setup.settings.theme
        if theme == "auto":
            theme = "dark" if self.palette().window().color().lightness() < 128 else "light"
        self.bridge.environment_value = json.dumps(
            {
                "mode": "desktop",
                "language": self.language,
                "theme": theme,
                "active": self.isVisible(),
                "client_id": self.workspace.setup.settings.active_client_id,
                "section": self.section,
                "agent_endpoint": self.agent_endpoint,
            }
        )
        self.bridge.ready()


class SettingsDialog(QDialog):
    """Desktop shell around the shared Settings document."""

    def __init__(self, owner, *, section="connections"):
        from torrentlinker.agent.desktop import DesktopSetup

        super().__init__(owner)
        dialog = self
        dialog.setWindowTitle(self.tr("Settings"))
        available = dialog.screen().availableGeometry()
        dialog.resize(min(1200, available.width() - 40), min(850, available.height() - 60))
        setup = DesktopSetup(owner.settings, owner.settings_path, owner.store)

        def service():
            assistant = owner.assistant_service()
            stack = getattr(owner, "_settings_stack", None)
            if stack is not None and not owner.agent_runtime.settings_edit_depth:
                stack.enter_context(owner.agent_runtime.editing_settings())
            if owner.agent_runtime.setup.settings != setup.settings:
                owner.agent_runtime.reset(setup.settings)
            view.agent_endpoint = owner.agent_runtime.url
            view.refresh()
            return assistant

        def agents():
            service()
            return owner.agent_runtime.service

        def companion(body):
            action = body.get("action")
            if action == "pair":
                owner.pair_companion()
            elif action == "disconnect":
                owner.disconnect_companion()
            elif action == "extension":
                owner.save_companion_extension()
            elif action == "downloads":
                owner.account_workspace.set_session_downloads(bool(body["enabled"]))
            elif action != "state":
                raise ValueError("Unknown Companion operation.")
            return owner.account_workspace.state()

        view = SettingsView(
            SettingsWorkspace(setup),
            section=section,
            assistant_service=service,
            agent_service=agents,
            companion_action=companion,
        )
        view.diagnostics_requested.connect(lambda: owner._export_diagnostics(dialog))
        self.view = view
        self.setup = setup
        self.agent_approvals = view.agent_approvals
        self.saved = False
        self.finished.connect(view.close)
        view.changed.connect(lambda: setattr(dialog, "saved", True))
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(0, 0, 0, 12)
        layout.addWidget(view)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

    def reject(self):
        if self.view.pending:
            QMessageBox.information(
                self,
                self.tr("Settings"),
                self.tr("Wait for the current Settings operation to finish."),
            )
            return
        super().reject()
