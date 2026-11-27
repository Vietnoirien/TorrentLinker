"""Replace a library film with a better release, with the old one waiting for its share to end."""

from __future__ import annotations

from pathlib import Path

import pytest

from torrentlinker.domain import Torrent
from torrentlinker.file_storage import TRASH_NAME, FileStorage
from torrentlinker.library_replace import FinRule, Replacements, placement

OLD, NEW = "a" * 40, "b" * 40


class Client:
    """A Torrent Client with two torrents; it records what it was asked to remove."""

    def __init__(self, torrents: list[Torrent]) -> None:
        self.torrents = {t.hash: t for t in torrents}
        self.removed: list[tuple[str, bool]] = []

    def torrent(self, hash: str, with_files: bool = True) -> Torrent | None:
        return self.torrents.get(hash)

    def remove(self, hash: str, *, delete_files: bool = False) -> None:
        self.removed.append((hash, delete_files))
        del self.torrents[hash]


def torrent(hash: str, *, progress: float = 1.0, state: str = "uploading", **fields) -> Torrent:
    return Torrent(hash, hash[:1], Path("/x"), progress=progress, state=state, **fields)


@pytest.fixture
def world(tmp_path: Path):
    root = tmp_path / "library"
    folder = root / "Films" / "Dune (2021)"
    folder.mkdir(parents=True)
    (folder / "Dune.2021.1080p.mkv").write_bytes(b"x" * 100)
    data = tmp_path / "data"
    data.mkdir()
    storage = FileStorage(data, (root,))
    return root, folder, storage, Replacements(data, storage)


def start(replacements, folder, *, replace=True, wait=True, rule=FinRule()):
    return replacements.start(
        "default", "film-1", new_hash=NEW, old_hash=OLD, old_paths=[folder / "Dune.2021.1080p.mkv"],
        replace=replace, wait=wait, rule=rule, actor="owner",
    )  # fmt: skip


def test_a_finished_download_without_waiting_removes_the_old_torrent_and_trashes_its_files(world):
    root, folder, storage, replacements = world
    start(replacements, folder, wait=False)
    client = Client([torrent(OLD), torrent(NEW, progress=0.4)])
    assert replacements.tick(client, "default") == []  # still downloading
    client.torrents[NEW] = torrent(NEW)
    assert replacements.tick(client, "default") != []
    assert client.removed == [(OLD, False)]  # never with its data
    assert not (folder / "Dune.2021.1080p.mkv").exists()
    [disk] = storage.listing()["disks"]
    assert disk["items"][0]["name"] == "Dune.2021.1080p.mkv" and (root / TRASH_NAME).exists()
    assert replacements.runs()[0]["state"] == "done"


def test_without_replace_the_old_version_is_left_alone(world):
    _, folder, _, replacements = world
    start(replacements, folder, replace=False)
    client = Client([torrent(OLD), torrent(NEW)])
    replacements.tick(client, "default")
    assert client.removed == [] and (folder / "Dune.2021.1080p.mkv").exists()
    assert replacements.hidden("default") == set()


def test_waiting_keeps_the_old_torrent_seeding_hidden_and_marked_until_the_rule_is_met(world):
    _, folder, _, replacements = world
    start(replacements, folder, rule=FinRule(use_time=True, hours=48, use_ratio=True, ratio=2.0))
    client = Client([torrent(OLD, seeding_time=3600, ratio=0.5), torrent(NEW)])
    replacements.tick(client, "default")
    assert replacements.runs()[0]["state"] == "seeding-out"
    assert replacements.hidden("default") == {"film-1"}  # hidden from Médias
    assert replacements.ending("default")[OLD]["ratio"] == 2.0  # the badge in Torrents
    assert client.removed == []
    client.torrents[OLD] = torrent(OLD, seeding_time=3600, ratio=2.5)  # ratio: l'un ou l'autre
    replacements.tick(client, "default")
    assert client.removed == [(OLD, False)] and replacements.runs()[0]["state"] == "done"


def test_an_old_release_that_no_longer_seeds_goes_at_once_even_with_wait_on(world):
    _, folder, _, replacements = world
    start(replacements, folder)
    client = Client([torrent(OLD, state="pausedUP"), torrent(NEW)])
    replacements.tick(client, "default")
    assert replacements.runs()[0]["state"] == "done"


@pytest.mark.parametrize(
    ("combine", "hours", "ratio", "met"),
    [
        ("any", 100, 0.1, True),
        ("any", 1, 0.1, False),
        ("all", 100, 0.1, False),
        ("all", 100, 3, True),
    ],
)
def test_the_fin_du_partage_rule_is_either_or_both(combine, hours, ratio, met):
    rule = FinRule(use_time=True, hours=48, use_ratio=True, ratio=1.0, combine=combine)
    assert rule.met(hours, ratio) is met


def test_a_rule_with_no_condition_is_met_at_once():
    assert FinRule(use_time=False, use_ratio=False).met(0, 0)
    with pytest.raises(ValueError):
        FinRule.parse({"hours": 0})


def test_a_trashed_old_release_can_be_restored(world):
    _, folder, storage, replacements = world
    start(replacements, folder, wait=False)
    replacements.tick(Client([torrent(OLD), torrent(NEW)]), "default")
    item = storage.listing()["disks"][0]["items"][0]
    storage.restore(item["id"], "owner")
    assert (folder / "Dune.2021.1080p.mkv").exists()


def test_the_new_release_lands_beside_the_old_one_or_in_the_download_folder(tmp_path: Path):
    beside = placement(tmp_path, 1, tmp_path / "downloads")
    assert beside.folder == tmp_path and not beside.fallback
    elsewhere = placement(tmp_path, 10**18, tmp_path / "downloads")
    assert elsewhere.fallback and elsewhere.folder == tmp_path / "downloads"
    assert "needed" in elsewhere.reason
    with pytest.raises(ValueError, match="Download Folder"):
        placement(tmp_path, 10**18, None)


def test_the_routes_are_the_owners_and_record_a_replacement(tmp_path: Path):
    from fastapi.testclient import TestClient

    from tests.test_web_jobs import login
    from torrentlinker.web.app import create_app

    library = tmp_path / "lib"
    library.mkdir()
    app = create_app(
        tmp_path / "app",
        password="test-password-long",
        roots=(library,),
        monitor_verifications=False,
    )
    body = {"film": "f", "new_hash": NEW, "old_hash": OLD, "old_paths": [], "new_size": 1,
            "replace": True, "wait": True}  # fmt: skip
    with TestClient(app) as browser:
        assert browser.get("/api/media/replacements").status_code == 401
        login(browser)
        assert browser.post("/api/media/replacements", json=body).status_code == 201
        [run] = browser.get("/api/media/replacements").json()["replacements"]
        assert run["state"] == "downloading" and run["wait"] and run["actor"] == "owner"
        found = browser.post(
            "/api/media/replacements/placement", json={"folder": str(library), "size": 1}
        ).json()
        assert found["fallback"] is False
