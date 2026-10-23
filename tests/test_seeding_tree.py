from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHeaderView

from torrentlinker.domain import Torrent
from torrentlinker.downloads import IndexerCategory
from torrentlinker.gui.seeding_tree import SeedingTree
from torrentlinker.seeding import Seeding, SeedingRow
from torrentlinker.zen import ZenDay


def sample():
    rows = [
        SeedingRow(Torrent("a", "Small", Path("/data"), size=9 * 1024**2), 0.1, 7010),
        SeedingRow(Torrent("b", "Large", Path("/data"), size=1024**3), 0.2, 7010),
        SeedingRow(Torrent("c", "Broad", Path("/data"), size=100), 0.3, 7000, True),
        SeedingRow(Torrent("d", "Unknown", Path("/data"), size=100), None),
    ]
    return Seeding(
        rows,
        ZenDay([0.1, 0.2, 0.3]),
        [],
        {7000: IndexerCategory("Books"), 7010: IndexerCategory("Comics", 7000)},
    )


def test_tree_groups_actual_categories_and_totals_without_inventing_subcategories(qtbot):
    tree = SeedingTree()
    qtbot.addWidget(tree)
    tree.show_seeding(sample())
    assert tree.topLevelItemCount() == 2
    books, comics = tree.groups[(7000,)], tree.groups[(7000, 7010)]
    assert comics.parent() is books
    assert tree.torrents["a"].parent() is comics
    assert tree.torrents["c"].parent() is books
    assert tree.torrents["d"].parent() is tree.groups[()]
    assert books.text(0) == "Books (3)"
    assert books.text(4) == "≈ 0.60"
    assert "snapshot" in tree.torrents["c"].toolTip(0)
    tree.sortItems(1, Qt.SortOrder.AscendingOrder)
    assert comics.child(0).text(0) == "Small"
    assert comics.child(1).text(0) == "Large"


def test_refresh_keeps_selection_expansion_filter_sort_and_manual_widths(qtbot):
    tree = SeedingTree()
    qtbot.addWidget(tree)
    tree.show_seeding(sample())
    tree.setCurrentItem(tree.torrents["b"], 2)
    tree.groups[(7000,)].setExpanded(False)
    tree.torrents["a"].setSelected(True)
    tree.torrents["b"].setSelected(True)
    tree.header().resizeSection(0, 510)
    tree.sortItems(1, Qt.SortOrder.AscendingOrder)
    tree.show_seeding(sample())
    assert not tree.groups[(7000,)].isExpanded()
    assert tree.torrents["a"].isSelected()
    assert tree.torrents["b"].isSelected()
    assert tree.currentItem() is tree.torrents["b"]
    assert tree.currentColumn() == 2
    assert tree.header().sectionSize(0) == 510
    assert tree.header().sectionResizeMode(0) == QHeaderView.ResizeMode.Interactive
    tree.filter("COMICS")
    assert tree.groups[(7000,)].isExpanded()
    assert not tree.torrents["a"].isHidden()
    assert tree.torrents["c"].isHidden()
    assert tree.groups[()].isHidden()
    tree.show_seeding(sample())
    assert tree.torrents["c"].isHidden()
    tree.filter("")
    assert not tree.groups[(7000,)].isExpanded()
    assert not tree.torrents["c"].isHidden()


def test_notes_sort_numerically_and_categories_average_torrents_not_subcategories(qtbot):
    from dataclasses import replace

    import pytest

    tree = SeedingTree()
    qtbot.addWidget(tree)
    view = sample()
    view = replace(
        view,
        rows=[
            replace(row, note=value)
            for row, value in zip(view.rows, [2.0, 10.0, 0.0, None], strict=True)
        ],
    )
    tree.show_seeding(view)
    assert tree.torrents["a"].text(5) == "≈ 2.00"
    assert tree.groups[(7000, 7010)].text(5) == "≈ 6.00"
    assert tree.groups[(7000,)].data(5, Qt.ItemDataRole.UserRole) == pytest.approx(4.0)
    assert tree.groups[()].text(5) == "–"
    tree.sortItems(5, Qt.SortOrder.AscendingOrder)
    assert tree.groups[(7000, 7010)].child(0) is tree.torrents["a"]
    tree.filter("Small")
    assert tree.groups[(7000,)].text(5) == "≈ 4.00"
    tree.show_seeding(
        replace(
            view,
            rows=[replace(row, note=None) if row.torrent.hash == "b" else row for row in view.rows],
        )
    )
    assert tree.groups[(7000,)].text(5) == "≈ 1.00"
