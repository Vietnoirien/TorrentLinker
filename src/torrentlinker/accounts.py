"""Accounts that share a server: the Owner and Members, their Permissions and caps (ADR-0022)."""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from uuid import uuid4

OWNER = "owner"  # the fixed account of the Owner; never restricted, edited or deleted
SESSION_IDLE = 30 * 86400  # a Member's session ends after 30 days of disuse


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
                CREATE TABLE IF NOT EXISTS sessions (
                    digest TEXT PRIMARY KEY,
                    account TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
                    created REAL NOT NULL, used REAL NOT NULL
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

    def create(
        self,
        name: str,
        login: str,
        permissions: Iterable[Permission] = (),
        *,
        password: str = "",
        proxy_user: str = "",
    ) -> str:
        """Add a Member with these Permissions, signing in with this password or proxy name."""
        identifier = uuid4().hex
        with self.lock, self.db:
            self.db.execute(
                "INSERT INTO accounts (id, name, created) VALUES (?,'',?)",
                (identifier, time.time()),
            )
            self._identify(identifier, name, login, proxy_user)
            if password:
                self._password(identifier, password)
            self.db.execute("INSERT INTO caps (account) VALUES (?)", (identifier,))
            self._grant(identifier, permissions)
        return identifier

    def update(self, account: str, name: str, login: str, proxy_user: str = "") -> None:
        """Rename a Member, or change how they sign in."""
        with self.lock, self.db:
            self._member(account)
            self._identify(account, name, login, proxy_user)

    def _identify(self, account: str, name: str, login: str, proxy_user: str) -> None:
        name, login = name.strip(), login.strip()
        if not name or not login or len(name) > 100 or len(login) > 100:
            raise ValueError("Give the Member a display name and a sign-in name.")
        if self.db.execute(
            "SELECT 1 FROM accounts WHERE login=? COLLATE NOCASE AND id<>?", (login, account)
        ).fetchone():
            raise ValueError("This sign-in name is already used.")
        self.db.execute("UPDATE accounts SET name=?, login=? WHERE id=?", (name, login, account))
        self._proxy_user(account, proxy_user)

    def set_proxy_user(self, account: str, proxy_user: str) -> None:
        """The name the trusted proxy sends for this account; the Owner may have one too."""
        with self.lock, self.db:
            if account != OWNER:
                self._member(account)
            self._proxy_user(account, proxy_user)

    def _proxy_user(self, account: str, proxy_user: str) -> None:
        proxy_user = proxy_user.strip()
        if len(proxy_user) > 200:
            raise ValueError("The proxy's user name is too long.")
        if (
            proxy_user
            and self.db.execute(
                "SELECT 1 FROM accounts WHERE proxy_user=? COLLATE NOCASE AND id<>?",
                (proxy_user, account),
            ).fetchone()
        ):
            raise ValueError("Another account already has this proxy user name.")
        self.db.execute(
            "UPDATE accounts SET proxy_user=? WHERE id=?", (proxy_user or None, account)
        )

    def by_proxy_user(self, proxy_user: str) -> str | None:
        with self.lock:
            row = self.db.execute(
                "SELECT id FROM accounts WHERE proxy_user=? COLLATE NOCASE", (proxy_user,)
            ).fetchone()
        return row["id"] if row else None

    def proxy_users(self) -> bool:
        """Whether any account is named by the proxy; until then its user header is ignored."""
        with self.lock:
            return bool(
                self.db.execute("SELECT 1 FROM accounts WHERE proxy_user IS NOT NULL").fetchone()
            )

    def members(self) -> list[dict]:
        with self.lock:
            rows = self.db.execute(
                "SELECT * FROM accounts WHERE id<>? ORDER BY name COLLATE NOCASE", (OWNER,)
            ).fetchall()
            granted = self.db.execute("SELECT * FROM permissions").fetchall()
        known = {p.value for p in Permission}
        return [
            {
                "id": r["id"],
                "name": r["name"],
                "login": r["login"] or "",
                "proxy_user": r["proxy_user"] or "",
                "disabled": bool(r["disabled"]),
                "has_password": bool(r["password"]),
                "permissions": sorted(
                    g["permission"]
                    for g in granted
                    if g["account"] == r["id"] and g["permission"] in known
                ),
                "caps": vars(self.caps(r["id"])),
            }
            for r in rows
        ]

    def owner_proxy_user(self) -> str:
        with self.lock:
            row = self.db.execute("SELECT proxy_user FROM accounts WHERE id=?", (OWNER,)).fetchone()
        return row["proxy_user"] or ""

    def set_password(self, account: str, password: str) -> None:
        """Change a Member's password; every session of the account ends."""
        with self.lock, self.db:
            self._member(account)
            self._password(account, password)
            self.db.execute("DELETE FROM sessions WHERE account=?", (account,))

    def _password(self, account: str, password: str) -> None:
        if not 12 <= len(password) <= 1024:
            raise ValueError("Use a password of at least 12 characters.")
        salt = secrets.token_bytes(16)
        stored = f"scrypt${salt.hex()}${scrypt(password, salt).hex()}"
        self.db.execute("UPDATE accounts SET password=? WHERE id=?", (stored, account))

    def verify(self, login: str, password: str) -> str | None:
        """The enabled Member signing in with this name and password, or None."""
        with self.lock:
            row = self.db.execute(
                "SELECT id, password, disabled FROM accounts "
                "WHERE login=? COLLATE NOCASE AND id<>?",
                (login.strip(), OWNER),
            ).fetchone()
        stored = row["password"] if row else ""
        _, salt, digest = stored.split("$") if stored.count("$") == 2 else ("", "00" * 16, "")
        # Hash even for an unknown name, so the time taken does not tell which field was wrong.
        matches = secrets.compare_digest(scrypt(password, bytes.fromhex(salt)).hex(), digest)
        return row["id"] if row and matches and not row["disabled"] else None

    def open_session(self, account: str) -> str:
        token = secrets.token_urlsafe(32)
        now = time.time()
        with self.lock, self.db:
            self.db.execute("DELETE FROM sessions WHERE used<?", (now - SESSION_IDLE,))
            self.db.execute(
                "INSERT INTO sessions VALUES (?,?,?,?)", (digest(token), account, now, now)
            )
        return token

    def session(self, token: str) -> tuple[str, bool] | None:
        """The account of a Member's session, and whether its 30 days just started again."""
        if not token:
            return None
        now = time.time()
        with self.lock, self.db:
            row = self.db.execute(
                "SELECT account, used FROM sessions WHERE digest=?", (digest(token),)
            ).fetchone()
            if row is None:
                return None
            if row["used"] < now - SESSION_IDLE:
                self.db.execute("DELETE FROM sessions WHERE digest=?", (digest(token),))
                return None
            renewed = row["used"] < now - 3600  # written at most hourly
            if renewed:
                self.db.execute("UPDATE sessions SET used=? WHERE digest=?", (now, digest(token)))
        return row["account"], renewed

    def end_session(self, token: str) -> None:
        with self.lock, self.db:
            self.db.execute("DELETE FROM sessions WHERE digest=?", (digest(token),))

    def disable(self, account: str, disabled: bool = True) -> None:
        """Désactiver ends every session and keeps everything; Réactiver undoes it."""
        with self.lock, self.db:
            self._member(account)
            self.db.execute("UPDATE accounts SET disabled=? WHERE id=?", (disabled, account))
            self.db.execute("DELETE FROM sessions WHERE account=?", (account,))

    def delete(self, account: str) -> None:
        """Erase a disabled Member with their Permissions, caps and sessions."""
        with self.lock, self.db:
            self._member(account)
            row = self.db.execute("SELECT disabled FROM accounts WHERE id=?", (account,)).fetchone()
            if not row["disabled"]:
                raise ValueError("Disable the Member before deleting them.")
            self.db.execute("DELETE FROM accounts WHERE id=?", (account,))

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


def scrypt(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)


def digest(token: str) -> str:
    """Session tokens are random, so a fast hash is enough to keep them unusable at rest."""
    return hashlib.sha256(token.encode()).hexdigest()
