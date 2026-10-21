"""Turn an Orphan's Candidates into Matches, and remember them between launches."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from torrentlinker.domain import ContentKind, LocalItem
from torrentlinker.indexer import Candidate, Indexer, SearchMode
from torrentlinker.matching import FileComparison, Match, MatchRules, compare, is_plausible, match
from torrentlinker.queries import ExternalIds, build_queries, find_ids, parse_name
from torrentlinker.store import Store
from torrentlinker.tmdb import Tmdb
from torrentlinker.torrent_meta import TorrentMeta, read_torrent
from torrentlinker.zen import ZenProfile, ZenTorrent, torrent_zen


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


def remember_candidates(
    store: Store, indexer: Indexer, item_path: Path, candidates: Iterable[Candidate]
) -> None:
    """Keep the last search's Candidates, so the Library shows them at the next launch."""
    rows = [{**asdict(c), "download_url": indexer.redact(c.download_url)} for c in candidates]
    store.remember_candidates(item_path, json.dumps(rows))


def remembered_candidates(
    store: Store, indexer: Indexer, item_path: Path
) -> list[Candidate] | None:
    """The Candidates of the Local Item's last search, or None if it was never searched."""
    text = store.remembered_candidates(item_path)
    if text is None:
        return None
    candidates = []
    for row in json.loads(text):
        row["download_url"] = indexer.unredact(row["download_url"])
        row["categories"] = tuple(row.get("categories", ()))
        candidates.append(Candidate(**row))
    return candidates


def restore_checked(
    indexer: Indexer,
    item: LocalItem,
    candidates: Iterable[Candidate],
    rules: MatchRules,
    rejections: Mapping[str, str] = {},
) -> list[CheckedCandidate]:
    """Compare remembered Candidates again using only cached .torrent files (no network)."""
    result = []
    for c in candidates:
        if candidate_key(c) in rejections:
            continue
        data = indexer.cached_torrent(c)
        if data is None:
            result.append(CheckedCandidate(c))
            continue
        result.append(_compared(item, c, read_torrent(data), rules))
    return result


def check_candidate(
    indexer: Indexer, item: LocalItem, candidate: Candidate, rules: MatchRules
) -> CheckedCandidate:
    return _compared(item, candidate, read_torrent(indexer.fetch_torrent(candidate)), rules)


def _compared(
    item: LocalItem, candidate: Candidate, meta: TorrentMeta, rules: MatchRules
) -> CheckedCandidate:
    return CheckedCandidate(
        candidate,
        meta,
        compare(item, meta.files, rules.ignore),
        match(item, meta.files, rules),
    )


def match_zen(
    profile: ZenProfile,
    checked: Iterable[CheckedCandidate],
    alongside: Sequence[ZenTorrent] = (),
) -> float | None:
    """Zen Estimate of the best Match once reseeded, or None without a Match.

    The user joins the Candidate's seeders, with a seed age of 0.
    """
    values = [
        torrent_zen(profile, ZenTorrent(v.candidate.size, v.candidate.seeders + 1), alongside)
        for v in checked
        if v.match is not None
    ]
    return max(values) if values else None
