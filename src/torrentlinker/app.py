from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QStandardPaths
from PySide6.QtWidgets import QApplication

from torrentlinker import i18n
from torrentlinker.config import Settings
from torrentlinker.gui.main_window import MainWindow
from torrentlinker.store import Store


def data_dir() -> Path:
    return Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation))


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("TorrentLinker")
    app.setOrganizationName("TorrentLinker")
    settings_path = data_dir() / "settings.json"
    settings = Settings.load(settings_path)
    translators = i18n.install(app, i18n.pick_language(settings.language))  # noqa: F841
    store = Store(data_dir() / "state.db")
    window = MainWindow(settings, settings_path, store)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
