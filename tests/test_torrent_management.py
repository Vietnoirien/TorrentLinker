from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt

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
    tracker_hosts,
)


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
