"""Gzip for text responses only: media, ranges and downloads travel as they are."""

from __future__ import annotations

from starlette.datastructures import Headers
from starlette.middleware.gzip import GZipResponder
from starlette.types import ASGIApp, Message, Receive, Scope, Send

TEXT_TYPES = {"application/json", "application/javascript", "image/svg+xml"}
NEVER = {"text/event-stream"}


def compressible(message: Message) -> bool:
    headers = Headers(raw=message["headers"])
    if message["status"] != 200 or "content-range" in headers or "content-encoding" in headers:
        return False
    if "attachment" in headers.get("content-disposition", "").lower():
        return False
    kind = headers.get("content-type", "").partition(";")[0].strip().lower()
    return kind not in NEVER and (kind.startswith("text/") or kind in TEXT_TYPES)


class TextGZip:
    def __init__(self, app: ASGIApp, minimum_size: int = 500, compresslevel: int = 6) -> None:
        self.app = app
        self.minimum_size = minimum_size
        self.compresslevel = compresslevel

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        headers = Headers(scope=scope) if scope["type"] == "http" else None
        if (
            headers is None
            or "gzip" not in headers.get("accept-encoding", "")
            or "range" in headers
        ):
            await self.app(scope, receive, send)
            return
        responder = GZipResponder(self.app, self.minimum_size, self.compresslevel)
        responder.send = send
        target = send

        async def route(message: Message) -> None:
            nonlocal target
            if message["type"] == "http.response.start":
                target = responder.send_with_compression if compressible(message) else send
            await target(message)

        await self.app(scope, receive, route)
