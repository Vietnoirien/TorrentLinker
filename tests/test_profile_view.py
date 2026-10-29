from PySide6.QtCore import Qt

from tests.test_web_profile import ORIGIN, prepared, snapshot
from torrentlinker.gui.zen_view import ZenTab
from torrentlinker.zen import ZenProfile


def test_profile_is_first_desktop_tab_and_shows_api_and_companion(qtbot, tmp_path, monkeypatch):
    _, setup = prepared(tmp_path, monkeypatch)
    workspace = setup.profile_workspace()
    workspace.refresh(setup.settings.indexer.url, "fake-key")
    tab = ZenTab(lambda: lambda: None, ZenProfile)
    qtbot.addWidget(tab)
    tab.resize(1200, 850)
    tab.show()
    assert tab.pages.tabText(0) == "Profile"
    view = tab.profile_view
    view.show_state(workspace.state())
    assert "Demo account" in view.identity.text()
    assert "123.5" in view.balance.text()
    assert "Connect" in view.advanced_status.text()
    with qtbot.waitSignal(view.pair_requested):
        qtbot.mouseClick(view.pair_button, Qt.MouseButton.LeftButton)
    code = workspace.pairing()["code"]
    token = workspace.receive("/api/companion/pair", ORIGIN, "", {"code": code, "accountId": "42"})[
        "token"
    ]
    workspace.receive("/api/companion/snapshot", ORIGIN, "Bearer " + token, snapshot())
    view.show_state(workspace.state())
    assert "42" in view.active_seeds.text()
    assert view.disconnect_button.isEnabled()
    import os
    from pathlib import Path

    if output := os.getenv("TL_PROFILE_SCREENSHOTS"):
        from PySide6.QtWidgets import QApplication

        from torrentlinker.gui.theme import apply_theme

        apply_theme(QApplication.instance(), "dark")
        tab.resize(1400, 1000)
        qtbot.wait(100)
        target = Path(output)
        target.mkdir(parents=True, exist_ok=True)
        assert tab.grab().save(str(target / "desktop-profile.png"))
    workspace.disconnect()
    view.show_state(workspace.state())
    assert not view.advanced_metrics.isVisible()
