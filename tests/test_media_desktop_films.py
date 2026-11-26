"""The desktop Médias answers the Owner's Tracker Films through MediaBrowserService, with the
web routes' validation. The index is seeded; no TMDb, tracker or poster host is reached."""

import base64
from io import BytesIO

import pytest
from PIL import Image

from tests.film_support import seed_index
from tests.test_tracker_films import FakeTmdb
from torrentlinker.media_browser import MediaBrowserService
from torrentlinker.web.app import create_app

GB = 10**9


@pytest.fixture
def service(tmp_path, monkeypatch):
    app = create_app(tmp_path, password="test-password-long", monitor_verifications=False)
    media = app.state.agent_service.media
    seed_index(
        media,
        {
            "1": ("Dune", "Dune", "2021", ["Science-Fiction", "Aventure"], "12", 155),
            "2": ("Alien", "Alien", "1979", ["Horreur", "Science-Fiction"], "16", 117),
        },
        [
            ("c411", "a" * 40, "Dune.2021.MULTi.1080p.WEB.x264-TEAM", 4 * GB, 30, "1"),
            ("tr4ker", "b" * 40, "Dune.2021.MULTi.2160p.BluRay.x265-TEAM", 40 * GB, 5, "1"),
            ("c411", "c" * 40, "Alien.1979.MULTi.1080p.BluRay.x264-TEAM", 7 * GB, 2, "2"),
        ],
    )
    return MediaBrowserService(app.state.agent_service), media


def test_the_landing_the_grid_and_a_film_are_the_owners(service):
    desktop, _ = service
    landing = desktop.request("media/tracker-films/landing?client_id=default")
    assert [row["key"] for row in landing["rows"][:2]] == ["tracker-new", "tracker-shared"]
    page = desktop.request("media/tracker-films?client_id=default&sort=title&limit=1")
    assert [r["title"] for r in page["rows"]] == ["Alien"] and page["has_more"]
    # The Owner's film carries its pre-selected release and every grouped one.
    dune = desktop.request("media/tracker-films/tmdb-1?client_id=default")
    assert len(dune["releases"]) == 2 and dune["tracker"]["hash"] == dune["releases"][0]["hash"]
    with pytest.raises(ValueError, match="sort"):
        desktop.request("media/tracker-films?sort=nope")


def test_the_grid_takes_two_genres_as_the_web_route_does(service):
    desktop, _ = service
    both = desktop.request(
        "media/tracker-films?genre=Science-Fiction&genre=Aventure&client_id=default"
    )
    assert [r["title"] for r in both["rows"]] == ["Dune"]
    one = desktop.request("media/tracker-films?genre=Science-Fiction&sort=title")
    assert [r["title"] for r in one["rows"]] == ["Alien", "Dune"]


def test_the_corrections_are_validated_like_the_web_routes(service):
    desktop, media = service
    with pytest.raises(ValueError, match="TMDb film number"):
        desktop.request("media/tracker-films/tmdb-1/rematch", {"tmdb": "abc"}, "POST")
    with pytest.raises(ValueError, match="TMDb key"):
        desktop.request("media/tracker-films/tmdb-1/rematch", {"tmdb": "2"}, "POST")
    with pytest.raises(ValueError, match="Unknown tracker"):
        desktop.request(
            f"media/tracker-films/releases/nope/{'a' * 40}/rematch", {"tmdb": "2"}, "POST"
        )
    with pytest.raises(ValueError, match="Unknown tracker release"):
        desktop.request("media/tracker-films/releases/c411/zzz/rematch", {"tmdb": "2"}, "POST")
    with pytest.raises(ValueError, match="Choose"):
        desktop.request("media/tracker-films/tmdb-1/rating", {"rating": "21"}, "POST")
    assert desktop.request("media/tracker-films/tmdb-2/rating", {"rating": "TP"}, "POST") == {
        "ok": True
    }
    assert desktop.request("media/tracker-films/tmdb-2")["age_rating"]["rating"] == "TP"
    # With a TMDb key (fake), a film and then one release move to another film.
    tmdb = FakeTmdb()
    media.tmdb_client = lambda key: tmdb
    media.agent.setup.secrets.update({"tmdb-api-key": "key"})
    tmdb.FILMS["9"] = ("Autre", "Other", "2021", "Un autre film.", ["Drame"], 90, "TP")
    desktop.request("media/tracker-films/tmdb-2/rematch", {"tmdb": "9"}, "POST")
    assert desktop.request("media/tracker-films/tmdb-9")["title"] == "Autre"
    desktop.request(
        f"media/tracker-films/releases/tr4ker/{'b' * 40}/rematch", {"tmdb": "9"}, "POST"
    )
    assert desktop.request("media/tracker-films/tmdb-1")["release_count"] == 1
    with pytest.raises(ValueError, match="Unknown Media browsing operation"):
        desktop.request("media/tracker-films/tmdb-1/nothing", {}, "POST")


def test_a_film_poster_crosses_the_bridge_as_a_data_url(service, monkeypatch):
    desktop, _ = service
    picture = BytesIO()
    Image.new("RGB", (600, 900), "#335577").save(picture, "PNG")
    monkeypatch.setattr(
        "torrentlinker.assistant.images.fetch_image", lambda url: (picture.getvalue(), "image/png")
    )
    for size in ("grid", "hero"):
        url = desktop.request(f"media/items/film-tmdb-1/artwork?client_id=default&size={size}")
        assert url["data_url"].startswith("data:image/webp;base64,")
        assert base64.b64decode(url["data_url"].split(",", 1)[1])[8:12] == b"WEBP"


def test_a_release_is_downloaded_through_the_existing_tracker_route(service, monkeypatch):
    desktop, media = service
    calls = []
    monkeypatch.setattr(
        media, "tracker_download", lambda client, setup, h: calls.append(h) or {"queued": True}
    )
    assert desktop.request(f"media/tracker/{'B' * 40}/download", {}, "POST") == {"queued": True}
    assert calls == ["b" * 40]
