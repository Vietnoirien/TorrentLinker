"""What Explorateur knows about the entries of a folder: the film they hold and the torrent
that seeds them (ADR-0029, #207, #208)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from torrentlinker.media import VIDEO


def seeds_of(torrents: list[tuple[str, str, Any]]) -> list[tuple[Path, dict[str, Any]]]:
    """The content each torrent puts on disk (a file, or a folder), with who seeds it.

    `torrents` holds (client id, client name, Torrent)."""
    found: dict[Path, dict[str, Any]] = {}
    for client_id, client_name, torrent in torrents:
        for top in {Path(torrent.save_path) / Path(name).parts[0] for name in torrent.files}:
            found.setdefault(
                top,
                {
                    "client": client_name, "client_id": client_id, "hash": torrent.hash.lower(),
                    "ratio": round(torrent.ratio, 2), "name": torrent.name,
                    "save_path": str(torrent.save_path),
                    "seeding": torrent.is_seeding, "verifying": "check" in torrent.state.lower(),
                },
            )  # fmt: skip
    return list(found.items())


def seeds_under(
    path: Path, seeds: list[tuple[Path, dict[str, Any]]]
) -> list[tuple[Path, dict[str, Any]]]:
    """The torrents whose content is the path, inside it or holds it."""
    return [(top, info) for top, info in seeds if _related(path, top)]


def _related(entry: Path, other: Path) -> bool:
    return entry == other or entry.is_relative_to(other) or other.is_relative_to(entry)


def annotate(
    folder: Path,
    entries: list[dict[str, Any]],
    films: list[dict[str, Any]],
    seeds: list[tuple[Path, dict[str, Any]]],
) -> None:
    """Add `seed` (the torrent using the entry) and `film` (title, Médias id) to each entry.

    `films` holds Médias' video items under the folder: {id, path, title}."""
    for entry in entries:
        path = folder / entry["name"]
        seed = next((info for top, info in seeds if _related(path, top)), None)
        if seed is not None:
            entry["seed"] = seed
        inside = [f for f in films if Path(f["path"]).is_relative_to(path)]
        if inside and (not entry["dir"] or len(inside) == 1 or _one_film(inside)):
            entry["film"] = {"id": inside[0]["id"], "title": inside[0]["title"]}
        elif len(inside) > 1:
            entry["films"] = len(inside)


def _one_film(items: list[dict[str, Any]]) -> bool:
    """Several files of one film (the film and its extras) are still one film."""
    return len({f["title"] for f in items}) == 1


def media_films(media: Any, client_id: str, folder: Path) -> list[dict[str, Any]]:
    """The films Médias lists under a folder, read without parsing every item."""
    prefix = str(folder.absolute()).rstrip("/") + "/"
    escaped = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    with media.lock:
        rows = media.db.execute(
            "SELECT id, path, json_extract(body, '$.title') AS title FROM media_items"
            " WHERE client=? AND path LIKE ? ESCAPE '\\'"
            " AND json_extract(body, '$.kind')='video' AND json_extract(body, '$.series') IS NULL",
            (client_id, escaped + "%"),
        ).fetchall()
    return [
        {"id": r["id"], "path": r["path"], "title": r["title"] or ""}
        for r in rows
        if Path(r["path"]).suffix.lower() in VIDEO
    ]
