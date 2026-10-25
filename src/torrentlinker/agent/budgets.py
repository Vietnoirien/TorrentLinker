"""Conservative daily reservations and final checks before a client receives data."""

from __future__ import annotations

import json
import math
import shutil
from datetime import UTC, datetime
from pathlib import Path

from torrentlinker.agent.access import Access, Grant
from torrentlinker.download_queue import entries
from torrentlinker.paths import PathMapper
from torrentlinker.plan import disk_of
from torrentlinker.torrent_meta import read_torrent
from torrentlinker.web.operations import JobRequest, Operations


def outstanding(access: Access, target: Operations, disk: str, exclude: str = "") -> int:
    """Account for unallocated client data and sends not yet observable in a client."""
    setup = target.setup._root or target.setup
    observed: dict[str, set[str]] = {}
    completed: dict[str, set[str]] = {}
    remaining = 0
    for profile in setup.settings.client_profiles:
        folders = profile.download_folders
        paths = [Path(p) for p in [folders.default, *folders.by_category.values()] if p]
        if not profile.enabled or not any(str(disk_of(p)) == disk for p in paths):
            continue
        scoped = (
            target.setup
            if profile.id == target.setup.settings.active_client_id
            else setup.for_client(profile.id)
        )
        try:
            torrents = scoped.client().torrents(with_files=False)
        except Exception:
            raise ValueError(
                "Cannot verify pending downloads on a client sharing this disk."
            ) from None
        observed[profile.id] = {t.hash.lower() for t in torrents}
        completed[profile.id] = {t.hash.lower() for t in torrents if t.progress >= 1}
        mapper = PathMapper(profile.path_mappings)
        for torrent in torrents:
            if torrent.progress >= 1:
                continue
            path = Path(mapper.to_local(str(torrent.save_path)))
            if str(disk_of(path)) == disk:
                remaining += math.ceil(torrent.total_size * (1 - max(0, torrent.progress)))
    for row in access.db.execute(
        "SELECT r.bytes,p.body,r.proposal_id FROM reservations r JOIN proposals p "
        "ON p.id=r.proposal_id "
        "WHERE r.disk=? AND r.proposal_id<>? AND r.storage_reconciled=0",
        (disk, exclude),
    ):
        request = json.loads(row[1])
        if set(request["hashes"]).issubset(completed.get(request["client_id"], set())):
            with access.db:
                access.db.execute(
                    "UPDATE reservations SET storage_reconciled=1 WHERE proposal_id=?", (row[2],)
                )
            continue
        # Missing or unavailable client data is uncertain, including after a restart.
        # Keep the whole reservation until every selected hash is observable.
        if not set(request["hashes"]).issubset(observed.get(request["client_id"], set())):
            remaining += row[0]
    return remaining


def reserve(
    access: Access, identifier: str, actor: str, grant: Grant, target: Operations, body: JobRequest
) -> dict[str, int]:
    if body.kind not in {"enqueue", "send-queue"}:
        return {}
    if not body.hashes:
        raise ValueError("Select explicit torrent hashes; MCP cannot send the whole shared queue.")
    if body.kind == "enqueue":
        rows = {r.infohash: r for r in target.setup.store.catalogue(body.hashes)}
        sizes = {
            h: target.candidates[h].size
            if h in target.candidates and not body.selection_id
            else rows[h].size
            for h in body.hashes
            if h in rows or h in target.candidates
        }
    else:
        queued = {
            e.candidate.infohash: e
            for e in entries(target.setup.store)
            if e.status == "queued" and e.candidate.infohash in body.hashes
        }
        sizes = {h: e.candidate.size for h, e in queued.items()}
        if any(str(e.folder) not in target.download_destinations() for e in queued.values()):
            raise ValueError(
                "A queued destination changed. Queue it again in the configured folder."
            )
    if set(sizes) != set(body.hashes) or any(s <= 0 for s in sizes.values()):
        raise ValueError("Search again: every selected torrent needs a known, positive size.")
    day = datetime.now(UTC).date().isoformat()
    used = access.db.execute(
        "SELECT COALESCE(SUM(bytes),0),COALESCE(SUM(torrents),0) FROM reservations "
        "WHERE grant_id=? AND day=?",
        (actor, day),
    ).fetchone()
    if (
        used[0] + sum(sizes.values()) > grant.daily_bytes
        or used[1] + len(sizes) > grant.daily_torrents
    ):
        raise ValueError("This operation exceeds the connection's daily download budget.")
    if body.kind == "send-queue":
        destinations = {e.folder for e in queued.values()}
        if len({str(disk_of(p)) for p in destinations}) != 1:
            raise ValueError("Send downloads on one disk at a time to reserve storage safely.")
        folder = target.setup.path_under_root(str(next(iter(destinations))))
        disk_sizes = {str(disk_of(folder)): (folder, sum(sizes.values()))}
    else:
        disk_sizes = {}
        for h, folder in target.enqueue_folders(body).items():
            disk = str(disk_of(folder))
            disk_sizes[disk] = (folder, disk_sizes.get(disk, (folder, 0))[1] + sizes[h])
    # Categories may use different disks; charge each disk only for its own downloads.
    for disk, (folder, size) in disk_sizes.items():
        pending = outstanding(access, target, disk)
        usage = shutil.disk_usage(folder)
        reserve_bytes = max(
            grant.reserve_bytes,
            int(usage.total * target.setup.settings.free_space_margin),
        )
        if usage.free - pending - size < reserve_bytes:
            raise ValueError(
                "The selected downloads would consume the required free-space reserve."
            )
    if body.kind == "send-queue":
        with access.db:
            access.db.execute(
                "INSERT INTO reservations (proposal_id,grant_id,day,bytes,torrents,disk) "
                "VALUES (?,?,?,?,?,?)",
                (identifier, actor, day, sum(sizes.values()), len(sizes), disk),
            )
    return sizes


def download_guard(
    access: Access,
    actor: str,
    grant: Grant,
    sizes: dict[str, int],
    stop,
    target: Operations,
    identifier: str,
):
    remaining = dict(sizes)

    def check(data: bytes, folder: str) -> None:
        access.grant(actor)
        if stop.is_set():
            raise ValueError("Agent job cancelled.")
        meta = read_torrent(data)
        size = sum(meta.files.values())
        if meta.infohash not in remaining or size > remaining[meta.infohash]:
            raise ValueError("Torrent size or identity changed. Review a new proposal.")
        with access.lock:
            pending = outstanding(access, target, str(disk_of(Path(folder))), identifier)
        usage = shutil.disk_usage(Path(folder))
        if usage.free - pending - sum(remaining.values()) < max(
            grant.reserve_bytes, int(usage.total * target.setup.settings.free_space_margin)
        ):
            raise ValueError("The free-space reserve is no longer available.")
        remaining.pop(meta.infohash)

    return check
