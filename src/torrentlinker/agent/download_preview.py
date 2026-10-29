"""Read-only download feasibility, using the same budgets and mounted destinations as sends."""

from __future__ import annotations

import shutil
import time
from datetime import UTC, datetime

from torrentlinker.agent.budgets import outstanding
from torrentlinker.plan import disk_of
from torrentlinker.queue_selection import validate_snapshot


def preview(
    service,
    actor: str,
    client_id: str,
    saved: dict,
    *,
    maximum_bytes: int | None = None,
    maximum_torrents: int | None = None,
) -> dict:
    target = service.target(actor, client_id)
    grant = service.access.grant(actor)
    if saved["source"] != "queue":
        raise ValueError("Use select_queue before previewing downloads.")
    validate_snapshot(target.setup, saved["rows"], saved["selection_fingerprint"])
    with service.access.lock:
        used = service.access.db.execute(
            "SELECT COALESCE(SUM(bytes),0),COALESCE(SUM(torrents),0) FROM reservations "
            "WHERE grant_id=? AND day=?",
            (actor, datetime.now(UTC).date().isoformat()),
        ).fetchone()
        bytes_left = max(0, grant.daily_bytes - used[0])
        torrents_left = max(0, grant.daily_torrents - used[1])
        try:
            present = {t.hash.lower() for t in target.setup.client().torrents(with_files=False)}
        except Exception:
            present = None
        try:
            indexer_url = target.setup.indexer().url
        except Exception:
            indexer_url = None
        destinations: dict[str, dict] = {}
        rows = []
        allocations: dict[str, int] = {}
        selected_hashes: set[str] = set()
        fit_bytes = fit_count = 0
        selected_disk = None
        for row in saved["rows"]:
            folder = row["folder"]
            blockers = []
            if not row["hash"] or len(row["hash"]) != 40:
                blockers.append("unknown_identity")
            if (maximum_bytes is not None and fit_bytes + row["size"] > maximum_bytes) or (
                maximum_torrents is not None and fit_count >= maximum_torrents
            ):
                blockers.append("explicit_cap")
            if row["hash"] in selected_hashes:
                blockers.append("duplicate_identity")
            if indexer_url is None:
                blockers.append("indexer_unavailable")
            elif row["indexer_url"] != indexer_url:
                blockers.append("indexer_changed")
            if row["status"] != "queued":
                blockers.append("not_queued")
            if row["size"] <= 0:
                blockers.append("unknown_size")
            if present is None:
                blockers.append("client_unavailable")
            elif row["hash"] in present:
                blockers.append("already_in_client")
            if folder not in destinations:
                observation = {
                    "folder": folder,
                    "capacity_bytes": None,
                    "free_bytes": None,
                    "pending_bytes": None,
                    "reserve_bytes": None,
                    "available_bytes": None,
                    "disk": None,
                    "uncertainty": "",
                }
                try:
                    # Missing or unverified paths never fall back to a parent disk.
                    path = target.setup.path_under_root(folder)
                    target.setup.configure_download_folder(folder, probe=False)
                    if folder not in target.download_destinations():
                        raise ValueError("Destination changed.")
                    if present is None:
                        raise ValueError("Client unavailable.")
                    disk = str(disk_of(path))
                    usage = shutil.disk_usage(path)
                    pending = outstanding(service.access, target, disk, reconcile=False)
                    reserve = max(
                        grant.reserve_bytes,
                        int(usage.total * target.setup.settings.free_space_margin),
                    )
                    observation.update(
                        capacity_bytes=usage.total,
                        free_bytes=usage.free,
                        pending_bytes=pending,
                        reserve_bytes=reserve,
                        available_bytes=max(0, usage.free - pending - reserve),
                        disk=disk,
                    )
                except Exception as error:
                    observation["uncertainty"] = target.setup.secrets.redact(str(error))
                destinations[folder] = observation
            observation = destinations[folder]
            disk = observation["disk"]
            if observation["available_bytes"] is None:
                blockers.append("destination_unverified")
            elif row["size"] + allocations.get(disk, 0) > observation["available_bytes"]:
                blockers.append("space_reserve")
            if row["size"] + fit_bytes > bytes_left:
                blockers.append("daily_bytes")
            if fit_count >= torrents_left:
                blockers.append("daily_torrents")
            if selected_disk is not None and disk != selected_disk:
                blockers.append("different_disk")
            if not blockers:
                fit_bytes += row["size"]
                fit_count += 1
                allocations[disk] = allocations.get(disk, 0) + row["size"]
                selected_disk = disk
                selected_hashes.add(row["hash"])
            rows.append({**row, "blockers": blockers, "fits_now": not blockers})
    return {
        "observed_at": time.time(),
        "selected_count": len(rows),
        "total_size_bytes": saved["total_size_bytes"],
        "known_size_bytes": saved.get("known_size_bytes", saved["total_size_bytes"]),
        "unknown_size_count": saved.get("unknown_size_count", 0),
        "remaining_daily_bytes": bytes_left,
        "remaining_daily_torrents": torrents_left,
        "used_daily_bytes": used[0],
        "used_daily_torrents": used[1],
        "destinations": list(destinations.values()),
        "fit_count": fit_count,
        "fit_size_bytes": fit_bytes,
        "rows": rows,
        "reservation_made": False,
        "uncertainty": "Feasibility uses current metadata and observations. "
        "Torrent contents and constraints are checked again before sending.",
    }
