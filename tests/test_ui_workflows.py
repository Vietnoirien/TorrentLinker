"""Interaction regressions: sorting must never change which item an action operates on."""

from pathlib import Path

from PySide6.QtCore import Qt

from torrentlinker.config import Settings
from torrentlinker.domain import ItemState, LibraryFolder, LocalItem
from torrentlinker.gui.main_window import MainWindow
from torrentlinker.indexer import Candidate
from torrentlinker.library import LibraryEntry
from torrentlinker.review import CheckedCandidate
from torrentlinker.store import Store


def test_sorted_candidates_keep_their_identity_for_replacement_and_rejection(qtbot, tmp_path):
    store = Store(tmp_path / "s.db")
    window = MainWindow(Settings(), tmp_path / "settings.json", store)
    qtbot.addWidget(window)
    panel = window.review
    entry = LibraryEntry(LibraryFolder(tmp_path), LocalItem(tmp_path / "Film"), ItemState.ORPHAN)
    panel.set_entry(entry)
    large = CheckedCandidate(Candidate("A large", 1024**3, "https://example.test/large", 20))
    small = CheckedCandidate(Candidate("Z small", 9 * 1024**2, "https://example.test/small", 3))
    panel._show(entry, [large, small])
    panel.candidates.sortItems(1, Qt.SortOrder.AscendingOrder)
    panel.candidates.selectRow(0)
    assert panel.selected() is small
    assert panel.selected_all() == [small]

    # Checking a Candidate can change both its displayed data and its sorted position.
    replacement = CheckedCandidate(
        Candidate("Z updated", 2 * 1024**3, small.candidate.download_url, 3)
    )
    panel._replace(entry, small, replacement)
    assert panel.selected() is replacement
    assert panel.candidates.currentRow() == 1
    panel.reject_button.click()
    assert list(store.rejections(entry.item.path)) == [small.candidate.download_url]
    assert panel.checked == [large]
    assert panel.candidates.rowCount() == 1
    assert panel.candidates.item(0, 0).text() == large.candidate.title


def test_library_search_combines_with_state_and_folder_filters(qtbot, tmp_path):
    window = MainWindow(Settings(), tmp_path / "settings.json", Store(tmp_path / "s.db"))
    qtbot.addWidget(window)
    folder = LibraryFolder(tmp_path)
    entries = [
        LibraryEntry(folder, LocalItem(tmp_path / "Amelie.mkv"), ItemState.ORPHAN),
        LibraryEntry(folder, LocalItem(tmp_path / "Amelie.2001.mkv"), ItemState.SEEDED),
        LibraryEntry(folder, LocalItem(tmp_path / "Other.mkv"), ItemState.ORPHAN),
    ]
    window.library_model.set_entries(entries)
    window.state_filter.setCurrentIndex(window.state_filter.findData(ItemState.ORPHAN))
    window.library_search.setText(" AMELIE ")
    assert window.library_proxy.rowCount() == 1
    assert window.library_proxy.index(0, 0).data() == "Amelie.mkv"
    window.library_search.clear()
    assert window.library_proxy.rowCount() == 2
    window.tabs.setCurrentIndex(2)
    assert window.navigation.currentRow() == 2
    window._focus_search()
    assert window.navigation.currentRow() == 1


def test_upload_sort_refresh_and_programmatic_selection_keep_the_right_item(qtbot, tmp_path):
    from tests.test_upload_view import model, tab

    view, _, _ = tab(qtbot, tmp_path)
    large, small = model(tmp_path, "A large.3mf"), model(tmp_path, "Z small.3mf")
    # Distinct byte sizes must sort numerically despite their formatted units.
    large = LibraryEntry(large.folder, LocalItem(large.item.path, {"a": 1024**3}), large.state)
    small = LibraryEntry(small.folder, LocalItem(small.item.path, {"b": 9 * 1024**2}), small.state)
    view.set_entries([large, small])
    view.show_all.setChecked(True)
    view.items.sortItems(2, Qt.SortOrder.AscendingOrder)
    view.items.selectRow(0)
    assert view.entry is small
    view._fill()
    assert view.entry is small
    assert view.items.item(0, 0).text() == small.item.path.name
    view.select(large.item.path)
    assert view.entry is large
    assert view.items.currentRow() == 1
    view._show_drafts([{"name": "Z last"}, {"name": "A first"}])
    view.drafts.sortItems(0, Qt.SortOrder.AscendingOrder)
    view._show_drafts(
        [{"name": "Z last", "category": "Models"}, {"name": "A first", "category": "Books"}]
    )
    assert view.drafts.item(0, 0).text() == "A first"
    assert view.drafts.item(0, 1).text() == "Books"


def test_seeding_filter_and_numeric_order_survive_refresh(qtbot):
    from torrentlinker.domain import Torrent
    from torrentlinker.gui.zen_view import SeedingView
    from torrentlinker.seeding import Seeding, SeedingRow
    from torrentlinker.zen import ZenDay

    view = SeedingView(lambda: lambda: Seeding([], ZenDay(), []))
    qtbot.addWidget(view)
    rows = [
        SeedingRow(Torrent("a", "Small film", Path("/data"), size=1024**2), 0.1),
        SeedingRow(Torrent("b", "Large film", Path("/data"), size=1024**3), 0.2),
    ]
    seeding = Seeding(rows, ZenDay([0.1, 0.2]), [])
    view.show_seeding(seeding)
    view.table.sortItems(1, Qt.SortOrder.AscendingOrder)
    view.search.setText(" LARGE ")
    view.show_seeding(seeding)
    assert view.table.topLevelItem(0).child(0).text(0) == "Small film"
    assert view.table.torrents["a"].isHidden()
    assert not view.table.torrents["b"].isHidden()
    view.search.clear()
    assert not view.table.torrents["a"].isHidden()
