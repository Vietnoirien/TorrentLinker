"""Fichiers routes: the Corbeille and the operation journal (ADR-0029). Owner only for now."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from torrentlinker.file_storage import FileStorage, StorageError


class TrashPath(BaseModel):
    path: str = Field(max_length=4096)


class Emptying(BaseModel):
    confirm: bool = False
    disk: str = Field(default="", max_length=40)


class Retention(BaseModel):
    days: int = Field(ge=1, le=365)


def file_routes(app: FastAPI, storage: FileStorage) -> None:
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
