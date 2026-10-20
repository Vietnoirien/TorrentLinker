"""Query building: turn a Local Item into Indexer search parameters."""

from __future__ import annotations

import re

from torrentlinker.domain import LocalItem


def is_single_file(item: LocalItem) -> bool:
    return list(item.files) == [item.path.name]


def name_query(item: LocalItem) -> str:
    name = item.path.stem if is_single_file(item) else item.path.name
    name = re.sub(r"\[[^\]]*\]|\{[^}]*\}|[()]", " ", name)
    name = re.sub(r"[._\-\s]+", " ", name)
    return name.strip()
