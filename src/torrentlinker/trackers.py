"""The Trackers TorrentLinker fully supports (ADR-0025): c411 and tr4ker.

A Tracker owns one Indexer, an account and everything tracker-specific. This module holds
only what each one *is*; credentials live in the secret store under the names given here.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

C411 = "c411"
TR4KER = "tr4ker"
DEFAULT_TRACKER = C411


@dataclass(frozen=True)
class Tracker:
    id: str
    name: str
    origin: str
    indexer_url: str  # its Torznab endpoint; the Indexer's id is the Tracker's id
    announce_hosts: tuple[str, ...]  # every host a torrent of this Tracker announces to
    source: str  # the `info.source` tag its torrents carry
    capabilities: frozenset[str]

    @property
    def indexer_id(self) -> str:
        return self.id

    @property
    def api_key_secret(self) -> str:
        """c411's key keeps the name it always had."""
        return "indexer-api-key" if self.id == C411 else f"indexer-key-{self.id}"

    @property
    def passkey_secret(self) -> str:
        return f"indexer-passkey-{self.id}"

    @property
    def announce_secret(self) -> str:
        """The private Announce URL (it holds the passkey); c411's keeps its original name."""
        return "announce-url" if self.id == C411 else f"announce-url-{self.id}"

    def has(self, capability: str) -> bool:
        return capability in self.capabilities


TRACKERS: dict[str, Tracker] = {
    C411: Tracker(
        C411,
        "c411",
        "https://c411.org",
        "https://c411.org/api/torznab",
        ("c411.org", "tk.c411.tw"),
        "C411",
        frozenset(
            {"search", "catalogue", "profile", "upload", "zen", "rss", "community", "crossseed"}
        ),
    ),
    TR4KER: Tracker(
        TR4KER,
        "tr4ker",
        "https://tr4ker.net",
        "https://tr4ker.net/api",
        ("tr4ker.net",),
        "TR4KER",
        # No Zen: its credits are a learned estimate, not c411's schedule (ADR-0027).
        frozenset({"search", "catalogue", "profile", "upload", "rss", "community", "crossseed"}),
    ),
}


def tracker(identifier: str) -> Tracker:
    try:
        return TRACKERS[identifier]
    except KeyError:
        raise ValueError("Unknown Tracker.") from None


def _host(url: str) -> str:
    return (urlsplit(url if "//" in url else "//" + url).hostname or "").lower()


def tracker_of_host(host: str) -> Tracker | None:
    """The Tracker a host belongs to: its own announce hosts or a subdomain of them."""
    host = host.lower()
    for found in TRACKERS.values():
        if any(host == h or host.endswith("." + h) for h in found.announce_hosts):
            return found
    return None


def tracker_of_url(url: str) -> Tracker | None:
    """The Tracker an announce, Indexer or site URL points at, None for any other site."""
    return tracker_of_host(_host(url)) if url else None


def valid_order(order: object) -> list[str]:
    """A saved Tracker order made whole: known Trackers once each, then any it left out.
    c411 leads unless the order puts another first on purpose."""
    seen: list[str] = []
    for item in order if isinstance(order, list) else []:
        if isinstance(item, str) and item in TRACKERS and item not in seen:
            seen.append(item)
    return seen + [t for t in TRACKERS if t not in seen]
