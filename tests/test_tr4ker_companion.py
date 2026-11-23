"""tr4ker's companion account: pairing, the filtered profile, the payout log, no secrets.

Every fixture is synthetic, built from the field names in docs/research/tr4ker-*.json. The fake
api_key, passkey and recovery values must never reach a stored file, a row or a response.
"""

import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from tests.test_web_jobs import login
from tests.test_web_profile import ORIGIN, OWNER, prepared, snapshot
from torrentlinker.tr4ker_profile import parse_payout, parse_profile, parse_shop

SECRETS = ("FAKE-API-KEY-9f3a", "FAKE-PASSKEY-77c1", "FAKE-TOTP-SECRET-0d5e", "FAKE-RECOVERY-aa12")

ME = {
    "id": 7,
    "username": "demo_t4k",
    "role": "member",
    "role_color": "#fff",
    "power": 1,
    "uploaded": 1000,
    "downloaded": 400,
    "bonus_upload": 100,
    "bonus_download": 0,
    "money": 250,
    "avatar_url": None,
    "bio": "hello",
    "joined_at": "2026-01-02T03:04:05Z",
    "last_seen_at": "2026-11-23T10:00:00Z",
    "personal_freeleech_until": None,
    "freeleech_global": False,
    "token_currency_name": "credits",
    "api_key": SECRETS[0],
    "passkey": SECRETS[1],
    "totp_enabled": True,
    "totp_secret": SECRETS[2],
    "recovery_codes": [SECRETS[3]],
}
STATS = {
    "freeleech_count": 3,
    "snapshots": [],
    "statistics": None,
    "summary": {
        "uploaded": 1000,
        "downloaded": 400,
        "raw_uploaded": 900,
        "raw_downloaded": 400,
        "bonus_upload": 100,
        "bonus_download": 0,
        "money": 250,
        "ratio_warning": False,
    },
}


def filtered_me():
    """What the companion sends: the same fields minus everything secret."""
    keep = (
        "id username role power uploaded downloaded bonus_upload bonus_download money joined_at"
        " last_seen_at personal_freeleech_until freeleech_global token_currency_name"
    ).split()
    return {k: ME[k] for k in keep} | {"id": str(ME["id"])}


def tr4ker_snapshot(account="7", **extra):
    return {
        "schema": 1,
        "source": "https://tr4ker.net",
        "tracker": "tr4ker",
        "capturedAt": datetime.now(UTC).isoformat(),
        "account": {"id": account, "username": "demo_t4k"},
        "me": filtered_me(),
        "stats": STATS,
        **extra,
    }


def pair(browser, account="7"):
    code = browser.post("/api/zen/profile/pairing?tracker=tr4ker", headers=OWNER).json()["code"]
    paired = browser.post(
        "/api/companion/pair",
        headers={"Origin": ORIGIN},
        json={"code": code, "accountId": account, "username": "demo_t4k", "tracker": "tr4ker"},
    )
    assert paired.status_code == 200, paired.text
    return {"Origin": ORIGIN, "Authorization": "Bearer " + paired.json()["token"]}


def test_profile_keeps_raw_and_bonus_apart_and_tolerates_empty_accounts():
    profile = parse_profile(ME, STATS)
    assert profile and (profile.account_id, profile.username) == ("7", "demo_t4k")
    assert (profile.raw_uploaded, profile.bonus_upload, profile.uploaded) == (900, 100, 1000)
    assert profile.ratio == pytest.approx(1100 / 400)
    assert profile.ratio_raw == pytest.approx(900 / 400)
    assert (profile.money, profile.freeleech_count, profile.ratio_warning) == (250, 3, False)
    bare = parse_profile({"id": "9", "username": "new"}, {"snapshots": [], "statistics": None})
    assert bare and bare.ratio is None and bare.money is None and bare.freeleech_count is None
    assert bare.badges == [] and bare.credit_multiplier is None
    assert parse_profile({"id": True, "username": "x"}) is None
    assert parse_profile({"username": "x"}) is None
    assert parse_profile("nope") is None
    # Wrong types become None instead of failing the whole profile.
    odd = parse_profile({"id": 1, "username": "u", "money": "lots", "uploaded": -5}, None)
    assert odd and odd.money is None and odd.uploaded is None


def test_badges_give_the_credit_multiplier_and_unknown_fields_are_ignored():
    stats = {
        **STATS,
        "badges": [
            {"name": "A", "power_type": "credit_multiplier", "power_value": 10, "extra": "x"},
            {"name": "B", "power_type": "credit_multiplier", "power_value": 25},
            {"name": "C", "power_type": "other", "power_value": 99},
            "junk",
        ],
    }
    profile = parse_profile(ME, stats)
    assert profile and profile.credit_multiplier == 25 and len(profile.badges) == 3


def test_a_profile_never_carries_a_secret_even_when_given_the_raw_me_body():
    blob = json.dumps(parse_profile(ME, STATS).as_dict())  # type: ignore[union-attr]
    for secret in SECRETS:
        assert secret not in blob
    assert "bio" not in blob and "avatar" not in blob


def test_payouts_parse_from_documented_names_and_ignore_the_rest():
    entry = {
        "id": 12,
        "amount": 35,
        "seeders": 4,
        "size_bytes": 5_000_000_000,
        "seedtime_seconds": 21600,
        "at": "2026-11-23T10:00:00+00:00",
        "slug": "some-film-2009",
        "category": "films",
        "multiplier": 10,
        "future_field": {"anything": 1},
    }
    payout = parse_payout(entry, 1_700_000_000.0)
    assert payout and payout.key == "id:12" and payout.amount == 35
    assert (payout.seeders, payout.size_bytes, payout.seedtime_seconds) == (4, 5_000_000_000, 21600)
    assert (payout.slug, payout.category, payout.multiplier) == ("some-film-2009", "films", 10)
    bare = parse_payout({"amount": 5})
    assert bare and bare.key.startswith("h:") and bare.seeders is None
    assert parse_payout({"amount": "5"}) is None and parse_payout({"seeders": 3}) is None
    assert parse_payout([1]) is None
    # The same content gives the same key: replays are idempotent without an id.
    assert (
        parse_payout({"amount": 5, "seeders": 2}).key
        == parse_payout(  # type: ignore[union-attr]
            {"amount": 5, "seeders": 2, "future": 1}
        ).key
    )


def test_shop_is_read_only_prices():
    items = parse_shop(
        {
            "items": [
                {"id": 1, "name": "+25 GB", "description": "x", "price": 400, "bonus_bytes": 25e9},
                {"name": "no id"},
            ]
        }
    )
    assert items and len(items) == 1 and (items[0].price, items[0].bonus_bytes) == (400, 25e9)
    assert parse_shop("nope") is None


def test_pairing_snapshot_and_payouts_flow_with_no_secret_on_disk(tmp_path, monkeypatch):
    app, setup = prepared(tmp_path, monkeypatch)
    with TestClient(app) as browser:
        login(browser)
        assert browser.get("/api/zen/profile").json()["tr4ker"]["paired"] is False
        # The pairing code belongs to the Owner's route, and tr4ker needs no c411 profile first.
        ext = pair(browser)
        state = browser.get("/api/zen/profile").json()["tr4ker"]
        assert state["paired"] and state["account"] == {"id": "7", "username": "demo_t4k"}
        sent = browser.post(
            "/api/companion/snapshot",
            headers=ext,
            json=tr4ker_snapshot(
                shop=[{"id": "1", "name": "+25 GB", "price": 400, "bonus_bytes": 25}]
            ),
        )
        assert sent.status_code == 200, sent.text
        state = browser.get("/api/zen/profile").json()["tr4ker"]
        assert state["available"] and state["profile"]["ratio"] == pytest.approx(2.75)
        assert state["shop"][0]["price"] == 400
        entries = [
            {"id": "a", "amount": 10, "seeders": 2, "size_bytes": 5, "seedtime_seconds": 21600},
            {"id": "b", "amount": 20, "at": "2026-11-23T10:00:00+00:00", "slug": "x"},
            {"amount": "bad"},
        ]
        body = {"tracker": "tr4ker", "accountId": "7", "entries": entries}
        first = browser.post("/api/companion/payouts", headers=ext, json=body)
        assert first.json() == {"accepted": 2, "added": 2}
        assert browser.post("/api/companion/payouts", headers=ext, json=body).json()["added"] == 0
        state = browser.get("/api/zen/profile").json()["tr4ker"]
        assert state["payouts"]["count"] == 2
        assert state["estimate"] == {"available": False, "payouts": 2, "needed": 30}
        # The c411 snapshot and API stay c411's.
        assert browser.get("/api/zen/profile").json()["companion"] is None
    dump = (tmp_path / "tr4ker-companion.json").read_text()
    assert (tmp_path / "tr4ker-companion.json").stat().st_mode & 0o777 == 0o600
    assert "Bearer" not in dump
    assert not any(secret in dump for secret in SECRETS)


def test_a_snapshot_made_from_the_raw_me_body_leaks_nothing(tmp_path, monkeypatch):
    app, setup = prepared(tmp_path, monkeypatch)
    with TestClient(app) as browser:
        login(browser)
        ext = pair(browser)
        raw = {**tr4ker_snapshot(), "me": ME}  # a companion that forgot to filter
        assert browser.post("/api/companion/snapshot", headers=ext, json=raw).status_code == 200
        response = browser.get("/api/zen/profile")
        assert not any(secret in response.text for secret in SECRETS)
    assert not any(secret in (tmp_path / "tr4ker-companion.json").read_text() for secret in SECRETS)
    import sqlite3

    rows = (
        sqlite3.connect(tmp_path / "catalogue.sqlite")
        .execute("SELECT payload FROM profile_history WHERE tracker = 'tr4ker'")
        .fetchall()
    )
    assert rows and not any(secret in row[0] for row in rows for secret in SECRETS)


def test_each_tracker_answers_only_for_itself(tmp_path, monkeypatch):
    app, setup = prepared(tmp_path, monkeypatch)
    with TestClient(app) as browser:
        login(browser)
        browser.post("/api/zen/profile/refresh", headers=OWNER)
        c411_code = browser.post("/api/zen/profile/pairing", headers=OWNER).json()["code"]
        c411 = browser.post(
            "/api/companion/pair",
            headers={"Origin": ORIGIN},
            json={"code": c411_code, "accountId": "42"},
        )
        c411_ext = {"Origin": ORIGIN, "Authorization": "Bearer " + c411.json()["token"]}
        t4k_ext = pair(browser)
        # A c411 token cannot sync tr4ker, and a tr4ker token cannot sync c411.
        assert (
            browser.post(
                "/api/companion/snapshot", headers={**c411_ext}, json=tr4ker_snapshot()
            ).status_code
            == 403
        )
        assert (
            browser.post("/api/companion/snapshot", headers=t4k_ext, json=snapshot()).status_code
            == 403
        )
        assert (
            browser.post(
                "/api/companion/snapshot", headers=t4k_ext, json={**snapshot(), "tracker": "c411"}
            ).status_code
            == 403
        )
        # A c411 pairing code cannot pair tr4ker.
        code = browser.post("/api/zen/profile/pairing", headers=OWNER).json()["code"]
        bad = browser.post(
            "/api/companion/pair",
            headers={"Origin": ORIGIN},
            json={"code": code, "accountId": "7", "tracker": "tr4ker"},
        )
        assert bad.status_code == 403
        # tr4ker never takes c411's routes (downloads, community), nor an unknown Tracker.
        for route in ("commands", "result", "actions-demand", "creation"):
            assert (
                browser.post(
                    f"/api/companion/{route}", headers=t4k_ext, json={"tracker": "tr4ker"}
                ).status_code
                == 403
            )
        assert (
            browser.post(
                "/api/companion/snapshot", headers=t4k_ext, json={"tracker": "nope"}
            ).status_code
            == 400
        )
        assert (
            browser.post(
                "/api/companion/payouts", headers=c411_ext, json={"accountId": "42", "entries": []}
            ).status_code
            == 400
        )
        # Unpairing one leaves the other.
        browser.post("/api/zen/profile/disconnect?tracker=tr4ker", headers=OWNER)
        state = browser.get("/api/zen/profile").json()
        assert state["paired"] and not state["tr4ker"]["paired"]
        assert (
            browser.post(
                "/api/companion/snapshot", headers=t4k_ext, json=tr4ker_snapshot()
            ).status_code
            == 403
        )


def test_account_binding_rejects_another_account_old_and_stale_snapshots(tmp_path, monkeypatch):
    app, setup = prepared(tmp_path, monkeypatch)
    with TestClient(app) as browser:
        login(browser)
        ext = pair(browser)
        post = lambda body: browser.post("/api/companion/snapshot", headers=ext, json=body)  # noqa: E731
        assert post(tr4ker_snapshot("8")).status_code == 403
        assert post({**tr4ker_snapshot(), "me": {**filtered_me(), "id": "8"}}).status_code == 403
        stale = {**tr4ker_snapshot(), "capturedAt": "2020-01-01T00:00:00+00:00"}
        assert post(stale).status_code == 400
        assert post({**tr4ker_snapshot(), "extra": 1}).status_code == 400
        value = tr4ker_snapshot()
        assert post(value).status_code == 200
        assert post(value).status_code == 400  # replay
        wrong = {"tracker": "tr4ker", "accountId": "8", "entries": []}
        assert browser.post("/api/companion/payouts", headers=ext, json=wrong).status_code == 403
        too_many = {"tracker": "tr4ker", "accountId": "7", "entries": [{"amount": 1}] * 101}
        assert browser.post("/api/companion/payouts", headers=ext, json=too_many).status_code == 400


def test_pairing_codes_are_single_use_and_cancellable(tmp_path, monkeypatch):
    app, setup = prepared(tmp_path, monkeypatch)
    with TestClient(app) as browser:
        login(browser)
        body = lambda code: {"code": code, "accountId": "7", "tracker": "tr4ker"}  # noqa: E731
        code = browser.post("/api/zen/profile/pairing?tracker=tr4ker", headers=OWNER).json()["code"]
        assert browser.get("/api/zen/profile").json()["tr4ker"]["pending"]
        browser.post("/api/zen/profile/pairing/cancel?tracker=tr4ker", headers=OWNER)
        assert not browser.get("/api/zen/profile").json()["tr4ker"]["pending"]
        assert (
            browser.post(
                "/api/companion/pair", headers={"Origin": ORIGIN}, json=body(code)
            ).status_code
            == 403
        )
        code = browser.post("/api/zen/profile/pairing?tracker=tr4ker", headers=OWNER).json()["code"]
        assert (
            browser.post(
                "/api/companion/pair", headers={"Origin": ORIGIN}, json=body(code)
            ).status_code
            == 200
        )
        assert (
            browser.post(
                "/api/companion/pair", headers={"Origin": ORIGIN}, json=body(code)
            ).status_code
            == 403
        )
        assert (
            browser.post("/api/zen/profile/pairing?tracker=nope", headers=OWNER).status_code == 409
        )


def test_pairing_survives_a_restart_and_the_payout_log_survives_unpairing(tmp_path, monkeypatch):
    from torrentlinker.profile_workspace import ProfileWorkspace

    app, setup = prepared(tmp_path, monkeypatch)
    with TestClient(app) as browser:
        login(browser)
        ext = pair(browser)
        entries = [{"id": "a", "amount": 10}]
        browser.post(
            "/api/companion/payouts",
            headers=ext,
            json={"tracker": "tr4ker", "accountId": "7", "entries": entries},
        )
    again = ProfileWorkspace(tmp_path, history=setup.profile_workspace().history)
    assert again.state()["tr4ker"]["paired"]
    assert again.state()["tr4ker"]["payouts"]["count"] == 1
    again.disconnect("tr4ker")
    assert not again.state()["tr4ker"]["paired"]
    assert again.tr4ker.store.tr4ker_payout_count("7") == 1  # type: ignore[union-attr]
