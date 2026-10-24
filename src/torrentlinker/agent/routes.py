"""Owner-only endpoints, protected by the host application's session middleware."""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from torrentlinker.agent.access import Access, Grant
from torrentlinker.agent.service import AgentService
from torrentlinker.web.setup import Setup


class Enabled(BaseModel):
    enabled: bool


def owner_routes(app: FastAPI, access: Access, setup: Setup, service: AgentService) -> None:
    @app.get("/api/agents")
    def snapshot() -> dict:
        return access.snapshot()

    @app.put("/api/agents")
    def enable(body: Enabled) -> dict:
        service.enable(body.enabled)
        return access.snapshot()

    @app.post("/api/agents")
    def create(body: Grant) -> dict:
        for identifier in body.clients:
            setup.settings.profile(identifier)
        return access.create(body)

    @app.post("/api/agents/{identifier}/revoke")
    def revoke(identifier: str) -> dict:
        service.revoke(identifier)
        return {"ok": True}

    @app.post("/api/agents/proposals/{identifier}/approve")
    def approve(identifier: str) -> dict:
        try:
            return service.execute(identifier, approved=True)
        except PermissionError as error:
            raise HTTPException(403, str(error)) from None

    @app.post("/api/agents/proposals/{identifier}/reject")
    def reject(identifier: str) -> dict:
        service.reject(identifier)
        return {"ok": True}

    @app.get("/api/agents/proposals/{identifier}/review")
    def review(identifier: str) -> dict:
        return service.review(identifier)

    @app.post("/api/agents/proposals/{identifier}/release-storage")
    def release_storage(identifier: str) -> dict:
        service.release_storage(identifier)
        return {"ok": True}
