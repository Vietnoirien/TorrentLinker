"""Moving and renaming a seeded torrent through every Torrent Client (ADR-0029)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.test_deluge_unit import FakeWebUi
from tests.test_deluge_unit import api_for as deluge_for
from tests.test_rtorrent_unit import FakeRtorrent
from tests.test_rtorrent_unit import api_for as rtorrent_for
from tests.test_transmission_unit import FakeRpc
from tests.test_transmission_unit import api_for as transmission_for
from tests.test_utorrent_unit import WebUI
from tests.test_utorrent_unit import api_for as utorrent_for
from tests.torrents import make_torrent
from torrentlinker.domain import Torrent
from torrentlinker.storage_moves import StorageMoveError, move_torrent, rename_in_torrent
from torrentlinker.utorrent import UtorrentError


class DelugeMoves(FakeWebUi):
    def core_move_storage(self, hashes: list[str], path: str) -> None:
        for h in hashes:
            self.torrents[h]["download_location"] = path


class TransmissionMoves(FakeRpc):
    def torrent_set_location(self, ids: list[str], location: str, move: bool) -> None:
        assert move is True
        self.torrents[ids[0]]["downloadDir"] = location


class RtorrentMoves(FakeRtorrent):
    finds_files = True

    def call(self, method: str, *params: Any) -> Any:
        if method == "d.directory.set":
            self.calls.append((method, params))
            self.torrents[params[0]]["d.directory"] = params[1]
            return 0
        if method == "d.check_hash":
            self.calls.append((method, params))
            if self.finds_files:
                self.torrents[params[0]].update({"d.complete": 1, "d.left_bytes": 0})
            return 0
        return super().call(method, *params)


def test_deluge_moves_the_data_through_move_storage(tmp_path: Path) -> None:
    web = DelugeMoves()
    api = deluge_for(web)
    (tmp_path / "book.epub").write_bytes(b"x" * 1000)
    h = api.add(make_torrent(tmp_path / "book.epub"), "/lib", [])
    web.torrents[h].update(progress=100.0, state="Seeding")
    api.set_location(h, "/library/Films")
    assert api.torrent(h, with_files=False).save_path == Path("/library/Films")  # type: ignore[union-attr]
    assert ("core.move_storage", [[h], "/library/Films"]) in web.calls


def test_transmission_moves_the_data_with_set_location(tmp_path: Path) -> None:
    rpc = TransmissionMoves()
    api = transmission_for(rpc)
    (tmp_path / "book.epub").write_bytes(b"x" * 1000)
    h = api.add(make_torrent(tmp_path / "book.epub"), "/lib", [])
    api.set_location(h, "/library/Films")
    assert api.torrent(h, with_files=False).save_path == Path("/library/Films")  # type: ignore[union-attr]


def test_deluge_and_transmission_rename_inside_the_client(tmp_path: Path) -> None:
    web = DelugeMoves()
    api = deluge_for(web)
    (tmp_path / "book.epub").write_bytes(b"x" * 1000)
    h = api.add(make_torrent(tmp_path / "book.epub"), "/lib", [])
    web.torrents[h].update(progress=100.0, state="Seeding")
    rename_in_torrent(api, h, "book.epub", "Book (2020).epub")
    assert list(api.files(h)) == ["Book (2020).epub"]


def test_rtorrent_stops_moves_on_disk_repoints_rechecks_and_starts(tmp_path: Path) -> None:
    fake = RtorrentMoves()
    api = rtorrent_for(fake)
    source = tmp_path / "old"
    (source / "Show").mkdir(parents=True)
    (source / "Show" / "e1.mkv").write_bytes(b"a" * 3000)
    (source / "Show" / "e2.mkv").write_bytes(b"b" * 2000)
    h = api.add(make_torrent(source / "Show"), str(source), [])
    fake.torrents[h.upper()]["d.complete"] = 1
    fake.torrents[h.upper()]["d.left_bytes"] = 0
    fake.torrents[h.upper()]["d.completed_bytes"] = 5000
    destination = tmp_path / "new"
    move_torrent(api, h, destination)
    assert (destination / "Show" / "e1.mkv").exists() and not (source / "Show").exists()
    assert fake.torrents[h.upper()]["d.directory"] == f"{destination}/Show"
    order = [
        m for m, _ in fake.calls if m in {"d.stop", "d.directory.set", "d.check_hash", "d.start"}
    ]
    assert order == ["d.stop", "d.directory.set", "d.check_hash", "d.start"]


def test_a_failed_rtorrent_move_puts_the_files_back_and_starts_it_again(tmp_path: Path) -> None:
    fake = RtorrentMoves()
    api = rtorrent_for(fake)
    source = tmp_path / "old"
    (source / "Show").mkdir(parents=True)
    (source / "Show" / "e1.mkv").write_bytes(b"a" * 3000)
    (source / "Show" / "e2.mkv").write_bytes(b"b" * 2000)
    h = api.add(make_torrent(source / "Show"), str(source), [])
    fake.finds_files = False  # the recheck finds nothing at the new place
    fake.torrents[h.upper()].update({"d.complete": 0, "d.left_bytes": 5000})
    destination = tmp_path / "new"
    with pytest.raises(StorageMoveError, match="Torrent Client does not find"):
        move_torrent(api, h, destination)
    assert (source / "Show" / "e1.mkv").exists()
    assert fake.calls[-1][0] == "d.start"
    assert fake.torrents[h.upper()]["d.directory"] == f"{source}/Show"


def test_utorrent_repoints_by_adding_the_same_torrent_stopped_at_the_new_place(
    tmp_path: Path,
) -> None:
    (tmp_path / "new.txt").write_bytes(b"disposable" * 100)
    data = make_torrent(tmp_path / "new.txt")
    web = WebUI()
    api = utorrent_for(web)
    h = api.add(data, "C:\\Downloads\\Old", [])
    api.repoint(h, "C:\\Downloads\\New", data)
    assert web.jobs[h][26] == "C:\\Downloads\\New"
    with pytest.raises(UtorrentError, match="torrent's own file"):
        api.repoint(h, "C:\\Downloads\\Other")


def test_utorrent_restores_its_registration_when_the_new_place_is_refused(tmp_path: Path) -> None:
    (tmp_path / "new.txt").write_bytes(b"disposable" * 100)
    data = make_torrent(tmp_path / "new.txt")
    web = WebUI()
    api = utorrent_for(web)
    h = api.add(data, "C:\\Downloads\\Old", [])
    with pytest.raises(UtorrentError):
        api.repoint(h, "D:\\Elsewhere", data)
    assert web.jobs[h][26] == "C:\\Downloads\\Old"


class FakeClient:
    """A client with one torrent, for the rules that do not depend on the client."""

    def __init__(self, torrent: Torrent) -> None:
        self.t = torrent
        self.log: list[str] = []

    def torrent(self, hash: str, with_files: bool = True) -> Torrent | None:
        return self.t

    def start(self, hash: str) -> None:
        self.log.append("start")

    def pause(self, hash: str) -> None:
        self.log.append("pause")


@pytest.mark.parametrize("tag", ["torrentlinker:verifying", "torrentlinker:link-a"])
def test_a_torrent_under_reseed_verification_is_refused(tag: str, tmp_path: Path) -> None:
    client = FakeClient(Torrent("a" * 40, "x", tmp_path, {"x": 1}, tags=frozenset({tag})))
    with pytest.raises(StorageMoveError, match="Reseed Verification"):
        move_torrent(client, "a" * 40, tmp_path / "other")  # type: ignore[arg-type]
    with pytest.raises(StorageMoveError, match="Reseed Verification"):
        rename_in_torrent(client, "a" * 40, "x", "y")  # type: ignore[arg-type]
    assert client.log == []


def test_rtorrent_renames_only_its_own_folder(tmp_path: Path) -> None:
    fake = RtorrentMoves()
    api = rtorrent_for(fake)
    (tmp_path / "Show").mkdir()
    (tmp_path / "Show" / "e1.mkv").write_bytes(b"a" * 3000)
    (tmp_path / "Show" / "e2.mkv").write_bytes(b"b" * 2000)
    h = api.add(make_torrent(tmp_path / "Show"), str(tmp_path), [])
    fake.torrents[h.upper()].update({"d.complete": 1, "d.left_bytes": 0, "d.completed_bytes": 5000})
    with pytest.raises(StorageMoveError, match="only its folder"):
        rename_in_torrent(api, h, "Show/e1.mkv", "Show/Episode 1.mkv")
    rename_in_torrent(api, h, "Show", "Show (2020)")
    assert (tmp_path / "Show (2020)" / "e1.mkv").exists()
    assert fake.torrents[h.upper()]["d.directory"] == f"{tmp_path}/Show (2020)"
