"""The companion kept current in one folder the owner loads unpacked once.

An unpacked extension cannot rewrite its own files, so the app does: it writes the bundled
files there (tied to the server's HTTPS origin on a web server) whenever they differ, and
the extension reloads itself when a reply announces a newer version.
"""

from __future__ import annotations

import json
import os
import shutil
import threading
from pathlib import Path
from urllib.parse import urlsplit

from torrentlinker.companion import bundled_version, extension_files

STAGING = ".updating"


def write_folder(folder: Path, files: dict[str, bytes]) -> bool:
    """Make the folder hold exactly these files; True when anything changed.

    Files are staged in a subfolder and moved over one by one (manifest last), so a reload
    never reads a half-written file.
    """
    folder.mkdir(parents=True, exist_ok=True)
    changed = {
        name
        for name, raw in files.items()
        if not (folder / name).is_file() or (folder / name).read_bytes() != raw
    }
    stale = [
        path
        for path in folder.iterdir()
        if path.is_file()
        and path.name not in files
        and path.suffix in {".js", ".json", ".html", ".css"}
    ]
    if not changed and not stale:
        return False
    staging = folder / STAGING
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir()
    try:
        for name in changed:
            (staging / name).write_bytes(files[name])
        for name in sorted(changed, key=lambda n: n == "manifest.json"):
            os.replace(staging / name, folder / name)
        for path in stale:
            path.unlink(missing_ok=True)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return True


class ManagedCompanion:
    """One managed folder. A web server also needs its public HTTPS origin: TL_PUBLIC_URL,
    else the last one an authenticated owner request arrived on (kept in origin_file)."""

    def __init__(
        self,
        folder: Path | None,
        *,
        origin_file: Path | None = None,
        public_url: str | None = None,
        needs_origin: bool = False,
    ) -> None:
        self.folder = folder
        self.origin_file = origin_file
        self.needs_origin = needs_origin
        self.fixed = self._https(public_url or "")
        self.lock = threading.Lock()

    @staticmethod
    def _https(value: str) -> str | None:
        parts = urlsplit(value.strip())
        if parts.scheme != "https" or not parts.hostname:
            return None
        return f"https://{parts.netloc}".rstrip("/") + parts.path.rstrip("/")

    def origin(self) -> str | None:
        if self.fixed:
            return self.fixed
        try:
            if self.origin_file:
                return self._https(str(json.loads(self.origin_file.read_text()).get("origin")))
        except (OSError, ValueError, AttributeError):
            pass
        return None

    def record(self, origin: str) -> None:
        """Remember the HTTPS origin the owner reached this server on."""
        found = self._https(origin)
        if not found or self.fixed or not self.origin_file or found == self.origin():
            return
        try:
            self.origin_file.write_text(json.dumps({"origin": found}))
        except OSError:
            pass

    def sync(self) -> dict[str, object] | None:
        """Bring the folder up to date; None when no folder is managed."""
        if self.folder is None:
            return None
        info: dict[str, object] = {"path": str(self.folder), "version": None}
        origin = self.origin()
        if self.needs_origin and origin is None:
            info["waiting"] = "origin"
            return info
        with self.lock:
            try:
                write_folder(self.folder, extension_files(origin))
            except OSError as error:
                info["error"] = error.strerror or "write failed"
                return info
        info["version"] = bundled_version()
        return info
