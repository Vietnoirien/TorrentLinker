"""Reseed: add a Match to qBittorrent against the existing data, then verify it.

The user's files are never written: the torrent is added stopped, checked, and only
started once Verification reaches 100%. A failed Verification removes the torrent
(never its data) and records a Rejection. See ADR-0002.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from torrentlinker.domain import LocalItem
from torrentlinker.matching import Match
from torrentlinker.qbit import Qbit
from torrentlinker.store import Store
from torrentlinker.torrent_meta import TorrentMeta, expected_progress

TAG = "torrentlinker"
VERIFYING = "torrentlinker:verifying"
CHECKING_STATES = {"checkingUP", "checkingDL", "checkingResumeData", "queuedForChecking", "moving"}
# A stopped torrent below 100% right after a recheck request may not have started checking yet.
RECHECK_GRACE = 10.0


class AlreadyInClient(Exception):
    pass


@dataclass(frozen=True)
class Outcome:
    hash: str
    verified: bool
    progress: float


def start_reseed(qbit: Qbit, store: Store, item: LocalItem, meta: TorrentMeta, match: Match) -> str:
    if qbit.torrent(meta.infohash) is not None:
        raise AlreadyInClient(meta.name)
    h = qbit.add(meta.data, str(item.save_path), [TAG, VERIFYING])
    unwanted = set(match.unwanted)
    store.start_verification(h, item.path, meta.infohash, expected_progress(meta, unwanted))
    for old, new in rename_plan(match, set(meta.files)):
        qbit.rename_file(h, old, new)
    if unwanted:
        indexes = [i for i, path in enumerate(meta.files) if path in unwanted]
        qbit.set_file_priority(h, indexes, 0)
    qbit.recheck(h)
    store.mark_rechecked(h)
    return h


def rename_plan(match: Match, torrent_paths: set[str]) -> list[tuple[str, str]]:
    """Renames that make the torrent's paths equal the local ones, safe against swaps."""
    renames = match.renames
    if not set(renames.values()) & torrent_paths:
        return list(renames.items())
    staged = {old: f"{old}.torrentlinker-tmp" for old in renames}
    return list(staged.items()) + [(staged[old], new) for old, new in renames.items()]


def check_verifications(
    qbit: Qbit, store: Store, now: Callable[[], float] = time.time
) -> dict[Path, Outcome]:
    """Settle every finished Verification; return outcomes by Local Item path."""
    outcomes: dict[Path, Outcome] = {}
    for t in qbit.torrents(tag=VERIFYING):
        record = store.verification(t.hash)
        if record is None or record.rechecked_at is None:
            # Reseed interrupted before its check was requested: undo it, the user can retry.
            qbit.remove(t.hash)
            store.end_verification(t.hash)
            continue
        item_path, candidate_key = record.item_path, record.candidate_key
        if t.state in CHECKING_STATES:
            continue
        # qBittorrent reports progress with limited precision.
        if t.progress >= record.required_progress - 1e-4:
            qbit.start(t.hash)
            qbit.remove_tags(t.hash, [VERIFYING])
            store.end_verification(t.hash)
            outcomes[item_path] = Outcome(t.hash, verified=True, progress=t.progress)
        elif now() - record.rechecked_at >= RECHECK_GRACE:
            qbit.remove(t.hash)
            store.end_verification(t.hash)
            store.reject(item_path, candidate_key, f"Verification failed at {t.progress:.1%}")
            outcomes[item_path] = Outcome(t.hash, verified=False, progress=t.progress)
    return outcomes


def pending_verifications(qbit: Qbit, store: Store) -> list[Path]:
    """Local Items whose Reseed is still being verified."""
    records = (store.verification(t.hash) for t in qbit.torrents(tag=VERIFYING))
    return [r.item_path for r in records if r is not None]
