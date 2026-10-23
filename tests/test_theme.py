import subprocess

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QProcess, Qt

from torrentlinker.config import Settings
from torrentlinker.gui import theme


@pytest.fixture
def desktop(qapp, monkeypatch):
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "GNOME")
    monkeypatch.setattr(theme.sys, "platform", "linux")
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess(a, 0, "'prefer-dark'\n")
    )
    # Keep the real desktop monitor out of deterministic unit tests.
    monkeypatch.setattr(QProcess, "start", lambda *a, **kw: None)
    theme._update_theme(qapp, Qt.ColorScheme.Light)
    theme.apply_theme(qapp)
    follower = qapp.findChild(theme.ThemeFollower)
    yield follower
    follower.stop()
    follower.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    theme._update_theme(qapp, Qt.ColorScheme.Light)


def test_explicit_gnome_dark_preference_overrides_light_qt_hint(qapp, desktop):
    assert qapp.palette().window().color().lightness() < 128


def test_manual_theme_overrides_desktop_and_auto_resumes_following(qapp, desktop):
    theme.set_theme("light")
    assert qapp.palette().window().color().lightness() > 128
    desktop.set_preference("color-scheme: 'prefer-dark'")
    assert qapp.palette().window().color().lightness() > 128
    theme.set_theme("auto")
    assert qapp.palette().window().color().lightness() < 128
    desktop.set_preference("color-scheme: 'prefer-light'")
    assert qapp.palette().window().color().lightness() > 128
    theme.set_theme("dark")
    assert qapp.palette().window().color().lightness() < 128


def test_theme_setting_is_saved_and_old_settings_default_to_auto(tmp_path, qtbot):
    from torrentlinker.gui.settings_dialog import SettingsDialog

    path = tmp_path / "settings.json"
    path.write_text("{}")
    settings = Settings.load(path)
    assert settings.theme == "auto"
    dialog = SettingsDialog(settings)
    qtbot.addWidget(dialog)
    dialog.theme.setCurrentIndex(dialog.theme.findData("dark"))
    dialog._save()
    assert settings.theme == "dark"
    settings.save(path)
    assert Settings.load(path).theme == "dark"
