from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QStandardPaths, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from torrentlinker import i18n
from torrentlinker.config import Settings
from torrentlinker.gui.main_window import MainWindow
from torrentlinker.store import Store


def data_dir() -> Path:
    return Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation))


def smoke_checks() -> None:
    """Exercise what a broken bundle would miss: guessit data, translations, assets."""
    from torrentlinker.domain import LocalItem
    from torrentlinker.queries import parse_name

    info = parse_name(LocalItem(Path("Amelie.2001.1080p.mkv"), {"Amelie.2001.1080p.mkv": 1}))
    assert info.get("title") == "Amelie" and info.get("year") == 2001, info
    assert (Path(i18n.__file__).parent / "torrentlinker_fr.qm").exists()
    assert (Path(__file__).parent / "assets" / "icon.png").exists()
    print("smoke test OK")


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("TorrentLinker")
    app.setOrganizationName("TorrentLinker")
    app.setWindowIcon(QIcon(str(Path(__file__).parent / "assets" / "icon.png")))
    settings_path = data_dir() / "settings.json"
    settings = Settings.load(settings_path)
    translators = i18n.install(app, i18n.pick_language(settings.language))  # noqa: F841
    store = Store(data_dir() / "state.db")
    window = MainWindow(settings, settings_path, store)
    window.show()
    if "--smoke-test" in sys.argv:  # used by CI on packaged builds
        smoke_checks()
        QTimer.singleShot(500, app.quit)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
