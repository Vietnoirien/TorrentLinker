"""Local SQLite state: caches and the user's decisions."""

from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS search_cache (
    key TEXT PRIMARY KEY,
    body TEXT NOT NULL,
    fetched_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS verification (
    hash TEXT PRIMARY KEY,
    item_path TEXT NOT NULL,
    candidate_key TEXT NOT NULL,
    rechecked_at REAL NOT NULL,
    required_progress REAL NOT NULL DEFAULT 1.0
);
CREATE TABLE IF NOT EXISTS rejection (
    item_path TEXT NOT NULL,
    candidate_key TEXT NOT NULL,
    reason TEXT NOT NULL,
    PRIMARY KEY (item_path, candidate_key)
);
CREATE TABLE IF NOT EXISTS item_query (
    item_path TEXT PRIMARY KEY,
    query TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class Verification:
    item_path: Path
    candidate_key: str
    rechecked_at: float
    required_progress: float


class Store:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.torrent_dir = path.parent / "torrents"
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock, self._db:
            self._db.executescript(SCHEMA)
            self._migrate()

    def _migrate(self) -> None:
        columns = {r[1] for r in self._db.execute("PRAGMA table_info(verification)")}
        if "required_progress" not in columns:
            self._db.execute(
                "ALTER TABLE verification ADD COLUMN required_progress REAL NOT NULL DEFAULT 1.0"
            )

    def cached_search(self, key: str, max_age: float) -> str | None:
        with self._lock:
            row = self._db.execute(
                "SELECT body, fetched_at FROM search_cache WHERE key = ?", (key,)
            ).fetchone()
        if row and time.time() - row[1] <= max_age:
            return str(row[0])
        return None

    def cache_search(self, key: str, body: str) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO search_cache VALUES (?, ?, ?)", (key, body, time.time())
            )

    def item_query(self, item_path: Path) -> str | None:
        with self._lock:
            row = self._db.execute(
                "SELECT query FROM item_query WHERE item_path = ?", (str(item_path),)
            ).fetchone()
        return str(row[0]) if row else None

    def set_item_query(self, item_path: Path, query: str) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO item_query VALUES (?, ?)", (str(item_path), query)
            )

    def cached_torrent(self, key: str) -> bytes | None:
        f = self.torrent_dir / f"{key}.torrent"
        return f.read_bytes() if f.exists() else None

    def cache_torrent(self, key: str, data: bytes) -> None:
        self.torrent_dir.mkdir(parents=True, exist_ok=True)
        (self.torrent_dir / f"{key}.torrent").write_bytes(data)

    # Verifications in flight ------------------------------------------------

    def start_verification(
        self, hash: str, item_path: Path, candidate_key: str, required_progress: float = 1.0
    ) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO verification VALUES (?, ?, ?, ?, ?)",
                (hash, str(item_path), candidate_key, time.time(), required_progress),
            )

    def verification(self, hash: str) -> Verification | None:
        with self._lock:
            row = self._db.execute(
                "SELECT item_path, candidate_key, rechecked_at, required_progress"
                " FROM verification WHERE hash = ?",
                (hash,),
            ).fetchone()
        return (
            Verification(Path(row[0]), str(row[1]), float(row[2]), float(row[3])) if row else None
        )

    def end_verification(self, hash: str) -> None:
        with self._lock, self._db:
            self._db.execute("DELETE FROM verification WHERE hash = ?", (hash,))

    # Rejections -------------------------------------------------------------

    def reject(self, item_path: Path, candidate_key: str, reason: str) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO rejection VALUES (?, ?, ?)",
                (str(item_path), candidate_key, reason),
            )

    def rejections(self, item_path: Path) -> dict[str, str]:
        with self._lock:
            rows = self._db.execute(
                "SELECT candidate_key, reason FROM rejection WHERE item_path = ?",
                (str(item_path),),
            ).fetchall()
        return {str(k): str(r) for k, r in rows}
