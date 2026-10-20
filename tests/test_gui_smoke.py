from pathlib import Path

from torrentlinker.config import Settings
from torrentlinker.gui.main_window import MainWindow


def test_main_window_opens(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    window = MainWindow(Settings(), tmp_path / "settings.json")
    qtbot.addWidget(window)
    window.show()
    assert window.isVisible()
