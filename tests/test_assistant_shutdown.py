"""Provider probes run outside the Assistant executor and must not race DB close."""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from torrentlinker.assistant.providers import Provider
from torrentlinker.web.app import create_app


def test_close_does_not_close_database_during_provider_assessment_write(tmp_path, monkeypatch):
    app = create_app(tmp_path, password="test-password-long", monitor_verifications=False)
    assistant = app.state.assistant
    agent = app.state.agent_service
    saved = assistant.save_provider(Provider(name="Fixture", kind="ollama", model="fixture"))
    monkeypatch.setattr("torrentlinker.assistant.capabilities.assess", lambda *a: {"checks": {}})
    monkeypatch.setattr(assistant.models, "context", lambda *a: {"context_window": 4096})
    entered = threading.Event()
    release = threading.Event()
    close_attempted = threading.Event()
    connection = assistant.db

    class Gate:
        def execute(self, sql, *args):
            if sql.startswith("INSERT OR REPLACE INTO options"):
                entered.set()
                assert release.wait(5)
            return connection.execute(sql, *args)

        def __enter__(self):
            connection.__enter__()
            return self

        def __exit__(self, *args):
            return connection.__exit__(*args)

        def close(self):
            close_attempted.set()
            # Observe the unsafe close without racing native SQLite in regression
            # runs. The real connection is closed after both threads join below.

    assistant.db = Gate()
    try:
        with ThreadPoolExecutor(max_workers=2) as workers:
            probe = workers.submit(assistant.test_provider, saved["id"])
            assert entered.wait(5)
            closing = workers.submit(assistant.close)
            assert assistant.shutdown.wait(5)
            try:
                assert not close_attempted.wait(0.1), "Database close raced the assessment write"
            finally:
                release.set()
            probe.result(timeout=5)
            closing.result(timeout=5)
            assert close_attempted.is_set()
    finally:
        release.set()
        connection.close()
        agent.jobs.close()
        agent.media.close()
        agent.access.db.close()
        agent.setup.store._db.close()


def test_assessment_returning_after_shutdown_does_not_touch_closed_database(tmp_path, monkeypatch):
    app = create_app(tmp_path, password="test-password-long", monitor_verifications=False)
    assistant = app.state.assistant
    agent = app.state.agent_service
    saved = assistant.save_provider(Provider(name="Fixture", kind="ollama", model="fixture"))
    entered = threading.Event()
    release = threading.Event()
    monkeypatch.setattr("torrentlinker.assistant.capabilities.assess", lambda *a: {"checks": {}})

    def context(*args):
        entered.set()
        assert release.wait(5)
        return {"context_window": 4096}

    monkeypatch.setattr(assistant.models, "context", context)
    try:
        with ThreadPoolExecutor(max_workers=1) as workers:
            probe = workers.submit(assistant.test_provider, saved["id"])
            assert entered.wait(5)
            assistant.close()
            release.set()
            with pytest.raises(ValueError, match="shutting down"):
                probe.result(timeout=5)
            with pytest.raises(ValueError, match="shutting down"):
                assistant.test_provider(saved["id"])
    finally:
        release.set()
        agent.jobs.close()
        agent.media.close()
        agent.access.db.close()
        agent.setup.store._db.close()


@pytest.mark.parametrize("deleted", [False, True])
def test_late_provider_ui_callbacks_are_ignored(qtbot, monkeypatch, deleted):
    from types import SimpleNamespace

    from shiboken6 import delete

    from torrentlinker.gui.assistant_connections import AssistantConnections

    widget = AssistantConnections(lambda: None)
    if not deleted:
        qtbot.addWidget(widget)
    widget.service = SimpleNamespace(closed=True)
    monkeypatch.setattr(
        "torrentlinker.gui.assistant_connections.QMessageBox.warning",
        lambda *a: pytest.fail("Late shutdown error opened a dialog"),
    )
    if deleted:
        delete(widget)
    widget._notify("Late result")
    widget.error(ValueError("Assistant is shutting down."))
