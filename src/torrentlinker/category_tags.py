"""Tracker category paths and additive client tags, independent of download folders."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from torrentlinker.domain import Torrent
from torrentlinker.downloads import IndexerCategory
from torrentlinker.qbit import Qbit

CATEGORY_TAG_PREFIX = "torrentlinker:category:"


def category_path(
    category: int | None, categories: Mapping[int, IndexerCategory]
) -> tuple[int, ...]:
    """Keep known ancestors, without inferring subcategories or following malformed cycles."""
    path: list[int] = []
    while category is not None and category not in path:
        path.append(category)
        info = categories.get(category)
        category = info.parent if info else None
    return tuple(reversed(path))


def category_tag(category: int | None, categories: Mapping[int, IndexerCategory]) -> str | None:
    path = category_path(category, categories)
    if not path or any(cid not in categories or not categories[cid].name.strip() for cid in path):
        return None
    # qBittorrent separates tags with commas, so a name must not introduce another tag.
    names = [" ".join(categories[cid].name.split()).replace(",", " ·") for cid in path]
    return CATEGORY_TAG_PREFIX + " / ".join(names)


@dataclass
class CategoryTagSync:
    supported: bool
    updated: int = 0
    unchanged: int = 0
    unknown: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)


def sync_category_tags(
    client: Qbit,
    torrents: Iterable[tuple[Torrent, int | None]],
    categories: Mapping[int, IndexerCategory],
) -> CategoryTagSync:
    """Tag only the supplied Indexer torrents; replace only tags in our own namespace.

    Batch equal tags for clients that support it. Deluge's one label is reserved for
    Verification, so it must never enter this flow. A tagging failure must not prevent
    the Seeding view from displaying the torrents it has already read.
    """
    report = CategoryTagSync(client.supports_category_tags)
    if not report.supported:
        return report
    pending: dict[str, list[Torrent]] = defaultdict(list)
    for torrent, category in torrents:
        tag = category_tag(category, categories)
        if tag is None:
            report.unknown += 1
        elif {t for t in torrent.tags if t.startswith(CATEGORY_TAG_PREFIX)} == {tag}:
            report.unchanged += 1
        else:
            pending[tag].append(torrent)
    for tag, group in pending.items():
        for offset in range(0, len(group), 200):
            batch = group[offset : offset + 200]
            missing = [t.hash for t in batch if tag not in t.tags]
            try:
                if missing:
                    client.add_tags_many(missing, [tag])
            except Exception as error:  # a later refresh retries; never hide the Seeding view
                report.failed += len(batch)
                report.errors.append(str(error) or type(error).__name__)
                continue
            for torrent in batch:
                stale = sorted(
                    t for t in torrent.tags if t.startswith(CATEGORY_TAG_PREFIX) and t != tag
                )
                try:
                    if stale:
                        client.remove_tags(torrent.hash, stale)
                except Exception as error:
                    report.failed += 1
                    report.errors.append(str(error) or type(error).__name__)
                else:
                    report.updated += 1
    return report
