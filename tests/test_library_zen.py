from dataclasses import replace

from PySide6.QtCore import Qt

from torrentlinker.config import Settings
from torrentlinker.domain import LibraryFolder, Torrent
from torrentlinker.gui.main_window import MainWindow
from torrentlinker.library import build_library
from torrentlinker.seeding import seeding
from torrentlinker.store import Store
from torrentlinker.zen import GB


def test_seeded_library_item_displays_the_same_estimate_as_zen(qtbot, tmp_path):
    settings = Settings()
    window = MainWindow(settings, tmp_path / "settings.json", Store(tmp_path / "s.db"))
    qtbot.addWidget(window)
    folder = tmp_path / "library"
    folder.mkdir()
    (folder / "film.mkv").write_bytes(b"film")
    torrent = Torrent(
        "a",
        "A different release name",
        folder,
        {"film.mkv": 4},
        state="uploading",
        tracker="https://c411.org/announce",
        size=GB,
        swarm_seeders=5,
    )
    entries = build_library([LibraryFolder(folder)], [torrent])
    view = seeding(settings.zen, [replace(torrent, files={})], settings.indexer.url)
    # Startup can finish the Zen refresh before the Library scan.
    window.zen_tab.seeding_view.updated.emit(view)
    window.library_model.set_entries(entries)
    index = window.library_model.index(0, window.library_model.ZEN_COLUMN)
    assert index.data(Qt.ItemDataRole.DisplayRole) == f"≈ {view.rows[0].zen:.2f}"


def test_linked_torrents_are_deduplicated_and_partial_items_get_current_estimates(tmp_path):
    from torrentlinker.domain import ItemState
    from torrentlinker.gui.library_model import LibraryModel
    from torrentlinker.matching import IgnoreList
    from torrentlinker.zen import ZenProfile

    folder = tmp_path / "library"
    item = folder / "pack"
    item.mkdir(parents=True)
    for name in ("one.epub", "two.epub", "missing.epub", "cover.jpg"):
        (item / name).write_bytes(b"book")
    torrents = [
        Torrent(
            "A",
            "Renamed pack",
            folder,
            {"pack/one.epub": 4, "pack/two.epub": 4},
            state="uploading",
            tracker="https://c411.org/announce",
            size=GB,
        ),
        Torrent(
            "b",
            "Cover",
            folder,
            {"pack/cover.jpg": 4},
            state="uploading",
            tracker="https://c411.org/announce",
            size=GB,
        ),
        Torrent(
            "c",
            "Unrelated pack",
            tmp_path / "elsewhere",
            {"pack/one.epub": 4},
            state="uploading",
            tracker="https://c411.org/announce",
            size=GB,
        ),
    ]
    entries = build_library([LibraryFolder(folder)], torrents, IgnoreList(("*.jpg",)))
    assert entries[0].state is ItemState.PARTIALLY_SEEDED
    assert entries[0].torrent_hashes == frozenset({"a"})
    model = LibraryModel()
    model.set_entries(entries)
    assert model.zen_of(entries[0]) is None
    view = seeding(ZenProfile(), torrents, "https://c411.org/api/torznab")
    model.set_seeding(view)
    assert model.zen_of(entries[0]) == view.rows[0].zen


def test_seeded_zen_refresh_updates_sorting_and_distinguishes_zero_from_unknown(qtbot, tmp_path):
    from torrentlinker.domain import ItemState, LocalItem
    from torrentlinker.gui.library_model import LibraryFilter, LibraryModel
    from torrentlinker.library import LibraryEntry
    from torrentlinker.seeding import Seeding, SeedingRow
    from torrentlinker.zen import ZenProfile

    model = LibraryModel()
    folder = LibraryFolder(tmp_path)
    first = LibraryEntry(folder, LocalItem(tmp_path / "a"), ItemState.SEEDED, frozenset({"a", "b"}))
    second = LibraryEntry(folder, LocalItem(tmp_path / "b"), ItemState.SEEDED, frozenset({"b"}))
    model.set_entries([first, second])
    a = Torrent("a", "a", tmp_path)
    b = Torrent("b", "b", tmp_path)
    day = seeding(ZenProfile(), [], "https://c411.org/api/torznab").day
    view = Seeding([SeedingRow(a, 2.0), SeedingRow(b, 1.0)], day, [])
    model.set_seeding(view)
    assert model.zen_of(first) == 3.0
    proxy = LibraryFilter()
    proxy.setSourceModel(model)
    proxy.sort(model.ZEN_COLUMN, Qt.SortOrder.DescendingOrder)
    assert proxy.index(0, 0).data(Qt.ItemDataRole.UserRole) is first
    # Paused is known zero; removed/missing from the snapshot is unknown.
    model.set_seeding(Seeding([SeedingRow(b, None)], day, []))
    assert model.zen_of(first) is None
    assert model.zen_of(second) == 0.0
    assert model.index(1, model.ZEN_COLUMN).data() == "≈ 0.00"
    assert proxy.index(0, 0).data(Qt.ItemDataRole.UserRole) is second
    model.set_seeding(None)
    assert model.zen_of(second) is None
