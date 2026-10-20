"""Reconcile: tell which Local Items qBittorrent already seeds."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from torrentlinker.domain import ItemState, LocalItem, Torrent
from torrentlinker.matching import IgnoreList


def classify(
    items: Iterable[LocalItem], torrents: Iterable[Torrent], ignore: IgnoreList = IgnoreList()
) -> dict[Path, ItemState]:
    seeded_files = {t.save_path / rel for t in torrents for rel in t.files}
    states: dict[Path, ItemState] = {}
    for item in items:
        content = [rel for rel in item.files if not ignore.matches(rel)] or list(item.files)
        covered = sum(1 for rel in content if item.save_path / rel in seeded_files)
        if content and covered == len(content):
            states[item.path] = ItemState.SEEDED
        elif covered:
            states[item.path] = ItemState.PARTIALLY_SEEDED
        else:
            states[item.path] = ItemState.ORPHAN
    return states
