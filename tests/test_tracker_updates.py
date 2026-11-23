"""Tracker updates retain unrelated URLs, tiers and each account's private key."""

import json
import threading
from types import SimpleNamespace

import pytest

from torrentlinker.agent.service import AgentRequest
from torrentlinker.config import Settings
from torrentlinker.tracker_updates import (
    Announce,
    TrackerUpdates,
    fingerprint,
    host_name,
    plan_change,
)

HOSTS = ["c411.org", "tk.c411.tw"]
OLD = "old-private-key"
NEW = "new-private-key"
URL = f"https://c411.org/{OLD}/announce"
SAVED = f"https://c411.org/announce/{NEW}"
OTHER = Announce("https://other.example/announce?passkey=other-private-key", 4)


def plan(entries, action, **kwargs):
    return plan_change(entries, action, configured=HOSTS, settings_announce=SAVED, **kwargs)


def test_host_move_keeps_path_query_passkey_tier_and_unrelated_tracker():
    first = Announce(f"https://c411.org:443/announce/{OLD}?x=%2F", 2)
    result = plan([first, OTHER], "replace-host", source_host="c411.org", target_host="tk.c411.tw")
    assert result.after == (Announce(f"https://tk.c411.tw:443/announce/{OLD}?x=%2F", 2), OTHER)
    assert OLD not in repr(result)
    assert result.groups == (fingerprint(OLD),)


def test_backup_uses_torrents_key_in_later_tier_and_is_idempotent():
    result = plan([Announce(URL, 1), OTHER], "add-backup", target_host="tk.c411.tw")
    assert result.after == (
        Announce(URL, 1),
        OTHER,
        Announce(f"https://tk.c411.tw/{OLD}/announce", 5),
    )
    assert not plan(list(result.after), "add-backup", target_host="tk.c411.tw").changed


@pytest.mark.parametrize(
    "url",
    [URL, f"https://c411.org/announce/{OLD}", f"https://c411.org/announce?x=%2F&passkey={OLD}&y=2"],
)
def test_passkey_changes_only_explicit_selected_group(url):
    first = Announce(url)
    untouched = Announce("https://tk.c411.tw/another-account/announce", 1)
    result = plan([first, untouched, OTHER], "update-passkey", groups=[fingerprint(OLD)])
    assert result.after[0].url == url.replace(OLD, NEW)
    assert result.after[1:] == (untouched, OTHER)
    assert not plan([first], "update-passkey", groups=[]).changed


def test_mixed_keys_are_not_implicitly_copied_to_backup():
    result = plan(
        [Announce(URL), Announce("https://a.c411.org/other/announce")],
        "add-backup",
        target_host="tk.c411.tw",
    )
    assert result.reason == "mixed_passkeys"
    assert not result.changed


def test_unrecognized_passkey_and_target_collision_are_skipped():
    assert (
        plan([Announce("https://c411.org/unknown")], "add-backup", target_host="tk.c411.tw").reason
        == "unsupported_passkey_format"
    )
    duplicate = plan(
        [Announce(URL), Announce(URL.replace("c411.org", "tk.c411.tw"), 1)],
        "replace-host",
        source_host="c411.org",
        target_host="tk.c411.tw",
    )
    assert duplicate.reason == "duplicate_target"
    assert not duplicate.changed


@pytest.mark.parametrize(
    "host", ["https://c411.org/key", "c411.org:443", "user@c411.org", "c411.org/path", "localhost"]
)
def test_host_input_never_accepts_urls_or_credentials(host):
    with pytest.raises(ValueError):
        host_name(host)


def test_automatic_backup_cannot_send_passkey_to_unconfigured_host():
    with pytest.raises(ValueError, match="Settings"):
        plan([Announce(URL)], "add-backup", target_host="c411.org.attacker.example")


class Client:
    def __init__(self):
        self.entries = [Announce(URL), OTHER]
        self.writes = []
        self.announced = []

    def torrents(self, **_):
        return [SimpleNamespace(hash="a" * 40, tracker=URL, trackers=(URL, OTHER.url))]

    def announce_entries(self, hash):
        return list(self.entries)

    def apply_announces(self, hash, before, after):
        self.writes.append((hash, before, after))
        self.entries = list(after)

    def reannounce(self, hash):
        self.announced.append(hash)


def service():
    client = Client()
    settings = Settings(announce_hosts=HOSTS)
    settings.ensure_profiles()
    setup = SimpleNamespace(
        settings=settings,
        secrets=SimpleNamespace(get=lambda key: SAVED if key == "announce-url" else ""),
        snapshot=lambda: {"client": "fixture"},
        client=lambda: client,
    )
    setup.for_client = lambda _: setup
    return TrackerUpdates(setup), client


def preview(updates, action="add-backup", groups=None):
    return updates.preview(
        ["default"],
        action,
        "c411.org",
        "tk.c411.tw",
        groups or [],
        threading.Event(),
        lambda _: None,
    )


def apply(updates, row, groups=None):
    return updates.apply(
        row["preview_id"],
        ["default"],
        row["action"],
        threading.Event(),
        lambda _: None,
        "c411.org",
        "tk.c411.tw",
        groups or [],
    )


def test_preview_includes_external_torrents_redacts_keys_and_is_consumed_once():
    updates, client = service()
    row = preview(updates)
    assert row["counts"] == {"update": 1}
    assert row["settings_group"] == fingerprint(NEW)
    assert OLD not in json.dumps(row) and NEW not in json.dumps(row)
    assert "https://" not in json.dumps(row)
    assert not client.writes
    result = apply(updates, row)
    assert result["rows"][0]["status"] == "updated"
    assert client.announced == ["a" * 40]
    with pytest.raises(ValueError, match="expired"):
        apply(updates, row)
    assert len(client.writes) == 1


def test_changed_trackers_or_reviewed_intent_are_not_overwritten():
    updates, client = service()
    row = preview(updates)
    with pytest.raises(ValueError, match="match"):
        apply(updates, row, [fingerprint(OLD)])
    client.entries.append(Announce("https://other.example/new", 8))
    result = apply(updates, row)
    assert result["rows"][0]["status"] == "changed_since_preview"
    assert not client.writes


def test_uncertain_client_error_is_sanitized_and_never_retried():
    updates, client = service()
    row = preview(updates)

    def failed(*_):
        raise RuntimeError(URL)

    client.apply_announces = failed
    result = apply(updates, row)
    assert result["rows"][0]["status"] == "uncertain"
    assert OLD not in json.dumps(result)
    with pytest.raises(ValueError):
        apply(updates, row)


def test_host_and_passkey_proposals_require_owner_but_backup_does_not():
    for action in ("replace-host", "update-passkey"):
        assert AgentRequest(kind="tracker-update", tracker_action=action).requires_owner_approval()
    assert not AgentRequest(
        kind="tracker-update", tracker_action="add-backup"
    ).requires_owner_approval()


def test_preview_aggregates_counts_by_host_and_passkey():
    updates, _ = service()
    result = preview(updates)
    assert result["hosts"] == {"c411.org": {"update": 1}}
    assert result["groups"] == {fingerprint(OLD): {"update": 1}}


def test_changed_settings_and_expired_previews_never_write(monkeypatch):
    updates, client = service()
    result = preview(updates)
    updates.setup.settings.announce_hosts = ["next.c411.org"]
    with pytest.raises(ValueError, match="Settings changed"):
        apply(updates, result)
    monkeypatch.setattr("time.monotonic", lambda: 10**15)
    with pytest.raises(ValueError, match="expired"):
        apply(updates, result)
    assert not client.writes


def test_mcp_tracker_preview_permissions_and_owner_approval(tmp_path):
    from fastapi.testclient import TestClient

    from tests.test_agent_access import call
    from tests.test_web_jobs import finished, login
    from torrentlinker.web.app import create_app

    client = Client()
    client.check = lambda: "fixture"
    client.folder_settings = lambda: []
    app = create_app(tmp_path, password="test-password-long", connector=lambda *args: client)
    with TestClient(app) as browser:
        login(browser)
        assert browser.post(
            "/api/setup/client", json={"client": "qbittorrent", "host": "http://fake"}
        ).is_success
        setup = app.state.agent_service.setup
        setup.secrets.update({"announce-url": SAVED})
        setup.settings.announce_hosts = HOSTS
        setup.save()
        browser.put("/api/agents", json={"enabled": True})
        grant = browser.post(
            "/api/agents",
            json={
                "name": "Tracker helper",
                "clients": ["default"],
                "mode": "execute",
                "permissions": ["controls"],
            },
        ).json()
        token = grant["token"]
        for action in ("replace-host", "update-passkey", "add-backup"):
            arguments = dict(
                client_ids=["default"],
                action=action,
                source_host="c411.org",
                target_host="tk.c411.tw",
                passkey_groups=[fingerprint(OLD)],
            )
            response = call(
                browser,
                token,
                "update_c411_trackers",
                dict(request_id=action + "-preview", **arguments),
            )
            assert not response.get("isError"), response
            job = finished(browser, response["structuredContent"]["job_id"])
            assert job["status"] == "completed", job
            preview_id = job["result"]["preview_id"]
            response = call(
                browser,
                token,
                "update_c411_trackers",
                dict(request_id=action + "-apply", preview_id=preview_id, **arguments),
            )
            assert not response.get("isError"), response
            proposal = response["structuredContent"]
            if action != "add-backup":
                assert proposal["status"] == "pending"
                assert not client.writes
            else:
                job = finished(browser, proposal["job_id"])
                assert job["status"] == "completed", job
                assert job["result"]["rows"][0]["status"] == "updated"
        history = browser.get("/api/jobs").text
        assert OLD not in history and NEW not in history and URL not in history
        restricted = browser.post(
            "/api/agents", json={"name": "Reader", "clients": ["default"]}
        ).json()
        response = call(
            browser,
            restricted["token"],
            "update_c411_trackers",
            dict(request_id="denied", **arguments),
        )
        assert "controls" in response["structuredContent"]["error"]


def test_empty_unsupported_client_has_explicit_capability():
    updates, client = service()
    client.tracker_updates_supported = lambda: False
    client.torrents = lambda **_: []
    result = preview(updates)
    assert result["capabilities"] == {"default": "unsupported_client"}
    assert result["clients"] == {"default": {}}


def test_desktop_tracker_polling_remains_available_during_exclusive_work(tmp_path):
    from torrentlinker.agent.coordination import coordinator
    from torrentlinker.agent.desktop import DesktopSetup
    from torrentlinker.store import Store
    from torrentlinker.torrents_workspace import TorrentWorkspace
    from torrentlinker.web.jobs import Jobs

    settings = Settings()
    settings.ensure_profiles()
    setup = DesktopSetup(settings, tmp_path / "config.toml", Store(tmp_path / "state.db"))
    jobs = Jobs(tmp_path)
    entered, release, polled = threading.Event(), threading.Event(), threading.Event()

    def work(stop, report):
        with coordinator.agent(stop):
            entered.set()
            release.wait(5)

    identifier = jobs.submit("tracker-preview", work)
    workspace = TorrentWorkspace(setup, lambda _: None, jobs=jobs)
    rows = []

    def poll():
        rows.append(workspace.request("tracker-job", {"id": identifier}))
        polled.set()

    thread = threading.Thread(target=poll)
    try:
        assert entered.wait(3)
        thread.start()
        assert polled.wait(1), "Progress polling waited for the tracker operation"
        assert rows[0]["status"] == "running"
    finally:
        release.set()
        thread.join(5)
        jobs.close()


# -- tr4ker: its own hosts and passkey, never mixed with c411's (ADR-0025) ------------------

TR_OLD = "tr4ker-old-passkey"
TR_NEW = "tr4ker-new-passkey"
TR_URL = f"https://tr4ker.net/announce/{TR_OLD}"
TR_SAVED = f"https://tr4ker.net/announce/{TR_NEW}"
C_URL = f"https://c411.org/announce/{OLD}"


def both_service(tr_saved=TR_SAVED):
    updates, client = service()
    secrets = {"announce-url": SAVED, "announce-url-tr4ker": tr_saved}
    updates.setup.secrets = SimpleNamespace(get=lambda key: secrets.get(key, ""))
    client.entries = {"c": [Announce(C_URL), OTHER], "t": [Announce(TR_URL)]}
    client.torrents = lambda **_: [
        SimpleNamespace(hash="c" * 40, tracker=C_URL, trackers=(C_URL, OTHER.url)),
        SimpleNamespace(hash="t" * 40, tracker=TR_URL, trackers=(TR_URL,)),
    ]
    client.announce_entries = lambda h: list(client.entries[h[0]])

    def write(h, before, after):
        client.writes.append((h, before, after))
        client.entries[h[0]] = list(after)

    client.apply_announces = write
    return updates, client


def move(updates, action, which, groups=None):
    return updates.preview(
        ["default"],
        action,
        "",
        "tr4ker.net",
        groups or [],
        threading.Event(),
        lambda _: None,
        which,
    )


def test_a_tr4ker_passkey_change_touches_only_tr4ker_torrents_and_the_reverse():
    updates, client = both_service()
    row = move(updates, "update-passkey", "tr4ker", [fingerprint(TR_OLD)])
    assert row["counts"] == {"update": 1}
    assert [r["hash"][0] for r in row["rows"]] == ["t"]
    assert row["settings_group"] == fingerprint(TR_NEW)
    assert TR_OLD not in json.dumps(row) and TR_NEW not in json.dumps(row)
    result = updates.apply(
        row["preview_id"],
        ["default"],
        "update-passkey",
        threading.Event(),
        lambda _: None,
        "",
        "tr4ker.net",
        [fingerprint(TR_OLD)],
        "tr4ker",
    )
    assert result["rows"][0]["status"] == "updated"
    assert [w[0][0] for w in client.writes] == ["t"]
    assert client.entries["t"] == [Announce(TR_SAVED)]
    assert client.entries["c"] == [Announce(C_URL), OTHER]  # c411 untouched
    # The reverse: a c411 passkey change leaves the tr4ker torrent alone.
    client.writes.clear()
    row = move(updates, "update-passkey", "c411", [fingerprint(OLD)])
    assert [r["hash"][0] for r in row["rows"]] == ["c"]
    assert client.entries["t"] == [Announce(TR_SAVED)]


def test_a_tr4ker_update_never_adds_another_trackers_announce():
    updates, _ = both_service()
    with pytest.raises(ValueError, match="tr4ker host"):
        updates.preview(
            ["default"],
            "add-backup",
            "",
            "tk.c411.tw",
            [],
            threading.Event(),
            lambda _: None,
            "tr4ker",
        )
    change = plan_change(
        [Announce(TR_URL), Announce(C_URL, 1)],
        "add-backup",
        configured=["tr4ker.net"],
        target_host="tr4ker.net",
        which="tr4ker",
    )
    assert change.reason == "already_current"  # c411's entry is neither read nor copied
    assert (
        plan_change(
            [Announce(C_URL)],
            "update-passkey",
            configured=["tr4ker.net"],
            settings_announce=TR_SAVED,
            groups=[fingerprint(OLD)],
            which="tr4ker",
        ).reason
        == "not_tr4ker"
    )
    with pytest.raises(ValueError, match="tr4ker Announce URL"):
        plan_change([], "update-passkey", configured=[], settings_announce=SAVED, which="tr4ker")


def test_a_preview_for_one_tracker_cannot_be_applied_for_the_other():
    updates, client = both_service()
    row = move(updates, "update-passkey", "tr4ker", [fingerprint(TR_OLD)])
    with pytest.raises(ValueError, match="match"):
        updates.apply(
            row["preview_id"],
            ["default"],
            "update-passkey",
            threading.Event(),
            lambda _: None,
            "",
            "tr4ker.net",
            [fingerprint(TR_OLD)],
            "c411",
        )
    assert not client.writes


def test_a_tr4ker_announce_keeps_its_info_dictionary_untouched():
    # The change is only ever a list of announce entries: there is no field for info data.
    change = plan_change(
        [Announce(TR_URL)],
        "update-passkey",
        configured=["tr4ker.net"],
        settings_announce=TR_SAVED,
        groups=[fingerprint(TR_OLD)],
        which="tr4ker",
    )
    assert change.after == (Announce(TR_SAVED),)
    assert TR_OLD not in repr(change) and TR_NEW not in repr(change)


def test_tracker_updates_request_defaults_to_c411():
    from torrentlinker.web.operations import JobRequest

    assert JobRequest(kind="tracker-preview").tracker_id == "c411"
    assert JobRequest(kind="tracker-preview", tracker_id="tr4ker").tracker_id == "tr4ker"
    with pytest.raises(ValueError):
        JobRequest(kind="tracker-preview", tracker_id="other")
