from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QMessageBox

from tests.fake_qbit import FakeQbit
from tests.torrents import make_torrent
from torrentlinker.domain import ItemState, LibraryFolder
from torrentlinker.gui.review_panel import ReviewPanel
from torrentlinker.indexer import Candidate
from torrentlinker.library import LibraryEntry
from torrentlinker.matching import MatchRules
from torrentlinker.qbit import AlreadyInClient
from torrentlinker.review import check_candidate
from torrentlinker.scan import scan_item
from torrentlinker.store import Store


@pytest.mark.parametrize("state,progress", [("stalledUP", 1.0), ("missingFiles", 0.0)])
@pytest.mark.parametrize("added_during_reseed", [False, True])
def test_existing_torrent_is_explained_without_mutating_it(
    qtbot, tmp_path: Path, monkeypatch, state, progress, added_during_reseed
):
    path = tmp_path / "movie.mkv"
    path.write_bytes(b"movie" * 4000)
    data = make_torrent(path)
    item = scan_item(path)
    indexer = SimpleNamespace(fetch_torrent=lambda c: data)
    checked = check_candidate(indexer, item, Candidate("Movie", item.size, "u"), MatchRules())
    client = FakeQbit()
    h = client.add(data, str(tmp_path / "old-location"), [])
    client._set(h, state=state, progress=progress)
    before = client.torrent(h)
    if added_during_reseed:
        client.by_hash.pop(h)

        def concurrent_add(*args):
            client.by_hash[h] = before
            raise AlreadyInClient()

        monkeypatch.setattr(client, "add", concurrent_add)
    store = Store(tmp_path / "state.db")
    panel = ReviewPanel(
        store, lambda: indexer, lambda: client, MatchRules, lambda: None, lambda e: ""
    )
    qtbot.addWidget(panel)
    entry = LibraryEntry(LibraryFolder(tmp_path), item, ItemState.ORPHAN)
    panel.remember(entry, [checked])
    panel.set_entry(entry)
    panel.candidates.selectRow(0)
    messages, errors = [], []
    monkeypatch.setattr(QMessageBox, "information", lambda _, title, text: messages.append(text))
    monkeypatch.setattr(QMessageBox, "warning", lambda _, title, text: errors.append(text))

    panel.reseed_button.click()
    qtbot.waitUntil(lambda: bool(messages or errors))

    assert not errors
    assert "already" in messages[0].lower()
    assert h in messages[0] and state in messages[0]
    assert str(tmp_path / "old-location") in messages[0]
    assert ("already seeding" in messages[0].lower()) == (progress == 1.0)
    assert client.torrent(h) == before
    assert client.started == [] and client.removed == [] and client.calls == []
    assert store.verification_hashes() == []
    assert panel.reseed_button.isEnabled()
