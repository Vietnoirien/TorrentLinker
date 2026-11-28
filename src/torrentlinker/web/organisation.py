"""Organisation routes: folder roles, provenance links, Ranger and À vérifier (Owner only, #223)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, Field

from torrentlinker.file_storage import FileStorage, StorageError
from torrentlinker.organisation import template_error
from torrentlinker.ranger import Board, RangerQueue


class Template(BaseModel):
    folder: str = Field(max_length=4096)
    kind: str = Field(pattern="^(film|series)$")
    template: str = Field(default="", max_length=300)


class Role(BaseModel):
    path: str = Field(max_length=4096)
    role: str = Field(pattern="^(lib|prov|none)$")
    kind: str = Field(default="", pattern="^(films|series|other|)$")


class Link(BaseModel):
    path: str = Field(max_length=4096)
    to: str = Field(default="", max_length=4096)


class Auto(BaseModel):
    path: str = Field(max_length=4096)
    on: bool


class Paths(BaseModel):
    paths: list[str] = Field(min_length=1, max_length=50)


class Review(BaseModel):
    path: str = Field(max_length=4096)
    title: str = Field(default="", max_length=300)
    keep: bool = False


def organisation_routes(
    app: FastAPI, storage: FileStorage, board: Board, queue: RangerQueue
) -> None:
    def refuse(error: StorageError) -> HTTPException:
        return HTTPException(409, str(error))

    @app.get("/api/files/organisation")
    def state() -> dict[str, Any]:
        """The board as last read: the folders are read in the background, never here."""
        board.ensure_scanned()
        return {**board.state(), "jobs": queue.active()}

    @app.get("/api/files/organisation/folders")
    def folders() -> dict[str, Any]:
        return {"folders": board.folders(), "disks": board.disks()}

    @app.post("/api/files/organisation/scan", status_code=202)
    def scan() -> dict[str, Any]:
        board.scan()
        return {"ok": True}

    @app.post("/api/files/organisation/role")
    def role(body: Role) -> dict[str, Any]:
        try:
            board.set_role(body.path, body.role, body.kind)
        except StorageError as error:
            raise refuse(error) from error
        return {"ok": True}

    @app.post("/api/files/organisation/link")
    def link(body: Link) -> dict[str, Any]:
        try:
            board.set_link(body.path, body.to)
        except StorageError as error:
            raise refuse(error) from error
        return {"ok": True}

    @app.post("/api/files/organisation/auto")
    def auto(body: Auto) -> dict[str, Any]:
        try:
            board.set_auto(body.path, body.on)
        except StorageError as error:
            raise refuse(error) from error
        return {"ok": True}

    @app.post("/api/files/organisation/template")
    def save_template(body: Template) -> dict[str, Any]:
        if body.template and (why := template_error(body.template)):
            raise HTTPException(400, why)
        if body.folder not in {lib["path"] for lib in board.libraries()}:
            raise HTTPException(404, "This is not an organised library.")
        storage.set_template(body.folder, body.kind, body.template)
        return {"ok": True}

    @app.get("/api/files/organisation/suggest")
    def suggest(q: str = Query("", max_length=200)) -> dict[str, Any]:
        return {"titles": board.suggest(q)}

    @app.post("/api/files/organisation/review")
    def review(body: Review) -> dict[str, Any]:
        try:
            board.keep(body.path) if body.keep else board.fix_title(body.path, body.title)
        except StorageError as error:
            raise refuse(error) from error
        return {"ok": True}

    @app.post("/api/files/organisation/summary")
    def summary(body: Paths) -> dict[str, Any]:
        try:
            return board.summary(body.paths)
        except StorageError as error:
            raise refuse(error) from error

    @app.post("/api/files/organisation/ranger", status_code=202)
    def ranger(body: Paths, request: Request) -> dict[str, Any]:
        """Queue every ready item of the chosen provenances: nothing moves in this request,
        the batch is kept and runs as one Tâche that survives a restart."""
        actor = request.state.actor
        known = set(board.provenances()) | {lib["path"] for lib in board.libraries()}
        rows = []
        for prov in body.paths:
            if prov not in known:
                raise HTTPException(404, "This folder is not a provenance.")
            if not board.ready(prov):
                raise HTTPException(409, "The folder is still being read: try again in a moment.")
            rows += [
                {"top": i.path, "prov": prov, "kind": i.kind, "title": i.title}
                for i in board.todo(prov)
                if i.recognised
            ]
        if not rows:
            raise HTTPException(409, "There is nothing to range in this selection.")
        names = ", ".join(Path(p).name for p in body.paths)
        job = queue.enqueue(f"Ranger {len(rows)} ({names})", actor.viewer or actor.account, rows)
        return {"job": job, "queued": len(rows)}
