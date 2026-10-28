"""Explicit, bounded discovery across series/season/episode scopes, including seeded items."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from guessit import guessit

from torrentlinker.domain import ContentKind, LocalItem
from torrentlinker.indexer import Candidate, Indexer, SearchMode
from torrentlinker.matching import MatchRules
from torrentlinker.queries import build_queries, find_ids
from torrentlinker.review import (
    CheckedCandidate,
    candidate_key,
    check_candidate,
    remember_candidates,
)
from torrentlinker.store import Store

MAX_QUERIES = 30
MAX_CANDIDATES = 100


def discover(
    indexer: Indexer,
    store: Store,
    item: LocalItem,
    kind: ContentKind,
    categories: tuple[int, ...],
    rules: MatchRules,
    stop: threading.Event,
    progress: Callable[[dict], None],
) -> list[CheckedCandidate]:
    caps = indexer.supported_modes()
    query_item = replace(item, path=item.save_path / item.search_name) if item.search_name else item
    bases = build_queries(query_item, kind, categories, find_ids(query_item), caps)
    queries = list(bases)
    if kind is ContentKind.SERIES:
        scopes: set[tuple[int, int | None]] = set()
        for name in item.files:
            info = guessit(Path(name).name)
            season, episode = info.get("season"), info.get("episode")
            if isinstance(season, int):
                scopes.add((season, None))
                if isinstance(episode, int):
                    scopes.add((season, episode))
        for base in bases:
            if base.mode is not SearchMode.TV:
                continue
            queries.append(replace(base, season=None, ep=None))
            allowed = caps.get(SearchMode.TV, set()) if caps is not None else {"season", "ep"}
            for season, episode in sorted(scopes, key=lambda s: (s[0], s[1] or 0)):
                if "season" in allowed and (episode is None or "ep" in allowed):
                    queries.append(replace(base, season=season, ep=episode))
    queries = list(dict.fromkeys(queries))
    found: dict[str, Candidate] = {}
    rejected = store.rejections(item.path)
    requests = 0
    limited = False
    for query in queries:
        offset = 0
        while True:
            if stop.is_set():
                raise ValueError("Compatible search cancelled.")
            if requests >= MAX_QUERIES or len(found) >= MAX_CANDIDATES:
                limited = True
                break
            page = indexer.search(replace(query, limit=100, offset=offset))
            requests += 1
            for candidate in page:
                key = candidate_key(candidate)
                if key not in rejected and len(found) < MAX_CANDIDATES:
                    scope = (
                        "episode"
                        if query.ep is not None
                        else "season"
                        if query.season is not None
                        else "series"
                        if kind is ContentKind.SERIES
                        else "item"
                    )
                    found.setdefault(
                        key,
                        replace(
                            candidate,
                            metadata={
                                **candidate.metadata,
                                "discovery": "compatible",
                                "scope": scope,
                            },
                        ),
                    )
            progress({"queries": requests, "candidates": len(found), "limited": limited})
            if len(page) < 100:
                break
            offset += 100
        if limited:
            break
    candidates = [
        replace(c, metadata={**c.metadata, "limited": str(limited).lower()}) for c in found.values()
    ]
    remember_candidates(store, indexer, item.path, candidates)
    checked = []
    for candidate in candidates:
        if stop.is_set():
            raise ValueError("Compatible search cancelled.")
        # A season may be much smaller than a pack. The target file tree decides.
        checked.append(check_candidate(indexer, item, candidate, rules))
        progress({"done": len(checked), "total": len(candidates), "limited": limited})
    return checked


def combine_items(items: list[LocalItem], mappings=()) -> LocalItem:
    """One relative manifest under a common, consistently mapped save path. No disk writes."""
    import hashlib
    import os

    from torrentlinker.paths import PathMapper
    from torrentlinker.provenance import identity

    if not 2 <= len(items) <= 100:
        raise ValueError("Select between 2 and 100 Local Items of the same series.")
    root = Path(os.path.commonpath([str(item.save_path) for item in items]))
    if root == Path(root.anchor):
        raise ValueError("Selected items need a common Library location below the filesystem root.")
    mapper = PathMapper(mappings)
    client_root = mapper.to_qbit(str(root)).replace("\\", "/").rstrip("/")
    files = {}
    for item in items:
        for relative, size in item.files.items():
            path = item.save_path / relative
            identity(path)
            name = path.relative_to(root).as_posix()
            client_path = mapper.to_qbit(str(path)).replace("\\", "/")
            if client_path != client_root + "/" + name:
                raise ValueError(
                    "Selected folders need one consistent Path Mapping from their common parent."
                )
            files[name] = size
    identifier = hashlib.sha256("\n".join(sorted(str(i.path) for i in items)).encode()).hexdigest()[
        :16
    ]
    titles = set()
    for name in files:
        info = guessit(Path(name).name)
        if isinstance(info.get("season"), int) and info.get("title"):
            titles.add(str(info["title"]))
    if len(titles) > 1:
        raise ValueError("Select Local Items from the same series.")
    title = next(iter(titles), str(guessit(items[0].path.name).get("title") or items[0].path.name))
    ids = [find_ids(item) for item in items]
    for field in ("imdb", "tmdb"):
        values = {getattr(value, field) for value in ids if getattr(value, field)}
        if len(values) > 1:
            raise ValueError("Selected items have conflicting series identifiers.")
        if values:
            title += " {" + field + "-" + next(iter(values)) + "}"
    return LocalItem(root / ("Library selection " + identifier), files, search_name=title)
