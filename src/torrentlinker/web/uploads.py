"""Server-side Upload preparation with the desktop category profiles."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import asdict
from typing import Any

from pydantic import BaseModel, Field

from torrentlinker.options import category_options, options_body
from torrentlinker.paths import PathMapper
from torrentlinker.scan import scan_item
from torrentlinker.torrent_details import web_url
from torrentlinker.upload import (
    PROFILES,
    PreparedUpload,
    UploadRequest,
    create_upload,
    default_category,
    missing_options,
    seed_upload,
    upload_files,
)
from torrentlinker.web.library import Library
from torrentlinker.web.setup import Setup


class UploadForm(BaseModel):
    category: int | None = None
    subcategory: int | None = None
    source: str = Field(default="", max_length=200)
    image: str = Field(default="", max_length=2048)
    title: str = Field(default="", max_length=200)
    description: str = Field(default="", max_length=15000)
    nfo: str = Field(default="", max_length=100000)
    options: dict[int, list[int]] = Field(default_factory=dict, max_length=50)
    reviewed: bool = False


class Uploads:
    def __init__(self, setup: Setup, library: Library):
        self.setup = setup
        self.library = library
        self.prepared: dict[str, tuple[PreparedUpload, str]] = {}

    def prepare(
        self, path: str, form: UploadForm, stop: threading.Event
    ) -> tuple[UploadRequest, dict[str, Any]]:
        entry = self.library.entry(path)
        self.library.check_tree(entry.item.path, stop)
        item = scan_item(entry.item.path)
        cid = form.category or default_category(entry.folder.kind)
        profile = PROFILES.get(cid) if cid is not None else None
        if profile is None:
            raise ValueError("Choose a supported Upload Category.")
        ignore = self.setup.settings.matching.ignore
        profile.inspect(item, ignore)
        sub = form.subcategory or profile.default_subcategory(item, ignore)
        if sub not in {s.id for s in profile.subcategories}:
            raise ValueError("Choose a subcategory from the selected Upload Category.")
        title = form.title or profile.suggested_name(item, ignore, form.source, sub)
        if not title or title in {".", ".."} or any(c in title for c in "/\\\x00"):
            raise ValueError("Use a release name without directory separators.")
        files = upload_files(item, title, ignore, profile.media_extensions)
        types = (
            category_options(self.setup.store, self.setup.indexer().category_options, sub)
            if self.setup.secrets.get("indexer-api-key")
            else []
        )
        chosen = form.options or profile.suggested_options(item, ignore, types)
        for kind in types:
            values = chosen.get(kind.id, [])
            if len(values) > (100 if kind.multiple else 1) or not set(values).issubset(
                {v.id for v in kind.values}
            ):
                raise ValueError("Invalid category option.")
        image = web_url(form.image)
        if form.image and not image:
            raise ValueError("Use a direct HTTP(S) image link.")
        description = form.description or profile.description(title, files, form.source, image)
        if image and image not in description:
            description = f"[center][img]{image}[/img][/center]\n" + description
        nfo = form.nfo or profile.nfo(title, files)
        request = UploadRequest(
            item,
            title,
            files,
            nfo,
            description,
            profile.category,
            sub,
            options_body(types, chosen),
            profile.draft_fields(item, ignore, files),
        )
        refusals = profile.refusals(item, ignore, sub) + missing_options(types, chosen)
        preview = {
            "title": title,
            "category": profile.category,
            "subcategory": sub,
            "subcategories": [asdict(s) for s in profile.subcategories],
            "files": [asdict(f) for f in files],
            "nfo": nfo,
            "description": description,
            "options": [asdict(t) for t in types],
            "chosen": chosen,
            "refusals": [f"{r.problem.value}: {r.detail}" for r in refusals],
            "warnings": [
                f"{w.judgement.value}: {w.detail}" for w in profile.warnings(item, ignore, sub)
            ],
        }
        return request, preview

    def draft(
        self, path: str, form: UploadForm, stop: threading.Event, progress: Callable[[Any], None]
    ) -> dict:
        if not form.reviewed:
            raise ValueError("Review the Upload description, files and category warnings first.")
        request, preview = self.prepare(path, form, stop)
        if preview["refusals"]:
            raise ValueError("Resolve the Upload refusals before saving the Draft.")
        if not web_url(form.image):
            raise ValueError("Add a hosted image to the description before saving the Draft.")
        directory = self.setup.path.parent / "uploads"
        directory.mkdir(exist_ok=True)
        prepared = create_upload(
            request,
            self.setup.secrets.get("announce-url"),
            directory,
            self.setup.indexer().save_draft,
            self.setup.store,
            report=lambda done, total: progress({"done": done, "total": total}),
            stopped=stop.is_set,
        )
        client_path = PathMapper(self.setup.settings.path_mappings).to_qbit(str(request.item.path))
        self.prepared[prepared.meta.infohash] = (prepared, client_path)
        return {
            "hash": prepared.meta.infohash,
            "title": prepared.saved.title,
            "draft_id": prepared.saved.draft_id,
            "message": (
                "Draft saved. Review and publish it on c411. It has not been seeded automatically."
            ),
        }

    def seed(self, hash: str, stop: threading.Event) -> dict:
        record = self.prepared.get(hash)
        if record is None:
            raise ValueError("This prepared Upload is not available in this server session.")
        prepared, client_path = record
        if not any(
            prepared.saved.item_path.is_relative_to(folder.path)
            for folder in self.setup.settings.library_folders
        ):
            raise ValueError("This Upload's Library Folder was removed. Register it again first.")
        current_path = PathMapper(self.setup.settings.path_mappings).to_qbit(
            str(prepared.saved.item_path)
        )
        if current_path != client_path:
            raise ValueError(
                "This Upload's Path Mapping changed. Review its destination before seeding."
            )
        self.library.check_tree(prepared.saved.item_path, stop)
        item = scan_item(prepared.saved.item_path)
        client = self.library.client()
        if client.requires_disk_renames:
            raise ValueError("Review µTorrent Upload disk renames in the desktop application.")
        result = seed_upload(client, self.setup.store, item, prepared)
        return {"hash": result, "status": "verifying"}
