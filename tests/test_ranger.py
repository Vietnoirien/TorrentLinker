"""Organisation's board: roles, links, Ranger, Auto, À vérifier and the emptied provenance (#223).
Fake Torrent Clients only: they record what they are told and never reach a real client."""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from torrentlinker import file_tasks
from torrentlinker.auto_tidy import AutoTidy
from torrentlinker.domain import ContentKind, LibraryFolder, Torrent
from torrentlinker.file_annotations import seeds_of
from torrentlinker.file_storage import FileStorage
from torrentlinker.file_tasks import Tasks
from torrentlinker.library_items import Item, discover, readable
from torrentlinker.organisation import Organisation
from torrentlinker.path_follow import replace_library
from torrentlinker.ranger import Board, RangerQueue

DUNE = "Dune.2021.1080p.BluRay.x265-GRP"


class Qb:
    """A qBittorrent that renames and moves files itself, as the real one does."""

    def __init__(self, *torrents: Torrent) -> None:
        self.torrents = {t.hash: t for t in torrents}
        self.calls: list[tuple] = []

    def torrent(self, hash, with_files=True):
        return self.torrents.get(hash)

    def rename_file(self, hash, old, new):
        self.calls.append(("rename_file", old, new))
        found = self.torrents[hash]
        (found.save_path / new).parent.mkdir(parents=True, exist_ok=True)
        (found.save_path / old).rename(found.save_path / new)
        files = {(new if n == old else n): size for n, size in found.files.items()}
        self.torrents[hash] = replace(found, files=files)

    def set_location(self, hash, path):
        self.calls.append(("set_location", hash, path))
        found = self.torrents[hash]
        for name in {Path(n).parts[0] for n in found.files}:
            (found.save_path / name).rename(Path(path) / name)
        self.torrents[hash] = replace(found, save_path=Path(path))

    def pause(self, hash):
        self.calls.append(("pause", hash))

    def start(self, hash):
        self.calls.append(("start", hash))

    def recheck(self, hash):
        self.calls.append(("recheck", hash))


class World:
    def __init__(self, tmp_path: Path, torrent: Torrent | None = None) -> None:
        self.root = tmp_path / "disk"
        self.old = self.root / "Old"
        self.films, self.series = self.root / "Films", self.root / "Séries"
        for folder in (self.old, self.films, self.series):
            folder.mkdir(parents=True)
        release = self.old / DUNE
        release.mkdir()
        (release / f"{DUNE}.mkv").write_bytes(b"v" * 100)
        (release / f"{DUNE}.fr.srt").write_bytes(b"s")
        (release / "info.nfo").write_bytes(b"n")
        (self.old / "Alien.1979.720p.BluRay.x264.mkv").write_bytes(b"a" * 50)
        pack = self.old / "Black.Mirror.S01.1080p"
        pack.mkdir()
        for n in (1, 2):
            (pack / f"Black.Mirror.S01E0{n}.1080p.WEB.mkv").write_bytes(b"e" * 30)
        (self.old / "IMG_3310.mov").write_bytes(b"m" * 20)
        (self.old / "Sci-Fi").mkdir()
        (self.old / "Sci-Fi" / "Moon.2009.FRENCH.720p.BluRay.x264.mkv").write_bytes(b"x" * 40)
        (self.old / "Sci-Fi" / "Solaris.1972.1080p.BluRay.mkv").write_bytes(b"y" * 40)
        data = tmp_path / "data"
        data.mkdir()
        self.data = data
        self.storage = FileStorage(data, (self.root,))
        self.libraries = [
            LibraryFolder(self.old, kind=ContentKind.OTHER),
            LibraryFolder(self.films, kind=ContentKind.MOVIE),
            LibraryFolder(self.series, kind=ContentKind.SERIES),
        ]
        db = sqlite3.connect(":memory:", check_same_thread=False)
        db.row_factory = sqlite3.Row
        db.execute("CREATE TABLE media_items (id TEXT, client TEXT, path TEXT, body TEXT)")
        db.execute(
            "INSERT INTO media_items VALUES ('1', 'c', ?, ?)",
            (
                str(release / f"{DUNE}.mkv"),
                json.dumps({"kind": "video", "title": "Dune", "year": "2021", "tmdb_id": "438631"}),
            ),
        )
        self.media = SimpleNamespace(db=db, lock=threading.RLock())
        self.client = Qb(torrent) if torrent else Qb()
        self.swapped: list[tuple[Path, list[Path]]] = []
        self.board = Board(
            self.storage, Organisation(self.storage), self.media,
            lambda: self.libraries, lambda: [], self.seeds, lambda _id: self.client,
            lambda: "c", lambda _id: "", self.register, self.swap, threaded=False,
        )  # fmt: skip
        self.tasks = Tasks(
            self.storage, seeds=lambda path: [(t, i) for t, i in self.seeds() if _related(path, t)],
            client_of=lambda _id: self.client, threaded=False,
        )  # fmt: skip
        self.queue = RangerQueue(data, self.board, lambda: self.tasks)
        self.tasks.planner = self.queue.planner

    def seeds(self):
        return seeds_of([("c", "qBittorrent", t) for t in self.client.torrents.values()])

    def register(self, path: Path, kind: ContentKind) -> None:
        self.libraries = [f for f in self.libraries if Path(f.path) != path]
        self.libraries.append(LibraryFolder(path, kind=kind))

    def swap(self, old: Path, new: list[Path]) -> None:
        self.swapped.append((old, new))
        self.libraries = [f for f in self.libraries if Path(f.path) != old]

    def organise(self) -> None:
        """The Owner's choices: the old folder is a provenance, the two others are libraries."""
        self.board.set_role(str(self.old), "prov")
        self.board.set_role(str(self.films), "lib", "films")
        self.board.set_role(str(self.series), "lib", "series")
        self.board.scan()


def _related(path: Path, top: Path) -> bool:
    return path == top or path.is_relative_to(top) or top.is_relative_to(path)


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path)


def test_a_name_that_tells_nothing_is_never_a_title():
    from guessit import guessit

    for name in (
        "IMG_3310.mov",
        "movie.mkv",
        "1080p.x265-GRP.mkv",
        "a8f3k2.mkv",
        "Sans titre 2.mp4",
    ):
        assert not readable(name, guessit(name)), name
    for name in ("Moon.2009.FRENCH.720p.BluRay.x264.mkv", "Inception.mkv", "Gourou (2026)"):
        assert readable(name, guessit(name)), name


def test_discovery_finds_films_series_and_what_a_grouping_folder_holds(world: World):
    found = {i.name: i for i in discover(world.old)}
    assert found[DUNE].kind == "film" and found[DUNE].recognised
    assert found["Black.Mirror.S01.1080p"].kind == "series"  # the pack is one series, not 2 films
    assert found["Sci-Fi/Moon.2009.FRENCH.720p.BluRay.x264.mkv"].group == "Sci-Fi"
    assert "Sci-Fi" not in found  # a grouping folder is not an item
    assert not found["IMG_3310.mov"].recognised


def test_the_default_roles_and_the_owner_s_choice(world: World):
    assert world.board.roles() == {}  # nothing has a role until the Owner gives it one
    assert {r["role"] for r in world.board.folders()} == {""}
    world.organise()
    assert world.board.roles()[str(world.old)] == "prov"
    assert [lib["kind"] for lib in world.board.libraries()] == ["films", "series"]
    (world.films / "x").mkdir()
    with pytest.raises(Exception, match="Library and Download Folders"):
        world.board.set_role(str(world.films / "x"), "lib")  # not a folder of Paramètres


def test_the_board_counts_each_provenance_and_lists_what_to_check(world: World):
    world.organise()
    [prov] = world.board.state()["provenances"]
    assert (prov["films"], prov["series"]) == (4, 1)  # Dune, Alien, Moon, Solaris; Black Mirror
    assert [r["name"] for r in prov["review"]] == ["IMG_3310.mov"]
    assert prov["auto"] is False  # an old library does not range by itself
    assert dict(prov["subs"]) == {"Sci-Fi": 2} and prov["ready"]


def test_the_summary_says_where_each_kind_goes_and_never_counts_the_unrecognised(world: World):
    world.organise()
    found = world.board.summary([str(world.old)])
    assert found["n"] == 5 and found["review"] == 1
    assert {(d["kind"], d["n"], Path(d["lib"]).name) for d in found["dests"]} == {
        ("film", 4, "Films"), ("series", 1, "Séries"),
    }  # fmt: skip
    assert found["seconds"] == 0  # one disk: instant
    assert any(e["to"].startswith("Dune (2021)") for e in found["examples"])


def test_a_provenance_pinned_to_the_films_library_still_sends_its_series_to_theirs(world: World):
    world.organise()
    world.board.set_link(str(world.old), str(world.films))
    found = world.board.summary([str(world.old)])
    assert [r["n"] for r in found["routed"]] == [1]  # the series, routed by kind
    assert {Path(d["lib"]).name for d in found["dests"]} == {"Films", "Séries"}
    world.board.set_link(str(world.old), "")
    assert world.board.pinned(str(world.old)) == ""


def test_ranger_renames_and_moves_each_item_in_one_pass_and_keeps_what_to_check(world: World):
    world.organise()
    rows = [
        {"top": i.path, "prov": str(world.old), "kind": i.kind}
        for i in world.board.items(str(world.old))
        if i.recognised
    ]
    world.queue.enqueue("Ranger", "owner", rows)
    assert (
        world.films / "Dune (2021) [tmdbid-438631]" / "Dune (2021) [tmdbid-438631].mkv"
    ).exists()
    assert (
        world.films / "Dune (2021) [tmdbid-438631]" / "Dune (2021) [tmdbid-438631].fr.srt"
    ).exists()
    assert (world.films / "Dune (2021) [tmdbid-438631]" / "info.nfo").exists()
    assert (world.films / "Alien (1979)" / "Alien (1979).mkv").exists()
    assert (world.films / "Moon (2009)" / "Moon (2009).mkv").exists()
    assert (world.series / "Black Mirror" / "Saison 01" / "Black Mirror S01E02.mkv").exists()
    assert (world.old / "IMG_3310.mov").exists()  # never moved blindly
    assert not (world.old / DUNE).exists()  # the emptied release folder is gone
    [task] = world.tasks.snapshot()
    assert task["state"] == "done" and task["kind"] == "ranger"


def test_a_seeded_release_moves_and_renames_through_its_client_and_keeps_seeding(tmp_path: Path):
    torrent = Torrent(
        "a" * 40, DUNE, tmp_path / "disk" / "Old", state="uploading", progress=1.0,
        files={f"{DUNE}/{DUNE}.mkv": 100, f"{DUNE}/{DUNE}.fr.srt": 1, f"{DUNE}/info.nfo": 1},
    )  # fmt: skip
    world = World(tmp_path, torrent)
    world.organise()
    item = next(i for i in world.board.items(str(world.old)) if i.name == DUNE)
    world.queue.enqueue(
        "Ranger", "owner", [{"top": item.path, "prov": str(world.old), "kind": "film"}]
    )
    [task] = world.tasks.snapshot()
    assert task["items"][0]["state"] == "done", task["items"][0]
    after = world.client.torrents["a" * 40]
    assert after.save_path == world.films
    assert set(after.files) == {
        "Dune (2021) [tmdbid-438631]/Dune (2021) [tmdbid-438631]" + ext
        for ext in (".mkv", ".fr.srt")
    } | {"Dune (2021) [tmdbid-438631]/info.nfo"}
    assert (world.films / next(iter(after.files))).exists()
    assert [c[0] for c in world.client.calls].count("set_location") == 1


def test_a_failed_move_puts_the_names_back(world: World, monkeypatch):
    world.organise()
    (world.films / "Alien (1979)").mkdir()  # the name is taken in the library
    item = next(i for i in world.board.items(str(world.old)) if i.name.startswith("Alien"))
    world.queue.enqueue(
        "Ranger", "owner", [{"top": item.path, "prov": str(world.old), "kind": "film"}]
    )
    [task] = world.tasks.snapshot()
    assert task["items"][0]["state"] == "failed" and "existe déjà" in task["items"][0]["reason"]
    assert Path(item.path).exists()  # it stays, under its own name


def test_a_title_fix_makes_an_item_ready_and_keeping_it_removes_it_from_the_list(world: World):
    world.organise()
    path = str(world.old / "IMG_3310.mov")
    world.board.fix_title(path, "Le Mariage de Sonia")
    [prov] = world.board.state()["provenances"]
    assert prov["review"] == [] and prov["films"] == 5
    world.queue.enqueue("Ranger", "owner", [{"top": path, "prov": str(world.old), "kind": "film"}])
    assert (world.films / "Le Mariage de Sonia" / "Le Mariage de Sonia.mov").exists()
    other = world.old / "movie.mkv"
    other.write_bytes(b"z")
    world.board.scan()
    world.board.keep(str(other))
    assert world.board.state()["provenances"][0]["review"] == []
    assert world.board.summary([str(world.old)])["review"] == 0


def test_a_copy_to_another_disk_is_estimated_and_the_large_batch_is_kept_on_disk(
    world: World, monkeypatch
):
    monkeypatch.setattr(file_tasks, "same_device", lambda a, b: False)
    monkeypatch.setattr(Board, "_root", lambda self, path: "/a" if "Old" in path else "/b")
    world.organise()
    found = world.board.summary([str(world.old)])
    assert found["seconds"] == 0 and found["bytes"] > 0  # tiny files: under a second
    rows = [
        {"top": i.path, "prov": str(world.old), "kind": i.kind}
        for i in world.board.items(str(world.old))
        if i.recognised
    ]
    job = world.queue.enqueue("Ranger", "owner", rows)
    states = {
        r["state"] for r in world.queue._db.execute("SELECT state FROM items WHERE job=?", (job,))
    }
    assert states == {"done"}


def test_after_a_restart_the_items_left_run_and_the_ones_done_are_not_repeated(world: World):
    world.organise()
    items = [i for i in world.board.items(str(world.old)) if i.recognised]
    db = world.queue._db
    # A batch that was queued, with one item done and one running when the application stopped.
    with db:
        db.execute("INSERT INTO jobs VALUES ('j1', 'Ranger', 'owner', 0, 'running')")
        for n, item in enumerate(items):
            state = "done" if n == 0 else "running" if n == 1 else "queued"
            db.execute(
                "INSERT INTO items (job, seq, prov, top, kind, title, state)"
                " VALUES ('j1', ?, ?, ?, ?, '', ?)",
                (n, str(world.old), item.path, item.kind, state),
            )
    first = items[0]
    again = RangerQueue(world.data, world.board, lambda: world.tasks)
    world.tasks.planner = again.planner
    assert again.resume() == 1
    [task] = world.tasks.snapshot()
    assert len(task["items"]) == len(items) - 1  # the done one is not in it
    assert Path(first.path).exists()  # and was not touched
    assert not [r for r in db.execute("SELECT * FROM items WHERE state IN ('queued','running')")]


def test_an_emptied_old_library_is_replaced_in_the_settings_and_grants_follow(world: World):
    world.organise()
    (world.old / "IMG_3310.mov").unlink()  # nothing to check is left either
    rows = [
        {"top": i.path, "prov": str(world.old), "kind": i.kind}
        for i in world.board.items(str(world.old))
        if i.recognised
    ]
    world.queue.enqueue("Ranger", "owner", rows)
    assert world.swapped and world.swapped[0][0] == world.old
    assert {p.name for p in world.swapped[0][1]} == {"Films", "Séries"}
    assert world.board.state()["provenances"][0]["swapped"] == [str(world.films), str(world.series)]


def test_a_provenance_with_something_left_is_not_replaced(world: World):
    world.organise()  # IMG_3310.mov is still there: À vérifier
    rows = [
        {"top": i.path, "prov": str(world.old), "kind": i.kind}
        for i in world.board.items(str(world.old))
        if i.recognised
    ]
    world.queue.enqueue("Ranger", "owner", rows)
    assert world.swapped == []


def test_replacing_a_library_in_the_settings_rewrites_the_members_grants(tmp_path: Path):
    from torrentlinker.accounts import Accounts, Permission

    accounts = Accounts(tmp_path)
    lea = accounts.create("Léa", "lea", {Permission.FILMS})
    accounts.set_media_limits(lea, "12", ["/old", "/other"])
    setup = SimpleNamespace(
        lock=threading.RLock(), _root=None, save=lambda: None,
        settings=SimpleNamespace(
            library_folders=[LibraryFolder(Path("/old")), LibraryFolder(Path("/new/Films"))]
        ),
    )  # fmt: skip
    found = replace_library(
        setup, accounts, Path("/old"), [Path("/new/Films"), Path("/new/Séries")]
    )
    assert found == {"library": 1, "grants": 1}
    assert [str(f.path) for f in setup.settings.library_folders] == ["/new/Films"]
    actor = accounts.actor(lea)
    assert actor is not None and actor.folders == {"/other", "/new/Films", "/new/Séries"}


def test_auto_ranges_only_what_finishes_after_it_was_seen_downloading(world: World, tmp_path: Path):
    downloads = world.root / "Downloads"
    downloads.mkdir()
    release = downloads / "Gourou.2026.FRENCH.720p.WEB.H265-TyHD"
    release.mkdir()
    (release / "Gourou.2026.FRENCH.720p.WEB.H265-TyHD.mkv").write_bytes(b"g" * 10)
    world.board.download_folders = lambda: [downloads]
    world.organise()
    world.board.set_role(str(downloads), "prov")
    assert world.board.auto_of(str(downloads))  # on for a download folder
    assert not world.board.auto_of(str(world.old))
    queued: list = []
    tidy = AutoTidy(world.data, lambda label, actor, rows: queued.append(rows))
    torrent = Torrent(
        "b" * 40, release.name, downloads, state="uploading", progress=0.4,
        files={f"{release.name}/{release.name}.mkv": 10},
    )  # fmt: skip
    roots = world.board.auto_roots()
    assert tidy.tick("c", [replace(torrent, progress=1.0)], roots) == []  # finished before
    assert tidy.tick("c", [torrent], roots) == []  # still downloading: remembered
    assert tidy.tick("c", [replace(torrent, progress=1.0)], roots) == ["queued"]
    assert queued[0][0]["top"] == str(release) and queued[0][0]["prov"] == str(downloads)
    assert tidy.tick("c", [replace(torrent, progress=1.0)], roots) == []  # once
    world.queue.enqueue("Ranger", "Rangement automatique", queued[0])
    assert (world.films / "Gourou (2026)" / "Gourou (2026).mkv").exists()


def test_the_old_per_folder_switches_become_the_provenance_auto(world: World):
    (world.data / "files-settings.json").write_text(
        json.dumps({"auto_tidy": {str(world.old): True}}), encoding="utf-8"
    )
    world.organise()
    assert world.board.auto_of(str(world.old))
    world.board.set_auto(str(world.old), False)
    assert not world.board.auto_of(str(world.old))


def test_a_title_to_check_is_suggested_from_the_indexes_and_keeps_its_year(world: World):
    with world.media.lock:
        world.media.db.execute(
            "CREATE TABLE film_c411 (tkey TEXT, title TEXT, original_title TEXT, year TEXT)"
        )
        world.media.db.executemany(
            "INSERT INTO film_c411 VALUES ('', ?, ?, ?)",
            [("Épisode 50", "Episode 50", "2011"), ("La Septième Compagnie", "", "1973")],
        )
    assert world.board.suggest("é") == []  # one letter is not a search
    found = world.board.suggest("episode")  # without its accent, still found
    assert found == [{"title": "Épisode 50", "year": "2011", "kind": "film"}]
    assert world.board.suggest("Septieme")[0]["year"] == "1973"
    named = Item("/y", "Episode.50.2011.French.720P.WebRip.X264.mkv", "film", 1)
    assert world.board.proposals(named)[0]["title"] == "Épisode 50"
    item = Item("/x", "x.mkv", "film", 1, title="Épisode 50 (2011)", recognised=True)
    body = world.board._body(item, "")
    assert body["title"] == "Épisode 50" and body["year"] == "2011"


def test_the_board_s_counts_follow_a_batch_as_it_runs(world: World):
    """Each ranged item leaves its provenance's count at once, and the library that takes it
    counts it: the board never shows a full old folder and an empty library mid-batch."""
    world.organise()
    before = len(world.board.items(str(world.old)))
    alien = next(i for i in world.board.items(str(world.old)) if i.name.startswith("Alien"))
    world.queue.enqueue(
        "Ranger", "owner", [{"top": alien.path, "prov": str(world.old), "kind": "film"}]
    )
    assert len(world.board.items(str(world.old))) == before - 1
    assert len(world.board.items(str(world.films))) == 1


def test_a_film_cut_in_parts_is_one_film_with_its_parts_in_order(tmp_path: Path):
    """ "CD1.avi … CD8.avi" in a film's folder are its parts: one item named after the folder,
    the parts kept in order as "- part1", "- part2"…, never eight films called "CD1"."""
    world = World(tmp_path)
    folder = world.old / "Comédie" / "Ze inconnus story - Le bocôup meilleur FR Divx"
    folder.mkdir(parents=True)
    for n, name in enumerate(("CD1.avi", "Cd2.avi", "cd3.avi"), start=1):
        (folder / name).write_bytes(b"p" * (100 - n))  # sizes would put them out of order
    found = [i for i in discover(world.old) if "inconnus" in i.name]
    assert len(found) == 1 and found[0].path == str(folder)
    world.organise()
    item = next(i for i in world.board.items(str(world.old)) if "inconnus" in i.name)
    world.queue.enqueue(
        "Ranger", "owner", [{"top": item.path, "prov": str(world.old), "kind": "film"}]
    )
    [moved] = [p for p in world.films.iterdir() if "inconnus" in p.name.lower()]
    assert sorted(p.name.rsplit(" - ", 1)[1] for p in moved.iterdir()) == [
        "part1.avi", "part2.avi", "part3.avi",
    ]  # fmt: skip
    assert not readable("CD1.avi", {"title": "CD1"})
