"""Disques proposes moving films from a disk under the 10 % margin to one with room (#210).

A proposal is a preview: the Owner ticks films and accepting queues their moves in Tâches, where
a seeded film moves through its Torrent Client (ADR-0029).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from torrentlinker.disk_report import _under, tree_size
from torrentlinker.file_annotations import seeds_under

SPEED = 150e6  # bytes per second of a disk-to-disk copy, for the estimate


def proposal(
    cards: list[dict[str, Any]],
    library: list[Path],
    films_of: Callable[[Path], list[dict[str, Any]]],
    seeds: list[tuple[Path, dict[str, Any]]],
) -> dict[str, Any]:
    """The films to move, per disk below the margin, and where they would go.

    `films_of(folder)` lists Médias' films under a Library Folder: {id, path, title}."""
    live = [c for c in cards if "error" not in c and c["writable"]]
    short = [c for c in live if c["below_margin"]]
    if not short:
        return {"state": "balanced", "sources": []}
    roomy = [c for c in live if not c["below_margin"]]
    if not roomy:
        return {"state": "no-room", "sources": []}
    target = max(roomy, key=lambda c: c["usable"])
    folders = [f for f in library if _under(f, [Path(r) for r in target["roots"]])]
    if not folders:
        return {"state": "no-folder", "target": _card(target), "sources": []}
    sources = []
    for card in short:
        roots = [Path(r) for r in card["roots"]]
        found: dict[str, dict[str, Any]] = {}
        for folder in (f for f in library if _under(f, roots)):
            for film in films_of(folder):
                top = folder / Path(film["path"]).relative_to(folder).parts[0]
                entry = found.setdefault(
                    str(top),
                    {"path": str(top), "name": top.name, "title": film["title"], "id": film["id"],
                     "folder": str(folder), "size": tree_size(top)[0]},
                )  # fmt: skip
                seed = seeds_under(top, seeds)
                if seed and "seed" not in entry:
                    entry["seed"] = {"client": seed[0][1]["client"], "ratio": seed[0][1]["ratio"]}
        films = sorted(found.values(), key=lambda f: -f["size"])
        sources.append({"disk": _card(card), "films": films})
    return {
        "state": "proposal", "target": {**_card(target), "folder": str(folders[0])},
        "sources": sources, "speed": SPEED,
    }  # fmt: skip


def _card(card: dict[str, Any]) -> dict[str, Any]:
    return {k: card[k] for k in ("id", "name", "free", "margin", "usable")}


def destination(proposed: dict[str, Any], paths: list[str]) -> tuple[str, list[str]]:
    """The folder to move to and the chosen paths that are really part of the proposal."""
    allowed = {f["path"] for s in proposed.get("sources", []) for f in s["films"]}
    return proposed["target"]["folder"], [p for p in paths if p in allowed]
