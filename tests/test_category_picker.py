from PySide6.QtCore import QPoint, Qt

from torrentlinker.downloads import IndexerCategory
from torrentlinker.gui.category_picker import CategoryPicker

CATEGORIES = {
    2000: IndexerCategory("Films & Videos"),
    2030: IndexerCategory("Film", 2000),
    2070: IndexerCategory("Documentary", 2000),
    7000: IndexerCategory("Books"),
    7020: IndexerCategory("Novels", 7000),
}


def picker(qtbot):
    widget = CategoryPicker()
    qtbot.addWidget(widget)
    widget.resize(400, 40)
    widget.set_categories(CATEGORIES)
    widget.show()
    return widget


def test_expand_does_not_select_and_subcategory_click_selects(qtbot):
    widget = picker(qtbot)
    widget.show_popup()
    qtbot.waitUntil(widget.popup.isVisible)
    root = widget.items[2000]
    assert root.childCount() == 2
    assert widget.items[2030].parent() is root
    assert not root.isExpanded()
    rect = widget.tree.visualItemRect(root)
    qtbot.mouseClick(
        widget.tree.viewport(),
        Qt.MouseButton.LeftButton,
        pos=QPoint(rect.left() - 11, rect.center().y()),
    )
    assert root.isExpanded()
    assert widget.popup.isVisible()
    assert widget.current_category is None
    child = widget.items[2030]
    qtbot.mouseClick(
        widget.tree.viewport(),
        Qt.MouseButton.LeftButton,
        pos=widget.tree.visualItemRect(child).center(),
    )
    assert widget.current_category == 2030
    assert widget.toolTip() == "Films & Videos / Film"
    assert not widget.popup.isVisible()


def test_parent_all_and_escape_keyboard_choices(qtbot):
    widget = picker(qtbot)
    widget.select_category(2030)
    widget.show_popup()
    assert widget.items[2000].isExpanded()
    widget.tree.setCurrentItem(widget.items[2000])
    qtbot.keyClick(widget.tree, Qt.Key.Key_Return)
    assert widget.current_category == 2000
    assert not widget.popup.isVisible()
    widget.show_popup()
    widget.tree.setCurrentItem(widget.items[7020])
    qtbot.keyClick(widget.tree, Qt.Key.Key_Escape)
    assert not widget.popup.isVisible()
    assert widget.current_category == 2000
    widget.show_popup()
    widget.tree.setCurrentItem(widget.all_item)
    qtbot.keyClick(widget.tree, Qt.Key.Key_Return)
    assert widget.current_category is None


def test_refresh_preserves_selection_and_hierarchy_and_handles_missing_ids(qtbot):
    widget = picker(qtbot)
    widget.select_category(7020)
    widget.items[7000].setExpanded(True)
    widget.set_categories(dict(reversed(list(CATEGORIES.items()))))
    assert widget.current_category == 7020
    assert widget.items[7000].isExpanded()
    assert widget.items[7020].parent() is widget.items[7000]
    widget.set_categories({2000: CATEGORIES[2000]})
    assert widget.current_category is None
