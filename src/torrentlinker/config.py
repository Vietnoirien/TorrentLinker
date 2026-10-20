"""Persisted settings. Secrets never go here — see secrets.py."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from torrentlinker.domain import ContentKind, LibraryFolder, PathMapping


@dataclass
class QbitSettings:
    host: str = "http://localhost:8080"
    username: str = "admin"


@dataclass
class IndexerSettings:
    url: str = "https://c411.org/api/torznab"


@dataclass
class Settings:
    qbit: QbitSettings = field(default_factory=QbitSettings)
    indexer: IndexerSettings = field(default_factory=IndexerSettings)
    library_folders: list[LibraryFolder] = field(default_factory=list)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "qbit": asdict(self.qbit),
            "indexer": asdict(self.indexer),
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
