from pathlib import Path

from torrentlinker.config import Settings
from torrentlinker.domain import ContentKind, LibraryFolder, PathMapping


def test_settings_survive_a_save_and_load(tmp_path: Path) -> None:
    s = Settings()
    s.library_folders = [
        LibraryFolder(Path("/lib/films"), 2, ContentKind.MOVIE, PathMapping("/lib/films", "/data"))
    ]
    s.kind_categories = {ContentKind.MOVIE: [2000, 2030]}
    s.matching.ignore_patterns = ["*.nfo"]
    s.save(tmp_path / "settings.json")

    loaded = Settings.load(tmp_path / "settings.json")

    assert loaded.library_folders == s.library_folders
    assert loaded.categories(ContentKind.MOVIE) == (2000, 2030)
    assert loaded.matching.ignore_patterns == ["*.nfo"]


def test_zen_profile_survives_a_save_and_load(tmp_path: Path) -> None:
    from torrentlinker.zen import ZenClass, ZenProfile

    s = Settings()
    s.zen = ZenProfile(ZenClass.SWARM_KEEPER, tree_bonus=0.03, seed_hours=18, torrent_cap=400)
    s.save(tmp_path / "settings.json")

    assert Settings.load(tmp_path / "settings.json").zen == s.zen


def test_download_folders_and_indexer_categories_survive_a_save_and_load(tmp_path: Path) -> None:
    from torrentlinker.downloads import DownloadFolders, IndexerCategory

    s = Settings()
    s.indexer_categories = {2000: IndexerCategory("Films"), 2030: IndexerCategory("VO", 2000)}
    s.download_folders = DownloadFolders({2030: "/dl/vo"}, "/dl")
    s.save(tmp_path / "settings.json")

    loaded = Settings.load(tmp_path / "settings.json")

    assert loaded.indexer_categories == s.indexer_categories
    assert loaded.download_folders == s.download_folders


def test_qbittorrent_api_keys_are_recognised() -> None:
    from torrentlinker.qbit import is_api_key

    assert is_api_key("qbt_" + "aB3" * 9 + "x")
    assert not is_api_key("qbt_short")
    assert not is_api_key("password")
