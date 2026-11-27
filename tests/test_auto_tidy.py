"""Ranger automatiquement: a finished download is renamed and moved to the placement rule's pick."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from torrentlinker.auto_tidy import AutoTidy, plan
from torrentlinker.domain import ContentKind, LibraryFolder, Torrent
from torrentlinker.file_storage import FileStorage
from torrentlinker.file_tasks import Tasks
from torrentlinker.organisation import DEFAULTS


def template_of(folder, kind):
    return DEFAULTS[kind]


def world(tmp_path: Path):
    root = tmp_path / "lib"
    downloads, films = root / "Downloads", root / "Films"
    downloads.mkdir(parents=True)
    films.mkdir()
    release = downloads / "Dune.2021.1080p.BluRay.x265-GRP"
    release.mkdir()
    (release / "Dune.2021.1080p.BluRay.x265-GRP.mkv").write_bytes(b"v" * 100)
    data = tmp_path / "data"
    data.mkdir()
    storage = FileStorage(data, (root,))
    torrent = Torrent(
        "a" * 40, release.name, downloads, state="uploading", progress=0.4,
        files={f"{release.name}/{release.name}.mkv": 100},
    )  # fmt: skip
    cards = [{"id": "d", "name": "lib", "roots": [str(root)], "usable": 10**9, "writable": True,
              "below_margin": False}]  # fmt: skip
    library = [LibraryFolder(films, kind=ContentKind.MOVIE)]
    return root, downloads, films, release, storage, torrent, cards, library


def test_the_plan_renames_inside_the_torrent_then_moves_it_to_the_library(tmp_path: Path):
    _, downloads, films, release, _, torrent, cards, library = world(tmp_path)
    found = plan(torrent, True, library, cards, template_of)
    assert found["kind"] == "film" and found["destination"] == str(films)
    rename, move = found["items"]
    assert rename["kind"] == "rename" and rename["to"].endswith("Dune (2021)/Dune (2021).mkv")
    assert move["kind"] == "move" and move["from"] == str(downloads / "Dune (2021)")


def test_a_client_that_cannot_rename_inside_a_torrent_is_left_alone(tmp_path: Path):
    *_, torrent, cards, library = world(tmp_path)
    assert "Link Folder" in plan(torrent, False, library, cards, template_of)["skip"]


def test_off_by_default_and_only_what_finishes_after_it_is_switched_on(tmp_path: Path):
    root, downloads, films, release, storage, torrent, cards, library = world(tmp_path)
    tasks = Tasks(storage, threaded=False)
    tidy = AutoTidy(
        tmp_path / "data",
        storage,
        lambda kind, items, actor: tasks.submit(kind, items, actor, "skip"),
    )

    def tick(t):
        return tidy.tick("default", [t], True, [downloads], library, cards, template_of)

    assert tick(torrent) == [] and release.exists()  # the option is off
    storage.set_auto_tidy(str(downloads), True)
    finished = replace(torrent, progress=1.0)
    assert tick(finished) == []  # it was never seen downloading: it finished before
    assert tick(torrent) == []  # still downloading: remembered
    assert tick(finished) == ["done"]
    assert (films / "Dune (2021)" / "Dune (2021).mkv").read_bytes() == b"v" * 100
    assert not release.exists() and tick(finished) == []  # tidied once
    assert tidy.results()[0]["state"] == "done"
