"""Bounded public chat images, isolated from application credentials and local files."""

from __future__ import annotations

import ipaddress
from functools import lru_cache
from urllib.parse import urlsplit

from torrentlinker.assistant.research import Research


def image_url(value: str) -> bool:
    try:
        url = urlsplit(value)
        host = url.hostname or ""
        if (
            len(value) > 4096
            or url.scheme not in {"http", "https"}
            or url.username is not None
            or url.password is not None
            or url.port not in {None, 80, 443}
            or not host
            or host.lower().rstrip(".").endswith((".localhost", ".local"))
            or host.lower().rstrip(".") == "localhost"
            or any(ord(c) < 32 for c in value)
        ):
            return False
        try:
            return ipaddress.ip_address(host).is_global
        except ValueError:
            return "." in host
    except ValueError:
        return False


@lru_cache(maxsize=16)
def fetch_image(url: str) -> tuple[bytes, str]:
    if not image_url(url):
        raise ValueError("Use a public HTTP(S) image URL.")
    # Research pins validated public DNS addresses and checks each redirect. No
    # application cookies, credentials or environment proxies are forwarded.
    _, kind, data = Research.fetch(url, maximum=5_000_000)
    mime = ""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        mime = "image/png"
    elif data.startswith(b"\xff\xd8\xff"):
        mime = "image/jpeg"
    elif data.startswith((b"GIF87a", b"GIF89a")):
        mime = "image/gif"
    elif data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        mime = "image/webp"
    if not mime or not kind.lower().startswith("image/"):
        raise ValueError("Use a direct PNG, JPEG, GIF or WebP image.")
    return data, mime
