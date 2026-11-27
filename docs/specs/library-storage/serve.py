"""Serve the real Web UI with example data and the library-storage previews (Replace, ...).

Run .venv/bin/python docs/specs/library-storage/serve.py from the repository root, then open
http://127.0.0.1:8767/library-storage-preview/signin, which signs in for you. No real accounts or
clients are used: the torrent client is a fake, the library, posters and tracker upgrades are
written into the real stores, and every connection outside this server is refused.
"""

import ipaddress
import json
import re
import socket
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import uvicorn

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

sys.path.insert(0, str(HERE))

import fixture  # noqa: E402
from tests.test_web_plan_execution import prepared  # noqa: E402
from torrentlinker.web.app import create_app  # noqa: E402

PORT = 8767
POSTERS = {}
PASSWORD = "library-storage-preview-only"
TYPES = {".css": "text/css", ".js": "text/javascript", ".html": "text/html; charset=utf-8"}
TAGS = (
    b'<link rel="stylesheet" href="library-storage-preview/preview.css">'
    b'<script src="library-storage-preview/preview.js" defer></script></head>'
)


class Preview:
    """Adds the preview stylesheet and toggle to the real page; serves their two files."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "") if scope["type"] == "http" else ""
        name = path.removeprefix("/library-storage-preview/")
        served = path != name and "/" not in name
        generated = {"fixture.json": fixture.fixture_json, "storage.json": fixture.storage_json}
        poster = re.fullmatch(r"poster-(\d+)\.png", name)
        if served and (name in generated or poster or (HERE / name).suffix in TYPES and (HERE / name).is_file()):
            if name in generated:
                body, kind = json.dumps(generated[name]()).encode(), "application/json"
            elif poster:
                # Generated posters, the same ones the Médias page shows; no outside image.
                row = fixture.FILMS[int(poster[1]) % len(fixture.FILMS)]
                if row[0] not in POSTERS:
                    POSTERS[row[0]] = fixture.poster(row[0], row[4])
                body, kind = POSTERS[row[0]], "image/png"
            else:
                body, kind = (HERE / name).read_bytes(), TYPES[(HERE / name).suffix]
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [
                        (b"content-type", kind.encode()),
                        (b"content-length", str(len(body)).encode()),
                        (b"cache-control", b"no-store"),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return
        if path == "/api/requests" and scope["method"] == "GET":
            # The Owner has no Member account here; Médias asks for Requests and would toast "Not found".
            body = b'{"requests":[],"household":[],"quota":{},"unread":0}'
            await send({"type": "http.response.start", "status": 200, "headers": [
                (b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
            await send({"type": "http.response.body", "body": body})
            return
        if path == "/library-storage-preview/signin":
            await self.sign_in(scope, send)
            return
        if path != "/":
            await self.app(scope, receive, send)
            return
        start, chunks = {}, []
        # An uncompressed page, so the tags can be added to it.
        scope = {**scope, "headers": [(k, v) for k, v in scope["headers"] if k != b"accept-encoding"]}

        async def capture(message):
            if message["type"] == "http.response.start":
                start.update(message)
            elif message["type"] == "http.response.body":
                chunks.append(message.get("body", b""))
                if not message.get("more_body"):
                    body = b"".join(chunks).replace(b"</head>", TAGS, 1)
                    headers = [(k, v) for k, v in start["headers"] if k != b"content-length"]
                    headers.append((b"content-length", str(len(body)).encode()))
                    await send({**start, "headers": headers})
                    await send({"type": "http.response.body", "body": body})

        await self.app(scope, receive, capture)

    async def sign_in(self, scope, send):
        """Signs in as the Owner with the preview password, then opens the page."""
        body = json.dumps({"password": PASSWORD}).encode()
        host = dict(scope["headers"]).get(b"host", f"127.0.0.1:{PORT}".encode())
        login = {
            **scope,
            "method": "POST",
            "path": "/api/login",
            "raw_path": b"/api/login",
            "query_string": b"",
            "headers": [
                (b"host", host),
                (b"origin", b"http://" + host),
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                (b"x-torrentlinker", b"1"),
            ],
        }
        sent = False

        async def receive():
            nonlocal sent
            if sent:
                return {"type": "http.disconnect"}
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}

        cookies, answer = [], []

        async def capture(message):
            if message["type"] == "http.response.start":
                answer.append(message["status"])
                cookies.extend(v for k, v in message["headers"] if k == b"set-cookie")
            elif message["type"] == "http.response.body":
                answer.append(message.get("body", b""))

        await self.app(login, receive, capture)
        if answer and answer[0] == 200:
            headers = [(b"location", b"/"), *[(b"set-cookie", c) for c in cookies]]
            await send({"type": "http.response.start", "status": 303, "headers": headers})
            await send({"type": "http.response.body", "body": b""})
            return
        text = b"Preview sign-in failed: " + b"".join(answer[1:])
        await send(
            {
                "type": "http.response.start",
                "status": 502,
                "headers": [(b"content-type", b"text/plain; charset=utf-8")],
            }
        )
        await send({"type": "http.response.body", "body": text})


def main():
    connect = socket.socket.connect

    def this_server_only(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            host, port = address[0], address[1]
            if not (ipaddress.ip_address(host).is_loopback and port == PORT):
                raise OSError("The library-storage preview refuses outside connections")
        return connect(sock, address)

    with TemporaryDirectory(prefix="tl-library-storage-") as temp:
        config, setup, client, _ = prepared(Path(temp))
        setup.settings.language = "fr"
        setup.settings.theme = "dark"
        setup.save()
        app = create_app(
            config, password=PASSWORD, service_override=setup, monitor_verifications=False
        )
        media_class = type(app.state.assistant.agent.media)
        fixture.seed(app, setup, client, Path(temp) / "downloads")
        print(f"Library-storage preview: http://127.0.0.1:{PORT}/library-storage-preview/signin")
        with (
            patch.object(socket.socket, "connect", this_server_only),
            # No tracker or TMDB read, ever: a refresh keeps what the fixture wrote.
            patch.object(media_class, "enrich", lambda *a, **k: "ok"),
            patch.object(media_class, "tracker_refresh", lambda *a, **k: "complete"),
            patch.object(media_class, "films_refresh", lambda *a, **k: None),
            patch("torrentlinker.web.media.start_films_index", lambda *a, **k: None),
        ):
            uvicorn.run(Preview(app), host="127.0.0.1", port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
