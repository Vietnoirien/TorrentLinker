"""Fichiers: the operation journal and the Corbeille, one trash folder per disk (ADR-0029).

Every file operation is written to the journal before it starts, with who asked for it and
how to undo it. Delete always means trash: the item is renamed into its disk's trash folder
(an instant move), remembered with its original path, and purged once the retention passed.
Only emptying the trash deletes data for good.
"""

from __future__ import annotations

import errno
import json
import os
import re
import shutil
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from torrentlinker.sqlite_support import concurrent

TRASH_NAME = ".corbeille"
DEFAULT_RETENTION_DAYS = 7
DAY = 86400.0


class StorageError(ValueError):
    """An operation refused or failed; the message says why."""


@dataclass(frozen=True)
class Disk:
    """The storage roots that share one device, with the trash folder that serves them."""

    id: str
    roots: tuple[Path, ...]
    trash: Path
    writable: bool
    reason: str

    @property
    def name(self) -> str:
        return str(self.roots[0])


def _read_only(path: Path) -> str:
    """Why nothing can be written under `path`, or an empty string."""
    try:
        if os.statvfs(path).f_flag & os.ST_RDONLY:
            return "The disk is mounted read-only."
    except OSError as error:
        return f"The disk cannot be read: {error.strerror or error}"
    if not os.access(path, os.W_OK):
        return "The folder is not writable by the application."
    return ""


class FileStorage:
    def __init__(self, directory: Path, roots: tuple[Path, ...], now=time.time) -> None:
        self.roots = tuple(p.resolve() for p in roots)
        self.now = now
        self._settings = directory / "files-settings.json"
        self._lock = threading.RLock()
        self._db = concurrent(sqlite3.connect(directory / "files.sqlite", check_same_thread=False))
        self._db.row_factory = sqlite3.Row
        with self._db:
            self._db.executescript(
                """
                CREATE TABLE IF NOT EXISTS operations (
                    id TEXT PRIMARY KEY, kind TEXT NOT NULL, actor TEXT NOT NULL,
                    started REAL NOT NULL, finished REAL, state TEXT NOT NULL,
                    detail TEXT NOT NULL, undo TEXT NOT NULL DEFAULT '',
                    error TEXT NOT NULL DEFAULT '');
                CREATE TABLE IF NOT EXISTS trash (
                    id TEXT PRIMARY KEY, disk TEXT NOT NULL, name TEXT NOT NULL,
                    original TEXT NOT NULL, stored TEXT NOT NULL, actor TEXT NOT NULL,
                    at REAL NOT NULL, size INTEGER NOT NULL, is_dir INTEGER NOT NULL,
                    reason TEXT NOT NULL DEFAULT '');
                """
            )

    # Settings ------------------------------------------------------------------------

    def retention_days(self) -> int:
        try:
            value = int(json.loads(self._settings.read_text(encoding="utf-8"))["retention_days"])
        except (OSError, ValueError, KeyError, TypeError):
            return DEFAULT_RETENTION_DAYS
        return value if 1 <= value <= 365 else DEFAULT_RETENTION_DAYS

    def set_retention_days(self, days: int) -> None:
        if not 1 <= days <= 365:
            raise StorageError("Keep the trash between 1 and 365 days.")
        try:
            current = json.loads(self._settings.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            current = {}
        self._settings.write_text(json.dumps({**current, "retention_days": days}), encoding="utf-8")

    def scrutiny_url(self) -> str:
        try:
            return str(json.loads(self._settings.read_text(encoding="utf-8")).get("scrutiny", ""))
        except (OSError, ValueError, TypeError):
            return ""

    def set_scrutiny_url(self, url: str) -> None:
        url = url.strip()
        if url and not re.fullmatch(r"https?://[^\s/]+(:\d+)?(/\S*)?", url):
            raise StorageError("Enter Scrutiny's address, for example http://scrutiny:8080.")
        try:
            current = json.loads(self._settings.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            current = {}
        self._settings.write_text(json.dumps({**current, "scrutiny": url}), encoding="utf-8")

    def templates(self) -> dict[str, dict[str, str]]:
        """The Organisation naming templates, per Library Folder: {folder: {film|series: text}}."""
        try:
            found = json.loads(self._settings.read_text(encoding="utf-8")).get("templates", {})
        except (OSError, ValueError, TypeError):
            return {}
        return found if isinstance(found, dict) else {}

    def set_template(self, folder: str, kind: str, template: str) -> None:
        """Save one template; an empty text brings back the Jellyfin default."""
        try:
            current = json.loads(self._settings.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            current = {}
        templates = current.get("templates", {})
        mine = {**templates.get(folder, {})}
        if template:
            mine[kind] = template
        else:
            mine.pop(kind, None)
        templates[folder] = mine
        self._settings.write_text(json.dumps({**current, "templates": templates}), encoding="utf-8")

    def auto_tidy(self) -> dict[str, bool]:
        """The old per-Download-Folder "Ranger automatiquement" switches (#212), read once to
        migrate them into the provenance links (#223)."""
        try:
            found = json.loads(self._settings.read_text(encoding="utf-8")).get("auto_tidy", {})
        except (OSError, ValueError, TypeError):
            return {}
        return {k: bool(v) for k, v in found.items()} if isinstance(found, dict) else {}

    # Organisation's board: roles, provenance links, fixed titles (#223) -------------------

    def board(self) -> dict[str, Any]:
        """`roles` {path: lib|prov|none}; `links` {provenance: {to, auto}} (`to` is an organised
        library, empty for Automatique); `titles` {item path: fixed title}; `kept` the items the
        Owner keeps as they are; `swapped` {old Library Folder: its organised libraries}."""
        try:
            found = json.loads(self._settings.read_text(encoding="utf-8")).get("board", {})
        except (OSError, ValueError, TypeError):
            found = {}
        found = found if isinstance(found, dict) else {}
        return {
            "roles": dict(found.get("roles", {})), "links": dict(found.get("links", {})),
            "titles": dict(found.get("titles", {})), "kept": list(found.get("kept", [])),
            "swapped": dict(found.get("swapped", {})),
        }  # fmt: skip

    def update_board(self, change) -> None:
        """Apply `change(board)` to the board and save it."""
        with self._lock:
            try:
                current = json.loads(self._settings.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                current = {}
            board = self.board()
            change(board)
            self._settings.write_text(json.dumps({**current, "board": board}), encoding="utf-8")

    # Disks ---------------------------------------------------------------------------

    def disks(self) -> list[Disk]:
        groups: dict[int, list[Path]] = {}
        for root in self.roots:
            try:
                groups.setdefault(root.stat().st_dev, []).append(root)
            except OSError:
                continue
        result = []
        for device, roots in groups.items():
            ordered = tuple(sorted(roots, key=lambda p: (len(p.parts), str(p))))
            reasons = [_read_only(r) for r in ordered]
            host = next((r for r, why in zip(ordered, reasons, strict=True) if not why), ordered[0])
            result.append(
                Disk(
                    str(device),
                    ordered,
                    host / TRASH_NAME,
                    writable=any(not why for why in reasons),
                    reason="" if any(not why for why in reasons) else reasons[0],
                )
            )
        return sorted(result, key=lambda d: d.name)

    def disk_of(self, path: Path) -> Disk:
        root = self.under_roots(path)
        device = str(root.stat().st_dev)
        for disk in self.disks():
            if disk.id == device:
                return disk
        raise StorageError("This path is on no known disk.")

    def under_roots(self, path: Path) -> Path:
        """The storage root holding `path`; refuses anything outside, and symbolic links."""
        candidate = Path(os.path.abspath(path))
        for root in self.roots:
            if candidate == root or candidate.is_relative_to(root):
                current = candidate
                while current != root:
                    if current.is_symlink():
                        raise StorageError(f"Not through a symbolic link: {current}")
                    current = current.parent
                return root
        raise StorageError("This path is outside the configured storage roots.")

    # Journal -------------------------------------------------------------------------

    def begin(self, kind: str, actor: str, detail: dict[str, Any], undo: dict[str, Any]) -> str:
        identifier = uuid.uuid4().hex
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO operations (id, kind, actor, started, state, detail, undo)"
                " VALUES (?, ?, ?, ?, 'pending', ?, ?)",
                (identifier, kind, actor, self.now(), json.dumps(detail), json.dumps(undo)),
            )
        return identifier

    def finish(self, identifier: str, state: str, error: str = "") -> None:
        with self._lock, self._db:
            self._db.execute(
                "UPDATE operations SET state=?, finished=?, error=? WHERE id=?",
                (state, self.now(), error, identifier),
            )

    def journal(self, limit: int = 200) -> list[dict[str, Any]]:
        rows = self._db.execute(
            "SELECT * FROM operations ORDER BY started DESC, rowid DESC LIMIT ?", (limit,)
        ).fetchall()
        trashed = {r["id"] for r in self._db.execute("SELECT id FROM trash").fetchall()}
        return [
            {
                "undoable": r["state"] == "done"
                and r["kind"] == "trash"
                and json.loads(r["undo"]).get("restore") in trashed,
                "id": r["id"],
                "kind": r["kind"],
                "actor": r["actor"],
                "started": r["started"],
                "finished": r["finished"],
                "state": r["state"],
                "detail": json.loads(r["detail"]),
                "error": r["error"],
            }
            for r in rows
        ]

    def undo(self, identifier: str, actor: str) -> str:
        """Undo a finished operation from the journal; only trashing can be undone so far."""
        row = self._db.execute("SELECT * FROM operations WHERE id=?", (identifier,)).fetchone()
        if row is None or row["state"] != "done":
            raise StorageError("Only a finished operation can be undone.")
        trashed = json.loads(row["undo"]).get("restore")
        if row["kind"] != "trash" or not trashed:
            raise StorageError("This operation cannot be undone.")
        return self.restore(trashed, actor)

    def reconcile(self) -> int:
        """Settle what a stop left half done: what moved is done, what did not is failed."""
        settled = 0
        with self._lock:
            for row in self._db.execute(
                "SELECT * FROM operations WHERE state='pending'"
            ).fetchall():
                detail = json.loads(row["detail"])
                source, target = Path(detail.get("from", "")), Path(detail.get("to", ""))
                if row["kind"] in {"trash", "restore"} and target.exists() and not source.exists():
                    self.finish(row["id"], "done")
                elif (
                    row["kind"] in {"trash", "restore"} and source.exists() and not target.exists()
                ):
                    self.finish(row["id"], "failed", "Interrupted before anything moved.")
                elif row["kind"] in {"purge", "empty"}:
                    self.finish(row["id"], "done", "Finished at startup.")
                else:
                    self.finish(row["id"], "failed", "Interrupted; check both places.")
                settled += 1
        return settled

    # Corbeille -----------------------------------------------------------------------

    @staticmethod
    def _size(path: Path) -> int:
        if path.is_symlink() or not path.is_dir():
            return path.lstat().st_size
        return sum(f.lstat().st_size for f in path.rglob("*") if f.is_file() and not f.is_symlink())

    def trash(self, path: Path, actor: str, reason: str = "") -> dict[str, Any]:
        """Move a file or folder into its disk's trash. Never deletes."""
        path = Path(os.path.abspath(path))
        self.under_roots(path)
        if not os.path.lexists(path):
            raise StorageError(f"{path} does not exist.")
        disk = self.disk_of(path)
        if not disk.writable:
            raise StorageError(f"{disk.name} is read-only: {disk.reason}")
        if path == disk.trash or path.is_relative_to(disk.trash):
            raise StorageError("This is already in the trash.")
        if path in self.roots:
            raise StorageError("A storage root cannot be trashed.")
        identifier = uuid.uuid4().hex[:12]
        stored = disk.trash / identifier / path.name
        size, is_dir = self._size(path), path.is_dir() and not path.is_symlink()
        operation = self.begin(
            "trash",
            actor,
            {"from": str(path), "to": str(stored), "size": size},
            {"restore": identifier},
        )
        try:
            stored.parent.mkdir(parents=True)
            os.rename(path, stored)
        except OSError as error:
            shutil.rmtree(stored.parent, ignore_errors=True)
            if error.errno != errno.ENOSPC:
                self.finish(operation, "failed", error.strerror or str(error))
                raise StorageError(
                    f"Could not trash {path.name}: {error.strerror or error}"
                ) from error
            # A full disk cannot even take a trash folder: the item is put in the trash where
            # it lies. The trash lists it, emptying it or the purge deletes it, and restoring
            # only takes it off the list.
            stored = path
            reason = reason or "Disque plein : mis à la corbeille sur place"
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO trash VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    identifier,
                    disk.id,
                    path.name,
                    str(path),
                    str(stored),
                    actor,
                    self.now(),
                    size,
                    int(is_dir),
                    reason,
                ),
            )
        self.finish(operation, "done")
        return self._item(self._row(identifier), self.retention_days())

    def _row(self, identifier: str) -> sqlite3.Row:
        row = self._db.execute("SELECT * FROM trash WHERE id=?", (identifier,)).fetchone()
        if row is None:
            raise StorageError("This item is no longer in the trash.")
        return row

    def _item(self, row: sqlite3.Row, retention: int) -> dict[str, Any]:
        left = max(0.0, row["at"] + retention * DAY - self.now())
        return {
            "id": row["id"],
            "disk": row["disk"],
            "name": row["name"],
            "from": row["original"],
            "by": row["actor"],
            "at": row["at"],
            "size": row["size"],
            "dir": bool(row["is_dir"]),
            "reason": row["reason"],
            "in_place": row["stored"] == row["original"],
            "days_left": int(-(-left // DAY)),
        }

    def listing(self) -> dict[str, Any]:
        retention = self.retention_days()
        items = [
            self._item(r, retention)
            for r in self._db.execute("SELECT * FROM trash ORDER BY at DESC").fetchall()
        ]
        return {
            "retention_days": retention,
            "disks": [
                {
                    "id": d.id,
                    "name": d.name,
                    "writable": d.writable,
                    "reason": d.reason,
                    "items": [i for i in items if i["disk"] == d.id],
                }
                for d in self.disks()
            ],
        }

    def restore(self, identifier: str, actor: str) -> str:
        """Put an item back where it came from; refuses to overwrite what is there now."""
        row = self._row(identifier)
        original, stored = Path(row["original"]), Path(row["stored"])
        self.under_roots(original)
        if original == stored:  # put in the trash where it lay: it only leaves the list
            with self._lock, self._db:
                self._db.execute("DELETE FROM trash WHERE id=?", (identifier,))
            return str(original)
        if os.path.lexists(original):
            raise StorageError(f"{original} exists already; rename or move it first.")
        if not os.path.lexists(stored):
            raise StorageError("The item is no longer in the trash folder.")
        operation = self.begin(
            "restore", actor, {"from": str(stored), "to": str(original)}, {"trash": str(original)}
        )
        try:
            original.parent.mkdir(parents=True, exist_ok=True)
            os.rename(stored, original)
        except OSError as error:
            self.finish(operation, "failed", error.strerror or str(error))
            raise StorageError(f"Could not restore: {error.strerror or error}") from error
        shutil.rmtree(stored.parent, ignore_errors=True)
        with self._lock, self._db:
            self._db.execute("DELETE FROM trash WHERE id=?", (identifier,))
        self.finish(operation, "done")
        return str(original)

    def _erase(self, row: sqlite3.Row) -> None:
        if row["stored"] == row["original"]:
            return self._erase_in_place(row)
        folder = Path(row["stored"]).parent
        if folder.parent.name != TRASH_NAME:
            raise StorageError("Refusing to delete outside a trash folder.")
        shutil.rmtree(folder, ignore_errors=False)
        with self._lock, self._db:
            self._db.execute("DELETE FROM trash WHERE id=?", (row["id"],))

    def _erase_in_place(self, row: sqlite3.Row) -> None:
        """Delete an item trashed where it lay, only if it is still what was trashed: the same
        kind and the same size. Anything else there now is left alone."""
        path = Path(row["original"])
        self.under_roots(path)
        if os.path.lexists(path):
            if path.is_symlink() or path.is_dir() != bool(row["is_dir"]):
                raise StorageError(f"{path} changed since it was trashed: it is kept.")
            if self._size(path) != row["size"]:
                raise StorageError(f"{path} changed since it was trashed: it is kept.")
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
        with self._lock, self._db:
            self._db.execute("DELETE FROM trash WHERE id=?", (row["id"],))

    def trashed_in_place(self) -> list[Path]:
        """What the trash holds where it lay: listings and scans leave it out."""
        rows = self._db.execute("SELECT original FROM trash WHERE stored = original").fetchall()
        return [Path(r["original"]) for r in rows]

    def empty(self, actor: str, disk: str | None = None) -> int:
        """Delete trashed data for good: the Owner's explicit action."""
        rows = [
            r
            for r in self._db.execute("SELECT * FROM trash").fetchall()
            if disk is None or r["disk"] == disk
        ]
        operation = self.begin("empty", actor, {"disk": disk or "all", "items": len(rows)}, {})
        try:
            for row in rows:
                self._erase(row)
        except (OSError, StorageError) as error:
            self.finish(operation, "failed", str(error))
            raise StorageError(f"Could not empty the trash: {error}") from error
        self.finish(operation, "done")
        return len(rows)

    def purge_expired(self) -> int:
        """The daily purge: what stayed past the retention is deleted for good."""
        limit = self.now() - self.retention_days() * DAY
        rows = self._db.execute("SELECT * FROM trash WHERE at <= ?", (limit,)).fetchall()
        if not rows:
            return 0
        operation = self.begin("purge", "system", {"items": len(rows)}, {})
        failed = ""
        for row in rows:
            try:
                self._erase(row)
            except (OSError, StorageError) as error:
                failed = str(error)
        self.finish(operation, "failed" if failed else "done", failed)
        return len(rows)
