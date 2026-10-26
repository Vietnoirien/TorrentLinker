"""Durable planning lists: owned revisions and immutable action materializations."""

from __future__ import annotations

import json
import re
import threading
import time
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from torrentlinker.category_tags import category_path
from torrentlinker.queue_selection import snapshot, statistics
from torrentlinker.torrent_management import comparison_status

MAX_ROWS = 10_000


class ListFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")
    categories: list[int] = Field(default_factory=list, max_length=100)
    include_descendants: bool = True
    query: str = Field(default="", max_length=500)
    exclude_terms: list[str] = Field(default_factory=list, max_length=100)
    client_ids: list[str] = Field(default_factory=list, max_length=100)
    min_size_bytes: int = Field(default=0, ge=0)
    max_size_bytes: int | None = Field(default=None, ge=0)
    sort_by: Literal["saved", "size", "title", "seeders"] = "saved"
    descending: bool = False
    count: int | None = Field(default=None, ge=0, le=10_000)

    def supplied(self):
        return bool(
            self.categories
            or self.query.strip()
            or any(term.strip() for term in self.exclude_terms)
            or self.client_ids
            or self.min_size_bytes
            or self.max_size_bytes is not None
            or self.count is not None
        )

    def select(self, rows, categories):
        selected = [row for row in rows if self.matches(row, categories)]
        if self.sort_by != "saved":
            selected.sort(
                key=lambda r: r["title"].casefold() if self.sort_by == "title" else r[self.sort_by],
                reverse=self.descending,
            )
        elif self.descending:
            selected.reverse()
        return selected if self.count is None else selected[: self.count]

    def matches(self, row, categories):
        ids = (
            set(category_path(row.get("category"), categories))
            if self.include_descendants
            else {row.get("category")}
        )
        title = row["title"].casefold()
        return (
            (not self.client_ids or row.get("client_id") in self.client_ids)
            and (not self.categories or bool(ids.intersection(self.categories)))
            and self.query.strip().casefold() in title
            and (not self.min_size_bytes or row["size"] >= self.min_size_bytes)
            and (self.max_size_bytes is None or row["size"] <= self.max_size_bytes)
            and not any(
                term.strip().casefold() in title for term in self.exclude_terms if term.strip()
            )
        )


class TorrentLists:
    def __init__(self, service):
        self.service = service
        self.access = service.access
        with self.access.lock, self.access.db:
            self.access.db.executescript(
                "CREATE TABLE IF NOT EXISTS torrent_lists (id TEXT PRIMARY KEY, actor TEXT, "
                "client TEXT, name TEXT, revision INTEGER);"
                "CREATE TABLE IF NOT EXISTS torrent_list_revisions "
                "(list_id TEXT, revision INTEGER, "
                "body TEXT, PRIMARY KEY(list_id,revision));"
                "CREATE TABLE IF NOT EXISTS torrent_list_requests (actor TEXT, request_id TEXT, "
                "intent TEXT, result TEXT, PRIMARY KEY(actor,request_id));"
                "CREATE TABLE IF NOT EXISTS torrent_list_selections (id TEXT PRIMARY KEY, "
                "actor TEXT, client TEXT, body TEXT);"
            )

    def _record(self, actor, identifier):
        with self.access.lock:
            self.access.grant(actor)
            row = self.access.db.execute(
                "SELECT * FROM torrent_lists WHERE id=? AND actor=?", (identifier, actor)
            ).fetchone()
            if row is None:
                raise ValueError("Torrent list not found for this connection.")
            if row["client"] != "all":
                self.service.target(actor, row["client"])
            return row

    def _rows(self, record, revision):
        row = self.access.db.execute(
            "SELECT body FROM torrent_list_revisions WHERE list_id=? AND revision=?",
            (record["id"], revision),
        ).fetchone()
        if row is None:
            raise ValueError("Torrent list revision not found.")
        rows = json.loads(row[0])
        for item in rows:
            item.setdefault("client_id", record["client"])
            self.service.target(record["actor"], item["client_id"])
        return rows

    def _summary(self, record, rows, revision=None):
        return {
            "id": record["id"],
            "name": record["name"],
            "client_id": record["client"],
            "revision": revision if revision is not None else record["revision"],
            **statistics(rows),
            "torrent_instance_count": len(rows),
            "unique_hash_count": len({r["hash"] for r in rows}),
            "metadata_size_bytes": sum(r["size"] for r in rows if r.get("size") is not None),
            "size_note": (
                "Metadata sizes may include shared files; no reclaimable bytes are inferred."
            ),
            "maximum_rows": MAX_ROWS,
        }

    def write_request(self, actor, request_id, intent, work):
        self.access.grant(actor)
        if not request_id or len(request_id) > 100:
            raise ValueError("Supply a stable request_id of 1 to 100 characters.")
        serialized = json.dumps(intent, sort_keys=True)
        with self.access.lock, self.access.db:
            if self.access.db.execute(
                "SELECT 1 FROM proposals WHERE grant_id=? AND request_id=?", (actor, request_id)
            ).fetchone():
                raise ValueError("This request_id already belongs to a different operation.")
            previous = self.access.db.execute(
                "SELECT intent,result FROM torrent_list_requests WHERE actor=? AND request_id=?",
                (actor, request_id),
            ).fetchone()
            if previous:
                if previous[0] != serialized:
                    raise ValueError("This request_id already belongs to a different operation.")
                return json.loads(previous[1])
            result = work()
            self.access.db.execute(
                "INSERT INTO torrent_list_requests VALUES (?,?,?,?)",
                (actor, request_id, serialized, json.dumps(result)),
            )
            return result

    def _import(self, actor, client, selection_id):
        if not selection_id:
            return []
        source_client, saved = self.service.selection(actor, selection_id, kind=None)
        source_clients = set(saved.get("client_ids") or [source_client])
        if len(source_clients) > 1 and client != "all":
            raise ValueError("A multi-client selection requires client_id=all.")
        if client != "all" and source_clients != {client}:
            raise ValueError("Selection and list must belong to the same Torrent Client.")
        rows = []
        seen = set()
        for item in saved["rows"]:
            identity = item.get("hash", "").lower()
            item_client = item.get("client_id", source_client)
            self.service.target(actor, item_client)
            if not re.fullmatch(r"[0-9a-f]{40}", identity):
                raise ValueError(
                    "Lists require known torrent identities; source contains an unknown hash."
                )
            if (item_client, identity) in seen:
                continue
            seen.add((item_client, identity))
            rows.append(
                {
                    **item,
                    "hash": identity,
                    "client_id": item_client,
                    "title": item.get("title", item.get("name", "")),
                    "category": item.get("category"),
                    "seeders": item.get("seeders", 0),
                    **(
                        {
                            "client_observation": next(
                                (
                                    o
                                    for o in saved.get("observations", [])
                                    if o["client_id"] == item_client
                                ),
                                {"client_id": item_client, "observed_at": saved["snapshot_at"]},
                            )
                        }
                        if saved.get("source") == "torrent-clients"
                        else {}
                    ),
                    "provenance": {
                        "selection_id": selection_id,
                        "source": saved.get("source", "torrent-clients"),
                        "indexer_url": item.get("indexer_url")
                        or item.get("provenance", {}).get("indexer_url")
                        or saved.get("indexer_url", ""),
                        "snapshot_at": saved["snapshot_at"],
                        "selection_fingerprint": saved.get("selection_fingerprint", ""),
                        **(
                            {
                                "discovery": "live-search",
                                "search": saved["search"],
                                "page": saved["page"],
                                "backend": saved["backend"],
                            }
                            if saved.get("selection_kind") == "live-search"
                            else {}
                        ),
                        **(
                            {"list_id": saved["list_id"], "list_revision": saved["list_revision"]}
                            if "list_id" in saved
                            else {}
                        ),
                    },
                }
            )
        return rows

    def create(self, actor, request_id, client_id, name, selection_id=""):
        if client_id != "all":
            self.service.target(actor, client_id)
        elif not selection_id:
            raise ValueError("A cross-client list needs a saved selection.")
        name = name.strip()
        if not name or len(name) > 120 or any(ord(c) < 32 for c in name):
            raise ValueError("Use a list name of 1 to 120 printable characters.")

        def work():
            rows = self._import(actor, client_id, selection_id)
            record = {
                "id": uuid4().hex,
                "actor": actor,
                "client": client_id,
                "name": name,
                "revision": 1,
            }
            self.access.db.execute(
                "INSERT INTO torrent_lists VALUES (?,?,?,?,?)", tuple(record.values())
            )
            self.access.db.execute(
                "INSERT INTO torrent_list_revisions VALUES (?,?,?)",
                (record["id"], 1, json.dumps(rows)),
            )
            return self._summary(record, rows)

        return self.write_request(
            actor,
            request_id,
            {"tool": "create", "client": client_id, "name": name, "selection": selection_id},
            work,
        )

    def edit(self, actor, request_id, list_id, expected_revision, action, selection_id, subset):
        self._record(actor, list_id)

        def work():
            record = self._record(actor, list_id)
            if record["revision"] != expected_revision:
                raise ValueError(
                    "Torrent list revision changed. Read the current revision before editing."
                )
            rows = self._rows(record, expected_revision)
            categories = self.service.setup.settings.indexer_categories
            if action == "clear":
                if selection_id or subset != ListFilter():
                    raise ValueError("Clear takes no source or filter; use remove for a subset.")
                imported = []
            elif action in {"keep", "remove"}:
                if selection_id:
                    if subset != ListFilter():
                        raise ValueError(
                            "Use either a source selection or a subset filter, not both."
                        )
                    imported = self._import(actor, record["client"], selection_id)
                elif subset.supplied():
                    imported = subset.select(rows, categories)
                else:
                    raise ValueError(
                        "Keep/remove require a source selection or explicit subset filter. "
                        "Use clear to empty the list intentionally."
                    )
            else:
                if not selection_id:
                    raise ValueError(
                        "Add/replace require an explicit source selection. "
                        "Use clear to empty the list intentionally."
                    )
                if action != "replace_subset" and subset != ListFilter():
                    raise ValueError("This action does not accept a subset filter.")
                if action == "replace_subset" and not subset.supplied():
                    raise ValueError("Replace_subset requires an explicit subset filter.")
                imported = self._import(actor, record["client"], selection_id)
            identities = {(r["client_id"], r["hash"]) for r in imported}
            if action == "clear":
                result = []
            elif action == "add":
                existing = {(r["client_id"], r["hash"]) for r in rows}
                result = rows + [r for r in imported if (r["client_id"], r["hash"]) not in existing]
            elif action in {"remove", "keep"}:
                result = [
                    r
                    for r in rows
                    if ((r["client_id"], r["hash"]) in identities) == (action == "keep")
                ]
            elif action == "replace":
                result = imported
            elif action == "replace_subset":
                selected_hashes = {
                    (r["client_id"], r["hash"]) for r in subset.select(rows, categories)
                }
                matching = [(r["client_id"], r["hash"]) in selected_hashes for r in rows]
                kept = {
                    (r["client_id"], r["hash"])
                    for r, match in zip(rows, matching, strict=True)
                    if not match
                }
                replacements = [r for r in imported if (r["client_id"], r["hash"]) not in kept]
                # Insert replacements where the first matching row used to be.
                result = []
                inserted = False
                for row, match in zip(rows, matching, strict=True):
                    if match and not inserted:
                        result.extend(replacements)
                        inserted = True
                    if not match:
                        result.append(row)
                if not inserted:
                    result.extend(replacements)
            else:
                raise ValueError("Unknown list edit action.")
            if len(result) > MAX_ROWS:
                raise ValueError(
                    f"Torrent lists hold at most {MAX_ROWS} rows; nothing was changed."
                )
            revision = expected_revision + 1
            self.access.db.execute(
                "INSERT INTO torrent_list_revisions VALUES (?,?,?)",
                (list_id, revision, json.dumps(result)),
            )
            self.access.db.execute(
                "UPDATE torrent_lists SET revision=? WHERE id=?", (revision, list_id)
            )
            return self._summary(record, result, revision)

        return self.write_request(
            actor,
            request_id,
            {
                "tool": "edit",
                "id": list_id,
                "revision": expected_revision,
                "action": action,
                "selection": selection_id,
                "subset": subset.model_dump(),
            },
            work,
        )

    def snapshot(self, actor, list_id, revision):
        """Return an owned immutable revision for server-side planning consumers."""
        with self.access.lock:
            record = self._record(actor, list_id)
            return record["client"], record["name"], self._rows(record, revision)

    def get(self, actor, list_id, revision, offset, limit):
        with self.access.lock:
            record = self._record(actor, list_id)
            rows = self._rows(record, revision)
            page = rows[offset : offset + limit]
            return {
                **self._summary(record, rows, revision),
                "current_revision": record["revision"],
                "offset": offset,
                "rows": page,
                "has_more": offset + len(page) < len(rows),
                "next_offset": offset + len(page) if offset + len(page) < len(rows) else None,
            }

    def listing(self, actor, client_id, offset, limit):
        if client_id != "all":
            self.service.target(actor, client_id)
        else:
            self.access.grant(actor)
        with self.access.lock:
            records = self.access.db.execute(
                "SELECT * FROM torrent_lists WHERE actor=? AND client=? ORDER BY rowid",
                (actor, client_id),
            ).fetchall()
            for record in records:
                self._record(actor, record["id"])
            return {
                "lists": [
                    self._summary(r, self._rows(r, r["revision"]))
                    for r in records[offset : offset + limit]
                ],
                "total": len(records),
                "has_more": offset + limit < len(records),
                "next_offset": offset + limit if offset + limit < len(records) else None,
            }

    def select(
        self, actor, request_id, list_id, expected_revision, source, criteria, offset, count
    ):
        self._record(actor, list_id)

        def work():
            record = self._record(actor, list_id)
            if record["revision"] != expected_revision:
                raise ValueError("Torrent list revision changed. Review its current revision.")
            if record["client"] == "all" and source != "clients":
                raise ValueError("Cross-client lists materialize through source=clients.")
            setup = (
                self.service.setup
                if record["client"] == "all"
                else self.service.target(actor, record["client"]).setup
            )
            all_rows = self._rows(record, expected_revision)
            if source == "clients" and any(
                r.get("provenance", {}).get("source") != "torrent-clients" for r in all_rows
            ):
                raise ValueError("Use source=clients only for saved Torrent Client rows.")
            if source != "clients" and any(
                r.get("provenance", {}).get("source") == "torrent-clients" for r in all_rows
            ):
                raise ValueError("Saved Torrent Client rows require source=clients.")
            eligible = criteria.select(all_rows, setup.settings.indexer_categories)
            chosen = eligible[offset : offset + count]
            refreshed_count = 0
            if source == "clients":
                from torrentlinker.torrent_selection import SelectionCriteria
                from torrentlinker.web.operations import JobRequest

                clients = list(dict.fromkeys(r["client_id"] for r in chosen))
                current_by_client = {}
                observations = []
                for client_id in clients:
                    target = self.service.target(actor, client_id)
                    target.run(
                        JobRequest(kind="refresh", client_id=client_id),
                        threading.Event(),
                        lambda _: None,
                    )
                    current_by_client[client_id] = {r["hash"]: r for r in target.rows}
                    observations.append(
                        {
                            "client_id": client_id,
                            "available": True,
                            "observed_at": time.time(),
                            "scanned_count": len(target.rows),
                        }
                    )
                resolved = []
                for row in chosen:
                    now = current_by_client[row["client_id"]].get(row["hash"])
                    if now is None or any(now[k] != row[k] for k in ("name", "size", "status")):
                        raise ValueError("Torrent changed. Review the list and select again.")
                    resolved.append({**row, **now, "client_id": row["client_id"]})
                saved = snapshot(resolved, "torrent-clients", SelectionCriteria().model_dump())
                saved.update(
                    client_ids=clients,
                    count_scope="saved",
                    ranking_complete=True,
                    torrent_instance_count=len(resolved),
                    unique_hash_count=len({r["hash"] for r in resolved}),
                    metadata_size_bytes=sum(r["size"] for r in resolved),
                    observations=observations,
                )
            elif source == "queue":
                from torrentlinker.queue_selection import queue_rows

                current = {}
                for row in queue_rows(setup):
                    if row["status"] == "queued":
                        current.setdefault(row["hash"], []).append(row)
                resolved = []
                for row in chosen:
                    matches = current.get(row["hash"], [])
                    if len(matches) != 1:
                        raise ValueError(
                            "Each listed torrent needs exactly one queued entry. Review the queue."
                        )
                    match = matches[0]
                    if any(match[k] != row[k] for k in ("title", "size", "category")):
                        raise ValueError(
                            "Queued torrent metadata changed. Review the list and queue."
                        )
                    refreshed_count += any(match[k] != row[k] for k in ("seeders",))
                    resolved.append(match)
            else:
                from torrentlinker.queue_selection import validate_catalogue_subset

                catalogue = {
                    r.infohash: r for r in setup.store.catalogue([r["hash"] for r in chosen])
                }
                resolved = []
                for row in chosen:
                    item = catalogue.get(row["hash"])
                    if item is None or any(
                        getattr(item, k) != row[k] for k in ("title", "size", "category")
                    ):
                        raise ValueError(
                            "Catalogue metadata changed or is unavailable. Review the list."
                        )
                    refreshed_count += item.seeders != row["seeders"] or item.seen_at != row.get(
                        "seen_at"
                    )
                    original = row["provenance"]
                    if original["source"] == "catalogue" and row.get("source") != item.source:
                        raise ValueError("Catalogue source changed. Review the list.")
                    resolved.append(
                        {
                            **row,
                            "hash": row["hash"],
                            "title": row["title"],
                            "size": row["size"],
                            "category": row["category"],
                            "seeders": item.seeders,
                            "source": item.source,
                            "seen_at": item.seen_at,
                        }
                    )
                validate_catalogue_subset(setup, resolved)
            if source != "clients":
                saved = snapshot(resolved, source, {})
            saved.update(
                parent_selection_id=f"list:{list_id}:{expected_revision}",
                list_id=list_id,
                list_revision=expected_revision,
                refreshed_fields=["seeders", "seen_at"] if source == "catalogue" else ["seeders"],
                volatile_metadata_refreshed_count=refreshed_count,
                list_totals=statistics(all_rows),
                eligible_count=len(eligible),
                has_more=offset + len(chosen) < len(eligible),
                next_offset=offset + len(chosen) if offset + len(chosen) < len(eligible) else None,
            )
            identifier = uuid4().hex
            self.access.db.execute(
                "INSERT INTO torrent_list_selections VALUES (?,?,?,?)",
                (identifier, actor, record["client"], json.dumps(saved)),
            )
            return {
                "selection_id": identifier,
                "list_id": list_id,
                "name": record["name"],
                "revision": expected_revision,
                **{k: v for k, v in saved.items() if k != "rows"},
                "expires_at": saved["snapshot_at"] + 900,
            }

        return self.write_request(
            actor,
            request_id,
            {
                "tool": "select",
                "id": list_id,
                "revision": expected_revision,
                "source": source,
                "criteria": criteria.model_dump(),
                "offset": offset,
                "count": count,
            },
            work,
        )

    def selection(self, actor, identifier, kind):
        row = self.access.db.execute(
            "SELECT * FROM torrent_list_selections WHERE id=? AND actor=?", (identifier, actor)
        ).fetchone()
        if row is None:
            return None
        saved = json.loads(row["body"])
        for client_id in saved.get("client_ids", [row["client"]]):
            self.service.target(actor, client_id)
        if kind not in {None, "select-catalogue", "select-torrents"}:
            raise ValueError("Use a completed live torrent selection for client management.")
        if kind == "select-torrents" and saved["source"] != "torrent-clients":
            raise ValueError("Use a saved client selection for client management.")
        if time.time() - saved["snapshot_at"] > 900:
            raise ValueError("Selection expired. Materialize the durable list again.")
        return row["client"], saved

    def compare_client(self, actor, list_id, expected_revision, offset, limit):
        with self.access.lock:
            record = self._record(actor, list_id)
            if record["revision"] != expected_revision:
                raise ValueError("Torrent list revision changed. Read the current revision.")
            rows = self._rows(record, expected_revision)
            if record["client"] == "all":
                client_ids = sorted({r["client_id"] for r in rows})
                presence = self.service.client_presence(
                    actor, client_ids, {r["hash"] for r in rows}
                )
                groups = {
                    key: []
                    for key in (
                        "actively_seeding",
                        "completed_paused",
                        "completed_other",
                        "incomplete",
                        "absent",
                        "unavailable",
                    )
                }
                classified = []
                for item in rows:
                    observation = presence[item["client_id"]]
                    state = (
                        observation["statuses"][item["hash"]]
                        if observation["available"]
                        else "unavailable"
                    )
                    groups[state].append(item)
                    classified.append(
                        {
                            "client_id": item["client_id"],
                            "hash": item["hash"],
                            "title": item["title"],
                            "status": state,
                        }
                    )
                return {
                    **self._summary(record, rows),
                    "observed_at": time.time(),
                    "observations": [
                        {
                            "client_id": client_id,
                            **{
                                key: value
                                for key, value in presence[client_id].items()
                                if key not in {"statuses", "completed"}
                            },
                        }
                        for client_id in client_ids
                    ],
                    "groups": {key: statistics(values) for key, values in groups.items()},
                    "rows": classified[offset : offset + limit],
                    "has_more": offset + limit < len(rows),
                    "next_offset": offset + limit if offset + limit < len(rows) else None,
                    "note": "Unavailable clients are unknown, never absent. Active seeding "
                    "reflects client state, not measured traffic.",
                }
            setup = self.service.target(actor, record["client"]).setup
        observed = time.time()
        live = {t.hash.lower(): t for t in setup.client().torrents(with_files=False)}
        groups = {
            key: []
            for key in (
                "actively_seeding",
                "completed_paused",
                "completed_other",
                "incomplete",
                "absent",
            )
        }
        classified = []
        for row in rows:
            torrent = live.get(row["hash"])
            status = comparison_status(torrent)
            groups[status].append(row)
            classified.append(
                {
                    "hash": row["hash"],
                    "title": row["title"],
                    "status": status,
                    "client_state": torrent.state if torrent else None,
                }
            )
        return {
            **self._summary(record, rows),
            "observed_at": observed,
            "groups": {key: statistics(values) for key, values in groups.items()},
            "rows": classified[offset : offset + limit],
            "has_more": offset + limit < len(rows),
            "next_offset": offset + limit if offset + limit < len(rows) else None,
            "note": "Active seeding means the client reports an active upload/seeding state; "
            "it does not prove current traffic. Unknown states are completed_other.",
        }
