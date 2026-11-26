"""Household Asks: a Viewer on a Shared Screen asks its account holder for a Tracker Film.

A Viewer never makes a Request (ADR-0022): it asks, and the ask waits in the holder's Médias
bell. The holder accepts, which turns it into the holder's own Request to the Owner on the
holder's quota, or refuses with an optional note. On the Owner's own account, accepting makes
no Request: the Owner chooses the release and downloads directly. The Viewer follows the ask
(pending, then the Request's own state) and may cancel it while it is pending. An ask the
Viewer was removed under, or whose holder was deleted, is gone with them.
"""

from __future__ import annotations

import time
from uuid import uuid4

from torrentlinker.accounts import OWNER, Accounts
from torrentlinker.member_requests import FilmAsk, Requests

STATES = ("pending", "accepted", "refused", "cancelled")


class HouseholdAsks:
    def __init__(self, accounts: Accounts, requests: Requests):
        self.accounts, self.requests = accounts, requests
        self.db, self.lock = accounts.db, accounts.lock
        with self.lock, self.db:
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS household_asks (
                    id TEXT PRIMARY KEY, account TEXT NOT NULL, viewer TEXT NOT NULL,
                    screen TEXT NOT NULL DEFAULT '', film TEXT NOT NULL, title TEXT NOT NULL,
                    year TEXT NOT NULL DEFAULT '', size INTEGER NOT NULL, state TEXT NOT NULL,
                    note TEXT NOT NULL DEFAULT '', request TEXT NOT NULL DEFAULT '',
                    seen INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL, updated REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS household_asks_account
                    ON household_asks(account, state);
            """)

    def ask(self, account: str, viewer: str, screen: str, film: FilmAsk) -> dict:
        """A Viewer's ask for a film; the same film is asked once while it waits."""
        now = time.time()
        with self.lock, self.db:
            if self.db.execute(
                "SELECT 1 FROM household_asks WHERE account=? AND viewer=? AND film=? "
                "AND state='pending'",
                (account, viewer, film.film),
            ).fetchone():
                raise ValueError("You have already asked for this film.")
            identifier = uuid4().hex
            self.db.execute(
                "INSERT INTO household_asks (id, account, viewer, screen, film, title, year, size,"
                " state, created, updated) VALUES (?,?,?,?,?,?,?,?,'pending',?,?)",
                (
                    identifier,
                    account,
                    viewer,
                    self.accounts.screen_name(screen) if screen else "",
                    film.film,
                    film.title,
                    film.year,
                    film.size,
                    now,
                    now,
                ),
            )
        return self.get(identifier)

    def get(self, identifier: str) -> dict:
        with self.lock:
            row = self.db.execute(
                "SELECT * FROM household_asks WHERE id=?", (identifier,)
            ).fetchone()
        if row is None:
            raise KeyError(identifier)
        return self._public(row)

    def _public(self, row) -> dict:
        found = {
            "id": row["id"],
            "film": row["film"],
            "title": row["title"],
            "year": row["year"],
            "size": row["size"],
            "state": row["state"],
            "note": row["note"],
            "screen": row["screen"],
            "viewer": self._viewer_name(row["account"], row["viewer"]),
            "created": row["created"],
            "request_state": "",
        }
        if row["request"]:
            try:
                found["request_state"] = self.requests.get(row["request"])["state"]
            except KeyError:
                pass
        return found

    def _viewer_name(self, account: str, viewer: str) -> str:
        found = next((p for p in self.accounts.profiles(account) if p["id"] == viewer), None)
        return found["name"] if found else ""

    def mine(self, account: str, viewer: str) -> dict:
        """What a Viewer asked, newest first, with the holder's name to say whom it asked."""
        with self.lock:
            rows = self.db.execute(
                "SELECT * FROM household_asks WHERE account=? AND viewer=? "
                "ORDER BY created DESC LIMIT 100",
                (account, viewer),
            ).fetchall()
        holder = "" if account == OWNER else self.accounts.display_name(account)
        return {"asks": [self._public(r) for r in rows], "holder": holder}

    def household(self, account: str) -> list[dict]:
        """The holder's drawer: what waits for an answer, then what was answered."""
        with self.lock:
            rows = self.db.execute(
                "SELECT * FROM household_asks WHERE account=? AND state IN ('pending','accepted',"
                "'refused') ORDER BY (state='pending') DESC, created DESC LIMIT 100",
                (account,),
            ).fetchall()
            known = {p["id"] for p in self.accounts.profiles(account)}
        return [self._public(r) for r in rows if r["viewer"] in known]

    def unseen(self, account: str) -> int:
        """Pending asks the holder has not yet opened the drawer on: the bell's badge."""
        with self.lock:
            return self.db.execute(
                "SELECT COUNT(*) FROM household_asks WHERE account=? AND state='pending' "
                "AND seen=0",
                (account,),
            ).fetchone()[0]

    def seen(self, account: str) -> None:
        with self.lock, self.db:
            self.db.execute("UPDATE household_asks SET seen=1 WHERE account=?", (account,))

    def cancel(self, account: str, viewer: str, identifier: str) -> dict:
        """The Viewer cancels its own ask while the holder has not answered."""
        with self.lock, self.db:
            row = self.db.execute(
                "SELECT state FROM household_asks WHERE id=? AND account=? AND viewer=?",
                (identifier, account, viewer),
            ).fetchone()
            if row is None:
                raise KeyError(identifier)
            if row["state"] != "pending":
                raise ValueError("Only a pending ask can be cancelled.")
            self._move(identifier, "cancelled")
        return self.get(identifier)

    def accept(self, account: str, identifier: str) -> dict:
        """The holder accepts: their own Request to the Owner, on their quota (a reached cap
        refuses and the ask stays pending). On the Owner's account there is no Request: the
        Owner chooses the release next."""
        with self.lock, self.db:
            row = self._pending(account, identifier)
            request = ""
            if account != OWNER:
                request = self.requests.ask_film(
                    account, FilmAsk(row["film"], row["title"], row["year"], row["size"])
                )["id"]
            self._move(identifier, "accepted", request=request)
        return self.get(identifier)

    def refuse(self, account: str, identifier: str, note: str = "") -> dict:
        note = note.strip()
        if len(note) > 500:
            raise ValueError("Keep the note under 500 characters.")
        with self.lock, self.db:
            self._pending(account, identifier)
            self._move(identifier, "refused", note=note)
        return self.get(identifier)

    def _pending(self, account: str, identifier: str):
        row = self.db.execute(
            "SELECT * FROM household_asks WHERE id=? AND account=?", (identifier, account)
        ).fetchone()
        if row is None:
            raise KeyError(identifier)
        if row["state"] != "pending":
            raise ValueError("This ask has already been answered.")
        return row

    def _move(self, identifier: str, state: str, *, note: str = "", request: str = "") -> None:
        self.db.execute(
            "UPDATE household_asks SET state=?, note=?, request=?, updated=?, seen=1 WHERE id=?",
            (state, note, request, time.time(), identifier),
        )
