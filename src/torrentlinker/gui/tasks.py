"""Run blocking work off the GUI thread."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal


class _Signals(QObject):
    done = Signal(object)
    failed = Signal(object)


class _Job(QRunnable):
    def __init__(self, fn: Callable[[], Any]) -> None:
        super().__init__()
        self.fn = fn
        self.signals = _Signals()

    def run(self) -> None:
        try:
            result = self.fn()
        except Exception as e:  # noqa: BLE001 - surfaced to the GUI
            self.signals.failed.emit(e)
        else:
            self.signals.done.emit(result)


_alive: set[_Job] = set()


def run_in_background(
    fn: Callable[[], Any],
    on_done: Callable[[Any], object],
    on_error: Callable[[Exception], object],
) -> None:
    job = _Job(fn)
    job.setAutoDelete(False)
    _alive.add(job)

    def finish(cb: Callable[[Any], object]) -> Callable[[Any], None]:
        def handler(value: Any) -> None:
            _alive.discard(job)
            cb(value)

        return handler

    job.signals.done.connect(finish(on_done))
    job.signals.failed.connect(finish(on_error))
    QThreadPool.globalInstance().start(job)
