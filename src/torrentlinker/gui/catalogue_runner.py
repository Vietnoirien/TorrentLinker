"""Update the Catalogue off the GUI thread, reporting each page read."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from torrentlinker.catalogue import CrawlProgress, Progress


class CatalogueSignals(QObject):
    progress = Signal(object)  # CrawlProgress
    failed = Signal(object)  # exception
    finished = Signal(bool)  # True when stopped before the end


class CatalogueRunner(QRunnable):
    """Runs `work(stop, progress)`; `stop()` asks it to end after the current page."""

    def __init__(self, work: Callable[[Callable[[], bool], Progress], None]) -> None:
        super().__init__()
        self.work = work
        self.signals = CatalogueSignals()
        self._stopped = False
        self.setAutoDelete(False)

    def stop(self) -> None:
        self._stopped = True

    @property
    def stopped(self) -> bool:
        return self._stopped

    def start(self) -> None:
        QThreadPool.globalInstance().start(self)

    def run(self) -> None:
        def progress(p: CrawlProgress) -> None:
            self.signals.progress.emit(p)

        try:
            self.work(lambda: self._stopped, progress)
        except Exception as e:  # noqa: BLE001 - surfaced to the GUI
            self.signals.failed.emit(e)
        self.signals.finished.emit(self._stopped)
