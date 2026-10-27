"""Load poster thumbnails for the visible Search rows without blocking the window."""

from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtGui import QImage, QPixmap

from torrentlinker.poster_cache import PosterCache, valid_poster_url

THUMB = (104, 128)  # twice the painted size, for sharp covers on HiDPI screens
MAX_IN_FLIGHT = 4
MEMORY = 300


class _Signals(QObject):
    done = Signal(str, object)  # url, QImage or None


class _Job(QRunnable):
    def __init__(self, cache: PosterCache, url: str) -> None:
        super().__init__()
        self.cache, self.url, self.signals = cache, url, _Signals()

    def run(self) -> None:
        image = None
        if (data := self.cache.fetch(self.url)) is not None:
            decoded = QImage.fromData(data)
            if not decoded.isNull() and decoded.width() * decoded.height() <= 4_000_000:
                image = decoded.scaled(
                    *THUMB,
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation,
                )
        self.signals.done.emit(self.url, image)


class PosterLoader(QObject):
    """pixmap(url) answers at once from memory and starts at most MAX_IN_FLIGHT downloads;
    `loaded` fires when a poster arrives so the rows repaint."""

    loaded = Signal(str)

    def __init__(self, cache: PosterCache, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.cache = cache
        self.enabled = True
        self._pixmaps: dict[str, QPixmap | None] = {}
        self._pending: set[str] = set()
        self._jobs: set[_Job] = set()
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(MAX_IN_FLIGHT)

    def pixmap(self, url: str) -> QPixmap | None:
        if not self.enabled or not url:
            return None
        if url in self._pixmaps:
            return self._pixmaps[url]
        if url not in self._pending and valid_poster_url(url):
            self._pending.add(url)
            job = _Job(self.cache, url)
            job.setAutoDelete(False)
            job.signals.done.connect(self._arrived)
            self._jobs.add(job)
            self._pool.start(job)
        return None

    def _arrived(self, url: str, image: object) -> None:
        self._pending.discard(url)
        if len(self._pixmaps) >= MEMORY:
            self._pixmaps.pop(next(iter(self._pixmaps)))
        self._pixmaps[url] = QPixmap.fromImage(image) if isinstance(image, QImage) else None
        self._jobs = {job for job in self._jobs if job.url != url}
        self.loaded.emit(url)

    def stop(self) -> None:
        self._pool.clear()
        self._pool.waitForDone(2000)
