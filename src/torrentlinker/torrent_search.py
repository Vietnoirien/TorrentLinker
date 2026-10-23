"""Native c411 search metadata and pagination, separate from Torznab searches."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from torrentlinker.catalogue_sync import ROOTS, SUBCATS, download_url
from torrentlinker.downloads import IndexerCategory
from torrentlinker.indexer import Candidate, Indexer, publication_time

SERIES_SLUGS = {"serie-tv", "animation-serie", "emission-tv", "serie-documentaire"}


@dataclass(frozen=True)
class SearchTree:
    # Roots use positive native IDs; children negative IDs to avoid ID collisions.
    categories: dict[int, IndexerCategory]
    slugs: dict[int, str]

    def root(self, selected: int | None) -> int | None:
        if selected is None or selected not in self.categories:
            return None
        return self.categories[selected].parent if selected < 0 else selected

    def series(self, selected: int | None) -> bool:
        return selected == 1 or self.slugs.get(selected or 0) in SERIES_SLUGS


def parse_tree(payload: dict[str, Any]) -> SearchTree:
    categories, slugs = {}, {}
    for root in payload["data"]:
        rid = int(root["id"])
        categories[rid] = IndexerCategory(str(root["name"]))
        slugs[rid] = str(root.get("slug", ""))
        for child in root.get("subcategories", []):
            cid = -int(child["id"])
            categories[cid] = IndexerCategory(str(child["name"]), rid)
            slugs[cid] = str(child.get("slug", ""))
    return SearchTree(categories, slugs)


@dataclass(frozen=True)
class SearchFacet:
    slug: str
    label: str
    choices: tuple[tuple[str, str], ...]  # label, option-value ID


def parse_facets(payload: dict[str, Any]) -> list[SearchFacet]:
    return [
        SearchFacet(
            str(group["slug"]),
            str(group["name"]),
            tuple((str(v["value"]), str(v["id"])) for v in group["values"]),
        )
        for group in payload["data"]
        if group.get("values")
    ]


@dataclass(frozen=True)
class SearchPage:
    rows: list[Candidate]
    page: int
    total: int
    per_page: int
    total_pages: int
    labels: dict[str, str]
    palliative: frozenset[str]

    @property
    def has_more(self) -> bool:
        return bool(self.rows) and self.page < self.total_pages

    @property
    def limited(self) -> bool:
        return self.total > self.per_page * self.total_pages


def native_search(indexer: Indexer, params: dict[str, str], page: int = 1) -> SearchPage:
    payload = indexer.catalogue_json(
        {**params, "page": str(page), "perPage": "100", "viewMode": "flat"}
    )
    rows, labels, palliative = [], {}, set()
    for item in payload["data"]:
        h = str(item["infoHash"]).lower()
        if len(h) != 40 or any(ch not in "0123456789abcdef" for ch in h):
            raise ValueError("Invalid torrent hash in search response")
        root, child = item.get("category") or {}, item.get("subcategory") or {}
        native_root, native_child = int(root.get("id") or 0), int(child.get("id") or 0)
        category = SUBCATS.get(native_root, {}).get(native_child) or ROOTS.get(native_root)
        rows.append(
            Candidate(
                str(item["name"]),
                int(item["size"]),
                indexer.unredact(download_url(h)),
                int(item.get("seeders") or 0),
                h,
                f"https://c411.org/torrents/{h}",
                (category,) if category is not None else (),
                published_at=publication_time(item.get("createdAt")),
            )
        )
        labels[h] = " / ".join(str(obj["name"]) for obj in (root, child) if obj.get("name"))
        if item.get("palliativeSince"):
            palliative.add(h)
    meta = payload["meta"]
    return SearchPage(
        rows,
        int(meta["page"]),
        int(meta["total"]),
        int(meta["perPage"]),
        int(meta["totalPages"]),
        labels,
        frozenset(palliative),
    )
