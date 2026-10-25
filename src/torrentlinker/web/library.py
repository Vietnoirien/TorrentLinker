"""Headless Library workflows, with mounted-root checks before reading user data."""

from __future__ import annotations

import os
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from torrentlinker.library import LibraryEntry, LibraryResult, build_library, indexer_contents
from torrentlinker.paths import MappedQbit, PathMapper
from torrentlinker.reseed import start_reseed
from torrentlinker.review import check_candidate, remember_candidates, remembered_candidates
from torrentlinker.scan import ScanError, scan_item
from torrentlinker.web.setup import Setup, StorageUnavailableError


class Library:
    def __init__(self, setup: Setup):
        self.setup = setup
        self.entries: list[LibraryEntry] = []

    def client(self) -> MappedQbit:
        return MappedQbit(self.setup.client(), PathMapper(self.setup.settings.path_mappings))

    def check_tree(self, path: Path, stop: threading.Event) -> None:
        self.setup.path_under_root(str(path), directory=path.is_dir())
        if not path.is_dir():
            return

        # Reject links in traversed trees, including in-root cycles, before the existing
        # desktop scanner follows a directory at its configured depth.
        def walk_failed(error: OSError) -> None:
            raise error

        for base, dirs, files in os.walk(path, onerror=walk_failed):
            if stop.is_set():
                raise ValueError("Scan cancelled.")
            for name in (*dirs, *files):
                child = Path(base) / name
                if child.is_symlink():
                    raise ValueError(
                        "The Library Folder contains symbolic links. Choose a directory "
                        "without links."
                    )
                self.setup.path_under_root(str(child), directory=False)

    def scan(self, stop: threading.Event, progress: Callable[[Any], None]) -> dict:
        unavailable = {}
        for folder in self.setup.settings.library_folders:
            if stop.is_set():
                return {"cancelled": True}
            try:
                self.check_tree(folder.path, stop)
            except (OSError, StorageUnavailableError) as error:
                unavailable[folder.path] = error
            except ValueError:
                if stop.is_set():
                    return {"cancelled": True}
                raise
        if stop.is_set():
            return {"cancelled": True}
        torrents = indexer_contents(
            self.client(), self.setup.store, self.setup.settings.indexer.url
        )
        result = LibraryResult()
        for folder in self.setup.settings.library_folders:
            if stop.is_set():
                return {"cancelled": True}
            if folder.path in unavailable:
                result.errors.append(ScanError(folder.path, str(unavailable[folder.path])))
                result.extend(entry for entry in self.entries if entry.folder == folder)
            else:
                scanned = build_library(
                    [folder],
                    torrents,
                    self.setup.settings.matching.ignore,
                    self.setup.store,
                    previous=self.entries,
                )
                result.extend(scanned)
                result.errors.extend(scanned.errors)
            progress({"items": len(result), "folder": str(folder.path)})
        if stop.is_set():
            return {"cancelled": True}
        self.entries = result
        return {
            "count": len(result),
            "partial": bool(result.errors),
            "errors": [
                {"path": str(error.path), "message": error.message} for error in result.errors
            ],
        }

    def rows(self) -> list[dict[str, Any]]:
        return [
            {
                "path": str(e.item.path),
                "name": e.item.path.name,
                "size": e.item.size,
                "state": e.state,
                "kind": e.folder.kind,
                "folder": str(e.folder.path),
            }
            for e in self.entries
        ]

    def entry(self, path: str) -> LibraryEntry:
        for entry in self.entries:
            if str(entry.item.path) == path:
                return entry
        raise ValueError("Scan the Library and select a Local Item first.")

    def check(self, path: str, stop: threading.Event, progress: Callable[[Any], None]) -> list:
        from torrentlinker.review import search_candidates

        entry = self.entry(path)
        self.check_tree(entry.item.path, stop)
        item = scan_item(entry.item.path)
        indexer = self.setup.indexer()
        candidates = search_candidates(
            indexer,
            item,
            entry.folder.kind,
            self.setup.settings.categories(entry.folder.kind),
            indexer.supported_modes(),
        )
        remember_candidates(self.setup.store, indexer, item.path, candidates)
        result = []
        for candidate in candidates:
            if stop.is_set():
                break
            checked = check_candidate(
                indexer, item, candidate, self.setup.settings.matching.rules()
            )
            result.append(
                {
                    "hash": candidate.infohash,
                    "title": candidate.title,
                    "size": candidate.size,
                    "seeders": candidate.seeders,
                    "match": "full"
                    if checked.match and checked.match.is_full
                    else "partial"
                    if checked.match
                    else "none",
                    "archive": checked.unpack is not None,
                }
            )
            progress({"done": len(result), "total": len(candidates)})
        return result

    def reseed(self, path: str, hash: str, stop: threading.Event) -> dict:
        entry = self.entry(path)
        self.check_tree(entry.item.path, stop)
        item = scan_item(entry.item.path)
        indexer = self.setup.indexer()
        candidates = remembered_candidates(self.setup.store, indexer, item.path) or []
        candidate = next((c for c in candidates if c.infohash == hash), None)
        if candidate is None:
            raise ValueError("Check this Local Item's Candidates first.")
        checked = check_candidate(indexer, item, candidate, self.setup.settings.matching.rules())
        if checked.unpack or not checked.match or not checked.meta:
            raise ValueError(
                "This Candidate requires extraction or has no Match. Prepare it in"
                " the desktop application."
            )
        client = self.client()
        if client.requires_disk_renames and checked.match.renames:
            raise ValueError(
                "This µTorrent Reseed requires disk renames. Review and approve "
                "those in the desktop application."
            )
        hash = start_reseed(client, self.setup.store, item, checked.meta, checked.match, hash)
        return {"hash": hash, "status": "verifying"}
