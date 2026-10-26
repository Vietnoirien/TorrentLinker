"""A persistent queue of torrents the user explicitly selected from Search."""

from __future__ import annotations

import hashlib
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, cast

from torrentlinker.category_tags import category_path, category_tag
from torrentlinker.downloads import IndexerCategory
from torrentlinker.indexer import Candidate, Indexer, KeyRefused, RateLimited
from torrentlinker.plan import PlanCandidate
from torrentlinker.qbit import Qbit
from torrentlinker.send import (
    LIMIT_WAITS,
    Refused,
    SendProgress,
    SendReport,
    UncertainSend,
    send_one,
)
from torrentlinker.store import CatalogueRow, Store
from torrentlinker.torrent_meta import read_torrent

SEARCH_TAG = "torrentlinker:search"


@dataclass(frozen=True)
class QueueEntry:
    key: str
    candidate: Candidate
    folder: Path
    indexer_url: str
    status: str = "queued"
    reason: str = ""
    client_id: str = "default"
    priority: int = 0
    added_at: float = 0
    retry_safe: bool = False
    origin: dict = field(default_factory=dict)


def entries(store: Store, *, all_clients: bool = False) -> list[QueueEntry]:
    result = []
    for key, payload, status, reason in store.queued_downloads():
        client_id = str(payload.get("client_id", "default"))
        if not all_clients and client_id != store.client_id:
            continue
        raw = cast(dict[str, Any], payload["candidate"])
        candidate = Candidate(**{**raw, "categories": tuple(raw.get("categories", []))})
        result.append(
            QueueEntry(
                key,
                candidate,
                Path(str(payload["folder"])),
                str(payload["indexer_url"]),
                status,
                reason,
                client_id,
                int(cast(Any, payload.get("priority", 0))),
                float(cast(Any, payload.get("added_at", 0))),
                bool(payload.get("retry_safe", False)),
                cast(dict, payload.get("origin", {})),
            )
        )
    return result


def queue_key(indexer: Indexer, candidate: Candidate) -> str:
    identity = (
        candidate.infohash.lower() if candidate.infohash else indexer.redact(candidate.download_url)
    )
    return hashlib.sha256((indexer.url + "\n" + identity).encode()).hexdigest()


def enqueue(
    store: Store, indexer: Indexer, candidate: Candidate, folder: Path,
    *, origin: dict | None = None
) -> bool:
    if not candidate.download_url:
        raise ValueError("This torrent has no download link.")
    clean = replace(
        candidate,
        download_url=indexer.redact(candidate.download_url),
        details_url=indexer.redact(candidate.details_url),
    )
    key = queue_key(indexer, clean)
    if store.client_id != "default":
        key = store.client_id + ":" + key
    return store.enqueue_download(
        key,
        {
            "candidate": asdict(clean),
            "folder": str(folder),
            "indexer_url": indexer.url,
            "client_id": store.client_id,
            **({"origin": origin} if origin else {}),
        },
    )


def run_queue(
    store: Store,
    indexer: Indexer,
    client: Qbit,
    categories: Mapping[int, IndexerCategory],
    stop: threading.Event,
    progress: Callable[[SendProgress], None],
    wait: Callable[[float], bool] | None = None,
    *,
    only: set[str] | None = None,
    order: list[str] | None = None,
) -> SendReport:
    """Send by priority and insertion order, or an explicitly reviewed snapshot order."""
    report = SendReport()
    pending = [
        entry
        for entry in entries(store)
        if entry.status == "queued" and (only is None or entry.key in only)
    ]
    if order is not None:
        positions = {key: i for i, key in enumerate(order)}
        if any(entry.key not in positions for entry in pending):
            raise ValueError("The send order must explicitly include every selected queue entry.")
        pending.sort(key=lambda entry: positions[entry.key])
    wait = wait or stop.wait
    for entry in pending:
        if stop.is_set():
            report.stopped = True
            break
        c = entry.candidate
        if not store.claim_download(entry.key):
            continue

        def show(retry_at: float | None = None, title: str = c.title) -> None:
            progress(
                SendProgress(
                    report.handled,
                    len(pending),
                    title,
                    len(report.added),
                    len(report.refused),
                    len(report.failed),
                    retry_at,
                )
            )

        show()
        accepted = False
        try:
            if entry.indexer_url != indexer.url:
                raise Refused("The Indexer changed. Search again before downloading this torrent.")
            if c.infohash and client.torrent(c.infohash) is not None:
                raise Refused("Already in the torrent client.")
            if not entry.folder.is_dir():
                raise Refused("The Download Folder is not accessible.")
            c = replace(c, download_url=indexer.unredact(c.download_url))
            limited = 0
            while True:
                try:
                    data = indexer.fetch_torrent(c, retry=False)
                    break
                except RateLimited as error:
                    delay = max(error.retry_after, LIMIT_WAITS[min(limited, len(LIMIT_WAITS) - 1)])
                    limited += 1
                    show(time.time() + delay)
                    if wait(delay):
                        stop.set()
                        break
            if stop.is_set():
                store.download_outcome(entry.key, "queued")
                report.stopped = True
                break
            meta = read_torrent(data)
            if c.infohash and c.infohash.lower() != meta.infohash.lower():
                raise Refused("The downloaded torrent does not match the selected result.")
            category = max(
                c.categories, key=lambda cid: len(category_path(cid, categories)), default=None
            )
            tags = [SEARCH_TAG]
            if client.supports_category_tags and (tag := category_tag(category, categories)):
                tags.append(tag)
            planned = PlanCandidate(
                meta.infohash, c.title, c.size, c.seeders, category, entry.folder
            )
            send_one(client, planned, data, tags=tags)
            accepted = True
            store.save_catalogue(
                [
                    CatalogueRow(
                        meta.infohash,
                        c.title,
                        c.size,
                        c.seeders,
                        category,
                        indexer.redact(c.download_url),
                        indexer.redact(c.details_url),
                        time.time(),
                    )
                ]
            )
        except Refused as error:
            reason = indexer.redact(str(error))
            store.download_outcome(entry.key, "refused", reason)
            report.refused.append((c.title, reason))
        except Exception as error:
            reason = indexer.redact(str(error) or type(error).__name__)
            store.download_outcome(
                entry.key,
                "uncertain" if accepted or isinstance(error, UncertainSend) else "failed",
                reason,
                retry_safe=not accepted and not isinstance(error, UncertainSend),
            )
            report.failed.append((c.title, reason))
            if isinstance(error, KeyRefused):
                report.stopped = True
                break
        else:
            store.download_outcome(entry.key, "sent")
            report.added.append(c.title)
        show()
    return report
