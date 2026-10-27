"""Numbered page links for the Search results: 1 2 3 … 400, Next, Last."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget


def page_numbers(current: int, total: int) -> list[int | None]:
    """Pages to link, with None for a gap: the ends, the neighbours of the current page,
    and the first or last three when it is near an end."""
    if total < 1:
        return []
    current = min(max(1, current), total)
    wanted = {1, total, current - 1, current, current + 1}
    if current <= 3:
        wanted |= {1, 2, 3}
    if current >= total - 2:
        wanted |= {total - 2, total - 1, total}
    pages = sorted(n for n in wanted if 1 <= n <= total)
    result: list[int | None] = []
    for number in pages:
        if result:
            last = result[-1]
            assert last is not None
            if number - last == 2:
                result.append(last + 1)  # a single hidden page is shown, not an ellipsis
            elif number - last > 2:
                result.append(None)
        result.append(number)
    return result


class PageBar(QWidget):
    page_requested = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self.current, self.total = 1, 1
        self.layout_ = QHBoxLayout(self)
        self.layout_.setContentsMargins(0, 0, 0, 0)
        self.layout_.setSpacing(6)
        self.previous = QPushButton(self.tr("← Previous"))
        self.previous.setProperty("chip", "page")
        self.previous.clicked.connect(lambda: self.page_requested.emit(self.current - 1))
        self.next = QPushButton(self.tr("Next →"))
        self.next.setProperty("chip", "page")
        self.next.clicked.connect(lambda: self.page_requested.emit(self.current + 1))
        self.last = QPushButton(self.tr("Last »"))
        self.last.setProperty("chip", "page")
        self.last.clicked.connect(lambda: self.page_requested.emit(self.total))
        self._state: tuple[int, int | None, bool, bool] | None = None
        self.set_state(1, None, False, False)

    def _clear(self) -> None:
        keep = (self.previous, self.next, self.last)
        while item := self.layout_.takeAt(0):
            widget = item.widget()
            if widget is not None and widget not in keep:
                widget.deleteLater()
            elif widget is not None:
                widget.hide()

    def set_state(self, page: int, total_pages: int | None, has_more: bool, enabled: bool) -> None:
        """total_pages is None when the Indexer does not say how many there are."""
        state = (page, total_pages, has_more, enabled)
        if state == self._state:
            return
        self._state = state
        self.current, self.total = page, total_pages or page
        self._clear()
        if page > 1:
            self.layout_.addWidget(self.previous)
            self.previous.show()
        if total_pages:
            for number in page_numbers(page, total_pages):
                if number is None:
                    self.layout_.addWidget(QLabel("…"))
                    continue
                button = QPushButton(str(number))
                button.setProperty("chip", "page")
                button.setCheckable(True)
                button.setChecked(number == page)
                button.setEnabled(enabled)
                button.setAccessibleName(self.tr("Page {0}").format(number))
                button.clicked.connect(lambda _=False, n=number: self.page_requested.emit(n))
                self.layout_.addWidget(button)
        if has_more:
            self.layout_.addWidget(self.next)
            self.next.show()
        if total_pages and page < total_pages - 1:
            self.layout_.addWidget(self.last)
            self.last.show()
            self.last.setEnabled(enabled)
        self.layout_.addStretch()
        # Hidden buttons keep an honest state for keyboard shortcuts and tests.
        self.previous.setEnabled(enabled and page > 1)
        self.next.setEnabled(enabled and has_more)
        self.last.setEnabled(enabled)
