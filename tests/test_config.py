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
