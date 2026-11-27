"""Organisation routes: rename proposals, templates, and the confirmed rows (Owner only)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from torrentlinker.file_storage import FileStorage
from torrentlinker.organisation import DEFAULTS, TOKENS, Organisation, template_error


class Template(BaseModel):
    folder: str = Field(max_length=4096)
    kind: str = Field(pattern="^(film|series)$")
    template: str = Field(default="", max_length=300)


class Apply(BaseModel):
    folder: str = Field(max_length=4096)
    keys: list[str] = Field(min_length=1, max_length=2000)


def organisation_routes(
    app: FastAPI, storage: FileStorage, organisation: Organisation, default_client
) -> None:
    @app.get("/api/files/organisation")
    def proposals(client_id: str = "") -> dict[str, Any]:
        return {
            "tokens": list(TOKENS), "defaults": DEFAULTS,
            "folders": organisation.folders(client_id or default_client()),
        }  # fmt: skip

    @app.post("/api/files/organisation/template")
    def save_template(body: Template) -> dict[str, Any]:
        if body.template and (why := template_error(body.template)):
            raise HTTPException(400, why)
        known = {str(Path(f.path)) for f in organisation.library_folders()}
        if body.folder not in known:
            raise HTTPException(404, "This is not a Library Folder.")
        storage.set_template(body.folder, body.kind, body.template)
        return {"ok": True}

    @app.post("/api/files/organisation/apply", status_code=202)
    def apply(body: Apply, request: Request) -> dict[str, Any]:
        """Queue the renames of the confirmed rows, recomputed here: the page's own paths are
        never trusted. A row that needs a Link Folder, or has a problem, is skipped."""
        actor = request.state.actor
        wanted = set(body.keys)
        card = next(
            (c for c in organisation.folders(default_client()) if c["path"] == body.folder), None
        )
        if card is None:
            raise HTTPException(404, "This is not a Library Folder.")
        rows = [r for r in card["rows"] if r["key"] in wanted]
        applicable = [r for r in rows if r["maps"] and not r["needs_link"] and not r["problem"]]
        items = [{"from": m["from"], "to": m["to"]} for r in applicable for m in r["maps"]]
        if not items:
            raise HTTPException(409, "Nothing to rename in this selection.")
        task = app.state.file_tasks.submit("rename", items, actor.viewer or actor.account, "skip")
        return {
            "task": task["id"],
            "queued": len(applicable),
            "skipped": len(rows) - len(applicable),
        }
