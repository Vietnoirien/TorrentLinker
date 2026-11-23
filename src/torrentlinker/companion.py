"""Packaged browser companion and desktop loopback receiver (started on demand)."""

from __future__ import annotations

import io
import json
import threading
import zipfile
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import cast
from urllib.parse import quote, urlsplit

from torrentlinker.companion_downloads import MAX_RESULT
from torrentlinker.profile_workspace import COMPANION_ROUTES, ProfileWorkspace, extension_origin

EXTENSION_DIR = Path(__file__).parent / "companion_extension"


def bundled_version() -> str:
    return str(json.loads((EXTENSION_DIR / "manifest.json").read_text())["version"])


def extension_files(web_origin: str | None = None) -> dict[str, bytes]:
    """The companion's files; receiver.json and the host permissions name only this server."""
    files: dict[str, bytes] = {}
    for path in sorted(EXTENSION_DIR.iterdir()):
        if not path.is_file():
            continue
        raw = path.read_bytes()
        origin = urlsplit(web_origin) if web_origin else None
        if path.name == "receiver.json" and origin and origin.scheme == "https":
            raw = json.dumps({"webTarget": (web_origin or "").rstrip("/")}).encode()
        elif (
            path.name == "manifest.json" and origin and origin.scheme == "https" and origin.hostname
        ):
            manifest = json.loads(raw)
            host = f"https://{origin.hostname}/*"
            manifest["host_permissions"].append(host)
            manifest["externally_connectable"]["matches"].append(host)
            raw = json.dumps(manifest, indent=2).encode()
        files[path.name] = raw
    return files


def extension_zip(web_origin: str | None = None) -> bytes:
    """Allow only this WebUI server to initiate a remote connection."""
    result = io.BytesIO()
    with zipfile.ZipFile(result, "w", zipfile.ZIP_DEFLATED) as bundle:
        for name, raw in extension_files(web_origin).items():
            bundle.writestr(f"torrentlinker-companion/{name}", raw)
    return result.getvalue()


def connection_url(address: str, code: str, account_id: str, tracker: str = "c411") -> str:
    # tr4ker has no API profile: its tab names the account when the extension pairs.
    payload = {"target": address, "code": code, "accountId": account_id}
    if tracker != "c411":
        payload = {"target": address, "code": code, "tracker": tracker}
    return address + "/companion/connect#" + quote(json.dumps(payload), safe="")


def connection_asset(path: str) -> tuple[bytes, str] | None:
    names = {
        "/companion/connect": ("companion-connect.html", "text/html"),
        "/companion/connect.js": ("companion-connect.js", "text/javascript"),
        "/companion/connect.css": ("companion-connect.css", "text/css"),
    }
    if path not in names:
        return None
    name, kind = names[path]
    return (Path(__file__).parent / "web" / "static" / name).read_bytes(), kind


class CompanionReceiver:
    def __init__(
        self,
        workspace: ProfileWorkspace,
        credentials: Callable[[], tuple[str, str]],
        port: int = 8767,
    ):
        class Handler(BaseHTTPRequestHandler):
            def setup(self) -> None:
                super().setup()
                self.connection.settimeout(5)

            def log_message(self, *_args: object) -> None:
                pass  # Never log account data or pairing credentials.

            def respond(self, status: int, body: dict | None = None) -> None:
                raw = json.dumps(body or {}).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Cache-Control", "no-store")
                origin = self.headers.get("Origin", "")
                if extension_origin(origin):
                    self.send_header("Access-Control-Allow-Origin", origin)
                    self.send_header("Vary", "Origin")
                    if status == 204:
                        self.send_header("Access-Control-Allow-Methods", "POST")
                        self.send_header(
                            "Access-Control-Allow-Headers", "content-type, authorization"
                        )
                self.end_headers()
                if status != 204:
                    self.wfile.write(raw)

            def allowed(self) -> bool:
                return (
                    self.path in COMPANION_ROUTES
                    and self.headers.get("Host")
                    == f"127.0.0.1:{cast(ThreadingHTTPServer, self.server).server_port}"
                    and extension_origin(self.headers.get("Origin", ""))
                )

            def do_OPTIONS(self) -> None:
                self.respond(204 if self.allowed() else 403)

            def do_GET(self) -> None:
                asset = connection_asset(self.path)
                if not asset or self.headers.get("Host") != (
                    f"127.0.0.1:{cast(ThreadingHTTPServer, self.server).server_port}"
                ):
                    self.respond(404)
                    return
                raw, kind = asset
                self.send_response(200)
                self.send_header("Content-Type", kind + "; charset=utf-8")
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(raw)

            def do_POST(self) -> None:
                if not self.allowed():
                    self.respond(403, {"detail": "Use the paired browser extension."})
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    maximum = MAX_RESULT if self.path == "/api/companion/result" else 65536
                    if not 0 < length <= maximum:
                        raise ValueError("Request too large.")
                    body = json.loads(self.rfile.read(length))
                    if not isinstance(body, dict):
                        raise ValueError("Invalid JSON object.")
                    workspace.bind(*credentials())
                    result = workspace.receive(
                        self.path,
                        self.headers.get("Origin", ""),
                        self.headers.get("Authorization", ""),
                        body,
                        version=self.headers.get("X-TorrentLinker-Companion", ""),
                    )
                    self.respond(200, result)
                except PermissionError as error:
                    self.respond(403, {"detail": str(error)})
                except (ValueError, UnicodeError):
                    self.respond(
                        400, {"detail": "Invalid or expired snapshot. Read a new preview."}
                    )

        try:
            self.server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        except OSError:
            if not port or workspace.state()["paired"]:
                raise
            self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.address = f"http://127.0.0.1:{self.server.server_port}"
        workspace.remember_receiver(self.server.server_port)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
