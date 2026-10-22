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


def test_only_orphans_are_searched_automatically() -> None:
    from torrentlinker.domain import LibraryFolder
    from torrentlinker.library import LibraryEntry, auto_searchable

    folder = LibraryFolder(LIB)
    entries = [
        LibraryEntry(folder, movie, ItemState.SEEDED),
        LibraryEntry(folder, show, ItemState.PARTIALLY_SEEDED),
        LibraryEntry(folder, LocalItem(LIB / "x"), ItemState.ORPHAN),
    ]

    assert [e.item.path.name for e in auto_searchable(entries)] == ["x"]


def test_only_indexer_torrents_make_items_seeded_and_only_their_files_are_read(
    tmp_path: Path,
) -> None:
    from tests.fake_qbit import FakeQbit
    from torrentlinker.library import indexer_contents
    from torrentlinker.store import CatalogueRow, Store

    url = "https://c411.org/api/torznab"
    book = LocalItem(LIB / "Book.epub", {"Book.epub": 5})
    music = LocalItem(LIB / "Album", {"Album/a.flac": 7})
    client = FakeQbit()
    client.by_hash = {
        "a" * 40: Torrent(
            "a" * 40, "Movie.mkv", LIB, {"Movie.mkv": 10}, tracker="https://tracker.c411.org/a"
        ),
        # Stopped, so no tracker yet: known from the Catalogue
        "b" * 40: Torrent("b" * 40, "Book.epub", LIB, {"Book.epub": 5}),
        "c" * 40: Torrent(
            "c" * 40, "Album", LIB, {"Album/a.flac": 7}, tracker="https://other.example/a"
        ),
        "d" * 40: Torrent(
            "d" * 40, "Show", LIB, dict(show.files), frozenset({"torrentlinker:zen"})
        ),
    }
    read: list[str] = []
    files = client.files
    client.files = lambda h: read.append(h) or files(h)  # type: ignore[method-assign]
    store = Store(tmp_path / "s.db")
    store.save_catalogue([CatalogueRow("b" * 40, "Book", 5, 1, 7000, "u", "d", 0)])

    torrents = indexer_contents(client, store, url)

    assert sorted(read) == ["a" * 40, "b" * 40, "d" * 40]  # never the other tracker's
    assert classify([movie, book, music, show], torrents) == {
        movie.path: ItemState.SEEDED,
        book.path: ItemState.SEEDED,
        music.path: ItemState.ORPHAN,  # seeded for another tracker: searched on c411
        show.path: ItemState.SEEDED,
    }
