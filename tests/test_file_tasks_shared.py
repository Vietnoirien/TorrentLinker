"""A file several torrents share moves once and the others follow (ADR-0029, rule 3, #222).
Fake Torrent Clients only: they record what they are told and move nothing on their own."""

# ruff: noqa: F811  (the `world` fixture is imported, then used as an argument)

from dataclasses import replace
from pathlib import Path

from tests.test_file_tasks import SeedClient, one, world  # noqa: F401
from torrentlinker.domain import Torrent
from torrentlinker.file_annotations import seeds_of, seeds_under
from torrentlinker.file_tasks import Tasks

A, B = "a" * 40, "b" * 40


class Follower(SeedClient):
    """The second client: it is pointed at files already moved, so it moves nothing."""

    def __init__(self, torrent, native=True, rechecked=1.0):
        super().__init__(torrent, native)
        self.rechecked = rechecked

    def set_location(self, hash, path):
        self.calls.append(("set_location", hash, path))
        self.torrents[hash] = replace(self.torrents[hash], save_path=Path(path))

    def recheck(self, hash):
        self.calls.append(("recheck", hash))
        self.torrents[hash] = replace(self.torrents[hash], progress=self.rechecked)


def shared_world(world, link_root="", rechecked=1.0):
    root, storage, _ = world
    films = root / "Films"
    first = Torrent(A, "Dune.mkv", films, files={"Dune.mkv": 3000}, state="uploading", progress=1.0)
    second = Torrent(
        B, "Dune.mkv", films, files={"Dune.mkv": 3000}, state="uploading", progress=1.0
    )
    one_client, other = SeedClient(first, True), Follower(second, rechecked=rechecked)
    clients = {"c411": one_client, "tr4ker": other}

    def seeds(path):
        known = [(cid, cid, t) for cid, c in clients.items() for t in c.torrents.values()]
        return seeds_under(path, seeds_of(known))

    tasks = Tasks(
        storage, seeds=seeds, client_of=clients.get, threaded=False,
        link_root_of=lambda cid: link_root if cid == "tr4ker" else "",
    )  # fmt: skip
    return root, tasks, one_client, other


def test_a_move_of_a_shared_file_moves_it_once_and_re_points_the_other_torrent(world):
    root, tasks, first, second = shared_world(world)
    _, item = one(tasks, "move", root / "Films" / "Dune.mkv", root / "Downloads")
    assert item["state"] == "done", item
    assert (root / "Downloads" / "Dune.mkv").exists() and not (root / "Films" / "Dune.mkv").exists()
    assert ("set_location", A, str(root / "Downloads")) in first.calls
    assert ("set_location", B, str(root / "Downloads")) in second.calls
    assert ("recheck", B) in second.calls and ("start", B) in second.calls
    assert second.torrents[B].save_path == root / "Downloads"
    assert item["torrents"] == ["Dune.mkv", "Dune.mkv"]  # the confirmation lists both


def test_a_rename_re_points_the_other_torrent_to_links_in_its_link_folder(world, tmp_path):
    links = tmp_path / "liens"
    links.mkdir()
    root, tasks, first, second = shared_world(world, link_root=str(links))
    _, item = one(tasks, "rename", root / "Films" / "Dune.mkv", root / "Films" / "Dune (2021).mkv")
    assert item["state"] == "done", item
    assert ("rename_file", "Dune.mkv", "Dune (2021).mkv") in first.calls
    folder = second.torrents[B].save_path
    assert folder.parent == links and (folder / "Dune.mkv").is_symlink()
    assert (folder / "Dune.mkv").resolve() == (root / "Films" / "Dune (2021).mkv").resolve()
    assert ("recheck", B) in second.calls


def test_without_a_link_folder_a_layout_that_differs_is_refused_before_anything_moves(world):
    root, tasks, first, second = shared_world(world)
    _, item = one(tasks, "rename", root / "Films" / "Dune.mkv", root / "Films" / "Dune (2021).mkv")
    assert item["state"] == "failed" and item["reason"].startswith("Dossier de liens requis")
    assert (root / "Films" / "Dune.mkv").exists() and not first.calls
    assert not second.calls


def test_a_failed_recheck_puts_every_torrent_back_at_its_old_place_still_seeding(world):
    root, tasks, first, second = shared_world(world, rechecked=0.5)
    _, item = one(tasks, "move", root / "Films" / "Dune.mkv", root / "Downloads")
    assert item["state"] == "failed", item
    assert (root / "Films" / "Dune.mkv").exists() and not (root / "Downloads" / "Dune.mkv").exists()
    assert first.torrents[A].save_path == root / "Films"
    assert second.torrents[B].save_path == root / "Films"
    assert second.calls[-1] == ("start", B)  # it seeds again
