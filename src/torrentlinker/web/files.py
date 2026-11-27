"""Fichiers routes: the Corbeille and the operation journal (ADR-0029). Owner only for now."""

from __future__ import annotations

import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from torrentlinker.disk_health import alert as health_alert
from torrentlinker.disk_health import disk_health, scrutiny
from torrentlinker.disk_report import disk_cards, place
from torrentlinker.file_storage import FileStorage, StorageError
from torrentlinker.file_tasks import Tasks, listing


class TrashPath(BaseModel):
    path: str = Field(max_length=4096)


class Emptying(BaseModel):
    confirm: bool = False
    disk: str = Field(default="", max_length=40)


class Placement(BaseModel):
    size: int = Field(ge=0)
    together_with: str = Field(default="", max_length=4096)


class Scrutiny(BaseModel):
    url: str = Field(default="", max_length=300)


class Operation(BaseModel):
    kind: str = Field(pattern="^(move|copy|rename|mkdir|trash)$")
    items: list[dict[str, str]] = Field(min_length=1, max_length=500)
    conflict: str = Field(default="skip", pattern="^(skip|replace|rename|keep-one)$")


class Retention(BaseModel):
    days: int = Field(ge=1, le=365)


def file_routes(
    app: FastAPI, storage: FileStorage, folders=lambda: ([], []), films=None, notice=None
) -> None:
    """`folders` gives the Library and Download Folders; `films(path)` counts a folder's films."""
    app.state.file_storage = storage

    def who(request: Request) -> str:
        actor = request.state.actor
        return actor.viewer or actor.account

    def refuse(error: StorageError) -> HTTPException:
        return HTTPException(409, str(error))

    @app.get("/api/files/trash")
    def trash_listing() -> dict:
        return storage.listing()

    @app.post("/api/files/trash")
    def trash(body: TrashPath, request: Request) -> dict:
        try:
            return storage.trash(Path(body.path), who(request))
        except StorageError as error:
            raise refuse(error) from error

    @app.post("/api/files/trash/{identifier}/restore")
    def restore(identifier: str, request: Request) -> dict:
        try:
            return {"restored": storage.restore(identifier, who(request))}
        except StorageError as error:
            raise refuse(error) from error

    @app.post("/api/files/trash/empty")
    def empty(body: Emptying, request: Request) -> dict:
        if not body.confirm:
            raise HTTPException(400, "Emptying the trash deletes its data for good: confirm it.")
        try:
            return {"deleted": storage.empty(who(request), body.disk or None)}
        except StorageError as error:
            raise refuse(error) from error

    @app.post("/api/files/trash/retention")
    def retention(body: Retention) -> dict:
        storage.set_retention_days(body.days)
        return {"retention_days": storage.retention_days()}

    @app.get("/api/files/journal")
    def journal() -> dict:
        return {"operations": storage.journal()}

    @app.post("/api/files/journal/{identifier}/undo")
    def undo(identifier: str, request: Request) -> dict:
        try:
            return {"restored": storage.undo(identifier, who(request))}
        except StorageError as error:
            raise refuse(error) from error

    tasks = Tasks(storage)
    app.state.file_tasks = tasks

    @app.get("/api/files/browse")
    def browse(path: str = "") -> dict:
        if not path:
            return {"path": "", "roots": [str(r) for r in storage.roots], "entries": []}
        try:
            target = Path(path)
            return {"path": str(target), "entries": listing(storage, target)}
        except StorageError as error:
            raise refuse(error) from error
        except OSError as error:
            raise HTTPException(404, error.strerror or str(error)) from error

    @app.post("/api/files/tasks", status_code=202)
    def run(body: Operation, request: Request) -> dict:
        try:
            return tasks.submit(body.kind, body.items, who(request), body.conflict)
        except StorageError as error:
            raise refuse(error) from error

    @app.get("/api/files/tasks")
    def queue() -> dict:
        return {"tasks": tasks.snapshot()}

    @app.post("/api/files/tasks/{identifier}/cancel")
    def cancel(identifier: str) -> dict:
        if identifier not in tasks.tasks:
            raise HTTPException(404, "Unknown task.")
        tasks.cancel(identifier)
        return {"ok": True}

    @app.post("/api/files/tasks/{identifier}/undo/{index}")
    def undo_item(identifier: str, index: int, request: Request) -> dict:
        try:
            return {"restored": tasks.undo(identifier, index, who(request))}
        except (StorageError, KeyError, IndexError) as error:
            raise HTTPException(409, str(error) or "Unknown task.") from error

    seen: dict[str, tuple[float, dict]] = {}

    def health(roots: list[Path]) -> dict:
        """Read at most every ten minutes: smartctl wakes a sleeping disk."""
        key = str(roots[0])
        if key in seen and time.monotonic() - seen[key][0] < 600:
            return seen[key][1]
        found = disk_health(roots, scrutiny_url=storage.scrutiny_url())
        seen[key] = (time.monotonic(), found)
        if (why := health_alert(found)) and notice is not None:
            notice("disk", f"Disk alert: {roots[0]}", "failing", why, f"disk:{key}:{why}")
        return found

    def cards() -> dict:
        library, downloads = folders()
        report = disk_cards(storage, library, downloads, films or (lambda _: 0), health=health)
        report["scrutiny_url"] = storage.scrutiny_url()
        return report

    @app.post("/api/files/disks/scrutiny")
    def save_scrutiny(body: Scrutiny) -> dict:
        try:
            storage.set_scrutiny_url(body.url)
        except StorageError as error:
            raise refuse(error) from error
        seen.clear()
        return {"scrutiny_url": storage.scrutiny_url()}

    @app.post("/api/files/disks/scrutiny/test")
    def test_scrutiny(body: Scrutiny) -> dict:
        import httpx

        try:
            known = scrutiny(body.url)
        except (httpx.HTTPError, ValueError, OSError) as error:
            raise HTTPException(409, f"Scrutiny does not answer: {error}") from error
        return {"disks": sorted(known)}

    @app.get("/api/files/disks")
    def disks() -> dict:
        return cards()

    @app.post("/api/files/disks/placement")
    def placement(body: Placement) -> dict:
        together = Path(body.together_with) if body.together_with else None
        return place(cards()["disks"], body.size, together)
