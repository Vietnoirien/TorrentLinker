"""Application jobs using the same domain operations as the desktop UI."""

from __future__ import annotations

import threading
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from torrentlinker.domain import Torrent
from torrentlinker.download_queue import enqueue, entries, run_queue
from torrentlinker.indexer import Candidate, SearchQuery
from torrentlinker.seeding import observe_swarm, seeding
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
from torrentlinker.torrent_selection import SelectionCriteria, select_rows
from torrentlinker.upload_queue import reset_local
from torrentlinker.web.library import Library
from torrentlinker.web.setup import Setup
from torrentlinker.web.storage import DownloadClient
from torrentlinker.web.uploads import UploadForm, Uploads
from torrentlinker.zen import ZenTorrent, note, torrent_zen


class DownloadFolderRequired(ValueError):
    def __init__(self, client_id: str, category: int | None):
        super().__init__(
            "Configure and verify a mounted Download Folder in Settings first. "
            "A seedbox API connection alone cannot check existing files."
        )
        self.client_id, self.category = client_id, category


class JobRequest(BaseModel):
    client_id: str = Field(default="", max_length=64)
    client_ids: list[str] = Field(default_factory=list, max_length=32)
    client_budgets: dict[str, int] = Field(default_factory=dict, max_length=32)
    kind: Literal[
        "manage",
        "refresh",
        "select-torrents",
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
        "upload-queue",
        "upload-send",
        "upload-remove",
        "upload-reset",
        "upload-seed",
        "profile",
        "verify",
        "configure-download-folder",
    ]
    action: Literal["pause", "resume", "recheck", "remove", "delete"] = "pause"
    hashes: list[str] = Field(default_factory=list, max_length=1000)
    confirmation: str = ""
    upload: UploadForm = Field(default_factory=UploadForm)
    draft_id: str = Field(default="", max_length=64)
    revision: int = Field(default=0, ge=0)
    maximum_bytes: int = Field(default=0, ge=0)
    maximum_torrents: int = Field(default=20, ge=1, le=1000)
    cached_only: bool = False
    selection: SelectionCriteria = Field(default_factory=SelectionCriteria)
    selection_id: str = Field(default="", max_length=64)
    path: str = Field(default="", max_length=4096)
    client_path: str = Field(default="", max_length=4096)
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
        self.observed: list[Torrent] = []
        self.connection_error = ""
        self.zen: dict[str, Any] = {}

    def validate(self, request: JobRequest) -> None:
        if request.kind in {"upload-send", "upload-remove", "upload-reset"} or (
            request.kind in {"upload-queue", "upload-preview"} and request.draft_id
        ):
            record = self.setup.store.local_draft(request.draft_id)
            if record["revision"] != request.revision:
                raise ValueError("Local Draft changed. Reload and review the current revision.")
        if request.kind in {"scan", "check", "reseed"} and not self.setup.settings.library_folders:
            raise ValueError("Add a mounted Library Folder in Settings first.")
        if request.kind == "reseed" and len(request.hashes) != 1:
            raise ValueError("Select one checked Candidate.")
        if request.kind in {"enqueue", "send-queue", "plan"}:
            targets = (
                [self.setup.for_client(identifier) for identifier in request.client_ids]
                if request.kind == "plan" and request.client_ids
                else [self.setup]
            )
            for target in targets:
                folder = target.download_folder(self.request_category(request))
                if not folder and request.kind == "plan" and request.category is None:
                    folder = next(
                        (
                            Path(value)
                            for value in target.settings.download_folders.by_category.values()
                        ),
                        None,
                    )
                if request.kind == "send-queue":
                    folder = next(
                        (
                            e.folder
                            for e in entries(target.store)
                            if e.status == "queued"
                            and (not request.hashes or e.candidate.infohash in request.hashes)
                        ),
                        folder,
                    )
                if not folder:
                    raise DownloadFolderRequired(
                        target.settings.active_client_id, self.request_category(request)
                    )
                target.path_under_root(str(folder))
        if request.kind == "manage" and not request.hashes:
            raise ValueError("Select at least one torrent.")

    def request_category(self, request: JobRequest) -> int | None:
        if request.category is not None:
            return request.category
        if request.kind == "enqueue" and request.hashes:
            categories = {r.category for r in self.setup.store.catalogue(request.hashes)}
            if len(categories) == 1:
                return categories.pop()
        return None

    def download_destinations(self) -> set[str]:
        folders = self.setup.settings.download_folders
        result = set()
        for value in [folders.default, *folders.by_category.values()]:
            if not value:
                continue
            try:
                result.add(str(self.setup.path_under_root(value)))
            except (ValueError, OSError):
                # An unrelated disconnected destination does not invalidate this one.
                continue
        return result

    def queue(self) -> list[dict[str, Any]]:
        return [
            {
                "client_id": e.client_id,
                "client_name": self.setup.settings.profile(e.client_id).name,
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
        if request.kind == "configure-download-folder":
            return self.setup.configure_download_folder(
                request.path, request.category, request.client_path, save=True
            )
        if request.kind == "upload-preview":
            if request.draft_id:
                record = self.setup.store.local_draft(request.draft_id)
                if record["path"] != request.path:
                    raise ValueError("A Local Draft cannot be moved to another Local Item.")
            return self.uploads.prepare(
                request.path, request.upload, stop, stored=bool(request.draft_id)
            )[1]
        if request.kind == "upload-queue":
            return self.uploads.queue(
                request.path, request.upload, stop, request.draft_id, request.revision
            )
        if request.kind == "upload-send":
            return self.uploads.send(request.draft_id, request.revision, stop, progress)
        if request.kind == "upload-remove":
            self.setup.store.remove_local_draft(request.draft_id, request.revision)
            return {"removed": request.draft_id}
        if request.kind == "upload-reset":
            return reset_local(self.setup.store, request.draft_id, request.revision)
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
            from torrentlinker.web.planning import catalogue as update_plan_catalogue
            from torrentlinker.web.planning import catalogue_status, plan

            if request.client_ids:
                from dataclasses import replace

                from torrentlinker.multi_plan import distributed_plan
                from torrentlinker.plan import PlanOptions

                targets = {
                    identifier: self.setup.for_client(identifier)
                    for identifier in dict.fromkeys(request.client_ids)
                }
                if not request.cached_only:
                    update_plan_catalogue(self.setup, stop, progress)
                if stop.is_set():
                    return {
                        "cancelled": True,
                        "rows": [],
                        "catalogue": catalogue_status(self.setup),
                    }
                settings = replace(
                    self.setup.settings,
                    plan_categories=[request.category]
                    if request.category is not None
                    else self.setup.settings.plan_categories,
                    plan_options=PlanOptions(
                        max_download_bytes=request.maximum_bytes,
                        max_torrents=request.maximum_torrents,
                    ),
                )

                def validate(identifier, folder):
                    target = targets[identifier]
                    target.configure_download_folder(str(folder))
                    Library(target).check_tree(folder, stop)

                proposed = distributed_plan(
                    settings,
                    self.setup.store,
                    {identifier: target.client() for identifier, target in targets.items()},
                    request.client_budgets,
                    validate,
                )
                return {
                    "provisional": True,
                    "catalogue": catalogue_status(self.setup),
                    "zen": proposed.zen_added,
                    "size": proposed.download_size,
                    "rows": [
                        {
                            "hash": i.candidate.infohash,
                            "title": i.candidate.title,
                            "size": i.candidate.size,
                            "seeders": i.candidate.seeders,
                            "zen": i.zen,
                            "note": i.note,
                            "client_id": i.candidate.client_id,
                            "folder": str(i.candidate.folder),
                        }
                        for i in proposed.items
                    ],
                }
            return plan(
                self.setup,
                self.library,
                request.maximum_bytes,
                request.maximum_torrents,
                stop,
                progress,
                cached_only=request.cached_only,
                category=request.category,
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
                    self.setup.verified_download_folder(self.request_category(request)),
                )
            return {
                "queued": count,
                "location": "TorrentLinker Search > Download queue",
                "sent_to_client": False,
                "downloads_started": False,
                "next_step": "Use send-queue only if the user asks to start downloads.",
            }
        if request.kind == "send-queue":
            queued_entries = [
                e
                for e in entries(self.setup.store)
                if e.status == "queued"
                and (not request.hashes or e.candidate.infohash in request.hashes)
            ]
            if not queued_entries and self.setup.download_folder(request.category):
                self.setup.verified_download_folder(request.category)
            # Recheck selected folders, including entries saved before settings changed.
            for entry in queued_entries:
                if entry.status == "queued":
                    self.setup.path_under_root(str(entry.folder))
                    self.setup.configure_download_folder(str(entry.folder))
                    if str(entry.folder) not in self.download_destinations():
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
                only={
                    e.key
                    for e in entries(self.setup.store)
                    if e.candidate.infohash in request.hashes
                }
                if request.hashes
                else None,
            )
            return {
                "added": len(report.added),
                "refused": [title for title, _ in report.refused],
                "failed": [title for title, _ in report.failed],
                "stopped": report.stopped,
            }
        if request.kind in {"refresh", "select-torrents"}:
            torrents = self.setup.client().torrents(with_files=False)
            settings = self.setup.settings
            cached_rows = {
                r.infohash: r
                for r in self.setup.store.catalogue([t.hash.lower() for t in torrents])
            }
            cached_rows.update(observe_swarm(self.setup.store, torrents, settings.indexer.url))
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
                        "client_id": settings.active_client_id,
                        "client_name": settings.profile().name,
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
                        "total_seeds": t.swarm_seeders,
                        "total_peers": t.swarm_peers,
                        "folder": str(t.save_path),
                        "trackers": tracker_hosts(t),
                        "categories": torrent_categories(t, labels),
                        "tags": sorted(t.tags),
                        "zen": estimate.zen if estimate else None,
                        "note": estimate.note if estimate else None,
                        "provisional": estimate.provisional_category if estimate else False,
                        "ranking_metrics_known": estimate is not None
                        and (t.swarm_seeders >= 0 or t.hash.lower() in cached_rows),
                    }
                )
            self.rows = rows
            self.observed = torrents
            self.connection_error = ""
            self.zen = {"count": view.count, "daily": view.day.total, "paid": view.day.paid}
            if request.kind == "select-torrents":
                return select_rows(rows, request.selection)
            return {"count": len(rows), "zen": self.zen}
        if request.kind == "manage":
            if request.selection_id:
                # Refresh and check the ranking inside the same desktop coordination scope.
                # Never replace a missing or changed selection with different torrents.
                Operations.run(
                    self, JobRequest(kind="refresh", client_id=request.client_id), stop, progress
                )
                selected = select_rows(self.rows, request.selection)
                if [row["hash"] for row in selected["rows"]] != request.hashes:
                    raise ValueError("Torrent selection changed. Select and review it again.")
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
            if request.selection_id:
                return {
                    "rows": result,
                    "requested_count": len(request.hashes),
                    "attempted_count": len(result),
                    "outcomes": dict(Counter(row["outcome"] for row in result)),
                    "cancelled": stop.is_set(),
                }
            return result
        raise ValueError("Unknown job.")
