import io
import json
import zipfile

import httpx

from tests.test_web_profile import ORIGIN, prepared, snapshot
from torrentlinker.companion import CompanionReceiver, bundled_version, extension_zip


def test_real_loopback_receiver_pairs_and_receives_without_owner_http_controls(
    tmp_path, monkeypatch
):
    _, setup = prepared(tmp_path, monkeypatch)
    workspace = setup.profile_workspace()
    workspace.refresh(setup.settings.indexer.url, "fake-key")
    code = workspace.pairing()["code"]
    receiver = CompanionReceiver(
        workspace, lambda: (setup.settings.indexer.url, "fake-key"), port=0
    )
    try:
        with httpx.Client(base_url=receiver.address, trust_env=False) as extension:
            assert extension.post("/api/zen/profile/pairing", json={}).status_code == 403
            assert extension.options("/api/companion/pair").status_code == 403
            ext = {"Origin": ORIGIN}
            assert extension.options("/api/companion/pair", headers=ext).status_code == 204
            pair = extension.post(
                "/api/companion/pair", headers=ext, json={"code": code, "accountId": "42"}
            )
            assert pair.status_code == 200
            ext["Authorization"] = "Bearer " + pair.json()["token"]
            assert (
                extension.post("/api/companion/snapshot", headers=ext, json=snapshot()).status_code
                == 200
            )
            assert workspace.state()["companion"]["activeSeeds"]["total"] == 42
            assert (
                extension.post(
                    "/api/companion/snapshot", headers={**ext, "Host": "evil.test"}, json=snapshot()
                ).status_code
                == 403
            )
            assert (
                extension.post("/api/companion/disconnect", headers=ext, json={}).status_code == 200
            )
            assert workspace.state()["companion"] is None
    finally:
        receiver.stop()


def test_extension_bundle_is_installable_and_contains_only_packaged_assets():
    with zipfile.ZipFile(io.BytesIO(extension_zip())) as bundle:
        manifest = json.loads(bundle.read("torrentlinker-companion/manifest.json"))
        assert manifest["manifest_version"] == 3
        assert set(manifest["permissions"]) == {"scripting", "storage", "alarms"}
        assert "https://*/*" not in manifest["host_permissions"]
        assert "https://*/*" not in manifest["externally_connectable"]["matches"]
        assert set(bundle.namelist()) == {
            f"torrentlinker-companion/{name}"
            for name in (
                "manifest.json",
                "background.js",
                "collect.js",
                "descriptor.js",
                "read.js",
                "trackers.js",
                "tr4ker.js",
                "update.js",
                "community.js",
                "companion.js",
                "companion.html",
                "style.css",
                "receiver.json",
            )
        }
    with zipfile.ZipFile(io.BytesIO(extension_zip("https://nas.example/torrentlinker/"))) as bundle:
        manifest = json.loads(bundle.read("torrentlinker-companion/manifest.json"))
        assert "https://nas.example/*" in manifest["host_permissions"]
        assert manifest["externally_connectable"]["matches"][-1] == "https://nas.example/*"
        assert json.loads(bundle.read("torrentlinker-companion/receiver.json")) == {
            "webTarget": "https://nas.example/torrentlinker"
        }


def test_creation_capability_checks_pair_account_and_allowed_operations(tmp_path, monkeypatch):
    import pytest

    _, setup = prepared(tmp_path, monkeypatch)
    workspace = setup.profile_workspace()
    workspace.refresh(setup.settings.indexer.url, "fake-key")
    paired = workspace.receive(
        "/api/companion/pair", ORIGIN, "", {"code": workspace.pairing()["code"], "accountId": "42"}
    )
    calls = []
    workspace.creation_handler = lambda action, value: (
        calls.append((action, value)) or {"review": "local-review"}
    )
    auth = "Bearer " + paired["token"]
    body = {
        "accountId": "42",
        "operation": "prepare",
        "value": {"kind": "prompt", "data": {"prompt": "Find a family film"}},
    }
    assert workspace.receive("/api/companion/creation", ORIGIN, auth, body) == {
        "review": "local-review"
    }
    assert calls[0][0] == "items-prepare"
    with pytest.raises(PermissionError):
        workspace.receive("/api/companion/creation", ORIGIN, "Bearer wrong", body)
    with pytest.raises(PermissionError):
        workspace.receive("/api/companion/creation", ORIGIN, auth, {**body, "accountId": "other"})
    with pytest.raises(ValueError):
        workspace.receive(
            "/api/companion/creation", ORIGIN, auth, {**body, "value": {"kind": "studio"}}
        )
    assert len(calls) == 1


def test_extension_behind_an_https_proxy_allows_the_public_https_address(tmp_path):
    from fastapi.testclient import TestClient

    from torrentlinker.web.app import create_app

    app = create_app(tmp_path, password="test-password-long", secure_cookie=True)
    with TestClient(app, base_url="http://tl.example") as client:
        login = client.post(
            "/api/login",
            json={"password": "test-password-long"},
            headers={"X-TorrentLinker": "1"},
        )
        # The proxy speaks HTTPS to the browser; the test client sends the Secure cookie itself.
        cookie = login.headers["set-cookie"].split(";")[0]
        answer = client.get(
            "/api/zen/profile/extension", headers={"X-TorrentLinker": "1", "Cookie": cookie}
        )
        assert answer.status_code == 200, answer.text
    with zipfile.ZipFile(io.BytesIO(answer.content)) as bundle:
        receiver = json.loads(bundle.read("torrentlinker-companion/receiver.json"))
        manifest = json.loads(bundle.read("torrentlinker-companion/manifest.json"))
    assert receiver == {"webTarget": "https://tl.example"}
    assert "https://tl.example/*" in manifest["host_permissions"]


def test_web_server_manages_the_companion_folder_from_the_owners_https_origin(tmp_path):
    from fastapi.testclient import TestClient

    from torrentlinker.web.app import create_app

    folder = tmp_path / "ext"
    app = create_app(
        tmp_path / "data", password="test-password-long", secure_cookie=True, companion_dir=folder
    )
    with TestClient(app, base_url="http://tl.example") as client:
        login = client.post(
            "/api/login",
            json={"password": "test-password-long"},
            headers={"X-TorrentLinker": "1"},
        )
        headers = {"X-TorrentLinker": "1", "Cookie": login.headers["set-cookie"].split(";")[0]}
        assert not folder.exists()  # the origin is not known yet
        state = client.get("/api/zen/profile", headers=headers).json()
        assert state["companion_folder"]["version"] == bundled_version()
        assert state["companion_folder"]["path"] == str(folder)
    assert json.loads((folder / "receiver.json").read_text()) == {"webTarget": "https://tl.example"}
    # A restart knows the recorded origin and keeps the folder current by itself.
    (folder / "receiver.json").unlink()
    create_app(
        tmp_path / "data", password="test-password-long", secure_cookie=True, companion_dir=folder
    )
    assert (folder / "receiver.json").exists()


def test_web_server_without_a_companion_dir_writes_nothing(tmp_path):
    from fastapi.testclient import TestClient

    from torrentlinker.web.app import create_app

    app = create_app(tmp_path, password="test-password-long")
    with TestClient(app) as client:
        login = client.post(
            "/api/login",
            json={"password": "test-password-long"},
            headers={"X-TorrentLinker": "1"},
        )
        headers = {"X-TorrentLinker": "1", "Cookie": login.headers["set-cookie"].split(";")[0]}
        assert client.get("/api/zen/profile", headers=headers).json()["companion_folder"] is None
