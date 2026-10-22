"""Every HTTP connection the app makes is created here, so the proxy applies to all of them.

Internet services (c411, TMDb, the Zen Lab snapshot, images, the speed test) go through
the proxy when one is set. The Torrent Client, usually on this computer or the local
network, goes through it only when the user asks.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

import httpx

SCHEMES = ("http", "https", "socks5", "socks5h")

_internet: str | None = None
_torrent_client: str | None = None


def proxy_url(address: str, username: str = "", password: str = "") -> str | None:
    """The proxy address with its credentials; None for no proxy. Raises ValueError when
    the address is not one the app can use."""
    address = address.strip()
    if not address:
        return None
    parts = urlsplit(address if "://" in address else f"http://{address}")
    if parts.scheme not in SCHEMES or not parts.hostname or not parts.port:
        raise ValueError(
            f"{address}: a proxy is http://, https://, socks5:// or socks5h:// "
            "followed by host:port"
        )
    netloc = f"{parts.hostname}:{parts.port}"
    if username:
        auth = quote(username, safe="")
        if password:
            auth += ":" + quote(password, safe="")
        netloc = f"{auth}@{netloc}"
    return urlunsplit((parts.scheme, netloc, "", "", ""))


def configure(proxy: str | None, for_torrent_client: bool = False) -> None:
    """Use `proxy` (from proxy_url) for every connection made from now on."""
    global _internet, _torrent_client
    _internet = proxy
    _torrent_client = proxy if for_torrent_client else None


def current() -> tuple[str | None, str | None]:
    """The proxies in use, internet and Torrent Client: connections kept open compare it
    to know when to be made again."""
    return _internet, _torrent_client


def client(*, torrent_client: bool = False, **kwargs: Any) -> httpx.Client:
    """An httpx client through the proxy that applies to this kind of connection."""
    proxy = _torrent_client if torrent_client else _internet
    return httpx.Client(proxy=proxy, **kwargs)


def requests_proxies() -> dict[str, str]:
    """The Torrent Client's proxy as the requests library takes it (qBittorrent's adapter);
    empty for a direct connection."""
    return {"http": _torrent_client, "https": _torrent_client} if _torrent_client else {}


def redacted(proxy: str | None) -> str:
    """The proxy address without its password, for messages and logs."""
    if not proxy:
        return ""
    parts = urlsplit(proxy)
    netloc = f"{parts.hostname}:{parts.port}"
    if parts.username:
        netloc = f"{parts.username}@{netloc}"
    return urlunsplit((parts.scheme, netloc, "", "", ""))


TRACE_URL = "https://c411.org/cdn-cgi/trace"  # c411 is behind Cloudflare, which echoes it


def address_seen(proxy: str | None) -> str:
    """The IP address c411 sees when the app connects through `proxy`."""
    with httpx.Client(proxy=proxy, timeout=20) as http:
        r = http.get(TRACE_URL)
        r.raise_for_status()
    for line in r.text.splitlines():
        if line.startswith("ip="):
            return line[3:]
    raise ValueError("c411 answered without saying which address it sees")
