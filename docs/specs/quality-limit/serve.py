"""Serve the real Web UI with example data and the proposed quality limit (preview).

Run .venv/bin/python docs/specs/quality-limit/serve.py from the repository root, then open
http://127.0.0.1:8767/quality-preview/owner (the Owner: Paramètres > Utilisateurs) or
http://127.0.0.1:8767/quality-preview/member (Léa, a Member: Médias). No real client or
account is used: every connection outside this server is refused, and the playback facts of
a film are stubbed (FFmpeg is not needed).
"""

import ipaddress
import json
import socket
import sys
import threading
from http.cookies import SimpleCookie
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import uvicorn

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from torrentlinker.accounts import Permission  # noqa: E402
from torrentlinker.config import Settings  # noqa: E402
from torrentlinker.domain import ContentKind, LibraryFolder  # noqa: E402
from torrentlinker.web.app import create_app  # noqa: E402

PORT = 8767
OWNER_PASSWORD = "quality-preview-only-owner"
MEMBER_PASSWORD = "quality-preview-only-lea"
PREVIEW = {"preview.js": "text/javascript"}
TAGS = b'<script src="quality-preview/preview.js" defer></script></head>'
QUALITIES = ["original", "360", "480", "720", "1080"]


def reply(status, body, kind, extra=()):
    return [
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", kind.encode()),
                (b"content-length", str(len(body)).encode()),
                (b"cache-control", b"no-store"),
                *extra,
            ],
        },
        {"type": "http.response.body", "body": body},
    ]


class Preview:
    """Adds the preview script to the real page, signs in and stubs the playback facts."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "") if scope["type"] == "http" else ""
        if path.startswith("/quality-preview/"):
            name = path.removeprefix("/quality-preview/")
            if name in PREVIEW:
                for message in reply(200, (HERE / name).read_bytes(), PREVIEW[name]):
                    await send(message)
                return
            if name in ("owner", "member"):
                await self.sign_in(scope, send, name)
                return
        if path.endswith("/playback") and path.startswith("/api/media/items/"):
            cookies = SimpleCookie(dict(scope["headers"]).get(b"cookie", b"").decode())
            cap = cookies["preview_cap"].value if "preview_cap" in cookies else ""
            member = "preview_member" in cookies
            allowed = QUALITIES
            if member and cap:
                allowed = [q for q in QUALITIES if q not in ("original",) and int(q) <= int(cap)]
            facts = {
                "available": True,
                "qualities": allowed,
                "audio": [{"id": 0, "language": "fr", "label": "Français"}],
                "duration": 7200,
                "width": 1920,
                "height": 1080,
                "hdr": False,
            }
            for message in reply(200, json.dumps(facts).encode(), "application/json"):
                await send(message)
            return
        if path not in ("/", "/static/settings/view.html", "/static/player/view.html", "/static/media/view.html"):
            await self.app(scope, receive, send)
            return
        tags = TAGS if path == "/" else TAGS.replace(b'src="', b'src="/')
        start, chunks = {}, []

        async def capture(message):
            if message["type"] == "http.response.start":
                start.update(message)
            elif message["type"] == "http.response.body":
                chunks.append(message.get("body", b""))
                if not message.get("more_body"):
                    body = b"".join(chunks).replace(b"</head>", tags, 1)
                    headers = [
                        (k, v)
                        for k, v in start["headers"]
                        if k not in (b"content-length", b"cache-control", b"etag")
                    ]
                    headers.append((b"cache-control", b"no-store"))
                    headers.append((b"content-length", str(len(body)).encode()))
                    await send({**start, "headers": headers})
                    await send({"type": "http.response.body", "body": body})

        plain = {
            **scope,
            "headers": [
                (k, v)
                for k, v in scope["headers"]
                if k not in (b"accept-encoding", b"if-none-match", b"if-modified-since")
            ],
        }
        await self.app(plain, receive, capture)

    async def sign_in(self, scope, send, who):
        if who == "owner":
            body = json.dumps({"password": OWNER_PASSWORD}).encode()
        else:
            body = json.dumps({"login": "lea", "password": MEMBER_PASSWORD}).encode()
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
            extra = [(b"set-cookie", c) for c in cookies]
            if who == "member":
                extra.append((b"set-cookie", b"preview_member=1; Path=/"))
            else:
                extra.append((b"set-cookie", b"preview_member=; Path=/; Max-Age=0"))
            headers = [(b"location", b"/"), *extra]
            await send({"type": "http.response.start", "status": 303, "headers": headers})
            await send({"type": "http.response.body", "body": b""})
            return
        text = b"Preview sign-in failed: " + b"".join(answer[1:])
        for message in reply(502, text, "text/plain; charset=utf-8"):
            await send(message)


def main():
    connect = socket.socket.connect

    def this_server_only(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            host, port = address[0], address[1]
            if not (ipaddress.ip_address(host).is_loopback and port == PORT):
                raise OSError("The quality-limit preview refuses outside connections")
        return connect(sock, address)

    with TemporaryDirectory(prefix="tl-quality-limit-") as temp:
        base = Path(temp)
        films, config = base / "films", base / "config"
        films.mkdir()
        config.mkdir()
        for name in ("The Revenant 2015 1080p", "Vice Versa 2015 1080p"):
            (films / f"{name}.mkv").write_bytes(b"\0" * 64)
        settings = Settings(language="fr", theme="dark")
        settings.library_folders = [LibraryFolder(films, None, ContentKind.MOVIE)]
        settings.save(config / "settings.json")
        app = create_app(
            config,
            members_enabled=True,
            password=OWNER_PASSWORD,
            roots=(films,),
            monitor_verifications=False,
        )
        app.state.accounts.create(
            "Léa",
            "lea",
            {Permission.FILMS, Permission.SERIES},
            password=MEMBER_PASSWORD,
        )
        app.state.agent_service.media.scan("default", threading.Event(), lambda _p: None)
        print(f"Owner:  http://127.0.0.1:{PORT}/quality-preview/owner")
        print(f"Member: http://127.0.0.1:{PORT}/quality-preview/member")
        with patch.object(socket.socket, "connect", this_server_only):
            uvicorn.run(Preview(app), host="127.0.0.1", port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
