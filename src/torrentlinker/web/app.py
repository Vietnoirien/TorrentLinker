"""Authenticated HTTP adapter for the headless application."""

from __future__ import annotations

import threading
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from torrentlinker import documentation
from torrentlinker.clients import connect
from torrentlinker.torrent_management import peer_count_order, tracker_group
from torrentlinker.web.confirmations import Confirmations
from torrentlinker.web.documentation import render
from torrentlinker.web.jobs import Jobs
from torrentlinker.web.operations import JobRequest, Operations
from torrentlinker.web.security import ServerSecrets, Sessions
from torrentlinker.web.setup import (
    Connection,
    Connector,
    FolderRemoval,
    FolderSetup,
    IndexerConnection,
    ProxySetup,
    Setup,
)


class ClientSelection(BaseModel):
    client_id: str = ""


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
    service_override: Setup | None = None,
    operation_factory=Operations,
    monitor_verifications: bool = True,
    assistant_transport=None,
) -> FastAPI:
    directory.mkdir(parents=True, exist_ok=True)
    sessions = Sessions(password)
    service = service_override or Setup(
        directory, roots, ServerSecrets(directory, secret_files), connector
    )

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
    operations = operation_factory(service)
    confirmations = Confirmations(service)
    client_operations: dict[str, Operations] = {}
    client_confirmations: dict[str, Confirmations] = {}

    def for_client(identifier: str = "") -> Operations:
        identifier = identifier or service.settings.default_client_id
        service.settings.profile(identifier)
        if identifier == service.settings.active_client_id:
            return operations
        if identifier not in client_operations:
            client_operations[identifier] = operation_factory(service.for_client(identifier))
        target = client_operations[identifier]
        target.setup.settings = service.settings.for_client(identifier)
        return target

    def consent(identifier: str) -> Confirmations:
        target = for_client(identifier)
        if target is operations:
            return confirmations
        if identifier not in client_confirmations:
            client_confirmations[identifier] = Confirmations(target.setup)
        return client_confirmations[identifier]

    def reset_clients() -> None:
        nonlocal operations, confirmations
        operations = operation_factory(service)
        confirmations = Confirmations(service)
        client_operations.clear()
        client_confirmations.clear()

    shutdown = threading.Event()
    verification_cursor = 0

    def verify_loop() -> None:
        nonlocal verification_cursor
        while not shutdown.wait(10):
            with jobs.lock:
                if service.configured and not jobs.active():
                    profiles = service.settings.client_profiles
                    start = verification_cursor % len(profiles)
                    for offset in range(len(profiles)):
                        position = (start + offset) % len(profiles)
                        profile = profiles[position]
                        if (
                            profile.enabled
                            and service.store.for_client(profile.id).verification_hashes()
                        ):
                            target = for_client(profile.id)
                            jobs.submit(
                                "verify",
                                lambda stop, progress, target=target: target.run(  # type: ignore[misc]
                                    JobRequest(
                                        kind="verify",
                                        client_id=target.setup.settings.active_client_id,
                                    ),
                                    stop,
                                    progress,
                                ),
                                client_id=profile.id,
                            )
                            verification_cursor = position + 1
                            break

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        monitor = threading.Thread(target=verify_loop, daemon=True, name="verification-monitor")
        if monitor_verifications:
            monitor.start()
        assistant.start_scheduler()
        try:
            async with mcp_server.session_manager.run():
                yield
        finally:
            shutdown.set()
            if monitor_verifications:
                monitor.join(timeout=2)
            assistant.close()
            jobs.close()

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)

    from torrentlinker.agent.access import Access
    from torrentlinker.agent.routes import owner_routes

    agent_access = Access(directory)
    from torrentlinker.agent.server import make_server
    from torrentlinker.agent.service import AgentService

    agent_service = AgentService(agent_access, service, jobs, for_client)
    mcp_server, mcp_app = make_server(agent_service)
    app.mount("/mcp", mcp_app)
    owner_routes(app, agent_access, service, agent_service)
    from torrentlinker.assistant.routes import routes as assistant_routes
    from torrentlinker.assistant.service import Assistant

    assistant = Assistant(directory, agent_service, mcp_server, assistant_transport)
    assistant_routes(app, assistant)
    app.state.assistant = assistant
    app.state.agent_service = agent_service
    app.state.reset_clients = reset_clients

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
        if route.startswith("/documentation/") and not sessions.valid(
            request.cookies.get("tl_session", "")
        ):
            return JSONResponse({"detail": "Sign in to TorrentLinker."}, status_code=401)
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

    @app.get("/api/documentation")
    def documentation_index(language: str = "en") -> list[dict[str, str]]:
        return documentation.guides(language)

    @app.get("/documentation/{name:path}", response_class=HTMLResponse)
    def documentation_reference(name: str, request: Request) -> HTMLResponse:
        if name not in {
            g["path"] for language in ("en", "fr") for g in documentation.guides(language)
        }:
            raise HTTPException(404, "Guide unavailable.")
        try:
            html = render(name, standalone=True, root_path=request.scope.get("root_path", ""))
        except (ValueError, OSError) as error:
            raise HTTPException(404, "Guide unavailable.") from error
        return HTMLResponse(
            '<!doctype html><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width">'
            "<title>TorrentLinker documentation</title><main>" + html + "</main>"
        )

    @app.get("/api/documentation/page/{name:path}")
    def documentation_page(name: str) -> dict[str, str]:
        try:
            return {"html": render(name)}
        except (ValueError, OSError) as error:
            raise HTTPException(404, "Guide unavailable.") from error

    @app.get("/api/documentation/file/{name:path}")
    def documentation_file(name: str) -> FileResponse:
        try:
            path = documentation.document_path(name)
            if path.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
                raise ValueError("Not an image.")
            return FileResponse(path)
        except (ValueError, OSError) as error:
            raise HTTPException(404, "Image unavailable.") from error

    @app.get("/api/setup")
    def setup(client_id: str = "") -> dict:
        return for_client(client_id).setup.snapshot()

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
        return for_client(body.client_id).setup.test_client(body)

    @app.post("/api/setup/client")
    def save_client(body: Connection) -> dict:
        nonlocal operations
        with jobs.lock:
            idle()
            target = for_client(body.client_id)
            old = target.setup.snapshot()
            saved = target.setup.test_client(body, save=True)
            if old["client"] != body.client or old["host"] != body.host:
                target.rows.clear()
                target.library.entries.clear()
            return saved

    @app.post("/api/clients")
    def add_client(body: Connection) -> dict:
        with jobs.lock:
            idle()
            if not body.name.strip():
                raise ValueError("Enter a name for this Torrent Client.")
            profile = service.settings.add_client(body.name, body.client)
            try:
                target = service.for_client(profile.id)
                result = target.test_client(body, save=True)
                service.configured = True
            except Exception:
                service.settings.client_profiles.remove(profile)
                raise
            return {**result, "client_id": profile.id}

    @app.post("/api/clients/default")
    def default_client(body: ClientSelection) -> dict:
        with jobs.lock:
            idle()
            service.settings.profile(body.client_id)
            service.settings.default_client_id = body.client_id
            service.save()
        return {"ok": True}

    @app.post("/api/clients/remove")
    def remove_client(body: ClientSelection) -> dict:
        from torrentlinker.client_profiles import pending_work

        with jobs.lock:
            idle()
            profile = service.settings.profile(body.client_id)
            if len(service.settings.client_profiles) == 1 or pending_work(
                service.settings, service.store, profile.id
            ):
                raise ValueError("This client has pending work or is the only configured client.")
            remaining = [p for p in service.settings.client_profiles if p.id != profile.id]
            if service.settings.active_client_id == profile.id:
                service.settings.select_client(remaining[0].id)
                service.store = service.store.for_client(remaining[0].id)
                service._client = None
            service.settings.client_profiles = remaining
            if service.settings.default_client_id == profile.id:
                service.settings.default_client_id = remaining[0].id
            service.save()
            reset_clients()
        return {"ok": True}

    @app.post("/api/setup/test-indexer")
    def test_indexer(body: IndexerConnection) -> dict:
        return service.test_indexer(body)

    @app.post("/api/setup/indexer")
    def save_indexer(body: IndexerConnection) -> dict:
        with jobs.lock:
            idle()
            result = service.test_indexer(body, save=True)
            reset_clients()
            return result

    @app.get("/api/folders")
    def folders(path: str = "") -> dict:
        return service.browse(path)

    @app.post("/api/setup/test-folder")
    def test_folder(body: FolderSetup) -> dict:
        return for_client(body.client_id).setup.folder(body)

    @app.post("/api/setup/folder")
    def save_folder(body: FolderSetup) -> dict:
        with jobs.lock:
            idle()
            target = for_client(body.client_id)
            result = target.setup.folder(body, save=True)
            target.library.entries.clear()
            return result

    @app.post("/api/setup/remove-folder")
    def remove_folder(body: FolderRemoval) -> dict:
        with jobs.lock:
            idle()
            target = for_client(body.client_id)
            if target.setup.store.verification_hashes():
                raise HTTPException(
                    409, "Finish pending Reseed Verifications before removing folders."
                )
            target.setup.remove_folder(body)
            target.library.entries.clear()
        return {"ok": True}

    @app.post("/api/setup/suggest-mappings")
    def suggest_mappings(body: ClientSelection) -> dict:
        with jobs.lock:
            idle()
            return for_client(body.client_id).setup.suggest_mappings()

    @app.post("/api/setup/proxy")
    def save_proxy(body: ProxySetup) -> dict:
        with jobs.lock:
            idle()
            result = service.proxy(body)
            reset_clients()
            return result

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

    @app.get("/api/upload/queue")
    def upload_queue(client_id: str = "") -> list:
        return for_client(client_id).setup.store.local_drafts()

    @app.get("/api/upload/queue/{identifier}/preview")
    def upload_queue_preview(
        identifier: str, revision: int = Query(ge=1), client_id: str = ""
    ) -> dict:
        from torrentlinker.agent.upload_presentations import draft_item

        store = for_client(client_id).setup.store
        try:
            draft = store.local_draft(identifier)
        except ValueError as error:
            raise HTTPException(404, str(error)) from error
        if draft["revision"] != revision:
            raise HTTPException(409, "Draft changed. Refresh the queue and preview it again.")
        return draft_item(draft, "0")

    @app.get("/api/library")
    def library(
        client_id: str = "",
        q: str = "",
        offset: int = Query(0, ge=0),
        limit: int = Query(100, ge=1, le=200),
    ) -> dict:
        rows = [
            r for r in for_client(client_id).library.rows() if q.casefold() in r["name"].casefold()
        ]
        return {"rows": rows[offset : offset + limit], "total": len(rows)}

    @app.get("/api/queue")
    def queue(client_id: str = "") -> list:
        if client_id == "all":
            return [
                row for p in service.settings.client_profiles for row in for_client(p.id).queue()
            ]
        return for_client(client_id).queue()

    @app.post("/api/queue/remove")
    def remove_queue(keys: list[str]) -> dict:
        with jobs.lock:
            idle()
            service.store.remove_downloads(keys[:1000])
        return {"ok": True}

    @app.get("/api/torrents")
    def torrents(
        client_id: str = "",
        q: str = "",
        sort: str = "name",
        descending: bool = False,
        offset: int = Query(0, ge=0),
        limit: int = Query(100, ge=1, le=200),
        tracker: str = "",
        state: str = "",
        category: str = "",
    ) -> dict:
        targets = (
            [for_client(p.id) for p in service.settings.client_profiles if p.enabled]
            if client_id == "all"
            else [for_client(client_id)]
        )
        from torrentlinker.seeding import combined_seeding

        observed = [t for target in targets for t in target.observed]
        combined = combined_seeding(
            service.settings.zen,
            observed,
            service.settings.indexer.url,
            catalogue={
                r.infohash: r for r in service.store.catalogue([t.hash.lower() for t in observed])
            },
        )
        combined_zen = {
            "count": combined.count,
            "daily": combined.day.total,
            "paid": combined.day.paid,
        }
        all_rows = [r for target in targets for r in target.rows]
        rows = [
            r
            for r in all_rows
            if q.casefold() in r["name"].casefold()
            and (
                not tracker
                or any(tracker_group(tracker) == tracker_group(host) for host in r["trackers"])
            )
            and (not state or r["status"] == state)
            and (not category or any(category == " / ".join(c) for c in r["categories"]))
        ]
        if sort not in {
            "name",
            "client_name",
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

        def sort_value(row):
            if sort in {"seeds", "peers"}:
                return peer_count_order(row[sort], row.get("total_" + sort, -1))
            return row[sort]

        rows.sort(
            key=lambda r: (
                sort_value(r) is None,
                sort_value(r).casefold() if isinstance(sort_value(r), str) else sort_value(r) or 0,
            ),
            reverse=descending,
        )
        return {
            "rows": rows[offset : offset + limit],
            "total": len(rows),
            "zen": combined_zen,
            "client_errors": [
                {"name": t.setup.settings.profile().name, "message": t.connection_error}
                for t in targets
                if t.connection_error
            ],
            "trackers": sorted({tracker_group(h) for r in all_rows for h in r["trackers"] if h}),
            "categories": sorted({" / ".join(c) for r in all_rows for c in r["categories"] if c}),
        }

    @app.post("/api/jobs", status_code=202)
    def start_job(body: JobRequest) -> dict:
        with jobs.lock:
            if body.client_id == "all":
                if body.kind != "refresh":
                    raise ValueError("Choose a target client before making changes.")
                targets = [for_client(p.id) for p in service.settings.client_profiles if p.enabled]

                def refresh_all(stop, progress):
                    results = []
                    for target in targets:
                        try:
                            result = target.run(body, stop, progress)
                        except Exception as error:
                            target.connection_error = error_message(error)
                            result = {"error": target.connection_error}
                        results.append(
                            {"client_id": target.setup.settings.active_client_id, **result}
                        )
                    return results

                return {"id": jobs.submit("refresh", refresh_all, client_id="all")}
            body = body.model_copy(
                update={"client_id": body.client_id or service.settings.default_client_id}
            )
            target = for_client(body.client_id)
            target.validate(body)
            if (
                body.kind == "manage"
                and body.action in {"delete", "remove"}
                and not consent(body.client_id).consume(body)
            ):
                raise HTTPException(409, "Review and confirm the selected torrents first.")
            identifier = jobs.submit(
                body.kind,
                lambda stop, progress: target.run(body, stop, progress),
                client_id=body.client_id,
            )
        return {"id": identifier}

    @app.post("/api/confirm")
    def confirm(body: JobRequest) -> dict:
        with jobs.lock:
            body = body.model_copy(
                update={"client_id": body.client_id or service.settings.default_client_id}
            )
            return consent(body.client_id).preview(body)

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
