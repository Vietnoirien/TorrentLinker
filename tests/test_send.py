import threading
from pathlib import Path

import pytest

from tests.fake_qbit import FakeQbit
from tests.torrents import make_torrent
from torrentlinker.indexer import KeyRefused, RateLimited
from torrentlinker.plan import Plan, PlanCandidate, PlanItem
from torrentlinker.send import ZEN_TAG, Refused, SendProgress, send_one, send_plan
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


def two_releases(tmp_path: Path) -> tuple[Plan, dict[str, bytes]]:
    a, b = release(tmp_path, "A"), release(tmp_path, "B")
    folder = tmp_path / "dl"
    plan = Plan([PlanItem(candidate(a, folder), 0.1), PlanItem(candidate(b, folder), 0.1)], 0.2)
    return plan, {read_torrent(a).infohash: a, read_torrent(b).infohash: b}


def test_progress_is_reported_for_each_torrent_and_at_the_end(tmp_path: Path) -> None:
    plan, data = two_releases(tmp_path)
    seen: list[SendProgress] = []

    send_plan(plan, FakeQbit(), lambda c: data[c.infohash], on_progress=seen.append)

    assert [(p.done, p.total, p.title) for p in seen] == [(0, 2, "A"), (1, 2, "B"), (2, 2, "")]
    assert seen[-1].added == 2


def test_when_the_indexer_limits_downloads_the_same_torrent_is_tried_again_later(
    tmp_path: Path,
) -> None:
    plan, data = two_releases(tmp_path)
    limits = [RateLimited(5), RateLimited(5)]
    waits: list[float] = []
    seen: list[SendProgress] = []

    def fetch(c: PlanCandidate) -> bytes:
        if limits:
            raise limits.pop(0)
        return data[c.infohash]

    def wait(seconds: float) -> bool:
        waits.append(seconds)
        return False

    report = send_plan(
        plan, FakeQbit(), fetch, on_progress=seen.append, wait=wait, now=lambda: 1000.0
    )

    assert report.added == ["A", "B"] and report.failed == []
    assert waits == [60, 120]  # longer each time, never shorter than a minute
    assert [p.retry_at for p in seen if p.retry_at] == [1060, 1120]


def test_stopping_during_a_wait_ends_sending_and_says_so(tmp_path: Path) -> None:
    plan, _data = two_releases(tmp_path)

    def fetch(c: PlanCandidate) -> bytes:
        raise RateLimited(900)

    report = send_plan(plan, FakeQbit(), fetch, wait=lambda seconds: True)

    assert report.stopped
    assert report.handled == 0 and report.failed == []


def test_stopping_ends_sending_before_the_next_torrent(tmp_path: Path) -> None:
    plan, data = two_releases(tmp_path)
    stop = threading.Event()

    def fetch(c: PlanCandidate) -> bytes:
        stop.set()  # the user stops while the first torrent is being sent
        return data[c.infohash]

    report = send_plan(plan, FakeQbit(), fetch, stop=stop)

    assert report.added == ["A"]
    assert report.stopped


def test_a_refused_key_stops_sending_instead_of_failing_every_torrent(tmp_path: Path) -> None:
    plan, _data = two_releases(tmp_path)
    fetched: list[str] = []

    def fetch(c: PlanCandidate) -> bytes:
        fetched.append(c.title)
        raise KeyRefused(401)

    report = send_plan(plan, FakeQbit(), fetch)

    assert fetched == ["A"]
    assert report.stopped
    assert [t for t, _ in report.failed] == ["A"]


def test_each_torrent_outcome_is_reported_so_it_can_be_saved(tmp_path: Path) -> None:
    plan, data = two_releases(tmp_path)
    (tmp_path / "dl" / "B").mkdir(parents=True)
    (tmp_path / "dl" / "B" / "film.mkv").write_bytes(b"mine")
    outcomes: list[tuple[str, str]] = []

    send_plan(
        plan,
        FakeQbit(),
        lambda c: data[c.infohash],
        on_outcome=lambda c, outcome, reason: outcomes.append((c.title, outcome)),
    )

    assert outcomes == [("A", "added"), ("B", "refused")]


def test_progress_counts_the_zen_per_day_of_what_was_sent(tmp_path: Path) -> None:
    plan, data = two_releases(tmp_path)
    seen: list[SendProgress] = []

    send_plan(plan, FakeQbit(), lambda c: data[c.infohash], on_progress=seen.append)

    assert [round(p.zen_added, 2) for p in seen] == [0.0, 0.1, 0.2]
