"""Small WebP copies of posters, generated once and keyed so a changed poster makes a new copy."""

from __future__ import annotations

import hashlib
import os
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
