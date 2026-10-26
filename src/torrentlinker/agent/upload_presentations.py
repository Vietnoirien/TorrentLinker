"""Immutable Upload review cards made from saved Local Draft revisions."""

from __future__ import annotations

import html
import json
import re
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from torrentlinker.agent.selection_presentations import Presentations
from torrentlinker.assistant.images import image_url
from torrentlinker.bbcode import bbcode_to_html
from torrentlinker.catalogue_sync import ROOTS, SUBCATS
from torrentlinker.torrent_details import preview_html
from torrentlinker.upload import category_name
from torrentlinker.upload_presentation import assess


class IncompletePresentation(ValueError):
    def __init__(self, drafts):
        super().__init__(
            "Upload presentations are incomplete. Repair the listed fields "
            "with upload-queue, then present the new revisions."
        )
        self.drafts = drafts


class DraftRevision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    draft_id: str = Field(min_length=1, max_length=100)
    revision: int = Field(ge=1)


def draft_item(draft, item_id, store=None):
    form = draft["form"]
    category, subcategory = form.get("category"), form.get("subcategory")
    mapped = SUBCATS.get(category, {}).get(subcategory, ROOTS.get(category))
    files = draft.get("files", [])
    item = Presentations.basic(
        {
            "title": form.get("title") or "Untitled Upload",
            "size": sum(file["size"] for file in files),
            "category": mapped,
            "native_category_label": category_name(category),
            "provenance": {"search": {"category": category}},
        },
        item_id,
    )
    markup, artwork = draft_preview(form)
    local_images = []
    if store is not None:
        from torrentlinker.upload_assets import Assets

        assets = Assets(store.torrent_dir.parent)
        for identifier in form.get("assets", []):
            try:
                local_images.append(assets.inline(identifier, draft["path"]))
            except ValueError:
                continue
    if local_images:
        start = len(artwork)
        markup = (
            "".join(
                f'<img src="preview-image:{i}" width="300">'
                for i in range(start, start + len(local_images))
            )
            + markup
        )
        artwork = (*artwork, *local_images)
    image = next((url for url in [form.get("image", ""), *artwork] if image_url(url)), "")
    image = image or next(iter(local_images), "")
    review = dict(draft.get("review") or {})
    completeness = assess(form, review.get("file_facts"), local=True)
    review["presentation"] = completeness
    review["refusals"] = list(
        dict.fromkeys(
            [
                *review.get("refusals", []),
                *(f"{f['field']}: {f['message']}" for f in completeness["missing_fields"]),
            ]
        )
    )
    item.update(
        presentation_type="upload_drafts",
        draft_id=draft["id"],
        draft_revision=draft["revision"],
        saved_status=draft["status"],
        image_url=image,
        artwork_status="saved_draft" if image else "missing",
        metadata_status="saved_draft",
        description_html=markup,
        description_images=list(artwork),
        description=html.unescape(re.sub(r"<[^>]+>", " ", markup)),
        nfo=form.get("nfo", ""),
        files=files,
        upload_form=form,
        upload_review=review,
        review_summary={key: len(review.get(key, [])) for key in ("warnings", "refusals")},
        facts={
            "Category": category_name(category),
            "Subcategory": str(subcategory or ""),
            "Source": form.get("source", ""),
            "Files": str(len(files)),
        },
    )
    return item


def draft_preview(form):
    # Upload descriptions are BBCode, including literal HTML typed by a user.
    return preview_html("<div>" + bbcode_to_html(form.get("description", "")) + "</div>")


def current_state(item, store):
    """Keep the reviewed contents frozen while marking edits/removal since capture."""
    # Render old snapshots from their frozen form too; never substitute current edits.
    from torrentlinker.upload_assets import inline_image

    markup, images = draft_preview(item.get("upload_form") or {})
    local_images = [url for url in item.get("description_images", []) if inline_image(url)]
    if local_images:
        markup = (
            "".join(
                f'<img src="preview-image:{i}" width="300">'
                for i in range(len(images), len(images) + len(local_images))
            )
            + markup
        )
        images = (*images, *local_images)
    item = {**item, "description_html": markup, "description_images": list(images)}
    try:
        current = store.local_draft(item["draft_id"])
    except ValueError:
        return {**item, "draft_deleted": True, "draft_changed": True}
    return {
        **item,
        "draft_deleted": False,
        "draft_changed": current["revision"] != item["draft_revision"],
        "current_revision": current["revision"],
        "current_status": current["status"],
    }


def present(service, actor, request_id, client_id, drafts, title="", offset=0, limit=12):
    if not 1 <= len(drafts) <= 50 or len({draft.draft_id for draft in drafts}) != len(drafts):
        raise ValueError("Choose 1 to 50 distinct Local Drafts with their exact revisions.")
    if offset < 0 or not 1 <= limit <= 20:
        raise ValueError("Use offset >= 0 and page limit from 1 to 20.")
    service.target(actor, client_id)
    intent = dict(
        tool="present_upload_drafts",
        client_id=client_id,
        drafts=[draft.model_dump() for draft in drafts],
        title=title,
        offset=offset,
        limit=limit,
    )
    presentations = service.presentations

    def work():
        store = service.target(actor, client_id).setup.store
        records = []
        for ref in drafts:
            record = store.local_draft(ref.draft_id)
            if record["revision"] != ref.revision:
                raise ValueError(
                    "Local Draft changed. Read upload-queue and present the current revision."
                )
            records.append(record)
        incomplete = []
        for record in records:
            check = assess(record["form"], record.get("review", {}).get("file_facts"), local=True)
            if check["missing_fields"]:
                incomplete.append(
                    {"draft_id": record["id"], "revision": record["revision"], **check}
                )
        if incomplete:
            raise IncompletePresentation(incomplete)
        # All items are captured before insertion; page/detail reads never enrich or fetch c411.
        items = [draft_item(record, str(i), store) for i, record in enumerate(records)]
        identifier = uuid4().hex
        body = dict(
            presentation_type="upload_drafts",
            rows=[{} for _ in items],
            title=title or "Upload drafts",
            list_id="",
            revision=None,
            research=False,
            enrichment=False,
        )
        service.access.db.execute(
            "INSERT INTO selection_presentations VALUES (?,?,?,?)",
            (identifier, actor, client_id, json.dumps(body)),
        )
        service.access.db.executemany(
            "INSERT INTO selection_presentation_items VALUES (?,?,?)",
            [(identifier, item["item_id"], json.dumps(item)) for item in items],
        )
        return {"id": identifier}

    saved = service.torrent_lists.write_request(actor, request_id, intent, work)
    return presentations.page(actor, saved["id"], offset, limit)
