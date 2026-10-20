from torrentlinker.domain import PathMapping
from torrentlinker.paths import PathMapper

docker = PathMapper([PathMapping(local="/mnt/nas/media", qbit="/data")])
windows = PathMapper([PathMapping(local="\\\\nas\\media", qbit="/data/media")])


def test_local_path_under_a_mapping_is_translated_for_qbittorrent() -> None:
    assert docker.to_qbit("/mnt/nas/media/Films") == "/data/Films"
    assert docker.to_local("/data/Films/x.mkv") == "/mnt/nas/media/Films/x.mkv"


def test_paths_outside_every_mapping_are_unchanged() -> None:
    assert docker.to_qbit("/home/me/Films") == "/home/me/Films"
    assert docker.to_local("/downloads/x") == "/downloads/x"


def test_prefix_must_end_at_a_path_boundary() -> None:
    assert docker.to_qbit("/mnt/nas/media2/Films") == "/mnt/nas/media2/Films"


def test_windows_unc_path_maps_to_a_linux_qbittorrent() -> None:
    assert windows.to_qbit("\\\\nas\\media\\E-Book") == "/data/media/E-Book"
    assert windows.to_local("/data/media/E-Book") == "\\\\nas\\media\\E-Book"


def test_windows_comparison_ignores_case_and_separator_style() -> None:
    assert windows.to_qbit("\\\\NAS\\Media/E-Book") == "/data/media/E-Book"


def test_longest_matching_mapping_wins() -> None:
    m = PathMapper([PathMapping("/mnt/nas", "/data"), PathMapping("/mnt/nas/films", "/movies")])
    assert m.to_qbit("/mnt/nas/films/a") == "/movies/a"
    assert m.to_local("/movies/a") == "/mnt/nas/films/a"


def test_qbittorrent_behind_a_mapping_still_reports_items_as_seeded(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from pathlib import Path

    from tests.fake_qbit import FakeQbit
    from tests.torrents import make_torrent
    from torrentlinker.domain import ItemState, LocalItem
    from torrentlinker.paths import MappedQbit
    from torrentlinker.reconcile import classify

    f = tmp_path / "Movie.mkv"
    f.write_bytes(b"m" * 100)
    fake = FakeQbit()
    fake.add(make_torrent(f), "/data", ["x"])
    qbit = MappedQbit(fake, PathMapper([PathMapping(str(tmp_path), "/data")]))
    item = LocalItem(f, {"Movie.mkv": 100})

    assert classify([item], qbit.torrents()) == {item.path: ItemState.SEEDED}
    assert qbit.torrents()[0].save_path == Path(tmp_path)


def test_reseed_behind_a_mapping_gives_qbittorrent_its_own_path(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from tests.fake_qbit import FakeQbit
    from tests.torrents import make_torrent
    from torrentlinker.domain import LocalItem
    from torrentlinker.matching import match
    from torrentlinker.paths import MappedQbit
    from torrentlinker.reseed import start_reseed
    from torrentlinker.store import Store
    from torrentlinker.torrent_meta import read_torrent

    lib = tmp_path / "lib"
    lib.mkdir()
    f = lib / "Movie.mkv"
    f.write_bytes(b"m" * 100)
    meta = read_torrent(make_torrent(f))
    fake = FakeQbit()
    qbit = MappedQbit(fake, PathMapper([PathMapping(str(lib), "/data/films")]))
    item = LocalItem(f, {"Movie.mkv": 100})

    h = start_reseed(
        qbit,
        Store(tmp_path / "s.db"),
        item,
        meta,
        match(item, meta.files),
        meta.infohash,  # type: ignore[arg-type]
    )

    assert str(fake.by_hash[h].save_path) == "/data/films"
