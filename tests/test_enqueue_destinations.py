import threading
from types import SimpleNamespace

import pytest

from torrentlinker.agent.desktop import DesktopSetup
from torrentlinker.config import Settings
from torrentlinker.download_queue import entries
from torrentlinker.downloads import DownloadFolders, IndexerCategory
from torrentlinker.store import CatalogueRow, Store
from torrentlinker.web.operations import DownloadFolderRequired, JobRequest, Operations


@pytest.fixture
def operations(tmp_path):
    films, games, fallback = [tmp_path / name for name in ("films", "games", "fallback")]
    for folder in (films, games, fallback):
        folder.mkdir()
    settings = Settings()
    settings.indexer_categories = {
        2000: IndexerCategory("Films"),
        2030: IndexerCategory("Film", 2000),
        4050: IndexerCategory("Games"),
    }
    settings.download_folders = DownloadFolders({2000: str(films), 4050: str(games)})
    settings.ensure_profiles()
    setup = DesktopSetup(settings, tmp_path / "settings.json", Store(tmp_path / "state.db"))
    setup._indexer = SimpleNamespace(
        url="https://indexer.test", redact=lambda value: value, unredact=lambda value: value
    )
    setup.store.save_catalogue(
        [
            CatalogueRow(h * 40, title, 4, 1, category, "https://indexer.test/" + h, "", 1)
            for h, title, category in [("a", "Film", 2030), ("b", "Game", 4050)]
        ]
    )
    return Operations(setup)


@pytest.mark.parametrize("default", [False, True])
def test_mixed_batch_uses_each_category_folder_even_with_a_default(operations, tmp_path, default):
    folders = operations.setup.settings.download_folders
    if default:
        folders.default = str(tmp_path / "fallback")
        operations.setup.settings.capture_client()
    request = JobRequest(kind="enqueue", hashes=["a" * 40, "b" * 40])
    operations.validate(request)
    result = operations.run(request, threading.Event(), lambda _: None)
    assert result["queued"] == 2
    assert {e.candidate.infohash: e.folder for e in entries(operations.setup.store)} == {
        "a" * 40: tmp_path / "films",
        "b" * 40: tmp_path / "games",
    }
    assert {e.candidate.categories for e in entries(operations.setup.store)} == {(2030,), (4050,)}


def test_mixed_batch_requests_only_the_missing_category_before_queueing_anything(operations):
    folders = operations.setup.settings.download_folders
    del folders.by_category[4050]
    request = JobRequest(kind="enqueue", hashes=["a" * 40, "b" * 40])
    for action in (
        lambda: operations.validate(request),
        lambda: operations.run(request, threading.Event(), lambda _: None),
    ):
        with pytest.raises(DownloadFolderRequired) as error:
            action()
        assert error.value.category == 4050
        assert entries(operations.setup.store) == []
        assert folders.default == ""


def test_unknown_category_does_not_offer_to_configure_a_global_default(operations):
    operations.setup.store.save_catalogue(
        [CatalogueRow("c" * 40, "Unknown", 4, 1, None, "https://indexer.test/c", "", 1)]
    )
    with pytest.raises(ValueError, match="category") as error:
        operations.validate(JobRequest(kind="enqueue", hashes=["c" * 40]))
    assert not isinstance(error.value, DownloadFolderRequired)


@pytest.mark.parametrize("shared_disk", [False, True])
@pytest.mark.parametrize("game_free", [4, 3])
def test_batch_storage_checks_each_disk_and_combines_shared_destinations(
    operations, tmp_path, monkeypatch, shared_disk, game_free
):
    from torrentlinker.agent import budgets
    from torrentlinker.agent.access import Access, Grant

    access = Access(tmp_path)
    grant = Grant(name="Test", clients=["default"], reserve_bytes=0)
    operations.setup.settings.free_space_margin = 0
    monkeypatch.setattr(budgets, "outstanding", lambda *args: 0)
    monkeypatch.setattr(budgets, "disk_of", lambda folder: "one" if shared_disk else folder.name)
    monkeypatch.setattr(
        budgets.shutil,
        "disk_usage",
        lambda folder: SimpleNamespace(total=100, free=game_free if folder.name == "games" else 4),
    )
    request = JobRequest(kind="enqueue", hashes=["a" * 40, "b" * 40])
    try:
        if shared_disk or game_free < 4:
            with pytest.raises(ValueError, match="reserve"):
                budgets.reserve(access, "proposal", "actor", grant, operations, request)
        else:
            assert budgets.reserve(access, "proposal", "actor", grant, operations, request) == {
                "a" * 40: 4,
                "b" * 40: 4,
            }
    finally:
        access.db.close()
