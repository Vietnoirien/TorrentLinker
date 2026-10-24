"""The Library: every Local Item of every Library Folder, with its state."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from functools import partial
from pathlib import Path
from typing import Literal, TypeVar

import httpx
import requests

from torrentlinker.deluge import DelugeError
from torrentlinker.domain import ItemState, LibraryFolder, LocalItem, Torrent
from torrentlinker.matching import IgnoreList
from torrentlinker.qbit import Qbit
from torrentlinker.reconcile import classify
from torrentlinker.scan import scan
from torrentlinker.seeding import indexer_torrents
from torrentlinker.store import Store


class LibraryReadTimeout(TimeoutError):
    """A scan timed out, with enough context to distinguish client reads from disk I/O."""

    def __init__(self, operation: Literal["torrents", "files", "folder"], target: str = ""):
        self.operation = operation
        self.target = target
        message = {
            "torrents": (
                "The Torrent Client timed out while reading its torrent list after two attempts."
            ),
            "files": (
                f"The Torrent Client timed out while reading the files of {target} "
                "after two attempts."
            ),
            "folder": f"Reading the Library Folder timed out: {target}",
        }[operation]
        super().__init__(message)


T = TypeVar("T")


def _timed_out(error: BaseException) -> bool:
    # qBittorrent wraps requests timeouts in APIConnectionError; retain the cause.
    seen: set[int] = set()
    while id(error) not in seen:
        seen.add(id(error))
        if isinstance(error, TimeoutError | httpx.TimeoutException | requests.Timeout):
            return True
        # A timeout inside Deluge's daemon can arrive as a JSON-RPC error instead.
        if isinstance(error, DelugeError) and str(error).strip().casefold() == "timed out":
            return True
        nested = error.__cause__ or error.__context__
        if nested is None:
            break
        error = nested
    return False


def _client_read(
    read: Callable[[], T], operation: Literal["torrents", "files"], target: str = ""
) -> T:
    """Retry a timed-out read once. Never retry commands or accept incomplete contents."""
    try:
        return read()
    except Exception as error:
        if not _timed_out(error):
            raise
    try:
        return read()
    except Exception as error:
        if not _timed_out(error):
            raise
        raise LibraryReadTimeout(operation, target) from error


@dataclass(frozen=True)
class LibraryEntry:
    folder: LibraryFolder
    item: LocalItem
    state: ItemState
    torrent_hashes: frozenset[str] = frozenset()


def build_library(
    folders: Iterable[LibraryFolder],
    torrents: list[Torrent],
    ignore: IgnoreList = IgnoreList(),
    cache: Store | None = None,
    refresh: bool = False,
) -> list[LibraryEntry]:
    file_hashes: dict[Path, set[str]] = {}
    for torrent in torrents:
        for rel in torrent.files:
            file_hashes.setdefault(torrent.save_path / rel, set()).add(torrent.hash.lower())
    entries: list[LibraryEntry] = []
    for folder in folders:
        try:
            items = scan(folder, cache, refresh)
        except TimeoutError as error:
            raise LibraryReadTimeout("folder", str(folder.path)) from error
        states = classify(items, torrents, ignore)
        for item in items:
            content = [rel for rel in item.files if not ignore.matches(rel)] or list(item.files)
            hashes = frozenset(
                hash for rel in content for hash in file_hashes.get(item.save_path / rel, ())
            )
            entries.append(LibraryEntry(folder, item, states[item.path], hashes))
    return entries


def indexer_contents(client: Qbit, store: Store, indexer_url: str) -> list[Torrent]:
    """The Indexer's torrents in the Torrent Client, with their files.

    Only they make a Local Item Seeded: a file seeded for another tracker stays an Orphan,
    to be searched and cross-seeded. Files are read for these torrents alone, one request
    each, which spares thousands of requests when the client seeds for other trackers.
    """
    listed = _client_read(lambda: client.torrents(with_files=False), "torrents")
    known = store.known_hashes([t.hash.lower() for t in listed])
    return [
        replace(t, files=_client_read(partial(client.files, t.hash), "files", t.name))
        for t in indexer_torrents(listed, indexer_url, known)
    ]


def auto_searchable(entries: Iterable[LibraryEntry]) -> list[LibraryEntry]:
    """Entries a batch search may pick up: Orphans only, never (Partially) Seeded Items."""
    return [e for e in entries if e.state is ItemState.ORPHAN]
