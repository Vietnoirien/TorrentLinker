"""Desktop host for the shared owner Torrents panel."""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QSettings, Signal, Slot

from torrentlinker.gui.community_view import BundledView, ViewBridge
from torrentlinker.gui.tasks import run_in_background
from torrentlinker.torrent_management import safe_error


class TorrentBridge(ViewBridge):
    response = Signal(int, str)

    def __init__(self, board):
        super().__init__()
        self.board = board

    @Slot(int, str, str)
    def requestAsync(self, identifier, action, payload):
        try:
            body = json.loads(payload)
            if body.pop("_client", None) != self.board.owner.settings.active_client_id:
                raise ValueError("The target client changed. Reopen Torrents.")
            if action == "transfer-browse":
                from PySide6.QtWidgets import QFileDialog

                folder = QFileDialog.getExistingDirectory(
                    self.board, "Destination", body.get("path", "")
                )
                self.response.emit(identifier, json.dumps({"data": {"selected": folder}}))
                return
            if action == "preferences":
                settings = QSettings()
                for key in ("columns", "widths"):
                    if key in body:
                        settings.setValue("torrents/shared-" + key, json.dumps(body[key]))
                result = {}
                for key in ("columns", "widths"):
                    try:
                        result[key] = json.loads(settings.value("torrents/shared-" + key, "{}"))
                    except (ValueError, TypeError):
                        result[key] = {}
                self.response.emit(identifier, json.dumps({"data": result}))
                return
            service = self.board.service()

            def work():
                try:
                    return {"data": service.request(action, body)}
                except Exception as error:
                    return {"error": safe_error(error)}

            run_in_background(
                work,
                lambda result: self.response.emit(
                    identifier, json.dumps(result, ensure_ascii=False)
                ),
                lambda error: self.response.emit(
                    identifier, json.dumps({"error": safe_error(error)})
                ),
                # DesktopOperations coordinates refresh itself. Nesting a desktop
                # worker around it would wait for that very worker to finish.
                coordinate=False,
            )
        except Exception as error:
            self.response.emit(identifier, json.dumps({"error": safe_error(error)}))


class TorrentsTab(BundledView):
    def __init__(self, owner, service=None):
        self.owner = owner
        self.service = service or (lambda: owner.assistant_service().agent.torrents_workspace)
        self.command = None
        self.sequence = 0
        super().__init__(
            TorrentBridge(self), Path(__file__).parents[1] / "web/static/torrents", "torrents"
        )

    def refresh(self):
        settings = self.owner.settings
        self.language = settings.language
        self.bridge.environment_value = json.dumps(
            {
                "mode": "desktop",
                "language": self.language,
                "client": settings.active_client_id,
                "active": self.isVisible(),
                "command": self.command,
                "theme": "dark" if self.palette().window().color().lightness() < 128 else "light",
            }
        )
        self.bridge.ready()

    def reset_connection(self):
        self.refresh()

    def focus_torrent(self, hash=""):
        self.sequence += 1
        self.command = {"id": self.sequence, "hash": hash}
        self.refresh()
