import base64

import pytest
from fastapi.testclient import TestClient

from tests.test_web_profile import ORIGIN, OWNER, login, prepared
from tests.torrents import make_torrent
from torrentlinker.torrent_meta import read_torrent


def pair(browser):
    login(browser)
    browser.post("/api/zen/profile/refresh", headers=OWNER)
    code = browser.post("/api/zen/profile/pairing", headers=OWNER).json()["code"]
    token = browser.post(
        "/api/companion/pair", headers={"Origin": ORIGIN}, json={"code": code, "accountId": "42"}
    ).json()["token"]
    return {"Origin": ORIGIN, "Authorization": "Bearer " + token}


def test_session_metadata_test_validates_and_discards_without_client(tmp_path, monkeypatch):
    app, _ = prepared(tmp_path, monkeypatch)
    content = tmp_path / "sample.txt"
    content.write_text("A harmless test file")
    torrent = make_torrent(content)
    infohash = read_torrent(torrent).infohash
    with TestClient(app) as browser:
        ext = pair(browser)
        browser.post("/api/companion/commands", headers=ext, json={})
        response = browser.post(
            "/api/zen/profile/download-tests",
            headers=OWNER,
            json={"infohash": infohash, "request_id": "test-1"},
        )
        assert response.status_code == 200
        job = response.json()
        command = browser.post("/api/companion/commands", headers=ext, json={}).json()["command"]
        assert command["infohash"] == infohash
        assert command["accountId"] == "42"
        assert (
            browser.post("/api/companion/commands", headers=ext, json={}).json()["command"] is None
        )
        sent = browser.post(
            "/api/companion/result",
            headers=ext,
            json={
                "id": job["id"],
                "accountId": "42",
                "status": 200,
                "data": base64.b64encode(torrent).decode(),
            },
        )
        assert sent.status_code == 200
        result = browser.get("/api/zen/profile/download-tests/" + job["id"]).json()
        assert result["status"] == "complete"
        assert result["bytes"] == len(torrent)
        assert result["infohash"] == infohash
        assert result["discarded"] is True
        assert "data" not in result and "announce" not in str(result)
        again = browser.post(
            "/api/zen/profile/download-tests",
            headers=OWNER,
            json={"infohash": infohash, "request_id": "test-1"},
        ).json()
        assert again["id"] == job["id"]
        assert (
            browser.post("/api/companion/commands", headers=ext, json={}).json()["command"] is None
        )


@pytest.mark.parametrize("status", [401, 403, 429])
def test_session_refusal_stops_subsequent_requests(tmp_path, monkeypatch, status):
    app, _ = prepared(tmp_path, monkeypatch)
    with TestClient(app) as browser:
        ext = pair(browser)
        browser.post("/api/companion/commands", headers=ext, json={})
        job = browser.post(
            "/api/zen/profile/download-tests",
            headers=OWNER,
            json={"infohash": "a" * 40, "request_id": "first"},
        ).json()
        browser.post("/api/companion/commands", headers=ext, json={})
        result = browser.post(
            "/api/companion/result",
            headers=ext,
            json={
                "id": job["id"],
                "accountId": "42",
                "status": status,
                "retryAfter": 123,
                "error": "secret tracker response must not escape",
            },
        )
        assert result.status_code == 200
        second = browser.post(
            "/api/zen/profile/download-tests",
            headers=OWNER,
            json={"infohash": "b" * 40, "request_id": "second"},
        )
        assert second.status_code == 409
        result = browser.get("/api/zen/profile/download-tests/" + job["id"]).json()
        assert result["http_status"] == status
        assert "secret" not in str(result)
        assert result["discarded"]


def test_session_tests_reject_wrong_account_content_and_replay(tmp_path, monkeypatch):
    app, setup = prepared(tmp_path, monkeypatch)
    with TestClient(app) as browser:
        ext = pair(browser)
        browser.post("/api/companion/commands", headers=ext, json={})
        job = browser.post(
            "/api/zen/profile/download-tests",
            headers=OWNER,
            json={"infohash": "a" * 40, "request_id": "invalid"},
        ).json()
        browser.post("/api/companion/commands", headers=ext, json={})
        body = {
            "id": job["id"],
            "accountId": "other",
            "status": 200,
            "data": base64.b64encode(b"<html>login</html>").decode(),
        }
        assert browser.post("/api/companion/result", headers=ext, json=body).status_code == 403
        body["accountId"] = "42"
        assert browser.post("/api/companion/result", headers=ext, json=body).status_code == 200
        result = browser.get("/api/zen/profile/download-tests/" + job["id"]).json()
        assert result["status"] == "failed"
        assert "login" not in str(result)
        assert browser.post("/api/companion/result", headers=ext, json=body).status_code == 400
        browser.post("/api/zen/profile/disconnect", headers=OWNER)
        assert browser.get("/api/zen/profile/download-tests/" + job["id"]).status_code == 404
        assert browser.post("/api/companion/commands", headers=ext, json={}).status_code == 403


def test_mcp_descriptor_tools_require_execute_downloads_and_hide_other_agents(
    tmp_path, monkeypatch
):
    from tests.test_agent_media import invoke
    from torrentlinker.agent.access import Grant

    app, _ = prepared(tmp_path, monkeypatch)
    with TestClient(app) as browser:
        ext = pair(browser)
        browser.post("/api/companion/commands", headers=ext, json={})
        access = app.state.agent_service.access
        access.enable(True)
        read_only = access.create(Grant(name="Read only", clients=["default"]))["id"]
        allowed = access.create(
            Grant(name="Authorized", clients=["default"], mode="execute", permissions=["downloads"])
        )["id"]
        assert invoke(app, read_only, "companion_status")["available"]
        assert "error" in invoke(
            app, read_only, "test_companion_download", infohash="a" * 40, request_id="one"
        )
        job = invoke(app, allowed, "test_companion_download", infohash="a" * 40, request_id="one")
        assert job["status"] == "pending"
        assert "error" in invoke(app, read_only, "get_companion_download_test", test_id=job["id"])
        assert invoke(app, allowed, "get_companion_download_test", test_id=job["id"]) == job


def test_batch_poll_hands_out_bounded_sequential_work_and_stops_after_failure(
    tmp_path, monkeypatch
):
    app, _ = prepared(tmp_path, monkeypatch)
    with TestClient(app) as browser:
        ext = pair(browser)
        browser.post("/api/companion/commands", headers=ext, json={})
        ids = [
            browser.post(
                "/api/zen/profile/download-tests",
                headers=OWNER,
                json={"infohash": f"{n:040x}", "request_id": f"batch-{n}"},
            ).json()["id"]
            for n in range(30)
        ]
        first = browser.post("/api/companion/commands", headers=ext, json={"limit": 25}).json()
        assert [c["id"] for c in first["commands"]] == ids[:25]
        assert first["command"]["id"] == ids[0]
        # A 404 is only that torrent; any other failure cancels what is still queued.
        missing = {"id": ids[0], "accountId": "42", "status": 404}
        assert browser.post("/api/companion/result", headers=ext, json=missing).status_code == 200
        assert browser.get("/api/zen/profile/download-tests/" + ids[27]).json()["status"] == (
            "pending"
        )
        slow = {"id": ids[2], "accountId": "42", "status": 0, "reason": "timeout"}
        browser.post("/api/companion/result", headers=ext, json=slow)
        assert browser.get("/api/zen/profile/download-tests/" + ids[27]).json()["status"] == (
            "pending"
        )
        failed = {"id": ids[1], "accountId": "42", "status": 0, "reason": "network"}
        browser.post("/api/companion/result", headers=ext, json=failed)
        cancelled = browser.get("/api/zen/profile/download-tests/" + ids[27]).json()
        assert cancelled["status"] == "failed"
        assert "Cancelled" in cancelled["error"]
        assert browser.get("/api/zen/profile/download-tests/" + ids[1]).json()["reason"] == (
            "network"
        )


def test_blocked_or_rate_limited_session_hands_out_no_more_work(tmp_path, monkeypatch):
    app, _ = prepared(tmp_path, monkeypatch)
    with TestClient(app) as browser:
        ext = pair(browser)
        browser.post("/api/companion/commands", headers=ext, json={})
        job = browser.post(
            "/api/zen/profile/download-tests",
            headers=OWNER,
            json={"infohash": "a" * 40, "request_id": "one"},
        ).json()
        browser.post("/api/companion/commands", headers=ext, json={"limit": 25})
        browser.post(
            "/api/companion/result",
            headers=ext,
            json={"id": job["id"], "accountId": "42", "status": 429, "retryAfter": 120},
        )
        assert browser.post(
            "/api/companion/commands", headers=ext, json={"limit": 25}
        ).json() == {"command": None, "commands": [], "concurrency": 1}


def test_concurrency_is_bounded_and_reaches_the_companion(tmp_path, monkeypatch):
    from tests.test_agent_media import invoke
    from torrentlinker.agent.access import Grant

    app, _ = prepared(tmp_path, monkeypatch)
    with TestClient(app) as browser:
        ext = pair(browser)
        assert browser.post("/api/companion/commands", headers=ext, json={}).json()[
            "concurrency"
        ] == 1
        access = app.state.agent_service.access
        access.enable(True)
        read_only = access.create(Grant(name="Read only", clients=["default"]))["id"]
        allowed = access.create(
            Grant(name="Authorized", clients=["default"], mode="execute", permissions=["downloads"])
        )["id"]
        assert "error" in invoke(app, read_only, "set_companion_concurrency", concurrency=2)
        assert "error" in invoke(app, allowed, "set_companion_concurrency", concurrency=17)
        assert invoke(app, allowed, "set_companion_concurrency", concurrency=3) == {
            "concurrency": 3
        }
        assert browser.post("/api/companion/commands", headers=ext, json={}).json()[
            "concurrency"
        ] == 3


def test_fresh_downloads_default_to_one_request_at_a_time():
    from torrentlinker.companion_downloads import CompanionDownloads

    assert CompanionDownloads(lambda: 0.0).state()["concurrency"] == 1
