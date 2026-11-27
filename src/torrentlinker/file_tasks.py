"""Explorateur's operations on files no torrent uses, run as Tâches (ADR-0029, #207).

Move, copy, rename, new folder and trash, each journaled before it starts (`FileStorage`). A move
on one disk is an instant rename; across disks it is a copy that is verified (size and hash)
before the source goes to its disk's Corbeille. A name already taken is a conflict: Ignorer,
Remplacer (the old file goes to the Corbeille) or Renommer, and two identical files offer
Garder un seul. Nothing fails silently: each item ends verified, failed with a reason, or
cancelled. A finished move or rename can be undone.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from torrentlinker.file_storage import FileStorage, StorageError

CHUNK = 1024 * 1024
CONFLICTS = ("skip", "replace", "rename", "keep-one")


def listing(storage: FileStorage, path: Path) -> list[dict[str, Any]]:
    """The entries of a folder under the storage roots, folders first."""
    storage.under_roots(path)
    rows = []
    with os.scandir(path) as entries:
        for entry in entries:
            if entry.name == ".corbeille":
                continue
            info = entry.stat(follow_symlinks=False)
            rows.append(
                {"name": entry.name, "dir": entry.is_dir(follow_symlinks=False),
                 "size": info.st_size, "modified": info.st_mtime, "link": entry.is_symlink()}
            )  # fmt: skip
    return sorted(rows, key=lambda r: (not r["dir"], r["name"].casefold()))


def same_device(a: Path, b: Path) -> bool:
    return a.stat().st_dev == b.stat().st_dev


def digest(path: Path, cancelled: Callable[[], bool] = lambda: False) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(CHUNK):
            if cancelled():
                raise InterruptedError("cancelled")
            h.update(chunk)
    return h.hexdigest()


def free_name(folder: Path, name: str) -> Path:
    stem, dot, suffix = name.rpartition(".") if "." in name[1:] else (name, "", "")
    n = 2
    while (candidate := folder / f"{stem} ({n}){dot}{suffix}").exists():
        n += 1
    return candidate


def _identical(a: Path, b: Path) -> bool:
    if a.is_dir() or b.is_dir() or a.stat().st_size != b.stat().st_size:
        return False
    return digest(a) == digest(b)


class Tasks:
    def __init__(
        self,
        storage: FileStorage,
        seeded: Callable[[Path], str | None] = lambda _: None,
        allowed: Callable[[Path], bool] = lambda _: True,
        threaded: bool = True,
    ) -> None:
        """`seeded(path)` names the client seeding a path (such files wait for #208);
        `allowed(path)` is the actor's right to touch it."""
        self.storage, self.seeded, self.allowed, self.threaded = storage, seeded, allowed, threaded
        self.tasks: dict[str, dict[str, Any]] = {}
        self._cancel: dict[str, threading.Event] = {}
        self._lock = threading.RLock()

    # -- Submitting ---------------------------------------------------------------------

    def submit(
        self,
        kind: str,
        items: list[dict[str, str]],
        actor: str,
        conflict: str = "skip",
        apply_all: bool = True,
    ) -> dict[str, Any]:
        """`items`: `{"from": path, "to": path}` (the destination folder for move and copy, the
        new full path for rename); trash and mkdir take `from` only."""
        if kind not in {"move", "copy", "rename", "mkdir", "trash"}:
            raise StorageError("Unknown operation.")
        if conflict not in CONFLICTS:
            raise StorageError("Unknown conflict choice.")
        identifier = uuid.uuid4().hex[:12]
        task = {
            "id": identifier, "kind": kind, "actor": actor, "state": "queued",
            "created": time.time(), "conflict": conflict, "apply_all": apply_all,
            "items": [
                {"from": i["from"], "to": i.get("to", ""), "state": "queued", "progress": 0.0,
                 "reason": "", "verified": False, "note": "", "final": "", "undo": None}
                for i in items
            ],
        }  # fmt: skip
        with self._lock:
            self.tasks[identifier] = task
            self._cancel[identifier] = threading.Event()
        if self.threaded:
            threading.Thread(target=self.run, args=(identifier,), daemon=True).start()
        else:
            self.run(identifier)
        return task

    def cancel(self, identifier: str) -> None:
        self._cancel[identifier].set()

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return sorted(self.tasks.values(), key=lambda t: -t["created"])

    # -- Running ------------------------------------------------------------------------

    def run(self, identifier: str) -> None:
        task, stop = self.tasks[identifier], self._cancel[identifier]
        task["state"] = "running"
        for item in task["items"]:
            if stop.is_set():
                item.update(state="cancelled", reason="Cancelled before it started.")
                continue
            item["state"] = "running"
            started = time.monotonic()
            operation = self.storage.begin(
                task["kind"], task["actor"], {"from": item["from"], "to": item["to"]}, {}
            )
            try:
                self._item(task, item, stop.is_set)
            except InterruptedError:
                item.update(state="cancelled", reason="Cancelled; the source is untouched.")
                self.storage.finish(operation, "failed", "cancelled")
            except (StorageError, OSError, ValueError) as error:
                item.update(state="failed", reason=str(error) or type(error).__name__)
                self.storage.finish(operation, "failed", item["reason"])
            else:
                if item["state"] == "running":
                    item.update(state="done", progress=1.0)
                self.storage.finish(operation, "done")
            item["seconds"] = round(time.monotonic() - started, 2)
        states = {i["state"] for i in task["items"]}
        task["state"] = "done" if states <= {"done", "skipped"} else (
            "cancelled" if "cancelled" in states else "failed"
        )  # fmt: skip

    def _guard(self, path: Path) -> Path:
        self.storage.under_roots(path)
        if not self.allowed(path):
            raise StorageError(f"You may not touch {path}.")
        if client := self.seeded(path):
            raise StorageError(
                f"{path.name} is seeded by {client}: moving it goes through that client."
            )
        return path

    def _item(self, task: dict[str, Any], item: dict[str, Any], cancelled) -> None:
        kind, source = task["kind"], Path(item["from"])
        if kind == "mkdir":
            target = self._guard(source)
            target.mkdir(parents=True, exist_ok=False)
            item.update(final=str(target), verified=target.is_dir(), undo=None)
            return
        self._guard(source)
        if not os.path.lexists(source):
            raise StorageError(f"{source} does not exist.")
        if kind == "trash":
            stored = self.storage.trash(source, task["actor"])
            item.update(verified=True, final=stored["from"], undo={"restore": stored["id"]})
            return
        target = Path(item["to"])
        if kind in {"move", "copy"}:
            self._guard(target)
            if not target.is_dir():
                raise StorageError(f"{target} is not a folder.")
            target = target / source.name
        else:  # rename
            self._guard(target.parent)
        if source == target or (source.is_dir() and target.is_relative_to(source)):
            raise StorageError("The destination is the source or inside it.")
        if os.path.lexists(target):
            chosen = self._conflict(task, item, source, target)
            if chosen is None:
                return
            target = chosen
        self._transfer(kind, source, target, item, cancelled)

    def _conflict(self, task, item, source: Path, target: Path) -> Path | None:
        choice = task["conflict"]
        if choice == "keep-one":
            if not _identical(source, target):
                raise StorageError(f"{target.name} differs from the source: choose another way.")
            if task["kind"] == "move":
                self.storage.trash(source, task["actor"], "Doublon identique : copie gardée")
            item.update(state="done", verified=True, final=str(target), progress=1.0,
                        note="Un seul exemplaire gardé")  # fmt: skip
            return None
        if choice == "skip":
            item.update(state="skipped", reason="Ignored: the name is taken.", progress=1.0)
            return None
        if choice == "replace":
            self.storage.trash(target, task["actor"], "Remplacé par un autre fichier")
            item["note"] = "Ancien fichier à la corbeille"
            return target
        return free_name(target.parent, target.name)

    def _transfer(self, kind: str, source: Path, target: Path, item, cancelled) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        same_disk = same_device(source, target.parent)
        if kind == "rename" or (kind == "move" and same_disk):
            os.rename(source, target)
            item.update(verified=target.exists() and not source.exists(), final=str(target),
                        undo={"rename": [str(target), str(source)]}, note="instantané")  # fmt: skip
            return
        self._copy(source, target, item, cancelled)
        item.update(final=str(target), verified=True)
        if kind == "move":  # copied and verified: only now does the source go to its trash
            stored = self.storage.trash(source, "system", "Déplacé vers un autre disque")
            item["undo"] = {"restore": stored["id"], "remove": str(target)}

    def _copy(self, source: Path, target: Path, item, cancelled) -> None:
        total = max(1, sum(f.stat().st_size for f in self._files(source)))
        done = 0
        made: list[Path] = []
        try:
            for src in self._files(source):
                dst = target if source.is_file() else target / src.relative_to(source)
                dst.parent.mkdir(parents=True, exist_ok=True)
                with src.open("rb") as r, dst.open("xb") as w:
                    made.append(dst)
                    while chunk := r.read(CHUNK):
                        if cancelled():
                            raise InterruptedError("cancelled")
                        w.write(chunk)
                        done += len(chunk)
                        item["progress"] = round(done / total, 3)
                shutil.copystat(src, dst)
                if src.stat().st_size != dst.stat().st_size or digest(src) != digest(dst):
                    raise StorageError(f"Verification failed for {src.name}: the copy was removed.")
        except BaseException:
            for path in made:  # a failed or cancelled copy leaves nothing behind
                path.unlink(missing_ok=True)
            raise

    @staticmethod
    def _files(path: Path) -> list[Path]:
        if path.is_file():
            return [path]
        return sorted(p for p in path.rglob("*") if p.is_file() and not p.is_symlink())

    # -- Undo ---------------------------------------------------------------------------

    def undo(self, identifier: str, index: int, actor: str) -> str:
        item = self.tasks[identifier]["items"][index]
        action = item.get("undo")
        if item["state"] != "done" or not action:
            raise StorageError("This cannot be undone.")
        if "rename" in action:
            now, before = Path(action["rename"][0]), Path(action["rename"][1])
            if os.path.lexists(before) or not os.path.lexists(now):
                raise StorageError("The files changed since: nothing was undone.")
            os.rename(now, before)
            result = str(before)
        else:
            if "remove" in action and (copy := Path(action["remove"])).exists():
                self.storage.trash(copy, actor, "Déplacement annulé")
            result = self.storage.restore(action["restore"], actor)
        item.update(state="undone", undo=None)
        return result
