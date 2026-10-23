import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QToolButton, QWidget

from torrentlinker.gui.browser_tabs import BrowserTabs
from torrentlinker.gui.theme import _update_theme


@pytest.mark.parametrize("scheme", [Qt.ColorScheme.Dark, Qt.ColorScheme.Light])
def test_overflow_scrolls_both_ways_and_keeps_search_accessible(qtbot, qapp, scheme):
    previous = qapp.styleSheet()
    palette = qapp.palette()
    try:
        _update_theme(qapp, scheme)
        browser = BrowserTabs(QWidget())
        qtbot.addWidget(browser)
        browser.resize(1000, 400)
        for i in range(30):
            browser.add_preview(QWidget(), f"Torrent {i:02d} MULTI 1080p BluRay long title")
        browser.show()
        browser.setCurrentIndex(30)
        qapp.processEvents()
        bar = browser.tabBar()
        left = bar.findChild(QToolButton, "ScrollLeftButton")
        right = bar.findChild(QToolButton, "ScrollRightButton")
        assert left.isVisible() and right.isVisible()
        assert left.width() >= 28 and right.width() >= 28
        assert browser.home_button.isVisible()
        # Scroll back far enough to reveal the oldest torrent, then click it.
        for _ in range(40):
            if not left.isEnabled():
                break
            qtbot.mouseClick(left, Qt.MouseButton.LeftButton)
        assert bar.tabRect(1).left() >= 0
        qtbot.mouseClick(bar, Qt.MouseButton.LeftButton, pos=bar.tabRect(1).center())
        assert browser.currentIndex() == 1
        assert right.isEnabled()
        # The opposite direction must still reach the newest torrent.
        for _ in range(40):
            if not right.isEnabled():
                break
            qtbot.mouseClick(right, Qt.MouseButton.LeftButton)
        assert bar.tabRect(30).right() < left.x()
        qtbot.mouseClick(bar, Qt.MouseButton.LeftButton, pos=bar.tabRect(30).center())
        assert browser.currentIndex() == 30
        qtbot.mouseClick(browser.home_button, Qt.MouseButton.LeftButton)
        assert browser.currentWidget() is browser.home
        browser._fill_tab_menu()
        browser.tab_menu.actions()[1].trigger()
        assert browser.currentIndex() == 1
    finally:
        qapp.setPalette(palette)
        qapp.setStyleSheet(previous)
