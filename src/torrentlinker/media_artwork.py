"""Small WebP copies of posters, generated once and keyed so a changed poster makes a new copy."""

from __future__ import annotations

import hashlib
import os
import re
import threading
from pathlib import Path
from typing import Any
from uuid import uuid4

WIDTHS = {"grid": 342, "hero": 780}
_locks: dict[str, threading.Lock] = {}
_guard = threading.Lock()


def download_lock(key: str) -> threading.Lock:
    """One lock per remote poster: two requests for an uncached poster download it once."""
    with _guard:
        return _locks.setdefault("download:" + key, threading.Lock())


def link(identifier: str, client_id: str, body: dict[str, Any]) -> str:
    """The row's artwork URL; its version changes with the poster, so a browser may keep it."""
    if not (body.get("artwork") or body.get("remote_artwork")):
        return ""
    seen = "|".join(
        str(body.get(k) or "") for k in ("artwork", "remote_artwork", "sidecar_signature")
    )
    version = hashlib.sha1(seen.encode(), usedforsecurity=False).hexdigest()[:12]
    return f"api/media/items/{identifier}/artwork?client_id={client_id}&v={version}"


def key(path: Path, folder: Path) -> str:
    """A cached poster is named by its content; a local one by where it is and when it changed."""
    if path.parent == folder:
        return path.stem
    info = path.stat()
    return hashlib.sha256(f"{path}|{info.st_mtime_ns}|{info.st_size}".encode()).hexdigest()


def variant(path: Path, folder: Path, size: str) -> Path:
    """The poster at `size` ("grid" or "hero") in `folder`/variants, made on first use."""
    if size not in WIDTHS:
        raise ValueError("Unknown artwork size.")
    target = folder / "variants" / f"{key(path, folder)}-{size}.webp"
    if target.is_file() and not target.is_symlink():
        return target
    with _guard:
        lock = _locks.setdefault(str(target), threading.Lock())
    with lock:  # two requests for one copy wait; the second finds it made
        if target.is_file() and not target.is_symlink():
            return target
        if target.parent.is_symlink() or target.is_symlink():
            raise ValueError("Artwork cache contains an unsafe path.")
        from PIL import Image

        target.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(path) as picture:
            if picture.width * picture.height > 32_000_000:
                raise ValueError("Artwork dimensions are too large.")
            picture.load()
            picture.thumbnail((WIDTHS[size], 100_000))  # never enlarged
            partial = target.with_name(f".{uuid4().hex}.tmp")
            try:
                picture.convert("RGB").save(partial, format="WEBP", quality=80, method=4)
                os.replace(partial, target)
            finally:
                partial.unlink(missing_ok=True)
    return target


MASTER_PNG = re.compile(r"^([a-f0-9]{64})\.png$")


def png_masters(folder: Path) -> list[Path]:
    """The masters still stored as PNG. They sit beside `variants`, never inside it."""
    if not folder.is_dir():
        return []
    return sorted(path for path in folder.glob("*.png") if MASTER_PNG.match(path.name))


def to_webp(path: Path) -> Path:
    """Write `path` beside itself as WebP and return it; the PNG is left for the caller.

    A poster is a photograph, and PNG stored it losslessly at about ten times the size. The
    name is kept: it is the hash of the bytes as downloaded, so only the suffix changes and
    the `-grid`/`-hero` copies named from the stem stay valid.
    """
    from PIL import Image

    target = path.with_suffix(".webp")
    partial = path.with_name(f".{uuid4().hex}.tmp")
    try:
        with Image.open(path) as picture:
            picture.load()
            picture.convert("RGB").save(partial, format="WEBP", quality=90, method=4)
        partial.replace(target)
    finally:
        partial.unlink(missing_ok=True)
    return target


def repoint(db: Any, old: str, new: str) -> int:
    """Name `new` wherever a stored record names `old`. Returns the rows changed.

    The caller holds the transaction: a master is deleted only once every reference to it has
    moved, so an interrupted pass leaves records pointing at a file that is still there.
    """
    changed = 0
    for table, identity in (("media_items", ("client", "id")), ("media_options", ("key",))):
        columns = ", ".join(identity)
        rows = db.execute(
            f"SELECT {columns}, body FROM {table} WHERE body LIKE ?",  # noqa: S608 - fixed names
            (f"%{old}%",),
        ).fetchall()
        for row in rows:
            where = " AND ".join(f"{name}=?" for name in identity)
            db.execute(
                f"UPDATE {table} SET body=? WHERE {where}",  # noqa: S608 - fixed names
                (row[-1].replace(old, new), *row[:-1]),
            )
            changed += 1
    return changed
