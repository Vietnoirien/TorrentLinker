from __future__ import annotations

import multiprocessing
import sys
from pathlib import Path

from PySide6.QtCore import QStandardPaths, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from torrentlinker import i18n
from torrentlinker.config import Settings
from torrentlinker.gui.main_window import MainWindow
from torrentlinker.gui.theme import apply_theme
from torrentlinker.store import Store
from torrentlinker.updates import CHECK_INTERVAL, installed_version, release_version


def data_dir() -> Path:
    return Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation))


def smoke_checks() -> None:
    """Exercise what a broken bundle would miss: guessit data, translations, assets, and
    the SOCKS support imported only once a SOCKS proxy is set."""
    import httpx

    from torrentlinker.domain import LocalItem
    from torrentlinker.queries import parse_name

    httpx.Client(proxy="socks5://127.0.0.1:1080").close()  # needs socksio
    import socks  # noqa: F401 - requests' SOCKS support, for qBittorrent's adapter
    import sockshandler  # noqa: F401

    info = parse_name(LocalItem(Path("Amelie.2001.1080p.mkv"), {"Amelie.2001.1080p.mkv": 1}))
    assert info.get("title") == "Amelie" and info.get("year") == 2001, info
    assert (Path(i18n.__file__).parent / "torrentlinker_fr.qm").exists()
    assert (Path(__file__).parent / "assets" / "icon.png").exists()
    assert release_version(installed_version()) is not None, "missing application version metadata"
    print("smoke test OK")


def setup_logging(path: Path) -> None:
    import logging

    path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(path, encoding="utf-8"), logging.StreamHandler()],
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)


def show_unexpected_errors() -> None:
    """Errors raised inside Qt callbacks would otherwise only reach the terminal."""
    import logging
    import traceback
    from types import TracebackType

    from PySide6.QtWidgets import QMessageBox

    def hook(kind: type[BaseException], error: BaseException, tb: TracebackType | None) -> None:
        details = "".join(traceback.format_exception(kind, error, tb))
        logging.getLogger("torrentlinker").error("unexpected error\n%s", details)
        box = QMessageBox(QMessageBox.Icon.Critical, "TorrentLinker", f"{kind.__name__}: {error}")
        box.setDetailedText(details)
        box.exec()

    sys.excepthook = hook


def main() -> int:
    multiprocessing.freeze_support()  # a frozen build re-runs itself for child processes
    app = QApplication(sys.argv)
    app.setApplicationName("TorrentLinker")
    app.setOrganizationName("TorrentLinker")
    show_unexpected_errors()
    app.setWindowIcon(QIcon(str(Path(__file__).parent / "assets" / "icon.png")))
    setup_logging(data_dir() / "torrentlinker.log")
    settings_path = data_dir() / "settings.json"
    settings = Settings.load(settings_path)
    apply_theme(app, settings.theme)
    translators = i18n.install(app, i18n.pick_language(settings.language))  # noqa: F841
    store = Store(data_dir() / "state.db")
    window = MainWindow(settings, settings_path, store)
    window.show()
    if "--smoke-test" in sys.argv:  # used by CI on packaged builds
        smoke_checks()
        QTimer.singleShot(500, app.quit)
    else:
        update_timer = QTimer(window)
        update_timer.setInterval(CHECK_INTERVAL * 1000)
        update_timer.timeout.connect(window.check_for_updates)
        update_timer.start()
        QTimer.singleShot(1000, window.check_for_updates)
        QTimer.singleShot(0, window.startup)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
