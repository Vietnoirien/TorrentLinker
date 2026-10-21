from pathlib import Path

from torrentlinker.config import Settings
from torrentlinker.gui.main_window import MainWindow
from torrentlinker.store import Store


def test_main_window_opens(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    window = MainWindow(Settings(), tmp_path / "settings.json", Store(tmp_path / "s.db"))
    qtbot.addWidget(window)
    window.show()
    assert window.isVisible()


def test_settings_open_on_the_connections_tab_with_hidden_keys(qtbot) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QLineEdit

    from torrentlinker.gui.settings_dialog import SettingsDialog

    dialog = SettingsDialog(Settings())
    qtbot.addWidget(dialog)

    assert dialog.tabs.currentIndex() == 0
    assert dialog.indexer_key.echoMode() == QLineEdit.EchoMode.Password
    assert dialog.tmdb_key.echoMode() == QLineEdit.EchoMode.Password
