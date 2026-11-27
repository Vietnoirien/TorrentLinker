"""Replace a library film with a better release (ADR-0029, #203, #204).

The better release downloads next to the old one, in the same Library Folder and on the same
disk, or in the Download Folder when that disk lacks space above the margin. Once it is
complete it becomes the film's file: the old one is hidden from Médias, and when it still
seeds it can wait for the "Fin du partage" rule (a time and/or a ratio, either or both) before
its torrent is removed without its data and its files go to the Corbeille. Nothing is deleted
for good, and every step is journaled by the file storage.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from torrentlinker.file_storage import FileStorage, StorageError
from torrentlinker.qbit import Qbit

MARGIN = 0.10  # a disk keeps this share of its space free
SEEDING = {"uploading", "stalledup", "forcedup", "seeding", "queuedup", "checkingup"}


@dataclass(frozen=True)
class FinRule:
    """When a replaced release that still seeds may be removed: a time and/or a ratio."""

    use_time: bool = True
    hours: float = 7 * 24.0
    use_ratio: bool = True
    ratio: float = 1.0
    combine: str = "any"  # "any": l'un ou l'autre; "all": les deux

    def met(self, seeding_hours: float, ratio: float) -> bool:
        checks = []
        if self.use_time:
            checks.append(seeding_hours >= self.hours)
        if self.use_ratio:
            checks.append(ratio >= self.ratio)
        if not checks:
            return True  # no condition: removed as soon as the new release is complete
        return all(checks) if self.combine == "all" else any(checks)

    @classmethod
    def parse(cls, value: dict[str, Any]) -> FinRule:
        rule = cls(
            use_time=bool(value.get("use_time", True)),
            hours=float(value.get("hours", 7 * 24)),
            use_ratio=bool(value.get("use_ratio", True)),
            ratio=float(value.get("ratio", 1.0)),
            combine="all" if value.get("combine") == "all" else "any",
        )
        if rule.hours <= 0 or rule.ratio <= 0:
            raise ValueError("The Fin du partage rule needs a positive time and ratio.")
        return rule


@dataclass(frozen=True)
class Placement:
    folder: Path
    fallback: bool  # the Download Folder, because the film's disk lacks space
    reason: str


def placement(
    film_folder: Path, size: int, download_folder: Path | None, margin: float = MARGIN
) -> Placement:
    """Beside the old release when its disk keeps the margin after this download, else in the
    Download Folder, with the reason."""
    stat = os.statvfs(film_folder)
    free, total = stat.f_bavail * stat.f_frsize, stat.f_blocks * stat.f_frsize
    if free - size >= total * margin:
        return Placement(film_folder, False, "")
    if download_folder is None:
        raise ValueError("The film's disk lacks space and no Download Folder is set.")
    return Placement(
        download_folder,
        True,
        f"{film_folder} has {free} bytes free, {size} are needed above a {margin:.0%} margin.",
    )


class Replacements:
    def __init__(self, directory: Path, storage: FileStorage, now=time.time) -> None:
        self.storage, self.now = storage, now
        self._lock = threading.RLock()
        self._db = sqlite3.connect(directory / "replacements.sqlite", check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._db:
            self._db.executescript(
                """
                CREATE TABLE IF NOT EXISTS replacement (
                    id TEXT PRIMARY KEY, client TEXT NOT NULL, film TEXT NOT NULL,
                    old_hash TEXT NOT NULL, new_hash TEXT NOT NULL, old_paths TEXT NOT NULL,
                    replace INTEGER NOT NULL, wait INTEGER NOT NULL, rule TEXT NOT NULL,
                    actor TEXT NOT NULL, state TEXT NOT NULL, since REAL, started REAL NOT NULL,
                    destination TEXT NOT NULL DEFAULT '', reason TEXT NOT NULL DEFAULT '',
                    error TEXT NOT NULL DEFAULT '');
                """
            )

    def start(
        self,
        client: str,
        film: str,
        *,
        new_hash: str,
        old_hash: str = "",
        old_paths: list[Path],
        replace: bool,
        wait: bool,
        rule: FinRule,
        actor: str,
        where: Placement | None = None,
    ) -> str:
        """Record a better release being downloaded; `wait` only counts with `replace`."""
        identifier = uuid.uuid4().hex[:12]
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO replacement (id, client, film, old_hash, new_hash, old_paths,"
                " replace, wait, rule, actor, state, started, destination, reason)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,'downloading',?,?,?)",
                (
                    identifier, client, film, old_hash.lower(), new_hash.lower(),
                    json.dumps([str(p) for p in old_paths]), int(replace), int(replace and wait),
                    json.dumps(rule.__dict__), actor, self.now(),
                    str(where.folder) if where else "", where.reason if where else "",
                ),
            )  # fmt: skip
        return identifier

    def _row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"], "client": row["client"], "film": row["film"], "state": row["state"],
            "replace": bool(row["replace"]), "wait": bool(row["wait"]), "since": row["since"],
            "old_hash": row["old_hash"], "new_hash": row["new_hash"],
            "destination": row["destination"], "reason": row["reason"], "error": row["error"],
            "rule": json.loads(row["rule"]), "actor": row["actor"],
            "old_paths": json.loads(row["old_paths"]),
        }  # fmt: skip

    def runs(self, client: str | None = None) -> list[dict[str, Any]]:
        rows = self._db.execute(
            "SELECT * FROM replacement WHERE ? IS NULL OR client=? ORDER BY started DESC",
            (client, client),
        ).fetchall()
        return [self._row(r) for r in rows]

    def hidden(self, client: str) -> set[str]:
        """The films whose old release Médias no longer shows: replaced, or ending its share."""
        rows = self._db.execute(
            "SELECT film FROM replacement WHERE client=? AND replace=1"
            " AND state IN ('seeding-out','done')",
            (client,),
        ).fetchall()
        return {r["film"] for r in rows}

    def ending(self, client: str) -> dict[str, dict[str, Any]]:
        """The old torrents Torrents marks "en fin de partage", with their rule."""
        rows = self._db.execute(
            "SELECT old_hash, rule FROM replacement WHERE client=? AND state='seeding-out'",
            (client,),
        ).fetchall()
        return {r["old_hash"]: json.loads(r["rule"]) for r in rows}

    def _set(
        self, identifier: str, state: str, error: str = "", since: float | None = None
    ) -> None:
        with self._lock, self._db:
            self._db.execute(
                "UPDATE replacement SET state=?, error=?, since=COALESCE(?, since) WHERE id=?",
                (state, error, since, identifier),
            )

    def tick(self, client: Qbit, client_id: str) -> list[str]:
        """Move every run of this client one step: complete, wait for the rule, or finish."""
        moved = []
        for run in self.runs(client_id):
            if run["state"] not in {"downloading", "seeding-out"}:
                continue
            before = run["state"]
            try:
                state = self._step(client, run)
            except Exception as error:  # noqa: BLE001 - recorded, and tried again next tick
                self._set(run["id"], before, f"{type(error).__name__}: {error}")
                continue
            if state != before:
                moved.append(run["id"])
        return moved

    def _step(self, client: Qbit, run: dict[str, Any]) -> str:
        if run["state"] == "downloading":
            new = client.torrent(run["new_hash"], with_files=False)
            if new is None or new.progress < 1 or "checking" in new.state.lower():
                return "downloading"
            if not run["replace"]:
                self._set(run["id"], "done")
                return "done"
            old = client.torrent(run["old_hash"], with_files=False) if run["old_hash"] else None
            seeds = old is not None and old.state.lower() in SEEDING
            if not (run["wait"] and seeds):
                return self._finish(client, run)
            self._set(run["id"], "seeding-out", since=self.now())
            return "seeding-out"
        old = client.torrent(run["old_hash"], with_files=False)
        if old is None:
            return self._finish(client, run)
        rule = FinRule.parse(run["rule"])
        if rule.met(old.seeding_time / 3600, old.ratio):
            return self._finish(client, run)
        return "seeding-out"

    def _finish(self, client: Qbit, run: dict[str, Any]) -> str:
        """The torrent leaves the client without its data; its files go to the Corbeille."""
        if run["old_hash"] and client.torrent(run["old_hash"], with_files=False) is not None:
            client.remove(run["old_hash"], delete_files=False)
        failed = []
        for path in run["old_paths"]:
            target = Path(path)
            if not os.path.lexists(target):
                continue  # already trashed or moved: nothing is lost by skipping
            try:
                self.storage.trash(target, run["actor"], "Remplacé par une meilleure version")
            except StorageError as error:
                failed.append(str(error))
        self._set(run["id"], "done" if not failed else "trash-failed", "; ".join(failed))
        return "done" if not failed else "trash-failed"
