"""Requests name a Film: one row per Member linked by the film, answered once, charged a
shared size. No Catalogue, TMDb or tracker is read."""

import pytest
from fastapi.testclient import TestClient

from tests.film_support import seed_index
from tests.test_members_signin import member, sign_in
from tests.test_web_jobs import login
from torrentlinker.accounts import OWNER, Accounts, Caps, Permission
from torrentlinker.member_requests import EXPIRY, CapReached, FilmAsk, Release, Requests
from torrentlinker.web.app import create_app

GB = 10**9
DUNE = FilmAsk("tmdb-1", "Dune", "2021", 8 * GB)


@pytest.fixture
def store(tmp_path):
    accounts = Accounts(tmp_path)
    ids = [accounts.create(n.title(), n, {Permission.REQUEST}) for n in ("lea", "hugo", "zoe")]
    return accounts, Requests(accounts), ids


def test_a_member_asks_for_a_film_with_no_release_and_the_quota_counts_the_quote(store):
    accounts, requests, (lea, *_) = store
    accounts.set_caps(lea, Caps(bytes_per_week=10 * GB))
    asked = requests.ask_film(lea, DUNE)
    assert asked["film"] == "tmdb-1" and asked["infohash"] == "" and asked["size"] == 8 * GB
    assert requests.quota(lea)["bytes_left"] == 2 * GB
    with pytest.raises(ValueError, match="already asked"):
        requests.ask_film(lea, DUNE)
    with pytest.raises(CapReached) as refused:
        requests.ask_film(lea, FilmAsk("tmdb-2", "Alien", "1979", 5 * GB))
    assert refused.value.cap == "size"


def test_members_asking_for_the_same_film_share_the_quoted_size(store):
    accounts, requests, (lea, hugo, zoe) = store
    accounts.set_caps(hugo, Caps(bytes_per_week=4 * GB))
    first = requests.ask_film(lea, DUNE)
    # Hugo cannot afford 8 GB alone but can afford half of it; joining divides the quote.
    second = requests.ask_film(hugo, DUNE)
    assert requests.get(first["id"])["size"] == 4 * GB == second["size"]
    third = requests.ask_film(
        zoe, FilmAsk("tmdb-1", "Dune", "2021", 9 * GB)
    )  # a new quote: ignored
    assert [requests.get(r["id"])["size"] for r in (first, second, third)] == [-(-8 * GB // 3)] * 3
    assert requests.quota(lea)["bytes_left"] is None
    # Members see that it is shared, never with whom.
    mine = requests.mine(lea)[0]
    assert mine["shared_with"] == 2 and "hugo" not in str(mine).lower()
    # The Approver sees one entry, with every requester.
    [entry] = requests.review()
    assert sorted(entry["requesters"]) == ["Hugo", "Lea", "Zoe"]
    assert entry["size"] == 3 * (-(-8 * GB // 3))


def test_a_cancel_gives_the_share_back_to_the_others_and_the_last_cancels_the_group(store):
    _, requests, (lea, hugo, _) = store
    first, second = requests.ask_film(lea, DUNE), requests.ask_film(hugo, DUNE)
    requests.cancel(hugo, second["id"])
    assert (
        requests.get(first["id"])["size"] == 8 * GB
        and requests.get(first["id"])["state"] == "pending"
    )
    requests.cancel(lea, first["id"])
    assert requests.get(first["id"])["state"] == "cancelled"
    # Cancelled asks give their slot back; the film can be asked again, from scratch.
    again = requests.ask_film(lea, DUNE)
    assert again["state"] == "pending" and again["size"] == 8 * GB


def test_acceptance_charges_the_smaller_of_the_quote_and_the_chosen_size(store):
    _, requests, (lea, hugo, _) = store
    first, second = requests.ask_film(lea, DUNE), requests.ask_film(hugo, DUNE)
    big = Release("a" * 40, "Dune.2160p", 40 * GB, "Dune", "2021")
    requests.answer(first["id"], OWNER, release=big)
    for row in (requests.get(first["id"]), requests.get(second["id"])):
        assert row["state"] == "accepted" and row["infohash"] == big.infohash
        assert row["size"] == 4 * GB and row["chosen_size"] == 40 * GB and row["quoted"] == 8 * GB
    assert requests.quota(lea)["bytes_left"] is None
    # The Owner's margin bar reads the real size; the Members' quota the shared charge.
    [entry] = requests.review()
    assert entry["chosen_size"] == 40 * GB and entry["size"] == 8 * GB
    # A smaller release lowers the charge.
    third = requests.ask_film(lea, FilmAsk("tmdb-2", "Alien", "1979", 8 * GB))
    requests.answer(
        third["id"], OWNER, release=Release("b" * 40, "Alien.720p", 2 * GB, "Alien", "1979")
    )
    assert requests.get(third["id"])["size"] == 2 * GB


def test_the_over_quota_note_follows_each_members_own_share(store):
    accounts, requests, (lea, hugo, _) = store
    first, second = requests.ask_film(lea, DUNE), requests.ask_film(hugo, DUNE)
    accounts.set_caps(hugo, Caps(bytes_per_week=1 * GB))  # lowered after he asked
    requests.answer(first["id"], OWNER, release=Release("a" * 40, "Dune", 8 * GB, "Dune", "2021"))
    # His 4 GB share is over his 1 GB: noted for him only.
    assert "weekly quota" in requests.get(second["id"])["answer"]
    assert requests.get(first["id"])["answer"] == ""


def test_a_refusal_moves_every_row_and_gives_every_slot_back(store):
    accounts, requests, (lea, hugo, _) = store
    for who in (lea, hugo):
        accounts.set_caps(who, Caps(requests_per_week=1))
    first, second = requests.ask_film(lea, DUNE), requests.ask_film(hugo, DUNE)
    requests.answer(first["id"], OWNER, refuse=True, note="Pas cette semaine")
    for row in (requests.get(first["id"]), requests.get(second["id"])):
        assert row["state"] == "refused" and row["answer"] == "Pas cette semaine" and row["unread"]
    assert requests.quota(lea)["requests_left"] == 1 and requests.quota(hugo)["requests_left"] == 1


def test_a_member_joins_only_while_the_request_is_pending(store):
    _, requests, (lea, hugo, _) = store
    first = requests.ask_film(lea, DUNE)
    requests.answer(first["id"], OWNER, release=Release("a" * 40, "Dune", 8 * GB, "Dune", "2021"))
    later = requests.ask_film(hugo, DUNE)
    assert later["state"] == "pending" and later["size"] == 8 * GB
    assert requests.get(first["id"])["size"] == 8 * GB  # the accepted one is unchanged
    [pending] = [r for r in requests.review() if r["state"] == "pending"]
    assert pending["requesters"] == ["Hugo"]


def test_expiry_runs_from_the_first_ask_and_a_join_does_not_extend_it(store):
    _, requests, (lea, hugo, _) = store
    first = requests.ask_film(lea, DUNE, now=1_000_000)
    second = requests.ask_film(hugo, DUNE, now=1_000_000 + EXPIRY - 60)
    assert requests.get(second["id"])["created"] == requests.get(first["id"])["created"]
    requests.expire(1_000_000 + EXPIRY + 60)
    assert requests.get(first["id"])["state"] == requests.get(second["id"])["state"] == "expired"


def test_existing_requests_get_their_film_where_it_is_known(store):
    _, requests, (lea, hugo, _) = store
    release = Release("a" * 40, "Dune.2021.1080p", 5 * GB, "Dune", "2021")
    old = requests.ask(lea, release)
    wish = requests.wish(hugo, "Ponyo")
    requests.link_films(lambda infohash: "tmdb-1" if infohash == "a" * 40 else "")
    assert requests.get(old["id"])["film"] == "tmdb-1" and requests.get(old["id"])["size"] == 5 * GB
    assert requests.get(wish["id"])["film"] == ""
    # A Member asking for that film now joins the migrated, still pending Request.
    joined = requests.ask_film(hugo, DUNE)
    assert joined["size"] == -(-5 * GB // 2)


# -- the Approver's side, through the web routes ------------------------------------------


@pytest.fixture
def server(tmp_path):
    app = create_app(
        tmp_path, members_enabled=True, password="test-password-long", monitor_verifications=False
    )
    seed_index(
        app.state.agent_service.media,
        {"1": ("Dune", "Dune", "2021", ["Science-Fiction"], "12", 155)},
        [
            ("c411", "a" * 40, "Dune.2021.MULTi.1080p.WEB.x264-TEAM", 4 * GB, 30, "1"),
            ("tr4ker", "b" * 40, "Dune.2021.MULTi.2160p.BluRay.x265-TEAM", 40 * GB, 5, "1"),
        ],
    )
    with TestClient(app) as browser:
        browser.headers["X-TorrentLinker"] = "1"
        yield app, browser


def test_the_approver_sees_one_group_with_the_films_releases_and_accepts_the_preselected(
    server, monkeypatch
):
    app, browser = server
    member(app, "lea", Permission.FILMS, Permission.REQUEST)
    member(app, "hugo", Permission.FILMS, Permission.REQUEST)
    for name in ("lea", "hugo"):
        sign_in(browser, name)
        asked = browser.post("/api/requests", json={"film": "tmdb-1"})
        assert asked.status_code == 200, asked.text
    mine = browser.get("/api/requests").json()["requests"][0]
    assert mine["shared_with"] == 1 and mine["infohash"] == ""
    assert "TEAM" not in browser.get("/api/requests").text
    browser.cookies.clear()
    login(browser)
    review = browser.get("/api/requests/review").json()["requests"]
    [entry] = [r for r in review if r["film"] == "tmdb-1"]
    assert sorted(entry["requesters"]) == ["Hugo", "Lea"] and len(entry["releases"]) == 2
    assert entry["releases"][0]["hash"] == entry["preselected"] and entry["quoted"] > 0
    assert isinstance(entry["below_threshold"], bool)
    sent = []
    monkeypatch.setattr(app.state.request_approval, "send", lambda infohash: sent.append(infohash))
    answered = browser.post(f"/api/requests/{entry['id']}/accept", json={})
    assert answered.status_code == 200 and answered.json()["state"] == "sent"
    assert sent == [entry["preselected"]]  # sent once, for both Members
    states = {r["state"] for r in app.state.requests.review(group=False)}
    assert states == {"sent"}


def test_the_approver_can_choose_another_release_and_read_its_description(server, monkeypatch):
    app, browser = server
    member(app, "lea", Permission.FILMS, Permission.REQUEST)
    sign_in(browser, "lea")
    identifier = browser.post("/api/requests", json={"film": "tmdb-1"}).json()["id"]
    assert browser.get(f"/api/requests/releases/{'a' * 40}/description").status_code == 403
    browser.cookies.clear()
    login(browser)
    monkeypatch.setattr(app.state.request_approval, "send", lambda infohash: None)
    chosen = browser.post(f"/api/requests/{identifier}/accept", json={"infohash": "b" * 40})
    assert chosen.json()["infohash"] == "b" * 40
    row = app.state.requests.get(identifier)
    assert row["chosen_size"] == 40 * GB and row["size"] <= row["quoted"]
    # The description is read from the Indexer; with none reachable it says so.
    answer = browser.get(f"/api/requests/releases/{'a' * 40}/description").json()
    assert answer["unavailable"] is True and answer["text"] == ""
