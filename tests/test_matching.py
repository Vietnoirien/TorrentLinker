from pathlib import Path

from torrentlinker.domain import LocalItem
from torrentlinker.matching import compare, match

EBOOK_LOCAL = "Le joueur d'echecs - Stefan Zweig.epub"
EBOOK = LocalItem(Path("/windocs/E-Book") / EBOOK_LOCAL, {EBOOK_LOCAL: 67163})
EBOOK_TORRENT = "Le.Joueur.D'echecs.Stefan.Zweig.2013.FR.[EPUB]-NOTAG.epub"


def test_identical_layout_is_a_full_match_without_renames() -> None:
    item = LocalItem(Path("/lib/Show"), {"Show/e01.mkv": 100, "Show/e02.mkv": 200})

    m = match(item, {"Show/e01.mkv": 100, "Show/e02.mkv": 200})

    assert m is not None and m.is_full
    assert m.renames == {}


def test_renamed_file_of_same_size_is_a_full_match_with_a_rename() -> None:
    m = match(EBOOK, {EBOOK_TORRENT: 67163})

    assert m is not None and m.is_full
    assert m.renames == {EBOOK_TORRENT: EBOOK_LOCAL}


def test_files_of_equal_size_are_paired_by_name() -> None:
    item = LocalItem(Path("/lib/MyShow"), {"MyShow/E02.mkv": 100, "MyShow/E01.mkv": 100})

    m = match(item, {"Show.S01/e01.mkv": 100, "Show.S01/e02.mkv": 100})

    assert m is not None
    assert m.pairs == {"Show.S01/e01.mkv": "MyShow/E01.mkv", "Show.S01/e02.mkv": "MyShow/E02.mkv"}


def test_torrent_file_without_local_counterpart_makes_a_partial_match() -> None:
    item = LocalItem(Path("/lib/Show"), {"Show/e01.mkv": 800})

    m = match(item, {"Show/e01.mkv": 800, "Show/e02.mkv": 200})

    assert m is not None and not m.is_full
    assert m.absent == ("Show/e02.mkv",)
    assert m.coverage == 0.8


def test_partial_match_below_minimum_coverage_is_no_match() -> None:
    item = LocalItem(Path("/lib/Show"), {"Show/e01.srt": 10})

    assert match(item, {"Show/e01.srt": 10, "Show/e01.mkv": 990}) is None


def test_ignored_torrent_file_absent_locally_still_gives_a_full_match() -> None:
    from torrentlinker.matching import IgnoreList, MatchRules

    item = LocalItem(Path("/lib/Movie"), {"Movie/movie.mkv": 100})
    files = {"Movie/movie.mkv": 100, "Movie/movie.nfo": 2, "Movie/Sample/s.mkv": 5}

    m = match(item, files, MatchRules(ignore=IgnoreList.default()))

    assert m is not None and m.is_full
    assert set(m.skipped) == {"Movie/movie.nfo", "Movie/Sample/s.mkv"}


def test_extra_local_files_do_not_prevent_a_full_match() -> None:
    item = LocalItem(Path("/lib/Movie"), {"Movie/movie.mkv": 100, "Movie/notes.txt": 3})

    m = match(item, {"Movie/movie.mkv": 100})

    assert m is not None and m.is_full


def test_candidate_size_within_tolerance_is_plausible() -> None:
    from torrentlinker.matching import is_plausible

    assert is_plausible(67163, EBOOK, tolerance=0.0)
    assert is_plausible(1020, LocalItem(Path("/x"), {"x": 1000}), tolerance=0.02)
    assert not is_plausible(1021, LocalItem(Path("/x"), {"x": 1000}), tolerance=0.02)
    assert not is_plausible(9000000, EBOOK, tolerance=0.02)


def test_same_size_files_are_paired_within_the_same_folder() -> None:
    # Two scales of one model: same triangles, so same sizes, in different folders.
    sizes = {"head.stl": 1084, "bike1-3.stl": 5084}
    torrent = {
        f"CA3D.Kaneda[STL]/{scale} scale/{name}": size
        for scale in ("1-6", "1-9", "1-12")
        for name, size in sizes.items()
    }
    item = LocalItem(
        Path("/lib/CA3D Studios - Kaneda - Akira"),
        {
            f"CA3D Studios - Kaneda - Akira/{scale} scale/{name}": size
            for scale in ("1-12", "1-9", "1-6")  # another order on disk
            for name, size in sizes.items()
        },
    )

    pairs = compare(item, torrent).pairs

    for t_path, local in pairs.items():
        assert t_path.split("/")[1] == local.split("/")[1], (t_path, local)
