from types import SimpleNamespace

import pytest
from qbittorrentapi import LoginFailed

from torrentlinker.config import Settings
from torrentlinker.gui.settings_dialog import SettingsDialog


@pytest.mark.parametrize(
    "error", [LoginFailed(), TimeoutError(), RuntimeError("connection refused")]
)
def test_connection_warning_always_explains_failure(qtbot, monkeypatch, error):
    dialog = SettingsDialog(Settings())
    qtbot.addWidget(dialog)
    monkeypatch.setattr(dialog, "_form_qbit", lambda: SimpleNamespace(check=lambda: None))
    monkeypatch.setattr(
        "torrentlinker.gui.settings_dialog.run_in_background",
        lambda fn, done, failed: failed(error),
    )
    messages = []
    monkeypatch.setattr(
        "torrentlinker.gui.settings_dialog.QMessageBox.warning",
        lambda parent, title, text: messages.append(text),
    )
    dialog._test_qbit()
    assert messages and "Web UI" in messages[0] and "running" in messages[0]
    assert (str(error) or type(error).__name__) in messages[0]
