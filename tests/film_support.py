"""Seed the Tracker Film index directly, so a test reads no Catalogue, TMDb or tracker."""

import json


def seed_index(media, films, releases):
    """`films`: tmdb -> (title, original title, year, genres, rating, runtime);
    `releases`: (tracker, hash, name, size, seeders, tmdb), an empty tmdb being unidentified."""
    with media.lock, media.db:
        for tmdb, (title, original, year, genres, rating, runtime) in films.items():
            media.db.execute(
                "INSERT INTO film_meta (tmdb, title, original_title, year, overview, genres,"
                " runtime, rating, poster) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    tmdb,
                    title,
                    original,
                    year,
                    f"Synopsis de {title}.",
                    json.dumps(genres, ensure_ascii=False),
                    runtime,
                    rating,
                    f"https://image.tmdb.org/t/p/w500/{tmdb}.jpg",
                ),
            )
        for position, (site, infohash, name, size, seeders, tmdb) in enumerate(releases):
            media.db.execute(
                "INSERT INTO film_release (tracker, infohash, name, size, seeders, category,"
                " published, position, tkey, title, year, manual)"
                " VALUES (?,?,?,?,?,2030,?,?,?,?,?,?)",
                (
                    site,
                    infohash,
                    name,
                    size,
                    seeders,
                    1e9 + position,
                    position,
                    "" if not tmdb else f'["{name[:4]}", "{films[tmdb][2]}"]',
                    name.split(".")[0],
                    films[tmdb][2] if tmdb else "",
                    tmdb,
                ),
            )
    media._films_changed()
