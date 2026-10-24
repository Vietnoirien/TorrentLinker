"""Authenticated HTTP adapter for the headless application."""

from __future__ import annotations

import threading
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from torrentlinker.clients import connect
from torrentlinker.web.confirmations import Confirmations
from torrentlinker.web.jobs import Jobs
from torrentlinker.web.operations import JobRequest, Operations
from torrentlinker.web.security import ServerSecrets, Sessions
from torrentlinker.web.setup import (
    Connection,
    Connector,
    FolderSetup,
    IndexerConnection,
    ProxySetup,
    Setup,
)


class Announce(BaseModel):
    value: str = Field(max_length=4096)


class Login(BaseModel):
    password: str = Field(max_length=1024)


def create_app(
    directory: Path,
    *,
    password: str,
    roots: tuple[Path, ...] = (),
    connector: Connector = connect,
    secret_files: dict[str, Path] | None = None,
    secure_cookie: bool = False,
) -> FastAPI:
    directory.mkdir(parents=True, exist_ok=True)
    sessions = Sessions(password)
    service = Setup(directory, roots, ServerSecrets(directory, secret_files), connector)

    def error_message(error: Exception) -> str:
        if isinstance(error, ValueError):
            return service.secrets.redact(str(error))
        kind = type(error).__name__.lower()
        if "timeout" in kind or "connection" in kind or "connect" in kind:
            return (
                "Cannot reach the service from this server. Check its address, "
                "port, network and proxy settings."
            )
        if any(word in kind for word in ("login", "forbidden", "unauthorized", "keyrefused")):
            return (
                "The service refused authentication. Check the username, password "
                "or API key permissions."
            )
        return (
            "Operation failed. Check the connection, folder permissions and "
            "available space before retrying."
        )

    jobs = Jobs(directory, error_message)
    operations = Operations(service)
    confirmations = Confirmations(service)

    shutdown = threading.Event()

    def verify_loop() -> None:
        while not shutdown.wait(10):
            with jobs.lock:
                if service.configured and not jobs.active() and service.store.verification_hashes():
                    jobs.submit(
                        "verify",
                        lambda stop, progress: operations.run(
                            JobRequest(kind="verify"), stop, progress
                        ),
                    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        monitor = threading.Thread(target=verify_loop, daemon=True, name="verification-monitor")
        monitor.start()
        try:
            yield
        finally:
            shutdown.set()
            monitor.join(timeout=2)
            jobs.close()

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)

    def idle() -> None:
        if jobs.active():
            raise HTTPException(409, "Wait for active jobs before changing settings.")

    @app.middleware("http")
    async def protect(request: Request, call_next):  # type: ignore[no-untyped-def]
        # ASGI root_path may prefix the URL behind a reverse proxy.
        route = request.scope.get("path", request.url.path)
        prefix = request.scope.get("root_path", "")
        if prefix and route.startswith(prefix + "/"):
            route = route[len(prefix) :]
        if route.startswith("/api/"):
            length = request.headers.get("content-length", "0")
            if not length.isdigit() or int(length) > 256_000:
                return JSONResponse({"detail": "Request too large."}, status_code=413)
            if request.method != "GET" and request.headers.get("X-TorrentLinker") != "1":
                return JSONResponse({"detail": "Browser request header required."}, status_code=403)
            if route != "/api/login" and not sessions.valid(request.cookies.get("tl_session", "")):
                return JSONResponse({"detail": "Sign in to TorrentLinker."}, status_code=401)
        try:
            response = await call_next(request)
        except Exception as error:
            # Do not let ASGI log a raw HTTP exception containing private URLs.
            response = JSONResponse({"detail": error_message(error)}, status_code=502)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid(request: Request, error: RequestValidationError) -> JSONResponse:
        # Pydantic's default response echoes inputs, including passwords.
        return JSONResponse(
            {"detail": "Invalid input. Check the required fields and their values."},
            status_code=422,
        )

    @app.post("/api/login")
    def login(body: Login) -> JSONResponse:
        try:
            token = sessions.login(body.password)
        except PermissionError as error:
            return JSONResponse({"detail": str(error)}, status_code=401)
        except ValueError as error:
            return JSONResponse({"detail": str(error)}, status_code=429)
        response = JSONResponse({"ok": True})
        response.set_cookie(
            "tl_session",
            token,
            httponly=True,
            samesite="strict",
            max_age=43200,
            secure=secure_cookie,
        )
        return response

    @app.post("/api/logout")
    def logout(request: Request) -> JSONResponse:
        sessions.logout(request.cookies.get("tl_session", ""))
        response = JSONResponse({"ok": True})
        response.delete_cookie("tl_session")
        return response

    @app.get("/api/setup")
    def setup() -> dict:
        return service.snapshot()

    @app.exception_handler(ValueError)
    async def bad_input(request: Request, error: ValueError) -> JSONResponse:
        return JSONResponse({"detail": error_message(error)}, status_code=400)

    @app.exception_handler(Exception)
    async def failed(request: Request, error: Exception) -> JSONResponse:
        # Adapter exceptions can contain private URLs and passwords.
        return JSONResponse(
            {
                "detail": error_message(error),
                "kind": type(error).__name__,
            },
            status_code=502,
        )

    @app.post("/api/setup/test-client")
    def test_client(body: Connection) -> dict:
        return service.test_client(body)

    @app.post("/api/setup/client")
    def save_client(body: Connection) -> dict:
        nonlocal operations
        with jobs.lock:
            idle()
            saved = service.test_client(body, save=True)
            operations = Operations(service)
            return saved

    @app.post("/api/setup/test-indexer")
    def test_indexer(body: IndexerConnection) -> dict:
        return service.test_indexer(body)

    @app.post("/api/setup/indexer")
    def save_indexer(body: IndexerConnection) -> dict:
        with jobs.lock:
            idle()
            return service.test_indexer(body, save=True)

    @app.get("/api/folders")
    def folders(path: str = "") -> dict:
        return service.browse(path)

    @app.post("/api/setup/test-folder")
    def test_folder(body: FolderSetup) -> dict:
        return service.folder(body)

    @app.post("/api/setup/folder")
    def save_folder(body: FolderSetup) -> dict:
        with jobs.lock:
            idle()
            return service.folder(body, save=True)

    @app.post("/api/setup/suggest-mappings")
    def suggest_mappings() -> dict:
        with jobs.lock:
            idle()
            return service.suggest_mappings()

    @app.post("/api/setup/proxy")
    def save_proxy(body: ProxySetup) -> dict:
        with jobs.lock:
            idle()
            return service.proxy(body)

    @app.post("/api/setup/announce")
    def save_announce(body: Announce) -> dict:
        parsed = urlsplit(body.value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
        ):
            raise HTTPException(400, "Use the private Announce URL supplied by c411.")
        with jobs.lock:
            idle()
            service.secrets.update({"announce-url": body.value})
        return {"ok": True}

    @app.get("/api/upload/categories")
    def upload_categories() -> list:
        from torrentlinker.upload import PROFILES, category_name

        return [{"id": cid, "name": category_name(cid)} for cid in PROFILES]

    @app.get("/api/library")
    def library(
        q: str = "", offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=200)
    ) -> dict:
        rows = [r for r in operations.library.rows() if q.casefold() in r["name"].casefold()]
        return {"rows": rows[offset : offset + limit], "total": len(rows)}

    @app.get("/api/queue")
    def queue() -> list:
        return operations.queue()

    @app.post("/api/queue/remove")
    def remove_queue(keys: list[str]) -> dict:
        with jobs.lock:
            idle()
            service.store.remove_downloads(keys[:1000])
        return {"ok": True}

    @app.get("/api/torrents")
    def torrents(
        q: str = "",
        sort: str = "name",
        descending: bool = False,
        offset: int = Query(0, ge=0),
        limit: int = Query(100, ge=1, le=200),
        tracker: str = "",
        state: str = "",
        category: str = "",
    ) -> dict:
        rows = [
            r
            for r in operations.rows
            if q.casefold() in r["name"].casefold()
            and (not tracker or tracker in r["trackers"])
            and (not state or r["status"] == state)
            and (not category or any(category == " / ".join(c) for c in r["categories"]))
        ]
        if sort not in {
            "name",
            "status",
            "size",
            "progress",
            "download",
            "upload",
            "ratio",
            "seeds",
            "peers",
            "zen",
            "note",
        }:
            raise HTTPException(400, "Unknown sort column.")
        rows.sort(
            key=lambda r: (
                r[sort] is None,
                r[sort].casefold() if isinstance(r[sort], str) else r[sort] or 0,
            ),
            reverse=descending,
        )
        return {
            "rows": rows[offset : offset + limit],
            "total": len(rows),
            "zen": operations.zen,
            "trackers": sorted({h for r in operations.rows for h in r["trackers"] if h}),
            "categories": sorted(
                {" / ".join(c) for r in operations.rows for c in r["categories"] if c}
            ),
        }

    @app.post("/api/jobs", status_code=202)
    def start_job(body: JobRequest) -> dict:
        with jobs.lock:
            operations.validate(body)
            if (
                body.kind == "manage"
                and body.action in {"delete", "remove"}
                and not confirmations.consume(body)
            ):
                raise HTTPException(409, "Review and confirm the selected torrents first.")
            identifier = jobs.submit(
                body.kind, lambda stop, progress: operations.run(body, stop, progress)
            )
        return {"id": identifier}

    @app.post("/api/confirm")
    def confirm(body: JobRequest) -> dict:
        with jobs.lock:
            return confirmations.preview(body)

    @app.get("/api/jobs")
    def list_jobs() -> list:
        return jobs.list()

    @app.get("/api/jobs/{identifier}")
    def read_job(identifier: str) -> dict:
        try:
            return jobs.get(identifier)
        except KeyError:
            raise HTTPException(404, "Job not found.") from None

    @app.post("/api/jobs/{identifier}/cancel")
    def cancel_job(identifier: str) -> dict:
        try:
            jobs.cancel(identifier)
        except KeyError:
            raise HTTPException(404, "Job not found.") from None
        return {"ok": True}

    assets = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=assets), name="static")

    @app.get("/healthz")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/")
    def shell() -> FileResponse:
        return FileResponse(assets / "index.html")

    return app
