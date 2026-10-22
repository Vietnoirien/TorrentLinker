"""Send a Plan off the GUI thread, reporting each torrent and any wait for the Indexer."""

from __future__ import annotations

import threading
from collections.abc import Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, SignalInstance
from shiboken6 import isValid

from torrentlinker.send import SendProgress, SendReport


class SendSignals(QObject):
    progress = Signal(object)  # SendProgress
    failed = Signal(object)  # exception
    finished = Signal(object)  # SendReport


class SendRunner(QRunnable):
    """Runs `work(stop, progress)`; `stop()` ends it before the next torrent or wait."""

    def __init__(
        self, work: Callable[[threading.Event, Callable[[SendProgress], None]], SendReport]
    ) -> None:
        super().__init__()
        self.work = work
        self.signals = SendSignals()
        self._stop = threading.Event()
        self.setAutoDelete(False)

    def stop(self) -> None:
        self._stop.set()

    def start(self) -> None:
        QThreadPool.globalInstance().start(self)

    def run(self) -> None:
        def emit(signal: SignalInstance, *args: object) -> None:
            try:
                signal.emit(*args)
            except RuntimeError:
                if isValid(self.signals):
                    raise
                self.stop()  # the window is gone: nobody is left to receive

        try:
            report = self.work(self._stop, lambda p: emit(self.signals.progress, p))
        except Exception as e:  # noqa: BLE001 - surfaced to the GUI
            emit(self.signals.failed, e)
        else:
            emit(self.signals.finished, report)
