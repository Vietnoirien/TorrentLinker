from pathlib import Path

from torrentlinker.downloads import DownloadFolders, IndexerCategory

CATEGORIES = {
    2000: IndexerCategory("Films"),
    2030: IndexerCategory("Films étrangers", 2000),
    2040: IndexerCategory("Films HD", 2000),
    7000: IndexerCategory("Ebook"),
    7020: IndexerCategory("Ebook FR", 7000),
}


def test_a_subcategory_uses_its_own_folder_first() -> None:
    folders = DownloadFolders({2030: "/dl/etrangers", 2000: "/dl/films"}, "/dl")

    assert folders.resolve(2030, CATEGORIES) == Path("/dl/etrangers")


def test_a_subcategory_without_a_folder_falls_back_to_its_category_then_the_default() -> None:
    folders = DownloadFolders({2000: "/dl/films"}, "/dl")

    assert folders.resolve(2040, CATEGORIES) == Path("/dl/films")
    assert folders.resolve(7020, CATEGORIES) == Path("/dl")
    assert folders.resolve(9999, CATEGORIES) == Path("/dl")  # unknown to the caps


def test_categories_without_any_download_folder_are_excluded() -> None:
    folders = DownloadFolders({2000: "/dl/films"})

    assert folders.resolve(7020, CATEGORIES) is None
    assert folders.excluded(CATEGORIES) == [7000, 7020]
    assert DownloadFolders(default="/dl").excluded(CATEGORIES) == []
