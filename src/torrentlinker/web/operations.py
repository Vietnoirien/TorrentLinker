"""Application jobs using the same domain operations as the desktop UI."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import asdict
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from torrentlinker.download_queue import enqueue, entries, run_queue
from torrentlinker.indexer import Candidate, SearchQuery
from torrentlinker.seeding import seeding
from torrentlinker.store import CatalogueRow
from torrentlinker.torrent_details import website_url
from torrentlinker.torrent_management import (
    category_labels,
    manage,
    status,
    torrent_categories,
    tracker_hosts,
)
from torrentlinker.torrent_search import native_search
from torrentlinker.web.library import Library
from torrentlinker.web.setup import Setup
from torrentlinker.web.storage import DownloadClient
from torrentlinker.web.uploads import UploadForm, Uploads
from torrentlinker.zen import ZenTorrent, note, torrent_zen


class JobRequest(BaseModel):
    kind: Literal[
        "manage",
        "refresh",
        "search",
        "enqueue",
        "send-queue",
        "scan",
        "check",
        "reseed",
        "catalogue",
        "plan",
        "details",
        "search-options",
        "upload-preview",
        "upload-draft",
        "upload-seed",
        "profile",
        "verify",
    ]
    action: Literal["pause", "resume", "recheck", "remove", "delete"] = "pause"
    hashes: list[str] = Field(default_factory=list, max_length=1000)
    confirmation: str = ""
    upload: UploadForm = Field(default_factory=UploadForm)
    maximum_bytes: int = Field(default=0, ge=0)
    maximum_torrents: int = Field(default=20, ge=1, le=1000)
    path: str = Field(default="", max_length=4096)
    query: str = Field(default="", max_length=500)
    page: int = Field(default=1, ge=1, le=10000)
    category: int | None = None
    filters: dict[str, str] = Field(default_factory=dict, max_length=30)

    @field_validator("hashes")
    @classmethod
    def hashes_valid(cls, hashes: list[str]) -> list[str]:
        if any(len(h) != 40 or any(c not in "0123456789abcdefABCDEF" for c in h) for h in hashes):
            raise ValueError("Invalid torrent hash.")
        return list(dict.fromkeys(h.lower() for h in hashes))


class Operations:
    def __init__(self, setup: Setup):
        self.setup = setup
        self.library = Library(setup)
        self.uploads = Uploads(setup, self.library)
        self.candidates: dict[str, Candidate] = {}
        self.rows: list[dict[str, Any]] = []
        self.zen: dict[str, Any] = {}

    def validate(self, request: JobRequest) -> None:
        if request.kind in {"scan", "check", "reseed"} and not self.setup.settings.library_folders:
            raise ValueError("Add a mounted Library Folder in Settings first.")
        if request.kind == "reseed" and len(request.hashes) != 1:
            raise ValueError("Select one checked Candidate.")
        if request.kind in {"enqueue", "send-queue", "plan"}:
            folder = self.setup.settings.download_folders.default
            if not folder:
                raise ValueError(
                    "Configure and verify a mounted Download Folder in Settings first."
                    " A seedbox API connection alone cannot check existing files."
                )
            self.setup.path_under_root(folder)
        if request.kind == "manage" and not request.hashes:
            raise ValueError("Select at least one torrent.")

    def queue(self) -> list[dict[str, Any]]:
        return [
            {
                "key": e.key,
                "title": e.candidate.title,
                "hash": e.candidate.infohash,
                "size": e.candidate.size,
                "folder": str(e.folder),
                "status": e.status,
                "reason": "Check the last job and client state." if e.reason else "",
                "zen": torrent_zen(
                    self.setup.settings.zen, ZenTorrent(e.candidate.size, e.candidate.seeders + 1)
                ),
                "note": note(
                    self.setup.settings.zen.zen_class,
                    ZenTorrent(e.candidate.size, e.candidate.seeders + 1),
                ),
            }
            for e in entries(self.setup.store)
        ]

    def run(
        self, request: JobRequest, stop: threading.Event, progress: Callable[[Any], None]
    ) -> Any:
        self.validate(request)
        if request.kind == "upload-preview":
            return self.uploads.prepare(request.path, request.upload, stop)[1]
        if request.kind == "upload-draft":
            return self.uploads.draft(request.path, request.upload, stop, progress)
        if request.kind == "upload-seed":
            if len(request.hashes) != 1:
                raise ValueError("Select one prepared Upload.")
            return self.uploads.seed(request.hashes[0], stop)
        if request.kind == "profile":
            from torrentlinker.profile import ProfileClient

            profile = ProfileClient(
                self.setup.settings.indexer.url, self.setup.secrets.get("indexer-api-key")
            ).fetch()
            self.setup.settings.zen = profile.apply(self.setup.settings.zen)
            self.setup.save()
            return {"balance": profile.balance, "class": profile.class_slug}
        if request.kind == "verify":
            from torrentlinker.reseed import check_verifications

            outcomes = check_verifications(self.library.client(), self.setup.store)
            return [
                {
                    "hash": o.hash,
                    "verified": o.verified,
                    "progress": o.progress,
                    "started": o.started,
                }
                for o in outcomes
            ]
        if request.kind == "catalogue":
            from torrentlinker.web.planning import catalogue as update_catalogue

            return update_catalogue(self.setup, stop, progress)
        if request.kind == "plan":
            from torrentlinker.web.planning import plan

            return plan(
                self.setup, self.library, request.maximum_bytes, request.maximum_torrents, stop
            )
        if request.kind == "details":
            from torrentlinker.torrent_details import parse_details, preview_html

            if len(request.hashes) != 1:
                raise ValueError("Select one torrent.")
            detail = parse_details(self.setup.indexer().torrent_json(request.hashes[0]))
            markup, images = preview_html(detail.description, detail.poster)
            return {
                "description": markup,
                "images": images,
                "nfo": detail.nfo,
                "files": detail.files,
            }
        if request.kind == "search-options":
            from torrentlinker.torrent_search import parse_facets, parse_tree

            indexer = self.setup.indexer()
            if not indexer.is_c411:
                return {
                    "categories": {
                        str(k): asdict(v) for k, v in self.setup.settings.indexer_categories.items()
                    },
                    "facets": [],
                }
            tree = parse_tree(indexer.search_categories())
            root = tree.root(request.category)
            facets = parse_facets(indexer.search_filter_options(root)) if root else []
            return {
                "categories": {str(k): asdict(v) for k, v in tree.categories.items()},
                "facets": [asdict(f) for f in facets],
            }
        if request.kind == "scan":
            return self.library.scan(stop, progress)
        if request.kind == "check":
            return self.library.check(request.path, stop, progress)
        if request.kind == "reseed":
            return self.library.reseed(request.path, request.hashes[0], stop)
        if request.kind == "search":
            indexer = self.setup.indexer()
            if indexer.is_c411:
                allowed = {
                    k: v
                    for k, v in request.filters.items()
                    if k not in {"page", "perPage", "viewMode", "apikey", "api_key"}
                    and len(v) < 500
                }
                params = {
                    "sortBy": "createdAt",
                    "sortOrder": "desc",
                    **allowed,
                    "name": request.query,
                }
                if request.category is not None:
                    if request.category < 0:
                        from torrentlinker.torrent_search import parse_tree

                        parent = parse_tree(indexer.search_categories()).root(request.category)
                        if parent is None:
                            raise ValueError("This subcategory is unavailable. Refresh categories.")
                        params["category"] = str(parent)
                    params["category" if request.category > 0 else "subcat"] = str(
                        abs(request.category)
                    )
                page = native_search(indexer, params, request.page)
                found, total_pages = page.rows, page.total_pages
            else:
                found = indexer.search(
                    SearchQuery(
                        q=request.query,
                        categories=(request.category,) if request.category else (),
                        limit=100,
                        offset=(request.page - 1) * 100,
                    )
                )
                total_pages = request.page + int(len(found) == 100)
            result = []
            catalogue = []
            for c in found:
                if not c.infohash:
                    continue
                self.candidates[c.infohash] = c
                zt = ZenTorrent(c.size, c.seeders + 1)
                result.append(
                    {
                        "hash": c.infohash,
                        "title": c.title,
                        "size": c.size,
                        "seeders": c.seeders,
                        "published_at": c.published_at,
                        "website": indexer.redact(website_url(c, indexer)),
                        "zen": torrent_zen(self.setup.settings.zen, zt),
                        "note": note(self.setup.settings.zen.zen_class, zt),
                        "categories": c.categories,
                    }
                )
                catalogue.append(
                    CatalogueRow(
                        c.infohash,
                        c.title,
                        c.size,
                        c.seeders,
                        c.categories[-1] if c.categories else None,
                        indexer.redact(c.download_url),
                        indexer.redact(c.details_url),
                        time.time(),
                    )
                )
            self.setup.store.save_catalogue(catalogue)
            return {"rows": result, "page": request.page, "pages": total_pages}
        if request.kind == "enqueue":
            indexer = self.setup.indexer()
            count = 0
            for h in request.hashes:
                candidate = self.candidates.get(h)
                if candidate is None:
                    cached = self.setup.store.catalogue([h])
                    if not cached:
                        raise ValueError("Search again before queueing this torrent.")
                    r = cached[0]
                    candidate = Candidate(
                        r.title,
                        r.size,
                        indexer.unredact(r.download_url),
                        r.seeders,
                        r.infohash,
                        r.details_url,
                    )
                count += enqueue(
                    self.setup.store,
                    indexer,
                    candidate,
                    self.setup.path_under_root(self.setup.settings.download_folders.default),
                )
            return {"queued": count}
        if request.kind == "send-queue":
            self.setup.verified_download_folder()
            # Recheck every queued folder, including entries saved before settings changed.
            for entry in entries(self.setup.store):
                if entry.status == "queued":
                    self.setup.path_under_root(str(entry.folder))
                    if str(entry.folder) != self.setup.settings.download_folders.default:
                        raise ValueError(
                            "A queued destination changed. Remove that entry and queue it again."
                        )
            client = DownloadClient(self.setup)
            report = run_queue(
                self.setup.store,
                self.setup.indexer(),
                client,
                self.setup.settings.indexer_categories,
                stop,
                lambda p: progress(asdict(p)),
            )
            return {
                "added": len(report.added),
                "refused": [title for title, _ in report.refused],
                "failed": [title for title, _ in report.failed],
                "stopped": report.stopped,
            }
        if request.kind == "refresh":
            torrents = self.setup.client().torrents(with_files=False)
            settings = self.setup.settings
            cached_rows = {
                r.infohash: r
                for r in self.setup.store.catalogue([t.hash.lower() for t in torrents])
            }
            view = seeding(
                settings.zen,
                torrents,
                settings.indexer.url,
                settings.uploads,
                catalogue=cached_rows,
                categories=settings.indexer_categories,
            )
            estimates = {r.torrent.hash: r for r in view.rows}
            labels = category_labels(settings.indexer_categories)
            rows = []
            for t in torrents:
                estimate = estimates.get(t.hash)
                rows.append(
                    {
                        "hash": t.hash,
                        "name": t.name,
                        "status": status(t),
                        "progress": t.progress,
                        "size": t.total_size,
                        "download": t.download_rate,
                        "upload": t.upload_rate,
                        "ratio": t.ratio,
                        "seeds": t.connected_seeds,
                        "peers": t.connected_peers,
                        "folder": str(t.save_path),
                        "trackers": tracker_hosts(t),
                        "categories": torrent_categories(t, labels),
                        "tags": sorted(t.tags),
                        "zen": estimate.zen if estimate else None,
                        "note": estimate.note if estimate else None,
                    }
                )
            self.rows = rows
            self.zen = {"count": view.count, "daily": sum(r.zen or 0 for r in view.rows)}
            return {"count": len(rows), "zen": self.zen}
        if request.kind == "manage":
            result = []
            for hash in request.hashes:
                if stop.is_set():
                    break
                results = manage(self.setup.client(), [hash], request.action)
                # Raw adapter failures may contain secrets. Expose only safe outcomes.
                result += [
                    {
                        **asdict(r),
                        "detail": "See connection settings." if r.outcome == "failed" else r.detail,
                    }
                    for r in results
                ]
                progress({"done": len(result), "total": len(request.hashes)})
            return result
        raise ValueError("Unknown job.")
