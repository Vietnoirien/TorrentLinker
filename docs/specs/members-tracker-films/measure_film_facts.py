"""Measure the film facts an instance has gathered, to decide whether and how to share them.

    docker exec -i torrentlinker python - < docs/specs/members-tracker-films/measure_film_facts.py

Read-only. "Film facts only" (owner, 2026-11-26): what would be shared is keyed by film
(title + year, or TMDB id), with no release names or infohashes, so only those columns are
counted in the size estimate.
"""

import json
import lzma
import sqlite3

db = sqlite3.connect("file:/config/media.sqlite?mode=ro", uri=True)
one = lambda sql: db.execute(sql).fetchone()[0]  # noqa: E731

titles = one("SELECT COUNT(DISTINCT tkey) FROM film_release WHERE tkey <> ''")
c411 = one("SELECT COUNT(*) FROM film_c411")
tmdb = one("SELECT COUNT(*) FROM film_meta")
facts = [
    {"key": r[0], "title": r[1], "original_title": r[2], "year": r[3], "overview": r[4], "genres": r[5], "runtime": r[6], "poster": r[7]}
    for r in db.execute("SELECT tkey, title, original_title, year, overview, genres, runtime, poster FROM film_c411")
]
facts += [
    {"key": r[0], "title": r[1], "original_title": r[2], "year": r[3], "overview": r[4], "genres": r[5], "runtime": r[6], "poster": r[7], "rating": r[8]}
    for r in db.execute("SELECT tmdb, title, original_title, year, overview, genres, runtime, poster, rating FROM film_meta")
]
covered = lambda field: sum(1 for f in facts if f.get(field) not in (None, "", "[]", 0))  # noqa: E731
raw = json.dumps(facts, ensure_ascii=False).encode()
print(f"film titles in the index : {titles:,}")
print(f"with c411 facts          : {c411:,}")
print(f"with TMDB facts          : {tmdb:,}")
print(f"share of titles covered  : {(c411 + tmdb) / titles:.1%}" if titles else "no titles yet")
for field in ("poster", "overview", "genres", "runtime", "original_title"):
    print(f"  {field:<15}: {covered(field):,}")
print(f"size as JSON             : {len(raw) / 1e6:.1f} MB")
print(f"size xz-compressed       : {len(lzma.compress(raw, preset=6)) / 1e6:.1f} MB")
walk = db.execute("SELECT body FROM media_options WHERE key LIKE 'films-c411%'").fetchall()
print("c411 walk state          :", [w[0][:120] for w in walk])
