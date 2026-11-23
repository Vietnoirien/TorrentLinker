"""Temporary desktop owner for shared Settings integration tests."""

from types import SimpleNamespace

from PySide6.QtWidgets import QVBoxLayout, QWidget

from tests.test_community_interfaces import js, wait_js
from torrentlinker.config import Settings
from torrentlinker.gui.settings_view import SettingsPage
from torrentlinker.store import Store


def open_tab(qtbot, view, label):
    """Open one of the Connections tabs (c411, tr4ker, Indexers, Clients, Companion, Services)."""
    import json

    js(
        qtbot,
        view,
        "[...document.querySelectorAll('.conn-tabs button')]"
        f".find(b=>b.firstChild.textContent==={json.dumps(label)}).click()",
    )
    wait_js(
        qtbot,
        view,
        "document.querySelector('.conn-tabs [aria-selected=true]')"
        f".firstChild.textContent==={json.dumps(label)}",
    )


def settings_page(qtbot, tmp_path, settings=None, *, section="connections", show=True, tab=""):
    """The Settings page in a window of its own, as the main window shows it."""

    class Owner(QWidget):
        def __init__(self):
            super().__init__()
            self.settings = settings or Settings(language="en")
            self.settings_path = tmp_path / "settings.json"
            self.store = Store(tmp_path / "state.db")
            self.exports = []
            # Connections > c411 shows the companion's state.
            self.account_workspace = SimpleNamespace(
                state=lambda: {"paired": False, "downloads": {}}
            )

        def _export_diagnostics(self, parent):
            self.exports.append(parent)

    owner = Owner()
    qtbot.addWidget(owner)
    page = SettingsPage(owner, section=section)
    QVBoxLayout(owner).addWidget(page)
    owner.resize(1200, 850)
    if show:
        owner.show()
        wait_js(qtbot, page.view, "Boolean(document.querySelector('.settings-form h2'))")
        if tab:
            open_tab(qtbot, page.view, tab)
    return page


def edit_field(qtbot, view, label, value):
    import json

    js(
        qtbot,
        view,
        f"{{const field=document.querySelector('[aria-label='+CSS.escape({json.dumps(label)})+']');"
        f"field.value={json.dumps(str(value))};field.dispatchEvent(new Event('input'));}}",
    )


def save_group(qtbot, dialog):
    js(
        qtbot,
        dialog.view,
        "document.querySelector('.settings-form > .settings-actions .primary').click()",
    )
    wait_js(
        qtbot,
        dialog.view,
        "document.querySelector('#settings-status').textContent==='Settings saved'",
    )


def service_view(
    qtbot, setup, *, assistant=None, agents=None, companion=None, section="connections", tab=""
):
    from torrentlinker.gui.settings_view import SettingsView
    from torrentlinker.settings_workspace import SettingsWorkspace

    view = SettingsView(
        SettingsWorkspace(setup),
        section=section,
        assistant_service=lambda: assistant,
        agent_service=lambda: agents,
        companion_action=companion,
        agent_endpoint="http://127.0.0.1:8790/mcp/",
    )
    qtbot.addWidget(view)
    view.resize(1200, 850)
    view.show()
    wait_js(qtbot, view, "Boolean(document.querySelector('.settings-form h2'))")
    if tab:
        open_tab(qtbot, view, tab)
    return view
