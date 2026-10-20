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


def test_torrent_files_are_renamed_to_the_local_names_before_verification(
    tmp_path: Path,
) -> None:
    item, _ = ebook(tmp_path)
    scene = tmp_path / "scene" / "Le.Joueur.D'echecs.Stefan.Zweig.2013.FR.[EPUB]-NOTAG.epub"
    scene.parent.mkdir()
    scene.write_bytes(b"z" * 67163)
    meta = read_torrent(make_torrent(scene))
    qbit, store = FakeQbit(), Store(tmp_path / "s.db")

    h = start_reseed(qbit, store, item, meta, match(item, meta.files))  # type: ignore[arg-type]

    assert qbit.by_hash[h].files == {item.path.name: 67163}
    assert qbit.calls == [f"rename {scene.name} -> {item.path.name}", "recheck"]


def test_root_folder_and_layout_differences_are_renamed_file_by_file(tmp_path: Path) -> None:
    src = tmp_path / "scene" / "Show.S01"
    (src / "Subs").mkdir(parents=True)
    (src / "Show.S01E01.mkv").write_bytes(b"a" * 1000)
    (src / "Subs" / "Show.S01E01.srt").write_bytes(b"b" * 10)
    meta = read_torrent(make_torrent(src))
    item = LocalItem(tmp_path / "lib" / "My Show", {"My Show/E01.mkv": 1000, "My Show/E01.srt": 10})
    qbit, store = FakeQbit(), Store(tmp_path / "s.db")

    h = start_reseed(qbit, store, item, meta, match(item, meta.files))  # type: ignore[arg-type]

    assert qbit.by_hash[h].files == {"My Show/E01.mkv": 1000, "My Show/E01.srt": 10}


def test_swapped_names_are_renamed_without_collisions(tmp_path: Path) -> None:
    from torrentlinker.matching import Match
    from torrentlinker.reseed import rename_plan

    m = Match({"S/a.mkv": "S/b.mkv", "S/b.mkv": "S/a.mkv"})
    files = {"S/a.mkv": 1, "S/b.mkv": 2}
    for old, new in rename_plan(m, set(files)):
        assert new not in files, f"{new} would overwrite another file"
        files[new] = files.pop(old)

    assert files == {"S/b.mkv": 1, "S/a.mkv": 2}


def partial_pack(tmp_path: Path) -> tuple[LocalItem, bytes]:
    # torf uses 16 KiB pieces here: episode 2 starts inside piece 1.
    src = tmp_path / "scene" / "Show"
    src.mkdir(parents=True)
    (src / "e1.mkv").write_bytes(b"a" * 20000)
    (src / "e2.mkv").write_bytes(b"b" * 20000)
    data = make_torrent(src)
    item = LocalItem(tmp_path / "lib" / "Show", {"Show/e1.mkv": 20000})
    return item, data


def test_partial_match_files_missing_locally_are_never_downloaded(tmp_path: Path) -> None:
    item, data = partial_pack(tmp_path)
    meta = read_torrent(data)
    qbit, store = FakeQbit(), Store(tmp_path / "s.db")

    h = start_reseed(qbit, store, item, meta, match(item, meta.files))  # type: ignore[arg-type]

    assert qbit.priorities[h] == {1: 0}
    assert qbit.calls.index("priority [1] = 0") < qbit.calls.index("recheck")


def test_partial_match_verifies_when_only_boundary_pieces_are_incomplete(tmp_path: Path) -> None:
    item, data = partial_pack(tmp_path)
    meta = read_torrent(data)
    m = match(item, meta.files)
    assert m is not None
    qbit, store = FakeQbit(), Store(tmp_path / "s.db")
    h = start_reseed(qbit, store, item, meta, m)

    # Piece 1 spans e1 (bytes 16384..20000) and e2: those 3616 bytes of e1 cannot verify.
    qbit.finish_check(h, 1 - 3616 / 20000)
    assert check_verifications(qbit, store, now=lambda: 1e12)[item.path].verified


def test_partial_match_below_the_expected_progress_fails(tmp_path: Path) -> None:
    item, data = partial_pack(tmp_path)
    meta = read_torrent(data)
    qbit, store = FakeQbit(), Store(tmp_path / "s.db")
    h = start_reseed(qbit, store, item, meta, match(item, meta.files))  # type: ignore[arg-type]

    qbit.finish_check(h, 0.5)
    assert not check_verifications(qbit, store, now=lambda: 1e12)[item.path].verified


def test_verification_started_before_a_restart_is_settled_after_it(tmp_path: Path) -> None:
    item, data = ebook(tmp_path)
    meta = read_torrent(data)
    qbit = FakeQbit()
    h = start_reseed(qbit, Store(tmp_path / "s.db"), item, meta, match(item, meta.files))  # type: ignore[arg-type]
    qbit.finish_check(h, 1.0)

    outcomes = check_verifications(qbit, Store(tmp_path / "s.db"))  # app relaunched

    assert outcomes[item.path].verified
    assert qbit.started == [h]


def test_reseed_interrupted_before_its_check_is_undone_without_a_rejection(
    tmp_path: Path,
) -> None:
    item, data = ebook(tmp_path)
    qbit = FakeQbit()
    h = qbit.add(data, str(item.save_path), [TAG, VERIFYING])  # crashed right after the add
    store = Store(tmp_path / "s.db")

    assert check_verifications(qbit, store) == {}
    assert qbit.removed == [(h, False)]
    assert item.path.exists()
    assert store.rejections(item.path) == {}
