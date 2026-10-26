"""Media storage closes with its owning server, including failed startup."""

import sqlite3

import pytest

from torrentlinker.media import MediaLibrary


@pytest.fixture
def media_connections(monkeypatch):
    connections = []
    original = MediaLibrary.__init__

    def track(self, *args, **kwargs):
        original(self, *args, **kwargs)
        connections.append(self.db)

    monkeypatch.setattr(MediaLibrary, "__init__", track)
    return connections


def assert_closed(connections):
    assert connections
    for connection in connections:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connection.execute("SELECT 1")


def test_packaged_smoke_releases_media_storage(media_connections):
    from torrentlinker.app import agent_smoke_checks

    agent_smoke_checks()
    assert_closed(media_connections)


def test_failed_desktop_startup_releases_media_storage(tmp_path, monkeypatch, media_connections):
    import uvicorn

    from torrentlinker.agent.desktop import DesktopServer
    from torrentlinker.config import Settings
    from torrentlinker.store import Store

    def invalid_config(*args, **kwargs):
        raise RuntimeError("Test server configuration failure")

    monkeypatch.setattr(uvicorn, "Config", invalid_config)
    store = Store(tmp_path / "state.db")
    server = DesktopServer(Settings(), tmp_path / "settings.json", store, port=0)
    try:
        with pytest.raises(RuntimeError, match="configuration failure"):
            server.start()
        assert_closed(media_connections)
    finally:
        for connection in media_connections:
            connection.close()
        store._db.close()
