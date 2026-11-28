"""Organisation's board: folder roles, provenance links, and Ranger (ADR-0029, #223).

A folder is an organised library (the app names and places everything in it), a provenance (an
old library or a Download Folder whose content goes to an organised library) or ignored. A
provenance goes to Automatique (each item is routed by kind, then by the placement rule) or is
pinned to one library. Ranger moves and renames each item to the library's template in one pass,
as Tâches; every torrent keeps seeding because a seeded file goes through its client (and a file
several torrents share follows #222). An item with no recognisable title is "to check": it is
never moved before the Owner gives it a title or keeps it as it is.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import threading
import time
import uuid
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from torrentlinker.disk_report import place, usage
from torrentlinker.domain import ContentKind, LibraryFolder
from torrentlinker.file_storage import TRASH_NAME, FileStorage, StorageError
from torrentlinker.library_items import (
    Item,
    SeedIndex,
    discover,
    episode_number,
    fixed_kind,
    one,
    part_number,
    video_height,
)
from torrentlinker.media import VIDEO
from torrentlinker.organisation import (
    DEFAULTS,
    SIDECARS,
    TOKENS,
    Organisation,
    clean,
    facts_of,
    fill,
    template_error,
)

logger = logging.getLogger(__name__)
SPEED = 150e6  # bytes per second of a copy to another disk, for the estimate
ROLES = ("lib", "prov", "none")
# What Windows and macOS leave in folders: never moved with an item, never a season.
JUNK = {"thumbs.db", "desktop.ini", ".ds_store"}


def junk(name: str) -> bool:
    """What a system or a client leaves beside media: never moved with an item, never a
    season (uTorrent's ~uTorrentPartFile_….dat holds pieces of files it skipped)."""
    lowered = name.lower()
    return lowered in JUNK or lowered.startswith("~utorrentpartfile")


def same_media(a: Path, b: Path) -> bool:
    """Whether two items hold the same videos: the same sizes, and the same first and last
    megabyte of the largest one (enough for copies, quick on 50 GB)."""

    def videos(path: Path) -> list[Path]:
        files = [path] if path.is_file() else [p for p in path.rglob("*") if p.is_file()]
        return sorted(
            (p for p in files if p.suffix.lower() in VIDEO), key=lambda p: p.stat().st_size
        )

    def ends(path: Path) -> bytes:
        size = path.stat().st_size
        with path.open("rb") as handle:
            head = handle.read(1 << 20)
            handle.seek(max(0, size - (1 << 20)))
            return head + handle.read(1 << 20)

    try:
        left, right = videos(a), videos(b)
        if not left or [p.stat().st_size for p in left] != [p.stat().st_size for p in right]:
            return False
        return ends(left[-1]) == ends(right[-1])
    except OSError:
        return False


def folded(name: str) -> str:
    """A title compared as people read it: no case, accent, punctuation or spaces, so
    "MONTY PYTHONS-FLYING CIRCUS" is "Monty Python's Flying Circus"."""
    from torrentlinker.media_tracker import plain

    return plain(name).replace(" ", "")


LIBRARY_RECOUNT = 10.0  # seconds between two readings of a library a batch fills
TITLES_FOR = 300.0  # seconds the suggestions keep the indexes' titles
KINDS = {ContentKind.MOVIE: "films", ContentKind.SERIES: "series"}
CONTENT = {"films": ContentKind.MOVIE, "series": ContentKind.SERIES, "other": ContentKind.OTHER}
ACTOR = "Rangement"
HIDDEN = {TRASH_NAME, ".liens"}


def _wanted(kind: str) -> str:
    return "series" if kind == "series" else "films"


class Board:
    """Roles, links and the contents of the folders, as Fichiers' Organisation shows them."""

    def __init__(
        self,
        storage: FileStorage,
        organisation: Organisation,
        media: Any,
        library_folders: Callable[[], list[LibraryFolder]],
        download_folders: Callable[[], list[Path]],
        seeds: Callable[[], list[tuple[Path, dict[str, Any]]]],
        client_of: Callable[[str], Any],
        default_client: Callable[[], str],
        link_root_of: Callable[[str], str] = lambda _: "",
        register_library: Callable[[Path, ContentKind], Any] = lambda path, kind: None,
        swap: Callable[[Path, list[Path]], Any] = lambda old, new: None,
        threaded: bool = True,
    ) -> None:
        self.storage, self.organisation, self.media = storage, organisation, media
        self.library_folders, self.download_folders = library_folders, download_folders
        self.seeds, self.client_of, self.default_client = seeds, client_of, default_client
        self.link_root_of, self.register_library, self.swap = link_root_of, register_library, swap
        self.threaded = threaded
        self._scans: dict[str, dict[str, Any]] = {}
        self._bodies: dict[str, dict[str, Any]] = {}
        self._pending: list[str] = []
        self._lock = threading.RLock()
        self._worker: threading.Thread | None = None

    # -- Roles and links ----------------------------------------------------------------------

    def roles(self) -> dict[str, str]:
        """The roles the Owner chose. A folder has none until then: nothing is organised, and
        nothing moved, on a guess."""
        return {k: v for k, v in self.storage.board()["roles"].items() if v in ROLES}

    def libraries(self) -> list[dict[str, Any]]:
        roles, known = self.roles(), {str(f.path): f for f in self.library_folders()}
        found = []
        for path, role in sorted(roles.items()):
            if role != "lib":
                continue
            entry = known.get(path)
            kind = KINDS.get(entry.kind, "other") if entry else "other"
            found.append({"path": path, "kind": kind, "disk": self._disk(path)})
        return found

    def provenances(self) -> list[str]:
        return sorted(p for p, r in self.roles().items() if r == "prov")

    def pinned(self, path: str) -> str:
        to = self.storage.board()["links"].get(path, {}).get("to", "")
        return to if any(lib["path"] == to for lib in self.libraries()) else ""

    def auto_of(self, path: str) -> bool:
        """Auto is on for a download folder and off for an old library, unless the Owner chose
        (the old per-Download-Folder switches of #212 are kept)."""
        link = self.storage.board()["links"].get(path, {})
        if "auto" in link:
            return bool(link["auto"])
        legacy = self.storage.auto_tidy()
        if path in legacy:
            return legacy[path]
        return path in {str(p) for p in self.download_folders()}

    def auto_roots(self) -> list[Path]:
        return [Path(p) for p in self.provenances() if self.auto_of(p)]

    def set_role(self, path: str, role: str, kind: str = "") -> None:
        if role not in ROLES:
            raise StorageError("Unknown role.")
        target = Path(path)
        self.storage.under_roots(target)
        if path not in {row["path"] for row in self.folders()}:
            raise StorageError("Roles go to the Library and Download Folders of Paramètres.")
        if not target.is_dir():
            raise StorageError(f"{path} is not a folder.")
        if role == "lib":
            if any(
                path != other
                and (Path(other).is_relative_to(target) or target.is_relative_to(other))
                for other, r in self.roles().items()
                if r == "lib"
            ):
                raise StorageError("An organised library cannot hold or sit inside another.")
            wanted = kind if kind in CONTENT else self._kind_of(path) or "films"
            self.register_library(target, CONTENT[wanted])

        def change(board: dict[str, Any]) -> None:
            board["roles"][path] = role
            board["links"].pop(path, None)
            board["swapped"].pop(path, None)
            for link in board["links"].values():
                if link.get("to") == path and role != "lib":
                    link["to"] = ""

        self.storage.update_board(change)
        self.scan([path] if role != "none" else [])

    def _kind_of(self, path: str) -> str:
        known = next((f for f in self.library_folders() if str(f.path) == path), None)
        return KINDS.get(known.kind, "") if known else ""

    def set_link(self, path: str, to: str) -> None:
        if path not in self.provenances():
            raise StorageError("This folder is not a provenance.")
        if to and to not in {lib["path"] for lib in self.libraries()}:
            raise StorageError("This is not an organised library.")

        def change(board: dict[str, Any]) -> None:
            board["links"].setdefault(path, {})["to"] = to

        self.storage.update_board(change)

    def set_auto(self, path: str, on: bool) -> None:
        if path not in self.provenances():
            raise StorageError("This folder is not a provenance.")

        def change(board: dict[str, Any]) -> None:
            board["links"].setdefault(path, {})["auto"] = on

        self.storage.update_board(change)

    # -- Folders ------------------------------------------------------------------------------

    def _root(self, path: str) -> str:
        here = Path(path)
        roots = [r for r in self.storage.roots if here == r or here.is_relative_to(r)]
        return str(max(roots, key=lambda r: len(r.parts))) if roots else ""

    def _disk(self, path: str) -> str:
        return self._root(path)

    def disks(self) -> list[dict[str, Any]]:
        """Each storage root with its space (roots on one device share the numbers)."""
        found = []
        for root in self.storage.roots:
            try:
                u = usage(root)
            except OSError:
                continue
            found.append({"name": str(root), "total": u.total, "used": u.used, "free": u.free})
        return found

    def folders(self) -> list[dict[str, Any]]:
        """The folders the Owner set up in Paramètres, and only those: their Library Folders and
        Download Folders, one row each. A role is given to these, never to any folder on a disk."""
        roles = self.roles()
        configured = {str(f.path) for f in self.library_folders()}
        configured |= {str(p) for p in self.download_folders()}
        libs = {lib["path"]: lib for lib in self.libraries()}
        rows = []
        for path in sorted(configured, key=str.casefold):
            scan = self._scans.get(path)
            rows.append({
                "path": path, "role": roles.get(path, ""), "disk": self._root(path),
                "kind": libs.get(path, {}).get("kind", ""), "parent": "",
                "videos": len(scan["items"]) if scan and scan["state"] == "ready" else None,
            })  # fmt: skip
        return rows

    # -- Scanning -----------------------------------------------------------------------------

    def scan(self, paths: Iterable[str] | None = None) -> None:
        """Read what the folders hold, in the background; the board shows it when it is ready."""
        roles = self.roles()
        wanted = [
            p for p in (paths if paths is not None else roles) if roles.get(p) in {"lib", "prov"}
        ]
        with self._lock:
            for path in wanted:
                if path not in self._pending:
                    self._pending.append(path)
                self._scans[path] = {**self._scans.get(path, {"items": []}), "state": "scanning"}
            if not self._pending or (self._worker and self._worker.is_alive()):
                return
            if self.threaded:
                self._worker = threading.Thread(target=self._drain, daemon=True, name="ranger-scan")
                self._worker.start()
                return
        self._drain()

    def ready(self, path: str) -> bool:
        return self._scans.get(path, {}).get("state") == "ready"

    def ensure_scanned(self) -> None:
        """Read the folders the first time the board is asked for, then keep what was read."""
        if not self._scans:
            self.scan()

    def scanning(self) -> bool:
        return any(s["state"] == "scanning" for s in self._scans.values())

    def _drain(self) -> None:
        while True:
            with self._lock:
                if not self._pending:
                    return
                path = self._pending.pop(0)
            try:
                items = self._discover(path)
            except Exception:  # noqa: BLE001 - one unreadable folder must not stop the others
                logger.warning("Could not read %s.", path, exc_info=True)
                items = []
            with self._lock:
                self._scans[path] = {"state": "ready", "items": items, "at": time.time()}
            if path in {lib["path"] for lib in self.libraries()}:
                try:  # worked out here, in the background, never in a page's request
                    self.unorganised(path, compute=True)
                except Exception:  # noqa: BLE001 - the board still shows the library
                    logger.warning("Could not check %s against its template.", path, exc_info=True)

    def _discover(self, path: str) -> list[Item]:
        client = self.default_client()
        prefix = path.rstrip("/") + "/"
        with self.media.lock:
            rows = self.media.db.execute(
                "SELECT path, body FROM media_items WHERE client=? AND substr(path, 1, ?) = ?",
                (client, len(prefix), prefix),
            ).fetchall()
        bodies = {r["path"]: json.loads(r["body"]) for r in rows}
        self._bodies[path] = bodies
        board = self.storage.board()
        series = any(
            str(f.path) == path and f.kind == ContentKind.SERIES
            for f in self.library_folders()
        )  # fmt: skip
        items = discover(Path(path), bodies, board["titles"], series_folder=series)
        # What the trash holds where it lay (a full disk) is no longer to be ranged.
        trashed = self.storage.trashed_in_place()
        items = [
            i for i in items
            if not any(Path(i.path) == t or Path(i.path).is_relative_to(t) for t in trashed)
        ]  # fmt: skip
        index = SeedIndex(self.seeds())
        for item in items:
            item.torrents = index.under(item.path)
        return items

    def todo(self, path: str) -> list[Item]:
        """What ranging a folder takes: a provenance's items, or what an organised library
        holds that its template does not name yet."""
        if path in {lib["path"] for lib in self.libraries()}:
            return self.unorganised(path)
        return self.items(path)

    def unorganised(self, library: str, compute: bool = False) -> list[Item]:
        """The items of an organised library that its template would rename or move: a
        release left under its own name, a season beside its series. Worked out once per
        reading of the library."""
        scan = self._scans.get(library)
        if not scan or scan.get("state") != "ready":
            return []
        cached = scan.get("todo")
        if cached is not None:
            return cached
        if not compute:
            return []  # the background reading works it out
        found = []
        for item in self.items(library):
            if not item.recognised:
                found.append(item)
                continue
            plan = self.plan_item(item, library)
            if plan.get("error") or plan["renames"] or Path(plan["new_top"]) != Path(item.path):
                found.append(item)
        scan["todo"] = found
        return found

    def moved(self, prov: str, top: str, library: str) -> None:
        """One item was ranged: it leaves its provenance's count now; the library that took it
        is read again at most every LIBRARY_RECOUNT seconds."""
        with self._lock:
            scan = self._scans.get(prov)
            if scan:
                scan["items"] = [i for i in scan["items"] if i.path != top]
                scan.pop("todo", None)
            last = self.__dict__.setdefault("_recounted", {})
            due = library and time.monotonic() - last.get(library, 0.0) >= LIBRARY_RECOUNT
            if due:
                last[library] = time.monotonic()
        if due:
            self.scan([library])

    def items(self, path: str) -> list[Item]:
        """The items the Owner has not chosen to keep as they are."""
        kept = set(self.storage.board()["kept"])
        scan = self._scans.get(path)
        return [i for i in scan["items"] if i.path not in kept] if scan else []

    def fix_title(self, path: str, title: str) -> None:
        title = title.strip()
        if not title:
            raise StorageError("Write a title first.")
        item = self._find(path)
        if item is None:
            raise StorageError("This item is not in a folder the board knows.")
        item.title, item.recognised, item.kind = title, True, fixed_kind(Path(path).name)
        self.storage.update_board(lambda board: board["titles"].__setitem__(path, title))

    def keep(self, path: str) -> None:
        if self._find(path) is None:
            raise StorageError("This item is not in a folder the board knows.")
        self.storage.update_board(
            lambda board: board["kept"].append(path) if path not in board["kept"] else None
        )

    def _find(self, path: str) -> Item | None:
        for scan in self._scans.values():
            for item in scan["items"]:
                if item.path == path:
                    return item
        return None

    # -- Routing ------------------------------------------------------------------------------

    def cards(self) -> list[dict[str, Any]]:
        """The disks the placement rule chooses between, with what each can still take."""
        found = []
        for disk in self.storage.disks():
            try:
                u = usage(disk.roots[0])
            except OSError:
                continue
            found.append({"id": disk.id, "name": disk.name, "roots": [str(r) for r in disk.roots],
                          "usable": u.usable, "writable": disk.writable})  # fmt: skip
        return found

    def route(
        self, prov: str, item: Item, cards: list[dict[str, Any]], reserve: bool = True
    ) -> dict[str, Any]:
        """The organised library an item goes to, and why not when none."""
        libs = self.libraries()
        own = next((lib for lib in libs if lib["path"] == prov), None)
        if own is not None and own["kind"] in {_wanted(item.kind), "other"}:
            return {"lib": own, "why": "", "routed": False}  # ranged where it is
        want = _wanted(item.kind)
        fitting = [lib for lib in libs if lib["kind"] == want] or [
            lib for lib in libs if lib["kind"] == "other"
        ]
        pinned = self.pinned(prov)
        chosen: dict[str, Any] | None = None
        routed = False
        if pinned:
            fixed = next(lib for lib in libs if lib["path"] == pinned)
            if fixed in fitting or fixed["kind"] == "other":
                chosen = fixed
            else:
                routed = True
        if chosen is None:
            if not fitting:
                return {"lib": None, "why": "no-library", "routed": routed}
            chosen = fitting[0]
            if len(fitting) > 1:
                together = next(
                    (
                        Path(lib["path"]) / clean(self._segments(lib, item)[0])
                        for lib in fitting
                        if (Path(lib["path"]) / clean(self._segments(lib, item)[0])).exists()
                    ),
                    None,
                )
                decided = place(cards, item.size, together)
                chosen = next(
                    (
                        lib for lib in fitting
                        if decided["disk"] and self._card_of(cards, lib["path"]) == decided["disk"]
                    ),
                    None,
                )  # fmt: skip
                if chosen is None:
                    return {"lib": None, "why": "no-room", "routed": routed}
        card = next((c for c in cards if c["id"] == self._card_of(cards, chosen["path"])), None)
        if card is not None and self._root(item.path) != self._root(chosen["path"]):
            if card["usable"] < item.size:
                return {"lib": None, "why": "no-room", "routed": routed}
            if reserve:
                card["usable"] -= item.size
        return {"lib": chosen, "why": "", "routed": routed}

    @staticmethod
    def _card_of(cards: list[dict[str, Any]], path: str) -> str:
        for card in cards:
            if any(Path(path) == Path(r) or Path(path).is_relative_to(r) for r in card["roots"]):
                return str(card["id"])
        return ""

    def _segments(self, lib: dict[str, Any], item: Item) -> list[str]:
        template = self.organisation.template(Path(lib["path"]), item.kind)
        if template_error(template):
            return [item.title or item.name]
        return fill(template, facts_of(self._body(item, item.videos[0][0] if item.videos else ""),
                                       Path(item.path).name))  # fmt: skip

    def _body(self, item: Item, video: str) -> dict[str, Any]:
        body: dict[str, Any] = next((b[video] for b in self._bodies.values() if video in b), {})
        if item.title:
            # A title picked from the suggestions carries its year: "Titre (2011)".
            dated = re.fullmatch(r"(.+?)\s*\((\d{4})\)", item.title)
            title, year = (dated.group(1), dated.group(2)) if dated else (item.title, "")
            body = {**body, "series" if item.kind == "series" else "title": title}
            if year:
                body["year"] = year
        return body

    def suggest(self, query: str, limit: int = 8) -> list[dict[str, str]]:
        """Titles the film and series indexes know, for the title a Review fixes: compared
        without case, accents or punctuation ("episode" finds "Épisode 50")."""
        from torrentlinker.media_tracker import plain

        wanted = plain(query)
        if len(wanted) < 2:
            return []
        starts, contains = [], []
        for row in self._known_titles():
            names = row["keys"]
            if any(n.startswith(wanted) for n in names):
                starts.append(row)
            elif any(wanted in n for n in names):
                contains.append(row)
        seen, out = set(), []
        for row in [*starts, *contains]:
            key = (row["keys"][0], row["year"])
            if key not in seen:
                seen.add(key)
                out.append({"title": row["title"], "year": row["year"], "kind": row["kind"]})
            if len(out) >= limit:
                break
        return out

    def _known_titles(self) -> list[dict[str, Any]]:
        """Every title of the indexes, read once every few minutes for the suggestions."""
        from torrentlinker.media_tracker import plain

        cached = self.__dict__.get("_titles")
        if cached and time.monotonic() - cached[0] < TITLES_FOR:
            return cached[1]
        rows: list[dict[str, Any]] = []
        with self.media.lock:
            for table, kind in (("film_meta", "film"), ("film_c411", "film"),
                                ("series_meta", "series"), ("series_c411", "series")):  # fmt: skip
                try:
                    found = self.media.db.execute(
                        f"SELECT title, original_title, year FROM {table} WHERE title <> ''"
                    ).fetchall()
                except sqlite3.OperationalError:
                    continue
                for title, original, year in found:
                    keys = [plain(title)] + ([plain(original)] if original else [])
                    rows.append(
                        {"title": title, "year": str(year or ""), "kind": kind, "keys": keys}
                    )
        rows.sort(key=lambda r: r["year"], reverse=True)
        self._titles = (time.monotonic(), rows)
        return rows

    def better(self, source: Path, other: Path) -> str:
        """Which of two versions of a film to keep, the one that goes into the library: the
        higher picture; at equal picture the one a torrent seeds; else the larger. "source"
        or "library"."""

        def main(path: Path) -> Path | None:
            files = [path] if path.is_file() else [p for p in path.rglob("*") if p.is_file()]
            videos = [p for p in files if p.suffix.lower() in VIDEO]
            return max(videos, key=lambda p: p.stat().st_size, default=None)

        mine, theirs = main(source), main(other)
        if theirs is None:
            return "source"
        if mine is None:
            return "library"
        heights = video_height(str(mine)), video_height(str(theirs))
        if heights[0] != heights[1]:
            return "source" if heights[0] > heights[1] else "library"
        index = SeedIndex(self.seeds())
        seeded = bool(index.under(str(source))), bool(index.under(str(other)))
        if seeded[0] != seeded[1]:
            return "source" if seeded[0] else "library"
        return "source" if mine.stat().st_size > theirs.stat().st_size else "library"

    def series_names(self, name: str) -> set[str]:
        """Every name a series goes by, compared plainly: its own, and the French and original
        titles the series indexes (TMDb, c411) give it."""

        wanted = folded(re.sub(r"\s*\(\d{4}\)$", "", name))
        names = {folded(name), wanted}
        for row in self._known_titles():
            keys = {k.replace(" ", "") for k in row["keys"]}
            if row["kind"] == "series" and wanted in keys:
                names.update(keys)
        return names - {""}

    def proposals(self, item: Item, limit: int = 4) -> list[dict[str, str]]:
        """What an unrecognised item might be, guessed from its file name."""
        from guessit import guessit

        name = Path(item.name).name
        try:
            guessed = str(guessit(name).get("title") or "")
        except Exception:  # noqa: BLE001  (a name guessit cannot read proposes nothing)
            guessed = ""
        # guessit reads "Episode.50.2011…" as an episode number: the words before the year
        # or the quality are the title then.
        leading = re.split(r"[ ._-](?:19|20)\d{2}(?:[ ._-]|$)|[ ._-]\d{3,4}p", Path(name).stem)[0]
        leading = re.sub(r"[._]+", " ", leading).strip()
        for wanted in dict.fromkeys(w for w in (guessed, leading) if w):
            if found := self.suggest(wanted, limit):
                return found
        return []

    # -- The board ----------------------------------------------------------------------------

    def state(self) -> dict[str, Any]:
        board = self.storage.board()
        libs, cards = self.libraries(), self.cards()
        out_libs = []
        for lib in libs:
            scan = self._scans.get(lib["path"])
            items = scan["items"] if scan else []
            out_libs.append({
                **lib, "name": Path(lib["path"]).name, "n": len(items),
                "bytes": sum(i.size for i in items),
                "pinned": sum(1 for p in self.provenances() if self.pinned(p) == lib["path"]),
                "todo": len(self.unorganised(lib["path"])),
                "ready": self.ready(lib["path"]),
                "templates": self._templates(lib),
            })  # fmt: skip
        library_set = {str(f.path) for f in self.library_folders()}
        downloads = {str(p) for p in self.download_folders()}
        provs = [self._prov(p, board, library_set, downloads, cards) for p in self.provenances()]
        return {
            "libraries": out_libs, "provenances": provs, "disks": self.disks(),
            "scanning": self.scanning(), "tokens": list(TOKENS), "defaults": DEFAULTS,
            "link_root": self._link_root(),
        }  # fmt: skip

    def _link_root(self) -> str:
        return next((r for r in (self.link_root_of(c) for c in self._clients()) if r), "")

    def _clients(self) -> list[str]:
        return [self.default_client()]

    def _templates(self, lib: dict[str, Any]) -> list[dict[str, Any]]:
        from torrentlinker.organisation import example

        kinds = {"films": ["film"], "series": ["series"]}.get(lib["kind"], ["film", "series"])
        found = []
        for kind in kinds:
            template = self.organisation.template(Path(lib["path"]), kind)
            found.append({
                "kind": kind, "template": template, "default": DEFAULTS[kind],
                "error": template_error(template), "example": example(template, kind),
            })  # fmt: skip
        return found

    def _prov(self, path, board, library_set, downloads, cards) -> dict[str, Any]:
        scan = self._scans.get(path)
        items = self.items(path) if scan else []
        ready = [i for i in items if i.recognised]
        review = [i for i in items if not i.recognised]
        films = [i for i in ready if i.kind == "film"]
        series = [i for i in ready if i.kind == "series"]
        groups: dict[str, int] = {}
        for item in ready:
            if item.group:
                groups[item.group] = groups.get(item.group, 0) + 1
        torrents = {t["hash"] for i in ready for t in i.torrents}
        routes = {
            kind: self.route(path, sample, cards, reserve=False)["lib"]
            for kind, sample in (
                ("film", films[0] if films else None),
                ("series", series[0] if series else None),
            )
            if sample is not None
        }
        kind = "download" if path in downloads else "library" if path in library_set else "other"
        return {
            "path": path, "name": Path(path).name, "disk": self._root(path), "kind": kind,
            "state": scan["state"] if scan else "scanning",
            "films": len(films), "series": len(series),
            "bytesFilms": sum(i.size for i in films), "bytesSeries": sum(i.size for i in series),
            "subs": sorted(groups.items(), key=lambda kv: -kv[1])[:4],
            "review": [
                {"path": i.path, "name": i.name, "size": i.size, "proposals": self.proposals(i)}
                for i in review
            ],
            "torrents": len(torrents),
            "cross": sum(1 for i in ready if len(i.torrents) > 1),
            "liens": sum(max(0, len(i.torrents) - 1) for i in ready),
            "to": self.pinned(path), "auto": self.auto_of(path),
            "ready": bool(ready) and any(routes.values()),
            "swapped": board["swapped"].get(path, []),
        }  # fmt: skip

    # -- The summary of a Ranger -------------------------------------------------------------

    def summary(self, paths: list[str]) -> dict[str, Any]:
        cards = self.cards()
        total: dict[str, Any] = {
            "n": 0, "bytes": 0, "crossing": 0, "torrents": set(), "liens": 0, "cross": 0,
        }  # fmt: skip
        dests: dict[tuple[str, str], dict[str, Any]] = {}
        routed: dict[tuple[str, str, str], int] = {}
        unrouted: dict[tuple[str, str, str], int] = {}
        blocked: list[dict[str, str]] = []
        examples: dict[str, list[dict[str, str]]] = {"film": [], "series": []}
        review = 0
        known = set(self.provenances()) | {lib["path"] for lib in self.libraries()}
        for prov in paths:
            if prov not in known:
                raise StorageError("This folder is not a provenance.")
            if self._scans.get(prov, {}).get("state") != "ready":
                raise StorageError("The folder is still being read: try again in a moment.")
            review += sum(1 for i in self.todo(prov) if not i.recognised)
            for item in (i for i in self.todo(prov) if i.recognised):
                found = self.route(prov, item, cards)
                lib = found["lib"]
                if lib is None:
                    key = (prov, item.kind, found["why"])
                    unrouted[key] = unrouted.get(key, 0) + 1
                    continue
                if why := self._blocked(item):
                    blocked.append({"name": item.name, "reason": why})
                    continue
                key2 = (lib["path"], item.kind)
                row = dests.setdefault(key2, {"lib": lib["path"], "kind": item.kind, "n": 0,
                                              "bytes": 0})  # fmt: skip
                row["n"] += 1
                row["bytes"] += item.size
                total["n"] += 1
                total["bytes"] += item.size
                if self._root(item.path) != self._root(lib["path"]):
                    total["crossing"] += item.size
                total["torrents"].update(t["hash"] for t in item.torrents)
                total["liens"] += max(0, len(item.torrents) - 1)
                total["cross"] += 1 if len(item.torrents) > 1 else 0
                if found["routed"]:
                    key3 = (prov, item.kind, lib["path"])
                    routed[key3] = routed.get(key3, 0) + 1
                if len(examples[item.kind]) < (3 if item.kind == "film" else 1):
                    plan = self.plan_item(item, lib["path"])
                    if not plan.get("error") and plan["renames"]:
                        main = plan["renames"][0]
                        examples[item.kind].append({
                            "from": item.name,
                            "to": Path(main["to"]).relative_to(Path(item.path).parent).as_posix(),
                        })  # fmt: skip
        return {
            "paths": paths, "n": total["n"], "bytes": total["bytes"],
            "seconds": round(total["crossing"] / SPEED),
            "dests": sorted(dests.values(), key=lambda d: (d["kind"], d["lib"])),
            "routed": [{"prov": p, "kind": k, "lib": lib, "n": n}
                       for (p, k, lib), n in routed.items()],
            "unrouted": [{"prov": p, "kind": k, "why": w, "n": n}
                         for (p, k, w), n in unrouted.items()],
            "blocked": blocked[:50], "nblocked": len(blocked),
            "torrents": len(total["torrents"]), "liens": total["liens"], "cross": total["cross"],
            "examples": [*examples["film"], *examples["series"]], "review": review,
            "link_root": self._link_root(),
        }  # fmt: skip

    def _blocked(self, item: Item) -> str:
        """Why a torrent's files cannot follow, found before anything moves."""
        if item.torrents and any(i.get("verifying") for i in item.torrents):
            return "This torrent is being checked."
        for info in item.torrents:
            client = self.client_of(info["client_id"])
            if client is not None and getattr(client, "repoint", None) is not None:
                return (
                    f"Dossier de liens requis : {info['client']} ne sait pas renommer les "
                    "fichiers d'un torrent."
                )
        others = {t["hash"]: t for t in item.torrents}
        if len(others) > 1:
            for info in list(others.values())[1:]:
                if not self.link_root_of(info["client_id"]):
                    return (
                        f"Dossier de liens requis : {info['name']} ({info['client']}) garde "
                        "ses noms, il faut un Dossier de liens pour ce client (Paramètres)."
                    )
        return ""

    # -- Planning one item ---------------------------------------------------------------------

    def plan_item(self, item: Item, library: str) -> dict[str, Any]:
        """The renames (inside the item's own folder) and the move that put an item in a
        library under its template, or why not."""
        top, lib = Path(item.path), Path(library)
        template = self.organisation.template(lib, item.kind)
        if why := template_error(template):
            return {"error": why}
        base = top.parent
        if top.is_dir():
            files = sorted(
                p for p in top.rglob("*")
                if p.is_file() and not p.is_symlink() and not junk(p.name)
            )  # fmt: skip
        else:
            files = [top]
        videos = [p for p in files if p.suffix.lower() in VIDEO]
        sizes = {p: p.stat().st_size for p in videos}
        if not videos:
            return {"error": f"{top.name} no longer holds a video."}
        biggest = max(sizes.values())
        main = [p for p in videos if sizes[p] >= biggest * 0.1 and "sample" not in p.stem.lower()]
        if item.kind == "film":
            parts = {p: part_number(p.name) for p in main}
            if len(main) > 1 and None not in parts.values():
                main = sorted(main, key=lambda p: (parts[p], p.name))  # CD1, CD2… in order
            else:
                main = sorted(main, key=lambda p: -sizes[p])
        targets: dict[Path, Path] = {}
        for index, video in enumerate(main):
            relative = (
                f"{top.name}/{video.relative_to(top).as_posix()}" if top.is_dir() else video.name
            )
            body = self._body(item, str(video))
            if item.kind == "series" and not body.get("episode"):
                # "Cowboy Bebop Session - part1.mkv" lost its number; the video still says
                # "Session #12".
                if (number := episode_number(str(video))) is not None:
                    body = {**body, "episode": number}
            segments = fill(template, facts_of(body, relative))
            segments[-1] += f" - part{index + 1}" if item.kind == "film" and len(main) > 1 else ""
            segments[-1] += video.suffix.lower()
            targets[video] = base.joinpath(*segments)
        tops = {t.relative_to(base).parts[0] for t in targets.values()}
        if len(tops) > 1:
            return {"error": "The episodes do not give the same folder: give the series a title."}
        first = next(iter(targets.values())).relative_to(base).parts
        layered = len(first) > 1
        new_top = base / first[0]
        target_dir = new_top if item.kind == "series" else next(iter(targets.values())).parent
        for other in files:
            if other in targets:
                continue
            owner = next((v for v in main if other.name.startswith(v.stem)), None)
            if other.suffix.lower() in SIDECARS and owner is not None:
                tail = other.name[len(owner.stem) :]
                targets[other] = targets[owner].with_name(targets[owner].stem + tail)
            elif top.is_dir() and layered:
                targets[other] = target_dir / other.relative_to(top)
        if not top.is_dir():  # a lone file: the subtitles beside it follow
            video = main[0]
            for neighbour in sorted(base.iterdir()):
                if neighbour.suffix.lower() in SIDECARS and neighbour.name.startswith(video.stem):
                    tail = neighbour.name[len(video.stem) :]
                    targets[neighbour] = targets[video].with_name(targets[video].stem + tail)
        if item.kind == "series" and not os.path.lexists(lib / new_top.name):
            # The series already in the library under another case or accent joins it:
            # "Shingeki No Kyojin" goes into "Shingeki no Kyojin".

            # Or under another of its names: the indexes know a series' French and original
            # titles, so "L'Attaque des Titans" joins "Shingeki no Kyojin".
            names = self.series_names(new_top.name)
            twin = next((d for d in lib.iterdir() if d.is_dir() and folded(d.name) in names), None)
            if twin is not None:
                # Its episodes take the series' name too: "Monty Python's Flying Circus S03E27".
                renamed, old_name = base / twin.name, new_top.name

                def joined(b: Path) -> Path:
                    if not b.is_relative_to(new_top):
                        return b
                    moved = renamed / b.relative_to(new_top)
                    if moved.name.startswith(old_name):
                        moved = moved.with_name(twin.name + moved.name[len(old_name) :])
                    return moved

                targets = {a: joined(b) for a, b in targets.items()}
                new_top = renamed
        renames = [{"from": str(a), "to": str(b)} for a, b in targets.items() if a != b]
        if top.is_dir() and not layered and any(p not in targets for p in files):
            if item.torrents:
                return {
                    "error": "This template has no folder: the torrent's other files cannot follow."
                }
        across = os.stat(base).st_dev != os.stat(lib).st_dev
        if not across and base != lib and new_top != top and os.path.lexists(new_top):
            return {"error": f"« {new_top.name} » existe déjà dans {base.name}."}
        # Two files given one name (a release numbering two episodes 31) is checked before
        # anything moves: the item waits in À vérifier instead of half moving.
        seen: dict[Path, Path] = {}
        for source, target in targets.items():
            if target in seen:
                return {
                    "error": f"Deux fichiers recevraient le même nom « {target.name} » : "
                    f"{seen[target].name} et {source.name}. Corrigez le nom de l'un d'eux.",
                    "review": True,
                }
            seen[target] = source
        landed = lib / new_top.name
        # The same media already in the library (a copy an earlier run could not finish):
        # one of the two goes to the trash instead of failing on the name.
        for other in dict.fromkeys((landed, lib / top.name)):
            if other != top and os.path.lexists(other) and same_media(top, other):
                return {
                    "renames": renames, "new_top": str(new_top), "dest": str(lib),
                    "duplicate": str(other), "error": "",
                }  # fmt: skip
        holds_video = landed.is_dir() and any(
            p.suffix.lower() in VIDEO for p in landed.rglob("*") if p.is_file()
        )
        if item.kind == "film" and holds_video and new_top != landed and top != landed:
            # Another version of the film is in the library already: the better one stays.
            return {
                "renames": renames, "new_top": str(new_top), "dest": str(lib),
                "duplicate": str(landed), "keep": self.better(top, landed), "error": "",
            }  # fmt: skip
        merge = False
        if os.path.lexists(landed) and new_top != landed:
            # Another season, or another part of a season, of a series already in the library
            # joins its folder: only a file already there stops it.
            if item.kind != "series" or not landed.is_dir():
                return {"error": f"« {new_top.name} » existe déjà dans {lib.name}."}
            taken = sorted(
                t.relative_to(base) for t in targets.values()
                if os.path.lexists(lib / t.relative_to(base))
            )  # fmt: skip
            if taken:
                return {"error": f"« {taken[0]} » existe déjà dans {lib.name}."}
            merge = True
        return {
            "renames": renames, "new_top": str(new_top), "dest": str(lib), "merge": merge,
            "error": "",
        }  # fmt: skip

    def plan(self, entry: dict[str, Any]) -> dict[str, Any]:
        """What ranging one queued item does, worked out as it runs: where it goes (the
        provenance's link, else the placement rule now), then its renames and its move."""
        if entry.get("plan"):
            return {**entry["plan"], "resumed": True}
        top = Path(entry["from"])
        if not os.path.lexists(top):
            return {"error": f"{top} n'existe plus."}
        item = self._item_of(entry)
        if item is None:
            return {"error": f"{top.name} no longer holds a video."}
        if not item.recognised:
            return {
                "error": "This item has no title yet: it is never moved before you give it one."
            }
        library = entry.get("to")
        if not library:
            found = self.route(entry.get("prov", ""), item, self.cards())
            if found["lib"] is None:
                reasons = {"no-room": "Aucune bibliothèque n'a la place.",
                           "no-library": "Aucune bibliothèque organisée pour ce type."}  # fmt: skip
                return {"error": reasons.get(found["why"], "Pas de bibliothèque.")}
            library = found["lib"]["path"]
        if why := self._blocked(item):
            return {"error": why}
        return self.plan_item(item, library)

    def _item_of(self, entry: dict[str, Any]) -> Item | None:
        path = entry["from"]
        item = self._find(path)
        if item is not None:
            item.torrents = SeedIndex(self.seeds()).under(path)
            return item
        # Read again after a restart: as the provenance reads it (a folder of series), and
        # never turned from the series it was queued as into a film.
        prov = entry.get("prov", "")
        series = entry.get("kind") == "series" or any(
            str(f.path) == prov and f.kind == ContentKind.SERIES for f in self.library_folders()
        )
        match = one(Path(path), self._bodies.get(prov, {}), self.storage.board()["titles"], series)
        if match is not None and entry.get("kind") == "series":
            match.kind = "series"
        if match is not None:
            match.torrents = SeedIndex(self.seeds()).under(path)
        return match

    # -- After a job ----------------------------------------------------------------------------

    def settle(self, prov: str, libraries: list[str]) -> bool:
        """A provenance that was a Library Folder and is now empty is replaced in the settings
        by the organised libraries that took its content; Member grants follow."""
        if prov not in {str(f.path) for f in self.library_folders()} or not libraries:
            return False
        self._scans[prov] = {"state": "scanning", "items": []}
        self._scans[prov] = {"state": "ready", "items": self._discover(prov), "at": time.time()}
        if self._scans[prov]["items"]:
            return False
        news = [Path(p) for p in dict.fromkeys(libraries)]
        self.swap(Path(prov), news)
        self.storage.update_board(
            lambda board: board["swapped"].__setitem__(prov, [str(p) for p in news])
        )
        return True


class RangerQueue:
    """The batches the Owner (or Auto) queued, kept on disk: a stop never loses what is left."""

    def __init__(
        self, directory: Path, board: Board, tasks: Callable[[], Any], now=time.time
    ) -> None:
        self.board, self.tasks, self.now = board, tasks, now
        self._lock = threading.RLock()
        self._db = sqlite3.connect(directory / "ranger.sqlite", check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._db:
            self._db.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, label TEXT, actor TEXT, created REAL, state TEXT);
                CREATE TABLE IF NOT EXISTS items (
                    job TEXT, seq INTEGER, prov TEXT, top TEXT, kind TEXT, title TEXT,
                    state TEXT, reason TEXT DEFAULT '', note TEXT DEFAULT '',
                    dest TEXT DEFAULT '', plan TEXT DEFAULT '', PRIMARY KEY (job, seq));
                """
            )

    def enqueue(self, label: str, actor: str, rows: list[dict[str, Any]]) -> str:
        """Keep a batch, then run it as one Tâche. `rows`: {top, prov, kind, title}."""
        identifier = uuid.uuid4().hex[:12]
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO jobs VALUES (?,?,?,?,'queued')", (identifier, label, actor, self.now())
            )
            self._db.executemany(
                "INSERT INTO items (job, seq, prov, top, kind, title, state)"
                " VALUES (?,?,?,?,?,?,'queued')",
                [
                    (identifier, n, r["prov"], r["top"], r["kind"], r.get("title", ""))
                    for n, r in enumerate(rows)
                ],
            )
        self._launch(identifier)
        return identifier

    def resume(self) -> int:
        """After a restart: what was running goes back to the queue, and every batch with
        items left is run again; items already done are never repeated."""
        with self._lock, self._db:
            self._db.execute("UPDATE items SET state='queued' WHERE state='running'")
            jobs = [
                r["job"]
                for r in self._db.execute(
                    "SELECT DISTINCT job FROM items WHERE state='queued'"
                ).fetchall()
            ]
        for identifier in jobs:
            self._launch(identifier, resumed=True)
        return len(jobs)

    def _launch(self, identifier: str, resumed: bool = False) -> None:
        with self._lock:
            job = self._db.execute("SELECT * FROM jobs WHERE id=?", (identifier,)).fetchone()
            rows = self._db.execute(
                "SELECT * FROM items WHERE job=? AND state='queued' ORDER BY seq", (identifier,)
            ).fetchall()
            if not rows:
                return
            self._db.execute("UPDATE jobs SET state='running' WHERE id=?", (identifier,))
            self._db.commit()
        items = [
            {"from": r["top"], "to": "", "job": identifier, "seq": r["seq"], "prov": r["prov"],
             "kind": r["kind"], "title": r["title"],
             **({"plan": json.loads(r["plan"])} if r["plan"] else {})}
            for r in rows
        ]  # fmt: skip
        label = job["label"] + (" (reprise)" if resumed else "")
        self.tasks().submit(
            "ranger", items, job["actor"], "skip", label=label,
            on_item=self._item_done, on_done=lambda task: self._job_done(identifier, task),
        )  # fmt: skip

    def planner(self, entry: dict[str, Any]) -> dict[str, Any]:
        plan = self.board.plan(entry)
        with self._lock, self._db:
            self._db.execute(
                "UPDATE items SET state='running', dest=?, plan=? WHERE job=? AND seq=?",
                (plan.get("dest", ""), json.dumps(plan) if not plan.get("error") else "",
                 entry["job"], entry["seq"]),
            )  # fmt: skip
        return plan

    def _item_done(self, task: dict[str, Any], item: dict[str, Any]) -> None:
        meta = item["meta"]
        with self._lock, self._db:
            self._db.execute(
                "UPDATE items SET state=?, reason=?, note=? WHERE job=? AND seq=?",
                (item["state"], item["reason"], item["note"], meta["job"], meta["seq"]),
            )
            row = self._db.execute(
                "SELECT prov, top, dest FROM items WHERE job=? AND seq=?",
                (meta["job"], meta["seq"]),
            ).fetchone()
        if row is not None and item["state"] == "done":
            # The board's counts follow the batch: the item leaves its provenance at once, and
            # its library is read again now and then.
            self.board.moved(row["prov"], row["top"], row["dest"])

    def _job_done(self, identifier: str, task: dict[str, Any]) -> None:
        with self._lock, self._db:
            left = self._db.execute(
                "SELECT COUNT(*) FROM items WHERE job=? AND state IN ('queued','running')",
                (identifier,),
            ).fetchone()[0]
            self._db.execute(
                "UPDATE jobs SET state=? WHERE id=?",
                ("running" if left else task["state"], identifier),
            )
            rows = self._db.execute(
                "SELECT prov, dest FROM items WHERE job=? AND state='done'", (identifier,)
            ).fetchall()
        provs = list(dict.fromkeys(r["prov"] for r in self._db.execute(
            "SELECT prov FROM items WHERE job=?", (identifier,)).fetchall()))  # fmt: skip
        self.board.scan(list(dict.fromkeys(r["dest"] for r in rows if r["dest"])))
        for prov in provs:
            libraries = [r["dest"] for r in rows if r["prov"] == prov and r["dest"]]
            try:
                self.board.scan([prov])
                self.board.settle(prov, libraries)
            except Exception:  # noqa: BLE001 - the ranging itself is done
                logger.warning("Could not settle %s.", prov, exc_info=True)

    def active(self) -> list[dict[str, Any]]:
        rows = self._db.execute(
            "SELECT j.id, j.label, j.state, COUNT(i.seq) total,"
            " SUM(i.state IN ('done','skipped','failed','cancelled')) ended"
            " FROM jobs j JOIN items i ON i.job=j.id GROUP BY j.id"
            " HAVING SUM(i.state IN ('queued','running')) > 0"
        ).fetchall()
        return [dict(r) for r in rows]
