"""Select one exact release per verified film, without changing the input list."""

from __future__ import annotations

import hashlib
import json
from uuid import uuid4

from torrentlinker.queue_selection import snapshot


def deduplicate(service, actor, request_id, selection_id, list_id, expected_revision, keep, count):
    if keep not in {"first", "smallest", "most_seeded"}:
        raise ValueError("Choose first, smallest or most_seeded.")
    if count is not None and not 1 <= count <= 100:
        raise ValueError("Choose a count from 1 to 100.")
    if not request_id or len(request_id) > 100:
        raise ValueError("Supply a stable request_id of 1 to 100 characters.")
    # Persist the source before fetching metadata; retries reuse its exact observations.
    enriched = service.presentations.create(
        actor,
        "dedup-source:" + hashlib.sha256(request_id.encode()).hexdigest(),
        selection_id=selection_id,
        list_id=list_id,
        expected_revision=expected_revision,
        enrichment=True,
        limit=1,
        max_rows=100,
    )
    identifier = enriched["enrichment_id"]
    _, client, body = service.presentations.record(actor, identifier)
    rows = body["rows"]
    if any("key" in row for row in rows):
        raise ValueError("Deduplicate discovery candidates, not download queue destinations.")
    groups = {}
    unknown = set()
    for index in range(len(rows)):
        item = service.presentations.item(actor, identifier, str(index))
        identity = item.get("content_identity") or {}
        content_id = str(identity.get("id", ""))
        # TV IDs identify a whole series, not its seasons/episodes. Titles and covers
        # cannot distinguish editions, remakes or different contents reliably.
        if (
            item["kind"] == "movie"
            and item["metadata_status"] == "verified"
            and identity.get("provider") == "tmdb"
            and len(content_id) <= 12
            and content_id.isascii()
            and content_id.isdecimal()
            and int(content_id) > 0
        ):
            key = ("tmdb-movie", str(int(content_id)))
        else:
            key = ("unverified", str(index))
            unknown.add(index)
        groups.setdefault(key, []).append(index)

    def rank(index):
        row = rows[index]
        if keep == "smallest":
            size = row.get("size") or 0
            return (size if size > 0 else float("inf"), index)
        if keep == "most_seeded":
            seeders = row.get("seeders")
            return (-(seeders if seeders is not None else -1), index)
        return (index, index)

    retained = [min(indices, key=rank) for indices in groups.values()]
    chosen = retained[:count] if count is not None else retained
    intent = dict(
        tool="deduplicate_selection",
        selection_id=selection_id,
        list_id=list_id,
        expected_revision=expected_revision,
        keep=keep,
        count=count,
    )

    def save():
        service.target(actor, client)
        result = snapshot([rows[i] for i in chosen], "catalogue", intent, len(retained))
        result.update(
            parent_selection_id=selection_id or f"list:{list_id}:{expected_revision}",
            deduplication=dict(
                keep=keep,
                input_count=len(rows),
                removed_duplicate_count=len(rows) - len(retained),
                verified_distinct_count=len(groups) - len(unknown),
                unknown_identity_count=len(unknown),
                retained_unknown_count=sum(i in unknown for i in chosen),
                omitted_by_count=len(retained) - len(chosen),
                identity_scope="Verified TMDb film IDs only; unknown identities and "
                "other kinds remain separate.",
            ),
            shortfall=max(0, count - len(chosen)) if count is not None else 0,
        )
        selection = uuid4().hex
        service.access.db.execute(
            "INSERT INTO torrent_list_selections VALUES (?,?,?,?)",
            (selection, actor, client, json.dumps(result)),
        )
        return {
            "selection_id": selection,
            "client_id": client,
            **{k: v for k, v in result.items() if k not in {"rows", "deduplication"}},
            **result["deduplication"],
            "expires_at": result["snapshot_at"] + 900,
        }

    return service.torrent_lists.write_request(actor, request_id, intent, save)
