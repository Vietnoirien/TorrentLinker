"""Offline torrent evidence. Imported trackers are never contacted or retained."""

from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import stat
import threading
from contextlib import closing
from pathlib import Path, PurePosixPath

import torf

from torrentlinker.domain import LocalItem
from torrentlinker.torrent_meta import TorrentMeta, read_torrent

MAX_TORRENT_BYTES = 8 * 1024 * 1024


def safe_torrent(data: bytes) -> TorrentMeta:
    if not data or len(data) > MAX_TORRENT_BYTES:
        raise ValueError("Torrent metadata must be between 1 byte and 8 MiB.")
    try:
        torrent = torf.Torrent.read_stream(io.BytesIO(data), validate=True)
        meta = read_torrent(data)
        if (
            torrent.metainfo["info"].get("meta version")
            or not meta.files
            or len(meta.files) > 10000
        ):
            raise ValueError("Only v1 torrents with at most 10000 files are supported.")
        for name in meta.files:
            parts = PurePosixPath(name).parts
            if (
                not parts
                or name.startswith("/")
                or any(p in {"..", ".", ""} or "\\" in p or ":" in p or "\x00" in p for p in parts)
            ):
                raise ValueError("Unsafe path in torrent metadata.")
        if sum(meta.files.values()) <= 0 or meta.piece_length > 64 * 1024 * 1024:
            raise ValueError("Invalid torrent size or piece length.")
        return meta
    except Exception as error:
        # Decoder errors can contain arbitrary imported metadata, including private URLs.
        raise ValueError(
            "Unsupported or invalid torrent metadata. Use a valid v1 .torrent."
        ) from error


def identity(path: Path) -> list[int]:
    for parent in (path, *path.parents):
        if parent.is_symlink():
            raise ValueError("Symbolic links are not supported for evidence or repair.")
    st = path.stat()
    if not stat.S_ISREG(st.st_mode):
        raise ValueError("A regular local file is required.")
    return [st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns]


def verify_pieces(meta: TorrentMeta, mapping: dict[str, Path], stop: threading.Event) -> dict:
    """Count target bytes in valid pieces, including boundaries and the final short piece."""
    hashes = torf.Torrent.read_stream(io.BytesIO(meta.data), validate=False).metainfo["info"][
        "pieces"
    ]
    before = {str(p): identity(p) for p in mapping.values()}
    states = []
    verified = filled = index = 0
    digest = hashlib.sha1()
    available = True
    for name, size in meta.files.items():
        source = mapping.get(name)
        stream = source.open("rb") if source else None
        try:
            remaining = size
            while remaining:
                if stop.is_set():
                    raise ValueError("Verification cancelled.")
                take = min(remaining, meta.piece_length - filled, 1024 * 1024)
                chunk = stream.read(take) if stream else b""
                if len(chunk) != take:
                    available = False
                digest.update(chunk)
                remaining -= take
                filled += take
                if filled == meta.piece_length:
                    valid = available and digest.digest() == hashes[index * 20 : (index + 1) * 20]
                    states.append(2 if valid else 0)
                    if valid:
                        verified += filled
                    filled, index, digest, available = 0, index + 1, hashlib.sha1(), True
        finally:
            if stream:
                stream.close()
    if filled:
        valid = available and digest.digest() == hashes[index * 20 : (index + 1) * 20]
        states.append(2 if valid else 0)
        if valid:
            verified += filled
    if any(identity(Path(p)) != stamp for p, stamp in before.items()):
        raise ValueError("Local files changed during verification. Inspect them again.")
    total = sum(meta.files.values())
    return {
        "verified_bytes": verified,
        "target_bytes": total,
        "missing_bytes": total - verified,
        "identities": before,
        "piece_states": states,
    }


class Provenance:
    def __init__(self, directory: Path):
        self.path = directory / "library-evidence.sqlite"

    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path)
        db.execute(
            "CREATE TABLE IF NOT EXISTS evidence (item TEXT, hash TEXT, body TEXT, "
            "PRIMARY KEY(item, hash))"
        )
        return db

    def inspect(self, item: LocalItem, data: bytes, stop: threading.Event) -> dict:
        meta = safe_torrent(data)
        files, mapping, ambiguous = [], {}, False
        used: set[str] = set()
        for name, size in meta.files.items():
            candidates = [p for p, length in item.files.items() if length == size and p not in used]
            exact = [p for p in candidates if PurePosixPath(p).name == PurePosixPath(name).name]
            choices = exact if len(exact) == 1 else candidates
            local = choices[0] if len(choices) == 1 else ""
            ambiguous |= len(choices) > 1
            if local:
                mapping[name] = item.save_path / local
                used.add(local)
            files.append({"original": name, "local": local, "candidates": candidates})
        checked = (
            verify_pieces(meta, mapping, stop)
            if not ambiguous
            else {
                "verified_bytes": 0,
                "target_bytes": sum(meta.files.values()),
                "missing_bytes": sum(meta.files.values()),
                "identities": {},
            }
        )
        status = (
            "ambiguous"
            if ambiguous
            else "verified"
            if checked["missing_bytes"] == 0
            else "partial"
            if checked["verified_bytes"]
            else "unverified"
        )
        result = {
            "hash": meta.infohash,
            "name": meta.name,
            "status": status,
            "files": files,
            **checked,
        }
        with closing(self._connect()) as db, db:
            db.execute(
                "INSERT OR REPLACE INTO evidence VALUES (?, ?, ?)",
                (str(item.path), meta.infohash, json.dumps(result)),
            )
        return result

    def names(self, item: LocalItem) -> list[str]:
        """Verified original release names, offered explicitly during upload preparation."""
        names = {row["name"] for row in self.rows(item) if row["status"] == "verified"}
        if item.path.is_file():
            names = {Path(name).stem for name in names}
        return sorted(names)

    def rows(self, item: LocalItem) -> list[dict]:
        with closing(self._connect()) as db, db:
            rows = [
                json.loads(row[0])
                for row in db.execute(
                    "SELECT body FROM evidence WHERE item = ? ORDER BY hash", (str(item.path),)
                )
            ]
        for row in rows:
            try:
                current = all(identity(Path(p)) == stamp for p, stamp in row["identities"].items())
            except (ValueError, OSError):
                current = False
            if not current:
                row["status"] = "stale"
        return rows
