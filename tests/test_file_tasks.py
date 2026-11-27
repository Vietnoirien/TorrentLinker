"""Explorateur's operations: instant renames, verified copies across disks, conflicts, undo."""

from __future__ import annotations

from pathlib import Path

import pytest

from torrentlinker import file_tasks
from torrentlinker.file_storage import TRASH_NAME, FileStorage
from torrentlinker.file_tasks import Tasks, listing


@pytest.fixture
def world(tmp_path: Path):
    root = tmp_path / "library"
    (root / "Films").mkdir(parents=True)
    (root / "Downloads").mkdir()
    (root / "Films" / "Dune.mkv").write_bytes(b"d" * 3000)
    (root / "Films" / "Alien.mkv").write_bytes(b"a" * 2000)
    data = tmp_path / "data"
    data.mkdir()
    storage = FileStorage(data, (root,))
    return root, storage, Tasks(storage, threaded=False)


def one(tasks, kind, source, to="", **kw):
    task = tasks.submit(kind, [{"from": str(source), "to": str(to)}], "owner", **kw)
    return task, task["items"][0]


def test_listing_shows_folders_first_and_hides_the_trash(world):
    root, storage, _ = world
    storage.trash(root / "Films" / "Alien.mkv", "owner")
    assert [r["name"] for r in listing(storage, root)] == ["Downloads", "Films"]
    assert [r["name"] for r in listing(storage, root / "Films")] == ["Dune.mkv"]


def test_a_move_on_one_disk_is_an_instant_rename_and_can_be_undone(world):
    root, storage, tasks = world
    task, item = one(tasks, "move", root / "Films" / "Dune.mkv", root / "Downloads")
    assert task["state"] == "done" and item["verified"] and item["note"] == "instantané"
    assert (root / "Downloads" / "Dune.mkv").exists() and not (root / "Films" / "Dune.mkv").exists()
    tasks.undo(task["id"], 0, "owner")
    assert (root / "Films" / "Dune.mkv").exists() and item["state"] == "undone"
    assert [o["kind"] for o in storage.journal()][0] == "move"


def test_a_rename_and_a_new_folder(world):
    root, _, tasks = world
    _, item = one(tasks, "rename", root / "Films" / "Dune.mkv", root / "Films" / "Dune (2021).mkv")
    assert item["state"] == "done" and (root / "Films" / "Dune (2021).mkv").exists()
    _, made = one(tasks, "mkdir", root / "Films" / "Séries")
    assert made["state"] == "done" and (root / "Films" / "Séries").is_dir()


def test_trashing_goes_to_the_disks_corbeille_and_is_restorable(world):
    root, storage, tasks = world
    task, item = one(tasks, "trash", root / "Films" / "Alien.mkv")
    assert item["state"] == "done" and (root / TRASH_NAME).exists()
    tasks.undo(task["id"], 0, "owner")
    assert (root / "Films" / "Alien.mkv").read_bytes() == b"a" * 2000


def test_a_move_across_disks_is_a_verified_copy_then_the_source_goes_to_the_trash(
    world, monkeypatch
):
    root, storage, tasks = world
    monkeypatch.setattr(file_tasks, "same_device", lambda a, b: False)
    task, item = one(tasks, "move", root / "Films" / "Dune.mkv", root / "Downloads")
    assert item["state"] == "done" and item["verified"] and item["progress"] == 1.0
    assert (root / "Downloads" / "Dune.mkv").read_bytes() == b"d" * 3000
    assert not (root / "Films" / "Dune.mkv").exists()  # now in the trash, not deleted
    assert storage.listing()["disks"][0]["items"][0]["name"] == "Dune.mkv"
    tasks.undo(task["id"], 0, "owner")  # the copy goes to the trash, the original comes back
    assert (root / "Films" / "Dune.mkv").read_bytes() == b"d" * 3000


def test_a_copy_that_fails_verification_leaves_the_source_and_no_partial_file(world, monkeypatch):
    root, _, tasks = world
    monkeypatch.setattr(file_tasks, "same_device", lambda a, b: False)
    real = file_tasks.digest
    monkeypatch.setattr(
        file_tasks, "digest", lambda p, *a: real(p, *a) if "Films" in str(p) else "bad"
    )
    task, item = one(tasks, "move", root / "Films" / "Dune.mkv", root / "Downloads")
    assert item["state"] == "failed" and "Verification failed" in item["reason"]
    assert (root / "Films" / "Dune.mkv").exists() and not (root / "Downloads" / "Dune.mkv").exists()
    assert task["state"] == "failed"


def test_conflicts_ignore_replace_rename_and_keep_one(world):
    root, storage, tasks = world
    (root / "Downloads" / "Dune.mkv").write_bytes(b"other")
    _, skipped = one(
        tasks, "copy", root / "Films" / "Dune.mkv", root / "Downloads", conflict="skip"
    )
    assert (
        skipped["state"] == "skipped" and (root / "Downloads" / "Dune.mkv").read_bytes() == b"other"
    )
    _, renamed = one(
        tasks, "copy", root / "Films" / "Dune.mkv", root / "Downloads", conflict="rename"
    )
    assert (root / "Downloads" / "Dune (2).mkv").read_bytes() == b"d" * 3000 and renamed[
        "state"
    ] == "done"
    _, replaced = one(
        tasks, "copy", root / "Films" / "Dune.mkv", root / "Downloads", conflict="replace"
    )
    assert (root / "Downloads" / "Dune.mkv").read_bytes() == b"d" * 3000
    assert storage.listing()["disks"][0]["items"][0]["reason"].startswith("Remplacé")
    assert replaced["note"] == "Ancien fichier à la corbeille"
    _, keep = one(
        tasks, "move", root / "Films" / "Dune.mkv", root / "Downloads", conflict="keep-one"
    )
    assert keep["state"] == "done" and keep["note"] == "Un seul exemplaire gardé"
    assert not (root / "Films" / "Dune.mkv").exists()  # the duplicate source is in the trash
    (root / "Downloads" / "Alien.mkv").write_bytes(b"different")
    _, differs = one(
        tasks, "move", root / "Films" / "Alien.mkv", root / "Downloads", conflict="keep-one"
    )
    assert differs["state"] == "failed" and "differs" in differs["reason"]


def test_seeded_files_and_paths_outside_the_roots_or_the_actors_folders_are_refused(
    world, tmp_path
):
    root, storage, _ = world
    seeded = Tasks(storage, seeded=lambda p: "qBittorrent", threaded=False)
    _, item = one(seeded, "trash", root / "Films" / "Dune.mkv")
    assert item["state"] == "failed" and "qBittorrent" in item["reason"]
    assert (root / "Films" / "Dune.mkv").exists()
    plain = Tasks(storage, threaded=False)
    _, outside = one(plain, "trash", tmp_path / "elsewhere.txt")
    assert outside["state"] == "failed" and "outside" in outside["reason"]
    limited = Tasks(storage, allowed=lambda p: "Films" not in str(p), threaded=False)
    _, denied = one(limited, "trash", root / "Films" / "Dune.mkv")
    assert denied["state"] == "failed" and "may not" in denied["reason"]


def test_a_cancelled_task_starts_nothing_and_says_so(world):
    root, storage, _ = world
    tasks = Tasks(storage, threaded=False)
    task = tasks.submit("trash", [{"from": str(root / "Films" / "Dune.mkv")}], "owner")
    tasks2 = Tasks(storage, threaded=False)
    tasks2.tasks["x"] = {**task, "id": "x", "items": [{**task["items"][0], "state": "queued"}]}
    import threading

    tasks2._cancel["x"] = threading.Event()
    tasks2.cancel("x")
    tasks2.run("x")
    assert (
        tasks2.tasks["x"]["items"][0]["state"] == "cancelled"
        and tasks2.tasks["x"]["state"] == "cancelled"
    )


def test_the_routes_browse_queue_and_undo(tmp_path: Path):
    import time

    from fastapi.testclient import TestClient

    from tests.test_web_jobs import login
    from torrentlinker.web.app import create_app

    root = tmp_path / "lib"
    (root / "Films").mkdir(parents=True)
    (root / "Films" / "Dune.mkv").write_bytes(b"x" * 10)
    (root / "Done").mkdir()
    app = create_app(
        tmp_path / "app", password="test-password-long", roots=(root,), monitor_verifications=False
    )
    with TestClient(app) as browser:
        assert browser.get("/api/files/browse").status_code == 401
        login(browser)
        assert browser.get("/api/files/browse").json()["roots"] == [str(root.resolve())]
        names = [e["name"] for e in browser.get(f"/api/files/browse?path={root}").json()["entries"]]
        assert names == ["Done", "Films"]
        assert browser.get("/api/files/browse?path=/etc").status_code == 409
        body = {
            "kind": "move",
            "items": [{"from": str(root / "Films" / "Dune.mkv"), "to": str(root / "Done")}],
        }
        task = browser.post("/api/files/tasks", json=body).json()
        for _ in range(100):
            [row] = browser.get("/api/files/tasks").json()["tasks"]
            if row["state"] != "running" and row["state"] != "queued":
                break
            time.sleep(0.05)
        assert row["state"] == "done" and (root / "Done" / "Dune.mkv").exists()
        assert browser.post(f"/api/files/tasks/{task['id']}/undo/0").status_code == 200
        assert (root / "Films" / "Dune.mkv").exists()
        assert browser.post(f"/api/files/tasks/{task['id']}/undo/0").status_code == 409
