from dataclasses import replace

from PySide6.QtCore import Qt

from tests.fake_qbit import FakeQbit
from tests.test_download_queue import setup_queue
from torrentlinker.config import ClientProfile, Settings
from torrentlinker.download_queue import enqueue, entries
from torrentlinker.gui.search_view import SearchTab
from torrentlinker.indexer import Candidate, Indexer
from torrentlinker.store import Store


def test_sorted_search_queues_the_selected_torrent_and_remembers_it(qtbot, tmp_path):
    store = Store(tmp_path / "state.db")
    indexer = Indexer("https://example.test/api", "key")
    settings = Settings()
    settings.download_folders.default = str(tmp_path)
    view = SearchTab(store, settings, lambda: indexer, FakeQbit)
    qtbot.addWidget(view)
    a = Candidate("A large", 1024**3, "https://example.test/a", 10, "a" * 40)
    z = Candidate("Z small", 9 * 1024**2, "https://example.test/z", 2, "b" * 40)
    view._show_results([a, z], indexer)
    view.results.sortItems(1, Qt.SortOrder.AscendingOrder)
    view.results.selectRow(0)
    assert view.selected_results() == [z]
    view.add_button.click()
    assert [e.candidate.title for e in entries(store)] == [z.title]
    view.add_button.click()
    assert len(entries(store)) == 1
    view.queue.selectRow(0)
    view.remove.click()
    assert entries(store) == []


def test_search_runs_off_thread_with_category_and_fresh_paging(qtbot, tmp_path):
    from torrentlinker.downloads import IndexerCategory

    indexer = Indexer("https://example.test/api", "key")
    calls = []

    def search(query, cached=True):
        calls.append((query, cached))
        return [Candidate(str(n), n, "url" + str(n)) for n in range(100)]

    indexer.search = search
    settings = Settings(
        indexer_categories={2000: IndexerCategory("Movies"), 2030: IndexerCategory("Film", 2000)}
    )
    view = SearchTab(Store(tmp_path / "state.db"), settings, lambda: indexer, FakeQbit)
    qtbot.addWidget(view)
    view.query.setText("Ocean")
    view.category.select_category(2030)
    view.search_button.click()
    qtbot.waitUntil(lambda: not view._searching)
    assert calls[0][0].q == "Ocean" and calls[0][0].categories == (2030,)
    assert calls[0][1] is False
    view.next.click()
    qtbot.waitUntil(lambda: len(calls) == 2 and not view._searching)
    assert calls[1][0].offset == 100
    assert view.previous.isEnabled()


def test_publication_column_sorts_by_timestamp_and_queue_preserves_date(
    qtbot, tmp_path, monkeypatch
):
    from PySide6.QtCore import QDateTime

    from torrentlinker.indexer import publication_time

    now = publication_time("2026-10-23T03:00:00Z")
    monkeypatch.setattr("torrentlinker.gui.search_view.time.time", lambda: now)
    store = Store(tmp_path / "dated.db")
    indexer = Indexer("https://example.test/api", "key")
    settings = Settings()
    settings.download_folders.default = str(tmp_path)
    view = SearchTab(store, settings, lambda: indexer, FakeQbit)
    qtbot.addWidget(view)
    view.show()
    old = Candidate("Old", 1, "old", published_at=publication_time("2026-10-22T23:30:00Z"))
    new = Candidate("New", 1, "new", published_at=publication_time("2026-10-23T01:00:00Z"))
    unknown = Candidate("Unknown", 1, "unknown")
    view._show_results([old, new, unknown], indexer)
    assert view.results.item(2, 7).text() == "–"
    view.results.sortItems(7, Qt.SortOrder.DescendingOrder)
    assert [view.results.item(i, 0).text() for i in range(3)] == ["New", "Old", "Unknown"]
    assert new.published_at is not None
    expected = QDateTime.fromMSecsSinceEpoch(round(new.published_at * 1000)).toLocalTime()
    assert view.results.item(0, 7).text() == "2 hours"
    assert view.results.item(1, 7).text() == "3 hours"
    assert view.results.item(0, 7).toolTip() == expected.toString("yyyy-MM-dd HH:mm:ss t")
    view.results.selectRow(0)
    view.add_selected()
    assert entries(store)[0].candidate.published_at == new.published_at
    assert now is not None
    now += 3600
    view.refresh_ages()
    assert view.results.item(0, 7).text() == "3 hours"
    assert view.selected_results() == [new]
    assert view.results.item(0, 7).data(Qt.ItemDataRole.UserRole) == new.published_at
    view.results.sortItems(7, Qt.SortOrder.AscendingOrder)
    assert [view.results.item(i, 0).text() for i in range(3)] == ["Unknown", "Old", "New"]


def test_queue_worker_and_restart_recovery(qtbot, tmp_path):
    store, indexer, client, c, data, folder = setup_queue(tmp_path)
    key = entries(store)[0].key
    store.download_outcome(key, "sending")
    store = Store(tmp_path / "state.db")
    view = SearchTab(store, Settings(), lambda: indexer, lambda: client)
    qtbot.addWidget(view)
    assert entries(store)[0].status == "uncertain"
    assert not view.start.isEnabled()
    assert "Check Torrent Client" in view.queue.item(0, 5).text()
    # After checking the client, the owner explicitly removes and queues it again.
    view.queue.selectRow(0)
    view.remove_selected()
    enqueue(store, indexer, c, folder)
    view.refresh_queue()
    assert entries(store)[0].status == "queued"
    assert not client.downloads
    view.start.click()
    qtbot.waitUntil(lambda: view.runner is None)
    assert client.downloads == [c.infohash]
    assert entries(store) == []
    assert view.queue.rowCount() == 0
    assert view.view_queue.text() == "Download queue (0)"
    assert not view.start.isEnabled()
    restored = SearchTab(store, Settings(), lambda: indexer, lambda: client)
    qtbot.addWidget(restored)
    assert restored.queue.rowCount() == 0
    assert not restored.start.isEnabled()
    restored.show()
    restored.view_queue.click()
    assert restored.queue.isVisible()


def test_search_zen_uses_profile_and_numeric_sort_and_website_uses_selected_identity(
    qtbot, tmp_path, monkeypatch
):
    import httpx

    from tests.test_torrent_search import fake_indexer
    from torrentlinker.zen import ZenClass, ZenProfile, ZenTorrent, added_values, note

    indexer = fake_indexer(lambda r: httpx.Response(200, json={}))
    settings = Settings(zen=ZenProfile(zen_class=ZenClass.SWARM_KEEPER, seed_hours=12))
    view = SearchTab(Store(tmp_path / "state.db"), settings, lambda: indexer, FakeQbit)
    qtbot.addWidget(view)
    rows = [
        Candidate("Large", 20 * 10**9, "download-a", 10, "a" * 40, categories=(2030,)),
        Candidate("Small", 10**9, "download-b", 5, "b" * 40, categories=(2030,)),
    ]
    view._show_results(rows, indexer)
    expected = added_values(
        settings.zen, [ZenTorrent(c.size, c.seeders + 1, category=2030) for c in rows]
    )
    for i, _row in enumerate(rows):
        assert view.results.item(i, 5).text() == f"≈ {expected[i]:.2f}"
        expected_note = note(
            settings.zen.zen_class, ZenTorrent(_row.size, _row.seeders + 1, category=2030)
        )
        assert view.results.item(i, 6).text() == f"≈ {expected_note:.2f}"
        assert view.results.item(i, 6).data(Qt.ItemDataRole.UserRole) == expected_note
    view.results.sortItems(5, Qt.SortOrder.AscendingOrder)
    view.results.selectRow(0)
    opened = []
    monkeypatch.setattr(
        "torrentlinker.gui.search_view.QDesktopServices.openUrl",
        lambda url: opened.append(url.toString()),
    )
    view.website_button.click()
    assert opened == ["https://c411.org/torrents/" + "b" * 40]
    assert view.selected_results() == [rows[1]]
    assert "Revival payouts are separate" in view.results.item(0, 5).toolTip()
    view.results.sortItems(6, Qt.SortOrder.AscendingOrder)
    view.results.clearSelection()
    view.results.selectRow(0)
    chosen_note = view.results.item(0, 6).text()
    view.show_details()
    assert f"Note: {chosen_note}" in view.browser.currentWidget().summary.text()


def test_search_existing_seeds_keep_their_current_estimate_after_sorting(qtbot, tmp_path):
    from types import SimpleNamespace

    import httpx

    from tests.test_torrent_search import fake_indexer
    from torrentlinker.seeding import Seeding, SeedingRow
    from torrentlinker.zen import ZenDay, ZenTorrent, note

    indexer = fake_indexer(lambda r: httpx.Response(200, json={}))
    view = SearchTab(Store(tmp_path / "state.db"), Settings(), lambda: indexer, FakeQbit)
    qtbot.addWidget(view)
    a = Candidate("A", 10**9, "a", 1, "a" * 40)
    b = Candidate("B", 2 * 10**9, "b", 2, "b" * 40)
    view._show_results([a, b], indexer)
    view.results.sortItems(0, Qt.SortOrder.DescendingOrder)
    active = [ZenTorrent(10**9, 2, 180)]
    view.set_seeding(Seeding([SeedingRow(SimpleNamespace(hash="a" * 40), 0.89)], ZenDay(), active))
    assert view.results.item(1, 0).text() == "A"
    assert view.results.item(1, 5).text() == "≈ 0.89"
    assert "Already seeding" in view.results.item(1, 5).toolTip()
    expected_note = note(view.settings.zen.zen_class, active[0])
    assert view.results.item(1, 6).text() == f"≈ {expected_note:.2f}"


def test_download_now_sends_only_open_torrent_and_keeps_others_queued(qtbot, tmp_path):
    from torrentlinker.download_queue import enqueue

    store, indexer, client, c, data, folder = setup_queue(tmp_path)
    other = Candidate("Other", 100, "https://example.test/other", 1, "f" * 40)
    enqueue(store, indexer, other, folder)
    view = SearchTab(store, Settings(), lambda: indexer, lambda: client)
    qtbot.addWidget(view)
    message = view.download_candidate(c, indexer, str(folder), True)
    assert "started" in message
    qtbot.waitUntil(lambda: view.runner is None)
    assert client.downloads == [c.infohash]
    states = {entry.candidate.infohash: entry.status for entry in entries(store)}
    assert states == {other.infohash: "queued"}


def test_add_from_details_does_not_start_queue_or_silently_change_folder(qtbot, tmp_path):
    import pytest

    store, indexer, client, c, data, folder = setup_queue(tmp_path)
    view = SearchTab(store, Settings(), lambda: indexer, lambda: client)
    qtbot.addWidget(view)
    assert view.download_candidate(c, indexer, str(folder), False) == "Already in the queue."
    assert client.downloads == []
    different = tmp_path / "other"
    different.mkdir()
    with pytest.raises(ValueError, match="already queued"):
        view.download_candidate(c, indexer, str(different), True)
    with pytest.raises(ValueError, match="accessible"):
        view.download_candidate(c, indexer, "", False)
    assert len(entries(store)) == 1 and entries(store)[0].folder == folder


def test_saved_queue_shows_zen_and_note_without_search_results(qtbot, tmp_path):
    from torrentlinker.download_queue import enqueue
    from torrentlinker.zen import ZenClass, ZenProfile, ZenTorrent, added_values, note

    store = Store(tmp_path / "queue-estimates.db")
    indexer = Indexer("https://c411.org/api", "key")
    candidate = Candidate("Queued", 10**9, "download", 5, "a" * 40, categories=(2030,))
    enqueue(store, indexer, candidate, tmp_path)
    settings = Settings(zen=ZenProfile(zen_class=ZenClass.SWARM_KEEPER, seed_hours=12))
    view = SearchTab(store, settings, lambda: indexer, FakeQbit)
    qtbot.addWidget(view)
    torrent = ZenTorrent(candidate.size, candidate.seeders + 1, category=2030)
    expected = added_values(settings.zen, [torrent])[0]
    assert view.queue.horizontalHeaderItem(2).text() == "≈ Zen/day"
    assert view.queue.item(0, 2).text() == f"≈ {expected:.2f}"
    assert view.queue.item(0, 3).text() == f"≈ {note(settings.zen.zen_class, torrent):.2f}"
    assert "Revival payouts are separate" in view.queue.item(0, 2).toolTip()
    view._show_results([candidate], indexer)
    for queue_column, result_column in ((2, 5), (3, 6)):
        queued = view.queue.item(0, queue_column)
        result = view.results.item(0, result_column)
        assert queued.text() == result.text()
        assert queued.toolTip() == result.toolTip()
        assert queued.data(Qt.ItemDataRole.UserRole) == result.data(Qt.ItemDataRole.UserRole)


def test_queue_estimates_refresh_with_profile_and_current_seeding_after_sorting(qtbot, tmp_path):
    from types import SimpleNamespace

    from torrentlinker.download_queue import enqueue
    from torrentlinker.seeding import Seeding, SeedingRow
    from torrentlinker.zen import ZenClass, ZenDay, ZenProfile, ZenTorrent, added_values, note

    store = Store(tmp_path / "refresh-queue.db")
    indexer = Indexer("https://c411.org/api", "key")
    small = Candidate("Small", 10**9, "small", 40, "a" * 40, categories=(2030,))
    large = Candidate("Large", 20 * 10**9, "large", 1, "b" * 40, categories=(2030,))
    for candidate in (small, large):
        enqueue(store, indexer, candidate, tmp_path)
    settings = Settings(zen=ZenProfile(zen_class=ZenClass.SWARM_KEEPER))
    view = SearchTab(store, settings, lambda: indexer, FakeQbit)
    qtbot.addWidget(view)
    view.queue.sortItems(2, Qt.SortOrder.DescendingOrder)
    assert view.queue.item(0, 0).text() == "Large"
    view.queue.selectRow(0)
    selected = view.selected_keys()
    previous = view.queue.item(0, 2).data(Qt.ItemDataRole.UserRole)
    settings.zen = replace(settings.zen, seed_hours=12)
    view.refresh_estimates()
    assert view.queue.item(0, 2).data(Qt.ItemDataRole.UserRole) == previous / 2
    assert view.selected_keys() == selected
    view.queue.sortItems(3, Qt.SortOrder.DescendingOrder)
    assert view.queue.item(0, 0).text() == "Large"
    # An already seeded torrent uses its observed swarm/age and current earnings.
    active = ZenTorrent(small.size, 2, 180, category=2030)
    view.set_seeding(
        Seeding([SeedingRow(SimpleNamespace(hash=small.infohash), 0.89)], ZenDay(), [active])
    )
    rows = {view.queue.item(i, 0).text(): i for i in range(2)}
    assert view.queue.item(rows["Small"], 2).text() == "≈ 0.89"
    assert "Already seeding" in view.queue.item(rows["Small"], 2).toolTip()
    assert view.queue.item(rows["Small"], 3).data(Qt.ItemDataRole.UserRole) == note(
        settings.zen.zen_class, active
    )
    expected = added_values(
        settings.zen, [ZenTorrent(large.size, large.seeders + 1, category=2030)], [active]
    )[0]
    assert view.queue.item(rows["Large"], 2).data(Qt.ItemDataRole.UserRole) == expected
    assert "count unavailable" not in view.queue.item(rows["Large"], 2).toolTip()
    assert view.selected_keys() == selected
    view.refresh_queue()
    assert view.selected_keys() == selected


def test_queue_estimates_use_saved_origin_when_current_indexer_changes(qtbot, tmp_path):
    from torrentlinker.download_queue import enqueue

    store = Store(tmp_path / "origins.db")
    c411 = Indexer("https://c411.org/api", "key")
    other = Indexer("https://other.test/api", "key")
    candidate = Candidate("C411", 10**9, "download", 3, "a" * 40)
    foreign = Candidate("Other", 10**9, "other", 3, "b" * 40)
    enqueue(store, c411, candidate, tmp_path)
    enqueue(store, other, foreign, tmp_path)
    view = SearchTab(store, Settings(), lambda: other, FakeQbit)
    qtbot.addWidget(view)
    view._show_results([foreign], other)
    view.refresh_estimates()
    view.queue.sortItems(2, Qt.SortOrder.DescendingOrder)
    assert view.queue.item(0, 0).text() == "C411"
    assert view.queue.item(0, 2).text().startswith("≈ ")
    assert view.queue.item(0, 3).text().startswith("≈ ")
    assert view.queue.item(1, 2).text() == "–"
    assert view.queue.item(1, 3).text() == "–"
    assert "available for c411" in view.queue.item(1, 2).toolTip()


def test_search_queue_tracks_external_writes(qtbot, tmp_path):
    from torrentlinker.download_queue import enqueue

    store = Store(tmp_path / "state.db")
    writer = Store(tmp_path / "state.db")
    indexer = Indexer("https://example.test/api", "key")
    view = SearchTab(store, Settings(), lambda: indexer, FakeQbit)
    qtbot.addWidget(view)
    view.show()
    candidate = Candidate("Added by Assistant", 1024, "https://example.test/a", 2, "a" * 40)
    enqueue(writer, indexer, candidate, tmp_path)
    qtbot.waitUntil(lambda: view.queue.rowCount() == 1, timeout=3000)
    assert view.queue.item(0, 0).text() == "Added by Assistant"
    view.queue.selectRow(0)
    selected = view.selected_keys()
    view.hide()
    enqueue(writer, indexer, replace(candidate, title="Second", infohash="b" * 40), tmp_path)
    view.show()
    assert view.queue.rowCount() == 2
    assert view.selected_keys() == selected
    writer.download_outcome(selected[0], "sent")
    qtbot.waitUntil(lambda: view.queue.item(0, 5).text() == "Sent to client", timeout=3000)
    assert view.selected_keys() == selected
    writer.remove_downloads(selected)
    qtbot.waitUntil(lambda: view.queue.rowCount() == 1, timeout=3000)
    assert view.queue.item(0, 0).text() == "Second"


def test_search_queue_poll_keeps_client_scope(qtbot, tmp_path):
    from torrentlinker.download_queue import enqueue

    store = Store(tmp_path / "state.db")
    writer = Store(tmp_path / "state.db")
    indexer = Indexer("https://example.test/api", "key")
    settings = Settings()
    settings.ensure_profiles()
    settings.client_profiles.append(ClientProfile("other", "Other"))
    view = SearchTab(store, settings, lambda: indexer, FakeQbit)
    qtbot.addWidget(view)
    view.show()
    candidate = Candidate("Other client", 1024, "https://example.test/a", 2, "a" * 40)
    enqueue(writer.for_client("other"), indexer, candidate, tmp_path)
    view._poll_queue()
    assert view.queue.rowCount() == 0
    view.store = store.for_client("other")
    view._poll_queue()
    assert view.queue.rowCount() == 1
    assert view.queue.item(0, 0).text() == "Other client"
