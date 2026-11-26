"""The film index fills on demand, where the user looks (decision 25): one job per client, the
films on screen first, no counts for a Member, the same routes on the desktop. TMDb and the
Catalogues are fake; the index job itself is replaced where a route is under test."""

# ruff: noqa: F811  (the `films` fixture is imported, then used as an argument)

import threading
import time

import pytest
from fastapi.testclient import TestClient

from tests.film_support import seed_index
from tests.test_media_tracker import library  # noqa: F401  (the films fixture needs it)
from tests.test_members_signin import member, sign_in
from tests.test_tracker_films import STOP, films, query  # noqa: F401
from tests.test_tracker_films_api import FILMS, RELEASES
from tests.test_web_jobs import login
from torrentlinker.accounts import Permission
from torrentlinker.media_browser import MediaBrowserService
from torrentlinker.web.app import create_app


def lookups(films):
    return [title for title, _ in films.tmdb.lookups]


def due(media):
    """The Catalogues are due and no run is fresh: the fixture's own scan stamped them."""
    with media.lock, media.db:
        media.db.execute("DELETE FROM media_options WHERE key LIKE 'films-%'")


def film_of(films, title):
    return next(f["id"] for f in query(films)["rows"] if f["title"] == title)


def test_the_titles_on_screen_are_identified_first_then_the_newest_then_the_most_shared(films):
    films.films_sync("default", films.setup_for_test)
    setup = films.setup_for_test
    # Dune has the most seeders; Alien is the newest on the Trackers.
    with films.lock, films.db:
        films.db.execute("UPDATE film_release SET published=500 WHERE title='Alien'")
    films._films_changed()
    films.films_focus("default", [film_of(films, "Spirited Away")])
    assert films.films_identify("default", setup, STOP(), pause=0, limit=1) == "batch"
    assert lookups(films) == ["Spirited Away"]  # on screen, though the least shared
    films.films_focus("default", [])  # the user scrolled away
    assert films.films_identify("default", setup, STOP(), pause=0, limit=1) == "batch"
    assert lookups(films)[1] == "Alien"  # then the newest
    assert films.films_identify("default", setup, STOP(), pause=0, limit=1) == "complete"
    assert lookups(films)[2] == "Dune"  # then the most shared


def test_a_title_comes_with_its_facts_so_its_poster_can_replace_the_plain_card(films):
    films.films_sync("default", films.setup_for_test)
    films.films_identify("default", films.setup_for_test, STOP(), pause=0, limit=1)
    assert films.tmdb.detailed == ["1"] and query(films, identified_only=True)["total"] == 1


def test_the_job_runs_in_batches_until_complete_and_the_index_is_then_not_behind(films):
    setup, seen = films.setup_for_test, []
    due(films)
    assert films.films_behind("default", setup)  # the Catalogues were never read
    assert films.films_index("default", setup, STOP(), seen.append, pause=0) == "complete"
    assert query(films, identified_only=True)["total"] == 3
    assert seen[-1] == {"phase": "identify", "identified": 3, "total": 3}
    assert not films.films_behind("default", setup)
    # A film added to the Catalogues makes it behind again once the Catalogues are due.
    due(films)
    assert films.films_behind("default", setup)


def test_without_a_tmdb_key_the_job_only_reads_the_catalogues(films):
    from types import SimpleNamespace

    setup = films.setup_for_test
    setup.secrets = SimpleNamespace(get=lambda name: "")
    assert films.films_index("default", setup, STOP(), lambda _: None, pause=0) == "off"
    assert query(films)["total"] == 4 and films.tmdb.lookups == []
    assert not films.films_behind("default", setup)


def test_the_job_stops_after_three_failures_and_a_page_does_not_restart_it_at_once(films):
    setup = films.setup_for_test
    due(films)
    films.tmdb.failing = True
    assert films.films_index("default", setup, STOP(), lambda _: None, pause=0) == "unavailable"
    assert not films.films_behind("default", setup)  # resting
    films._films_resting.clear()
    assert films.films_behind("default", setup)


def test_one_identification_runs_at_a_time(films):
    setup = films.setup_for_test
    assert films._films_working.acquire(blocking=False)
    try:
        assert films.films_index("default", setup, STOP(), lambda _: None) == "busy"
        assert films.films_refresh("default", setup, STOP()) == "waiting"
    finally:
        films._films_working.release()


def test_the_revision_moves_with_the_index_and_only_the_owner_gets_counts(films):
    films.films_sync("default", films.setup_for_test)
    before = films.films_revision("default", True, False)
    assert before["running"] is True and "total" not in before and "identified" not in before
    films.films_identify("default", films.setup_for_test, STOP(), pause=0, limit=1)
    after = films.films_revision("default", False, True)
    assert after["revision"] != before["revision"] and after["running"] is False
    assert (after["identified"], after["total"]) == (1, 3)


@pytest.fixture
def server(tmp_path):
    app = create_app(
        tmp_path, members_enabled=True, password="test-password-long", monitor_verifications=False
    )
    media = app.state.agent_service.media
    seed_index(media, FILMS, RELEASES)
    started, release = [], threading.Event()

    def index(client, setup, stop, progress, **_):
        started.append(client)
        release.wait(5)
        return "complete"

    media.films_index = index
    # The Catalogues are due, so the index is behind.
    due(media)
    with TestClient(app) as browser:
        browser.headers["X-TorrentLinker"] = "1"
        yield app, browser, started, release


def wait_for(condition):
    for _ in range(100):
        if condition():
            return
        time.sleep(0.02)
    raise AssertionError("timed out")


def test_opening_the_landing_a_grid_or_the_home_starts_the_job_once_per_client(server):
    app, browser, started, release = server
    login(browser)
    for path in (
        "/api/media/tracker-films/landing",
        "/api/media/tracker-films",
        "/api/media/home",
        "/api/media/tracker-films/landing",
    ):
        assert browser.get(path).status_code == 200
    wait_for(lambda: started)
    assert started == ["default"]  # the first request started it; the others joined it
    jobs = app.state.agent_service.jobs
    assert jobs.running("films-index", "default")
    # It runs apart from the batch lane and never counts as work in progress.
    assert jobs.list()[0]["lane"] == "films" and not jobs.active()
    assert browser.get("/api/media/tracker-films/revision").json()["running"] is True
    release.set()
    wait_for(lambda: not jobs.running("films-index", "default"))
    assert browser.get("/api/media/tracker-films/revision").json()["running"] is False


def test_a_member_never_gets_counts_and_may_not_browse_without_the_permission(server):
    app, browser, _, release = server
    release.set()
    member(app, "lea", Permission.FILMS)
    sign_in(browser, "lea")
    answer = browser.get("/api/media/tracker-films/revision").json()
    assert set(answer) == {"revision", "running"}
    assert browser.post(
        "/api/media/tracker-films/focus", json={"films": ["title-0123456789abcdef"]}
    ).json() == {"ok": True}
    member(app, "tom", Permission.SEARCH)
    sign_in(browser, "tom")
    assert browser.get("/api/media/tracker-films/revision").status_code == 403
    assert browser.post("/api/media/tracker-films/focus", json={"films": []}).status_code == 403


def test_the_owner_gets_counts_and_a_focus_reaches_the_index(server):
    app, browser, _, release = server
    release.set()
    login(browser)
    answer = browser.get("/api/media/tracker-films/revision").json()
    assert answer["total"] == 4 and answer["identified"] == 4 and answer["running"] is False
    media = app.state.agent_service.media
    unknown = next(f["id"] for f in media._film_index() if not f["identified"])
    assert (
        browser.post("/api/media/tracker-films/focus", json={"films": [unknown]}).status_code == 200
    )
    # A name that is not a film, or a list too long, is refused by the same validation.
    assert (
        browser.post("/api/media/tracker-films/focus", json={"films": ["x" * 81]}).status_code
        == 422
    )


def test_the_desktop_router_serves_the_same_routes(server):
    app, _, started, release = server
    desktop = MediaBrowserService(app.state.agent_service)
    desktop.request("media/tracker-films/landing?client_id=default")
    wait_for(lambda: started)
    assert started == ["default"]
    answer = desktop.request("media/tracker-films/revision?client_id=default")
    assert answer["running"] is True and answer["total"] == 4
    assert desktop.request("media/tracker-films/focus", {"films": ["title-1"]}, "POST") == {
        "ok": True
    }
    release.set()
