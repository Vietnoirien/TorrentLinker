"""Replace routes: start a replacement, follow it, read the Fin du partage rule (Owner only)."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from torrentlinker.library_replace import FinRule, Placement, Replacements, placement


class Rule(BaseModel):
    use_time: bool = True
    hours: float = Field(default=168.0, gt=0, le=24 * 3650)
    use_ratio: bool = True
    ratio: float = Field(default=1.0, gt=0, le=1000)
    combine: str = Field(default="any", pattern="^(any|all)$")


class Replacement(BaseModel):
    film: str = Field(max_length=200)
    new_hash: str = Field(pattern="^[0-9a-fA-F]{40}$")
    old_hash: str = Field(default="", pattern="^([0-9a-fA-F]{40})?$")
    old_paths: list[str] = Field(max_length=500)
    new_size: int = Field(ge=0)
    replace: bool = False
    wait: bool = False
    rule: Rule = Rule()
    client_id: str = ""


class Place(BaseModel):
    folder: str = Field(max_length=4096)
    size: int = Field(ge=0)
    download_folder: str = Field(default="", max_length=4096)


def replace_routes(app: FastAPI, replacements: Replacements, client_for) -> None:
    app.state.replacements = replacements

    @app.get("/api/media/replacements")
    def listing(client_id: str = "") -> dict:
        return {"replacements": replacements.runs(client_id or None)}

    @app.post("/api/media/replacements/placement")
    def where(body: Place) -> dict:
        try:
            found: Placement = placement(
                Path(body.folder),
                body.size,
                Path(body.download_folder) if body.download_folder else None,
            )
        except (OSError, ValueError) as error:
            raise HTTPException(400, str(error)) from error
        return {"folder": str(found.folder), "fallback": found.fallback, "reason": found.reason}

    @app.post("/api/media/replacements", status_code=201)
    def start(body: Replacement, request: Request) -> dict:
        actor = request.state.actor
        try:
            run = replacements.start(
                body.client_id,
                body.film,
                new_hash=body.new_hash,
                old_hash=body.old_hash,
                old_paths=[Path(p) for p in body.old_paths],
                replace=body.replace,
                wait=body.wait,
                rule=FinRule.parse(body.rule.model_dump()),
                actor=actor.viewer or actor.account,
            )
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        return {"id": run}

    @app.post("/api/media/replacements/tick")
    def tick(client_id: str = "") -> dict:
        return {"moved": replacements.tick(client_for(client_id), client_id)}
