"""What Médias knows about replacing a library film (ADR-0029, #203, #204).

`replace_context` describes the old release of a "Meilleure version sur le tracker" film (its
file, whether its torrent still seeds, and where the new release would land);
`follow_replacement` moves the watch state, progress and playlists of the old file to the new one.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from torrentlinker.library_replace import SEEDING, placement
from torrentlinker.media import VIDEO, identity
from torrentlinker.paths import PathMapper


def _top_level(torrent, mapper: PathMapper) -> list[Path]:
    """What the torrent put on disk: its files, or the folder holding them."""
    base = Path(mapper.to_local(str(torrent.save_path)))
    return sorted({base / Path(name).parts[0] for name in torrent.files})


def _free(folder: Path) -> int:
    stat = os.statvfs(folder)
    return stat.f_bavail * stat.f_frsize


def replace_context(media, client_id: str, setup, infohash: str) -> dict[str, Any]:
    """The library film this tracker release would replace, or `{"available": False}`."""
    upgrades = media._tracker_cache(client_id, "tracker-upgrade")
    key = next(
        (
            k
            for k, entry in upgrades.items()
            if any(r["hash"] == infohash for r in entry.get("releases") or [])
        ),
        None,
    )
    film = media._library_films(client_id).get(key) if key else None
    if not film or not film.get("files"):
        return {"available": False}
    entry = media.tracker_entry(client_id, infohash)
    release = entry["release"]
    current = max(film["files"], key=lambda f: f["size"])
    with media.lock:
        row = media.db.execute(
            "SELECT path FROM media_items WHERE client=? AND id=?", (client_id, current["id"])
        ).fetchone()
    if row is None:
        return {"available": False}
    path = Path(row["path"])
    mapper = PathMapper(setup.settings.path_mappings)
    old: dict[str, Any] = {
        "hash": "", "paths": [str(path)], "seeding": False, "hours": 0.0, "ratio": 0.0,
    }  # fmt: skip
    observed = media.agent.for_client(client_id).observed
    holder = next(
        (
            t
            for t in observed
            if any(
                (Path(mapper.to_local(str(t.save_path))) / name).absolute() == path.absolute()
                for name in t.files
            )
        ),
        None,
    )
    if holder is not None:
        live = holder
        try:
            live = setup.client().torrent(holder.hash, with_files=False) or holder
        except Exception:  # noqa: BLE001 - the observed state is good enough
            pass
        old.update(
            hash=holder.hash.lower(),
            paths=[str(p) for p in _top_level(holder, mapper)],
            seeding=live.progress >= 1 and live.state.lower() in SEEDING,
            hours=round(live.seeding_time / 3600, 1),
            ratio=round(live.ratio, 2),
        )
    try:
        download = setup.verified_download_folder(release.get("category"))
    except Exception:  # noqa: BLE001 - no Download Folder for this category
        download = None
    where = None
    problem = ""
    try:
        found = placement(path.parent, int(release["size"]), download)
        stat = os.statvfs(found.folder)
        where = {
            "folder": str(found.folder), "fallback": found.fallback, "reason": found.reason,
            "free": stat.f_bavail * stat.f_frsize, "beside": str(path.parent),
            "beside_free": _free(path.parent),
        }  # fmt: skip
    except (OSError, ValueError) as error:
        problem = str(error)
    return {
        "available": True,
        "film": key,
        "old": {
            "name": path.name, "size": current["size"], "own_score": release.get("own_score"),
            **old,
        },
        "new": {"name": release["name"], "size": release["size"]},
        "placement": where,
        "problem": problem,
    }  # fmt: skip


def old_item_ids(media, client_id: str, old_paths: list[str]) -> list[str]:
    with media.lock:
        rows = media.db.execute(
            "SELECT id, path FROM media_items WHERE client=?", (client_id,)
        ).fetchall()
    chosen = [Path(p).absolute() for p in old_paths]
    return [
        r["id"] for r in rows if any(Path(r["path"]).absolute().is_relative_to(c) for c in chosen)
    ]


def follow_replacement(media, client_id: str, old_ids: list[str], new_paths: list[Path]) -> None:
    """The new file takes the old one's watch state, progress and playlists; Médias then
    lists only the new one."""
    videos = [p for p in new_paths if p.suffix.lower() in VIDEO]
    if not videos or not old_ids:
        return
    new_id = identity(str(videos[0].absolute()))
    with media.lock, media.db:
        for old in old_ids:
            media.db.execute(
                "INSERT OR REPLACE INTO media_progress"
                " (client, item, position, duration, watched, account, viewer)"
                " SELECT client, ?, position, duration, watched, account, viewer"
                " FROM media_progress WHERE client=? AND item=?",
                (new_id, client_id, old),
            )
            media.db.execute(
                "DELETE FROM media_progress WHERE client=? AND item=?", (client_id, old)
            )
        for row in media.db.execute(
            "SELECT id, items FROM media_playlists WHERE client=?", (client_id,)
        ).fetchall():
            items = json.loads(row["items"])
            swapped: list[str] = []
            for item in items:
                item = new_id if item in old_ids else item
                if item not in swapped:
                    swapped.append(item)
            if swapped != items:
                media.db.execute(
                    "UPDATE media_playlists SET items=? WHERE id=?",
                    (json.dumps(swapped), row["id"]),
                )
        media.db.execute(
            f"DELETE FROM media_items WHERE client=? AND id IN ({','.join('?' * len(old_ids))})",
            (client_id, *old_ids),
        )
