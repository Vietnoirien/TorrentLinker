"""Fichiers: the Corbeille, its retention and the operation journal (ADR-0029)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.test_web_jobs import login
from torrentlinker.file_storage import DAY, TRASH_NAME, FileStorage, StorageError
from torrentlinker.web.app import create_app


class Clock:
    def __init__(self) -> None:
        self.t = 1_000_000.0

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def library(tmp_path: Path) -> Path:
    root = tmp_path / "library"
    (root / "Films" / "Dune (2021)").mkdir(parents=True)
    (root / "Films" / "Dune (2021)" / "Dune.mkv").write_bytes(b"x" * 1234)
    return root


def make(tmp_path: Path, library: Path, clock: Clock | None = None) -> FileStorage:
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    return FileStorage(data, (library,), now=clock or Clock())


def test_trashing_moves_into_the_disks_trash_and_restoring_puts_it_back(
    tmp_path: Path, library: Path
) -> None:
    storage = make(tmp_path, library)
    film = library / "Films" / "Dune (2021)"
    item = storage.trash(film, "owner")
    assert not film.exists()
    assert (library / TRASH_NAME / item["id"] / "Dune (2021)" / "Dune.mkv").exists()
    assert item["size"] == 1234 and item["by"] == "owner" and item["days_left"] == 7
    assert item["from"] == str(film)
    [disk] = storage.listing()["disks"]
    assert [i["name"] for i in disk["items"]] == ["Dune (2021)"]
    storage.restore(item["id"], "owner")
    assert (film / "Dune.mkv").read_bytes() == b"x" * 1234
    assert storage.listing()["disks"][0]["items"] == []
    assert [o["kind"] for o in storage.journal()] == ["restore", "trash"]


def test_restore_never_overwrites_what_took_the_place(tmp_path: Path, library: Path) -> None:
    storage = make(tmp_path, library)
    film = library / "Films" / "Dune (2021)"
    item = storage.trash(film, "owner")
    film.mkdir()
    with pytest.raises(StorageError, match="exists already"):
        storage.restore(item["id"], "owner")


def test_the_purge_waits_for_the_retention_and_the_retention_is_a_setting(
    tmp_path: Path, library: Path
) -> None:
    clock = Clock()
    storage = make(tmp_path, library, clock)
    item = storage.trash(library / "Films" / "Dune (2021)", "owner")
    clock.t += 6 * DAY
    assert storage.purge_expired() == 0
    assert storage.listing()["disks"][0]["items"][0]["days_left"] == 1
    storage.set_retention_days(3)
    assert storage.purge_expired() == 1
    assert not (library / TRASH_NAME / item["id"]).exists()
    assert storage.journal()[0]["kind"] == "purge" and storage.journal()[0]["actor"] == "system"


def test_emptying_deletes_for_good_and_is_journaled(tmp_path: Path, library: Path) -> None:
    storage = make(tmp_path, library)
    storage.trash(library / "Films" / "Dune (2021)", "owner")
    assert storage.empty("owner") == 1
    assert list((library / TRASH_NAME).iterdir()) == []
    assert storage.journal()[0]["kind"] == "empty"


def test_paths_outside_the_roots_symlinks_and_roots_are_refused(
    tmp_path: Path, library: Path
) -> None:
    storage = make(tmp_path, library)
    outside = tmp_path / "elsewhere.txt"
    outside.write_text("x")
    with pytest.raises(StorageError, match="outside"):
        storage.trash(outside, "owner")
    (library / "link").symlink_to(outside)
    with pytest.raises(StorageError, match="symbolic link"):
        storage.trash(library / "link" / "x", "owner")
    with pytest.raises(StorageError, match="root"):
        storage.trash(library, "owner")


def test_a_read_only_root_is_reported_and_nothing_fails_silently(
    tmp_path: Path, library: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = make(tmp_path, library)
    monkeypatch.setattr(
        "torrentlinker.file_storage._read_only", lambda p: "The disk is mounted read-only."
    )
    [disk] = storage.listing()["disks"]
    assert disk["writable"] is False and "read-only" in disk["reason"]
    with pytest.raises(StorageError, match="read-only"):
        storage.trash(library / "Films", "owner")
    assert (library / "Films").exists()


def test_a_real_read_only_directory_is_detected(tmp_path: Path, library: Path) -> None:
    storage = make(tmp_path, library)
    library.chmod(0o555)
    try:
        if os.access(library, os.W_OK):
            pytest.skip("running as a user who can write anywhere")
        assert storage.disks()[0].writable is False
    finally:
        library.chmod(0o755)


def test_the_journal_survives_a_restart_and_reconciles_an_interrupted_move(
    tmp_path: Path, library: Path
) -> None:
    storage = make(tmp_path, library)
    film = library / "Films" / "Dune (2021)"
    stored = library / TRASH_NAME / "abc" / film.name
    # An interrupted trash: journaled, and the rename did happen.
    done = storage.begin("trash", "owner", {"from": str(film), "to": str(stored)}, {})
    stored.parent.mkdir(parents=True)
    os.rename(film, stored)
    # Another that never moved anything.
    never = storage.begin(
        "trash", "owner", {"from": str(library / "Films"), "to": str(stored / "x")}, {}
    )
    reopened = make(tmp_path, library)
    assert reopened.reconcile() == 2
    states = {o["id"]: o for o in reopened.journal()}
    assert states[done]["state"] == "done"
    assert states[never]["state"] == "failed" and "Interrupted" in states[never]["error"]


def test_routes_are_the_owners_and_emptying_needs_confirmation(
    tmp_path: Path, library: Path
) -> None:
    app = create_app(
        tmp_path / "app",
        password="test-password-long",
        roots=(library,),
        monitor_verifications=False,
    )
    with TestClient(app) as browser:
        assert browser.get("/api/files/trash").status_code == 401
        login(browser)
        film = library / "Films" / "Dune (2021)"
        item = browser.post("/api/files/trash", json={"path": str(film)}).json()
        assert not film.exists() and item["by"] == "owner"
        listing = browser.get("/api/files/trash").json()
        assert (
            listing["retention_days"] == 7 and listing["disks"][0]["items"][0]["id"] == item["id"]
        )
        assert browser.post("/api/files/trash/empty", json={}).status_code == 400
        assert browser.post("/api/files/trash/retention", json={"days": 14}).json() == {
            "retention_days": 14
        }
        entry = browser.get("/api/files/journal").json()["operations"][0]
        assert entry["kind"] == "trash" and entry["undoable"] is True
        assert browser.post(f"/api/files/journal/{entry['id']}/undo").status_code == 200
        assert film.exists()
        assert browser.post(f"/api/files/journal/{entry['id']}/undo").status_code == 409
        assert browser.post("/api/files/trash", json={"path": "/etc"}).status_code == 409
        assert browser.get("/api/files/journal").json()["operations"][0]["kind"] == "restore"


def test_a_full_disk_trashes_in_place_and_emptying_deletes_it_there(
    tmp_path: Path, library: Path, monkeypatch
) -> None:
    """A disk too full for a trash folder still takes an item in its trash: it stays where it
    lies, the trash lists it, emptying deletes it there, restoring only takes it off the list,
    and something else found there since is never deleted."""
    import errno

    storage = make(tmp_path, library)
    film = library / "Film (2020)"
    film.mkdir()
    (film / "Film (2020).mkv").write_bytes(b"x" * 10)
    other = library / "Other.mkv"
    other.write_bytes(b"y" * 5)
    real_mkdir = Path.mkdir

    def full(self, *args, **kwargs):
        if ".corbeille" in str(self):
            raise OSError(errno.ENOSPC, "No space left on device")
        return real_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", full)
    first = storage.trash(film, "owner")
    second = storage.trash(other, "owner")
    assert first["in_place"] and film.exists()
    assert storage.trashed_in_place() == [film, other] or set(storage.trashed_in_place()) == {
        film,
        other,
    }
    assert storage.restore(second["id"], "owner") == str(other) and other.exists()
    assert storage.trashed_in_place() == [film]
    (film / "extra.txt").write_bytes(b"new")  # changed since: kept
    with pytest.raises(StorageError, match="changed"):
        storage.empty("owner")
    assert film.exists()
    (film / "extra.txt").unlink()
    assert storage.empty("owner") == 1
    assert not film.exists() and storage.trashed_in_place() == []
