"""Reconcile: tell which Local Items qBittorrent already seeds."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from torrentlinker.domain import ItemState, LocalItem, Torrent


def classify(items: Iterable[LocalItem], torrents: Iterable[Torrent]) -> dict[Path, ItemState]:
    seeded_files = {t.save_path / rel for t in torrents for rel in t.files}
    states: dict[Path, ItemState] = {}
    for item in items:
        covered = sum(1 for rel in item.files if item.save_path / rel in seeded_files)
        if item.files and covered == len(item.files):
            states[item.path] = ItemState.SEEDED
        elif covered:
            states[item.path] = ItemState.PARTIALLY_SEEDED
        else:
            states[item.path] = ItemState.ORPHAN
    return states
