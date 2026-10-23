"""The Seeding view: the user's Indexer torrents in qBittorrent and their Zen Estimate.

Uses only what qBittorrent knows (tracker, swarm seeders, seeding time), so no request
reaches the Indexer.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass, field

from torrentlinker.category_tags import CategoryTagSync
from torrentlinker.domain import Torrent
from torrentlinker.downloads import IndexerCategory
from torrentlinker.reseed import TAG
from torrentlinker.store import CatalogueRow, Store
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
    category: int | None = None
    provisional_category: bool = False


@dataclass(frozen=True)
class Seeding:
    rows: list[SeedingRow]
    day: ZenDay
    active: list[ZenTorrent]  # the seeding torrents, as the Zen rules see them
    categories: dict[int, IndexerCategory] = field(default_factory=dict)
    tag_sync: CategoryTagSync | None = None

    @property
    def count(self) -> int:
        return sum(1 for r in self.rows if r.zen is not None)


def zen_torrent(t: Torrent, cached: CatalogueRow | None = None) -> ZenTorrent:
    seeds = t.swarm_seeders
    if seeds < 0:
        seeds = cached.seeders + 1 if cached else 1
    return ZenTorrent(
        t.total_size,
        max(seeds, 1),
        seed_days(t.seeding_time),
        cached.category if cached else None,
    )


def observe_swarm(
    store: Store, torrents: Iterable[Torrent], indexer_url: str
) -> dict[str, CatalogueRow]:
    """Use qBittorrent's tracker counts for the next Plan, with no Indexer request."""
    mine = indexer_torrents(torrents, indexer_url)
    store.update_catalogue_seeders(
        {
            t.hash.lower(): max(0, t.swarm_seeders - int(t.is_seeding))
            for t in mine
            if t.swarm_seeders >= 0
        }
    )
    return {r.infohash: r for r in store.catalogue([t.hash.lower() for t in mine])}


def indexer_torrents(
    torrents: Iterable[Torrent], indexer_url: str, known: Collection[str] = ()
) -> list[Torrent]:
    """Torrents from the Indexer: by their tracker, or, since a torrent that has not
    announced yet has none, by their infohash in `known` (the Catalogue) or this app's tag.
    """
    return [
        t
        for t in torrents
        if is_indexer_torrent(t.tracker, indexer_url)
        or t.hash.lower() in known
        or any(tag == TAG or tag.startswith(TAG + ":") for tag in t.tags)
    ]


def seeding(
    profile: ZenProfile,
    torrents: Iterable[Torrent],
    indexer_url: str,
    uploads: int = 0,
    *,
    catalogue: Mapping[str, CatalogueRow] = {},
    categories: Mapping[int, IndexerCategory] = {},
) -> Seeding:
    """Every Indexer torrent in qBittorrent, with a Zen Estimate for those seeding."""
    mine = indexer_torrents(torrents, indexer_url, catalogue)
    active = [t for t in mine if t.is_seeding]
    as_zen = [zen_torrent(t, catalogue.get(t.hash.lower())) for t in active]
    day = estimate(profile, as_zen, uploads)
    zen = dict(zip((t.hash for t in active), day.per_torrent, strict=True))
    rows = []
    for torrent in mine:
        cached = catalogue.get(torrent.hash.lower())
        rows.append(
            SeedingRow(
                torrent,
                zen.get(torrent.hash),
                cached.category if cached else None,
                cached is not None and cached.source == "zen-lab",
            )
        )
    return Seeding(rows, day, as_zen, dict(categories))
