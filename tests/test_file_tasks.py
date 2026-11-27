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


def test_paths_outside_the_roots_or_the_actors_folders_are_refused(world, tmp_path):
    root, storage, _ = world
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


def test_entries_know_the_torrent_seeding_them_and_the_film_they_hold(tmp_path: Path):
    from torrentlinker.domain import Torrent
    from torrentlinker.file_annotations import annotate, seeds_of

    folder = tmp_path / "Films"
    torrent = Torrent(
        "A" * 40, "Dune", folder, files={"Dune/Dune.mkv": 5, "Dune/Dune.nfo": 1}, ratio=1.234,
        state="uploading",
    )  # fmt: skip
    entries = [
        {"name": "Dune", "dir": True},
        {"name": "Alien.mkv", "dir": False},
        {"name": "Others", "dir": True},
    ]
    films = [
        {"id": "f1", "path": str(folder / "Dune" / "Dune.mkv"), "title": "Dune"},
        {"id": "f2", "path": str(folder / "Alien.mkv"), "title": "Alien"},
        {"id": "f3", "path": str(folder / "Others" / "a.mkv"), "title": "A"},
        {"id": "f4", "path": str(folder / "Others" / "b.mkv"), "title": "B"},
    ]
    annotate(folder, entries, films, seeds_of([("default", "qBittorrent", torrent)]))
    dune, alien, others = entries
    assert dune["seed"]["client"] == "qBittorrent" and dune["seed"]["ratio"] == 1.23
    assert dune["film"] == {"id": "f1", "title": "Dune"} and "seed" not in alien
    assert alien["film"]["id"] == "f2"
    assert "film" not in others and others["films"] == 2  # a folder of several films


def test_a_copy_reports_what_is_left_of_it(world, monkeypatch):
    root, storage, tasks = world
    target = root / "Downloads" / "Dune.mkv"
    item = {"state": "running"}
    ticks = iter([0.0, 1.0, 2.0, 3.0, 4.0, 5.0])
    monkeypatch.setattr(file_tasks.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(file_tasks, "CHUNK", 1000)
    tasks._copy(root / "Films" / "Dune.mkv", target, item, lambda: False)
    assert target.exists() and item["progress"] == 1.0 and item["eta"] == 0


class SeedClient:
    """A Torrent Client that records what it is told, and moves nothing itself."""

    def __init__(self, torrent, native: bool) -> None:
        self.torrents = {torrent.hash: torrent}
        self.calls: list[tuple] = []
        if not native:
            self.repoint = self._repoint

    def torrent(self, hash, with_files=True):
        return self.torrents.get(hash)

    def set_location(self, hash, path):
        self.calls.append(("set_location", hash, path))
        from dataclasses import replace

        old = self.torrents[hash]
        for name in {Path(n).parts[0] for n in old.files}:
            (old.save_path / name).rename(Path(path) / name)  # the client moves the files itself
        self.torrents[hash] = replace(self.torrents[hash], save_path=Path(path))

    def _repoint(self, hash, path, data, name=None):
        self.calls.append(("repoint", hash, path))
        from dataclasses import replace

        self.torrents[hash] = replace(self.torrents[hash], save_path=Path(path))

    def rename_file(self, hash, old, new):
        self.calls.append(("rename_file", old, new))
        save = self.torrents[hash].save_path
        (save / old).rename(save / new)

    def remove(self, hash, *, delete_files=False):
        self.calls.append(("remove", hash, delete_files))
        del self.torrents[hash]

    def pause(self, hash):
        self.calls.append(("pause", hash))

    def start(self, hash):
        self.calls.append(("start", hash))

    def recheck(self, hash):
        self.calls.append(("recheck", hash))


def seeded_world(world, native=True):
    from torrentlinker.domain import Torrent
    from torrentlinker.file_annotations import seeds_of, seeds_under

    root, storage, _ = world
    films = root / "Films"
    torrent = Torrent(
        "a" * 40, "Dune.mkv", films, files={"Dune.mkv": 3000}, state="uploading", ratio=1.5
    )
    client = SeedClient(torrent, native)

    def seeds(path):
        known = [("default", "qBittorrent", t) for t in client.torrents.values()]
        return seeds_under(path, seeds_of(known))

    tasks = Tasks(storage, seeds=seeds, client_of=lambda _: client, threaded=False)
    return root, storage, tasks, client


def test_a_seeded_file_moves_through_its_client_and_keeps_seeding(world):
    root, storage, tasks, client = seeded_world(world)
    _, item = one(tasks, "move", root / "Films" / "Dune.mkv", root / "Downloads")
    assert (
        item["state"] == "done"
        and ("set_location", "a" * 40, str(root / "Downloads")) in client.calls
    )
    assert item["undo"]["client"]["back"] == str(root / "Films")


def test_a_seeded_file_is_renamed_inside_its_client(world):
    root, storage, tasks, client = seeded_world(world)
    task, item = one(
        tasks, "rename", root / "Films" / "Dune.mkv", root / "Films" / "Dune (2021).mkv"
    )
    assert ("rename_file", "Dune.mkv", "Dune (2021).mkv") in client.calls
    assert item["note"].startswith("Renommé dans le client")
    assert item["state"] == "done" and (root / "Films" / "Dune (2021).mkv").exists()


def test_trashing_a_seeded_file_removes_its_torrent_without_the_data(world):
    root, storage, tasks, client = seeded_world(world)
    _, item = one(tasks, "trash", root / "Films" / "Dune.mkv")
    assert item["state"] == "done" and ("remove", "a" * 40, False) in client.calls
    assert not (root / "Films" / "Dune.mkv").exists()


def test_a_folder_holding_several_torrents_and_a_part_of_a_torrent_are_refused(world):
    root, storage, tasks, client = seeded_world(world)
    from torrentlinker.domain import Torrent

    other = Torrent(
        "b" * 40, "Alien.mkv", root / "Films", files={"Alien.mkv": 2000}, state="uploading"
    )
    client.torrents[other.hash] = other
    _, item = one(tasks, "move", root / "Films", root / "Downloads")
    assert item["state"] == "failed" and "2 torrents" in item["reason"]


def test_a_seeded_move_across_disks_copies_verifies_repoints_then_trashes_the_source(
    world, monkeypatch
):
    root, storage, tasks, client = seeded_world(world, native=False)
    monkeypatch.setattr(file_tasks, "same_device", lambda a, b: False)
    monkeypatch.setattr("torrentlinker.storage_moves._wait", lambda *a, **k: True)
    client.torrents["a" * 40] = __import__("dataclasses").replace(
        client.torrents["a" * 40], progress=1.0
    )
    _, item = one(tasks, "move", root / "Films" / "Dune.mkv", root / "Downloads")
    assert item["state"] == "done" and item["verified"], item
    assert (root / "Downloads" / "Dune.mkv").read_bytes() == b"d" * 3000
    assert not (root / "Films" / "Dune.mkv").exists()  # in the trash
    assert ("repoint", "a" * 40, str(root / "Downloads")) in client.calls
    assert client.calls[-1] == ("start", "a" * 40)  # seeding again, whatever happened
