"""Ephemeral, account-bound descriptor tests. No file or Torrent Client writes."""

from __future__ import annotations

import base64
import re
import secrets
from collections.abc import Callable
from typing import Any

from torrentlinker.torrent_meta import read_torrent

MAX_TORRENT = 8 * 1024 * 1024
MAX_RESULT = (MAX_TORRENT * 4 // 3) + 4096


class CompanionDownloads:
    """Called under the ProfileWorkspace lock; raw descriptors are never retained."""

    def __init__(self, clock: Callable[[], float]):
        self.clock = clock
        self.jobs: dict[str, dict[str, Any]] = {}
        self.last_poll = 0.0
        self.retry_at = 0.0
        self.blocked = False

    def clear(self) -> None:
        self.jobs.clear()
        self.last_poll = 0.0
        self.blocked = False
        # Re-pairing must not remove a server-requested cooldown.

    def _expire(self) -> None:
        now = self.clock()
        for key, job in list(self.jobs.items()):
            if now - job["created"] > 600:
                del self.jobs[key]
            elif job["status"] in ("pending", "running") and now > job["expires"]:
                job.update(status="failed", error="Companion timed out. No automatic retry.")

    def state(self) -> dict[str, Any]:
        self._expire()
        return {
            "available": self.last_poll > 0 and self.clock() - self.last_poll < 70,
            "retry_after": max(0, int(self.retry_at - self.clock() + 0.999)),
            "blocked": self.blocked,
        }

    @staticmethod
    def _public(job: dict[str, Any]) -> dict[str, Any]:
        return {
            k: v for k, v in job.items() if k not in ("actor", "request_id", "created", "expires")
        }

    def get(self, identifier: str, actor: str) -> dict[str, Any]:
        self._expire()
        job = self.jobs.get(identifier)
        if job is None or job["actor"] != actor:
            raise ValueError("Download test unavailable or expired.")
        return self._public(job)

    def submit(self, infohash: str, request_id: str, actor: str) -> dict[str, Any]:
        self._expire()
        if not re.fullmatch(r"[a-fA-F0-9]{40}", infohash):
            raise ValueError("Use a torrent info hash, not a URL.")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", request_id):
            raise ValueError(
                "Use a stable request ID of 1–100 letters, digits, underscores or dashes."
            )
        infohash = infohash.lower()
        for job in self.jobs.values():
            if job["actor"] == actor and job["request_id"] == request_id:
                if job["infohash"] != infohash:
                    raise ValueError("Request ID already used for another torrent.")
                return self._public(job)
        state = self.state()
        if not state["available"]:
            raise ValueError("Connect the updated companion and keep a signed-in c411 tab open.")
        if self.blocked:
            raise ValueError("c411 refused the session. Check the account and reconnect.")
        if state["retry_after"]:
            raise ValueError(f"c411 requested a wait. Retry after {state['retry_after']} seconds.")
        if any(j["status"] in ("pending", "running") for j in self.jobs.values()):
            raise ValueError("A companion download is already in progress.")
        if len(self.jobs) >= 256:
            raise ValueError("Recent test history is full. Wait for older results to expire.")
        now = self.clock()
        identifier = secrets.token_hex(16)
        job = dict(
            id=identifier,
            infohash=infohash,
            request_id=request_id,
            actor=actor,
            created=now,
            expires=now + 90,
            status="pending",
        )
        self.jobs[identifier] = job
        return self._public(job)

    def poll(self, account: str) -> dict[str, Any]:
        self._expire()
        self.last_poll = self.clock()
        for job in self.jobs.values():
            if job["status"] == "pending":
                job["status"] = "running"
                return {
                    "command": {"id": job["id"], "infohash": job["infohash"], "accountId": account}
                }
        return {"command": None}

    def receive(self, body: dict[str, Any]) -> dict[str, bool]:
        self._expire()
        identifier = body.get("id")
        if not isinstance(identifier, str):
            raise ValueError("Invalid download test ID.")
        job = self.jobs.get(identifier)
        if job is None or job["status"] != "running":
            raise ValueError("No active download test matches this result.")
        status = body.get("status")
        if type(status) is not int or not 0 <= status <= 599:
            raise ValueError("Invalid HTTP status.")
        job.update(status="failed", http_status=status, discarded=True)
        if status != 200:
            job["error"] = "The session download was refused or unavailable."
            if status == 429:
                wait = body.get("retryAfter", 60)
                if type(wait) is not int or not 0 <= wait <= 2147483647:
                    wait = 60
                self.retry_at = max(self.retry_at, self.clock() + max(60, wait))
                job["retry_after"] = max(60, wait)
            if status in (401, 403):
                self.blocked = True
            return {"accepted": True}
        try:
            encoded = body.get("data")
            if not isinstance(encoded, str) or len(encoded) > MAX_RESULT:
                raise ValueError()
            raw = base64.b64decode(encoded, validate=True)
            if not 0 < len(raw) <= MAX_TORRENT:
                raise ValueError()
            meta = read_torrent(raw)
            if meta.infohash.lower() != job["infohash"] or not meta.files:
                raise ValueError()
            job.update(status="complete", bytes=len(raw), files=len(meta.files))
        except Exception:
            # Never expose parser errors, announce URLs or arbitrary tracker bodies.
            job["error"] = "Invalid torrent metadata or unexpected info hash."
        return {"accepted": True}
