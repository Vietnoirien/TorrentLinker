from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QStandardPaths
from PySide6.QtWidgets import QApplication

from torrentlinker.config import Settings
from torrentlinker.gui.main_window import MainWindow


def data_dir() -> Path:
    return Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation))


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("TorrentLinker")
    app.setOrganizationName("TorrentLinker")
    settings_path = data_dir() / "settings.json"
    window = MainWindow(Settings.load(settings_path), settings_path)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
