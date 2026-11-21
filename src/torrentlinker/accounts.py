"""Accounts that share a server: the Owner and Members, their Permissions and caps (ADR-0022)."""

from __future__ import annotations

import sqlite3
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from uuid import uuid4

OWNER = "owner"  # the fixed account of the Owner; never restricted, edited or deleted


class Permission(StrEnum):
    """One thing a Member may see or do. What acts on the Owner's c411 account is never one."""

    FILMS = "films"
    SERIES = "series"
    ANIME = "anime"
    MUSIC = "music"
    MEDIA_CENTER = "media-center"
    ADULT = "adult"
    REQUEST = "request"
    WISH = "wish"
    SEARCH = "search"
    ASSISTANT = "assistant"
    QUEUE = "queue"
    TORRENTS = "torrents"
    APPROVE = "approve"
    MANAGE_MEMBERS = "manage-members"
    EDIT_RATINGS = "edit-ratings"


WATCH = (Permission.FILMS, Permission.SERIES, Permission.ANIME, Permission.MUSIC)
# A Viewer holds only these, never more than its account.
MEDIA = frozenset({*WATCH, Permission.MEDIA_CENTER, Permission.ADULT})


@dataclass(frozen=True)
class Actor:
    """Who makes a request: an account holder, or a Viewer watching under one."""

    account: str
    permissions: frozenset[Permission]
    viewer: str = ""

    @property
    def owner(self) -> bool:
        return self.account == OWNER and not self.viewer

    def holds(self, permission: Permission) -> bool:
        return self.owner or permission in self.permissions


OWNER_ACTOR = Actor(OWNER, frozenset(Permission))


@dataclass(frozen=True)
class Caps:
    """A Member's optional limits; None means no limit."""

    requests_per_week: int | None = None
    bytes_per_week: int | None = None
    pending: int | None = None
    assistant_per_day: int = 20


class Accounts:
    def __init__(self, directory: Path):
        self.lock = threading.RLock()
        self.db = sqlite3.connect(directory / "accounts.sqlite", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        with self.db:
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS accounts (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, login TEXT UNIQUE,
                    proxy_user TEXT UNIQUE, password TEXT NOT NULL DEFAULT '',
                    disabled INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS permissions (
                    account TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
                    permission TEXT NOT NULL, PRIMARY KEY(account, permission)
                );
                CREATE TABLE IF NOT EXISTS caps (
                    account TEXT PRIMARY KEY REFERENCES accounts(id) ON DELETE CASCADE,
                    requests_per_week INTEGER, bytes_per_week INTEGER, pending INTEGER,
                    assistant_per_day INTEGER NOT NULL DEFAULT 20
                );
            """)
            self.db.execute(
                "INSERT OR IGNORE INTO accounts (id, name, created) VALUES (?, 'Owner', ?)",
                (OWNER, time.time()),
            )

    def close(self) -> None:
        self.db.close()

    def actor(self, account: str) -> Actor | None:
        """The actor an account signs in as; None when it is unknown or disabled."""
        if account == OWNER:
            return OWNER_ACTOR
        with self.lock:
            row = self.db.execute("SELECT disabled FROM accounts WHERE id=?", (account,)).fetchone()
            if row is None or row["disabled"]:
                return None
            granted = self.db.execute(
                "SELECT permission FROM permissions WHERE account=?", (account,)
            ).fetchall()
        known = {p.value for p in Permission}
        return Actor(
            account,
            frozenset(Permission(r["permission"]) for r in granted if r["permission"] in known),
        )

    def create(self, name: str, login: str, permissions: Iterable[Permission] = ()) -> str:
        """Add a Member with these Permissions; sign-in comes with its password (#129)."""
        name, login = name.strip(), login.strip()
        if not name or not login or len(name) > 100 or len(login) > 100:
            raise ValueError("Give the Member a display name and a sign-in name.")
        identifier = uuid4().hex
        with self.lock, self.db:
            if self.db.execute(
                "SELECT 1 FROM accounts WHERE login=? COLLATE NOCASE", (login,)
            ).fetchone():
                raise ValueError("This sign-in name is already used.")
            self.db.execute(
                "INSERT INTO accounts (id, name, login, created) VALUES (?,?,?,?)",
                (identifier, name, login, time.time()),
            )
            self.db.execute("INSERT INTO caps (account) VALUES (?)", (identifier,))
            self._grant(identifier, permissions)
        return identifier

    def grant(self, account: str, permissions: Iterable[Permission]) -> None:
        """Replace a Member's Permissions. The Owner holds every Permission and cannot change."""
        with self.lock, self.db:
            self._member(account)
            self.db.execute("DELETE FROM permissions WHERE account=?", (account,))
            self._grant(account, permissions)

    def _grant(self, account: str, permissions: Iterable[Permission]) -> None:
        self.db.executemany(
            "INSERT INTO permissions VALUES (?,?)",
            [(account, Permission(p).value) for p in set(permissions)],
        )

    def caps(self, account: str) -> Caps:
        with self.lock:
            self._member(account)
            row = self.db.execute("SELECT * FROM caps WHERE account=?", (account,)).fetchone()
        if row is None:
            return Caps()
        return Caps(
            row["requests_per_week"],
            row["bytes_per_week"],
            row["pending"],
            row["assistant_per_day"],
        )

    def set_caps(self, account: str, caps: Caps) -> None:
        values = (caps.requests_per_week, caps.bytes_per_week, caps.pending)
        if any(v is not None and v < 0 for v in values) or not 0 <= caps.assistant_per_day:
            raise ValueError("Caps cannot be negative.")
        with self.lock, self.db:
            self._member(account)
            self.db.execute(
                "INSERT OR REPLACE INTO caps VALUES (?,?,?,?,?)",
                (account, *values, caps.assistant_per_day),
            )

    def _member(self, account: str) -> None:
        if account == OWNER:
            raise PermissionError("The Owner's account cannot be restricted.")
        if not self.db.execute("SELECT 1 FROM accounts WHERE id=?", (account,)).fetchone():
            raise ValueError("This Member no longer exists.")
