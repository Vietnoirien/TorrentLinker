"""Check public GitHub releases without blocking startup or requiring credentials."""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from torrentlinker import net

REPOSITORY = "https://github.com/Vietnoirien/TorrentLinker"
LATEST_RELEASE = "https://api.github.com/repos/Vietnoirien/TorrentLinker/releases/latest"
CHECK_INTERVAL = 24 * 60 * 60
log = logging.getLogger(__name__)


def installed_version() -> str:
    try:
        return version("torrentlinker")
    except PackageNotFoundError:
        return "unknown"


def release_version(tag: object) -> tuple[int, int, int] | None:
    # Preview and development builds are deliberately outside the stable channel.
    if not isinstance(tag, str) or not re.fullmatch(r"v?\d{1,6}\.\d{1,6}\.\d{1,6}", tag):
        return None
    major, minor, patch = tag.removeprefix("v").split(".")
    return int(major), int(minor), int(patch)


@dataclass(frozen=True)
class Release:
    tag: str

    @property
    def url(self) -> str:
        # Only a validated stable version is used; never open a URL supplied by the API.
        return f"{REPOSITORY}/releases/tag/{self.tag}"


def check_for_update(cache: Path, *, current: str | None = None) -> Release | None:
    """Return a newer stable release, reusing successful checks for one day.

    Call from a worker. Network and cache failures are nonfatal; the next launch
    or daily check retries them. No torrent or account information is sent.
    """
    running = release_version(current if current is not None else installed_version())
    if running is None:
        return None
    now = time.time()
    tag: str | None = None
    try:
        cached = json.loads(cache.read_text(encoding="utf-8"))
        if (
            isinstance(cached, dict)
            and isinstance(cached.get("checked_at"), (int, float))
            and 0 <= now - cached["checked_at"] < CHECK_INTERVAL
            and release_version(cached.get("tag")) is not None
        ):
            tag = cached["tag"]
    except (OSError, ValueError):
        pass
    if tag is None:
        try:
            with net.client(timeout=5.0) as client:
                response = client.get(
                    LATEST_RELEASE,
                    headers={
                        "Accept": "application/vnd.github+json",
                        "User-Agent": "TorrentLinker-update-check",
                        "X-GitHub-Api-Version": "2022-11-28",
                    },
                )
                response.raise_for_status()
                data = response.json()
            if (
                not isinstance(data, dict)
                or data.get("draft") is not False
                or data.get("prerelease") is not False
                or release_version(data.get("tag_name")) is None
            ):
                return None
            tag = data["tag_name"]
        except Exception as error:
            # A release check must never interrupt normal work, including proxy failures.
            log.debug("release check unavailable: %s", error)
            return None
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps({"checked_at": now, "tag": tag}), encoding="utf-8")
        except OSError:
            log.debug("could not save release check", exc_info=True)
    latest = release_version(tag)
    return Release(tag) if tag is not None and latest is not None and latest > running else None
