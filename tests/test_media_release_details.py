"""Film details come from c411 release descriptions and never fail a library refresh."""

import json
import threading
import types

from torrentlinker.indexer import RateLimited
from torrentlinker.media import MediaLibrary
from torrentlinker.store import CatalogueRow

DEBORAH = "9cd37233a21399a4bac244d146010dbfd4de4c01"
SPECTRAL = "a" * 40


class Catalogue:
    rows = [
        CatalogueRow(
            DEBORAH, "The.Taking.of.Deborah.Logan.2014.MULTI.1080p.BluRay", 1, 9, 2030, "", "", 0.0
        ),
        CatalogueRow(SPECTRAL, "Spectral.2016.MULTI.1080p.WEB", 1, 3, 2030, "", "", 0.0),
    ]

    def catalogue_titled(self, words, limit=200):
        return [r for r in self.rows if all(w.lower() in r.title.lower() for w in words)][:limit]


class C411:
    is_c411 = True

    def __init__(self, limited=()):
        self.calls = []
        self.limited = set(limited)

    def torrent_json(self, infohash):
        self.calls.append(infohash)
        if infohash in self.limited:
            raise RateLimited(600)
        return {
            "metadata": {
                "tmdbData": {
                    "id": 297608,
                    "title": "L'Étrange Cas Deborah Logan",
                    "originalTitle": "The Taking of Deborah Logan",
                    "overview": "Pour sa thèse consacrée à Alzheimer, Mia filme Deborah.",
                    "posterUrl": "https://image.tmdb.org/t/p/w500/poster.jpg",
                    "genres": ["Horreur", "Mystère"],
                    "directors": ["Adam Robitel"],
                    "rating": 6.8,
                    "year": 2014,
                }
            }
        }


def library(tmp_path, titles):
    agent = types.SimpleNamespace(setup=types.SimpleNamespace(path=tmp_path / "settings.json"))
    media = MediaLibrary(agent)
    with media.db:
        for number, (title, year) in enumerate(titles):
            body = {
                "kind": "video",
                "title": title,
                "year": year,
                "series": "",
                "description": "",
                "identity_source": "filename",
                "content_id": str(number),
                "artwork": "",
            }
            media.db.execute(
                "INSERT INTO media_items VALUES (?,?,?,?,?,?,?,?)",
                (
                    str(number),
                    "default",
                    f"/films/{number}.mkv",
                    "/films",
                    1,
                    1,
                    0,
                    json.dumps(body),
                ),
            )
    return media


def setup(indexer):
    return types.SimpleNamespace(
        indexer=lambda: indexer, store=Catalogue(), settings=types.SimpleNamespace(path_mappings=[])
    )


def body(media, identifier):
    row = media.db.execute("SELECT body FROM media_items WHERE id=?", (identifier,)).fetchone()
    return json.loads(row[0])


def test_catalogue_release_gives_french_title_synopsis_and_poster(tmp_path):
    media = library(tmp_path, [("The Taking of Deborah Logan", "2014"), ("Unknown Film", "")])
    indexer = C411()
    status = media.enrich("default", setup(indexer), threading.Event(), lambda _p: None)
    assert status == "complete"
    film = body(media, "0")
    assert film["title"] == "L'Étrange Cas Deborah Logan"
    assert film["original_title"] == "The Taking of Deborah Logan"
    assert film["description"].startswith("Pour sa thèse")
    assert film["remote_artwork"].endswith("poster.jpg")
    assert film["genre"] == "Horreur, Mystère"
    assert film["identity_source"] == "c411 release description"
    assert body(media, "1")["title"] == "Unknown Film"
    # Answers are cached: a second refresh asks c411 nothing.
    media.enrich("default", setup(indexer), threading.Event(), lambda _p: None)
    assert indexer.calls == [DEBORAH]


def test_rate_limit_stops_quietly_and_a_later_refresh_finishes(tmp_path):
    media = library(tmp_path, [("Spectral", "2016"), ("The Taking of Deborah Logan", "2014")])
    status = media.enrich("default", setup(C411(limited={SPECTRAL})), threading.Event(), print)
    assert status == "limit"
    assert body(media, "0")["title"] == "Spectral"
    later = C411()
    assert media.enrich("default", setup(later), threading.Event(), print) == "complete"
    assert body(media, "0").get("release_details") == SPECTRAL
    assert body(media, "1").get("release_details") == DEBORAH


def test_without_c411_nothing_is_fetched(tmp_path):
    media = library(tmp_path, [("Spectral", "2016")])

    def missing():
        raise ValueError("Add your c411 API key in Settings first.")

    plain = types.SimpleNamespace(
        indexer=missing, store=Catalogue(), settings=types.SimpleNamespace(path_mappings=[])
    )
    assert media.enrich("default", plain, threading.Event(), print) == "off"
    assert "release_details" not in body(media, "0")


def test_downloaded_release_is_described_by_its_own_hash(tmp_path):
    from pathlib import Path

    from torrentlinker.domain import Torrent

    exact = "b" * 40
    media = library(tmp_path, [("deborah logan rip", "")])
    indexer = C411()
    downloaded = Torrent(exact, "rip", Path("/films"), {"0.mkv": 1}, progress=1.0)
    media.enrich("default", setup(indexer), threading.Event(), print, [downloaded])
    assert indexer.calls == [exact]
    assert body(media, "0")["release_details"] == exact
