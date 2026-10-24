"""Loopback MCP server owned by the desktop process, sharing its settings and Store."""

from __future__ import annotations

import copy
import secrets
import socket
import threading
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from typing import Any

from torrentlinker.agent.coordination import coordinator
from torrentlinker.config import Settings
from torrentlinker.credentials import get_secret, set_secret
from torrentlinker.store import Store
from torrentlinker.torrent_management import safe_error
from torrentlinker.web.operations import Operations
from torrentlinker.web.security import ServerSecrets
from torrentlinker.web.setup import Setup


class KeyringSecrets(ServerSecrets):
    def __init__(self):
        self.lock = threading.Lock()
        self.files: dict[str, Path] = {}
        self.seen: set[str] = set()

    def get(self, name: str) -> str:
        value = get_secret(name)
        if value:
            with self.lock:
                self.seen.add(value)
        return value

    def update(self, values: dict[str, str]) -> None:
        for key, value in values.items():
            set_secret(key, value)
            if value:
                with self.lock:
                    self.seen.add(value)

    def redact(self, text: str, *, public_urls: bool = False) -> str:
        if not text:
            return text
        with self.lock:
            for value in self.seen:
                text = text.replace(value, "[secret]")
        if public_urls:
            from torrentlinker.assistant.privacy import safe_content

            return safe_content(text)
        return safe_error(ValueError(text))


class DesktopSetup(Setup):
    def __init__(self, settings: Settings, path: Path, store: Store):
        from torrentlinker.clients import connect

        self.path, self.settings, self.store = path, copy.deepcopy(settings), store
        self._root = None
        self.marker = path.parent / "desktop.ready"
        self.configured = True  # ordinary client errors surface through the job
        self.secrets = KeyringSecrets()
        self.connector = connect
        self.lock = threading.RLock()
        self._client = None
        self._indexer = None
        self.download_guard = None
        self.roots = ()

    def path_under_root(self, value: str, *, directory: bool = True) -> Path:
        roots = [f.path for f in self.settings.library_folders]
        for profile in self.settings.client_profiles:
            folders = profile.download_folders
            roots.extend(Path(p) for p in [folders.default, *folders.by_category.values()] if p)
        self.roots = tuple(p.resolve() for p in roots)
        return super().path_under_root(value, directory=directory)

    def verified_download_folder(self) -> Path:
        # Desktop uses the existing Path Mappings and may download into a new empty folder.
        # Remote mappings still require the web adapter's matching-file verification.
        if self.settings.path_mappings:
            return super().verified_download_folder()
        from urllib.parse import urlsplit

        from torrentlinker.config import CLIENT_FIELDS

        host = urlsplit(getattr(self.settings, CLIENT_FIELDS[self.settings.client]).host).hostname
        if host not in {"localhost", "127.0.0.1", "::1"}:
            return super().verified_download_folder()
        return self.path_under_root(self.settings.download_folders.default)


class DesktopOperations(Operations):
    def run(self, request, stop, progress):
        progress({"message": "Waiting for desktop operations to finish."})
        with coordinator.agent(stop):
            return super().run(request, stop, progress)


class DesktopServer:
    def __init__(self, settings: Settings, path: Path, store: Store, *, port: int = 8790):
        self.setup = DesktopSetup(settings, path, store)
        self.directory = path.parent
        self.server: Any = None
        self.thread: threading.Thread | None = None
        self.app: Any = None
        self.pending_settings = False
        self.port = port
        self.url = f"http://127.0.0.1:{port}/mcp/"

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        import uvicorn

        from torrentlinker.web.app import create_app

        listener = socket.socket()
        try:
            listener.bind(("127.0.0.1", self.port))
            listener.listen(128)
            self.url = f"http://127.0.0.1:{listener.getsockname()[1]}/mcp/"
            self.app = create_app(
                self.directory,
                password=secrets.token_urlsafe(32),
                service_override=self.setup,
                operation_factory=DesktopOperations,
                monitor_verifications=False,
            )
            # The Windows GUI executable has no stdout/stderr. Keep the desktop's
            # file logging instead of Uvicorn's console formatter and handlers.
            self.server = uvicorn.Server(
                uvicorn.Config(self.app, access_log=False, log_level="warning", log_config=None)
            )
        except Exception:
            listener.close()
            if self.app is not None:
                self.app.state.assistant.close()
                self.service.jobs.close()
                self.service.access.db.close()
                self.app = None
            raise
        server = self.server

        def run():
            try:
                server.run(sockets=[listener])
            finally:
                listener.close()

        self.thread = threading.Thread(target=run, daemon=True, name="desktop-mcp")
        self.thread.start()

    def reset(self, settings: Settings) -> None:
        if self.app is None:
            self.setup.settings = copy.deepcopy(settings)
            self.setup.store = self.setup.store.for_client(settings.active_client_id)
            return
        with self.service.jobs.lock:
            if self.service.jobs.active():
                raise ValueError("Wait for agent jobs before changing clients.")
            self.setup.settings = copy.deepcopy(settings)
            self.setup.store = self.setup.store.for_client(settings.active_client_id)
            self.setup._client = None
            self.setup._indexer = None
            self.app.state.reset_clients()

    def busy(self) -> bool:
        if self.app is None:
            return False
        if not self.service.jobs.lock.acquire(blocking=False):
            return True
        try:
            return self.service.jobs.active()
        finally:
            self.service.jobs.lock.release()

    @contextmanager
    def editing_settings(self):
        if not self.service.jobs.lock.acquire(blocking=False):
            raise ValueError("Wait for agent jobs before changing settings.")
        try:
            if self.service.jobs.active():
                raise ValueError("Wait for agent jobs before changing settings.")
            previous = self.service.suspended
            self.service.suspended = True
        finally:
            self.service.jobs.lock.release()
        try:
            yield
        finally:
            self.service.suspended = previous

    def sync(self, settings: Settings) -> None:
        """GUI-thread refresh after profile, folder or Plan preferences change."""
        if self.app is None or (self.setup.settings == settings and not self.pending_settings):
            return
        if not self.service.jobs.lock.acquire(blocking=False):
            return
        try:
            if self.service.suspended and not self.pending_settings:
                return
            if self.service.jobs.active():
                self.service.suspended = True
                self.pending_settings = True
                return
            self.reset(settings)
            if self.pending_settings:
                self.service.suspended = False
                self.pending_settings = False
        finally:
            self.service.jobs.lock.release()

    @property
    def service(self):
        if self.app is None:
            raise ValueError("Start Agent access first.")
        return self.app.state.agent_service

    def close(self) -> None:
        if self.server is not None:
            self.server.should_exit = True
        if self.app is not None:
            assistant = self.app.state.assistant
            assistant.shutdown.set()
            for stop in list(assistant.stops.values()):
                stop.set()
            for job in self.service.jobs.list():
                if job["status"] in {"queued", "running"}:
                    self.service.jobs.cancel(job["id"])
        if self.thread is not None:
            self.thread.join(timeout=3)


def agent_settings_change(fn):
    """Make the whole desktop settings transaction unavailable to agent submissions."""

    @wraps(fn)
    def guarded(window, *args, **kwargs):
        runtime = window.agent_runtime
        if runtime is None or runtime.app is None:
            return fn(window, *args, **kwargs)
        try:
            with runtime.editing_settings():
                return fn(window, *args, **kwargs)
        except ValueError as error:
            window.client_selector.blockSignals(True)
            window.client_selector.setCurrentIndex(
                window.client_selector.findData(window.settings.active_client_id)
            )
            window.client_selector.blockSignals(False)
            window.statusBar().showMessage(window.tr(str(error)))

    return guarded
