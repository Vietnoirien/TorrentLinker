from pathlib import Path

import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QHeaderView

from torrentlinker.domain import Torrent
from torrentlinker.downloads import IndexerCategory
from torrentlinker.gui.seeding_tree import SeedingTree
from torrentlinker.seeding import Seeding, SeedingRow
from torrentlinker.zen import ZenDay


@pytest.fixture(autouse=True)
def isolated_preferences(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "torrentlinker.gui.seeding_tree.QSettings",
        lambda: QSettings(str(tmp_path / "view.ini"), QSettings.Format.IniFormat),
    )


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


def test_categories_start_collapsed_and_user_layout_survives_restart(qtbot):
    from dataclasses import replace

    tree = SeedingTree()
    qtbot.addWidget(tree)
    tree.show_seeding(sample())
    assert all(not item.isExpanded() for item in tree.groups.values())
    tree.groups[(7000,)].setExpanded(True)
    tree.groups[(7000, 7010)].setExpanded(True)
    tree.groups[(7000,)].setExpanded(False)

    reopened = SeedingTree()
    qtbot.addWidget(reopened)
    view = sample()
    view = replace(view, categories={**view.categories, 7000: IndexerCategory("Livres")})
    reopened.show_seeding(view)
    assert not reopened.groups[(7000,)].isExpanded()
    assert reopened.groups[(7000, 7010)].isExpanded()
    reopened.groups[(7000,)].setExpanded(True)
    reopened.show_seeding(view)
    assert reopened.groups[(7000,)].isExpanded()
    assert reopened.groups[(7000, 7010)].isExpanded()
    assert not reopened.groups[()].isExpanded()


def test_filter_and_refresh_do_not_persist_automatic_expansion(qtbot):
    tree = SeedingTree()
    qtbot.addWidget(tree)
    tree.show_seeding(sample())
    tree.groups[(7000,)].setExpanded(True)
    tree.filter("small")
    assert tree.groups[(7000, 7010)].isExpanded()
    tree.show_seeding(sample())
    assert tree.groups[(7000, 7010)].isExpanded()
    reopened = SeedingTree()
    qtbot.addWidget(reopened)
    reopened.show_seeding(sample())
    assert reopened.groups[(7000,)].isExpanded()
    assert not reopened.groups[(7000, 7010)].isExpanded()
    tree.filter("")
    assert tree.groups[(7000,)].isExpanded()
    assert not tree.groups[(7000, 7010)].isExpanded()


def test_expand_and_collapse_all_are_remembered_after_restart(qtbot):
    tree = SeedingTree()
    qtbot.addWidget(tree)
    tree.show_seeding(sample())
    tree.expandAll()
    reopened = SeedingTree()
    qtbot.addWidget(reopened)
    reopened.show_seeding(sample())
    assert all(item.isExpanded() for item in reopened.groups.values())
    reopened.filter("small")
    reopened.collapseAll()
    reopened.filter("")
    assert all(not item.isExpanded() for item in reopened.groups.values())
    restarted = SeedingTree()
    qtbot.addWidget(restarted)
    restarted.show_seeding(sample())
    assert all(not item.isExpanded() for item in restarted.groups.values())
