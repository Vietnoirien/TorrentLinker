"""Reattaching torrents whose data Ranger copied into the library (#223). Fake client only."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from torrentlinker.domain import Torrent
from torrentlinker.seed_repair import apply, library_index, missing, plan


class Client:
    """qBittorrent as far as a repair needs: names inside the torrent, a check that finds
    the data where the names say."""

    def __init__(self, torrent: Torrent) -> None:
        self.t = torrent
        self.calls: list[tuple] = []
        self.checks = 0

    def pause(self, hash):
        self.calls.append(("pause",))
        self.t = replace(self.t, state="pausedUP")

    def set_location(self, hash, path):
        self.calls.append(("set_location", path))
        self.t = replace(self.t, save_path=Path(path))

    def rename_file(self, hash, old, new):
        self.calls.append(("rename", old, new))
        files = dict(self.t.files)
        files[new] = files.pop(old)
        self.t = replace(self.t, files=files)

    def recheck(self, hash):
        self.calls.append(("recheck",))
        self.checks = 2  # two looks while it checks

    def torrent(self, hash, with_files=True):
        if self.checks:
            self.checks -= 1
            return replace(self.t, state="checkingUP")
        there = sum(s for n, s in self.t.files.items() if (self.t.save_path / n).exists())
        return replace(self.t, progress=there / sum(self.t.files.values()), state="pausedUP")

    def start(self, hash):
        self.calls.append(("start",))


def library(tmp_path: Path) -> tuple[Path, Path]:
    films, series = tmp_path / "library" / "Films", tmp_path / "library" / "Séries"
    (films / "Gourou (2026)").mkdir(parents=True)
    (films / "Gourou (2026)" / "Gourou (2026).mkv").write_bytes(b"g" * 300)
    (series / "Black Mirror" / "Saison 03").mkdir(parents=True)
    for n in (1, 2):
        (series / "Black Mirror" / "Saison 03" / f"Black Mirror S03E0{n}.mkv").write_bytes(
            bytes([n]) * (200 + n)
        )
    return films, series


def test_a_lone_film_is_reattached_to_its_library_copy_and_seeds_again(tmp_path: Path):
    films, series = library(tmp_path)
    torrent = Torrent(
        "a" * 40, "Gourou.2026.mkv", tmp_path / "windocs" / "Film",
        files={"Gourou.2026.mkv": 300}, progress=1.0,
    )  # fmt: skip
    assert missing(torrent)
    repair = plan(torrent, library_index([films, series]), [films, series])
    assert repair is not None and repair.save_path == films
    assert repair.renames == [("Gourou.2026.mkv", "Gourou (2026)/Gourou (2026).mkv")]
    client = Client(torrent)
    assert apply(client, repair, wait=lambda s: None) == "seeding"
    assert client.calls[0] == ("pause",) and client.calls[-1] == ("start",)
    assert (films / "Gourou (2026)" / "Gourou (2026).mkv").read_bytes() == b"g" * 300


def test_a_season_pack_is_reattached_file_by_file(tmp_path: Path):
    films, series = library(tmp_path)
    torrent = Torrent(
        "b" * 40, "Black.Mirror.S03", tmp_path / "windocs" / "Séries",
        files={"Black.Mirror.S03/E01.mkv": 201, "Black.Mirror.S03/E02.mkv": 202,
               "Black.Mirror.S03/info.nfo": 7},
        progress=1.0,
    )  # fmt: skip
    repair = plan(torrent, library_index([films, series]), [films, series])
    assert repair is not None and repair.save_path == series
    assert dict(repair.renames)["Black.Mirror.S03/E02.mkv"] == (
        "Black Mirror/Saison 03/Black Mirror S03E02.mkv"
    )
    assert repair.unmatched == ["Black.Mirror.S03/info.nfo"]  # fetched again, nothing more
    client = Client(torrent)
    assert apply(client, repair, wait=lambda s: None) == "partial"  # the nfo is missing


def test_nothing_is_guessed_when_the_copy_is_not_found_or_found_twice(tmp_path: Path):
    films, series = library(tmp_path)
    (films / "Other (2020)").mkdir()
    (films / "Other (2020)" / "Other (2020).mkv").write_bytes(b"o" * 300)  # same size twice
    torrent = Torrent(
        "c" * 40, "Gourou.2026.mkv", tmp_path / "windocs", files={"Gourou.2026.mkv": 300}
    )
    assert plan(torrent, library_index([films, series]), [films, series]) is None
    present = Torrent("d" * 40, "x.mkv", films / "Gourou (2026)", files={"Gourou (2026).mkv": 300})
    assert not missing(present)  # a torrent whose data is there is left alone


def test_a_torrent_fetching_again_what_the_library_holds_is_reattached(tmp_path: Path):
    """The client found the files gone and started over: its partial copy is left aside and
    the torrent points at the library's whole one."""
    films, series = library(tmp_path)
    old = tmp_path / "windocs" / "Film"
    old.mkdir(parents=True)
    (old / "Gourou.2026.mkv").write_bytes(b"g" * 120)  # 40 % fetched again
    torrent = Torrent(
        "e" * 40, "Gourou.2026.mkv", old, files={"Gourou.2026.mkv": 300}, progress=0.4,
        state="error",
    )  # fmt: skip
    assert missing(torrent)
    repair = plan(torrent, library_index([films, series]), [films, series])
    assert repair is not None and repair.left == [old / "Gourou.2026.mkv"]
    assert apply(Client(torrent), repair, wait=lambda s: None) == "seeding"
