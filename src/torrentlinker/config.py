"""Persisted settings. Secrets never go here — see credentials.py."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from torrentlinker.domain import ContentKind, LibraryFolder, PathMapping
from torrentlinker.matching import (
    DEFAULT_IGNORE_PATTERNS,
    DEFAULT_MIN_PARTIAL_COVERAGE,
    DEFAULT_SIZE_TOLERANCE,
    IgnoreList,
    MatchRules,
)


@dataclass
class QbitSettings:
    host: str = "http://localhost:8080"
    username: str = "admin"


@dataclass
class IndexerSettings:
    url: str = "https://c411.org/api/torznab"


@dataclass
class MatchingSettings:
    size_tolerance: float = DEFAULT_SIZE_TOLERANCE
    min_partial_coverage: float = DEFAULT_MIN_PARTIAL_COVERAGE
    ignore_patterns: list[str] = field(default_factory=lambda: list(DEFAULT_IGNORE_PATTERNS))

    @property
    def ignore(self) -> IgnoreList:
        return IgnoreList(tuple(self.ignore_patterns))

    def rules(self) -> MatchRules:
        return MatchRules(self.size_tolerance, self.min_partial_coverage, self.ignore)


@dataclass
class Settings:
    qbit: QbitSettings = field(default_factory=QbitSettings)
    indexer: IndexerSettings = field(default_factory=IndexerSettings)
    matching: MatchingSettings = field(default_factory=MatchingSettings)
    # Torznab categories searched for each Content Kind; none listed = all categories.
    kind_categories: dict[ContentKind, list[int]] = field(default_factory=dict)
    language: str = "auto"  # auto | en | fr

    def categories(self, kind: ContentKind) -> tuple[int, ...]:
        return tuple(self.kind_categories.get(kind, []))

    library_folders: list[LibraryFolder] = field(default_factory=list)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "qbit": asdict(self.qbit),
            "indexer": asdict(self.indexer),
            "matching": asdict(self.matching),
            "kind_categories": {k.value: v for k, v in self.kind_categories.items()},
            "language": self.language,
            "library_folders": [_folder_to_json(f) for f in self.library_folders],
        }
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> Settings:
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            qbit=QbitSettings(**data.get("qbit", {})),
            indexer=IndexerSettings(**data.get("indexer", {})),
            matching=MatchingSettings(**data.get("matching", {})),
            language=str(data.get("language", "auto")),
            kind_categories={
                ContentKind(k): [int(c) for c in v]
                for k, v in data.get("kind_categories", {}).items()
            },
            library_folders=[_folder_from_json(f) for f in data.get("library_folders", [])],
        )


def _folder_to_json(f: LibraryFolder) -> dict[str, object]:
    return {
        "path": str(f.path),
        "depth": f.depth,
        "kind": f.kind.value,
        "mapping": asdict(f.mapping) if f.mapping else None,
    }


def _folder_from_json(d: dict) -> LibraryFolder:  # type: ignore[type-arg]
    return LibraryFolder(
        path=Path(d["path"]),
        depth=int(d.get("depth", 1)),
        kind=ContentKind(d.get("kind", ContentKind.OTHER.value)),
        mapping=PathMapping(**d["mapping"]) if d.get("mapping") else None,
    )
