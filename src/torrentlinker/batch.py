"""Batch search: search many Orphans one after the other."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import TypeVar

from torrentlinker.library import LibraryEntry, auto_searchable

R = TypeVar("R")


def run_batch(
    entries: Iterable[LibraryEntry],
    search: Callable[[LibraryEntry], list[R]],
    on_searched: Callable[[int, int, LibraryEntry, list[R]], None],
    cancelled: Callable[[], bool],
    on_error: Callable[[LibraryEntry, Exception], None] = lambda e, err: None,
) -> int:
    """Search every Orphan among `entries`; return how many were processed."""
    queue = auto_searchable(entries)
    done = 0
    for i, entry in enumerate(queue, 1):
        if cancelled():
            break
        try:
            found = search(entry)
        except Exception as err:  # noqa: BLE001 - one bad item must not stop the batch
            on_error(entry, err)
        else:
            on_searched(i, len(queue), entry, found)
        done += 1
    return done
