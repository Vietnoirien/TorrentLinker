from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.test_agent_access import call, rpc
from tests.test_web_jobs import Client, finished, login
from torrentlinker.domain import Torrent
from torrentlinker.web.app import create_app


class SelectionClient(Client):
    def __init__(self, torrents):
        super().__init__()
        self.release.set()
        self.items = torrents

    def torrents(self, **kwargs):
        return self.items

    def torrent(self, hash, **kwargs):
        return next((t for t in self.items if t.hash == hash), None)


def book(number, size, **kwargs):
    return Torrent(
        f"{number:040x}",
        f"Book {number}",
        Path("/media"),
        size=size,
        state=kwargs.pop("state", "uploading"),
        tracker=kwargs.pop("tracker", "https://c411.org/announce/private"),
        swarm_seeders=kwargs.pop("swarm_seeders", 1000),
        category=kwargs.pop("category", "Ebook/Livres"),
        **kwargs,
    )


def connect(browser, **kwargs):
    login(browser)
    browser.post("/api/setup/client", json={"client": "deluge", "host": "https://box.example"})
    grant = browser.post(
        "/api/agents", json={"name": "Selector", "clients": ["default"], **kwargs}
    ).json()
    browser.put("/api/agents", json={"enabled": True})
    return grant["token"]


def select(browser, token, **criteria):
    response = call(
        browser,
        token,
        "select_torrents",
        {"request_id": "select-books", "client_id": "default", "criteria": criteria},
    )
    assert not response.get("isError"), response
    submitted = response["structuredContent"]
    assert "job_id" in submitted, submitted
    assert finished(browser, submitted["job_id"])["status"] == "completed"
    return submitted["job_id"]


def test_mcp_selects_exactly_1000_across_the_entire_client_not_one_page(tmp_path):
    client = SelectionClient(
        [book(i, i * 1024**2) for i in range(1, 1006)]
        + [book(2000, 10 * 1024**3, seeding_time=365 * 86400)]
        + [book(2001, 20 * 1024**3, category="Films")]
        + [book(2002, 30 * 1024**3, state="pausedUP")]
        + [book(2003, 40 * 1024**3, tags=frozenset({"torrentlinker:verifying"}))]
    )
    with TestClient(
        create_app(tmp_path, password="test-password-long", connector=lambda *args: client)
    ) as browser:
        token = connect(browser, mode="execute", permissions=["controls"])
        names = {t["name"] for t in rpc(browser, token, "tools/list").json()["result"]["tools"]}
        assert "select_torrents" in names
        selection_id = select(browser, token, category="Ebook", count=1000)
        preview = call(browser, token, "job_status", {"job_id": selection_id})["structuredContent"][
            "result"
        ]
        assert preview["selected_count"] == 1000
        assert preview["eligible_count"] == 1006
        assert preview["shortfall"] == 0
        assert preview["total_size_bytes"] == 530055168000
        assert len(preview["rows"]) == 50
        assert preview["rows"][0]["hash"] == f"{1005:040x}"
        last = call(
            browser, token, "job_status", {"job_id": selection_id, "offset": 999, "limit": 1}
        )["structuredContent"]["result"]
        assert last["rows"][0]["hash"] == f"{6:040x}"
        assert client.paused == []
        action = call(
            browser,
            token,
            "manage_selection",
            {"request_id": "pause-1000", "selection_id": selection_id, "action": "pause"},
        )["structuredContent"]
        assert finished(browser, action["job_id"])["status"] == "completed"
        assert len(client.paused) == len(set(client.paused)) == 1000
        assert f"{5:040x}" not in client.paused
        assert f"{2000:040x}" not in client.paused


def test_selection_action_uses_saved_hashes_and_existing_owner_approval(tmp_path):
    client = SelectionClient([book(1, 1024), book(2, 4096), book(3, 4096)])
    with TestClient(
        create_app(tmp_path, password="test-password-long", connector=lambda *args: client)
    ) as browser:
        token = connect(browser)
        selection_id = select(browser, token, count=2)
        arguments = {
            "request_id": "pause-selection",
            "selection_id": selection_id,
            "action": "pause",
        }
        response = call(browser, token, "manage_selection", arguments)
        assert not response.get("isError"), response
        proposal = response["structuredContent"]
        assert proposal["requires_owner_approval"] is True
        assert client.paused == []
        approved = browser.post(f"/api/agents/proposals/{proposal['id']}/approve")
        assert approved.status_code == 200, approved.text
        done = finished(browser, approved.json()["job_id"])
        assert done["status"] == "completed"
        assert done["result"]["outcomes"] == {"sent": 2}
        assert done["result"]["attempted_count"] == 2
        assert client.paused == [f"{2:040x}", f"{3:040x}"]
        retry = call(browser, token, "manage_selection", arguments)["structuredContent"]
        assert retry["job_id"] == approved.json()["job_id"]
        assert len(client.paused) == 2


def test_selection_excludes_unknown_metrics_and_does_not_pad_a_shortfall(tmp_path):
    client = SelectionClient(
        [
            book(1, 1024, tracker="https://tk.c411.tw/announce/private"),
            book(2, 4096, tracker="https://other.example/announce"),
            book(3, 8192, swarm_seeders=-1),
        ]
    )
    with TestClient(
        create_app(tmp_path, password="test-password-long", connector=lambda *args: client)
    ) as browser:
        token = connect(browser)
        identifier = select(browser, token, count=5)
        result = call(browser, token, "job_status", {"job_id": identifier})["structuredContent"][
            "result"
        ]
        assert result["selected_count"] == 1
        assert result["shortfall"] == 4
        assert result["excluded"]["unknown_metric"] == 2
        assert result["rows"][0]["hash"] == f"{1:040x}"


@pytest.mark.parametrize("change", ["missing", "paused", "new-best", "verifying"])
def test_selection_that_changes_before_approval_fails_without_substitutions(tmp_path, change):
    client = SelectionClient([book(1, 1024), book(2, 4096)])
    with TestClient(
        create_app(tmp_path, password="test-password-long", connector=lambda *args: client)
    ) as browser:
        token = connect(browser)
        identifier = select(browser, token, count=1)
        proposal = call(
            browser,
            token,
            "manage_selection",
            {"request_id": "pause", "selection_id": identifier, "action": "pause"},
        )["structuredContent"]
        if change == "missing":
            client.items.pop()
        elif change == "paused":
            client.items[-1] = replace(client.items[-1], state="pausedUP")
        elif change == "new-best":
            client.items.append(book(3, 8192))
        else:
            client.items[-1] = replace(
                client.items[-1], tags=frozenset({"torrentlinker:verifying"})
            )
        approved = browser.post(f"/api/agents/proposals/{proposal['id']}/approve")
        assert approved.status_code == 200
        result = finished(browser, approved.json()["job_id"])
        assert result["status"] == "failed"
        assert "selection changed" in result["error"]
        assert client.paused == []


def test_selection_is_private_and_remove_always_needs_owner_approval(tmp_path):
    client = SelectionClient([book(1, 1024)])
    with TestClient(
        create_app(tmp_path, password="test-password-long", connector=lambda *args: client)
    ) as browser:
        token = connect(browser, mode="execute", permissions=["controls"])
        identifier = select(browser, token, count=1)
        other = browser.post("/api/agents", json={"name": "Other", "clients": ["default"]}).json()
        arguments = {"request_id": "remove", "selection_id": identifier, "action": "remove"}
        result = call(browser, other["token"], "manage_selection", arguments)["structuredContent"]
        assert "error" in result
        result = call(browser, token, "manage_selection", arguments)["structuredContent"]
        assert result["requires_owner_approval"] is True
        assert client.paused == []


def test_expired_selection_requires_a_new_preview(tmp_path, monkeypatch):
    import time

    client = SelectionClient([book(1, 1024)])
    with TestClient(
        create_app(tmp_path, password="test-password-long", connector=lambda *args: client)
    ) as browser:
        token = connect(browser, mode="execute", permissions=["controls"])
        identifier = select(browser, token, count=1)
        later = time.time() + 901
        monkeypatch.setattr(time, "time", lambda: later)
        result = call(
            browser,
            token,
            "manage_selection",
            {"request_id": "pause", "selection_id": identifier, "action": "pause"},
        )["structuredContent"]
        assert "expired" in result["error"]
        assert client.paused == []


@pytest.mark.parametrize("ranking", ["largest_size", "lowest_zen_per_gib"])
def test_rankings_and_tracker_mirrors_use_the_same_selection_workflow(tmp_path, ranking):
    client = SelectionClient(
        [
            book(1, 1024**3, tracker="https://tk.c411.tw/announce/private"),
            book(2, 3 * 1024**3),
            book(3, 50 * 1024**3, tracker="https://other.example/announce"),
        ]
    )
    with TestClient(
        create_app(tmp_path, password="test-password-long", connector=lambda *args: client)
    ) as browser:
        token = connect(browser)
        identifier = select(browser, token, count=5, tracker="tk.c411.tw", ranking=ranking)
        preview = call(browser, token, "job_status", {"job_id": identifier})["structuredContent"][
            "result"
        ]
        assert [r["hash"] for r in preview["rows"]] == [f"{2:040x}", f"{1:040x}"]
        assert preview["selected_count"] == 2
        assert preview["shortfall"] == 3


def test_failed_refresh_cannot_reuse_an_earlier_selection_snapshot(tmp_path):
    class DisconnectableClient(SelectionClient):
        online = True

        def torrents(self, **kwargs):
            if not self.online:
                raise ConnectionError("Offline")
            return super().torrents(**kwargs)

    client = DisconnectableClient([book(1, 1024)])
    with TestClient(
        create_app(tmp_path, password="test-password-long", connector=lambda *args: client)
    ) as browser:
        token = connect(browser, mode="execute", permissions=["controls"])
        identifier = select(browser, token, count=1)
        client.online = False
        action = call(
            browser,
            token,
            "manage_selection",
            {"request_id": "pause", "selection_id": identifier, "action": "pause"},
        )["structuredContent"]
        assert finished(browser, action["job_id"])["status"] == "failed"
        assert client.paused == []


def test_selection_cannot_be_retargeted_or_given_extra_hashes(tmp_path):
    client = SelectionClient([book(1, 1024), book(2, 4096)])
    with TestClient(
        create_app(tmp_path, password="test-password-long", connector=lambda *args: client)
    ) as browser:
        token = connect(browser, mode="execute", permissions=["controls"])
        identifier = select(browser, token, count=1)
        result = call(
            browser,
            token,
            "propose_action",
            {
                "request_id": "tampered",
                "operation": {
                    "kind": "manage",
                    "client_id": "default",
                    "action": "pause",
                    "selection_id": identifier,
                    "selection": {"count": 1},
                    "hashes": [f"{1:040x}", f"{2:040x}"],
                },
            },
        )["structuredContent"]
        assert "error" in result
        assert client.paused == []


def test_smallest_client_selection_supports_title_and_size_filters(tmp_path):
    client = SelectionClient([book(1, 0), book(2, 10), book(3, 20), book(4, 30), book(5, 40)])
    with TestClient(
        create_app(tmp_path, password="test-password-long", connector=lambda *args: client)
    ) as browser:
        token = connect(browser)
        identifier = select(
            browser,
            token,
            category="Ebook",
            ranking="smallest_size",
            query="Book",
            min_size_bytes=15,
            max_size_bytes=35,
            count=10,
        )
        result = call(browser, token, "job_status", {"job_id": identifier})["structuredContent"][
            "result"
        ]
        assert [r["hash"] for r in result["rows"]] == [f"{3:040x}", f"{4:040x}"]
        assert result["total_size_bytes"] == 50
        assert result["shortfall"] == 8
