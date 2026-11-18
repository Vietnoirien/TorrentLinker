"""Desktop Search host. Search and queue rendering live in the shared panel."""

from __future__ import annotations

import copy
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QSettings, Signal, Slot
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QFileDialog, QVBoxLayout, QWidget

from torrentlinker.agent.desktop import DesktopOperations, DesktopSetup
from torrentlinker.gui.browser_tabs import BrowserTabs
from torrentlinker.gui.community_view import BundledView, ViewBridge
from torrentlinker.search_workspace import SearchWorkspace
from torrentlinker.torrent_management import safe_error
from torrentlinker.web.jobs import Jobs


class SearchSetup(DesktopSetup):
    def save(self):
        # Folder edits are merged into the live settings on the GUI thread.
        # Writing this worker's snapshot could overwrite a later client switch.
        pass


class SearchBridge(ViewBridge):
    response = Signal(int, str)
    finished = Signal(int, object, object)

    def __init__(self, board):
        super().__init__()
        self.board = board
        self.finished.connect(self.completed)

    @Slot(int, object, object)
    def completed(self, identifier, service, result):
        changed = bool(service.setup.download_folder_changes)
        service.setup.apply_download_folder_changes(self.board.owner.settings)
        if changed:
            self.board.owner.settings.save(self.board.owner.settings_path)
        self.response.emit(identifier, json.dumps(result, ensure_ascii=False))

    @Slot(int, str, str)
    def requestAsync(self, identifier, action, payload):
        board = self.board

        def done(value):
            self.response.emit(identifier, json.dumps({"data": value}, ensure_ascii=False))

        def failed(error):
            self.response.emit(identifier, json.dumps({"error": safe_error(error)}))

        try:
            body = json.loads(payload)
            if body.pop("_client", None) != board.owner.settings.active_client_id:
                raise ValueError("The target client changed. Reopen Search.")
            if action == "preferences":
                settings = QSettings()
                if body.get("tl-search-density") in {"comfortable", "compact"}:
                    settings.setValue("search/density", body["tl-search-density"])
                if body.get("tl-search-posters") in {"0", "1"}:
                    settings.setValue("search/posters", body["tl-search-posters"] == "1")
                done(
                    {
                        "tl-search-density": settings.value("search/density", "comfortable"),
                        "tl-search-posters": "1"
                        if settings.value("search/posters", True, bool)
                        else "0",
                    }
                )
            elif action == "pick":
                done(
                    {
                        "selected": QFileDialog.getExistingDirectory(
                            board, QCoreApplication.translate("SearchTab", "Choose a folder")
                        )
                    }
                )
            elif action == "navigate":
                if body.get("page") not in {"search", "queue"}:
                    raise ValueError("Unknown Search page.")
                board.page = body["page"]
                board.refresh()
                done({"ok": True})
            elif action == "details":
                board.tab.open_details(body["row"])
                done({"ok": True})
            elif action == "subscribe":
                board.tab.subscribe_requested.emit(body.get("query", ""))
                done({"ok": True})
            elif action == "torrents":
                board.tab.manage_requested.emit(body.get("hashes", []))
                done({"ok": True})
            else:
                service = board.service()

                def work():
                    try:
                        result = {"data": service.request(action, body)}
                    except Exception as error:
                        result = {"error": safe_error(error)}
                    self.finished.emit(identifier, service, result)

                board.requests.submit(work)
        except Exception as error:
            failed(error)


class SearchBoard(BundledView):
    def __init__(self, tab, owner):
        self.tab, self.owner = tab, owner
        self.services = {}
        self.page = "search"
        self.jobs = None
        self.requests = ThreadPoolExecutor(max_workers=4, thread_name_prefix="search-panel")
        super().__init__(
            SearchBridge(self),
            Path(__file__).parents[1] / "web/static/search",
            "search",
            owner.settings.language,
        )

    def service(self):
        if self.jobs is None:
            directory = self.owner.settings_path.parent / "search-jobs"
            directory.mkdir(parents=True, exist_ok=True)
            self.jobs = Jobs(directory, error_message=safe_error)
        client = self.owner.settings.active_client_id
        if client not in self.services:
            setup = SearchSetup(
                self.owner.settings, self.owner.settings_path, self.owner.store.for_client(client)
            )
            self.services[client] = SearchWorkspace(DesktopOperations(setup), self.jobs)
        service = self.services[client]
        # Never replace the settings used by an in-flight job.
        if not self.jobs.active() and service.setup.settings != self.owner.settings:
            service.setup.settings = copy.deepcopy(self.owner.settings)
            service.setup._client = None
            service.setup._indexer = None
        return service

    def refresh(self):
        self.bridge.environment_value = json.dumps(
            {
                "mode": "desktop",
                "language": self.language,
                "client": self.owner.settings.active_client_id,
                "active": self.isVisible(),
                "page": self.page,
                "theme": "dark" if self.palette().window().color().lightness() < 128 else "light",
            }
        )
        self.bridge.ready()


class SearchTab(QWidget):
    subscribe_requested = Signal(str)
    manage_requested = Signal(list)

    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.setProperty("ownsScrolling", True)
        self.board = SearchBoard(self, owner)
        self.browser = BrowserTabs(self.board)
        self.browser.close_requested.connect(self.close_detail)
        self.detail_tabs = {}
        for text, now in (("Queue all tabs", False), ("Download all tabs", True)):
            action = QAction(self.tr(text), self)
            action.triggered.connect(lambda checked=False, now=now: self.queue_tabs(now))
            self.browser.extra_actions.append(action)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.browser)

    def focus_search(self):
        self.show_results()
        if self.board.web:
            self.board.web.page().runJavaScript("document.getElementById('search-query').focus()")

    def show_results(self):
        self.board.page = "search"
        self.browser.setCurrentWidget(self.board)
        self.board.refresh()

    def show_queue(self):
        self.board.page = "queue"
        self.browser.setCurrentWidget(self.board)
        self.board.refresh()

    def set_seeding(self, view):
        self.board.service().operations.observed = [row.torrent for row in view.rows]
        self.board.refresh()

    def refresh_categories(self):
        self.board.refresh()

    def refresh_estimates(self):
        self.board.refresh()

    def open_details(self, row):
        from torrentlinker.gui.torrent_details import TorrentDetailsDialog
        from torrentlinker.indexer import Candidate

        service = self.board.service()
        infohash = str(row["hash"])
        key = (self.owner.settings.active_client_id, infohash)
        if key in self.detail_tabs:
            self.browser.setCurrentWidget(self.detail_tabs[key])
            return
        candidate = service.operations.candidates.get(infohash)
        if candidate is None:
            records = service.setup.store.catalogue([infohash])
            if not records:
                raise ValueError("Search again before opening this torrent.")
            record = records[0]
            candidate = Candidate(
                record.title,
                record.size,
                record.download_url,
                record.seeders,
                infohash,
                categories=(record.category,) if record.category else (),
            )

        def download(_folder, now):
            if key[0] != self.owner.settings.active_client_id:
                raise ValueError("The target client changed. Reopen Search.")
            self.show_results()
            if self.board.web:
                self.board.web.page().runJavaScript(
                    "guard(()=>searchEnqueue("
                    + json.dumps([infohash])
                    + ","
                    + json.dumps(now)
                    + "))"
                )
            return self.tr("The torrent will be queued using its configured category folder.")

        page = TorrentDetailsDialog(
            candidate,
            service.setup.indexer(),
            str(row.get("zen", "–")),
            "",
            self,
            download=download,
            embedded=True,
            torrent_note=str(row.get("note", "–")),
        )
        page.close_requested.connect(lambda: self.close_detail(page))
        self.detail_tabs[key] = page
        self.browser.add_preview(page, candidate.title)
        self.browser.setCurrentWidget(page)

    def queue_tabs(self, now=False):
        hashes = [
            key[1] for key in self.detail_tabs if key[0] == self.owner.settings.active_client_id
        ]
        if not hashes:
            return
        self.show_results()
        if self.board.web:
            self.board.web.page().runJavaScript(
                "guard(()=>searchEnqueue(" + json.dumps(hashes) + "," + json.dumps(now) + "))"
            )

    def close_detail(self, page):
        self.detail_tabs = {
            key: value for key, value in self.detail_tabs.items() if value is not page
        }
        self.browser.removeTab(self.browser.indexOf(page))
        page.dispose()

    def stop(self):
        self.board.requests.shutdown(wait=True, cancel_futures=True)
        if self.board.jobs is not None:
            self.board.jobs.close()
            self.board.jobs = None
        for page in list(self.detail_tabs.values()):
            self.close_detail(page)
