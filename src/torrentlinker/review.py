"""Turn an Orphan's Candidates into verified Matches."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from torrentlinker.domain import ContentKind, LocalItem
from torrentlinker.indexer import Candidate, Indexer, SearchMode
from torrentlinker.matching import FileComparison, Match, MatchRules, compare, is_plausible, match
from torrentlinker.queries import ExternalIds, build_queries, find_ids, parse_name
from torrentlinker.tmdb import Tmdb
from torrentlinker.torrent_meta import TorrentMeta, read_torrent


@dataclass(frozen=True)
class CheckedCandidate:
    candidate: Candidate
    meta: TorrentMeta | None = None
    comparison: FileComparison | None = None
    match: Match | None = None

    @property
    def compared(self) -> bool:
        return self.meta is not None


def candidate_key(candidate: Candidate) -> str:
    """Stable identity of a Candidate, used for Rejections. Never contains the API key."""
    return candidate.infohash or candidate.details_url or candidate.download_url.split("?")[0]


def search_candidates(
    indexer: Indexer,
    item: LocalItem,
    kind: ContentKind,
    categories: tuple[int, ...],
    caps_modes: dict[SearchMode, set[str]] | None,
    tmdb: Tmdb | None = None,
    override: str | None = None,
) -> list[Candidate]:
    """Run the item's queries in order (ID first, then name) until one finds Candidates."""
    ids = find_ids(item)
    if tmdb and not (ids.imdb or ids.tmdb) and kind.has_external_ids:
        info = parse_name(item)
        try:
            found = tmdb.lookup(str(info.get("title", "")), info.get("year"), kind)
        except Exception:  # noqa: BLE001 - the lookup is a best-effort hint
            found = None
        ids = ExternalIds(tmdb=found)
    for query in build_queries(item, kind, categories, ids, caps_modes, override):
        if candidates := indexer.search(query):
            return candidates
    return []


def check_candidates(
    indexer: Indexer,
    item: LocalItem,
    candidates: Iterable[Candidate],
    rules: MatchRules,
    rejections: Mapping[str, str] = {},
) -> list[CheckedCandidate]:
    """Fetch the .torrent of every size-plausible, non-rejected Candidate and compare files."""
    result = []
    for c in candidates:
        if candidate_key(c) in rejections:
            continue
        if not is_plausible(c.size, item, rules.size_tolerance):
            result.append(CheckedCandidate(c))
            continue
        result.append(check_candidate(indexer, item, c, rules))
    return result


def check_candidate(
    indexer: Indexer, item: LocalItem, candidate: Candidate, rules: MatchRules
) -> CheckedCandidate:
    meta = read_torrent(indexer.fetch_torrent(candidate))
    return CheckedCandidate(
        candidate,
        meta,
        compare(item, meta.files, rules.ignore),
        match(item, meta.files, rules),
    )
