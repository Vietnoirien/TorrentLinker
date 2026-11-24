"""Every shared store runs in write-ahead logging, so a reader and a writer stop waiting."""

import sqlite3
import threading
from pathlib import Path

from torrentlinker.sqlite_support import concurrent


def mode(path: Path) -> str:
    with sqlite3.connect(path) as db:
        return str(db.execute("PRAGMA journal_mode").fetchone()[0])


def test_concurrent_records_wal_in_the_file_for_every_later_connection(tmp_path):
    path = tmp_path / "store.sqlite"
    db = concurrent(sqlite3.connect(path))
    db.execute("CREATE TABLE t (id TEXT PRIMARY KEY)")
    db.commit()
    db.close()
    # Recorded in the file, so the desktop application opening it later gets it too.
    assert mode(path) == "wal"


def test_a_reader_is_not_blocked_by_an_open_write(tmp_path):
    """The point of it: with the rollback journal this read waits for the writer's commit."""
    path = tmp_path / "store.sqlite"
    writer = concurrent(sqlite3.connect(path))
    writer.execute("CREATE TABLE t (id TEXT PRIMARY KEY)")
    writer.commit()

    writer.execute("BEGIN IMMEDIATE")
    writer.execute("INSERT INTO t VALUES ('pending')")
    read = []

    def reading():
        other = sqlite3.connect(path, timeout=1)
        read.append(other.execute("SELECT count(*) FROM t").fetchone()[0])
        other.close()

    thread = threading.Thread(target=reading)
    thread.start()
    thread.join(timeout=5)
    writer.commit()
    writer.close()
    assert read == [0], "the reader saw the last committed state instead of waiting"


def test_an_unsuitable_filesystem_does_not_stop_the_store_opening(tmp_path):
    """A database that cannot take WAL is opened anyway; only the waiting comes back."""

    class Refusing(sqlite3.Connection):
        def execute(self, *args, **kwargs):
            raise sqlite3.DatabaseError("cannot change into wal mode")

    db = sqlite3.connect(tmp_path / "store.sqlite", factory=Refusing)
    assert concurrent(db) is db
    db.close()
