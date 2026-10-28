from dataclasses import replace
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, QSettings, Qt

from tests.fake_qbit import FakeQbit
from tests.test_qbit_unit import Synced, entry
from torrentlinker.category_tags import category_tag
from torrentlinker.domain import Torrent
from torrentlinker.downloads import IndexerCategory
from torrentlinker.gui.torrents_view import TorrentsTab
from torrentlinker.qbit import QbitApi
from torrentlinker.reseed import VERIFYING
from torrentlinker.torrent_management import (
    category_labels,
    manage,
    safe_error,
    status,
    torrent_categories,
    tracker_groups,
    tracker_hosts,
)


@pytest.fixture(autouse=True)
def isolated_table_settings(tmp_path, monkeypatch):
    settings = QSettings(str(tmp_path / "table.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr("torrentlinker.gui.torrents_view.QSettings", lambda: settings)
    return settings


def torrent(hash="a", **kwargs):
    return Torrent(hash, f"Torrent {hash}", Path("/seedbox/downloads"), **kwargs)


def test_tracker_identity_does_not_use_personal_tags_or_leak_passkeys():
    t = torrent(
        tags=frozenset({"c411"}), tracker="https://Elsewhere.EXAMPLE/secret/announce?k=pass"
    )
    assert tracker_hosts(t) == ("elsewhere.example",)
    assert tracker_hosts(torrent(tags=frozenset({"c411"}))) == ("",)
    t = replace(
        t,
        trackers=(
            "udp://second.example:6969/announce",
            "https://user:password@elsewhere.example/private",
            "https://[broken",
        ),
    )
    assert tracker_hosts(t) == ("elsewhere.example", "second.example")
    assert "secret" not in safe_error(RuntimeError("failed https://tracker/secret?key=abc"))


def test_category_names_with_slashes_remain_real_taxonomy_nodes():
    categories = {
        7000: IndexerCategory("Ebook"),
        7010: IndexerCategory("Books / Manuals", parent=7000),
    }
    tag = category_tag(7010, categories)
    assert torrent_categories(torrent(tags=frozenset({tag})), category_labels(categories)) == (
        ("Ebook", "Books / Manuals"),
    )
    assert torrent_categories(torrent(category="Media/Books"), {}) == (("Media", "Books"),)
    assert torrent_categories(torrent(tags=frozenset({"my-books"})), {}) == ((),)


def test_mirror_grouping_preserves_announce_hosts_and_unrelated_trackers():
    t = torrent(
        trackers=(
            "https://c411.org/announce/private",
            "https://TK.C411.TW./announce/private",
            "https://tk.c411.tw.attacker.test/announce",
            "https://elsewhere.example/announce",
        )
    )
    assert tracker_groups(t) == ("c411.org", "elsewhere.example", "tk.c411.tw.attacker.test")
    assert "tk.c411.tw" in tracker_hosts(t)
    assert tracker_groups(torrent(tags=frozenset({"c411"}))) == ("",)


def test_qbit_sync_tracks_all_announce_memberships_and_removals():
    api = QbitApi("http://127.0.0.1:1", "", "")
    sync = Synced()
    sync.answers = [
        {
            "rid": 1,
            "full_update": True,
            "torrents": {"a": entry("A")},
            "trackers": {"https://one.example/secret": ["a"], "udp://two.example/announce": ["a"]},
        },
        {"rid": 2, "trackers_removed": ["https://one.example/secret"]},
        {"rid": 3, "trackers": {"udp://two.example/announce": []}},
        {"rid": 4, "full_update": True, "torrents": {"a": entry("A")}},
    ]
    api._client = sync
    assert tracker_hosts(api.torrents(with_files=False)[0]) == ("one.example", "two.example")
    assert tracker_hosts(api.torrents(with_files=False)[0]) == ("two.example",)
    assert tracker_hosts(api.torrents(with_files=False)[0]) == ("",)
    assert tracker_hosts(api.torrents(with_files=False)[0]) == ("",)


def test_qbit_swarm_counts_are_visible_without_connected_peers(qtbot):
    api = QbitApi("http://127.0.0.1:1", "", "")
    sync = Synced()
    sync.answers = [
        {
            "rid": 1,
            "full_update": True,
            "torrents": {
                "a": entry("Book", num_seeds=0, num_leechs=0, num_complete=42, num_incomplete=3)
            },
        }
    ]
    api._client = sync
    tab, _ = make_tab(qtbot, a=api.torrents(with_files=False)[0])
    assert tab.model.index(0, 12).data() == "0 (42)"
    assert tab.model.index(0, 13).data() == "0 (3)"


def test_actions_deduplicate_protect_verification_and_keep_files():
    client = FakeQbit(by_hash={"a": torrent(), "b": torrent("b", tags=frozenset({VERIFYING}))})
    results = manage(client, ["a", "a", "b", "gone"], "remove")
    assert [r.outcome for r in results] == ["sent", "verifying", "missing"]
    assert client.removed == [("a", False)]
    assert "b" in client.by_hash


def test_batch_action_continues_after_one_failure():
    class FailingClient(FakeQbit):
        def pause(self, hash):
            if hash == "a":
                raise RuntimeError("unavailable")
            super().pause(hash)

    client = FailingClient(by_hash={"a": torrent(), "b": torrent("b")})
    assert [r.outcome for r in manage(client, ["a", "b"], "pause")] == ["failed", "sent"]
    assert status(client.by_hash["b"]) == "paused"


def test_empty_file_selection_cannot_mean_all_files():
    client = FakeQbit(by_hash={"a": torrent()})
    assert manage(client, ["a"], "skip_files") == []
    assert client.priorities == {}
    manage(client, ["a"], "skip_files", file_indexes=[2])
    assert client.priorities == {"a": {2: 0}}


def make_tab(qtbot, **torrents):
    client = FakeQbit(by_hash=torrents)
    tab = TorrentsTab(lambda: client)
    qtbot.addWidget(tab)
    tab.resize(1100, 720)
    tab.show()
    qtbot.waitUntil(lambda: not tab._loading)
    tab.timer.stop()
    return tab, client


def test_tree_counts_deduplicate_and_filters_combine(qtbot):
    tab, _ = make_tab(
        qtbot,
        a=torrent(
            trackers=("https://one/secret", "udp://two/announce"),
            category="Books/Comics",
            state="uploading",
            tags=frozenset({"personal"}),
        ),
        b=torrent("b", tracker="https://one/secret", state="stoppedDL", progress=0.5),
    )
    assert tab._tree_counts[()] == 2
    assert tab._tree_counts[("one",)] == 2
    assert tab._tree_counts[("two",)] == 1
    assert tab._tree_counts[("one", "Books", "Comics")] == 1
    root = tab.tree.topLevelItem(0)
    tab.tree.setCurrentItem(root.child(1))
    assert tab.proxy.rowCount() == 1
    tab.states.setCurrentIndex(tab.states.findData("paused"))
    assert tab.proxy.rowCount() == 0
    tab.tree.setCurrentItem(root)
    assert tab.proxy.rowCount() == 1
    tab.tags.setCurrentIndex(tab.tags.findData("personal"))
    assert tab.proxy.rowCount() == 0


def test_c411_mirror_shares_tree_branch_and_category_counts(qtbot):
    tab, _ = make_tab(
        qtbot,
        a=torrent(
            trackers=("https://c411.org/announce/private", "https://tk.c411.tw/announce/private"),
            category="Ebook/Books",
        ),
        b=torrent("b", tracker="https://tk.c411.tw/announce/private", category="Ebook/Books"),
    )
    root = tab.tree.topLevelItem(0)
    assert root.childCount() == 1
    assert tab._tree_counts[("c411.org",)] == 2
    assert tab._tree_counts[("c411.org", "Ebook", "Books")] == 2
    tab.tree.setCurrentItem(root.child(0))
    assert tab.proxy.rowCount() == 2


def test_refresh_keeps_selection_sort_and_updated_values(qtbot):
    tab, client = make_tab(qtbot, a=torrent(size=200), b=torrent("b", size=100))
    tab.table.sortByColumn(3, Qt.SortOrder.DescendingOrder)
    tab.table.selectRow(0)
    assert tab.selected()[0].hash == "a"
    client.by_hash["a"] = replace(client.by_hash["a"], size=50)
    tab.refresh()
    qtbot.waitUntil(lambda: not tab._loading)
    assert tab.selected()[0].hash == "a"
    assert tab.proxy.index(1, 0).data(Qt.ItemDataRole.UserRole) == "a"
    # Insertions/removals must also retain selected hashes.
    client.by_hash["c"] = torrent("c")
    tab.refresh()
    qtbot.waitUntil(lambda: not tab._loading)
    assert tab.selected()[0].hash == "a"
    tab.hide()
    assert not tab.timer.isActive()


def test_files_are_loaded_only_on_demand_and_for_current_selection(qtbot, monkeypatch):
    tab, _ = make_tab(
        qtbot, a=torrent(files={"one.epub": 1}), b=torrent("b", files={"two.epub": 2})
    )
    jobs = []
    monkeypatch.setattr(
        "torrentlinker.gui.torrents_view.run_in_background",
        lambda fn, done, fail: jobs.append((fn, done)),
    )
    tab._restore_selection({"a"})
    assert jobs == []
    tab.details.setCurrentIndex(1)
    assert len(jobs) == 1
    tab._restore_selection({"b"})
    assert len(jobs) == 2
    jobs[1][1](jobs[1][0]())
    jobs[0][1](jobs[0][0]())
    assert tab.files.item(0, 0).text() == "two.epub"


def test_background_refresh_ignores_previous_connection(qtbot, monkeypatch):
    tab, _ = make_tab(qtbot, a=torrent())
    jobs = []
    monkeypatch.setattr(
        "torrentlinker.gui.torrents_view.run_in_background",
        lambda fn, done, fail: jobs.append(done),
    )
    tab.refresh()
    tab.reset_connection()
    jobs[0]([torrent()])
    assert tab.model.rows == []
    jobs[1]([torrent("new")])
    assert [t.hash for t in tab.model.rows] == ["new"]


def test_qbit_file_listing_keeps_real_file_indexes():
    from unittest.mock import Mock

    api = QbitApi("http://127.0.0.1:1", "", "")
    api._client = Mock()
    api._client.torrents_files.return_value = [
        {"index": 0, "name": "first", "size": 10, "priority": 1},
        {"index": 2, "name": "third", "size": 20, "priority": 0},
    ]
    assert [(f.index, f.wanted) for f in api.file_listing("a")] == [(0, True), (2, False)]
    api.pause("a")
    api._client.torrents_stop.assert_called_once_with(torrent_hashes="a")


def test_deluge_management_resume_keeps_user_limits_and_pause_targets_selection():
    from unittest.mock import Mock

    from torrentlinker.deluge import DelugeApi

    api = DelugeApi("http://127.0.0.1:1", "")
    api._call = Mock()
    api.resume("a")
    api._call.assert_called_once_with("core.resume_torrent", "a")
    api._call.reset_mock()
    api.pause("a")
    api._call.assert_called_once_with("core.pause_torrent", ["a"])


def test_transmission_management_stop_targets_selection():
    from unittest.mock import Mock

    from torrentlinker.transmission import TransmissionApi

    api = TransmissionApi("http://127.0.0.1:1", "", "")
    api._call = Mock()
    api.pause("a")
    api._call.assert_called_once_with("torrent-stop", ids=["a"])


def test_file_selection_uses_original_indexes_after_sorting(qtbot):
    from torrentlinker.domain import TorrentFile

    tab, client = make_tab(qtbot, a=torrent())
    client.file_listing = lambda _: [TorrentFile(2, "z", 10), TorrentFile(7, "a", 20)]
    tab._restore_selection({"a"})
    tab.details.setCurrentIndex(1)
    qtbot.waitUntil(lambda: tab.files.rowCount() == 2)
    tab.files.sortItems(0, Qt.SortOrder.AscendingOrder)
    tab.files.selectRow(0)
    tab.perform("skip_files")
    qtbot.waitUntil(lambda: not tab._acting)
    assert client.priorities["a"] == {7: 0}


def test_unchanged_refresh_does_not_notify_or_resort_the_table(qtbot):
    from PySide6.QtTest import QSignalSpy

    tab, _ = make_tab(qtbot, a=torrent(state="uploading"))
    changed = QSignalSpy(tab.model.dataChanged)
    layout = QSignalSpy(tab.proxy.layoutChanged)
    tab.refresh()
    qtbot.waitUntil(lambda: not tab._loading)
    assert changed.count() == 0
    assert layout.count() == 0


def test_state_filter_updates_when_only_state_changes(qtbot):
    tab, client = make_tab(qtbot, a=torrent(state="uploading"))
    tab.states.setCurrentIndex(tab.states.findData("paused"))
    assert tab.proxy.rowCount() == 0
    client.by_hash["a"] = replace(client.by_hash["a"], state="stoppedUP")
    tab.refresh()
    qtbot.waitUntil(lambda: not tab._loading)
    assert tab.proxy.rowCount() == 1


def test_parent_only_tags_have_unspecified_subcategory(qtbot):
    cats = {7000: IndexerCategory("Ebook"), 7010: IndexerCategory("Books", 7000)}
    tag = category_tag(7000, cats)
    tab, _ = make_tab(qtbot, a=torrent(tracker="https://tracker/secret", tags=frozenset({tag})))
    tab._known_categories = category_labels(cats)
    tab._group()
    assert tab._tree_counts[("tracker", "Ebook", "")] == 1


def test_connection_counts_sort_numerically_and_refresh(qtbot):
    tab, client = make_tab(
        qtbot,
        a=torrent(connected_seeds=2, connected_peers=12, swarm_seeders=50),
        b=torrent("b", connected_seeds=10, connected_peers=3),
    )
    assert tab.model.index(0, 12).data() == "2 (50)"
    assert tab.model.index(0, 13).data() == "12 (?)"
    assert "50" in tab.model.index(0, 12).data(Qt.ItemDataRole.ToolTipRole)
    for column, first in ((12, "a"), (13, "a")):
        assert not tab.table.isColumnHidden(column)
        tab.table.sortByColumn(column, Qt.SortOrder.DescendingOrder)
        assert tab.proxy.index(0, 0).data(Qt.ItemDataRole.UserRole) == first
    tab._restore_selection({"a"})
    client.by_hash["a"] = replace(client.by_hash["a"], connected_peers=1, connected_seeds=20)
    tab.refresh()
    qtbot.waitUntil(lambda: not tab._loading)
    assert tab.selected()[0].hash == "a"
    assert tab.proxy.index(0, 0).data(Qt.ItemDataRole.UserRole) == "b"
    assert tab.model.index(0, 12).data() == "20 (50)"
    changed = []
    tab.model.dataChanged.connect(lambda left, right: changed.append(left.column()))
    client.by_hash["a"] = replace(client.by_hash["a"], swarm_peers=30)
    tab.refresh()
    qtbot.waitUntil(lambda: not tab._loading)
    assert 13 in changed
    assert tab.model.index(0, 13).data() == "1 (30)"
    assert tab.proxy.index(0, 0).data(Qt.ItemDataRole.UserRole) == "a"


def test_context_menu_targets_clicked_row_or_existing_multi_selection(qtbot, monkeypatch):
    tab, _ = make_tab(qtbot, a=torrent(), b=torrent("b"), c=torrent("c"))
    commands = []
    monkeypatch.setattr(tab, "perform", lambda action: commands.append((action, tab.selected())))
    tab._restore_selection({"a", "b"})
    tab._context_menu(tab.table.visualRect(tab.proxy.index(0, 0)).center())
    assert {t.hash for t in tab.selected()} == {"a", "b"}
    tab.context_menu.actions()[1].trigger()
    assert commands[0][0] == "pause"
    assert {t.hash for t in commands[0][1]} == {"a", "b"}
    tab.context_menu.hide()
    tab._context_menu(tab.table.visualRect(tab.proxy.index(2, 0)).center())
    assert [t.hash for t in tab.selected()] == ["c"]
    tab.context_menu.hide()
    tab._context_menu(QPoint(5, tab.table.viewport().height() - 1))
    assert not tab.context_menu.isVisible()
    tab._acting = True
    tab._context_menu(tab.table.visualRect(tab.proxy.index(2, 0)).center())
    assert all(not a.isEnabled() for a in tab.context_menu.actions() if not a.isSeparator())


def test_context_remove_keeps_confirmation(qtbot, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    tab, client = make_tab(qtbot, a=torrent())
    tab.table.selectRow(0)
    remove = next(a for a in tab.context_menu.actions() if a.text() == "Remove…")
    remove.trigger()
    assert client.removed == []
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    remove.trigger()
    qtbot.waitUntil(lambda: not tab._acting)
    assert client.removed == [("a", False)]


def test_old_column_preferences_survive_and_new_columns_stay_configurable(
    qtbot, isolated_table_settings
):
    from PySide6.QtGui import QStandardItemModel
    from PySide6.QtWidgets import QTableView

    old = QTableView()
    qtbot.addWidget(old)
    old.setModel(QStandardItemModel(0, 12, old))
    old.setColumnWidth(0, 280)
    old.setColumnHidden(8, True)
    isolated_table_settings.setValue("torrents/header", old.horizontalHeader().saveState())
    tab, _ = make_tab(qtbot, a=torrent())
    header = tab.table.horizontalHeader()
    assert tab.table.columnWidth(0) == 280
    assert tab.table.isColumnHidden(8)
    assert header.visualIndex(12) == header.visualIndex(5) + 1
    assert header.visualIndex(13) == header.visualIndex(12) + 1
    tab._column(12, False)
    tab.hide()
    reopened, _ = make_tab(qtbot, a=torrent())
    assert reopened.table.isColumnHidden(12)
    assert not reopened.table.isColumnHidden(13)
    reopened.resize(2000, 720)
    qtbot.waitUntil(lambda: reopened.width() == 2000)
    assert reopened.search.width() <= 420


def test_explicit_delete_removes_data_once_and_protects_verifying_torrents():
    client = FakeQbit(by_hash={"a": torrent(), "b": torrent("b", tags=frozenset({VERIFYING}))})
    results = manage(client, ["a", "a", "b", "gone"], "delete")
    assert [r.outcome for r in results] == ["sent", "verifying", "missing"]
    assert client.removed == [("a", True)]
    assert "b" in client.by_hash


def test_delete_dialog_defaults_to_cancel_and_names_all_selected_torrents(qtbot, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    tab, client = make_tab(qtbot, a=torrent(), b=torrent("b"))
    tab._restore_selection({"a", "b"})
    seen = []

    def cancel(box):
        assert box.defaultButton() == box.button(QMessageBox.StandardButton.Cancel)
        assert box.escapeButton() == box.button(QMessageBox.StandardButton.Cancel)
        assert "2" in box.text()
        assert "remote server or seedbox" in box.informativeText()
        assert "shared with other torrents" in box.informativeText()
        assert "Torrent a" in box.detailedText()
        assert "Torrent b" in box.detailedText()
        assert "/seedbox/downloads" in box.detailedText()
        seen.append(True)
        return QMessageBox.StandardButton.Cancel

    monkeypatch.setattr(QMessageBox, "exec", cancel)
    delete = tab.context_menu.actions()[-1]
    assert delete.text() == "Delete torrent and files…"
    delete.trigger()
    assert seen == [True]
    assert client.removed == []
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Yes)
    delete.trigger()
    qtbot.waitUntil(lambda: not tab._acting)
    assert sorted(client.removed) == [("a", True), ("b", True)]


@pytest.mark.parametrize("delete_files", [False, True])
def test_all_client_adapters_send_explicit_data_deletion_flag(delete_files):
    from unittest.mock import Mock

    from torrentlinker.deluge import DelugeApi
    from torrentlinker.paths import MappedQbit, PathMapper
    from torrentlinker.transmission import TransmissionApi
    from torrentlinker.utorrent import UtorrentApi

    qbit = QbitApi("http://127.0.0.1:1", "", "")
    qbit._client = Mock()
    qbit.remove("a", delete_files=delete_files)
    qbit._client.torrents_delete.assert_called_once_with(
        delete_files=delete_files, torrent_hashes="a"
    )
    deluge = DelugeApi("http://127.0.0.1:1", "")
    deluge._call = Mock()
    deluge.remove("a", delete_files=delete_files)
    deluge._call.assert_called_once_with("core.remove_torrent", "a", delete_files)
    transmission = TransmissionApi("http://127.0.0.1:1", "", "")
    transmission._call = Mock()
    transmission.remove("a", delete_files=delete_files)
    transmission._call.assert_called_once_with(
        "torrent-remove", ids=["a"], **{"delete-local-data": delete_files}
    )
    utorrent = UtorrentApi("http://127.0.0.1:1", "", "")
    utorrent._action = Mock()
    utorrent.remove("a", delete_files=delete_files)
    utorrent._action.assert_called_once_with("removedata" if delete_files else "remove", "a")
    client = FakeQbit(by_hash={"a": torrent()})
    MappedQbit(client, PathMapper([])).remove("a", delete_files=delete_files)
    assert client.removed == [("a", delete_files)]


def test_progress_bar_fills_from_left_to_right(qtbot):
    tab = TorrentsTab(lambda: FakeQbit())
    qtbot.addWidget(tab)
    tab.resize(1000, 400)
    tab.show()
    tab.model.update([torrent("a", progress=0.5), torrent("b", progress=1.0)])
    tab.table.setColumnWidth(2, 200)
    tab.table.setRowHeight(0, 40)
    image = tab.table.viewport().grab().toImage()
    rect = tab.table.visualRect(tab.proxy.index(0, 2))
    y = rect.center().y() + 12  # below the label, where only the bar's fill shows
    left = image.pixelColor(rect.left() + 12, y)
    right = image.pixelColor(rect.right() - 12, y)
    top_left = image.pixelColor(rect.left() + 12, rect.top() + 6)
    assert left != right  # filled on the left, empty on the right, whatever the row height
    assert top_left == left or top_left != right
