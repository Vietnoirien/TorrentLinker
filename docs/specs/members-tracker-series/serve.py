"""Serve the real Web UI with example data and the Tracker Series preview.

Run .venv/bin/python docs/specs/members-tracker-series/serve.py from the repository root, then open
http://127.0.0.1:8768/tracker-series-preview/signin, which signs in for you. No real accounts or
clients are used: the torrent client is a fake, the Library series are written into the real
stores, and every connection outside this server is refused. The Tracker Series, the Member's
Requests and the Approver's list live in this process (the real routes do not exist yet).
"""

import ipaddress
import json
import re
import socket
import sys
import time
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

PORT = 8768
PASSWORD = "tracker-series-preview-only"
PREFIX = "tracker-series-preview"
TYPES = {".css": "text/css", ".js": "text/javascript", ".html": "text/html; charset=utf-8"}
HOST_TAGS = (
    f'<link rel="stylesheet" href="{PREFIX}/preview.css">'
    f'<script src="{PREFIX}/preview.js" defer></script></head>'
).encode()
MEDIA_CSS = f'<link rel="stylesheet" href="../../{PREFIX}/series.css"></head>'.encode()
# series.js runs before view.js, which opens the transport it wraps.
MEDIA_SCRIPT = (b'<script src="view.js">', f'<script src="../../{PREFIX}/series.js"></script><script src="view.js">'.encode())
SETTINGS_TAGS = (
    f'<link rel="stylesheet" href="../../{PREFIX}/series.css">'
    f'<script src="../../{PREFIX}/settings.js" defer></script></head>'
).encode()

DATA = {row["id"]: row for row in fixture.build()}
POSTERS: dict[str, bytes] = {}
REQUESTS: list[dict] = []


def hash_of(series, key):
    return next(
        (r for s in series["seasons"] for r in s["releases"] if r["hash"] == key),
        series["integrale"]["release"] if series["integrale"] and series["integrale"]["release"]["hash"] == key else None,
    )


def seed_requests():
    now = time.time()
    REQUESTS.clear()

    def row(rid, who, account, sid, seasons, pre, hours, follow=False):
        series = DATA[sid]
        size = sum(hash_of(series, h)["size"] for h in pre)
        REQUESTS.append({
            "id": rid, "who": who, "account": account, "series": sid, "title": series["title"], "year": series["year"],
            "seasons": seasons, "follow": follow, "pre": pre, "quoted": size, "chosen": None, "state": "pending",
            "created": now - hours * 3600, "updated": now - hours * 3600, "answer": "", "unread": False,
        })

    s = DATA["tv-95396"]
    row("a" * 31 + "1", "Julie", "julie", "tv-95396", [1, 2], [s["integrale"]["release"]["hash"]], 20)
    b = DATA["tv-1396"]
    row("a" * 31 + "2", "Marc", "marc", "tv-1396", [3, 4, 5], [b["integrale"]["release"]["hash"]], 52)
    t = DATA["tv-100088"]
    row("a" * 31 + "3", "Julie", "julie", "tv-100088", [1], [t["seasons"][0]["releases"][0]["hash"]], 90, follow=True)


def quota():
    mine = [r for r in REQUESTS if r["account"] == "camille" and r["state"] in ("pending", "accepted")]
    return {
        "requests_left": max(0, 5 - len(mine)),
        "bytes_left": max(0, 120 * 10**9 - sum(r["quoted"] for r in mine)),
        "pending_left": max(0, 3 - sum(1 for r in mine if r["state"] == "pending")),
        "reset": time.time() + 4 * 86400,
    }


def member_rows():
    out = []
    for r in sorted((r for r in REQUESTS if r["account"] == "camille"), key=lambda r: -r["created"]):
        out.append({
            "id": r["id"], "kind": "request", "state": r["state"], "title": r["title"], "year": str(r["year"]),
            "note": "", "infohash": "", "release": "", "size": r["quoted"], "film": r["series"], "series": True,
            "seasons": r["seasons"], "follow": r["follow"], "quoted": r["quoted"], "chosen_size": r["chosen"],
            "created": r["created"], "updated": r["updated"], "unread": r["unread"], "answer": r["answer"],
            "answered_by": "Viet" if r["answer"] else "", "shared_with": 1 if r["id"][-1] in "12" else 0,
        })
    return out


def review_rows():
    out = []
    for r in sorted(REQUESTS, key=lambda r: -r["created"]):
        series = DATA[r["series"]]
        asked = []
        for n in r["seasons"]:
            season = series["seasons"][n - 1]
            asked.append({"n": n, "state": season["state"], "count": season["count"], "releases": season["releases"]})
        out.append({
            "id": r["id"], "kind": "request", "state": r["state"], "title": r["title"], "year": str(r["year"]),
            "requester": r["who"], "account": r["account"], "note": "", "infohash": "", "release": "", "film": "",
            "size": r["quoted"], "quoted": r["quoted"], "chosen_size": r["chosen"], "created": r["created"], "updated": r["updated"],
            "series": {
                "id": series["id"], "poster": f"api/{PREFIX}/poster-{series['id']}.png", "asked": asked,
                "integrale": series["integrale"], "pre": r["pre"], "follow": r["follow"], "airing": series["airing"],
                "owned": series["owned"], "seasons": len(series["seasons"]),
            },
            "quota": {"requests_left": 3, "bytes_left": 60 * 10**9}, "approval_limits": {"count_left": 3, "bytes_left": 60 * 10**9},
            "events": [{"at": r["created"], "state": "pending", "note": ""}] + (
                [{"at": r["updated"], "state": r["state"], "note": r["answer"]}] if r["state"] != "pending" else []),
        })
    return out


class Preview:
    """Adds the preview files to the real pages; serves them, the posters and the preview routes."""

    def __init__(self, app):
        self.app = app

    async def reply(self, send, body: bytes, kind: str, status=200):
        await send({"type": "http.response.start", "status": status, "headers": [
            (b"content-type", kind.encode()), (b"content-length", str(len(body)).encode()), (b"cache-control", b"no-store")]})
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path, method = scope["path"], scope["method"]
        for prefix in (f"/{PREFIX}/", f"/api/{PREFIX}/"):
            if path.startswith(prefix):
                return await self.own(path.removeprefix(prefix), method, scope, receive, send)
        if path == "/api/requests" and method == "GET":
            return await self.reply(send, b'{"requests":[],"household":[],"quota":{},"unread":0}', "application/json")
        if path == "/api/requests/review" and method == "GET":
            body = {"requests": review_rows(), "margin": {"capacity": 900 * 10**9, "downloading": 120 * 10**9,
                                                           "pending": sum(r["quoted"] for r in REQUESTS if r["state"] == "pending"), "stale": False}}
            return await self.reply(send, json.dumps(body).encode(), "application/json")
        answer = re.fullmatch(r"/api/requests/(a{31}\d|[0-9a-f]{32})/(accept|refuse)", path)
        if answer and method == "POST":
            body = json.loads(await self.read(receive) or b"{}")
            row = next((r for r in REQUESTS if r["id"] == answer[1]), None)
            if row:
                row.update(state="accepted" if answer[2] == "accept" else "refused", updated=time.time(), unread=True,
                           answer=body.get("note", ""))
                if answer[2] == "accept":
                    row["chosen"] = sum(hash_of(DATA[row["series"]], h)["size"] for h in body.get("infohashes", row["pre"]))
            return await self.reply(send, b"{}", "application/json")
        if path == "/" and method == "GET":
            return await self.inject(scope, receive, send, HOST_TAGS)
        if path == "/static/media/view.html":
            return await self.inject(scope, receive, send, MEDIA_CSS, MEDIA_SCRIPT)
        if path == "/static/settings/view.html":
            return await self.inject(scope, receive, send, SETTINGS_TAGS)
        if path == "/static/settings/members.js":
            return await self.patch_members(scope, receive, send)
        await self.app(scope, receive, send)

    @staticmethod
    async def read(receive) -> bytes:
        body, more = b"", True
        while more:
            message = await receive()
            body += message.get("body", b"")
            more = message.get("more_body", False)
        return body

    async def own(self, name, method, scope, receive, send):
        if name == "fixture.json":
            return await self.reply(send, json.dumps({"series": list(DATA.values())}).encode(), "application/json")
        poster = re.fullmatch(r"poster-([a-z]+-\d+)\.png", name)
        if poster and poster[1] in DATA:
            if poster[1] not in POSTERS:
                row = DATA[poster[1]]
                POSTERS[poster[1]] = fixture.poster(row["title"], row["colours"])
            return await self.reply(send, POSTERS[poster[1]], "image/png")
        if name == "requests":
            return await self.reply(send, json.dumps({"requests": member_rows(), "quota": quota(), "unread": sum(1 for r in member_rows() if r["unread"])}).encode(), "application/json")
        if name in ("ask", "cancel", "seen", "reset"):
            body = json.loads(await self.read(receive) or b"{}")
            if name == "ask":
                REQUESTS.append({"id": "b" * 31 + str(len(REQUESTS) % 10), "who": "Camille", "account": "camille", "series": body["series"],
                                 "title": DATA[body["series"]]["title"], "year": DATA[body["series"]]["year"], "seasons": body["seasons"],
                                 "follow": bool(body.get("follow")), "pre": body["pre"], "quoted": body["quote"], "chosen": None,
                                 "state": "pending", "created": time.time(), "updated": time.time(), "answer": "", "unread": False})
            elif name == "cancel":
                for r in REQUESTS:
                    if r["id"] == body["id"] and r["state"] == "pending":
                        r.update(state="cancelled", updated=time.time())
            elif name == "seen":
                for r in REQUESTS:
                    r["unread"] = False
            else:
                seed_requests()
            return await self.reply(send, b"{}", "application/json")
        file = HERE / name
        if "/" not in name and file.suffix in TYPES and file.is_file():
            return await self.reply(send, file.read_bytes(), TYPES[file.suffix])
        if name == "signin":
            return await self.sign_in(scope, send)
        return await self.reply(send, b"Not found", "text/plain", 404)

    async def capture(self, scope, receive):
        start, chunks = {}, []
        scope = {**scope, "headers": [(k, v) for k, v in scope["headers"] if k != b"accept-encoding"]}

        async def grab(message):
            if message["type"] == "http.response.start":
                start.update(message)
            elif message["type"] == "http.response.body":
                chunks.append(message.get("body", b""))

        await self.app(scope, receive, grab)
        return start, b"".join(chunks)

    async def inject(self, scope, receive, send, tags, swap=None):
        start, body = await self.capture(scope, receive)
        body = body.replace(b"</head>", tags, 1)
        if swap:
            body = body.replace(*swap, 1)
        headers = [(k, v) for k, v in start["headers"] if k not in (b"content-length", b"etag", b"last-modified")]
        # The panel frames may call this server's preview routes (the real ones do not exist yet).
        headers = [(k, v + b"; connect-src 'self'" if k == b"content-security-policy" else v) for k, v in headers]
        await send({**start, "headers": [*headers, (b"content-length", str(len(body)).encode()), (b"cache-control", b"no-store")]})
        await send({"type": "http.response.body", "body": body})

    async def patch_members(self, scope, receive, send):
        # The one change of the Settings page: the "films" Permission is called "Films et séries".
        start, body = await self.capture(scope, receive)
        text = body.decode().replace('["films", say("Films", "Films")]', '["films", say("Films and series", "Films et séries")]')
        body = text.encode()
        headers = [(k, v) for k, v in start["headers"] if k not in (b"content-length", b"etag", b"last-modified")]
        await send({**start, "headers": [*headers, (b"content-length", str(len(body)).encode()), (b"cache-control", b"no-store")]})
        await send({"type": "http.response.body", "body": body})

    async def sign_in(self, scope, send):
        body = json.dumps({"password": PASSWORD}).encode()
        host = dict(scope["headers"]).get(b"host", f"127.0.0.1:{PORT}".encode())
        login = {**scope, "method": "POST", "path": "/api/login", "raw_path": b"/api/login", "query_string": b"",
                 "headers": [(b"host", host), (b"origin", b"http://" + host), (b"content-type", b"application/json"),
                             (b"content-length", str(len(body)).encode()), (b"x-torrentlinker", b"1")]}
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
            await send({"type": "http.response.start", "status": 303, "headers": [(b"location", b"/"), *[(b"set-cookie", c) for c in cookies]]})
            await send({"type": "http.response.body", "body": b""})
            return
        await self.reply(send, b"Preview sign-in failed: " + b"".join(answer[1:]), "text/plain; charset=utf-8", 502)


def add_members(app):
    """Two Members for the Settings page: one with no limit, one under 12. In process: no socket."""
    from fastapi.testclient import TestClient

    owner = TestClient(app, base_url=f"http://127.0.0.1:{PORT}")
    owner.headers["X-TorrentLinker"] = "1"
    owner.post("/api/login", json={"password": PASSWORD})
    for name, login, limit in (("Camille", "camille", None), ("Léo", "leo", "12")):
        owner.post("/api/members", json={
            "name": name, "login": login, "password": "preview-member-password-only", "age_limit": limit,
            "permissions": ["films", "series", "anime", "request"],
            "caps": {"requests_per_week": 5, "bytes_per_week": 120 * 10**9, "pending": 3},
        })


def main():
    connect = socket.socket.connect

    def this_server_only(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            host, port = address[0], address[1]
            if not (ipaddress.ip_address(host).is_loopback and port == PORT):
                raise OSError("The tracker-series preview refuses outside connections")
        return connect(sock, address)

    seed_requests()
    with TemporaryDirectory(prefix="tl-tracker-series-") as temp:
        config, setup, client, _ = prepared(Path(temp))
        setup.settings.language = "fr"
        setup.settings.theme = "dark"
        setup.save()
        app = create_app(config, password=PASSWORD, service_override=setup, monitor_verifications=False, members_enabled=True)
        media_class = type(app.state.assistant.agent.media)
        add_members(app)
        fixture.seed(app, setup, Path(temp) / "downloads")
        print(f"Tracker Series preview: http://127.0.0.1:{PORT}/{PREFIX}/signin", flush=True)
        with (
            patch.object(socket.socket, "connect", this_server_only),
            patch.object(media_class, "enrich", lambda *a, **k: "ok"),
            patch.object(media_class, "tracker_refresh", lambda *a, **k: "complete"),
            patch.object(media_class, "films_refresh", lambda *a, **k: None),
            patch("torrentlinker.web.media.start_films_index", lambda *a, **k: None),
        ):
            uvicorn.run(Preview(app), host="127.0.0.1", port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
