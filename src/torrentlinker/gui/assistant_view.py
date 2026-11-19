"""Desktop host for the approved shared Assistant discussion and history."""

import json
from pathlib import Path

from fastapi.encoders import jsonable_encoder
from PySide6.QtCore import QSettings, Signal, Slot

from torrentlinker.assistant.panel import AssistantPanelService
from torrentlinker.gui.community_view import BundledView, ViewBridge
from torrentlinker.gui.tasks import run_in_background


class AssistantBridge(ViewBridge):
    response = Signal(int, str)

    def __init__(self, panel):
        super().__init__()
        self.panel = panel

    @Slot(int, str, str)
    def requestAsync(self, identifier, path, payload):
        try:
            body = json.loads(payload)
            if path == "open-link":
                from urllib.parse import unquote, urlsplit

                from PySide6.QtCore import QUrl
                from PySide6.QtGui import QDesktopServices

                from torrentlinker.assistant.markdown import documentation_link

                url = body.get("url", "")
                if documentation_link(url):
                    from torrentlinker.gui.documentation import show_guide

                    parsed = urlsplit(url)
                    show_guide(
                        self.panel.window(),
                        parsed.path.removeprefix("/documentation/"),
                        unquote(parsed.fragment),
                    )
                elif (
                    QUrl(url).scheme() in {"http", "https"}
                    and QUrl(url).host()
                    and not QUrl(url).userInfo()
                ):
                    QDesktopServices.openUrl(QUrl(url))
                else:
                    raise ValueError("Unsupported link")
                self.response.emit(identifier, '{"data":null}')
                return
            if path == "connections":
                self.panel.connectionsRequested.emit()
                self.response.emit(identifier, '{"data":null}')
                return
            if path == "preferences":
                prefs = QSettings()
                if "sidebar_width" in body:
                    prefs.setValue(
                        "assistant/sidebar_width", max(180, min(420, int(body["sidebar_width"])))
                    )
                self.response.emit(
                    identifier,
                    json.dumps(
                        {
                            "data": {
                                "sidebar_width": int(prefs.value("assistant/sidebar_width", 240))
                            }
                        }
                    ),
                )
                return
            service = self.panel.get_service()
            self.panel.service = service

            def work():
                try:
                    return {
                        "data": jsonable_encoder(
                            AssistantPanelService(service).request(
                                path, body.get("body"), body.get("method", "GET")
                            )
                        )
                    }
                except Exception as error:
                    return {"error": service.secrets.redact(str(error))}

            run_in_background(
                work,
                lambda result: self.response.emit(identifier, json.dumps(result)),
                lambda error: self.response.emit(identifier, json.dumps({"error": str(error)})),
                coordinate=False,
            )
        except Exception as error:
            self.response.emit(identifier, json.dumps({"error": str(error)}))


class AssistantPanel(BundledView):
    connectionsRequested = Signal()

    def __init__(self, get_service, parent=None):
        self.get_service = get_service
        self.service = None
        self.revision = 0
        self.startup_error = ""
        super().__init__(
            AssistantBridge(self), Path(__file__).parents[1] / "web/static/assistant", "assistant"
        )
        if parent:
            self.setParent(parent)

    def activate(self):
        try:
            self.service = self.get_service()
            self.language = self.service.agent.setup.settings.language
            self.startup_error = ""
        except Exception as error:
            self.service = None
            self.startup_error = str(error)
        self.refresh()

    def refresh(self):
        self.revision += 1
        self.bridge.environment_value = json.dumps(
            {
                "mode": "desktop",
                "error": self.startup_error,
                "revision": self.revision,
                "language": self.language,
                "active": self.isVisible(),
                "theme": "dark" if self.palette().window().color().lightness() < 128 else "light",
            }
        )
        self.bridge.ready()

    def focus_composer(self):
        if self.web:
            self.web.page().runJavaScript("document.querySelector('#assistant-prompt')?.focus()")
