"""What Médias shows of the Tracker Series index (ADR-0030, #215, #218, #219).

The Séries tab gets a "Sur le tracker" row and a "Tout voir" page by genre, the Anime tab the same
for anime series. A series panel lists its seasons (a full pack, episodes only, covered by an
Intégrale, or none) and their episodes. A Member never sees a release; the Owner sees every one.
A series fully in the Library is hidden from Members, a partly owned one stays with its owned
seasons marked, and the Age Rating rule is the films': a series without a rating stays hidden
under a limit.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from torrentlinker import age_ratings
from torrentlinker.media_tracker import plain

PAGE = 60


def owned_seasons(media: Any, client_id: str) -> dict[str, set[int]]:
    """The seasons each series has in the Library, by TMDb id and by plain title."""
    with media.lock:
        rows = media.db.execute(
            "SELECT body FROM media_items WHERE client=? AND json_extract(body, '$.series') <> ''"
            " AND json_extract(body, '$.kind')='video'",
            (client_id,),
        ).fetchall()
    found: dict[str, set[int]] = {}
    for (text,) in rows:
        body = json.loads(text)
        season = body.get("season")
        for key in (
            f"tmdb:{body.get('tmdb_id')}" if body.get("tmdb_id") else "",
            plain(body["series"]),
        ):
            if key:
                found.setdefault(key, set()).add(int(season) if str(season).isdigit() else 1)
    return found


def _owned(entry: dict[str, Any], library: dict[str, set[int]]) -> set[int]:
    return library.get(f"tmdb:{entry['tmdb']}", set()) | library.get(plain(entry["title"]), set())


def _seasons(media: Any, tmdb: str) -> dict[int, dict[str, Any]]:
    if not tmdb:
        return {}
    with media.lock:
        seasons = media.db.execute(
            "SELECT season, name, episodes FROM series_season WHERE tmdb=? AND season>0", (tmdb,)
        ).fetchall()
        episodes = media.db.execute(
            "SELECT season, episode, title, overview FROM series_episode WHERE tmdb=?", (tmdb,)
        ).fetchall()
    found = {
        r["season"]: {"n": r["season"], "name": r["name"], "count": r["episodes"], "episodes": {}}
        for r in seasons
    }
    for r in episodes:
        if r["season"] in found:
            found[r["season"]]["episodes"][r["episode"]] = {
                "title": r["title"],
                "overview": r["overview"],
            }
    return found


def _card(entry: dict[str, Any], owned: set[int], seasons: int) -> dict[str, Any]:
    meta = entry["meta"] or {}
    return {
        "id": "tseries-" + entry["id"], "kind": "video", "tseries": entry["id"],
        "title": entry["title"], "year": meta.get("year") or "",
        "age_rating": {"rating": meta["rating"], "source": "tmdb", "by": "", "suggestion": None}
        if meta.get("rating") else None,
        "genre": ", ".join(json.loads(meta["genres"])) if meta.get("genres") else "",
        "description": meta.get("overview") or "", "duration": 0,
        "artwork_url": "tracker" if meta.get("poster") else "", "available": True,
        "identified": bool(entry["tmdb"]), "in_library": bool(seasons) and len(owned) >= seasons,
        "owned_seasons": sorted(owned), "series_kind": entry["kind"],
    }  # fmt: skip


def may_see(entry: dict[str, Any], owned: set[int], seasons: int, actor: Any) -> bool:
    if actor.owner:
        return True
    if not entry["tmdb"] or (seasons and len(owned) >= seasons):
        return False  # unidentified, or fully in the Library
    rank = age_ratings.rank((entry["meta"] or {}).get("rating"))
    return actor.age_limit is None or (rank is not None and rank <= actor.age_limit)


def catalogue(media: Any, client_id: str, actor: Any, scope: str) -> list[dict[str, Any]]:
    """The series cards the actor sees in one tab: `series` (documentaries included) or `anime`."""
    library = owned_seasons(media, client_id)
    cards = []
    for entry in media.series_index():
        if (entry["kind"] == "anime") != (scope == "anime"):
            continue
        owned = _owned(entry, library)
        count = len(_seasons(media, entry["tmdb"])) if entry["tmdb"] else 0
        if may_see(entry, owned, count, actor):
            cards.append({**_card(entry, owned, count), "_seeders": _seeders(entry),
                          "_published": 0})  # fmt: skip
    return cards


def _seeders(entry: dict[str, Any]) -> int:
    return max((r["seeders"] for r in entry["releases"]), default=0)


SORTS: dict[str, Callable[[dict[str, Any]], Any]] = {
    "new": lambda c: (-c["_published"], plain(c["title"])),
    "shared": lambda c: (-c["_seeders"], plain(c["title"])),
    "year": lambda c: (-int(c["year"] or 0), plain(c["title"])),
    "title": lambda c: plain(c["title"]),
}


def _public(card: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in card.items() if not k.startswith("_")}


def grid(
    cards: list[dict[str, Any]], genres: list[str], sort: str, q: str, offset: int, limit: int
) -> dict[str, Any]:
    wanted = {plain(g) for g in genres}
    needle = plain(q)
    found = [
        c for c in cards
        if (not wanted or wanted <= {plain(g) for g in c["genre"].split(", ")})
        and (not needle or needle in plain(c["title"]))
    ]  # fmt: skip
    found.sort(key=SORTS.get(sort, SORTS["new"]))
    return {"rows": [_public(c) for c in found[offset : offset + limit]], "total": len(found)}


def landing(cards: list[dict[str, Any]], limit: int = 20) -> dict[str, Any]:
    """The row on the tab ("Sur le tracker") and one row per genre for the "Tout voir" page."""
    rows = []
    first = grid(cards, [], "shared", "", 0, limit)
    if first["rows"]:
        rows.append({"key": "tracker", "title": "", "filters": {"tracker": "series"}, **first})
    genres: dict[str, int] = {}
    for card in cards:
        for genre in filter(None, card["genre"].split(", ")):
            genres[genre] = genres.get(genre, 0) + 1
    for genre in sorted(genres, key=lambda g: (-genres[g], g)):
        page = grid(cards, [genre], "shared", "", 0, limit)
        rows.append(
            {
                "key": "genre",
                "title": genre,
                "filters": {"tracker": "series", "genre": genre},
                **page,
            }
        )
    return {"rows": rows}


def detail(media: Any, client_id: str, identifier: str, actor: Any) -> dict[str, Any]:
    """The series panel: its seasons, with what the Trackers hold and what the Library has.
    The Owner also gets the releases of each season and episode."""
    from torrentlinker.tracker_series import coverage

    entry = next((e for e in media.series_index() if e["id"] == identifier), None)
    if entry is None:
        raise KeyError(identifier)
    library = owned_seasons(media, client_id)
    owned = _owned(entry, library)
    seasons = _seasons(media, entry["tmdb"])
    if not may_see(entry, owned, len(seasons), actor):
        raise KeyError(identifier)
    cover = coverage(
        entry["releases"], {n: s["count"] for n, s in seasons.items()},
        {n: set(s["episodes"]) for n, s in seasons.items()},
    )  # fmt: skip
    out = []
    for n, season in sorted(seasons.items()):
        held = cover.get(n, {"state": "none", "episodes": set()})
        on_tracker = (
            set(season["episodes"]) if held["state"] in {"pack", "complete"} else held["episodes"]
        )
        row = {
            "n": n, "name": season["name"], "count": season["count"], "state": held["state"],
            "owned": n in owned,
            # A Member asks for a season with a full pack (or an Intégrale), never for episodes.
            "askable": n not in owned and held["state"] in {"pack", "complete"},
            "episodes": [
                {"n": e, "title": v["title"], "overview": v["overview"],
                 "on_tracker": e in on_tracker}
                for e, v in sorted(season["episodes"].items())
            ],
        }  # fmt: skip
        if actor.owner:
            row["releases"] = _releases(entry, n)
        out.append(row)
    return {
        **_card(entry, owned, len(seasons)),
        "seasons": out,
        "status": (entry["meta"] or {}).get("status") or "",
    }


def _releases(entry: dict[str, Any], season: int) -> list[dict[str, Any]]:
    """The Owner's view of a season: its packs, the Intégrales that cover it and its episodes."""
    found = []
    for r in entry["releases"]:
        pack = r["pack"]
        if pack == "season" and season in r["seasons"]:
            kind = "season"
        elif pack == "complete" and (not r["seasons"] or season in r["seasons"]):
            kind = "integrale"
        elif pack == "episode" and r["season"] == season:
            kind = "episode"
        else:
            continue
        found.append(
            {"hash": r["infohash"], "name": r["name"], "size": r["size"], "seeders": r["seeders"],
             "tracker": r["tracker"], "kind": kind, "episode": r["episode"]}
        )  # fmt: skip
    return sorted(found, key=lambda x: (x["kind"], x["episode"], -x["seeders"]))
