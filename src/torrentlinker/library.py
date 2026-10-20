"""The Library: every Local Item of every Library Folder, with its state."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from torrentlinker.domain import ItemState, LibraryFolder, LocalItem, Torrent
from torrentlinker.matching import IgnoreList
from torrentlinker.reconcile import classify
from torrentlinker.scan import scan


@dataclass(frozen=True)
class LibraryEntry:
    folder: LibraryFolder
    item: LocalItem
    state: ItemState


def build_library(
    folders: Iterable[LibraryFolder], torrents: list[Torrent], ignore: IgnoreList = IgnoreList()
) -> list[LibraryEntry]:
    entries: list[LibraryEntry] = []
    for folder in folders:
        items = scan(folder)
        states = classify(items, torrents, ignore)
        entries.extend(LibraryEntry(folder, i, states[i.path]) for i in items)
    return entries
