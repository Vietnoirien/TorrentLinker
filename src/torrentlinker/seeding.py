"""The Seeding view: the user's Indexer torrents in qBittorrent and their Zen Estimate.

Uses only what qBittorrent knows (tracker, swarm seeders, seeding time), so no request
reaches the Indexer.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from torrentlinker.domain import Torrent
from torrentlinker.zen import (
    ZenDay,
    ZenProfile,
    ZenTorrent,
    estimate,
    is_indexer_torrent,
    seed_days,
)


@dataclass(frozen=True)
class SeedingRow:
    torrent: Torrent
    zen: float | None  # None when the torrent is not seeding


@dataclass(frozen=True)
class Seeding:
    rows: list[SeedingRow]
    day: ZenDay
    active: list[ZenTorrent]  # the seeding torrents, as the Zen rules see them

    @property
    def count(self) -> int:
        return sum(1 for r in self.rows if r.zen is not None)


def zen_torrent(t: Torrent) -> ZenTorrent:
    return ZenTorrent(t.total_size, max(t.swarm_seeders, 1), seed_days(t.seeding_time))


def indexer_torrents(torrents: Iterable[Torrent], indexer_url: str) -> list[Torrent]:
    return [t for t in torrents if is_indexer_torrent(t.tracker, indexer_url)]


def seeding(
    profile: ZenProfile, torrents: Iterable[Torrent], indexer_url: str, uploads: int = 0
) -> Seeding:
    """Every Indexer torrent in qBittorrent, with a Zen Estimate for those seeding."""
    mine = indexer_torrents(torrents, indexer_url)
    active = [t for t in mine if t.is_seeding]
    as_zen = [zen_torrent(t) for t in active]
    day = estimate(profile, as_zen, uploads)
    zen = dict(zip((t.hash for t in active), day.per_torrent, strict=True))
    return Seeding([SeedingRow(t, zen.get(t.hash)) for t in mine], day, as_zen)
