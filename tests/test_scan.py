from pathlib import Path

from torrentlinker.domain import LibraryFolder
from torrentlinker.scan import scan


def write(path: Path, size: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)


def test_each_top_level_entry_is_a_local_item(tmp_path: Path) -> None:
    write(tmp_path / "Movie.2020.mkv", 10)
    write(tmp_path / "Show.S01" / "e01.mkv", 20)
    write(tmp_path / "Show.S01" / "subs" / "e01.srt", 3)

    items = scan(LibraryFolder(tmp_path, depth=1))

    by_name = {i.path.name: i for i in items}
    assert set(by_name) == {"Movie.2020.mkv", "Show.S01"}
    assert by_name["Movie.2020.mkv"].files == {"Movie.2020.mkv": 10}
    assert by_name["Show.S01"].files == {"Show.S01/e01.mkv": 20, "Show.S01/subs/e01.srt": 3}
    assert by_name["Show.S01"].size == 23


def test_depth_two_lists_entries_inside_each_subfolder(tmp_path: Path) -> None:
    write(tmp_path / "Show" / "Season 1" / "e01.mkv", 5)
    write(tmp_path / "Show" / "Season 2" / "e01.mkv", 6)
    write(tmp_path / "Loose.File.mkv", 7)

    items = scan(LibraryFolder(tmp_path, depth=2))

    assert sorted(i.path.relative_to(tmp_path).as_posix() for i in items) == [
        "Loose.File.mkv",
        "Show/Season 1",
        "Show/Season 2",
    ]
    season1 = next(i for i in items if i.path.name == "Season 1")
    assert season1.files == {"Season 1/e01.mkv": 5}
