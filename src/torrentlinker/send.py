"""Send a Plan to qBittorrent: download its torrents into their Download Folders.

Each .torrent comes straight from the Indexer with the user's key. A torrent is
refused when any of its files already exists at the target: the app never writes to a
file it did not create (ADR-0004).

When the Indexer limits downloads (429), sending waits and tries the same torrent again,
longer each time, instead of failing every torrent left in the Plan.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from torrentlinker.indexer import KeyRefused, RateLimited
from torrentlinker.plan import Plan, PlanCandidate
from torrentlinker.qbit import AlreadyInClient, Qbit
from torrentlinker.torrent_meta import TorrentMeta, read_torrent

ZEN_TAG = "torrentlinker:zen"
LIMIT_WAITS = (60.0, 120.0, 300.0, 600.0, 900.0)  # seconds, after each 429 in a row


@dataclass
class SendReport:
    added: list[str] = field(default_factory=list)  # titles
    reseeded: list[str] = field(default_factory=list)
    refused: list[tuple[str, str]] = field(default_factory=list)  # title, reason
    failed: list[tuple[str, str]] = field(default_factory=list)  # title, error
    stopped: bool = False  # the user stopped before the end of the Plan

    @property
    def handled(self) -> int:
        return len(self.added) + len(self.reseeded) + len(self.refused) + len(self.failed)


@dataclass(frozen=True)
class SendProgress:
    done: int  # torrents handled so far
    total: int
    title: str  # the torrent being sent
    added: int
    refused: int
    failed: int
    retry_at: float | None = None  # time.time() of the next try while the Indexer limits
    zen_added: float = 0.0  # ≈ Zen/day of the torrents added or Reseeded so far


class _Stopped(Exception):
    pass


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


def send_one(
    qbit: Qbit, candidate: PlanCandidate, data: bytes, *, tags: list[str] | None = None
) -> str:
    """Add one Plan torrent, started, into its Download Folder; return its hash."""
    if candidate.folder is None:
        raise Refused("no Download Folder")
    meta = read_torrent(data)
    if qbit.torrent(meta.infohash) is not None:
        raise Refused("already in qBittorrent")
    if existing := existing_targets(candidate.folder, meta):
        raise Refused(f"would overwrite {existing[0]}")
    try:
        return qbit.download(data, str(candidate.folder), tags if tags is not None else [ZEN_TAG])
    except AlreadyInClient as e:  # added meanwhile, e.g. by a Reseed
        raise Refused(str(e)) from e


def send_plan(
    plan: Plan,
    qbit: Qbit,
    fetch: Callable[[PlanCandidate], bytes],
    reseed: Callable[[PlanCandidate], None] | None = None,
    on_progress: Callable[[SendProgress], None] = lambda p: None,
    on_outcome: Callable[[PlanCandidate, str, str], None] = lambda c, outcome, reason: None,
    stop: threading.Event | None = None,
    wait: Callable[[float], bool] | None = None,
    client_for: Callable[[str], Qbit] | None = None,
    now: Callable[[], float] = time.time,
) -> SendReport:
    """Send every Plan item; one failing never stops the others.

    `on_outcome(candidate, outcome, reason)` follows each torrent: added, reseeded,
    refused or failed. `stop` ends sending before the next torrent, or during a wait.
    `wait(seconds)` returns True when stopped meanwhile; it defaults to waiting on `stop`.
    """
    report = SendReport()
    stop = stop or threading.Event()
    wait = wait or stop.wait
    total = len(plan.items)
    zen_sent = 0.0

    def progress(title: str, retry_at: float | None = None) -> None:
        on_progress(
            SendProgress(
                report.handled,
                total,
                title,
                len(report.added) + len(report.reseeded),
                len(report.refused),
                len(report.failed),
                retry_at,
                zen_sent,
            )
        )

    def fetch_patiently(c: PlanCandidate) -> bytes:
        limited = 0
        while True:
            try:
                return fetch(c)
            except RateLimited as e:
                delay = max(e.retry_after, LIMIT_WAITS[min(limited, len(LIMIT_WAITS) - 1)])
                limited += 1
                progress(c.title, now() + delay)
                if wait(delay):
                    raise _Stopped from e
                progress(c.title)

    for item in plan.items:
        c = item.candidate
        if stop.is_set():
            report.stopped = True
            break
        progress(c.title)
        try:
            if c.reseed:
                if reseed is None:
                    raise Refused("Reseeds are not handled here")
                reseed(c)
                report.reseeded.append(c.title)
                zen_sent += item.zen
                on_outcome(c, "reseeded", "")
            else:
                target = client_for(c.client_id) if client_for and c.client_id else qbit
                send_one(target, c, fetch_patiently(c))
                report.added.append(c.title)
                zen_sent += item.zen
                on_outcome(c, "added", "")
        except _Stopped:
            report.stopped = True
            break
        except Refused as e:
            report.refused.append((c.title, str(e)))
            on_outcome(c, "refused", str(e))
        except KeyRefused as e:  # every torrent left would fail the same way
            report.failed.append((c.title, str(e)))
            report.stopped = True
            break
        except Exception as e:  # noqa: BLE001 - reported to the user
            report.failed.append((c.title, str(e) or type(e).__name__))
            on_outcome(c, "failed", str(e) or type(e).__name__)
    progress("")
    return report
