"""Organisation's routes: the board, the role sheet, Ranger queued and kept (#223)."""

import time

import pytest
from fastapi.testclient import TestClient

from tests.test_members_signin import member, sign_in
from torrentlinker.accounts import Permission
from torrentlinker.config import Settings
from torrentlinker.domain import ContentKind, LibraryFolder
from torrentlinker.web.app import create_app


@pytest.fixture
def server(tmp_path):
    root = tmp_path / "disk"
    old, films, series = root / "Old", root / "Films", root / "Séries"
    for folder in (old, films, series):
        folder.mkdir(parents=True)
    (old / "Moon.2009.FRENCH.720p.BluRay.x264.mkv").write_bytes(b"x" * 20)
    (old / "IMG_3310.mov").write_bytes(b"y")
    config = tmp_path / "config"
    config.mkdir()
    settings = Settings()
    settings.library_folders = [LibraryFolder(old, None, ContentKind.OTHER)]
    settings.save(config / "settings.json")
    app = create_app(
        config, members_enabled=True, password="test-password-long", roots=(root,),
        monitor_verifications=False,
    )  # fmt: skip
    with TestClient(app) as browser:
        browser.headers["X-TorrentLinker"] = "1"
        from tests.test_web_jobs import login

        login(browser)
        yield app, browser, old, films, series


def board(browser):
    for _ in range(100):
        found = browser.get("/api/files/organisation").json()
        if not found["scanning"]:
            return found
        time.sleep(0.05)
    raise AssertionError("the folders were never read")


def test_roles_links_and_the_summary_through_the_routes(server):
    app, browser, old, films, series = server
    for path, role, kind in ((old, "prov", ""), (films, "lib", "films"), (series, "lib", "series")):
        assert (
            browser.post(
                "/api/files/organisation/role", json={"path": str(path), "role": role, "kind": kind}
            ).status_code
            == 200
        )
    found = board(browser)
    assert [lib["name"] for lib in found["libraries"]] == ["Films", "Séries"]
    [prov] = found["provenances"]
    assert prov["films"] == 1 and [r["name"] for r in prov["review"]] == ["IMG_3310.mov"]
    assert found["tokens"] and found["disks"]
    pin = browser.post("/api/files/organisation/link", json={"path": str(old), "to": str(films)})
    assert pin.status_code == 200 and board(browser)["provenances"][0]["to"] == str(films)
    assert (
        browser.post(
            "/api/files/organisation/link", json={"path": str(old), "to": str(old)}
        ).status_code
        == 409
    )  # a provenance is not an organised library
    summary = browser.post("/api/files/organisation/summary", json={"paths": [str(old)]}).json()
    assert summary["n"] == 1 and summary["review"] == 1


def test_ranger_queues_the_batch_and_the_move_happens_in_the_background(server):
    app, browser, old, films, series = server
    for path, role, kind in ((old, "prov", ""), (films, "lib", "films"), (series, "lib", "series")):
        browser.post(
            "/api/files/organisation/role", json={"path": str(path), "role": role, "kind": kind}
        )
    board(browser)
    queued = browser.post("/api/files/organisation/ranger", json={"paths": [str(old)]})
    assert queued.status_code == 202 and queued.json()["queued"] == 1
    for _ in range(100):
        if (films / "Moon (2009)" / "Moon (2009).mkv").exists():
            break
        time.sleep(0.05)
    assert (films / "Moon (2009)" / "Moon (2009).mkv").exists()
    assert (old / "IMG_3310.mov").exists()  # never moved blindly
    [task, *_] = browser.get("/api/files/tasks").json()["tasks"]
    assert task["kind"] == "ranger" and task["label"].startswith("Ranger 1")


def test_a_member_never_reaches_the_board(server):
    app, browser, *_ = server
    member(app, "lea", Permission.MANAGE_FILES)
    sign_in(browser, "lea")
    assert browser.get("/api/files/organisation").status_code == 403
    assert browser.post("/api/files/organisation/ranger", json={"paths": ["/x"]}).status_code == 403


def test_an_emptied_old_library_is_swapped_in_the_settings_and_grants_follow(server):
    app, browser, old, films, series = server
    lea = member(app, "lea", Permission.FILMS)
    app.state.accounts.set_media_limits(lea, "12", [str(old)])
    (old / "IMG_3310.mov").unlink()
    for path, role, kind in ((old, "prov", ""), (films, "lib", "films"), (series, "lib", "series")):
        browser.post(
            "/api/files/organisation/role", json={"path": str(path), "role": role, "kind": kind}
        )
    board(browser)
    browser.post("/api/files/organisation/ranger", json={"paths": [str(old)]})
    for _ in range(100):
        found = board(browser)
        if found["provenances"][0]["swapped"]:
            break
        time.sleep(0.05)
    assert found["provenances"][0]["swapped"] == [str(films)]
    saved = Settings.load(old.parent.parent / "config" / "settings.json")
    folders = {str(f.path) for f in saved.library_folders}
    assert str(old) not in folders and str(films) in folders
    assert app.state.accounts.actor(lea).folders == {str(films)}
