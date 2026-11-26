"""Read the preview's data from a running instance's /config, read-only. Run inside the container:

    docker exec -i torrentlinker python - < docs/specs/members-tracker-films/extract_fixtures.py > raw.json

It prints the tracker suggestions (titles, years, genres, synopses, runtimes, releases) and the
library's films with artwork, and names the poster files to copy. Nothing is written.
"""

import json
import sqlite3

db = sqlite3.connect("file:/config/media.sqlite?mode=ro", uri=True)

tracker = []
for key, body in db.execute(
    "SELECT key, body FROM media_options WHERE key LIKE 'tracker-new:%' OR key LIKE 'tracker-upgrade:%'"
):
    entry = json.loads(body)
    facts = entry.get("facts") or {}
    releases = [
        {k: r.get(k) for k in ("hash", "name", "size", "seeders", "category", "published_at", "tracker")}
        for r in entry.get("releases") or []
    ]
    tracker.append(
        {
            "kind": key.split(":", 1)[0],
            "key": key.split(":", 2)[2],
            "title": facts.get("title") or entry.get("title"),
            "original_title": facts.get("original_title") or "",
            "year": str(facts.get("year") or entry.get("year") or ""),
            "rating": facts.get("rating"),
            "genres": facts.get("genres") or [],
            "overview": facts.get("overview") or "",
            "runtime": facts.get("runtime") or 0,
            "cast": (facts.get("cast") or [])[:4],
            "directors": facts.get("directors") or [],
            "language": facts.get("language") or "",
            "uploader": facts.get("uploader") or "",
            "poster_url": facts.get("poster_url") or "",
            "artwork": entry.get("artwork") or "",
            "releases": releases,
        }
    )

library = []
for item_id, added, body in db.execute(
    "SELECT id, added, body FROM media_items WHERE client='default' AND c_kind='video' "
    "AND json_extract(body,'$.artwork')<>'' ORDER BY added DESC"
):
    b = json.loads(body)
    library.append(
        {
            "id": item_id,
            "added": added,
            **{
                k: b.get(k)
                for k in ("title", "year", "genre", "description", "duration", "artwork", "series", "season", "episode", "content_id", "language", "certification", "release")
            },
        }
    )

print(json.dumps({"tracker": tracker, "library": library}, ensure_ascii=False))
