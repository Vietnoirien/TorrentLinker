from pathlib import Path

from torrentlinker.domain import ItemState, LocalItem, Torrent
from torrentlinker.reconcile import classify

LIB = Path("/lib")

movie = LocalItem(LIB / "Movie.mkv", {"Movie.mkv": 10})
show = LocalItem(LIB / "Show", {"Show/e01.mkv": 1, "Show/e02.mkv": 2})


def test_item_covered_by_a_torrent_is_seeded_and_others_are_orphans() -> None:
    torrents = [Torrent("h1", "Movie.mkv", LIB, {"Movie.mkv": 10})]

    states = classify([movie, show], torrents)

    assert states == {movie.path: ItemState.SEEDED, show.path: ItemState.ORPHAN}


def test_item_with_only_some_files_in_torrents_is_partially_seeded() -> None:
    torrents = [Torrent("h1", "Show", LIB, {"Show/e01.mkv": 1})]

    assert classify([show], torrents) == {show.path: ItemState.PARTIALLY_SEEDED}


def test_files_of_one_item_spread_over_several_torrents_count_as_seeded() -> None:
    torrents = [
        Torrent("h1", "e01.mkv", LIB / "Show", {"e01.mkv": 1}),
        Torrent("h2", "e02.mkv", LIB / "Show", {"e02.mkv": 2}),
    ]

    assert classify([show], torrents) == {show.path: ItemState.SEEDED}


def test_local_ignored_files_do_not_make_an_item_partially_seeded() -> None:
    from torrentlinker.matching import IgnoreList

    movie_dir = LocalItem(LIB / "Movie", {"Movie/movie.mkv": 10, "Movie/Thumbs.db": 1})
    torrents = [Torrent("h1", "Movie", LIB, {"Movie/movie.mkv": 10})]

    states = classify([movie_dir], torrents, IgnoreList.default())

    assert states == {movie_dir.path: ItemState.SEEDED}
