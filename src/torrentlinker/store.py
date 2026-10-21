"""Local SQLite state: caches and the user's decisions."""

from __future__ import annotations

import json
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
    rechecked_at REAL,
    required_progress REAL NOT NULL DEFAULT 1.0,
    required_pieces TEXT
);
CREATE TABLE IF NOT EXISTS rejection (
    item_path TEXT NOT NULL,
    candidate_key TEXT NOT NULL,
    reason TEXT NOT NULL,
    PRIMARY KEY (item_path, candidate_key)
);
CREATE TABLE IF NOT EXISTS scan_cache (
    item_path TEXT PRIMARY KEY,
    signature TEXT NOT NULL,
    files TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS remembered_candidates (
    item_path TEXT PRIMARY KEY,
    candidates TEXT NOT NULL,
    searched_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS item_query (
    item_path TEXT PRIMARY KEY,
    query TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS catalogue (
    infohash TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    size INTEGER NOT NULL,
    seeders INTEGER NOT NULL,
    category INTEGER,
    download_url TEXT NOT NULL,
    details_url TEXT NOT NULL,
    seen_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS catalogue_crawl (
    category INTEGER PRIMARY KEY,
    next_offset INTEGER NOT NULL DEFAULT 0,
    complete INTEGER NOT NULL DEFAULT 0,
    updated_at REAL
);
"""


@dataclass(frozen=True)
class CatalogueRow:
    """A torrent of the Catalogue. `download_url` never holds the API key."""

    infohash: str
    title: str
    size: int
    seeders: int
    category: int | None
    download_url: str
    details_url: str
    seen_at: float


@dataclass(frozen=True)
class CrawlState:
    category: int
    next_offset: int = 0  # where a paused full crawl resumes
    complete: bool = False  # a full crawl reached the end once
    updated_at: float | None = None


@dataclass(frozen=True)
class Verification:
    item_path: Path
    candidate_key: str
    rechecked_at: float | None
    # Piece ranges Verification checks when some files are absent; None means all of them.
    required_pieces: list[tuple[int, int]] | None


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
        if "required_pieces" not in columns:
            self._db.execute("ALTER TABLE verification ADD COLUMN required_pieces TEXT")

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

    def remember_candidates(self, item_path: Path, candidates_json: str) -> None:
        """Keep the last search's Candidates of a Local Item (already free of the API key)."""
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO remembered_candidates VALUES (?, ?, ?)",
                (str(item_path), candidates_json, time.time()),
            )

    def remembered_candidates(self, item_path: Path) -> str | None:
        with self._lock:
            row = self._db.execute(
                "SELECT candidates FROM remembered_candidates WHERE item_path = ?",
                (str(item_path),),
            ).fetchone()
        return str(row[0]) if row else None

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
        self,
        hash: str,
        item_path: Path,
        candidate_key: str,
        required_pieces: list[tuple[int, int]] | None = None,
    ) -> None:
        pieces = json.dumps(required_pieces) if required_pieces is not None else None
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO verification"
                " (hash, item_path, candidate_key, rechecked_at, required_pieces)"
                " VALUES (?, ?, ?, NULL, ?)",
                (hash, str(item_path), candidate_key, pieces),
            )

    def mark_rechecked(self, hash: str) -> None:
        with self._lock, self._db:
            self._db.execute(
                "UPDATE verification SET rechecked_at = ? WHERE hash = ?", (time.time(), hash)
            )

    def verification(self, hash: str) -> Verification | None:
        with self._lock:
            row = self._db.execute(
                "SELECT item_path, candidate_key, rechecked_at, required_pieces"
                " FROM verification WHERE hash = ?",
                (hash,),
            ).fetchone()
        if not row:
            return None
        rechecked = float(row[2]) if row[2] is not None else None
        pieces = [tuple(r) for r in json.loads(row[3])] if row[3] is not None else None
        return Verification(Path(row[0]), str(row[1]), rechecked, pieces)  # type: ignore[arg-type]

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

    # Scan cache -------------------------------------------------------------

    def cached_scan(self, item_path: Path, signature: str) -> dict[str, int] | None:
        with self._lock:
            row = self._db.execute(
                "SELECT files FROM scan_cache WHERE item_path = ? AND signature = ?",
                (str(item_path), signature),
            ).fetchone()
        return {str(k): int(v) for k, v in json.loads(row[0]).items()} if row else None

    def cache_scan(self, item_path: Path, signature: str, files: dict[str, int]) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO scan_cache VALUES (?, ?, ?)",
                (str(item_path), signature, json.dumps(files)),
            )

    # Catalogue --------------------------------------------------------------

    def save_catalogue(self, rows: list[CatalogueRow]) -> None:
        with self._lock, self._db:
            self._db.executemany(
                "INSERT OR REPLACE INTO catalogue VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        r.infohash,
                        r.title,
                        r.size,
                        r.seeders,
                        r.category,
                        r.download_url,
                        r.details_url,
                        r.seen_at,
                    )
                    for r in rows
                ],
            )

    def known_hashes(self, hashes: list[str]) -> set[str]:
        with self._lock:
            found = set()
            for i in range(0, len(hashes), 500):
                chunk = hashes[i : i + 500]
                marks = ",".join("?" * len(chunk))
                found |= {
                    str(r[0])
                    for r in self._db.execute(
                        f"SELECT infohash FROM catalogue WHERE infohash IN ({marks})", chunk
                    )
                }
            return found

    def catalogue(self) -> list[CatalogueRow]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM catalogue").fetchall()
        return [CatalogueRow(*r) for r in rows]

    def catalogue_size(self) -> int:
        with self._lock:
            return int(self._db.execute("SELECT COUNT(*) FROM catalogue").fetchone()[0])

    def catalogue_categories(self, hashes: list[str]) -> set[int]:
        """Categories of the given torrents, as far as the Catalogue knows them."""
        with self._lock:
            found: set[int] = set()
            for i in range(0, len(hashes), 500):
                chunk = hashes[i : i + 500]
                marks = ",".join("?" * len(chunk))
                found |= {
                    int(r[0])
                    for r in self._db.execute(
                        f"SELECT DISTINCT category FROM catalogue WHERE infohash IN ({marks})"
                        " AND category IS NOT NULL",
                        chunk,
                    )
                }
            return found

    def crawl_state(self, category: int) -> CrawlState:
        with self._lock:
            row = self._db.execute(
                "SELECT next_offset, complete, updated_at FROM catalogue_crawl WHERE category = ?",
                (category,),
            ).fetchone()
        if not row:
            return CrawlState(category)
        return CrawlState(category, int(row[0]), bool(row[1]), row[2])

    def save_crawl_state(self, state: CrawlState) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO catalogue_crawl VALUES (?, ?, ?, ?)",
                (state.category, state.next_offset, int(state.complete), state.updated_at),
            )

    def catalogue_updated_at(self) -> float | None:
        with self._lock:
            row = self._db.execute("SELECT MAX(updated_at) FROM catalogue_crawl").fetchone()
        return float(row[0]) if row and row[0] is not None else None

    def crawl_paused(self) -> bool:
        """Whether a full crawl stopped before the end of some category."""
        with self._lock:
            row = self._db.execute(
                "SELECT 1 FROM catalogue_crawl WHERE next_offset > 0 AND complete = 0 LIMIT 1"
            ).fetchone()
        return row is not None
