"""Reseed: add a Match to qBittorrent against the existing data, then verify it.

The user's files are never written: the torrent is added stopped, checked, and only
started once Verification shows every piece is already there. A Match with absent
files is left stopped after Verification, because starting it would fetch the pieces
it shares with local files. A failed Verification removes the torrent (never its data)
and records a Rejection. See ADR-0002.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from torrentlinker.domain import LocalItem, Torrent
from torrentlinker.matching import Match
from torrentlinker.qbit import Qbit
from torrentlinker.store import Store, Verification
from torrentlinker.torrent_meta import TorrentMeta, pieces_inside

log = logging.getLogger(__name__)

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
    problem: str | None = None  # something other than the data being wrong


def start_reseed(
    qbit: Qbit,
    store: Store,
    item: LocalItem,
    meta: TorrentMeta,
    match: Match,
    candidate_key: str,
    sleep: Callable[[float], None] = time.sleep,
) -> str:
    with _LOCK:
        if qbit.torrent(meta.infohash) is not None:
            raise AlreadyInClient(meta.name)
        h = qbit.add(meta.data, str(item.save_path), [TAG, VERIFYING])
        absent = set(match.unwanted)
        required = pieces_inside(meta, absent) if absent else None
        local_files = sorted(match.pairs.values())
        store.start_verification(h, item.path, candidate_key, required, local_files)
        # qBittorrent re-applies its own list of file paths when a new torrent settles and
        # when a check starts. A rename it has not taken in yet is then undone on disk,
        # which moves the user's file back to the torrent's original path. So: rename only
        # once the torrent has settled, and check only once qBittorrent lists the new paths.
        _wait_for(lambda: _settled(qbit.torrent(h)), sleep, h, qbit, "the torrent to settle")
        for old, new in rename_plan(match, set(meta.files)):
            qbit.rename_file(h, old, new)
        expected = {match.pairs.get(path, path) for path in meta.files}
        _wait_for(
            lambda: _files(qbit.torrent(h)) == expected,
            sleep,
            h,
            qbit,
            "qBittorrent to take in the renamed files",
        )
        if missing := _missing(item.save_path, local_files):
            qbit.remove(h)  # never deletes files
            store.end_verification(h)
            raise ReseedAborted(f"Local files are no longer in place: {', '.join(missing)}")
        if absent:
            indexes = [i for i, path in enumerate(meta.files) if path in absent]
            qbit.set_file_priority(h, indexes, 0)
        qbit.recheck(h)
        store.mark_rechecked(h)
        return h


SETTLED_STATES = ("stopped", "paused", "missingFiles", "error")
SET_UP_TIMEOUT = 30.0
POLL_INTERVAL = 0.2


class ReseedAborted(Exception):
    """qBittorrent did not reach a safe state; the torrent was removed, data untouched."""


def _missing(save_path: Path, local_files: list[str]) -> list[str]:
    return [f for f in local_files if not (save_path / f).exists()]


def _settled(t: Torrent | None) -> bool:
    return t is not None and t.state.startswith(SETTLED_STATES)


def _files(t: Torrent | None) -> set[str]:
    return set(t.files) if t is not None else set()


def _wait_for(
    condition: Callable[[], bool],
    sleep: Callable[[float], None],
    hash: str,
    qbit: Qbit,
    what: str,
) -> None:
    for _ in range(int(SET_UP_TIMEOUT / POLL_INTERVAL)):
        if condition():
            return
        sleep(POLL_INTERVAL)
    qbit.remove(hash)  # never deletes files
    raise ReseedAborted(f"Timed out waiting for {what}")


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
            if missing := _missing(t.save_path, record.local_files):
                # Never seed from files that are not where the user keeps them.
                qbit.remove(t.hash)
                store.end_verification(t.hash)
                problem = f"Local files are no longer in place: {', '.join(missing)}"
                log.error("%s (%s)", problem, record.item_path)
                outcomes.append(Outcome(record.item_path, t.hash, False, 0.0, problem=problem))
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
