from pathlib import Path

import httpx
import pytest
import requests

from tests.fake_qbit import FakeQbit
from torrentlinker.domain import LibraryFolder, Torrent
from torrentlinker.library import build_library, indexer_contents
from torrentlinker.store import Store

URL = "https://c411.org/api/torznab"


@pytest.mark.parametrize("error_type", [TimeoutError, httpx.ReadTimeout, requests.ReadTimeout])
@pytest.mark.parametrize("operation", ["torrents", "files"])
def test_scan_retries_only_the_client_read_that_timed_out(tmp_path, error_type, operation):
    (tmp_path / "book.epub").write_bytes(b"book")
    client = FakeQbit(
        by_hash={
            "a": Torrent(
                "a", "book.epub", tmp_path, {"book.epub": 4}, tracker="https://c411.org/announce"
            )
        }
    )
    original = getattr(client, operation)
    calls = []

    def sometimes(*args, **kwargs):
        calls.append(True)
        if len(calls) == 1:
            raise error_type("timed out")
        return original(*args, **kwargs)

    setattr(client, operation, sometimes)
    store = Store(tmp_path / "state.db")
    torrents = indexer_contents(client, store, URL)
    entries = build_library([LibraryFolder(tmp_path, depth=5)], torrents)
    assert any(e.item.path.name == "book.epub" and e.state.value == "seeded" for e in entries)
    assert len(calls) == 2


@pytest.mark.parametrize("operation", ["torrents", "files"])
def test_persistent_client_timeout_identifies_operation_and_does_not_return_partial_data(
    tmp_path, operation
):
    client = FakeQbit(
        by_hash={"a": Torrent("a", "book.epub", tmp_path, tracker="https://c411.org/announce")}
    )
    calls = []

    def timeout(*args, **kwargs):
        calls.append(True)
        raise httpx.ReadTimeout("timed out https://user:secret@client/private")

    setattr(client, operation, timeout)
    with pytest.raises(TimeoutError) as error:
        indexer_contents(client, Store(tmp_path / "s.db"), URL)
    assert "Torrent Client" in str(error.value)
    assert ("book.epub" if operation == "files" else "torrent list") in str(error.value)
    assert "secret" not in str(error.value)
    assert len(calls) == 2


def test_authentication_failure_is_not_retried(tmp_path):
    client = FakeQbit()
    calls = []

    def denied(**kwargs):
        calls.append(True)
        raise ValueError("login refused")

    client.torrents = denied
    with pytest.raises(ValueError, match="login refused"):
        indexer_contents(client, Store(tmp_path / "s.db"), URL)
    assert len(calls) == 1


def test_folder_timeout_identifies_folder_without_retry(tmp_path, monkeypatch):
    def timeout(*args):
        raise TimeoutError("timed out")

    monkeypatch.setattr(Path, "iterdir", timeout)
    result = build_library([LibraryFolder(tmp_path, depth=5)], [])
    assert result == []
    assert len(result.errors) == 1
    assert result.errors[0].path == tmp_path
    assert "timed out" in result.errors[0].message


def test_qbittorrent_wrapped_timeout_is_retried(tmp_path):
    from qbittorrentapi.exceptions import APIConnectionError

    client = FakeQbit()
    calls = []

    def wrapped(**kwargs):
        calls.append(True)
        if len(calls) == 1:
            try:
                raise requests.ReadTimeout("timed out")
            except requests.ReadTimeout:
                raise APIConnectionError("connection failed")  # noqa: B904 - matches the adapter
        return []

    client.torrents = wrapped
    assert indexer_contents(client, Store(tmp_path / "s.db"), URL) == []
    assert len(calls) == 2


def test_scan_timeout_still_scans_files_with_unknown_state(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from torrentlinker.config import Settings
    from torrentlinker.domain import ItemState, LocalItem
    from torrentlinker.gui import main_window
    from torrentlinker.library import LibraryEntry

    root = tmp_path / "Books"
    root.mkdir()
    (root / "old.epub").write_bytes(b"x" * 10)
    folder = LibraryFolder(root, depth=5)
    window = main_window.MainWindow(
        Settings(library_folders=[folder]), tmp_path / "settings.json", Store(tmp_path / "s.db")
    )
    qtbot.addWidget(window)
    previous = [
        LibraryEntry(folder, LocalItem(root / "old.epub", {"old.epub": 10}), ItemState.SEEDED)
    ]
    window.library_model.set_entries(previous)
    client = FakeQbit()

    def timeout(**kwargs):
        raise httpx.ReadTimeout("timed out")

    client.torrents = timeout
    monkeypatch.setattr(window, "qbit", lambda: client)
    messages = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: messages.append(args[2]))
    window.scan()
    qtbot.waitUntil(lambda: bool(messages))
    assert "torrent list" in messages[0]
    assert "Settings" in messages[0]
    assert [e.item for e in window.library_model.entries] == [e.item for e in previous]
    assert window.library_model.entries[0].state is ItemState.UNKNOWN
    assert window.scan_action.isEnabled()
    assert window.rescan_action.isEnabled()
    assert window.add_folder_action.isEnabled()


@pytest.mark.parametrize("depth", [1, 5])
@pytest.mark.parametrize("failure", ["http", "rpc"])
def test_deluge_scan_recovers_from_transport_or_daemon_timeout(tmp_path, depth, failure):
    import json

    from tests.test_deluge_unit import FakeWebUi
    from torrentlinker.deluge import DelugeApi

    web = FakeWebUi()
    attempts = []

    def handler(request):
        body = json.loads(request.content)
        if body["method"] == "core.get_torrents_status":
            attempts.append(True)
            if len(attempts) == 1:
                if failure == "http":
                    raise httpx.ReadTimeout("timed out", request=request)
                return web._reply(body, None, {"message": "timed out", "code": 4})
        return web.handler(request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        client = DelugeApi("http://deluge.test", "secret", http=http)
        folder = tmp_path / "books"
        nested = folder / "a" / "b" / "c" / "d"
        nested.mkdir(parents=True)
        (nested / "book.epub").write_bytes(b"book")
        torrents = indexer_contents(client, Store(tmp_path / "s.db"), URL)
        entries = build_library([LibraryFolder(folder, depth=depth)], torrents)
        assert sum(len(e.item.files) for e in entries) == 1
        assert len(attempts) == 2
