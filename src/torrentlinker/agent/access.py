"""Persistent owner permissions. MCP cannot create tokens or approve proposals."""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import threading
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Grant(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    clients: list[str] = Field(min_length=1, max_length=32)
    mode: Literal["propose", "execute"] = "propose"
    permissions: list[Literal["downloads", "controls", "reseed", "uploads"]] = Field(
        default_factory=list, max_length=4
    )
    daily_bytes: int = Field(default=10 * 1024**3, ge=0)
    daily_torrents: int = Field(default=20, ge=0, le=1000)
    reserve_bytes: int = Field(default=10 * 1024**3, ge=0)


class Access:
    def __init__(self, directory: Path):
        self.lock = threading.RLock()
        self.db = sqlite3.connect(directory / "agents.sqlite", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        with self.db:
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT);
                CREATE TABLE IF NOT EXISTS grants (
                    id TEXT PRIMARY KEY, digest TEXT UNIQUE, body TEXT, revoked INTEGER DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS proposals (
                    id TEXT PRIMARY KEY, grant_id TEXT, request_id TEXT, body TEXT,
                    fingerprint TEXT, created REAL, status TEXT, job_id TEXT DEFAULT '',
                    UNIQUE(grant_id, request_id)
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY, created REAL, grant_id TEXT, action TEXT, detail TEXT
                );
                CREATE TABLE IF NOT EXISTS reservations (
                    proposal_id TEXT PRIMARY KEY, grant_id TEXT, day TEXT, bytes INTEGER,
                    torrents INTEGER, disk TEXT
                );
                CREATE TABLE IF NOT EXISTS goals (
                    id TEXT PRIMARY KEY, grant_id TEXT, body TEXT, revision INTEGER
                );
            """)
            if "storage_reconciled" not in {
                row[1] for row in self.db.execute("PRAGMA table_info(reservations)")
            }:
                self.db.execute(
                    "ALTER TABLE reservations ADD COLUMN storage_reconciled INTEGER DEFAULT 0"
                )

    @property
    def enabled(self) -> bool:
        with self.lock:
            row = self.db.execute("SELECT value FROM config WHERE key='enabled'").fetchone()
            return bool(row and row[0] == "true")

    def enable(self, value: bool) -> None:
        with self.lock, self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO config VALUES ('enabled', ?)", (json.dumps(value),)
            )

    def create(self, grant: Grant, *, internal: bool = False) -> dict:
        identifier, token = secrets.token_hex(12), secrets.token_urlsafe(32)
        if internal:
            identifier = "assistant-" + identifier
        with self.lock, self.db:
            self.db.execute(
                "INSERT INTO grants (id,digest,body) VALUES (?,?,?)",
                (identifier, hashlib.sha256(token.encode()).hexdigest(), grant.model_dump_json()),
            )
        return {"id": identifier, **grant.model_dump(), "token": token}

    def grant(self, identifier: str) -> Grant:
        with self.lock:
            row = self.db.execute("SELECT * FROM grants WHERE id=?", (identifier,)).fetchone()
            if (
                row is None
                or row["revoked"]
                or (not identifier.startswith("assistant-") and not self.enabled)
            ):
                raise PermissionError("Agent access is disabled or revoked.")
            return Grant.model_validate_json(row["body"])

    def update_internal(self, identifier: str, grant: Grant) -> None:
        """Edit owner-managed chat permissions without resetting its usage ledger."""
        with self.lock, self.db:
            if not identifier.startswith("assistant-"):
                raise ValueError("Only internal Assistant permissions can be edited here.")
            self.grant(identifier)
            self.db.execute(
                "UPDATE grants SET body=? WHERE id=?", (grant.model_dump_json(), identifier)
            )
        self.event(identifier, "permissions updated")

    def authenticate(self, token: str) -> str:
        with self.lock:
            row = self.db.execute(
                "SELECT id FROM grants WHERE digest=?",
                (hashlib.sha256(token.encode()).hexdigest(),),
            ).fetchone()
            if not token or row is None or row[0].startswith("assistant-"):
                raise PermissionError("Invalid agent token.")
            self.grant(row[0])
            return str(row[0])

    def revoke(self, identifier: str) -> None:
        with self.lock, self.db:
            self.db.execute("UPDATE grants SET revoked=1 WHERE id=?", (identifier,))
        self.event(identifier, "revoked")

    def event(self, identifier: str, action: str, detail: str = "") -> None:
        with self.lock, self.db:
            self.db.execute(
                "INSERT INTO events (created,grant_id,action,detail) VALUES (?,?,?,?)",
                (time.time(), identifier, action, detail),
            )
            self.db.execute(
                "DELETE FROM events WHERE id NOT IN "
                "(SELECT id FROM events ORDER BY id DESC LIMIT 1000)"
            )

    def snapshot(self) -> dict:
        with self.lock:
            connections = [
                {"id": r["id"], **json.loads(r["body"]), "revoked": bool(r["revoked"])}
                for r in self.db.execute("SELECT * FROM grants")
            ]
            proposals = [
                {**dict(r), "body": json.loads(r["body"])}
                for r in self.db.execute("SELECT * FROM proposals ORDER BY created DESC LIMIT 100")
            ]
            return {
                "enabled": self.enabled,
                "connections": connections,
                "proposals": proposals,
                "activity": [
                    dict(r)
                    for r in self.db.execute("SELECT * FROM events ORDER BY id DESC LIMIT 100")
                ],
                "goals": [
                    {**dict(r), "body": json.loads(r["body"])}
                    for r in self.db.execute("SELECT * FROM goals")
                ],
            }
