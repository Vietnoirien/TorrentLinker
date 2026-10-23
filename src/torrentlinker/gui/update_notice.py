"""A quiet, dismissible notice linking to a newer release."""

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton

from torrentlinker.updates import Release


class UpdateNotice(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("updateNotice")
        self.release: Release | None = None
        self._dismissed: str | None = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        self.message = QLabel()
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        self.message.setWordWrap(True)
        layout.addWidget(self.message, 1)
        self.open_button = QPushButton(self.tr("View release"))
        self.open_button.clicked.connect(self._open_release)
        layout.addWidget(self.open_button)
        self.dismiss_button = QPushButton(self.tr("Dismiss"))
        self.dismiss_button.clicked.connect(self._dismiss)
        layout.addWidget(self.dismiss_button)
        self.hide()

    def show_release(self, release: Release | None) -> None:
        if release is None or release.tag == self._dismissed:
            return
        self.release = release
        self.message.setText(
            self.tr("TorrentLinker {version} is available.").format(version=release.tag)
        )
        self.show()

    def _open_release(self) -> None:
        if self.release:
            QDesktopServices.openUrl(QUrl(self.release.url))

    def _dismiss(self) -> None:
        if self.release:
            self._dismissed = self.release.tag
        self.hide()
