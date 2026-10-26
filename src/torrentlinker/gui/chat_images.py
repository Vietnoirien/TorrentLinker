"""Asynchronous image previews shared across transcript refreshes."""

from collections import OrderedDict

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QImage
from shiboken6 import isValid

from torrentlinker.assistant.images import fetch_image, image_url
from torrentlinker.gui.tasks import run_in_background
from torrentlinker.gui.torrent_details import decode_preview
from torrentlinker.upload_assets import inline_image


class ChatImages(QObject):
    ready = Signal(str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.images: OrderedDict[str, QImage | None] = OrderedDict()
        self.pending: set[str] = set()

    def request(self, url: str) -> QImage | None:
        if url in self.images:
            self.images.move_to_end(url)
            return self.images[url]
        inline = inline_image(url)
        if url in self.pending or not (inline or image_url(url)):
            return None
        self.pending.add(url)

        def finished(image):
            if not isValid(self):
                return
            self.pending.discard(url)
            self.images[url] = image
            while len(self.images) > 32:
                self.images.popitem(last=False)
            self.ready.emit(url, image)

        def load():
            return decode_preview(inline[0] if inline else fetch_image(url)[0]).scaled(
                360,
                360,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )

        run_in_background(load, finished, lambda error: finished(None))
        return None
