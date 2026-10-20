from pathlib import Path

from tests.fake_qbit import FakeQbit
from tests.torrents import make_torrent
from torrentlinker.domain import LocalItem
from torrentlinker.matching import match
from torrentlinker.reseed import TAG, VERIFYING, Outcome, check_verifications, start_reseed
from torrentlinker.store import Store
from torrentlinker.torrent_meta import read_torrent


def ebook(tmp_path: Path) -> tuple[LocalItem, bytes]:
    lib = tmp_path / "E-Book"
    lib.mkdir()
    f = lib / "Le joueur d'echecs - Stefan Zweig.epub"
    f.write_bytes(b"z" * 67163)
    return LocalItem(f, {f.name: 67163}), make_torrent(f)


def test_reseed_adds_the_torrent_stopped_at_the_item_location_and_forces_a_check(
    tmp_path: Path,
) -> None:
    item, data = ebook(tmp_path)
    meta = read_torrent(data)
    qbit, store = FakeQbit(), Store(tmp_path / "s.db")

    h = start_reseed(qbit, store, item, meta, match(item, meta.files))  # type: ignore[arg-type]

    t = qbit.torrent(h)
    assert t is not None
    assert t.save_path == item.save_path
    assert {TAG, VERIFYING} <= t.tags
    assert qbit.rechecked == [h]
    assert qbit.started == []


def test_torrent_is_started_once_verification_reaches_100_percent(tmp_path: Path) -> None:
    item, data = ebook(tmp_path)
    meta = read_torrent(data)
    qbit, store = FakeQbit(), Store(tmp_path / "s.db")
    h = start_reseed(qbit, store, item, meta, match(item, meta.files))  # type: ignore[arg-type]

    assert check_verifications(qbit, store) == {}  # still checking

    qbit.finish_check(h, 1.0)
    outcomes = check_verifications(qbit, store)

    assert outcomes == {item.path: Outcome(h, verified=True, progress=1.0)}
    assert qbit.started == [h]
    assert VERIFYING not in qbit.by_hash[h].tags


def test_failed_verification_removes_the_torrent_keeps_data_and_records_a_rejection(
    tmp_path: Path,
) -> None:
    item, data = ebook(tmp_path)
    meta = read_torrent(data)
    qbit, store = FakeQbit(), Store(tmp_path / "s.db")
    h = start_reseed(qbit, store, item, meta, match(item, meta.files))  # type: ignore[arg-type]
    qbit.finish_check(h, 0.973)

    outcomes = check_verifications(qbit, store, now=lambda: 1e12)

    assert outcomes == {item.path: Outcome(h, verified=False, progress=0.973)}
    assert qbit.removed == [(h, False)]
    assert item.path.read_bytes() == b"z" * 67163
    assert store.rejections(item.path) == {meta.infohash: "Verification failed at 97.3%"}


def test_a_stopped_torrent_right_after_the_recheck_request_is_not_judged_yet(
    tmp_path: Path,
) -> None:
    item, data = ebook(tmp_path)
    meta = read_torrent(data)
    qbit, store = FakeQbit(), Store(tmp_path / "s.db")
    h = start_reseed(qbit, store, item, meta, match(item, meta.files))  # type: ignore[arg-type]
    qbit.finish_check(h, 0.0)  # e.g. qBittorrent has not picked the recheck up yet

    assert check_verifications(qbit, store) == {}
    assert h in qbit.by_hash


def test_reseeding_a_torrent_already_in_qbittorrent_is_refused(tmp_path: Path) -> None:
    import pytest

    from torrentlinker.reseed import AlreadyInClient

    item, data = ebook(tmp_path)
    meta = read_torrent(data)
    qbit, store = FakeQbit(), Store(tmp_path / "s.db")
    start_reseed(qbit, store, item, meta, match(item, meta.files))  # type: ignore[arg-type]

    with pytest.raises(AlreadyInClient):
        start_reseed(qbit, store, item, meta, match(item, meta.files))  # type: ignore[arg-type]
