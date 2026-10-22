import sqlite3
from pathlib import Path

from torrentlinker.store import Store


def test_edited_query_is_remembered_per_local_item(tmp_path: Path) -> None:
    item = Path("/windocs/E-Book/Le joueur d'echecs - Stefan Zweig.epub")
    Store(tmp_path / "s.db").set_item_query(item, "joueur echecs zweig")

    reopened = Store(tmp_path / "s.db")

    assert reopened.item_query(item) == "joueur echecs zweig"
    assert reopened.item_query(Path("/other")) is None


def test_old_completed_crawls_are_rechecked_without_losing_torrents(tmp_path: Path) -> None:
    from torrentlinker.store import CatalogueRow, CrawlState

    path = tmp_path / "s.db"
    store = Store(path)
    row = CatalogueRow("aa" * 20, "Book", 1, 1, 7000, "u", "d", 0)
    store.save_catalogue([row])
    with sqlite3.connect(path) as db:
        db.execute("DROP TABLE catalogue_crawl")
        db.execute(
            "CREATE TABLE catalogue_crawl (category INTEGER PRIMARY KEY, next_offset INTEGER,"
            " complete INTEGER, updated_at REAL)"
        )
        db.execute("INSERT INTO catalogue_crawl VALUES (7000, 0, 1, 123)")

    reopened = Store(path)

    assert reopened.crawl_state(7000) == CrawlState(7000, updated_at=123)
    assert reopened.catalogue() == [row]
    reopened.save_crawl_state(CrawlState(7000, complete=True, updated_at=124))
    assert Store(path).crawl_state(7000).complete  # migration runs only once


def test_existing_feed_states_accept_persistent_sync_checkpoints(tmp_path: Path) -> None:
    from dataclasses import replace

    from torrentlinker.store import FeedState

    path = tmp_path / "s.db"
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE catalogue_feed (name TEXT PRIMARY KEY, next_page INTEGER,"
            " updated_at REAL, count INTEGER, limited INTEGER)"
        )
        db.execute("INSERT INTO catalogue_feed VALUES ('live', 2, 123, 500, 1)")

    store = Store(path)
    state = store.feed_state("live")
    assert state == FeedState("live", 2, 123, 500, True)
    checkpoint = replace(state, head_hashes=("a" * 40, "b" * 40))
    store.save_feed_state(checkpoint)
    assert Store(path).feed_state("live") == checkpoint


def test_the_plan_and_what_was_sent_survive_a_restart(tmp_path: Path) -> None:
    from torrentlinker.store import SavedPlanItem

    items = [
        SavedPlanItem(f"{c * 40}", f"Book {c}", 1000, 2, 7020, "/dl", 0.1, 3.5) for c in "abcd"
    ]
    store = Store(tmp_path / "s.db")
    store.save_plan(items, made_at=1000.0)
    store.set_plan_sending(True)
    store.mark_plan_item("a" * 40, "added")
    store.mark_plan_item("b" * 40, "refused", "already in qBittorrent")
    store.mark_plan_item("c" * 40, "failed", "HTTP 500")

    saved = Store(tmp_path / "s.db").saved_plan()

    assert saved is not None and saved.sending and saved.made_at == 1000.0
    assert [i.title for i in saved.pending] == ["Book c", "Book d"]  # failed ones are retried
    assert saved.items[1].reason == "already in qBittorrent"


def test_clearing_the_plan_leaves_nothing_saved(tmp_path: Path) -> None:
    from torrentlinker.store import SavedPlanItem

    store = Store(tmp_path / "s.db")
    store.save_plan([SavedPlanItem("a" * 40, "Book", 1, 1, None, "/dl", 0.1, None)])

    store.clear_plan()

    assert store.saved_plan() is None
