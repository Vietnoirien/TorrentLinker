"""Local SQLite state: caches and the user's decisions."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass, field
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
    required_pieces TEXT,
    local_files TEXT
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
CREATE TABLE IF NOT EXISTS catalogue_feed (
    name TEXT PRIMARY KEY,
    next_page INTEGER NOT NULL DEFAULT 1,
    updated_at REAL,
    count INTEGER NOT NULL DEFAULT 0,
    limited INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS plan_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    made_at REAL NOT NULL,
    sending INTEGER NOT NULL DEFAULT 0,
    zen_added REAL
);
CREATE TABLE IF NOT EXISTS plan_item (
    position INTEGER PRIMARY KEY,
    infohash TEXT NOT NULL,
    title TEXT NOT NULL,
    size INTEGER NOT NULL,
    seeders INTEGER NOT NULL,
    category INTEGER,
    folder TEXT NOT NULL,
    zen REAL NOT NULL,
    note REAL,
    outcome TEXT,
    reason TEXT
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
    source: str = "indexer"


@dataclass(frozen=True)
class SavedPlanItem:
    """A download of the saved Plan; `outcome` is None until it has been sent."""

    infohash: str
    title: str
    size: int
    seeders: int
    category: int | None
    folder: str
    zen: float
    note: float | None
    outcome: str | None = None  # added, refused or failed
    reason: str | None = None


@dataclass(frozen=True)
class SavedPlan:
    made_at: float
    sending: bool  # a send was running when the app stopped
    items: list[SavedPlanItem]
    zen_added: float | None = None  # ≈ Zen/day of the whole Plan, as it was made

    @property
    def pending(self) -> list[SavedPlanItem]:
        """Torrents still to send; a failed one is tried again, a refused one is final."""
        return [i for i in self.items if i.outcome not in ("added", "refused")]


@dataclass(frozen=True)
class FeedState:
    name: str
    next_page: int = 1
    updated_at: float | None = None
    count: int = 0
    limited: bool = False
    head_hashes: tuple[str, ...] = ()  # newest page of the last successful sync
    started_at: float | None = None  # baseline for an interrupted first latest-only update


@dataclass(frozen=True)
class CrawlState:
    category: int
    next_offset: int = 0  # where a paused full crawl resumes
    complete: bool = False  # a full crawl reached the end once
    updated_at: float | None = None
    limited: bool = False  # the Indexer stopped paging before coverage was established


@dataclass(frozen=True)
class Verification:
    item_path: Path
    candidate_key: str
    rechecked_at: float | None
    # Piece ranges Verification checks when some files are absent; None means all of them.
    required_pieces: list[tuple[int, int]] | None
    # Local files the torrent must find in place, relative to its save path.
    local_files: list[str] = field(default_factory=list)


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
        feed_columns = {r[1] for r in self._db.execute("PRAGMA table_info(catalogue_feed)")}
        if "head_hashes" not in feed_columns:
            self._db.execute(
                "ALTER TABLE catalogue_feed ADD COLUMN head_hashes TEXT NOT NULL DEFAULT '[]'"
            )
        if "started_at" not in feed_columns:
            self._db.execute("ALTER TABLE catalogue_feed ADD COLUMN started_at REAL")
        catalogue_columns = {r[1] for r in self._db.execute("PRAGMA table_info(catalogue)")}
        if "source" not in catalogue_columns:
            self._db.execute(
                "ALTER TABLE catalogue ADD COLUMN source TEXT NOT NULL DEFAULT 'indexer'"
            )
        crawl_columns = {r[1] for r in self._db.execute("PRAGMA table_info(catalogue_crawl)")}
        if "limited" not in crawl_columns:
            self._db.execute(
                "ALTER TABLE catalogue_crawl ADD COLUMN limited INTEGER NOT NULL DEFAULT 0"
            )
            # Older versions called a repeated final page a completed crawl. Recheck
            # these categories once; their stored torrents remain available to Plans.
            self._db.execute(
                "UPDATE catalogue_crawl SET complete = 0, next_offset = 0 WHERE complete = 1"
            )
        plan_columns = {r[1] for r in self._db.execute("PRAGMA table_info(plan_state)")}
        if "zen_added" not in plan_columns:  # 0.2.3 saved Plans without it
            self._db.execute("ALTER TABLE plan_state ADD COLUMN zen_added REAL")
        columns = {r[1] for r in self._db.execute("PRAGMA table_info(verification)")}
        if "required_progress" not in columns:
            self._db.execute(
                "ALTER TABLE verification ADD COLUMN required_progress REAL NOT NULL DEFAULT 1.0"
            )
        if "required_pieces" not in columns:
            self._db.execute("ALTER TABLE verification ADD COLUMN required_pieces TEXT")
        if "local_files" not in columns:
            self._db.execute("ALTER TABLE verification ADD COLUMN local_files TEXT")

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
        local_files: list[str] | None = None,
    ) -> None:
        pieces = json.dumps(required_pieces) if required_pieces is not None else None
        files = json.dumps(local_files or [])
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO verification"
                " (hash, item_path, candidate_key, rechecked_at, required_pieces, local_files)"
                " VALUES (?, ?, ?, NULL, ?, ?)",
                (hash, str(item_path), candidate_key, pieces, files),
            )

    def mark_rechecked(self, hash: str) -> None:
        with self._lock, self._db:
            self._db.execute(
                "UPDATE verification SET rechecked_at = ? WHERE hash = ?", (time.time(), hash)
            )

    def verification(self, hash: str) -> Verification | None:
        with self._lock:
            row = self._db.execute(
                "SELECT item_path, candidate_key, rechecked_at, required_pieces, local_files"
                " FROM verification WHERE hash = ?",
                (hash,),
            ).fetchone()
        if not row:
            return None
        rechecked = float(row[2]) if row[2] is not None else None
        pieces = [tuple(r) for r in json.loads(row[3])] if row[3] is not None else None
        files = [str(f) for f in json.loads(row[4])] if row[4] else []
        return Verification(Path(row[0]), str(row[1]), rechecked, pieces, files)  # type: ignore[arg-type]

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
                "INSERT INTO catalogue VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(infohash) DO UPDATE SET"
                " title=excluded.title, size=excluded.size, seeders=excluded.seeders,"
                " category=excluded.category, download_url=excluded.download_url,"
                " details_url=excluded.details_url, seen_at=excluded.seen_at,"
                " source=excluded.source"
                " WHERE excluded.source != 'zen-lab' OR catalogue.source = 'zen-lab'",
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
                        r.source,
                    )
                    for r in rows
                ],
            )

    def known_hashes(self, hashes: list[str], *, seen_before: float | None = None) -> set[str]:
        with self._lock:
            found = set()
            for i in range(0, len(hashes), 500):
                chunk = hashes[i : i + 500]
                marks = ",".join("?" * len(chunk))
                found |= {
                    str(r[0])
                    for r in self._db.execute(
                        f"SELECT infohash FROM catalogue WHERE infohash IN ({marks})"
                        + (" AND seen_at < ?" if seen_before is not None else ""),
                        [*chunk, seen_before] if seen_before is not None else chunk,
                    )
                }
            return found

    def catalogue(self, hashes: list[str] | None = None) -> list[CatalogueRow]:
        with self._lock:
            if hashes is None:
                rows = self._db.execute("SELECT * FROM catalogue").fetchall()
            else:
                rows = []
                for i in range(0, len(hashes), 500):
                    chunk = hashes[i : i + 500]
                    marks = ",".join("?" * len(chunk))
                    rows.extend(
                        self._db.execute(
                            f"SELECT * FROM catalogue WHERE infohash IN ({marks})", chunk
                        ).fetchall()
                    )
        return [CatalogueRow(*r) for r in rows]

    def update_catalogue_seeders(self, counts: dict[str, int]) -> None:
        """Apply swarm observations without claiming size/category metadata was refreshed."""
        with self._lock, self._db:
            self._db.executemany(
                "UPDATE catalogue SET seeders = ? WHERE infohash = ?",
                [(count, h.lower()) for h, count in counts.items() if count >= 0],
            )

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
                "SELECT next_offset, complete, updated_at, limited"
                " FROM catalogue_crawl WHERE category = ?",
                (category,),
            ).fetchone()
        if not row:
            return CrawlState(category)
        return CrawlState(category, int(row[0]), bool(row[1]), row[2], bool(row[3]))

    def save_crawl_state(self, state: CrawlState) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO catalogue_crawl"
                " (category, next_offset, complete, updated_at, limited) VALUES (?, ?, ?, ?, ?)",
                (
                    state.category,
                    state.next_offset,
                    int(state.complete),
                    state.updated_at,
                    int(state.limited),
                ),
            )

    def limited_categories(self) -> set[int]:
        """Categories where the Indexer's paging limit prevented a complete crawl."""
        with self._lock:
            return {
                int(row[0])
                for row in self._db.execute(
                    "SELECT category FROM catalogue_crawl WHERE limited = 1"
                )
            }

    def feed_state(self, name: str) -> FeedState:
        with self._lock:
            row = self._db.execute(
                "SELECT next_page, updated_at, count, limited, head_hashes, started_at"
                " FROM catalogue_feed WHERE name = ?",
                (name,),
            ).fetchone()
        return (
            FeedState(name, row[0], row[1], row[2], bool(row[3]), tuple(json.loads(row[4])), row[5])
            if row
            else FeedState(name)
        )

    def save_feed_state(self, state: FeedState) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO catalogue_feed"
                " (name, next_page, updated_at, count, limited, head_hashes, started_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    state.name,
                    state.next_page,
                    state.updated_at,
                    state.count,
                    int(state.limited),
                    json.dumps(state.head_hashes),
                    state.started_at,
                ),
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
            feed = self._db.execute(
                "SELECT 1 FROM catalogue_feed WHERE next_page > 1"
                " AND name NOT LIKE 'c411-latest:%' LIMIT 1"
            ).fetchone()
        return row is not None or feed is not None

    # The saved Plan ---------------------------------------------------------

    def save_plan(
        self,
        items: list[SavedPlanItem],
        made_at: float | None = None,
        zen_added: float | None = None,
    ) -> None:
        """Replace the saved Plan, so it survives a crash or a restart."""
        with self._lock, self._db:
            self._db.execute("DELETE FROM plan_item")
            self._db.execute("DELETE FROM plan_state")
            if not items:
                return
            self._db.execute(
                "INSERT INTO plan_state (id, made_at, sending, zen_added) VALUES (1, ?, 0, ?)",
                (time.time() if made_at is None else made_at, zen_added),
            )
            self._db.executemany(
                "INSERT INTO plan_item (position, infohash, title, size, seeders, category,"
                " folder, zen, note, outcome, reason) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                [
                    (
                        n,
                        i.infohash,
                        i.title,
                        i.size,
                        i.seeders,
                        i.category,
                        i.folder,
                        i.zen,
                        i.note,
                        i.outcome,
                        i.reason,
                    )
                    for n, i in enumerate(items)
                ],
            )

    def saved_plan(self) -> SavedPlan | None:
        with self._lock:
            state = self._db.execute(
                "SELECT made_at, sending, zen_added FROM plan_state"
            ).fetchone()
            rows = self._db.execute(
                "SELECT infohash, title, size, seeders, category, folder, zen, note, outcome,"
                " reason FROM plan_item ORDER BY position"
            ).fetchall()
        if state is None:
            return None
        return SavedPlan(
            float(state[0]), bool(state[1]), [SavedPlanItem(*r) for r in rows], state[2]
        )

    def set_plan_sending(self, sending: bool) -> None:
        with self._lock, self._db:
            self._db.execute("UPDATE plan_state SET sending = ?", (int(sending),))

    def mark_plan_item(self, infohash: str, outcome: str, reason: str = "") -> None:
        with self._lock, self._db:
            self._db.execute(
                "UPDATE plan_item SET outcome = ?, reason = ? WHERE infohash = ?",
                (outcome, reason or None, infohash),
            )

    def clear_plan(self) -> None:
        self.save_plan([])
