"""Saved objectives and measured progress; never change a user's c411 Class."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from torrentlinker.seeding import combined_seeding
from torrentlinker.zen import ZenClass

if TYPE_CHECKING:
    from torrentlinker.agent.service import AgentService


class Goal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    client_ids: list[str] = Field(min_length=1, max_length=32)
    target_daily_zen: float = Field(default=0, ge=0, le=1_000_000, allow_inf_nan=False)
    target_balance: float | None = Field(default=None, ge=0, le=1_000_000, allow_inf_nan=False)
    desired_class: ZenClass | None = None
    maximum_bytes: int = Field(default=10 * 1024**3, ge=0)
    maximum_torrents: int = Field(default=20, ge=1, le=1000)
    category: int | None = Field(
        default=None,
        gt=0,
        description="Torznab Catalogue category ID from catalogue_categories, not an Upload "
        "or native search category ID. Omit for all categories.",
    )
    prefer_existing_files: bool = True


def save(service: AgentService, actor: str, identifier: str, revision: int, goal: Goal) -> dict:
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", identifier):
        raise ValueError("Use a goal ID with letters, numbers, underscores or hyphens.")
    for client_id in goal.client_ids:
        service.target(actor, client_id)
    key = actor + ":" + identifier
    with service.access.lock, service.access.db:
        row = service.access.db.execute("SELECT revision FROM goals WHERE id=?", (key,)).fetchone()
        if revision != (row[0] if row else 0):
            raise ValueError("The goal changed. Read its current revision before editing.")
        service.access.db.execute(
            "INSERT OR REPLACE INTO goals VALUES (?,?,?,?)",
            (key, actor, goal.model_dump_json(), revision + 1),
        )
        service.access.event(actor, "goal_saved", identifier)
    return {"id": identifier, "revision": revision + 1, **goal.model_dump(mode="json")}


def status(service: AgentService, actor: str, identifier: str) -> dict:
    service.access.grant(actor)
    with service.access.lock:
        row = service.access.db.execute(
            "SELECT * FROM goals WHERE id=? AND grant_id=?", (actor + ":" + identifier, actor)
        ).fetchone()
    if row is None:
        raise ValueError("Goal not found.")
    goal = Goal.model_validate_json(row["body"])
    targets = [service.target(actor, client_id) for client_id in goal.client_ids]
    torrents = [t for target in targets for t in target.observed]
    current = combined_seeding(
        service.setup.settings.zen,
        torrents,
        service.setup.settings.indexer.url,
        catalogue={
            r.infohash: r for r in service.setup.store.catalogue([t.hash.lower() for t in torrents])
        },
    )
    complete = all(target.zen and not target.connection_error for target in targets)
    daily = current.day.total if complete else None
    return {
        "id": identifier,
        "revision": row["revision"],
        **goal.model_dump(mode="json"),
        "actual_class": service.setup.settings.zen.zen_class,
        "daily_zen": daily,
        "remaining_daily_zen": max(0, goal.target_daily_zen - daily) if daily is not None else None,
        "balance": None,
        "provisional": True,
        "notes": "Refresh each selected client before assessing progress. Income is an "
        "estimate; balances, revival payouts and upload rewards are not inferred. "
        "The desired Class does not change the c411 account. Check existing Library "
        "matches before proposing new downloads.",
    }
