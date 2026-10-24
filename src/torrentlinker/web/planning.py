"""Plan against verified mounted destinations, using the existing selection engine."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import asdict
from typing import Any

from torrentlinker.catalogue_sync import sync_catalogue
from torrentlinker.domain import LibraryFolder
from torrentlinker.plan import (
    PlanOptions,
    catalogue_candidates,
    disk_of,
    disk_space,
    make_plan,
    on_disk,
)
from torrentlinker.scan import scan
from torrentlinker.seeding import seeding
from torrentlinker.web.library import Library
from torrentlinker.web.setup import Setup


def catalogue(setup: Setup, stop: threading.Event, progress: Callable[[Any], None]) -> dict:
    sync_catalogue(
        setup.indexer(),
        setup.store,
        setup.settings.indexer_categories,
        bootstrap=True,
        max_pages=10,
        stop=stop.is_set,
        progress=lambda p: progress(asdict(p)),
        categories=setup.settings.indexer_categories,
    )
    return {"count": setup.store.catalogue_size()}


def plan(
    setup: Setup, library: Library, maximum_bytes: int, maximum_torrents: int, stop: threading.Event
) -> dict:
    folder = setup.verified_download_folder()
    library.check_tree(folder, stop)
    torrents = setup.client().torrents(with_files=False)
    settings = setup.settings
    cached = {r.infohash: r for r in setup.store.catalogue()}
    current = seeding(settings.zen, torrents, settings.indexer.url, catalogue=cached)
    candidates = catalogue_candidates(
        cached.values(),
        settings.download_folders,
        settings.indexer_categories,
        {t.hash.lower() for t in torrents},
        disk_of,
    )
    existing = on_disk(candidates, scan(LibraryFolder(folder), setup.store))
    exclude = {r.infohash for r in existing}
    spaces = disk_space([folder], settings.free_space_margin)
    available = {space.disk: space.available for space in spaces}
    slots = max(0, settings.zen.torrent_cap - current.count) if settings.zen.torrent_cap else None
    proposed = make_plan(
        settings.zen,
        [c for c in candidates if c.infohash not in exclude],
        available,
        current.active,
        slots,
        options=PlanOptions(max_download_bytes=maximum_bytes, max_torrents=maximum_torrents),
        disk_spaces=spaces,
    )
    return {
        "rows": [
            {
                "hash": i.candidate.infohash,
                "title": i.candidate.title,
                "size": i.candidate.size,
                "seeders": i.candidate.seeders,
                "zen": i.zen,
                "note": i.note,
            }
            for i in proposed.items
        ],
        "zen": proposed.zen_added,
        "size": proposed.download_size,
        "excluded": len(existing),
    }
