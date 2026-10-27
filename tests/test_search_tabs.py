import httpx
from PySide6.QtCore import Qt

from tests.fake_qbit import FakeQbit
from tests.test_download_queue import setup_queue
from tests.test_torrent_details import DETAILS
from tests.test_torrent_search import fake_indexer
from torrentlinker.config import Settings
from torrentlinker.download_queue import enqueue, entries, queue_key
from torrentlinker.gui.search_view import SearchTab
from torrentlinker.gui.torrent_details import TorrentDetailsDialog
from torrentlinker.indexer import Candidate, Indexer
from torrentlinker.store import Store


def make_view(qtbot, tmp_path):
    store = Store(tmp_path / "state.db")
    indexer = Indexer("https://example.test/api", "key")
    settings = Settings()
    settings.download_folders.default = str(tmp_path)
    view = SearchTab(store, settings, lambda: indexer, FakeQbit)
    qtbot.addWidget(view)
    rows = [
        Candidate(name, i + 1, f"https://example.test/{i}", 2, f"{i:040x}")
        for i, name in enumerate(["A", "B", "C"], 1)
    ]
    view._show_results(rows, indexer)
    return view, rows, indexer


def test_double_click_opens_correct_sorted_result_and_reuses_its_tab(qtbot, tmp_path):
    view, rows, indexer = make_view(qtbot, tmp_path)
    view.query.setText("My search")
    view.results.sortItems(0, Qt.SortOrder.DescendingOrder)
    view.results.itemDoubleClicked.emit(view.results.item(0, 1))
    page = view.browser.currentWidget()
    assert isinstance(page, TorrentDetailsDialog) and page.candidate == rows[2]
    assert not page.isWindow()
    view.open_details(rows[2])
    assert view.browser.count() == 2
    page.folder.setText(str(tmp_path / "chosen"))
    view.focus_search()
    assert view.browser.currentWidget() is view.home
    assert view.query.text() == "My search" and view.results.item(0, 0).text() == "C"
    view.open_details(rows[2])
    assert view.browser.currentWidget().folder.text() == str(tmp_path / "chosen")


def test_search_visible_on_startup_and_after_closing_all_previews(qtbot, tmp_path):
    view, rows, _ = make_view(qtbot, tmp_path)
    view.resize(1100, 800)
    view.show()
    qtbot.waitExposed(view)
    assert view.home.isVisible()
    assert view.query.isVisible() and view.search_button.isVisible()
    assert view.browser.home_button.isVisible()
    view.query.setText("Keep my search")
    for candidate in rows:
        view.open_details(candidate)
    view.browser.home_button.click()
    assert view.query.isVisible()
    view.open_details(rows[-1])
    view.browser.close_others(view.home)
    assert view.home.isVisible() and view.query.isVisible()
    assert view.query.text() == "Keep my search"
    # Switching sidebar pages must not hide the only remaining browser page.
    view.hide()
    view.show()
    assert view.query.isVisible() and view.search_button.isVisible()


def test_tab_close_reorder_and_list_preserve_home_and_queue_only_open_torrents(qtbot, tmp_path):
    view, rows, indexer = make_view(qtbot, tmp_path)
    for candidate in rows:
        view.open_details(candidate)
    removed = view.browser.widget(2)
    view.browser.request_close(2)
    assert removed._closed
    view.browser.tabBar().moveTab(2, 0)
    view.browser.request_close(view.browser.indexOf(view.home))
    assert view.browser.count() == 3
    view.browser._fill_tab_menu()
    assert [a.text() for a in view.browser.tab_menu.actions() if not a.isSeparator()][:3] == [
        "C",
        "Search",
        "A",
    ]
    view.browser.tab_menu.actions()[1].trigger()
    assert view.browser.currentWidget() is view.home
    view._show_results([Candidate("Another search", 1, "url", infohash="f" * 40)], indexer)
    view.queue_tabs.trigger()
    assert [entry.candidate for entry in entries(view.store)] == [rows[2], rows[0]]
    assert view.runner is None
    view.queue_tabs.trigger()
    assert len(entries(view.store)) == 2
    view.browser.close_others(view.home)
    assert view.browser.count() == 1 and not view._detail_tabs
    assert not view.queue_tabs.isEnabled() and not view.download_tabs.isEnabled()
    assert len(entries(view.store)) == 2  # Closing a tab never removes queued torrents.


def test_batch_validates_every_folder_before_adding_anything(qtbot, tmp_path):
    view, rows, _ = make_view(qtbot, tmp_path)
    view.open_details(rows[0])
    view.open_details(rows[1])
    bad = view.browser.currentWidget()
    bad.folder.setText(str(tmp_path / "missing"))
    view.queue_open_tabs(False)
    assert entries(view.store) == []
    assert view.browser.currentWidget() is bad
    assert "accessible" in bad.action_status.text()
    assert "Could not queue tabs" in view.queue_notice.text()
    assert "accessible" in view.queue_notice.text()


def test_queue_all_opens_visible_queue_without_starting_downloads(qtbot, tmp_path):
    view, rows, _ = make_view(qtbot, tmp_path)
    view.resize(1100, 800)
    view.show()
    for candidate in rows:
        view.open_details(candidate)
    view.focus_search()
    view.queue_tabs.trigger()
    assert len(entries(view.store)) == 3
    assert view.queue.isVisible()
    assert view.queue.rowCount() == 3 and view.start.isVisible()
    assert view.runner is None
    assert "3 added" in view.queue_status.text()
    assert view.view_queue.text() == "Download queue (3)"
    view.open_details(rows[0])
    assert view.view_queue.isVisible()
    view.view_queue.click()
    assert view.queue.isVisible() and view.queue.rowCount() == 3
    view.browser.close_others(view.home)
    view.focus_search()
    view.view_queue.click()
    assert view.queue.isVisible() and view.queue.rowCount() == 3


def test_batch_rejects_missing_download_link_before_partial_queue(qtbot, tmp_path):
    view, rows, indexer = make_view(qtbot, tmp_path)
    view.open_details(rows[0])
    view.open_details(Candidate("No link", 1, "", infohash="f" * 40))
    view.queue_open_tabs(True)
    assert entries(view.store) == []
    assert "no download link" in view.browser.currentWidget().action_status.text()


def test_download_all_tabs_leaves_unrelated_queue_entries_waiting(qtbot, tmp_path):
    from tests.test_send import release
    from torrentlinker.torrent_meta import read_torrent

    store, indexer, client, c, data, folder = setup_queue(tmp_path)
    data2 = release(tmp_path, "Film.2026")
    meta2 = read_torrent(data2)
    second = Candidate(meta2.name, 5001, "https://example.test/second", 2, meta2.infohash)
    indexer._http = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, content=data2 if request.url.path == "/second" else data
            )
        )
    )
    other = Candidate("Unrelated", 100, "https://example.test/other", 1, "f" * 40)
    enqueue(store, indexer, other, folder)
    settings = Settings()
    settings.download_folders.default = str(folder)
    view = SearchTab(store, settings, lambda: indexer, lambda: client)
    qtbot.addWidget(view)
    view._show_results([c, second, other], indexer)
    view.open_details(c)
    view.open_details(second)
    view.focus_search()
    view.download_tabs.trigger()
    qtbot.waitUntil(lambda: view.runner is None)
    assert client.downloads == [c.infohash, second.infohash]
    states = {entry.candidate.infohash: entry.status for entry in entries(store)}
    assert states[c.infohash] == states[second.infohash] == "sent"
    assert states[other.infohash] == "queued"
    assert view.browser.currentWidget() is view.home and view.pages.currentIndex() == 1
    assert len(view._detail_tabs) == 2
    view.queue_open_tabs(True)
    assert view.runner is None and client.downloads == [c.infohash, second.infohash]


def test_closed_tab_ignores_pending_metadata_and_can_be_reopened(qtbot, tmp_path, monkeypatch):
    from torrentlinker.torrent_details import parse_details

    jobs = []
    monkeypatch.setattr(
        "torrentlinker.gui.torrent_details.run_in_background",
        lambda work, done, failed: jobs.append((work, done, failed)),
    )
    view, rows, _ = make_view(qtbot, tmp_path)
    indexer = fake_indexer(lambda r: httpx.Response(200, json=DETAILS))
    view._show_results(rows, indexer)
    view.open_details(rows[0])
    page = view.browser.currentWidget()
    view.close_detail(page)
    jobs.pop()[1](parse_details(DETAILS))
    assert not jobs and view.browser.count() == 1
    view.open_details(rows[0])
    assert view.browser.currentWidget() is not page
    view.close_detail(view.browser.currentWidget())
    jobs.pop()[2](ValueError("late failure"))
    assert view.browser.count() == 1


def test_close_other_tabs_keeps_target_and_home(qtbot, tmp_path):
    view, rows, indexer = make_view(qtbot, tmp_path)
    for candidate in rows:
        view.open_details(candidate)
    keep = view._detail_tabs[queue_key(indexer, rows[1])]
    view.browser.close_others(keep)
    assert view.browser.count() == 2
    assert list(view._detail_tabs.values()) == [keep]
    keep.reject()  # The embedded Close/Escape action closes its tab.
    assert view.browser.count() == 1


def test_browser_shortcuts_and_middle_click_close_inside_search(qtbot, tmp_path):
    view, rows, _ = make_view(qtbot, tmp_path)
    view.resize(1100, 800)
    view.show()
    for candidate in rows[:2]:
        view.open_details(candidate)
    view.activateWindow()
    view.browser.currentWidget().folder.setFocus()
    qtbot.waitUntil(lambda: view.browser.currentWidget().folder.hasFocus())
    qtbot.keyClick(
        view.browser.currentWidget().folder, Qt.Key.Key_W, Qt.KeyboardModifier.ControlModifier
    )
    assert view.browser.count() == 2
    bar = view.browser.tabBar()
    qtbot.mouseClick(bar, Qt.MouseButton.MiddleButton, pos=bar.tabRect(1).center())
    assert view.browser.count() == 1
    view.query.setFocus()
    qtbot.keyClick(view.query, Qt.Key.Key_W, Qt.KeyboardModifier.ControlModifier)
    assert view.browser.count() == 1
