"""Authenticated owner controls; companion writes use a separate, narrow capability."""

from __future__ import annotations

import json

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from torrentlinker.profile import ProfileError
from torrentlinker.profile_workspace import extension_origin
from torrentlinker.web.setup import Setup


async def companion_request(request: Request, route: str, setup: Setup) -> Response:
    origin = request.headers.get("origin", "")
    if not extension_origin(origin):
        return JSONResponse({"detail": "Use the paired browser extension."}, status_code=403)
    headers = {"Access-Control-Allow-Origin": origin, "Vary": "Origin", "Cache-Control": "no-store"}
    if request.method == "OPTIONS":
        return Response(
            status_code=204,
            headers={
                **headers,
                "Access-Control-Allow-Methods": "POST",
                "Access-Control-Allow-Headers": "content-type, authorization",
            },
        )
    if request.method != "POST":
        return JSONResponse({"detail": "POST required."}, status_code=405, headers=headers)
    try:
        raw = b""
        async for chunk in request.stream():
            raw += chunk
            if len(raw) > 8192:
                raise ValueError("Request too large.")
        body = json.loads(raw)
        if not isinstance(body, dict):
            raise ValueError("Invalid JSON object.")
        workspace = setup.profile_workspace()
        result = workspace.receive(route, origin, request.headers.get("authorization", ""), body)
        return JSONResponse(result, headers=headers)
    except PermissionError as error:
        return JSONResponse({"detail": str(error)}, status_code=403, headers=headers)
    except (ValueError, UnicodeError):
        return JSONResponse(
            {"detail": "Invalid or expired snapshot. Read a new preview."},
            status_code=400,
            headers=headers,
        )


def profile_routes(app: FastAPI, setup: Setup) -> None:
    @app.get("/api/zen/profile")
    def state():  # type: ignore[no-untyped-def]
        return setup.profile_workspace().state()

    @app.post("/api/zen/profile/refresh")
    def refresh():  # type: ignore[no-untyped-def]
        workspace = setup.profile_workspace()
        try:
            profile = workspace.refresh(
                setup.settings.indexer.url, setup.secrets.get("indexer-api-key")
            )
            setup.settings.zen = profile.apply(setup.settings.zen)
            setup.save()
        except ProfileError:
            pass  # Typed error is shown next to the last successful API data.
        return workspace.state()

    @app.post("/api/zen/profile/pairing")
    def pairing():  # type: ignore[no-untyped-def]
        try:
            return setup.profile_workspace().pairing()
        except ValueError as error:
            raise HTTPException(409, str(error)) from error

    @app.post("/api/zen/profile/disconnect")
    def disconnect():  # type: ignore[no-untyped-def]
        workspace = setup.profile_workspace()
        workspace.disconnect()
        return workspace.state()

    @app.get("/api/zen/profile/extension")
    def extension(request: Request) -> Response:
        from torrentlinker.companion import extension_zip

        return Response(
            extension_zip(str(request.base_url)),
            media_type="application/zip",
            headers={"Content-Disposition": 'attachment; filename="torrentlinker-companion.zip"'},
        )

    @app.get("/companion/connect")
    @app.get("/companion/connect.js")
    @app.get("/companion/connect.css")
    def connect_page(request: Request) -> Response:
        from torrentlinker.companion import connection_asset

        path = "/companion/" + request.url.path.rsplit("/", 1)[-1]
        asset = connection_asset(path)
        assert asset is not None
        raw, kind = asset
        return Response(
            raw,
            media_type=kind,
            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
        )
