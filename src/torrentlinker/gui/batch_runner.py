"""Run a batch search off the GUI thread, reporting each result as it lands."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from torrentlinker.batch import run_batch
from torrentlinker.library import LibraryEntry
from torrentlinker.review import Verified


class BatchSignals(QObject):
    result = Signal(int, int, object, object)  # index, total, entry, results
    error = Signal(object, object)  # entry, exception
    finished = Signal(int)


class BatchRunner(QRunnable):
    def __init__(
        self, entries: list[LibraryEntry], search: Callable[[LibraryEntry], list[Verified]]
    ) -> None:
        super().__init__()
        self.entries = entries
        self.search = search
        self.signals = BatchSignals()
        self._cancelled = False
        self.setAutoDelete(False)

    def cancel(self) -> None:
        self._cancelled = True

    def start(self) -> None:
        QThreadPool.globalInstance().start(self)

    def run(self) -> None:
        done = run_batch(
            self.entries,
            self.search,
            lambda i, n, e, r: self.signals.result.emit(i, n, e, r),
            lambda: self._cancelled,
            lambda e, err: self.signals.error.emit(e, err),
        )
        self.signals.finished.emit(done)
