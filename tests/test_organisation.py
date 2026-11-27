"""Organisation: Jellyfin names from templates, proposals per release, seeded rows."""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from torrentlinker.domain import ContentKind, LibraryFolder, Torrent
from torrentlinker.file_annotations import seeds_of
from torrentlinker.file_storage import FileStorage
from torrentlinker.file_tasks import Tasks
from torrentlinker.organisation import DEFAULTS, Organisation, example, fill, template_error


def test_the_default_templates_give_the_jellyfin_layout():
    film = {"titre": "Dune", "année": "2021", "tmdbid": "438631"}
    assert fill(DEFAULTS["film"], film) == ["Dune (2021) [tmdbid-438631]"] * 2
    series = {"titre": "Severance", "année": "2022", "saison": "01", "épisode": "03"}
    assert fill(DEFAULTS["series"], series) == ["Severance (2022)", "Saison 01", "Severance S01E03"]


def test_a_missing_id_or_year_drops_its_group_and_a_colon_becomes_a_dash():
    assert (
        fill(DEFAULTS["film"], {"titre": "Dune: Part Two", "année": "2024"})
        == ["Dune - Part Two (2024)"] * 2
    )
    assert fill("{titre} ({année})", {"titre": "Dune"}) == ["Dune"]


@pytest.mark.parametrize(
    ("template", "fragment"),
    [("{titre}/{nope}", "Unknown token"), ("{année}", "{titre}"), ("../{titre}", "Invalid"),
     ("{titre}/a/b/c", "Three levels")],
)  # fmt: skip
def test_a_bad_template_says_why(template, fragment):
    assert fragment in template_error(template)
    assert example(template, "film") == ""


class Client:
    def __init__(self, native: bool) -> None:
        if not native:
            self.repoint = lambda *a: None


def world(tmp_path: Path, *, torrent: Torrent | None = None, native: bool = True):
    root = tmp_path / "lib"
    folder = root / "Films"
    release = folder / "Dune.2021.1080p.BluRay.x265-GRP"
    release.mkdir(parents=True)
    (release / "Dune.2021.1080p.BluRay.x265-GRP.mkv").write_bytes(b"v" * 100)
    (release / "Dune.2021.1080p.BluRay.x265-GRP.fr.srt").write_bytes(b"s")
    data = tmp_path / "data"
    data.mkdir()
    storage = FileStorage(data, (root,))
    db = sqlite3.connect(":memory:", check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute("CREATE TABLE media_items (id TEXT, client TEXT, path TEXT, body TEXT)")
    body = {"kind": "video", "title": "Dune", "year": "2021", "tmdb_id": "438631"}
    db.execute(
        "INSERT INTO media_items VALUES ('1', 'c', ?, ?)",
        (str(release / "Dune.2021.1080p.BluRay.x265-GRP.mkv"), json.dumps(body)),
    )
    media = SimpleNamespace(db=db, lock=threading.RLock())
    seeds = seeds_of([("default", "qBittorrent", torrent)] if torrent else [])
    organisation = Organisation(
        storage, media, lambda: [LibraryFolder(folder, kind=ContentKind.MOVIE)],
        lambda path: seeds, lambda client_id: Client(native),
    )  # fmt: skip
    return folder, release, storage, organisation


def test_a_film_is_proposed_under_its_jellyfin_name_with_its_subtitles(tmp_path: Path):
    folder, release, _, organisation = world(tmp_path)
    [card] = organisation.folders("c")
    [row] = card["rows"]
    name = "Dune (2021) [tmdbid-438631]"
    assert row["current"] == release.name and row["proposed"] == f"{name}/{name}.mkv"
    assert {m["to"] for m in row["maps"]} == {
        str(folder / name / f"{name}.mkv"),
        str(folder / name / f"{name}.fr.srt"),
    }
    assert card["templates"][0]["example"].startswith("Dune (2021) [tmdbid-438631]")
    assert row["seed"] is None and not row["needs_link"]


def test_applying_renames_on_disk_and_leaves_no_empty_folder_behind(tmp_path: Path):
    folder, release, storage, organisation = world(tmp_path)
    [row] = organisation.folders("c")[0]["rows"]
    tasks = Tasks(storage, threaded=False)
    task = tasks.submit(
        "rename", [{"from": m["from"], "to": m["to"]} for m in row["maps"]], "owner", "skip"
    )
    assert {i["state"] for i in task["items"]} == {"done"}
    name = "Dune (2021) [tmdbid-438631]"
    assert (folder / name / f"{name}.mkv").is_file() and not release.exists()


def test_a_template_is_saved_per_library_folder_and_changes_the_proposal(tmp_path: Path):
    folder, _, storage, organisation = world(tmp_path)
    storage.set_template(str(folder), "film", "{titre} ({année})")
    [row] = organisation.folders("c")[0]["rows"]
    assert row["proposed"] == "Dune (2021).mkv"
    storage.set_template(str(folder), "film", "")  # back to the Jellyfin default
    assert organisation.template(folder, "film") == DEFAULTS["film"]


def seeded(tmp_path: Path, native: bool):
    folder = tmp_path / "lib" / "Films"
    torrent = Torrent(
        "a" * 40, "Dune.2021.1080p.BluRay.x265-GRP", folder,
        files={"Dune.2021.1080p.BluRay.x265-GRP/Dune.2021.1080p.BluRay.x265-GRP.mkv": 100},
        state="uploading", ratio=2.0,
    )  # fmt: skip
    return world(tmp_path, torrent=torrent, native=native)[3]


def test_a_native_client_renames_inside_the_torrent(tmp_path: Path):
    [row] = seeded(tmp_path, True).folders("c")[0]["rows"]
    assert row["seed"]["client"] == "qBittorrent" and row["seed"]["native"]
    assert not row["needs_link"] and not row["problem"]


def test_a_client_that_cannot_rename_inside_a_torrent_needs_a_link_folder(tmp_path: Path):
    [row] = seeded(tmp_path, False).folders("c")[0]["rows"]
    assert row["needs_link"] and not row["seed"]["native"]
