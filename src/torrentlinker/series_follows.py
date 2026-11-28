"""Suivre la série: each new complete season pack of a followed series becomes a pending Request.

A Member who asks for an airing series may follow it (ADR-0030). When a Tracker then holds a
full pack of a season that was not there when they followed, the Member gets a pending Request
for that season, which the Approver answers like any other: nothing downloads on its own, and
the Member sees it as new. Following stops when they say so.
"""

from __future__ import annotations

import json
import time
from typing import Any

from torrentlinker import tracker_series_view as view
from torrentlinker.member_requests import CapReached, FilmAsk


class SeriesFollows:
    def __init__(self, requests, media) -> None:
        self.requests, self.media = requests, media
        self.db, self.lock = requests.db, requests.lock
        with self.lock, self.db:
            self.db.executescript(
                """
                CREATE TABLE IF NOT EXISTS series_follow (
                    account TEXT NOT NULL, series TEXT NOT NULL, since REAL NOT NULL,
                    known TEXT NOT NULL DEFAULT '[]', PRIMARY KEY(account, series));
                """
            )

    def _packs(self, series: str) -> dict[int, dict[str, Any]]:
        """The seasons with a full pack on a Tracker now, with their best pack."""
        entry = next((e for e in self.media.series_index(fresh=True) if e["id"] == series), None)
        if entry is None:
            return {}
        found: dict[int, dict[str, Any]] = {}
        for release in entry["releases"]:
            if release["pack"] == "season" and len(release["seasons"]) == 1:
                n = release["seasons"][0]
                if n not in found or release["seeders"] > found[n]["seeders"]:
                    found[n] = release
        return found

    def follow(self, account: str, series: str) -> None:
        """Follow from now on: the packs already there are not new."""
        with self.lock, self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO series_follow VALUES (?,?,?,?)",
                (account, series, time.time(), json.dumps(sorted(self._packs(series)))),
            )

    def unfollow(self, account: str, series: str) -> None:
        with self.lock, self.db:
            self.db.execute(
                "DELETE FROM series_follow WHERE account=? AND series=?", (account, series)
            )

    def following(self, account: str) -> list[str]:
        rows = self.db.execute(
            "SELECT series FROM series_follow WHERE account=?", (account,)
        ).fetchall()
        return [r["series"] for r in rows]

    def tick(self, client_id: str) -> int:
        """Ask, for each follower, for the seasons whose pack is new. Returns how many Requests."""
        made = 0
        with self.lock:
            rows = [dict(r) for r in self.db.execute("SELECT * FROM series_follow")]
        library = view.owned_seasons(self.media, client_id)
        for row in rows:
            packs = self._packs(row["series"])
            known = set(json.loads(row["known"]))
            fresh = sorted(set(packs) - known)
            if not fresh:
                continue
            index = self.media.series_index(fresh=True)
            entry = next((e for e in index if e["id"] == row["series"]), None)
            if entry is None:
                continue
            owned = view._owned(entry, library)
            for n in fresh:
                if n in owned:
                    continue
                try:
                    created = self.requests.ask_film(
                        row["account"],
                        FilmAsk(
                            f"{row['series']}:{n}", f"{entry['title']} · saison {n}",
                            str((entry["meta"] or {}).get("year") or ""), int(packs[n]["size"]),
                        ),
                    )  # fmt: skip
                except (CapReached, ValueError):
                    continue  # over a cap or already asked: the Member can ask by hand
                with self.lock, self.db:
                    self.db.execute("UPDATE requests SET seen=0 WHERE id=?", (created["id"],))
                made += 1
            with self.lock, self.db:
                self.db.execute(
                    "UPDATE series_follow SET known=? WHERE account=? AND series=?",
                    (json.dumps(sorted(known | set(fresh))), row["account"], row["series"]),
                )
        return made
