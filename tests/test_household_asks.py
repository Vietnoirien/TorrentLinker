"""Household Asks (decision 24): a Viewer on a Shared Screen asks its account holder for a Tracker
Film; the holder accepts into a Request of their own, or refuses. No tracker or TMDb is read."""

import pytest
from fastapi.testclient import TestClient

from tests.film_support import seed_index
from tests.test_members_signin import PASSWORD, member, sign_in
from tests.test_members_viewers import screen_sign_in
from tests.test_web_jobs import login
from torrentlinker.accounts import OWNER, Accounts, Caps, Permission
from torrentlinker.household_asks import HouseholdAsks
from torrentlinker.member_requests import FilmAsk, Requests
from torrentlinker.web.app import create_app

GB = 10**9
FAMILY = {Permission.FILMS, Permission.REQUEST}


@pytest.fixture
def server(tmp_path):
    app = create_app(
        tmp_path, members_enabled=True, password="test-password-long", monitor_verifications=False
    )
    seed_index(
        app.state.agent_service.media,
        {
            "1": ("Dune", "Dune", "2021", ["Science-Fiction"], "12", 155),
            "2": ("Chihiro", "Spirited Away", "2001", ["Animation"], "TP", 125),
        },
        [
            ("c411", "a" * 40, "Dune.2021.MULTi.1080p.WEB.x264-TEAM", 4 * GB, 30, "1"),
            ("c411", "c" * 40, "Chihiro.2001.MULTi.1080p.BluRay.x264-TEAM", 8 * GB, 20, "2"),
        ],
    )
    with TestClient(app) as browser:
        browser.headers["X-TorrentLinker"] = "1"
        yield app, browser


def household(app, *, can_ask=True, age_limit=None):
    """Léa with Tom, a Viewer on her living-room screen."""
    lea = member(app, "lea", *FAMILY)
    app.state.accounts.set_pin(lea, "", "2468")
    tom = app.state.accounts.add_viewer(lea, "Tom", {Permission.FILMS}, age_limit, can_ask)
    return lea, tom


def on_screen(browser, tom):
    screen_sign_in(browser)
    assert browser.post("/api/screen/choose", json={"viewer": tom}).status_code == 200


def test_a_viewer_may_ask_only_when_its_holder_turned_it_on_and_never_makes_a_request(server):
    app, browser = server
    lea, tom = household(app, can_ask=False)
    on_screen(browser, tom)
    assert browser.get("/api/household-asks").json()["can_ask"] is False
    assert browser.post("/api/household-asks", json={"film": "tmdb-1"}).status_code == 403
    # A Viewer never makes a Request, nor answers an ask.
    assert browser.post("/api/requests", json={"film": "tmdb-1"}).status_code == 403
    # Léa turns the switch on from Mon compte; it is hers to decide (and the Owner's).
    sign_in(browser, "lea")
    profile = next(p for p in browser.get("/api/account").json()["profiles"] if p["id"] == tom)
    assert profile["can_ask"] is False
    body = {"name": "Tom", "permissions": ["films"], "age_limit": None, "can_ask": True}
    assert browser.post(f"/api/account/viewers/{tom}", json=body).status_code == 200
    on_screen(browser, tom)
    assert browser.get("/api/household-asks").json()["can_ask"] is True
    asked = browser.post("/api/household-asks", json={"film": "tmdb-1"})
    assert asked.status_code == 200, asked.text
    assert browser.post("/api/household-asks", json={"film": "tmdb-1"}).status_code == 409
    assert browser.post("/api/household-asks", json={"film": "tmdb-9"}).status_code == 404
    mine = browser.get("/api/household-asks").json()
    assert mine["holder"] == "Lea" and mine["asks"][0]["state"] == "pending"
    assert mine["asks"][0]["title"] == "Dune"
    identifier = mine["asks"][0]["id"]
    assert browser.post(f"/api/household-asks/{identifier}/accept").status_code == 403
    assert browser.post(f"/api/household-asks/{identifier}/refuse", json={}).status_code == 403
    cancelled = browser.post(f"/api/household-asks/{identifier}/cancel")
    assert cancelled.json()["state"] == "cancelled"
    assert browser.post(f"/api/household-asks/{identifier}/cancel").status_code == 409


def test_the_ask_waits_in_the_holders_bell_and_accepting_makes_her_own_request(server):
    app, browser = server
    lea, tom = household(app)
    app.state.accounts.set_caps(lea, Caps(requests_per_week=3, bytes_per_week=20 * GB))
    on_screen(browser, tom)
    browser.post("/api/household-asks", json={"film": "tmdb-1"})
    sign_in(browser, "lea")
    drawer = browser.get("/api/requests").json()
    assert drawer["unread"] == 1 and drawer["requests"] == []
    [ask] = drawer["household"]
    assert ask["viewer"] == "Tom" and ask["state"] == "pending" and ask["title"] == "Dune"
    assert ask["size"] > 0  # the quote her quota is checked against
    assert browser.post("/api/requests/seen").json()["unread"] == 0
    accepted = browser.post(f"/api/household-asks/{ask['id']}/accept")
    assert accepted.status_code == 200, accepted.text
    # Her own Request, to the Owner, on her quota, with no release chosen.
    [request] = browser.get("/api/requests").json()["requests"]
    assert (
        request["film"] == "tmdb-1" and request["state"] == "pending" and request["infohash"] == ""
    )
    assert app.state.requests.quota(lea)["requests_left"] == 2
    assert browser.post(f"/api/household-asks/{ask['id']}/accept").status_code == 409
    # Tom follows it: accepted, then the Request's own state.
    on_screen(browser, tom)
    [seen] = browser.get("/api/household-asks").json()["asks"]
    assert seen["state"] == "accepted" and seen["request_state"] == "pending"
    app.state.requests.move(request["id"], "refused", OWNER, "Pas cette semaine")
    assert browser.get("/api/household-asks").json()["asks"][0]["request_state"] == "refused"


def test_a_reached_quota_leaves_the_ask_pending_and_a_refusal_carries_its_note(server):
    app, browser = server
    lea, tom = household(app)
    app.state.accounts.set_caps(lea, Caps(requests_per_week=1))
    on_screen(browser, tom)
    first = browser.post("/api/household-asks", json={"film": "tmdb-1"}).json()
    second = browser.post("/api/household-asks", json={"film": "tmdb-2"}).json()
    sign_in(browser, "lea")
    assert browser.post(f"/api/household-asks/{first['id']}/accept").status_code == 200
    blocked = browser.post(f"/api/household-asks/{second['id']}/accept")
    assert blocked.status_code == 409 and blocked.json()["cap"] == "count"
    assert app.state.household_asks.get(second["id"])["state"] == "pending"
    refused = browser.post(
        f"/api/household-asks/{second['id']}/refuse", json={"note": "Pas ce soir"}
    )
    assert refused.json()["state"] == "refused"
    on_screen(browser, tom)
    asks = {a["title"]: a for a in browser.get("/api/household-asks").json()["asks"]}
    assert asks["Chihiro"]["state"] == "refused" and asks["Chihiro"]["note"] == "Pas ce soir"


def test_the_viewers_age_limit_decides_which_films_it_can_ask_for(server):
    app, browser = server
    lea, tom = household(app, age_limit=1)  # -10: Dune is rated -12
    on_screen(browser, tom)
    assert browser.post("/api/household-asks", json={"film": "tmdb-1"}).status_code == 404
    assert browser.post("/api/household-asks", json={"film": "tmdb-2"}).status_code == 200


def test_a_holder_without_the_request_permission_gives_her_viewers_no_ask(server):
    app, browser = server
    lea = member(app, "lea", Permission.FILMS)
    app.state.accounts.set_pin(lea, "", "2468")
    tom = app.state.accounts.add_viewer(lea, "Tom", {Permission.FILMS}, None, True)
    on_screen(browser, tom)
    assert browser.get("/api/household-asks").json()["can_ask"] is False
    assert browser.post("/api/household-asks", json={"film": "tmdb-1"}).status_code == 403


def test_the_owner_can_set_the_switch_on_a_members_viewer_but_a_manager_cannot(server):
    app, browser = server
    lea, tom = household(app, can_ask=False)
    manager = member(app, "boss", Permission.MANAGE_MEMBERS, *FAMILY, password=PASSWORD)
    body = {"name": "Tom", "permissions": ["films"], "age_limit": None, "can_ask": True}
    sign_in(browser, "boss")
    browser.post(f"/api/members/{lea}/viewers/{tom}", json=body)
    assert next(p for p in app.state.accounts.profiles(lea) if p["id"] == tom)["can_ask"] is False
    browser.cookies.clear()
    login(browser)
    assert browser.post(f"/api/members/{lea}/viewers/{tom}", json=body).status_code == 200
    assert next(p for p in app.state.accounts.profiles(lea) if p["id"] == tom)["can_ask"] is True
    assert manager


def test_on_the_owners_own_account_accepting_makes_no_request(tmp_path):
    accounts = Accounts(tmp_path)
    requests = Requests(accounts)
    asks = HouseholdAsks(accounts, requests)
    accounts.set_pin(OWNER, "", "2468")
    tom = accounts.add_viewer(OWNER, "Tom", {Permission.FILMS}, None, True)
    ask = asks.ask(OWNER, tom, "", FilmAsk("tmdb-1", "Dune", "2021", 4 * GB))
    assert asks.household(OWNER)[0]["viewer"] == "Tom" and asks.unseen(OWNER) == 1
    done = asks.accept(OWNER, ask["id"])
    # The Owner chooses the release next and downloads directly: there is no Request.
    assert done["state"] == "accepted" and done["request_state"] == ""
    assert requests.review() == []
    assert accounts.viewer_actor(OWNER, tom).asks  # type: ignore[union-attr]


def test_removing_a_viewer_takes_its_asks_out_of_the_drawer(tmp_path):
    accounts = Accounts(tmp_path)
    asks = HouseholdAsks(accounts, Requests(accounts))
    lea = accounts.create("Léa", "lea", FAMILY)
    tom = accounts.add_viewer(lea, "Tom", {Permission.FILMS}, None, True)
    asks.ask(lea, tom, "", FilmAsk("tmdb-1", "Dune", "2021", 4 * GB))
    accounts.remove_viewer(lea, tom)
    assert asks.household(lea) == []
