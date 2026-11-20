"""Media's tracker rows: well scored c411 films, apart from the library and as upgrades."""

import contextlib
import threading
from types import SimpleNamespace

import pytest

from torrentlinker.indexer import Candidate, RateLimited
from torrentlinker.store import CatalogueRow
from torrentlinker.torrent_search import ListingRow

GB = 1024**3


class FakeIndexer:
    is_c411 = True

    def background(self, stop=None):
        return contextlib.nullcontext()

    def unredact(self, value):
        return value


class FakeStore:
    def __init__(self, titles):
        self.rows = [
            CatalogueRow(f"{n:040x}", title, 20 * GB, 100 - n, 2030, "", "", 0.0, "indexer", 1)
            for n, title in enumerate(titles)
        ]

    def catalogue_films(self, limit=3000, least_seeders=5):
        return self.rows


def listing_page(title, year, *, size=20 * GB, resolution="2160p"):
    """One c411 release of the film, with the facts ReleaseScore needs."""
    h = format(abs(hash((title, year))), "040x")[-40:]
    release = f"{title.replace(' ', '.')}.{year}.MULTi.{resolution}.BluRay.x265-TEAM"
    return SimpleNamespace(
        rows=[
            Candidate(release, size, "https://c411.org/dl", 50, h, "", (2030,), published_at=1.7e9)
        ],
        details={
            h: ListingRow(
                title=title,
                year=year,
                kind="movie",
                runtime=120,
                tags=(("resolution", resolution), ("codec", "x265"), ("source", "BluRay")),
                genres=("Drame",),
                overview="Un film.",
                poster_url="https://image.tmdb.org/t/p/w500/poster.jpg",
            )
        },
    )


@pytest.fixture
def library(tmp_path):
    from torrentlinker.config import Settings
    from torrentlinker.domain import LibraryFolder
    from torrentlinker.web.app import create_app

    root = tmp_path / "videos"
    root.mkdir()
    (root / "The Revenant 2015 VOSTFR 720 WEB.mkv").write_bytes(b"\0" * 64)
    config = tmp_path / "config"
    config.mkdir()
    settings = Settings()
    settings.library_folders = [LibraryFolder(root)]
    settings.save(config / "settings.json")
    app = create_app(
        config, password="test-password-long", roots=(root,), monitor_verifications=False
    )
    media = app.state.assistant.agent.media
    media.scan("default", threading.Event(), lambda _p: None)
    return media


def setup_with(store, threshold=0, folder=None):
    from torrentlinker.config import Settings

    settings = Settings()
    settings.release_score = {"threshold": threshold}
    return SimpleNamespace(
        settings=settings,
        store=store,
        indexer=FakeIndexer,
        download_folder=lambda category: folder,
        verified_download_folder=lambda category: folder,
    )


def test_tracker_rows_split_new_films_from_better_versions_of_library_films(library, monkeypatch):
    calls = []

    def search(indexer, params, page=1):
        calls.append(params["name"])
        return listing_page(params["name"], int(params["year"]))

    monkeypatch.setattr("torrentlinker.torrent_search.native_search", search)
    setup = setup_with(FakeStore(["Oppenheimer.2023.MULTi.2160p.WEB.x265-TEAM"]))
    assert library.tracker_refresh("default", setup, threading.Event()) == "complete"
    # The library's own film is looked up first, then the Catalogue's.
    assert calls == ["The Revenant", "Oppenheimer"]
    rows = {row["key"]: row for row in library.tracker_rows("default", setup)}
    assert [item["title"] for item in rows["tracker"]["rows"]] == ["Oppenheimer"]
    upgrade = rows["upgrades"]["rows"][0]
    assert upgrade["title"] == "The Revenant"
    assert upgrade["tracker"]["score"] > upgrade["tracker"]["own_score"]
    assert upgrade["id"].startswith("tracker-") and upgrade["artwork_url"]
    assert upgrade["tracker"]["published_at"] == 1.7e9
    # A refresh within ten minutes looks nothing up again.
    assert library.tracker_refresh("default", setup, threading.Event()) == "waiting"
    assert len(calls) == 2
    # The threshold, from ReleaseScore's settings, hides releases below it.
    assert library.tracker_rows("default", setup_with(setup.store, threshold=100)) == []


def test_tracker_refresh_looks_up_twenty_films_and_stops_when_c411_asks_to_wait(
    library, monkeypatch
):
    titles = [f"Film.Numero.{n:02d}.{1980 + n}.1080p.WEB.x264-TEAM" for n in range(30)]
    calls = []

    def search(indexer, params, page=1):
        calls.append(params["name"])
        return listing_page(params["name"], int(params["year"]))

    monkeypatch.setattr("torrentlinker.torrent_search.native_search", search)
    setup = setup_with(FakeStore(titles))
    library.tracker_refresh("default", setup, threading.Event())
    assert len(calls) == 20

    def limited(indexer, params, page=1):
        raise RateLimited(60)

    monkeypatch.setattr("torrentlinker.torrent_search.native_search", limited)
    monkeypatch.setattr("torrentlinker.media_tracker.RUN_INTERVAL", 0)
    assert library.tracker_refresh("default", setup, threading.Event()) == "limit"
    # What was found before stays suggested.
    assert library.tracker_rows("default", setup)


def test_queueing_a_tracker_film_needs_its_download_folder(library, monkeypatch, tmp_path):
    monkeypatch.setattr(
        "torrentlinker.torrent_search.native_search",
        lambda indexer, params, page=1: listing_page(params["name"], int(params["year"])),
    )
    store = FakeStore(["Oppenheimer.2023.MULTi.2160p.WEB.x265-TEAM"])
    library.tracker_refresh("default", setup_with(store), threading.Event())
    item = next(
        row for row in library.tracker_rows("default", setup_with(store)) if row["key"] == "tracker"
    )["rows"][0]
    infohash = item["tracker"]["hash"]
    with pytest.raises(ValueError, match="Download Folder"):
        library.tracker_enqueue("default", setup_with(store), infohash)
    queued = []
    monkeypatch.setattr(
        "torrentlinker.download_queue.enqueue",
        lambda store, indexer, candidate, folder: queued.append((candidate, folder)) or True,
    )
    result = library.tracker_enqueue("default", setup_with(store, folder=tmp_path), infohash)
    assert result["queued"] and queued[0][0].infohash == infohash and queued[0][1] == tmp_path
    with pytest.raises(ValueError, match="no longer suggested"):
        library.tracker_enqueue("default", setup_with(store, folder=tmp_path), "0" * 40)


def test_desktop_media_service_queues_a_tracker_release_by_its_hash(monkeypatch):
    from torrentlinker.media_browser import MediaBrowserService

    calls = []
    media = SimpleNamespace(
        setup=lambda client: "setup",
        tracker_enqueue=lambda client, setup, h: calls.append((client, setup, h)) or {"ok": 1},
    )
    agent = SimpleNamespace(
        media=media, setup=SimpleNamespace(settings=SimpleNamespace(default_client_id="default"))
    )
    service = MediaBrowserService(agent)
    infohash = "A" * 40
    assert service.request(f"media/tracker/{infohash}/enqueue", {}, "POST") == {"ok": 1}
    assert calls == [("default", "setup", "a" * 40)]
    with pytest.raises(ValueError, match="Unknown tracker release"):
        service.request("media/tracker/../enqueue", {}, "POST")
