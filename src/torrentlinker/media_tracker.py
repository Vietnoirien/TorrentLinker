"""Media's tracker rows: films on c411 whose best release scores well.

Two rows, films only. "Available" lists films the library does not have; "Upgrades" lists
library films with a release that scores clearly better than the file on disk. ReleaseScore
needs a film's runtime, which the Catalogue does not keep, so each film costs one c411
listing request. A refresh looks up a few films in the background and caches the answers;
the rows are drawn from that cache.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict
from typing import Any

from guessit import guessit

LOOKUPS_PER_RUN = 20
RUN_INTERVAL = 600  # seconds between two refreshes of the same client
RECHECK = 7 * 86400  # a film's releases are looked up again after a week
UPGRADE_MARGIN = 5  # an upgrade scores at least this much more than the file on disk
ROW_LIMIT = 60
KEYS = ("tracker", "upgrades")


def plain(value: Any) -> str:
    """A title compared without case, accents or punctuation."""
    import re
    import unicodedata

    value = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def film_key(title: str, year: str) -> str:
    return json.dumps([plain(title), str(year or "")])


class TrackerRows:
    """Mixed into MediaLibrary, which provides db, lock, agent, identity and setup()."""

    db: Any
    lock: Any
    _tracker_films: dict[str, tuple[float, list[dict[str, Any]]]]

    # -- What the library holds -------------------------------------------------------------

    def _library_films(self, client_id) -> dict[str, dict[str, Any]]:
        """Library films by title and year, with the best scored file of each."""
        with self.lock:
            rows = self.db.execute(
                "SELECT id, path, size, body FROM media_items WHERE client=?", (client_id,)
            ).fetchall()
        films: dict[str, dict[str, Any]] = {}
        for row in rows:
            body = json.loads(row["body"])
            if body.get("kind") != "video" or body.get("series") or body.get("anime"):
                continue
            title, year = (body.get("title") or "").strip(), str(body.get("year") or "")
            if not title:
                continue
            key = film_key(title, year)
            films.setdefault(key, {"title": title, "year": year, "files": []})["files"].append(
                {"id": row["id"], "name": row["path"].rsplit("/", 1)[-1], "size": row["size"]}
            )
        return films

    def _catalogue_candidates(self, setup, owned: set[str]) -> list[dict[str, Any]]:
        """Well seeded Catalogue films the library does not hold, once guessed per hour."""
        cache = getattr(self, "_tracker_films", None)
        if cache is None:
            cache = self._tracker_films = {}
        client = setup.settings.active_client_id
        known = cache.get(client)
        if known and time.time() - known[0] < 3600:
            films = known[1]
        else:
            seen: dict[str, dict[str, Any]] = {}
            for row in setup.store.catalogue_films():
                guessed = guessit(row.title, {"type": "movie"})
                title, year = guessed.get("title"), guessed.get("year")
                if not isinstance(title, str) or not year or guessed.get("type") != "movie":
                    continue
                key = film_key(title, str(year))
                if key not in seen:
                    seen[key] = {"title": title, "year": str(year), "seeders": row.seeders}
            films = sorted(seen.values(), key=lambda film: -film["seeders"])
            cache[client] = (time.time(), films)
        return [f for f in films if film_key(f["title"], f["year"]) not in owned]

    # -- Looking films up on c411 -----------------------------------------------------------

    def _tracker_lookup(self, setup, indexer, title: str, year: str) -> dict[str, Any]:
        """One listing request: the film's facts and its best scored release."""
        from torrentlinker.release_score.estimate import estimate
        from torrentlinker.release_score.service import score
        from torrentlinker.torrent_search import native_search

        params = {"name": title, "category": "1"}
        if year:
            params["year"] = year
        page = native_search(indexer, params)
        wanted = plain(title)
        best: dict[str, Any] | None = None
        facts: dict[str, Any] = {}
        for candidate in page.rows:
            listing = page.details.get(candidate.infohash or "")
            if listing is None or listing.kind not in ("movie", ""):
                continue
            guessed = guessit(candidate.title, {"type": "movie"})
            if (
                plain(guessed.get("title") or listing.title) != wanted
                and plain(listing.title) != wanted
            ):
                continue
            if year and str(listing.year or guessed.get("year") or "") not in {"", year}:
                continue
            details = asdict(listing)
            result = score(
                estimate(candidate.title, candidate.size, details), setup.settings.release_score
            )
            facts = facts or details
            if result.get("score") is None:
                continue
            release = {
                "hash": candidate.infohash,
                "name": candidate.title,
                "size": candidate.size,
                "seeders": candidate.seeders,
                "category": candidate.categories[0] if candidate.categories else None,
                "score": result["score"],
                "color": result.get("color", ""),
                "published_at": candidate.published_at,
            }
            if best is None or (release["score"], release["seeders"]) > (
                best["score"],
                best["seeders"],
            ):
                best, facts = release, details
        return {"at": time.time(), "best": best, "facts": facts}

    def tracker_refresh(self, client_id, setup, stop: threading.Event) -> str:
        """Look a few films up, library films first; the rest wait for the next refresh."""
        from torrentlinker.indexer import KeyRefused, RateLimited

        gate = "tracker-run:" + client_id
        with self.lock:
            saved = self.db.execute(
                "SELECT body FROM media_options WHERE key=?", (gate,)
            ).fetchone()
        if saved and time.time() - json.loads(saved[0]) < RUN_INTERVAL:
            return "waiting"
        try:
            indexer = setup.indexer()
        except Exception:
            return "off"
        if not indexer.is_c411:
            return "off"
        with self.lock, self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO media_options VALUES (?,?)", (gate, json.dumps(time.time()))
            )
        library = self._library_films(client_id)
        cached = self._tracker_cache(client_id)
        due = [
            (key, film)
            for key, film in [
                *library.items(),
                *(
                    (film_key(f["title"], f["year"]), f)
                    for f in self._catalogue_candidates(setup, set(library))
                ),
            ]
            if time.time() - cached.get(key, {}).get("at", 0) > RECHECK
        ][:LOOKUPS_PER_RUN]
        status = "complete"
        with indexer.background(stop):
            for key, film in due:
                if stop.is_set():
                    return "cancelled"
                try:
                    found = self._tracker_lookup(setup, indexer, film["title"], film["year"])
                except (RateLimited, KeyRefused):
                    return "limit"
                except Exception:
                    status = "partial"
                    continue
                found.update(title=film["title"], year=film["year"])
                with self.lock, self.db:
                    self.db.execute(
                        "INSERT OR REPLACE INTO media_options VALUES (?,?)",
                        (f"tracker:{client_id}:{key}", json.dumps(found)),
                    )
        return status

    def _tracker_cache(self, client_id) -> dict[str, dict[str, Any]]:
        prefix = f"tracker:{client_id}:"
        with self.lock:
            rows = self.db.execute(
                "SELECT key, body FROM media_options WHERE key LIKE ?", (prefix + "%",)
            ).fetchall()
        return {row[0][len(prefix) :]: json.loads(row[1]) for row in rows}

    # -- Rows -------------------------------------------------------------------------------

    def tracker_rows(self, client_id, setup) -> list[dict[str, Any]]:
        """The two rows, drawn from cached lookups only."""
        from torrentlinker.release_score.estimate import estimate
        from torrentlinker.release_score.preferences import Preferences
        from torrentlinker.release_score.service import score

        preferences = setup.settings.release_score
        threshold = Preferences.model_validate(preferences).threshold
        library = self._library_films(client_id)
        available, upgrades = [], []
        for key, entry in self._tracker_cache(client_id).items():
            best = entry.get("best")
            if not best or best["score"] < threshold:
                continue
            item = self._tracker_item(entry)
            film = library.get(key)
            if film is None:
                available.append(item)
                continue
            # The file on disk, scored with the same film facts.
            facts = entry.get("facts") or {}
            own = max(
                (
                    score(estimate(f["name"], f["size"], facts), preferences).get("score") or 0
                    for f in film["files"]
                ),
                default=0,
            )
            if best["score"] >= own + UPGRADE_MARGIN:
                item["tracker"]["own_score"] = own
                item["tracker"]["library_id"] = film["files"][0]["id"]
                upgrades.append(item)
        rows = []
        for key, items in (("tracker", available), ("upgrades", upgrades)):
            items.sort(key=lambda i: (-i["tracker"]["score"], -i["tracker"]["seeders"]))
            if items:
                rows.append(
                    {
                        "key": key,
                        "title": "",
                        "filters": {"tracker": key},
                        "total": min(len(items), ROW_LIMIT),
                        "rows": items[:ROW_LIMIT],
                    }
                )
        return rows

    @staticmethod
    def _tracker_item(entry: dict[str, Any]) -> dict[str, Any]:
        facts, best = entry.get("facts") or {}, entry["best"]
        return {
            "id": "tracker-" + best["hash"],
            "kind": "video",
            "title": facts.get("title") or entry.get("title") or best["name"],
            "year": str(facts.get("year") or entry.get("year") or ""),
            "rating": facts.get("rating"),
            "genre": ", ".join(facts.get("genres") or []),
            "description": facts.get("overview") or "",
            "duration": (facts.get("runtime") or 0) * 60,
            "artwork_url": "tracker" if facts.get("poster_url") else "",
            "available": True,
            "tracker": {
                "hash": best["hash"],
                "name": best["name"],
                "size": best["size"],
                "seeders": best["seeders"],
                "score": best["score"],
                "color": best.get("color", ""),
                "published_at": best.get("published_at"),
            },
        }

    def tracker_entry(self, client_id, infohash: str) -> dict[str, Any]:
        for entry in self._tracker_cache(client_id).values():
            if (entry.get("best") or {}).get("hash") == infohash:
                return entry
        raise ValueError("This tracker release is no longer suggested.")

    def tracker_artwork(self, client_id, infohash: str):
        """The film's poster, downloaded once like library artwork."""
        entry = self.tracker_entry(client_id, infohash)
        poster = (entry.get("facts") or {}).get("poster_url") or ""
        if not poster.startswith("https://image.tmdb.org/"):
            return None
        if not entry.get("artwork"):
            from torrentlinker.assistant.images import fetch_image

            data, _ = fetch_image(poster)
            entry["artwork"] = self.cache_artwork(data)  # type: ignore[attr-defined]
            key = film_key(entry.get("title") or "", entry.get("year") or "")
            with self.lock, self.db:
                self.db.execute(
                    "INSERT OR REPLACE INTO media_options VALUES (?,?)",
                    (f"tracker:{client_id}:{key}", json.dumps(entry)),
                )
        image = entry["artwork"]
        if not image.startswith("asset:"):
            return None
        return self.agent.setup.path.parent / "media-artwork" / image[6:]  # type: ignore[attr-defined]

    def tracker_enqueue(self, client_id, setup, infohash: str) -> dict[str, Any]:
        """Queue the suggested release, as Search does; nothing starts until the queue is sent."""
        from torrentlinker.catalogue_sync import download_url
        from torrentlinker.download_queue import enqueue
        from torrentlinker.indexer import Candidate

        best = self.tracker_entry(client_id, infohash)["best"]
        category = best.get("category")
        if setup.download_folder(category) is None:
            raise ValueError(
                "Choose a Download Folder for this category in Settings before queueing."
            )
        indexer = setup.indexer()
        candidate = Candidate(
            best["name"],
            best["size"],
            indexer.unredact(download_url(infohash)),
            best["seeders"],
            infohash,
            f"https://c411.org/torrents/{infohash}",
            categories=(category,) if category is not None else (),
        )
        added = enqueue(setup.store, indexer, candidate, setup.verified_download_folder(category))
        return {"queued": bool(added), "title": best["name"]}
