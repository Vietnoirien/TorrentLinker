"""Reseed: add a Match to qBittorrent against the existing data, then verify it.

The user's files are never written: the torrent is added stopped, checked, and only
started once Verification shows every piece is already there. A Match with absent
files is left stopped after Verification, because starting it would fetch the pieces
it shares with local files. A failed Verification removes the torrent (never its data)
and records a Rejection. See ADR-0002.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from torrentlinker.domain import LocalItem
from torrentlinker.matching import Match
from torrentlinker.qbit import Qbit
from torrentlinker.store import Store, Verification
from torrentlinker.torrent_meta import TorrentMeta, pieces_inside

TAG = "torrentlinker"
VERIFYING = "torrentlinker:verifying"
PARTIAL = "torrentlinker:partial"
CHECKING_STATES = {"checkingUP", "checkingDL", "checkingResumeData", "queuedForChecking", "moving"}
# A stopped torrent below 100% right after a recheck request may not have started checking yet.
RECHECK_GRACE = 10.0
PIECE_VERIFIED = 2  # qBittorrent pieceStates: 0 missing, 1 downloading, 2 have

# Held for a whole Reseed set-up and for every check, so a poll never sees a half-made Reseed.
_LOCK = threading.Lock()


class AlreadyInClient(Exception):
    pass


@dataclass(frozen=True)
class Outcome:
    item_path: Path
    hash: str
    verified: bool
    progress: float
    started: bool = False


def start_reseed(
    qbit: Qbit, store: Store, item: LocalItem, meta: TorrentMeta, match: Match, candidate_key: str
) -> str:
    with _LOCK:
        if qbit.torrent(meta.infohash) is not None:
            raise AlreadyInClient(meta.name)
        h = qbit.add(meta.data, str(item.save_path), [TAG, VERIFYING])
        absent = set(match.unwanted)
        required = pieces_inside(meta, absent) if absent else None
        store.start_verification(h, item.path, candidate_key, required)
        for old, new in rename_plan(match, set(meta.files)):
            qbit.rename_file(h, old, new)
        if absent:
            indexes = [i for i, path in enumerate(meta.files) if path in absent]
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
) -> list[Outcome]:
    """Settle every finished Verification."""
    with _LOCK:
        outcomes = []
        for t in qbit.torrents(tag=VERIFYING):
            record = store.verification(t.hash)
            if record is None or record.rechecked_at is None:
                # A Reseed interrupted before its check was requested: undo it, the user
                # can retry. (The lock rules out a Reseed still being set up.)
                qbit.remove(t.hash)
                store.end_verification(t.hash)
                continue
            if t.state in CHECKING_STATES:
                continue
            verified, progress = _verdict(qbit, t.hash, t.progress, record)
            if verified:
                outcomes.append(_accept(qbit, store, t.hash, record, progress))
            elif now() - record.rechecked_at >= RECHECK_GRACE:
                qbit.remove(t.hash)
                store.end_verification(t.hash)
                store.reject(
                    record.item_path,
                    record.candidate_key,
                    f"Verification failed at {progress:.1%}",
                )
                outcomes.append(Outcome(record.item_path, t.hash, False, progress))
        return outcomes


def _verdict(qbit: Qbit, hash: str, progress: float, record: Verification) -> tuple[bool, float]:
    if record.required_pieces is None:
        return progress >= 1.0, progress
    states = qbit.piece_states(hash)
    wanted = [i for start, end in record.required_pieces for i in range(start, end)]
    have = sum(1 for i in wanted if i < len(states) and states[i] == PIECE_VERIFIED)
    share = have / len(wanted) if wanted else 0.0
    return bool(wanted) and have == len(wanted), share


def _accept(qbit: Qbit, store: Store, hash: str, record: Verification, progress: float) -> Outcome:
    complete = record.required_pieces is None
    if complete:
        qbit.start(hash)
    else:
        qbit.add_tags(hash, [PARTIAL])
    qbit.remove_tags(hash, [VERIFYING])
    store.end_verification(hash)
    return Outcome(record.item_path, hash, True, progress, started=complete)


def pending_verifications(qbit: Qbit, store: Store) -> list[Path]:
    """Local Items whose Reseed is still being verified."""
    records = (store.verification(t.hash) for t in qbit.torrents(tag=VERIFYING))
    return [r.item_path for r in records if r is not None]
