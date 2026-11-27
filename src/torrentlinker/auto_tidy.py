"""Auto: a download that finishes in an Auto provenance is ranged like the rest (#212, #223).

A provenance with Auto on (the default for a Download Folder, off for an old library) ranges
each release that finishes while it is on: the same move and rename as Ranger, queued as a
Tâche, to the provenance's pinned library or, for Automatique, the one the kind and the
placement rule pick. A release that was already finished when Auto went on is left to the
Owner's Ranger.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from guessit import guessit

from torrentlinker.media import VIDEO

ACTOR = "Rangement automatique"


class AutoTidy:
    def __init__(self, directory: Path, enqueue: Callable[[str, str, list[dict[str, Any]]], Any]):
        """`enqueue(label, actor, rows)` queues a batch of {top, prov, kind, title}."""
        self.enqueue = enqueue
        self._lock = threading.RLock()
        self._db = sqlite3.connect(directory / "auto-tidy.sqlite", check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._db:
            self._db.executescript(
                """
                CREATE TABLE IF NOT EXISTS seen (client TEXT, hash TEXT, PRIMARY KEY(client, hash));
                CREATE TABLE IF NOT EXISTS tidied (
                    client TEXT, hash TEXT, at REAL, state TEXT, detail TEXT,
                    PRIMARY KEY(client, hash));
                """
            )

    def results(self) -> list[dict[str, Any]]:
        rows = self._db.execute("SELECT * FROM tidied ORDER BY at DESC LIMIT 50").fetchall()
        return [dict(r) for r in rows]

    def tick(self, client_id: str, torrents, roots: list[Path]) -> list[str]:
        """Remember what is still downloading in an Auto provenance; range what finished."""
        queued = []
        for torrent in torrents:
            where = Path(torrent.save_path)
            root = next((r for r in roots if where == r or where.is_relative_to(r)), None)
            if root is None:
                continue
            key = (client_id, torrent.hash.lower())
            with self._lock, self._db:
                if torrent.progress < 1:
                    self._db.execute("INSERT OR IGNORE INTO seen VALUES (?,?)", key)
                    continue
                known = self._db.execute(
                    "SELECT 1 FROM seen WHERE client=? AND hash=?", key
                ).fetchone()
                tidied = self._db.execute(
                    "SELECT 1 FROM tidied WHERE client=? AND hash=?", key
                ).fetchone()
            if not known or tidied or "check" in torrent.state.lower():
                continue
            if any(t.startswith("torrentlinker:") for t in torrent.tags):
                continue  # under Reseed Verification or a Link Folder: never moved
            queued.append(self._queue(client_id, torrent, root))
        return queued

    def _queue(self, client_id: str, torrent, root: Path) -> str:
        save = Path(torrent.save_path)
        tops = sorted({Path(name).parts[0] for name in torrent.files})
        videos = sorted(n for n in torrent.files if Path(n).suffix.lower() in VIDEO)
        state, detail = "skipped", "No video in this torrent."
        if videos:
            kind = "series" if guessit(videos[0]).get("type") == "episode" else "film"
            rows = [{"top": str(save / t), "prov": str(root), "kind": kind} for t in tops]
            try:
                self.enqueue(f"Ranger {torrent.name}", ACTOR, rows)
                state, detail = "queued", str(root)
            except Exception as error:  # noqa: BLE001 - recorded, and never tried again
                state, detail = "failed", str(error)
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO tidied VALUES (?,?,?,?,?)",
                (client_id, torrent.hash.lower(), time.time(), state, detail),
            )
        return state
