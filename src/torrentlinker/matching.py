"""Matching: compare a Candidate's file tree with an Orphan's files, by size."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from torrentlinker.domain import LocalItem


@dataclass(frozen=True)
class Match:
    """How a torrent's files map onto a Local Item's files.

    `pairs` maps each torrent file path to the local file path holding its data.
    `missing` lists torrent files with no local counterpart.
    """

    pairs: dict[str, str]
    missing: tuple[str, ...] = field(default=())

    @property
    def is_full(self) -> bool:
        return not self.missing

    @property
    def renames(self) -> dict[str, str]:
        return {t: local for t, local in self.pairs.items() if t != local}


def match(item: LocalItem, torrent_files: dict[str, int]) -> Match | None:
    result = compare(item, torrent_files)
    return result if result.is_full else None


def compare(item: LocalItem, torrent_files: dict[str, int]) -> Match:
    """Pair torrent files with local files of identical size; names only break ties."""
    by_size: dict[int, list[str]] = defaultdict(list)
    for path, size in item.files.items():
        by_size[size].append(path)

    pairs: dict[str, str] = {}
    missing: list[str] = []
    for t_path, size in torrent_files.items():
        options = by_size.get(size)
        if not options:
            missing.append(t_path)
            continue
        local = max(options, key=lambda candidate: _name_similarity(t_path, candidate))
        options.remove(local)
        pairs[t_path] = local

    return Match(pairs, tuple(missing))


def _name_similarity(a: str, b: str) -> float:
    name_a, name_b = a.rsplit("/", 1)[-1].casefold(), b.rsplit("/", 1)[-1].casefold()
    return SequenceMatcher(None, name_a, name_b).ratio()


DEFAULT_SIZE_TOLERANCE = 0.02


def is_plausible(candidate_size: int, item: LocalItem, tolerance: float) -> bool:
    """Whether a Candidate's total size is close enough to be worth fetching its .torrent."""
    return abs(candidate_size - item.size) <= tolerance * item.size
