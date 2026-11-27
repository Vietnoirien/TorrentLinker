"""The series index fills on demand, as the film index does: a page that shows series starts
one job per client, nothing runs twice, results arrive with a revision bump. TMDb and the
Catalogues are fake."""

# ruff: noqa: F811  (the `series` fixture is imported, then used as an argument)

import threading
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from tests.test_media_tracker import library  # noqa: F401  (the series fixture needs it)
from tests.test_tracker_series import series  # noqa: F401
from tests.test_web_jobs import login
from torrentlinker.web.app import create_app


def test_the_index_is_behind_until_the_job_has_read_the_catalogues_and_identified(series):
    setup = series.setup_for_test
    assert series.series_behind("default", setup)  # the Catalogues were never read
    before = series.series_revision_info(True, False)
    assert before["running"] is True and "total" not in before
    assert (
        series.series_index_job("default", setup, threading.Event(), lambda _: None, pause=0)
        == "complete"
    )
    assert not series.series_behind("default", setup)
    after = series.series_revision_info(False, True)
    assert after["revision"] != before["revision"] and after["running"] is False
    assert (after["identified"], after["total"]) == (2, 3)  # TMDb knows Arrow and Naruto
    assert series.series_index()  # results are there


def test_without_a_tmdb_key_the_catalogues_are_read_and_the_job_does_not_repeat(series):
    series.setup_for_test.secrets = None
    setup = series.setup_for_test
    setup.indexer = lambda: SimpleNamespace(is_c411=False)  # no c411 to walk either
    assert series.series_index_job("default", setup, threading.Event(), lambda _: None) == "off"
    assert not series.series_behind("default", setup)


def test_a_second_job_does_not_run_while_one_is_filling_the_index(series):
    assert series._series_working.acquire(blocking=False)
    try:
        status = series.series_index_job(
            "default", series.setup_for_test, threading.Event(), lambda _: None
        )
    finally:
        series._series_working.release()
    assert status == "busy"


@pytest.fixture
def server(tmp_path):
    app = create_app(tmp_path, password="test-password-long", monitor_verifications=False)
    media = app.state.agent_service.media
    started, release = [], threading.Event()

    def job(client, setup, stop, progress, **_):
        started.append(client)
        release.wait(5)
        return "complete"

    media.series_index_job = job
    with TestClient(app) as browser:
        browser.headers["X-TorrentLinker"] = "1"
        yield app, browser, started, release


def wait_for(condition):
    for _ in range(100):
        if condition():
            return
        time.sleep(0.02)
    raise AssertionError("timed out")


def test_opening_the_landing_or_tout_voir_starts_the_job_once_per_client(server):
    app, browser, started, release = server
    login(browser)
    for path in (
        "/api/media/tracker-series/landing?scope=series",
        "/api/media/tracker-series?scope=anime",
        "/api/media/tracker-series/landing?scope=anime",
    ):
        assert browser.get(path).status_code == 200
    wait_for(lambda: started)
    assert started == ["default"]
    jobs = app.state.agent_service.jobs
    assert jobs.running("series-index", "default") and not jobs.active()
    assert browser.get("/api/media/tracker-series/revision?scope=series").json()["running"] is True
    release.set()
    wait_for(lambda: not jobs.running("series-index", "default"))
    assert browser.get("/api/media/tracker-series/revision?scope=series").json()["running"] is False
