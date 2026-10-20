from pathlib import Path

from torrentlinker.domain import LocalItem
from torrentlinker.matching import match

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


def test_torrent_file_without_local_counterpart_is_no_full_match() -> None:
    item = LocalItem(Path("/lib/Show"), {"Show/e01.mkv": 100})

    assert match(item, {"Show/e01.mkv": 100, "Show/e02.mkv": 200}) is None


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
