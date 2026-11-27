"""What is keyed by a path follows a folder that was moved or renamed (ADR-0029, rule 6).

Library Folders, Download Folders, the app side of Path Mappings and Member folder grants are
rewritten in the same operation as the move, so nothing points at the old place. (Link Folder
manifests are keyed by torrent, not by the library path, and are left alone.)
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any


def moved(path: str, old: Path, new: Path) -> str | None:
    """`path` after `old` became `new`, or None when it was not inside `old`."""
    here = Path(path)
    if here == old or here.is_relative_to(old):
        return str(new / here.relative_to(old))
    return None


def follow_move(setup: Any, accounts: Any, old: Path, new: Path) -> dict[str, int]:
    """Rewrite every setting and grant that pointed into `old`; returns what changed."""
    changed = {"library": 0, "downloads": 0, "mappings": 0, "grants": 0}
    with setup.lock:
        settings = setup.settings
        folders = []
        for folder in settings.library_folders:
            target = moved(str(folder.path), old, new)
            changed["library"] += target is not None
            folders.append(replace(folder, path=Path(target)) if target else folder)
        settings.library_folders = folders
        downloads = settings.download_folders
        if downloads.default and (target := moved(downloads.default, old, new)):
            downloads.default, changed["downloads"] = target, changed["downloads"] + 1
        for category, value in list(downloads.by_category.items()):
            if target := moved(value, old, new):
                downloads.by_category[category] = target
                changed["downloads"] += 1
        mappings = []
        for mapping in settings.path_mappings:
            target = moved(mapping.local, old, new)
            changed["mappings"] += target is not None
            mappings.append(replace(mapping, local=target) if target else mapping)
        settings.path_mappings = mappings
        if any(changed.values()):
            (setup._root or setup).save()
    if accounts is not None:
        with accounts.lock, accounts.db:
            for row in accounts.db.execute(
                "SELECT account, folders FROM media_limits WHERE folders IS NOT NULL"
            ).fetchall():
                granted = json.loads(row["folders"])
                rewritten = [moved(f, old, new) or f for f in granted]
                if rewritten != granted:
                    accounts.db.execute(
                        "UPDATE media_limits SET folders=? WHERE account=?",
                        (json.dumps(sorted(set(rewritten))), row["account"]),
                    )
                    changed["grants"] += 1
    return changed
