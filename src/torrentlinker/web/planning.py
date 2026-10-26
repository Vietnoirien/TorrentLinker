"""Plan against verified mounted destinations, using the existing selection engine."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import asdict
from typing import Any

from torrentlinker.catalogue import plan_categories
from torrentlinker.catalogue_sync import SNAPSHOT_NAME, sync_catalogue
from torrentlinker.domain import LibraryFolder
from torrentlinker.plan import (
    Plan,
    PlanOptions,
    catalogue_candidates,
    disk_of,
    disk_space,
    explain_inputs,
    make_plan,
    on_disk,
)
from torrentlinker.plan_diagnostics import PlanIssue, issue_text
from torrentlinker.scan import scan
from torrentlinker.seeding import seeding
from torrentlinker.web.library import Library
from torrentlinker.web.setup import Setup


def catalogue_status(setup: Setup) -> dict:
    store = setup.store
    snapshot = store.feed_state(SNAPSHOT_NAME)
    return {
        "count": store.catalogue_size(),
        "updated_at": store.catalogue_updated_at(),
        "limited_categories": sorted(store.limited_categories()),
        "paused": store.crawl_paused(),
        "snapshot_imported_at": snapshot.updated_at,
    }


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
    return catalogue_status(setup)


def plan(
    setup: Setup,
    library: Library,
    maximum_bytes: int,
    maximum_torrents: int,
    stop: threading.Event,
    progress: Callable[[Any], None],
    *,
    cached_only: bool = False,
    category: int | None = None,
    options: PlanOptions | None = None,
) -> dict:
    settings = setup.settings
    if category is not None:
        relevant = plan_categories(
            [category], settings.download_folders, settings.indexer_categories
        )
        destinations = (setup.download_folder(c) for c in relevant)
        folders = list(dict.fromkeys(path for path in destinations if path is not None))
        for folder in folders:
            setup.configure_download_folder(str(folder))
    else:
        configured = settings.download_folders
        paths = dict.fromkeys([configured.default, *configured.by_category.values()])
        folders = []
        for value in paths:
            if value:
                setup.configure_download_folder(value)
                folders.append(setup.path_under_root(value))
    for folder in folders:
        library.check_tree(folder, stop)
    if not cached_only:
        sync_catalogue(
            setup.indexer(),
            setup.store,
            plan_categories(
                [category] if category is not None else settings.indexer_categories,
                settings.download_folders,
                settings.indexer_categories,
            ),
            bootstrap=True,
            max_pages=10,
            stop=stop.is_set,
            progress=lambda p: progress(asdict(p)),
            categories=settings.indexer_categories,
        )
    if stop.is_set():
        return {"cancelled": True, "catalogue": catalogue_status(setup)}
    torrents = setup.client().torrents(with_files=False)
    cached = {r.infohash: r for r in setup.store.catalogue()}
    current = seeding(settings.zen, torrents, settings.indexer.url, catalogue=cached)
    issues: list[PlanIssue] = []
    candidates = catalogue_candidates(
        cached.values(),
        settings.download_folders,
        settings.indexer_categories,
        {t.hash.lower() for t in torrents},
        disk_of,
        {category} if category is not None else None,
        settings.plan_exclusions,
        issues=issues,
    )
    existing = [
        row
        for folder in folders
        for row in on_disk(candidates, scan(LibraryFolder(folder), setup.store).require_complete())
    ]
    exclude = {r.infohash for r in existing}
    spaces = disk_space(folders, settings.free_space_margin)
    available = {space.disk: space.available for space in spaces}
    slots = max(0, settings.zen.torrent_cap - current.count) if settings.zen.torrent_cap else None
    proposed = make_plan(
        settings.zen,
        [c for c in candidates if c.infohash not in exclude],
        available,
        current.active,
        slots,
        options=options
        or PlanOptions(max_download_bytes=maximum_bytes, max_torrents=maximum_torrents),
        disk_spaces=spaces,
    )
    proposed = explain_inputs(proposed, issues, existing)
    return {
        "issues": [{**asdict(issue), "message": issue_text(issue)} for issue in proposed.issues],
        "provisional": True,
        "catalogue": catalogue_status(setup),
        "rows": [
            {
                "hash": i.candidate.infohash,
                "title": i.candidate.title,
                "size": i.candidate.size,
                "seeders": i.candidate.seeders,
                "zen": i.zen,
                "note": i.note,
                "folder": str(i.candidate.folder),
                "client_id": setup.settings.active_client_id,
            }
            for i in proposed.items
        ],
        "zen": proposed.zen_added,
        "size": proposed.download_size,
        "excluded": len(existing),
        "storage": plan_storage(proposed),
    }


def plan_storage(proposed: Plan) -> list[dict]:
    return [
        {
            "folder": str(space.folder),
            "free": space.free,
            "reserved": space.reserved,
            "download": space.download,
            "after_plan": space.after_plan,
        }
        for space in proposed.disk_spaces
    ]
