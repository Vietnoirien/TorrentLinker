from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMenu

from tests.test_search_page import make_rich_view
from tests.test_search_tabs import make_view
from torrentlinker.download_queue import enqueue, entries
from torrentlinker.downloads import IndexerCategory


def test_add_selected_from_comfortable_results_opens_queue(qtbot, tmp_path, monkeypatch):
    view, _ = make_rich_view(qtbot, tmp_path, monkeypatch)
    view.set_density("comfortable")
    view.results.selectRow(1)
    selected = view.selected_results()
    assert len(selected) == 1
    qtbot.mouseClick(view.add_button, Qt.MouseButton.LeftButton)
    assert [e.candidate.infohash for e in entries(view.store)] == [c.infohash for c in selected]
    assert view.queue.isVisible()


def test_header_counts_sent_rows_that_remain_visible(qtbot, tmp_path):
    view, rows, indexer = make_view(qtbot, tmp_path)
    for candidate in rows:
        enqueue(view.store, indexer, candidate, tmp_path)
    for entry in entries(view.store):
        view.store.download_outcome(entry.key, "sent")
    view.refresh_queue()
    assert view.queue.rowCount() == 3
    assert view.view_queue.text() == "Download queue (3)"
    assert not view.start.isEnabled()
    assert "3 sent" in view.queue_summary.text()


def test_queue_has_a_management_context_menu(qtbot, tmp_path):
    view, _, _ = make_view(qtbot, tmp_path)
    assert view.queue.contextMenuPolicy() == Qt.ContextMenuPolicy.CustomContextMenu


def test_missing_folder_feedback_stays_visible_and_nothing_is_queued(qtbot, tmp_path, monkeypatch):
    view, _ = make_rich_view(qtbot, tmp_path, monkeypatch)
    view.resize(1100, 600)
    view.settings.download_folders.default = ""
    view.results.selectRow(0)
    qtbot.mouseClick(view.add_button, Qt.MouseButton.LeftButton)
    qtbot.wait(20)
    assert "Download Folder" in view.result_status.text()
    assert view.rect().contains(view.result_status.mapTo(view, view.result_status.rect().center()))
    assert not entries(view.store)
    assert view.results.isVisible()
    view.folder.setText(str(tmp_path))
    qtbot.mouseClick(view.add_button, Qt.MouseButton.LeftButton)
    assert len(entries(view.store)) == 1
    assert view.queue.isVisible()


def test_duplicate_add_opens_existing_queue_without_another_entry(qtbot, tmp_path):
    view, rows, _ = make_view(qtbot, tmp_path)
    view._add_candidates(rows[:1])
    view.show_results()
    view._add_candidates(rows[:1])
    assert len(entries(view.store)) == 1
    assert "0 added" in view.queue_status.text()
    assert "1 already listed" in view.queue_status.text()
    assert view.pages.currentIndex() == 1


def test_context_menu_targets_sorted_row_and_removes_only_that_entry(qtbot, tmp_path, monkeypatch):
    view, rows, _ = make_view(qtbot, tmp_path)
    view._add_candidates(rows)
    view.queue.sortItems(0, Qt.SortOrder.DescendingOrder)
    view.queue.selectRow(2)
    target = view.queue.item(0, 0)
    key = target.data(Qt.ItemDataRole.UserRole)

    class Menu(QMenu):
        def exec(self, position):
            assert view.selected_keys() == [key]
            actions = {action.text(): action for action in self.actions()}
            assert actions["Start selected"].isEnabled()
            assert not actions["Retry selected"].isEnabled()
            actions["Remove selected"].trigger()

    monkeypatch.setattr("torrentlinker.gui.search_view.QMenu", Menu)
    view._queue_context_menu(view.queue.visualItemRect(target).center())
    assert key not in {e.key for e in entries(view.store)}
    assert len(entries(view.store)) == 2


def test_retry_preserves_uncertain_and_unsafe_entries(qtbot, tmp_path):
    view, rows, _ = make_view(qtbot, tmp_path)
    view._add_candidates(rows)
    first, second, third = entries(view.store)
    view.store.download_outcome(first.key, "failed", retry_safe=True)
    view.store.download_outcome(second.key, "failed", retry_safe=False)
    view.store.download_outcome(third.key, "uncertain")
    view.refresh_queue()
    view.queue.selectAll()
    assert view.retry.isEnabled()
    view.retry.click()
    assert {e.key: e.status for e in entries(view.store)} == {
        first.key: "queued",
        second.key: "failed",
        third.key: "uncertain",
    }
    assert not view.retry.isEnabled()


def test_uncertain_download_explains_reconciliation_and_removes_only_local_record(qtbot, tmp_path):
    view, rows, _ = make_view(qtbot, tmp_path)
    source = tmp_path / "kept.bin"
    source.write_bytes(b"Keep the source files")
    view._add_candidates(rows[:1])
    entry = entries(view.store)[0]
    view.store.download_outcome(entry.key, "uncertain", "Check the Torrent Client")
    view.refresh_queue()
    view.queue.selectRow(0)
    assert "Check Torrent Client before retrying" in view.queue.item(0, 5).text()
    assert "1 need attention" in view.queue_summary.text()
    assert not view.retry.isEnabled()
    assert not view.start.isEnabled()

    def no_client_call():
        raise AssertionError("Local reconciliation must not contact the Torrent Client")

    view.client = no_client_call
    view.remove.click()
    assert entries(view.store) == []
    assert source.read_bytes() == b"Keep the source files"
    assert not view.remove.isEnabled()


def test_animation_series_explains_its_missing_folder_without_using_tv_folder(qtbot, tmp_path):
    view, rows, _ = make_view(qtbot, tmp_path)
    view.settings.download_folders.default = ""
    view.settings.download_folders.by_category = {5000: str(tmp_path)}
    view.settings.indexer_categories = {
        2000: IndexerCategory("Films & Vidéos"),
        5000: IndexerCategory("Série TV", 2000),
        5070: IndexerCategory("Animation Série", 2000),
    }
    candidate = replace(rows[0], categories=(2000, 5070))
    view._add_candidates([candidate])
    assert "Animation Série" in view.result_status.text()
    assert not entries(view.store)
    view.folder.setText(str(tmp_path))
    view._add_candidates([candidate])
    assert entries(view.store)[0].folder == tmp_path
