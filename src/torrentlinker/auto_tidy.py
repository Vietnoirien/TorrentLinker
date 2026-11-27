"""Ranger automatiquement: a finished download is renamed and moved, still seeding (#212).

A Download Folder with the option on (off by default) tidies each release that finishes
while it is on: the file is renamed with the template of the Library Folder the placement
rule picks, then moved there through its Torrent Client. Both steps are Tâches, so they are
logged and can be undone. A client that cannot rename inside a torrent leaves the release where
it is, with the reason in the journal.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from guessit import guessit

from torrentlinker.disk_report import place
from torrentlinker.domain import ContentKind
from torrentlinker.media import VIDEO
from torrentlinker.organisation import clean, facts_of, fill, template_error

ACTOR = "Rangement automatique"


def _kind_ok(folder_kind: ContentKind, kind: str) -> int:
    """0 when the Library Folder is for this kind, 1 when it takes anything, else 2."""
    if folder_kind == (ContentKind.SERIES if kind == "series" else ContentKind.MOVIE):
        return 0
    return 1 if folder_kind == ContentKind.OTHER else 2


def plan(
    torrent,
    native: bool,
    library: list[Any],
    cards: list[dict[str, Any]],
    template_of,
) -> dict[str, Any]:
    """What tidying this torrent does: the rename inside its folder, then the move, or why not.

    `template_of(folder, kind)` is the Library Folder's naming template."""
    videos = sorted(n for n in torrent.files if Path(n).suffix.lower() in VIDEO)
    if not videos:
        return {"skip": "No video in this torrent."}
    if len(videos) > 1 and not guessit(videos[0]).get("episode"):
        return {"skip": "Several videos that are not episodes: tidy it from Organisation."}
    kind = "series" if guessit(videos[0]).get("type") == "episode" else "film"
    if not native:
        return {"skip": "This client cannot rename inside a torrent: it needs a Link Folder."}
    ranked = sorted(
        (f for f in library if _kind_ok(f.kind, kind) < 2), key=lambda f: _kind_ok(f.kind, kind)
    )
    if not ranked:
        return {"skip": "No Library Folder takes this kind of release."}
    folder = Path(ranked[0].path)
    template = template_of(folder, kind)
    if template_error(template):
        return {"skip": f"The template of {folder.name} is not valid."}
    save = Path(torrent.save_path)
    renames: list[dict[str, str]] = []
    top = ""
    for name in videos:
        segments = fill(template, facts_of({}, Path(name).name))
        segments[-1] += Path(name).suffix.lower()
        top = top or segments[0]
        renames.append({"from": str(save / name), "to": str(save.joinpath(*segments))})
    together = None
    for entry in library:
        if (Path(entry.path) / clean(top)).exists():
            together = Path(entry.path) / clean(top)
    chosen = place(cards, sum(torrent.files.values()), together)
    if chosen["disk"] is None:
        return {"skip": "No disk has room above the 10 % margin."}
    roots = next(c["roots"] for c in cards if c["id"] == chosen["disk"])
    on_disk = [
        f
        for f in ranked
        if any(Path(f.path) == Path(r) or Path(f.path).is_relative_to(r) for r in roots)
    ]
    if not on_disk:
        return {"skip": f"{chosen['name']} has no Library Folder for this kind of release."}
    destination = Path(on_disk[0].path)
    new_top = save / clean(top)
    first = renames[0]["to"]
    one_file = len(videos) == 1 and Path(first).parent == save
    items = [{"kind": "rename", **r} for r in renames]
    items.append(
        {"kind": "move", "from": first if one_file else str(new_top), "to": str(destination)}
    )
    return {"kind": kind, "items": items, "destination": str(destination), "why": chosen["why"]}


class AutoTidy:
    def __init__(self, directory: Path, storage, submit, refresh=lambda client_id: None) -> None:
        """`submit(kind, items, actor)` queues Tâches and returns the task; `refresh(client)`
        reads the client's torrents again, so the move after a rename sees the new names."""
        self.storage, self.submit, self.refresh = storage, submit, refresh
        self._lock = threading.RLock()
        self._db = sqlite3.connect(directory / "auto-tidy.sqlite", check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._db:
            self._db.executescript(
                """
                CREATE TABLE IF NOT EXISTS seen (client TEXT, hash TEXT, PRIMARY KEY(client, hash));
                CREATE TABLE IF NOT EXISTS tidied (
                    client TEXT, hash TEXT, at REAL, state TEXT, detail TEXT,
                    PRIMARY KEY(client, hash));
                """
            )

    def results(self) -> list[dict[str, Any]]:
        rows = self._db.execute("SELECT * FROM tidied ORDER BY at DESC LIMIT 50").fetchall()
        return [dict(r) for r in rows]

    def tick(self, client_id: str, torrents, native: bool, downloads, library, cards, template_of):
        """Remember what is still downloading; tidy what finished in a Download Folder that
        has the option on."""
        on = [Path(f) for f, flag in self.storage.auto_tidy().items() if flag]
        done = []
        for torrent in torrents:
            where = Path(torrent.save_path)
            if not any(where == f or where.is_relative_to(f) for f in on):
                continue
            key = (client_id, torrent.hash.lower())
            with self._lock, self._db:
                if torrent.progress < 1:
                    self._db.execute("INSERT OR IGNORE INTO seen VALUES (?,?)", key)
                    continue
                known = self._db.execute(
                    "SELECT 1 FROM seen WHERE client=? AND hash=?", key
                ).fetchone()
                tidied = self._db.execute(
                    "SELECT 1 FROM tidied WHERE client=? AND hash=?", key
                ).fetchone()
            if not known or tidied or "check" in torrent.state.lower():
                continue
            if any(t.startswith("torrentlinker:") for t in torrent.tags):
                continue  # under Reseed Verification or a Link Folder: never moved
            done.append(self._tidy(client_id, torrent, native, library, cards, template_of))
        return done

    def _tidy(self, client_id, torrent, native, library, cards, template_of) -> str:
        found = plan(torrent, native, library, cards, template_of)
        state, detail = "skipped", found.get("skip", "")
        if "items" in found:
            try:
                for item in found["items"]:
                    kind = item.pop("kind")
                    task = self.submit(kind, [item], ACTOR)
                    deadline = time.monotonic() + 6 * 3600  # a copy across disks is long
                    while task["state"] in {"queued", "running"} and time.monotonic() < deadline:
                        time.sleep(0.5)
                    if task["state"] != "done":
                        reason = next((i["reason"] for i in task["items"] if i["reason"]), "")
                        raise RuntimeError(reason or f"The {kind} did not finish.")
                    self.refresh(client_id)  # the move that follows starts from the new name
                state, detail = "done", found["destination"]
            except Exception as error:  # noqa: BLE001 - recorded, and never tried again
                state, detail = "failed", str(error)
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO tidied VALUES (?,?,?,?,?)",
                (client_id, torrent.hash.lower(), time.time(), state, detail),
            )
        return state
