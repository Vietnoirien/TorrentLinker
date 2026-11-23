"""RSS and the Torrent Clients: each client's state of a torrent, pausing and resuming it, and
the tr4ker category tree. Fake clients only; nothing reaches a real client or tracker."""

import time
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.fake_qbit import FakeQbit
from tests.test_members_signin import member
from tests.test_members_workspace import server  # noqa: F401 - the fixture
from tests.test_web_jobs import login
from torrentlinker import tr4ker_categories
from torrentlinker.accounts import Permission
from torrentlinker.domain import Torrent
from torrentlinker.torrent_management import feed_state
from torrentlinker.torrents_workspace import TorrentQuery
from torrentlinker.tr4ker_categories import Tr4kerCategories
from torrentlinker.web.app import create_app

A, B, C = "a" * 40, "b" * 40, "c" * 40


@pytest.mark.parametrize(
    ("state", "progress", "expected"),
    [
        ("uploading", 1.0, "seeding"),
        ("stalledUP", 1.0, "seeding"),
        ("forcedUP", 1.0, "seeding"),
        ("downloading", 0.4, "downloading"),
        ("stalledDL", 0.4, "downloading"),
        ("metaDL", 0.0, "downloading"),
        ("pausedUP", 1.0, "paused"),
        ("stoppedDL", 0.4, "paused"),
        ("checkingUP", 1.0, "checking"),
        ("checkingResumeData", 0.4, "checking"),
        ("queuedUP", 1.0, "queued"),
        ("queuedDL", 0.4, "queued"),
        ("", 1.0, "unknown"),
        ("error", 0.4, "unknown"),
        ("missingFiles", 1.0, "unknown"),
        ("moving", 1.0, "unknown"),
    ],
)
def test_a_client_state_reads_as_one_of_five_or_unknown(state, progress, expected):
    assert feed_state(Torrent(A, "T", Path("/d"), state=state, progress=progress)) == expected


def stocked(app, **clients):
    """Give each named client a fake with these torrents; returns the feed control."""
    service = app.state.agent_service
    for name, torrents in clients.items():
        target = service.for_client(name)
        fake = FakeQbit(by_hash={t.hash: t for t in torrents})
        target.setup.client = lambda fake=fake: fake  # type: ignore[method-assign]
        target.observed = list(fake.by_hash.values())
        target.connection_error = ""
        target.feed_observed_at = time.time()
    return service.feed_control


def test_inbox_rows_carry_each_clients_state_and_their_tracker(tmp_path, monkeypatch):
    app = create_app(tmp_path, password="test-password-long")
    with TestClient(app):
        control = stocked(
            app,
            default=[Torrent(A, "One", Path("/d"), state="uploading", progress=1.0)],
        )
        monkeypatch.setattr(
            control.feeds,
            "inbox",
            lambda **_: [
                {"infohash": A, "metadata": {"tracker": "tr4ker"}},
                {"infohash": B, "metadata": {}},
            ],
        )
        rows = control.inbox()
    assert rows[0]["client_states"] == {"default": "seeding"}
    assert rows[0]["tracker"] == "tr4ker"
    assert rows[1]["client_states"] == {} and rows[1]["tracker"] == "c411"


def test_a_state_the_client_did_not_report_is_unknown(tmp_path, monkeypatch):
    app = create_app(tmp_path, password="test-password-long")
    with TestClient(app):
        control = stocked(app, default=[Torrent(A, "One", Path("/d"), state="")])
        monkeypatch.setattr(control.feeds, "inbox", lambda **_: [{"infohash": A}])
        assert control.inbox()[0]["client_states"] == {"default": "unknown"}


def two_clients(app):
    from torrentlinker.domain import Torrent as T

    settings = app.state.agent_service.setup.settings
    settings.client_profiles.append(replace(settings.profile(), id="nas", name="NAS"))
    return stocked(
        app,
        default=[T(A, "One", Path("/d"), state="uploading", progress=1.0)],
        nas=[
            T(A, "One", Path("/d"), state="uploading", progress=1.0),
            T(B, "Two", Path("/d"), state="downloading", progress=0.2),
        ],
    )


def test_pause_and_resume_reach_each_client_that_has_the_torrent(tmp_path):
    app = create_app(tmp_path, password="test-password-long")
    with TestClient(app):
        control = two_clients(app)
        answer = control.client_action([A, B, C], "pause")
        assert answer["clients"]["default"]["sent"] == 1
        assert answer["clients"]["nas"]["sent"] == 2
        service = app.state.agent_service
        assert service.for_client("default").setup.client().by_hash[A].state == "stoppedUP"
        assert service.for_client("nas").setup.client().by_hash[B].state == "stoppedUP"
        assert {t.hash: feed_state(t) for t in service.for_client("nas").observed} == {
            A: "paused",
            B: "paused",
        }
        answer = control.client_action([A], "resume")
        assert answer["clients"]["default"]["sent"] == 1
        assert service.for_client("default").setup.client().by_hash[A].state == "uploading"
        assert service.for_client("nas").setup.client().by_hash[B].state == "stoppedUP"
        with pytest.raises(ValueError, match="pause or resume"):
            control.client_action([A], "remove")


def test_a_client_that_fails_is_reported_and_the_others_go_on(tmp_path):
    app = create_app(tmp_path, password="test-password-long")
    with TestClient(app):
        control = two_clients(app)

        def refuse():
            raise RuntimeError("client down at https://box.example/?key=secret")

        app.state.agent_service.for_client("default").setup.client = refuse
        answer = control.client_action([A], "pause")
        assert "secret" not in answer["clients"]["default"]["error"]
        assert answer["clients"]["nas"]["sent"] == 1


def test_the_client_route_is_the_owners_and_takes_only_info_hashes(tmp_path):
    app = create_app(tmp_path, password="test-password-long")
    with TestClient(app) as browser:
        browser.headers["X-TorrentLinker"] = "1"
        assert browser.post("/api/feed-inbox/client", json={}).status_code == 401
        login(browser)
        two_clients(app)
        body = {"hashes": [A], "action": "pause"}
        assert (
            browser.post("/api/feed-inbox/client", json=body).json()["clients"]["nas"]["sent"] == 1
        )
        bad = browser.post(
            "/api/feed-inbox/client", json={"hashes": ["tr4ker:x"], "action": "pause"}
        )
        assert bad.status_code == 422
        worked = browser.post(
            "/api/feeds/workspace",
            json={
                "path": "feed-inbox/client",
                "method": "POST",
                "body": {**body, "action": "resume"},
            },
        )
        assert worked.json()["clients"]["nas"]["sent"] == 1


def test_a_member_cannot_pause_or_resume_through_rss(server):  # noqa: F811
    app, browser = server
    member(app, "lea", *Permission)
    browser.post("/api/login", json={"login": "lea", "password": "lea-password-long"})
    body = {"hashes": [A], "action": "pause"}
    assert browser.post("/api/feed-inbox/client", json=body).status_code == 403
    workspace = {"path": "feed-inbox/client", "method": "POST", "body": body}
    assert browser.post("/api/feeds/workspace", json=workspace).status_code == 403


def test_torrents_can_be_limited_to_some_hashes(operations):
    from tests.test_torrents_workspace import workspace

    service = workspace(operations)
    rows = service.request("list", {"hashes": ["C" * 40, "e" * 40]})["rows"]
    assert sorted(r["name"] for r in rows) == ["Other", "Small"]
    assert service.request("list", {})["total"] == 3
    with pytest.raises(ValueError):
        TorrentQuery(hashes=["nope"])


pytest_plugins = ["tests.test_enqueue_destinations"]


def tree(*records):
    return [
        {"id": i, "slug": slug, "name": slug.title(), "parent_id": parent, "sort_order": i}
        for i, (slug, parent) in enumerate(records, 1)
    ]


class Tab:
    def __init__(self, body=None, can_read=True, error=None):
        self.body, self.can_read, self.error, self.paths = body, can_read, error, []

    def read_json(self, path, timeout=60.0):
        self.paths.append(path)
        if self.error:
            raise self.error
        return self.body


def test_the_tree_is_tr4kers_own_read_in_its_tab_and_kept_for_a_day():
    now = [0.0]
    cache = Tr4kerCategories(lambda: now[0])
    tab = Tab({"categories": tree(("films", None), ("films-film", 1), ("bad slug!", None))})
    rows = cache.get(tab)
    assert [r["slug"] for r in rows] == ["films", "films-film"]
    assert rows[1] == {"id": 2, "slug": "films-film", "name": "Films-Film", "parent": 1, "order": 2}
    assert tab.paths == ["/api/public/categories"]
    cache.get(tab)
    assert len(tab.paths) == 1
    now[0] = 90000.0
    tab.body = tree(("audio", None))
    assert [r["slug"] for r in cache.get(tab)] == ["audio"]


def test_without_an_answering_tab_the_shipped_snapshot_stands_in():
    for tab in (None, Tab(can_read=False), Tab(error=RuntimeError("closed")), Tab({"x": 1})):
        rows = Tr4kerCategories().get(tab)
        assert {"films", "series-tv"} <= {r["slug"] for r in rows}
    assert all(
        set(r) == {"id", "slug", "name", "parent", "order"} for r in tr4ker_categories.snapshot()
    )


def test_feed_options_offer_the_tree_on_both_routes(tmp_path):
    app = create_app(tmp_path, password="test-password-long")
    with TestClient(app) as browser:
        login(browser)
        direct = browser.get("/api/feed-options").json()["tr4ker_categories"]
        shared = browser.post("/api/feeds/workspace", json={"path": "feed-options"}).json()
        assert direct and direct == shared["tr4ker_categories"]
        assert "films" in {r["slug"] for r in direct}
