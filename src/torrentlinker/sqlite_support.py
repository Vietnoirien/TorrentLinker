"""How this application's SQLite databases are opened.

Every store here is read and written by several threads at once: a Search while the Catalogue
refreshes, a listing while a scan writes, the queue while a job reports progress. SQLite's
default rollback journal makes a writer and a reader exclude each other, so each of those
waits for the other to finish even though they touch different rows.

Write-ahead logging lets them run together: readers see the last committed state while a
writer appends. It is recorded in the database file, so it holds for every later connection,
including the desktop application opening the same file.

`synchronous` is left at its default, so a commit is still flushed before it is acknowledged.
Media sets NORMAL on its own, deliberately: the player writes a position every second and
losing the last few after a power cut costs nothing.
"""

from __future__ import annotations

import sqlite3


def concurrent(db: sqlite3.Connection) -> sqlite3.Connection:
    """Put `db` in write-ahead logging, so its readers and its writer stop excluding
    each other. Returns the same connection, for use at the point of opening.

    A database on a filesystem that cannot share memory between processes refuses WAL; that
    is not a reason to fail to open it, so the rollback journal stands in and the only cost
    is the waiting it was meant to remove.
    """
    try:
        db.execute("PRAGMA journal_mode=WAL")
    except sqlite3.DatabaseError:
        pass
    return db
