"""The Library: every Local Item of every Library Folder, with its state."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace

from torrentlinker.domain import ItemState, LibraryFolder, LocalItem, Torrent
from torrentlinker.matching import IgnoreList
from torrentlinker.qbit import Qbit
from torrentlinker.reconcile import classify
from torrentlinker.scan import scan
from torrentlinker.seeding import indexer_torrents
from torrentlinker.store import Store


@dataclass(frozen=True)
class LibraryEntry:
    folder: LibraryFolder
    item: LocalItem
    state: ItemState


def build_library(
    folders: Iterable[LibraryFolder],
    torrents: list[Torrent],
    ignore: IgnoreList = IgnoreList(),
    cache: Store | None = None,
    refresh: bool = False,
) -> list[LibraryEntry]:
    entries: list[LibraryEntry] = []
    for folder in folders:
        items = scan(folder, cache, refresh)
        states = classify(items, torrents, ignore)
        entries.extend(LibraryEntry(folder, i, states[i.path]) for i in items)
    return entries


def indexer_contents(client: Qbit, store: Store, indexer_url: str) -> list[Torrent]:
    """The Indexer's torrents in the Torrent Client, with their files.

    Only they make a Local Item Seeded: a file seeded for another tracker stays an Orphan,
    to be searched and cross-seeded. Files are read for these torrents alone, one request
    each, which spares thousands of requests when the client seeds for other trackers.
    """
    listed = client.torrents(with_files=False)
    known = store.known_hashes([t.hash.lower() for t in listed])
    return [
        replace(t, files=client.files(t.hash)) for t in indexer_torrents(listed, indexer_url, known)
    ]


def auto_searchable(entries: Iterable[LibraryEntry]) -> list[LibraryEntry]:
    """Entries a batch search may pick up: Orphans only, never (Partially) Seeded Items."""
    return [e for e in entries if e.state is ItemState.ORPHAN]
