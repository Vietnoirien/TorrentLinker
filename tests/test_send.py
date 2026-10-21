from pathlib import Path

import pytest

from tests.fake_qbit import FakeQbit
from tests.torrents import make_torrent
from torrentlinker.plan import Plan, PlanCandidate, PlanItem
from torrentlinker.send import ZEN_TAG, Refused, send_one, send_plan
from torrentlinker.torrent_meta import read_torrent


def release(tmp_path: Path, name: str = "Film.2020") -> bytes:
    src = tmp_path / "elsewhere" / name
    src.mkdir(parents=True)
    (src / "film.mkv").write_bytes(b"x" * 5000)
    (src / "film.nfo").write_bytes(b"n")
    return make_torrent(src)


def candidate(data: bytes, folder: Path) -> PlanCandidate:
    meta = read_torrent(data)
    return PlanCandidate(meta.infohash, meta.name, 5001, 3, 2000, folder, 1)


def test_a_plan_torrent_is_added_started_into_its_download_folder_with_the_zen_tag(
    tmp_path: Path,
) -> None:
    data, qbit = release(tmp_path), FakeQbit()
    folder = tmp_path / "dl"

    h = send_one(qbit, candidate(data, folder), data)

    t = qbit.torrent(h)
    assert t is not None and t.save_path == folder
    assert ZEN_TAG in t.tags
    assert qbit.downloads == [h]


def test_a_torrent_whose_file_already_exists_at_the_target_is_refused(tmp_path: Path) -> None:
    data, qbit = release(tmp_path), FakeQbit()
    folder = tmp_path / "dl"
    (folder / "Film.2020").mkdir(parents=True)
    (folder / "Film.2020" / "film.nfo").write_bytes(b"mine")

    with pytest.raises(Refused):
        send_one(qbit, candidate(data, folder), data)

    assert qbit.torrents() == []
    assert (folder / "Film.2020" / "film.nfo").read_bytes() == b"mine"


def test_an_existing_empty_folder_of_the_same_name_is_fine(tmp_path: Path) -> None:
    data, qbit = release(tmp_path), FakeQbit()
    (tmp_path / "dl" / "Film.2020").mkdir(parents=True)

    send_one(qbit, candidate(data, tmp_path / "dl"), data)

    assert len(qbit.torrents()) == 1


def test_a_file_standing_where_the_torrent_needs_a_folder_is_refused(tmp_path: Path) -> None:
    data, qbit = release(tmp_path), FakeQbit()
    (tmp_path / "dl").mkdir()
    (tmp_path / "dl" / "Film.2020").write_bytes(b"a file")

    with pytest.raises(Refused):
        send_one(qbit, candidate(data, tmp_path / "dl"), data)


def test_sending_reports_each_torrent_and_one_failure_does_not_stop_the_rest(
    tmp_path: Path,
) -> None:
    good, blocked = release(tmp_path, "A"), release(tmp_path, "B")
    folder = tmp_path / "dl"
    (folder / "B").mkdir(parents=True)
    (folder / "B" / "film.mkv").write_bytes(b"mine")
    items = [
        PlanItem(candidate(blocked, folder), 0.2),
        PlanItem(PlanCandidate("x" * 40, "broken", 1, 1, 1, folder, 1), 0.1),
        PlanItem(candidate(good, folder), 0.3),
    ]
    torrents = {read_torrent(good).infohash: good, read_torrent(blocked).infohash: blocked}

    def fetch(c: PlanCandidate) -> bytes:
        if c.infohash not in torrents:
            raise OSError("HTTP 404")
        return torrents[c.infohash]

    report = send_plan(Plan(items, 0.6), FakeQbit(), fetch)

    assert report.added == ["A"]
    assert [t for t, _ in report.refused] == ["B"]
    assert report.failed == [("broken", "HTTP 404")]
