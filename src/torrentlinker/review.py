"""Turn an Orphan's Candidates into verified Matches."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from torrentlinker.domain import LocalItem
from torrentlinker.indexer import Candidate, Indexer
from torrentlinker.matching import IgnoreList, Match, compare, is_plausible, match
from torrentlinker.torrent_meta import TorrentMeta, read_torrent


@dataclass(frozen=True)
class Verified:
    candidate: Candidate
    meta: TorrentMeta | None = None
    comparison: Match | None = None
    match: Match | None = None

    @property
    def checked(self) -> bool:
        return self.meta is not None


@dataclass(frozen=True)
class MatchRules:
    size_tolerance: float
    min_partial_coverage: float
    ignore: IgnoreList


def candidate_key(candidate: Candidate) -> str:
    """Stable identity of a Candidate, used for Rejections. Never contains the API key."""
    return candidate.infohash or candidate.details_url or candidate.download_url.split("?")[0]


def verify(
    indexer: Indexer,
    item: LocalItem,
    candidates: Iterable[Candidate],
    rules: MatchRules,
    rejections: Mapping[str, str] = {},
) -> list[Verified]:
    """Fetch the .torrent of every size-plausible, non-rejected Candidate and compare files."""
    result = []
    for c in candidates:
        if candidate_key(c) in rejections:
            continue
        if not is_plausible(c.size, item, rules.size_tolerance):
            result.append(Verified(c))
            continue
        result.append(verify_one(indexer, item, c, rules))
    return result


def verify_one(
    indexer: Indexer, item: LocalItem, candidate: Candidate, rules: MatchRules
) -> Verified:
    meta = read_torrent(indexer.fetch_torrent(candidate))
    return Verified(
        candidate,
        meta,
        compare(item, meta.files, rules.ignore),
        match(item, meta.files, rules.ignore, rules.min_partial_coverage),
    )
