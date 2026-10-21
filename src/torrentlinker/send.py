"""Send a Plan to qBittorrent: download its torrents into their Download Folders.

Each .torrent comes straight from the Indexer with the user's key. A torrent is
refused when any of its files already exists at the target: the app never writes to a
file it did not create (ADR-0004).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from torrentlinker.plan import Plan, PlanCandidate
from torrentlinker.qbit import Qbit
from torrentlinker.torrent_meta import TorrentMeta, read_torrent

ZEN_TAG = "torrentlinker:zen"


@dataclass
class SendReport:
    added: list[str] = field(default_factory=list)  # titles
    reseeded: list[str] = field(default_factory=list)
    refused: list[tuple[str, str]] = field(default_factory=list)  # title, reason
    failed: list[tuple[str, str]] = field(default_factory=list)  # title, error


class Refused(Exception):
    pass


def existing_targets(folder: Path, meta: TorrentMeta) -> list[Path]:
    """Files of the torrent that already exist under `folder` (or would escape it)."""
    found = []
    for name in meta.files:
        parts = PurePosixPath(name).parts
        if (
            not parts
            or any(p in ("", ".", "..") for p in parts)
            or PurePosixPath(name).is_absolute()
        ):
            raise Refused(f"unsafe path in torrent: {name}")
        target = folder.joinpath(*parts)
        # A file standing where the torrent needs a folder blocks it too.
        blockers = [target, *(folder.joinpath(*parts[:i]) for i in range(1, len(parts)))]
        if target.exists() or any(b.is_file() for b in blockers[1:]):
            found.append(target)
    return found


def send_one(qbit: Qbit, candidate: PlanCandidate, data: bytes) -> str:
    """Add one Plan torrent, started, into its Download Folder; return its hash."""
    if candidate.folder is None:
        raise Refused("no Download Folder")
    meta = read_torrent(data)
    if qbit.torrent(meta.infohash) is not None:
        raise Refused("already in qBittorrent")
    if existing := existing_targets(candidate.folder, meta):
        raise Refused(f"would overwrite {existing[0]}")
    return qbit.download(data, str(candidate.folder), [ZEN_TAG])


def send_plan(
    plan: Plan,
    qbit: Qbit,
    fetch: Callable[[PlanCandidate], bytes],
    reseed: Callable[[PlanCandidate], None] | None = None,
    on_progress: Callable[[int, int, str], None] = lambda i, n, title: None,
) -> SendReport:
    """Send every Plan item; one failing never stops the others."""
    report = SendReport()
    total = len(plan.items)
    for i, item in enumerate(plan.items, 1):
        c = item.candidate
        on_progress(i, total, c.title)
        try:
            if c.reseed:
                if reseed is None:
                    raise Refused("Reseeds are not handled here")
                reseed(c)
                report.reseeded.append(c.title)
            else:
                send_one(qbit, c, fetch(c))
                report.added.append(c.title)
        except Refused as e:
            report.refused.append((c.title, str(e)))
        except Exception as e:  # noqa: BLE001 - reported to the user
            report.failed.append((c.title, str(e) or type(e).__name__))
    return report
