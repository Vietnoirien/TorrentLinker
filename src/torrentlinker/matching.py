"""Matching: compare a Candidate's file tree with an Orphan's files, by size."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from fnmatch import fnmatch

from torrentlinker.domain import LocalItem

DEFAULT_SIZE_TOLERANCE = 0.02
DEFAULT_MIN_PARTIAL_COVERAGE = 0.5
DEFAULT_IGNORE_PATTERNS = (
    "*.nfo",
    "*.url",
    "*.sfv",
    "Thumbs.db",
    ".DS_Store",
    "desktop.ini",
    "*.part",
    "*.parts",
    "*.!qB",
    "sample",
    "*-sample.*",
    "*.sample.*",
    ".pad",
)


@dataclass(frozen=True)
class IgnoreList:
    """Patterns for Ignored Files, matched case-insensitively against every path segment."""

    patterns: tuple[str, ...] = ()

    @classmethod
    def default(cls) -> IgnoreList:
        return cls(DEFAULT_IGNORE_PATTERNS)

    def matches(self, path: str) -> bool:
        segments = [s.casefold() for s in path.split("/")]
        return any(fnmatch(s, p.casefold()) for p in self.patterns for s in segments)


@dataclass(frozen=True)
class Match:
    """How a torrent's files map onto a Local Item's files.

    `pairs` maps each torrent file path to the local file path holding its data.
    `missing` lists torrent files with no local counterpart; `skipped` lists Ignored
    Files of the torrent with no local counterpart. Neither will ever be downloaded.
    """

    pairs: dict[str, str]
    missing: tuple[str, ...] = field(default=())
    skipped: tuple[str, ...] = field(default=())
    coverage: float = 1.0

    @property
    def is_full(self) -> bool:
        return not self.missing

    @property
    def unwanted(self) -> tuple[str, ...]:
        return self.missing + self.skipped

    @property
    def renames(self) -> dict[str, str]:
        return {t: local for t, local in self.pairs.items() if t != local}


def match(
    item: LocalItem,
    torrent_files: dict[str, int],
    ignore: IgnoreList = IgnoreList(),
    min_coverage: float = DEFAULT_MIN_PARTIAL_COVERAGE,
) -> Match | None:
    """A Full or Partial Match, or None when too little of the torrent is present locally."""
    result = compare(item, torrent_files, ignore)
    if result.is_full or (result.pairs and result.coverage >= min_coverage):
        return result
    return None


def compare(
    item: LocalItem, torrent_files: dict[str, int], ignore: IgnoreList = IgnoreList()
) -> Match:
    """Pair torrent files with local files of identical size; names only break ties."""
    by_size: dict[int, list[str]] = defaultdict(list)
    for path, size in item.files.items():
        by_size[size].append(path)

    pairs: dict[str, str] = {}
    missing: list[str] = []
    skipped: list[str] = []
    # Pair real content first so an Ignored File never steals a same-size local file.
    ordered = sorted(torrent_files.items(), key=lambda kv: ignore.matches(kv[0]))
    for t_path, size in ordered:
        options = by_size.get(size)
        if not options:
            (skipped if ignore.matches(t_path) else missing).append(t_path)
            continue
        local = max(options, key=lambda candidate: _name_similarity(t_path, candidate))
        options.remove(local)
        pairs[t_path] = local

    wanted = sum(s for p, s in torrent_files.items() if not ignore.matches(p))
    present = sum(torrent_files[p] for p in pairs if not ignore.matches(p))
    coverage = present / wanted if wanted else 1.0
    return Match(pairs, tuple(missing), tuple(skipped), coverage)


def is_plausible(candidate_size: int, item: LocalItem, tolerance: float) -> bool:
    """Whether a Candidate's total size is close enough to be worth fetching its .torrent."""
    return abs(candidate_size - item.size) <= tolerance * item.size


def _name_similarity(a: str, b: str) -> float:
    name_a, name_b = a.rsplit("/", 1)[-1].casefold(), b.rsplit("/", 1)[-1].casefold()
    return SequenceMatcher(None, name_a, name_b).ratio()
