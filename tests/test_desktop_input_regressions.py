from PySide6.QtWidgets import QDialogButtonBox

from tests.test_community_interfaces import js, wait_js
from torrentlinker.config import Settings
from torrentlinker.gui.settings_dialog import SettingsDialog
from torrentlinker.gui.zen_view import PlanView


def test_editing_plan_size_keeps_focus_and_scroll(qtbot):
    view = PlanView()
    qtbot.addWidget(view)
    view.resize(620, 450)
    view.options_changed.connect(lambda _: view.invalidate())
    view.show()
    wait_js(qtbot, view, "typeof initialized!=='undefined' && initialized")
    js(qtbot, view, "document.querySelector('#plan-options').open=true")
    js(qtbot, view, "document.querySelector('#plan-min-size').focus();window.scrollTo(0,120)")
    before = js(qtbot, view, "window.scrollY")
    js(
        qtbot,
        view,
        "document.querySelector('#plan-min-size').value='4';"
        "document.querySelector('#plan-min-size').dispatchEvent(new Event('input',{bubbles:true}))",
    )
    qtbot.waitUntil(lambda: view.options.min_size == 4 * 1024**3)
    assert js(qtbot, view, "document.activeElement.id==='plan-min-size'")
    assert js(qtbot, view, "window.scrollY") == before
    assert js(qtbot, view, "document.querySelector('#plan-min-size').value==='4'")


def test_scrolling_over_focused_plan_size_does_not_change_value(qtbot):
    view = PlanView()
    qtbot.addWidget(view)
    view.show()
    wait_js(qtbot, view, "typeof initialized!=='undefined' && initialized")
    js(qtbot, view, "document.querySelector('#plan-options').open=true")
    assert js(
        qtbot,
        view,
        """(() => {
      const input=document.querySelector('#plan-min-size');input.value='4';input.focus();
      const wheel=new WheelEvent('wheel',{bubbles:true,cancelable:true,deltaY:-120});
      input.dispatchEvent(wheel);return wheel.defaultPrevented&&input.value==='4';
    })()""",
    )


def test_settings_save_fits_available_screen(qtbot):
    dialog = SettingsDialog(Settings(), secret_values={})
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.wait(20)
    available = dialog.screen().availableGeometry()
    assert available.contains(dialog.frameGeometry())
    buttons = dialog.findChild(QDialogButtonBox)
    save = buttons.button(QDialogButtonBox.StandardButton.Save)
    assert available.contains(save.mapToGlobal(save.rect().bottomRight()))


def test_settings_uses_short_work_area_above_taskbar(qtbot, monkeypatch):
    from types import SimpleNamespace

    from PySide6.QtCore import QRect

    area = QRect(0, 0, 1366, 640)
    monkeypatch.setattr(
        SettingsDialog, "screen", lambda self: SimpleNamespace(availableGeometry=lambda: area)
    )
    dialog = SettingsDialog(Settings(), secret_values={})
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.wait(20)
    assert dialog.height() <= area.height() - 60
    buttons = dialog.findChild(QDialogButtonBox)
    save = buttons.button(QDialogButtonBox.StandardButton.Save)
    assert dialog.rect().contains(save.mapTo(dialog, save.rect().bottomRight()))
