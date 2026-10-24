"""Stdio bridge to a running application; never opens its database or credentials."""

from __future__ import annotations

import argparse
import json
import os
import sys
from urllib.parse import urlsplit

import httpx


def main() -> int:
    parser = argparse.ArgumentParser(description="Connect an MCP host to running TorrentLinker")
    parser.add_argument("--url", default="http://127.0.0.1:8790/mcp/")
    args = parser.parse_args()
    url = urlsplit(args.url)
    if (
        url.scheme not in {"http", "https"}
        or not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
    ):
        parser.error("Use an HTTP(S) MCP endpoint without credentials or query parameters.")
    if url.scheme == "http" and url.hostname not in {"127.0.0.1", "localhost", "::1"}:
        parser.error("Remote MCP endpoints require HTTPS.")
    token = os.getenv("TL_MCP_TOKEN", "")
    if not token:
        parser.error("Set TL_MCP_TOKEN to a token created in Settings → Agent access.")
    if sys.stdin is None or sys.stdout is None:
        parser.error("This build has no console streams. Connect using Streamable HTTP instead.")
    headers = {"Authorization": "Bearer " + token, "Accept": "application/json, text/event-stream"}
    with httpx.Client(
        headers=headers, timeout=60, follow_redirects=False, trust_env=False
    ) as client:
        while True:
            line = sys.stdin.readline(256_001)
            if not line:
                break
            if len(line) > 256_000:
                print("MCP message too large.", file=sys.stderr)
                return 1
            message = None
            try:
                message = json.loads(line)
                if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
                    raise ValueError("Invalid JSON-RPC message.")
                response = client.post(args.url, json=message)
                response.raise_for_status()
                if response.status_code == 202 or not response.content:
                    continue
                output = response.json()
                # Negotiated version is forwarded on subsequent HTTP requests.
                if message.get("method") == "initialize":
                    version = output.get("result", {}).get("protocolVersion")
                    if version:
                        client.headers["MCP-Protocol-Version"] = version
            except (ValueError, httpx.HTTPError):
                if isinstance(message, dict) and "id" not in message:
                    continue
                output = {
                    "jsonrpc": "2.0",
                    "id": message.get("id") if isinstance(message, dict) else None,
                    "error": {
                        "code": -32603,
                        "message": "Cannot complete MCP request. "
                        "Check TorrentLinker is running, access is enabled and the token is valid.",
                    },
                }
            print(json.dumps(output, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
