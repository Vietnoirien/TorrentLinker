from pathlib import Path

from torrentlinker.domain import PathMapping, Torrent
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


# Detection ---------------------------------------------------------------------


def put(path: Path, size: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)


def qbit_torrent(h: str, save_path: str, files: dict[str, int]) -> Torrent:
    return Torrent(h * 40, next(iter(files)).split("/")[0], Path(save_path), files)


def test_detection_finds_a_docker_volume_from_qbittorrent_torrents(tmp_path: Path) -> None:
    from torrentlinker.paths import detect_mappings

    nas = tmp_path / "mnt" / "nas"
    put(nas / "torrents" / "ebooks" / "Zweig.epub", 300)
    put(nas / "torrents" / "films" / "Film" / "film.mkv", 900)
    torrents = [
        qbit_torrent("a", "/data/torrents/ebooks", {"Zweig.epub": 300}),
        qbit_torrent("b", "/data/torrents/ebooks", {"Other.epub": 200}),  # gone since
        qbit_torrent("c", "/data/torrents/films", {"Film/film.mkv": 900, "Film/a.nfo": 1}),
    ]

    # Only the ebooks are a Download Folder: the folders above it are looked at too.
    found = detect_mappings(torrents, [nas / "torrents" / "ebooks"])

    [suggestion] = found.suggestions
    assert suggestion.mapping == PathMapping(str(nas), "/data")
    assert suggestion.torrents == 3
    assert found.not_found == [] and found.same_paths == 0


def test_torrents_at_the_same_path_need_no_mapping(tmp_path: Path) -> None:
    from torrentlinker.paths import detect_mappings

    put(tmp_path / "dl" / "Zweig.epub", 300)
    torrents = [qbit_torrent("a", str(tmp_path / "dl"), {"Zweig.epub": 300})]

    found = detect_mappings(torrents, [tmp_path / "dl"])

    assert found.suggestions == [] and found.same_paths == 1


def test_a_file_of_another_size_is_not_the_torrent(tmp_path: Path) -> None:
    from torrentlinker.paths import detect_mappings

    put(tmp_path / "nas" / "ebooks" / "Zweig.epub", 299)
    torrents = [qbit_torrent("a", "/data/ebooks", {"Zweig.epub": 300})]

    found = detect_mappings(torrents, [tmp_path / "nas" / "ebooks"])

    assert found.suggestions == [] and found.not_found == ["/data/ebooks"]


def test_file_lists_are_read_for_a_few_torrents_of_each_path_only(tmp_path: Path) -> None:
    from torrentlinker.paths import TRIES_PER_PATH, detect_mappings

    torrents = [Torrent(f"{i:040x}", f"T{i}", Path("/data/x"), {}) for i in range(50)]
    asked: list[str] = []

    def files(t: Torrent) -> dict[str, int]:
        asked.append(t.hash)
        return {f"{t.name}.epub": 10}

    detect_mappings(torrents, [tmp_path], files)

    assert len(asked) == TRIES_PER_PATH


def test_a_windows_share_maps_to_qbittorrent_paths_on_the_nas() -> None:
    from torrentlinker.paths import _shortest

    assert _shortest("Z:\\torrents\\ebooks", "/data/torrents/ebooks") == PathMapping(
        "Z:\\", "/data"
    )
    # A mapping always keeps a folder on each side, never a bare "/".
    assert _shortest("/home/me/data", "/data") == PathMapping("/home/me/data", "/data")


# Checks ------------------------------------------------------------------------


def test_check_counts_the_torrents_each_mapping_leads_to(tmp_path: Path) -> None:
    from torrentlinker.paths import check_mappings

    (tmp_path / "nas" / "ebooks").mkdir(parents=True)
    good, stale = PathMapping(str(tmp_path / "nas"), "/data"), PathMapping("/x", "/media")
    torrents = [
        qbit_torrent("a", "/data/ebooks", {"a.epub": 1}),
        qbit_torrent("b", "/data/ebooks", {"b.epub": 1}),
        qbit_torrent("c", "/data/films", {"c.mkv": 1}),  # folder missing here
        qbit_torrent("d", "/media/music", {"d.flac": 1}),
        qbit_torrent("e", "/elsewhere", {"e.iso": 1}),
    ]

    checks = {c.mapping: c for c in check_mappings(torrents, [good, stale])}

    assert (checks[good].found, checks[good].total) == (2, 3)
    assert checks[good].missing == ["/data/films"]
    assert (checks[stale].found, checks[stale].total) == (0, 1)
    assert (checks[None].found, checks[None].total) == (0, 1)


def test_download_folders_qbittorrent_cannot_see_are_pointed_out(tmp_path: Path) -> None:
    from torrentlinker.paths import unreachable_download_folders

    covered, bare = Path("/mnt/nas/ebooks"), Path("/mnt/other/films")
    mappings = [PathMapping("/mnt/nas", "/data")]

    assert unreachable_download_folders([covered, bare], mappings, "/downloads") == [bare]
    # qBittorrent's own folder exists here: it shares this computer's paths.
    assert unreachable_download_folders([bare], [], str(tmp_path)) == []
