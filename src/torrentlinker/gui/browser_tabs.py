"""Movable preview tabs with a permanent search page and scoped shortcuts."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, Signal
from PySide6.QtGui import QAction, QKeySequence, QMouseEvent, QShortcut
from PySide6.QtWidgets import QMenu, QTabBar, QTabWidget, QToolButton, QWidget


class BrowserTabs(QTabWidget):
    close_requested = Signal(object)

    def __init__(self, home: QWidget) -> None:
        super().__init__()
        self.home = home
        self.setObjectName("searchBrowser")
        self.tabBar().setObjectName("searchBrowserBar")
        self.setDocumentMode(True)
        self.tabBar().setDrawBase(False)
        self.setMovable(True)
        self.setUsesScrollButtons(True)
        self.tabBar().setElideMode(Qt.TextElideMode.ElideRight)
        self.tabBar().setExpanding(False)
        self.addTab(home, self.tr("Search"))
        # The home page remains in the stack and keyboard cycle, but its button
        # lives outside the scrolling strip so it cannot disappear on overflow.
        # Hide only the tab label. QTabWidget.setTabVisible also hides the
        # Search page itself when it is the only page on startup.
        self.tabBar().setTabVisible(0, False)
        self.home_button = QToolButton()
        self.home_button.setObjectName("browserHome")
        self.home_button.setText(self.tr("Search"))
        self.home_button.setCheckable(True)
        self.home_button.setChecked(True)
        self.home_button.clicked.connect(self._show_home)
        self.currentChanged.connect(
            lambda _: self.home_button.setChecked(self.currentWidget() is self.home)
        )
        self.setCornerWidget(self.home_button, Qt.Corner.TopLeftCorner)
        self.tabBar().setTabButton(0, QTabBar.ButtonPosition.RightSide, None)
        self.tabBar().setTabButton(0, QTabBar.ButtonPosition.LeftSide, None)
        self.tabCloseRequested.connect(self.request_close)
        self.tabBar().installEventFilter(self)
        self.tabBar().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tabBar().customContextMenuRequested.connect(self._menu)
        self.tab_list = QToolButton()
        self.tab_list.setObjectName("browserTabList")
        self.tab_list.setText(self.tr("Open tabs"))
        self.tab_list.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.extra_actions: list[QAction] = []  # shown under the tab list, for whole-set actions
        self.tab_menu = QMenu(self.tab_list)
        self.tab_menu.aboutToShow.connect(self._fill_tab_menu)
        self.tab_list.setMenu(self.tab_menu)
        self.setCornerWidget(self.tab_list)
        for key, action in (
            ("Ctrl+W", lambda: self.request_close(self.currentIndex())),
            ("Ctrl+Tab", lambda: self.setCurrentIndex((self.currentIndex() + 1) % self.count())),
            (
                "Ctrl+Shift+Tab",
                lambda: self.setCurrentIndex((self.currentIndex() - 1) % self.count()),
            ),
        ):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(action)

    def _show_home(self) -> None:
        self.setCurrentWidget(self.home)
        self.home_button.setChecked(True)

    def add_preview(self, page: QWidget, title: str) -> None:
        index = self.addTab(page, title)
        self.setTabToolTip(index, title)
        close = QToolButton(self.tabBar())
        close.setObjectName("browserTabClose")
        close.setText("×")
        close.setToolTip(self.tr("Close tab"))
        close.setAccessibleName(self.tr("Close tab"))
        close.setFixedSize(24, 24)
        close.clicked.connect(lambda: self.request_close(self.indexOf(page)))
        self.tabBar().setTabButton(index, QTabBar.ButtonPosition.RightSide, close)

    def request_close(self, index: int) -> None:
        page = self.widget(index)
        if page is not None and page is not self.home:
            self.close_requested.emit(page)

    def close_others(self, keep: QWidget) -> None:
        for index in reversed(range(self.count())):
            page = self.widget(index)
            if page is not keep:
                self.request_close(index)

    def _fill_tab_menu(self) -> None:
        self.tab_menu.clear()
        for index in range(self.count()):
            page = self.widget(index)
            title = self.tabToolTip(index) or self.tabText(index)
            action = self.tab_menu.addAction(title)
            action.setCheckable(True)
            action.setChecked(page is self.currentWidget())
            action.triggered.connect(
                lambda checked=False, target=page: self.setCurrentWidget(target)
            )
        if self.extra_actions:
            self.tab_menu.addSeparator()
            for action in self.extra_actions:
                self.tab_menu.addAction(action)

    def _menu(self, position: QPoint) -> None:
        index = self.tabBar().tabAt(position)
        page = self.widget(index)
        if page is None:
            return
        menu = QMenu(self)
        close = menu.addAction(self.tr("Close tab"))
        close.setEnabled(page is not self.home)
        close.triggered.connect(lambda: self.request_close(self.indexOf(page)))
        others = menu.addAction(self.tr("Close other tabs"))
        others.triggered.connect(lambda: self.close_others(page))
        all_tabs = menu.addAction(self.tr("Close all torrent tabs"))
        all_tabs.triggered.connect(lambda: self.close_others(self.home))
        menu.exec(self.tabBar().mapToGlobal(position))

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.tabBar() and event.type() == QEvent.Type.MouseButtonRelease:
            if isinstance(event, QMouseEvent) and event.button() == Qt.MouseButton.MiddleButton:
                self.request_close(self.tabBar().tabAt(event.position().toPoint()))
                return True
        return super().eventFilter(watched, event)
