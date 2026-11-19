"""Owner Torrents panel service shared by desktop and Web."""

from __future__ import annotations

import secrets
import threading
import time
from contextlib import nullcontext
from dataclasses import asdict
from typing import Literal

from pydantic import BaseModel, Field

from torrentlinker.seeding import indexer_torrents
from torrentlinker.torrent_management import manage, peer_count_order, safe_error, tracker_group
from torrentlinker.web.operations import JobRequest, Operations
from torrentlinker.zen import weight


class TorrentQuery(BaseModel):
    client_id: str = ""
    q: str = ""
    sort: Literal[
        "name",
        "client_name",
        "status",
        "size",
        "progress",
        "download",
        "upload",
        "ratio",
        "eta",
        "note",
        "zen",
        "weight",
        "seeds",
        "peers",
        "seedtime",
    ] = "name"
    descending: bool = False
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=100, ge=1, le=200)
    tracker: str = ""
    state: str = ""
    category: str = ""
    tag: str = ""
    scope: Literal["", "c411", "other"] = ""
    size_min: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    size_max: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    note_min: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    zen_min: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    weight_min: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    seed_max: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    days_min: float | None = Field(default=None, ge=0, allow_inf_nan=False)


class TorrentInstance(BaseModel):
    client_id: str = Field(min_length=1)
    hash: str = Field(pattern=r"^[a-fA-F0-9]{40}$")


class TorrentAction(BaseModel):
    action: Literal[
        "pause",
        "resume",
        "recheck",
        "remove",
        "delete",
        "skip_files",
        "want_files",
        "reannounce",
        "limits",
        "category",
        "location",
    ]
    items: list[TorrentInstance] = Field(min_length=1, max_length=1000)
    file_indexes: list[int] = Field(default_factory=list, max_length=10000)
    download_limit: int = Field(default=0, ge=0)
    upload_limit: int = Field(default=0, ge=0)
    category: str = Field(default="", max_length=200)
    tags: list[str] = Field(default_factory=list, max_length=50)
    path: str = Field(default="", max_length=4096)
    token: str = ""


class TorrentWorkspace:
    def __init__(self, setup, for_client):
        self.setup, self.for_client = setup, for_client
        self.lock = threading.RLock()
        self.updated: dict[str, float] = {}
        self.observed_at: dict[str, float] = {}
        self.pending: dict[str, tuple] = {}

    def target(self, identifier):
        identifier = identifier or self.setup.settings.active_client_id
        profile = self.setup.settings.profile(identifier)
        if not profile.enabled:
            raise ValueError("This Torrent Client is disabled.")
        return self.for_client(identifier)

    def request(self, action, body=None):
        body = body or {}
        from torrentlinker.agent.coordination import coordinator
        from torrentlinker.agent.desktop import DesktopSetup

        # Acquire application access before our own lock. Desktop refresh must not
        # nest DesktopOperations' agent context while this request holds it.
        access = (
            coordinator.agent(threading.Event())
            if isinstance(self.setup, DesktopSetup)
            else nullcontext()
        )
        with access, self.lock:
            if action == "list":
                return self.list(TorrentQuery.model_validate(body))
            if action in {"review", "apply"}:
                return self.action(action, TorrentAction.model_validate(body))
            if action == "files":
                item = TorrentInstance.model_validate(body)
                return {
                    "files": [
                        asdict(f)
                        for f in self.target(item.client_id).setup.client().file_listing(item.hash)
                    ]
                }
            raise ValueError("Unknown torrent operation.")

    def list(self, query: TorrentQuery):
        profiles = [p for p in self.setup.settings.client_profiles if p.enabled]
        identifiers = (
            [p.id for p in profiles]
            if query.client_id == "all"
            else [query.client_id or self.setup.settings.active_client_id]
        )
        rows, errors = [], []
        for identifier in identifiers:
            target = self.target(identifier)
            try:
                if time.monotonic() - self.updated.get(identifier, 0) >= 4:
                    Operations.run(
                        target,
                        JobRequest(kind="refresh", client_id=identifier),
                        threading.Event(),
                        lambda _: None,
                    )
                    self.updated[identifier] = time.monotonic()
                    self.observed_at[identifier] = time.time()
                observed = {t.hash: t for t in target.observed}
                eligible_hashes = {
                    t.hash
                    for t in indexer_torrents(
                        target.observed,
                        target.setup.settings.indexer.url,
                        {r.infohash for r in target.setup.store.catalogue(list(observed))},
                    )
                }
                capabilities = self.capabilities(target.setup.client())
                for original in target.rows:
                    row = dict(original)
                    torrent = observed[row["hash"]]
                    # Weight uses the existing estimator, never a separate UI formula.
                    eligible = row["hash"] in eligible_hashes
                    if not row.get("ranking_metrics_known"):
                        row["note"] = row["zen"] = None
                    row.update(
                        weight=weight(row["size"]) if eligible else None,
                        c411=eligible,
                        seedtime=torrent.seeding_time / 86400,
                        key=identifier + ":" + row["hash"],
                        capabilities=capabilities,
                        observed_at=self.observed_at.get(identifier),
                    )
                    rows.append(row)
            except Exception as error:
                errors.append(
                    {"name": target.setup.settings.profile().name, "message": safe_error(error)}
                )
        all_rows = rows

        def value(row, key):
            v = (
                peer_count_order(row[key], row["total_" + key])
                if key in {"seeds", "peers"}
                else row.get(key)
            )
            return None if isinstance(v, (int, float)) and v < 0 else v

        ranges = [
            ("size_min", "size", True),
            ("size_max", "size", False),
            ("note_min", "note", True),
            ("zen_min", "zen", True),
            ("weight_min", "weight", True),
            ("seed_max", "seeds", False),
            ("days_min", "seedtime", True),
        ]

        def matches(row):
            if query.q.casefold() not in row["name"].casefold() and query.q.lower() != row["hash"]:
                return False
            if query.state and row["status"] != query.state:
                return False
            if query.tracker and query.tracker not in [tracker_group(h) for h in row["trackers"]]:
                return False
            if query.category and query.category not in [" / ".join(c) for c in row["categories"]]:
                return False
            if query.tag and query.tag not in row["tags"]:
                return False
            if query.scope and row["c411"] != (query.scope == "c411"):
                return False
            for field, key, minimum in ranges:
                threshold = getattr(query, field)
                if threshold is not None:
                    v = value(row, key)
                    if v is None or (v < threshold if minimum else v > threshold):
                        return False
            return True

        rows = [r for r in rows if matches(r)]
        known = [r for r in rows if value(r, query.sort) is not None]
        unknown = [r for r in rows if value(r, query.sort) is None]
        known.sort(
            key=lambda r: (
                str(value(r, query.sort)).casefold()
                if isinstance(value(r, query.sort), str)
                else value(r, query.sort)
            ),
            reverse=query.descending,
        )
        rows = known + unknown
        offset = min(query.offset, max(0, (len(rows) - 1) // query.limit) * query.limit)
        return {
            "rows": rows[offset : offset + query.limit],
            "total": len(rows),
            "offset": offset,
            "client_errors": errors,
            "clients": [{"id": p.id, "name": p.name} for p in profiles],
            "trackers": sorted({tracker_group(h) for r in all_rows for h in r["trackers"] if h}),
            "categories": sorted({" / ".join(c) for r in all_rows for c in r["categories"] if c}),
            "tags": sorted({t for r in all_rows for t in r["tags"]}),
            "summary": {
                "count": len(all_rows),
                "download": sum(r["download"] for r in all_rows),
                "upload": sum(r["upload"] for r in all_rows),
            },
            "observed_at": min(
                (self.observed_at[i] for i in identifiers if i in self.observed_at), default=None
            ),
        }

    @staticmethod
    def capabilities(client):
        actions = ["pause", "resume", "recheck", "remove", "delete", "skip_files", "want_files"]
        return actions + list(getattr(client, "management_controls", ()))

    def action(self, operation, body):
        payload = body.model_dump_json(exclude={"token"})
        identities, rows = [], []
        for item in body.items:
            target = self.target(item.client_id)
            identities.append(str(target.setup.snapshot()))
            torrent = target.setup.client().torrent(item.hash, with_files=False)
            if torrent is None:
                raise ValueError("A selected torrent no longer exists. Refresh the list.")
            if body.action not in self.capabilities(target.setup.client()):
                raise ValueError("This operation is not supported by this Torrent Client.")
            rows.append(
                {
                    "client_id": item.client_id,
                    "hash": item.hash,
                    "name": torrent.name,
                    "client_name": target.setup.settings.profile().name,
                    "folder": str(torrent.save_path),
                }
            )
            if body.action.endswith("_files"):
                listing = target.setup.client().file_listing(item.hash)
                indexes = {f.index for f in listing}
                if not body.file_indexes or not set(body.file_indexes) <= indexes:
                    raise ValueError("Choose existing file indexes.")
                rows[-1]["files"] = [asdict(f) for f in listing if f.index in body.file_indexes]
        identity = (payload, identities, rows)
        if operation == "review":
            now = time.monotonic()
            self.pending = {k: v for k, v in self.pending.items() if v[0] > now}
            if len(self.pending) >= 100:
                self.pending.clear()
            token = secrets.token_urlsafe(32)
            self.pending[token] = (now + 300, identity)
            return {"token": token, "rows": rows}
        record = self.pending.pop(body.token, None)
        if record is None or record[0] < time.monotonic() or record[1] != identity:
            raise ValueError("Review and confirm this exact action first.")
        results, seen = [], set()
        for item in body.items:
            key = (item.client_id, item.hash)
            if key in seen:
                continue
            seen.add(key)
            target = self.target(item.client_id)
            client = target.setup.client()
            if body.action in {"reannounce", "limits", "category", "location"}:
                # Share the existing Reseed setup lock; never relocate or relabel protected links.
                from torrentlinker import reseed

                try:
                    with reseed._LOCK:
                        torrent = client.torrent(item.hash, with_files=False)
                        if torrent is None or any(
                            t.startswith("torrentlinker:link") or t == reseed.VERIFYING
                            for t in torrent.tags
                        ):
                            raise ValueError(
                                "Protected or missing torrent. Use its Reseed workflow."
                            )
                        client.manage_control(item.hash, body.action, body.model_dump())
                    result = {"hash": item.hash, "outcome": "sent", "detail": ""}
                except Exception as error:
                    result = {"hash": item.hash, "outcome": "failed", "detail": safe_error(error)}
            else:
                if body.action.endswith("_files"):
                    indexes = {f.index for f in client.file_listing(item.hash)}
                    if not body.file_indexes or not set(body.file_indexes) <= indexes:
                        raise ValueError("Choose existing file indexes.")
                result = asdict(
                    manage(client, [item.hash], body.action, file_indexes=body.file_indexes)[0]
                )
            results.append({**result, "client_id": item.client_id})
            self.updated.pop(item.client_id, None)
        return {"rows": results}
