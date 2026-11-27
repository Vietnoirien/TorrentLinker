"""Gérer les fichiers: a Member moves, renames and trashes inside their granted Library Folders,
and a folder move keeps grants and settings pointing at the new path (#209)."""

import time

import pytest
from fastapi.testclient import TestClient

from tests.test_members_signin import member, sign_in
from tests.test_web_jobs import login
from torrentlinker.accounts import Permission
from torrentlinker.config import Settings
from torrentlinker.domain import ContentKind, LibraryFolder
from torrentlinker.web.app import create_app


@pytest.fixture
def server(tmp_path):
    films, private = tmp_path / "films", tmp_path / "private"
    (films / "Dune").mkdir(parents=True)
    (films / "Dune" / "Dune.mkv").write_bytes(b"x" * 20)
    (films / "Done").mkdir()
    private.mkdir()
    (private / "Secret.mkv").write_bytes(b"s")
    config = tmp_path / "config"
    config.mkdir()
    settings = Settings()
    settings.library_folders = [
        LibraryFolder(films, None, ContentKind.MOVIE),
        LibraryFolder(private, None, ContentKind.MOVIE),
    ]
    settings.download_folders.default = str(films / "Dune" / "Incoming")
    settings.save(config / "settings.json")
    app = create_app(
        config, members_enabled=True, password="test-password-long", roots=(films, private),
        monitor_verifications=False,
    )  # fmt: skip
    with TestClient(app) as browser:
        browser.headers["X-TorrentLinker"] = "1"
        yield app, browser, films, private


def finish(browser):
    for _ in range(100):
        [row, *_] = browser.get("/api/files/tasks").json()["tasks"]
        if row["state"] not in {"queued", "running"}:
            return row
        time.sleep(0.05)
    raise AssertionError("the task did not finish")


def test_a_member_without_the_permission_is_refused_everywhere(server):
    app, browser, films, _ = server
    member(app, "lea", Permission.FILMS)
    sign_in(browser, "lea")
    for method, url in (("get", "/api/files/browse"), ("get", "/api/files/trash"),
                        ("get", "/api/files/tasks"), ("get", "/api/files/disks"),
                        ("get", "/api/files/journal")):  # fmt: skip
        assert getattr(browser, method)(url).status_code == 403


def test_a_member_sees_and_changes_only_their_granted_folders(server):
    app, browser, films, private = server
    lea = member(app, "lea", Permission.MANAGE_FILES)
    app.state.accounts.set_media_limits(lea, None, [str(films)])
    sign_in(browser, "lea")
    assert browser.get("/api/files/browse").json()["roots"] == [str(films)]
    assert browser.get(f"/api/files/browse?path={private}").status_code == 409
    # Moving inside the granted folder works, and is logged under the Member's name.
    move = {
        "kind": "move",
        "items": [{"from": str(films / "Dune" / "Dune.mkv"), "to": str(films / "Done")}],
    }
    assert browser.post("/api/files/tasks", json=move).status_code == 202
    assert finish(browser)["state"] == "done" and (films / "Done" / "Dune.mkv").exists()
    # Outside it, the server refuses and nothing moves.
    outside = {"kind": "trash", "items": [{"from": str(private / "Secret.mkv")}]}
    browser.post("/api/files/tasks", json=outside)
    row = finish(browser)
    assert row["items"][0]["state"] == "failed" and "may not" in row["items"][0]["reason"]
    assert (private / "Secret.mkv").exists()
    assert (
        browser.post("/api/files/trash", json={"path": str(private / "Secret.mkv")}).status_code
        == 409
    )
    # Trashing inside works and the Member sees and restores only their own folders' items.
    item = browser.post("/api/files/trash", json={"path": str(films / "Done" / "Dune.mkv")}).json()
    assert item["by"]
    assert [
        i["name"] for d in browser.get("/api/files/trash").json()["disks"] for i in d["items"]
    ] == ["Dune.mkv"]
    assert browser.post(f"/api/files/trash/{item['id']}/restore").status_code == 200
    # Owner-only: emptying, retention, disks, the journal.
    assert browser.post("/api/files/trash/empty", json={"confirm": True}).status_code == 403
    assert browser.post("/api/files/trash/retention", json={"days": 3}).status_code == 403
    assert browser.get("/api/files/disks").status_code == 403


def test_a_moved_folder_keeps_settings_and_grants_pointing_at_the_new_path(server):
    app, browser, films, _ = server
    lea = member(app, "lea", Permission.MANAGE_FILES)
    app.state.accounts.set_media_limits(lea, None, [str(films / "Dune")])
    login(browser)
    move = {
        "kind": "rename",
        "items": [{"from": str(films / "Dune"), "to": str(films / "Dune (2021)")}],
    }
    browser.post("/api/files/tasks", json=move)
    assert finish(browser)["state"] == "done"
    settings = app.state.agent_service.setup.settings
    assert settings.download_folders.default == str(films / "Dune (2021)" / "Incoming")
    actor = app.state.accounts.actor(lea)
    assert actor.folders == {str(films / "Dune (2021)")}
    # And undoing the rename brings them back.
    task_id = browser.get("/api/files/tasks").json()["tasks"][0]["id"]
    assert browser.post(f"/api/files/tasks/{task_id}/undo/0").status_code == 200
    assert app.state.accounts.actor(lea).folders == {str(films / "Dune")}
