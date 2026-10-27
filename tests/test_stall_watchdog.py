import logging
import time

from PySide6.QtCore import QObject, QTimer

from torrentlinker.gui.stall_watchdog import StallWatchdog, install


def slow_database_call():
    time.sleep(0.12)


def test_stall_is_logged_with_the_gui_stack(qtbot, caplog):
    parent = QObject()
    watchdog = StallWatchdog(40, parent)
    qtbot.wait(60)
    caplog.set_level(logging.WARNING, logger="torrentlinker.stall")
    QTimer.singleShot(0, slow_database_call)
    qtbot.wait(400)
    watchdog.running = False
    messages = [r.getMessage() for r in caplog.records]
    assert any("stalled" in m and "slow_database_call" in m for m in messages)


def test_quick_ticks_log_nothing(qtbot, caplog):
    parent = QObject()
    watchdog = StallWatchdog(200, parent)
    caplog.set_level(logging.WARNING, logger="torrentlinker.stall")
    qtbot.wait(300)
    watchdog.running = False
    assert not [r for r in caplog.records if "stalled" in r.getMessage()]


def test_off_unless_asked(monkeypatch):
    monkeypatch.delenv("TORRENTLINKER_STALL_MS", raising=False)
    assert install(QObject()) is None
    monkeypatch.setenv("TORRENTLINKER_STALL_MS", "nope")
    assert install(QObject()) is None
