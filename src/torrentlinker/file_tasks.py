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
import logging
import os
import shutil
import tempfile
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from torrentlinker.file_storage import FileStorage, StorageError

logger = logging.getLogger(__name__)
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


class _Mirror(dict):  # type: ignore[type-arg]
    """A step of an item: its progress and time left show on the item itself."""

    def __init__(self, parent: dict[str, Any], values: dict[str, Any]) -> None:
        super().__init__(values)
        self.parent = parent

    def __setitem__(self, key: str, value: Any) -> None:
        super().__setitem__(key, value)
        if key in {"progress", "eta"}:
            self.parent[key] = value


class Tasks:
    def __init__(
        self,
        storage: FileStorage,
        seeds: Callable[[Path], list[tuple[Path, dict[str, Any]]]] = lambda _: [],
        allowed: Callable[[Path], bool] = lambda _: True,
        threaded: bool = True,
        followed: Callable[[Path, Path], Any] = lambda old, new: None,
        client_of: Callable[[str], Any] = lambda _: None,
        link_root_of: Callable[[str], str] = lambda _: "",
        planner: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        refresh: Callable[[list[str]], None] = lambda client_ids: None,
    ) -> None:
        """`seeds(path)` gives the torrents whose files overlap a path, with the content each
        puts on disk; `client_of(id)` is that torrent's client (ADR-0029: a seeded file moves
        and renames through its client); `allowed(path)` is the actor's right to touch it.
        `planner(item)` says what ranging one item does (renames, then the move), worked out when
        the item runs; `refresh(client ids)` reads those clients' torrents again."""
        self.storage, self.seeds, self.allowed, self.threaded = storage, seeds, allowed, threaded
        self.client_of = client_of
        self.link_root_of = link_root_of  # a client id -> its Link Folder ("" when none)
        self.planner, self.refresh = planner, refresh
        self.followed = followed  # settings and grants keyed by a path follow a moved folder
        self.tasks: dict[str, dict[str, Any]] = {}
        self._cancel: dict[str, threading.Event] = {}
        self._allowed: dict[str, Callable[[Path], bool]] = {}
        self._hooks: dict[str, tuple[Any, Any]] = {}
        self._lock = threading.RLock()

    # -- Submitting ---------------------------------------------------------------------

    def submit(
        self,
        kind: str,
        items: list[dict[str, str]],
        actor: str,
        conflict: str = "skip",
        apply_all: bool = True,
        allowed: Callable[[Path], bool] | None = None,
        label: str = "",
        on_item: Callable[[dict[str, Any], dict[str, Any]], None] | None = None,
        on_done: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        """`items`: `{"from": path, "to": path}` (the destination folder for move and copy, the
        new full path for rename); trash and mkdir take `from` only. "ranger" takes the item's
        path and the destination library (empty: the planner picks), and any other key a
        planner needs, kept in the item's `meta`. `on_item(task, item)` is called as each item
        ends and `on_done(task)` when the task does."""
        if kind not in {"move", "copy", "rename", "mkdir", "trash", "ranger"}:
            raise StorageError("Unknown operation.")
        if conflict not in CONFLICTS:
            raise StorageError("Unknown conflict choice.")
        identifier = uuid.uuid4().hex[:12]
        task = {
            "id": identifier, "kind": kind, "actor": actor, "state": "queued",
            "created": time.time(), "conflict": conflict, "apply_all": apply_all, "label": label,
            "items": [
                {"from": i["from"], "to": i.get("to", ""), "state": "queued", "progress": 0.0,
                 "reason": "", "verified": False, "note": "", "final": "", "undo": None,
                 "meta": {k: v for k, v in i.items() if k not in {"from", "to"}}}
                for i in items
            ],
        }  # fmt: skip
        with self._lock:
            self._allowed[identifier] = allowed or self.allowed
            self.tasks[identifier] = task
            self._cancel[identifier] = threading.Event()
            self._hooks[identifier] = (on_item, on_done)
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
                self._hook(identifier, 0, task, item)
                continue
            item["state"] = "running"
            started = time.monotonic()
            operation = self.storage.begin(
                task["kind"], task["actor"], {"from": item["from"], "to": item["to"]}, {}
            )
            try:
                self._item(task, item, stop.is_set, self._allowed.get(identifier, self.allowed))
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
            self._hook(identifier, 0, task, item)
        states = {i["state"] for i in task["items"]}
        task["state"] = "done" if states <= {"done", "skipped"} else (
            "cancelled" if "cancelled" in states else "failed"
        )  # fmt: skip
        self._hook(identifier, 1, task)

    def _hook(self, identifier: str, which: int, *args: Any) -> None:
        """Tell whoever queued the task how it went; a hook that fails never stops the task."""
        call = self._hooks.get(identifier, (None, None))[which]
        if call is not None:
            try:
                call(*args)
            except Exception:  # noqa: BLE001 - the bookkeeping must not undo a finished item
                logger.warning("A task hook failed.", exc_info=True)

    def _guard(self, path: Path, allowed: Callable[[Path], bool] | None = None) -> Path:
        self.storage.under_roots(path)
        if not (allowed or self.allowed)(path):
            raise StorageError(f"You may not touch {path}.")
        return path

    def _item(self, task: dict[str, Any], item: dict[str, Any], cancelled, allowed) -> None:
        kind, source = task["kind"], Path(item["from"])
        if kind == "ranger":
            return self._ranger(task, item, cancelled, allowed)
        if kind == "mkdir":
            target = self._guard(source, allowed)
            target.mkdir(parents=True, exist_ok=False)
            item.update(final=str(target), verified=target.is_dir(), undo=None)
            return
        self._guard(source, allowed)
        if not os.path.lexists(source):
            raise StorageError(f"{source} does not exist.")
        if kind == "trash":
            self._unseed(source, task["actor"])
            stored = self.storage.trash(source, task["actor"])
            item.update(verified=True, final=stored["from"], undo={"restore": stored["id"]})
            return
        target = Path(item["to"])
        if kind in {"move", "copy"}:
            self._guard(target, allowed)
            if not target.is_dir():
                raise StorageError(f"{target} is not a folder.")
            target = target / source.name
        else:  # rename
            self._guard(target.parent, allowed)
        if source == target or (source.is_dir() and target.is_relative_to(source)):
            raise StorageError("The destination is the source or inside it.")
        if os.path.lexists(target):
            chosen = self._conflict(task, item, source, target)
            if chosen is None:
                return
            target = chosen
        self._transfer(kind, source, target, item, cancelled)

    # -- Ranger: rename to the library's template, then move, in one pass (#223) -------------

    def _ranger(self, task: dict[str, Any], item: dict[str, Any], cancelled, allowed) -> None:
        """Rename an item's files to its library's template inside their own folder, then move
        the result into the library, each step through the client when a torrent seeds it. Any
        failure puts the names back: nothing is left half done."""
        if self.planner is None:
            raise StorageError("Nothing plans the ranging.")
        plan = self.planner({**item["meta"], "from": item["from"], "to": item["to"]})
        item["meta"]["plan"] = plan
        if plan.get("error"):
            raise StorageError(plan["error"])
        destination, new_top = Path(plan["dest"]), Path(plan["new_top"])
        landed = destination / new_top.name
        steps = [
            r for r in plan["renames"]
            if os.path.lexists(r["from"]) or not os.path.lexists(r["to"])
        ]  # fmt: skip
        if not steps and not os.path.lexists(new_top) and os.path.lexists(landed):
            item.update(verified=True, final=str(landed), progress=1.0, note="Déjà rangé")
            return
        if plan.get("resumed") and os.path.lexists(new_top) and os.path.lexists(landed):
            self._discard(landed)  # the copy a stop interrupted: it is made again
        clients = sorted({info["client_id"] for _, info in self.seeds(Path(item["from"]))})
        done: list[dict[str, str]] = []
        rename = {"kind": "rename", "actor": task["actor"], "conflict": "skip"}
        try:
            for step in steps:
                if cancelled():
                    raise InterruptedError("cancelled")
                part = {"from": step["from"], "to": step["to"], "state": "running", "note": ""}
                self._item(rename, part, cancelled, allowed)
                if part["state"] == "skipped":
                    raise StorageError(f"« {Path(step['to']).name} » existe déjà.")
                done.append(step)
            if done and clients:
                self.refresh(clients)
            move = {"kind": "move", "actor": task["actor"], "conflict": "skip"}
            part = _Mirror(item, {"from": str(new_top), "to": str(destination), "state": "running"})
            self._item(move, part, cancelled, allowed)
            if part["state"] == "skipped":
                raise StorageError(f"« {new_top.name} » existe déjà dans {destination.name}.")
        except BaseException:
            for step in reversed(done):
                back = {"from": step["to"], "to": step["from"], "state": "running", "note": ""}
                try:
                    if clients:
                        self.refresh(clients)
                    self._item(rename, back, cancelled, allowed)
                except Exception:  # noqa: BLE001 - put every other name back too
                    logger.warning("Could not put %s back.", step["from"], exc_info=True)
            raise
        item.update(
            verified=part.get("verified", True),
            final=str(landed),
            progress=1.0,
            undo=None,
            note=part.get("note") or "Rangé",
        )
        if clients:
            self.refresh(clients)

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
        if kind != "copy" and (seeds := self.seeds(source)):
            return self._seeded(kind, source, target, seeds, item, cancelled)
        target.parent.mkdir(parents=True, exist_ok=True)
        same_disk = same_device(source, target.parent)
        if kind == "rename" or (kind == "move" and same_disk):
            os.rename(source, target)
            if kind == "rename":
                self._prune(source.parent, target)
            if target.is_dir():
                self.followed(source, target)
            item.update(verified=target.exists() and not source.exists(), final=str(target),
                        undo={"rename": [str(target), str(source)]}, note="instantané")  # fmt: skip
            return
        self._copy(source, target, item, cancelled)
        item.update(final=str(target), verified=True)
        if kind == "move":  # copied and verified: only now does the source go to its trash
            if target.is_dir():
                self.followed(source, target)
            stored = self.storage.trash(source, "system", "Déplacé vers un autre disque")
            item["undo"] = {"restore": stored["id"], "remove": str(target)}

    # -- Files a torrent seeds: through its client (ADR-0029) -----------------------------

    def _owner(self, source: Path, seeds, what: str) -> tuple[Path, dict[str, Any], Any]:
        """The one torrent a path belongs to, and its client; anything else is refused."""
        if len(seeds) != 1:
            raise StorageError(
                f"{source.name} holds the files of {len(seeds)} torrents: {what} them one by one."
            )
        top, info = seeds[0]
        client = self.client_of(info["client_id"])
        if client is None:
            raise StorageError(f"The Torrent Client {info['client']} is not reachable.")
        return top, info, client

    # -- Files several torrents share (ADR-0029, rule 3, #222) -------------------------------

    def _shared(self, kind: str, source: Path, target: Path, seeds, item, cancelled) -> None:
        """Move or rename once, through the first torrent's client; every other torrent on the
        same files is then re-pointed to the new place and rechecked, through symlinks in its
        client's Link Folder when its names or folders differ. Any failure puts every torrent
        back at its old place, still seeding."""
        from torrentlinker.storage_moves import StorageMoveError

        group = []
        for top, info in seeds:
            client = self.client_of(info["client_id"])
            if client is None:
                raise StorageError(f"The Torrent Client {info['client']} is not reachable.")
            group.append((top, info, client))
        top, info, client = group[0]
        others = [self._plan_other(kind, source, target, group[0], g) for g in group[1:]]
        item["torrents"] = [i["name"] for _, i, _ in group]
        moved = False
        done: list[tuple[Any, dict[str, Any], Path, Path | None]] = []
        try:
            try:
                if kind == "rename":
                    self._rename_in_client(source, target, info, client, item)
                else:
                    self._move_in_client(source, target, top, info, client, item, cancelled)
            except StorageMoveError as error:
                raise StorageError(str(error)) from error
            moved = True
            for other, other_info, where, links in others:
                old = Path(other_info["save_path"])
                done.append((other, other_info, old, links))
                self._repoint_checked(other, other_info["hash"], where)
            item["undo"] = None  # the others were re-pointed: undo would leave them behind
            names = ", ".join(i["client"] for _, i, _, _ in others)
            item["note"] = (
                f"{len(group)} torrents partagent ces fichiers : tous continuent ({names})"
            )
        except BaseException:
            for other, other_info, old, _links in reversed(done):
                try:
                    self._point(other, other_info["hash"], old)
                    other.start(other_info["hash"])
                except Exception:  # noqa: BLE001 - keep putting the others back
                    pass
            for _, _, _, links in others:
                if links is not None:
                    shutil.rmtree(links, ignore_errors=True)
            if moved:
                self._shared_back(kind, source, target, info, client)
            raise

    def _plan_other(self, kind, source: Path, target: Path, primary, member):
        """Where another torrent of the group points after the move: (client, info, folder, the
        links folder to remove on a rollback). Refused up front when a Link Folder is needed
        and not set."""
        from torrentlinker.storage_moves import refusal

        _, first, _ = primary
        _, info, client = member
        torrent = client.torrent(info["hash"])
        if torrent is None:
            raise StorageError(f"{info['name']} is no longer in {info['client']}.")
        if (why := refusal(torrent)) is not None:
            raise StorageError(why)
        same = (
            kind == "move" and Path(info["save_path"]) == Path(first["save_path"]) == source.parent
        )
        if same:
            return client, info, target.parent, None
        root = self.link_root_of(info["client_id"])
        if not root:
            raise StorageError(
                f"Dossier de liens requis : {info['name']} ({info['client']}) garde ses noms, "
                "il faut un Dossier de liens pour ce client (Paramètres)."
            )
        links = Path(tempfile.mkdtemp(prefix="torrentlinker-", dir=root))
        try:
            for name in torrent.files:
                old = Path(info["save_path"]) / name
                rel = old.relative_to(source) if old != source else Path()
                link = links / name
                link.parent.mkdir(parents=True, exist_ok=True)
                link.symlink_to(target / rel if str(rel) != "." else target)
        except Exception:
            shutil.rmtree(links, ignore_errors=True)
            raise
        return client, info, links, links

    def _point(self, client, hash: str, folder: Path) -> None:
        repoint = getattr(client, "repoint", None)
        if repoint is not None:
            data = getattr(client, "export_torrent", lambda h: None)(hash)
            repoint(hash, str(folder), data)
        else:
            client.set_location(hash, str(folder))

    def _repoint_checked(self, client, hash: str, folder: Path) -> None:
        from torrentlinker.storage_moves import _wait

        client.pause(hash)
        self._point(client, hash, folder)
        client.recheck(hash)
        _wait(client, hash, lambda t: "checking" not in t.state.lower(), 600)
        after = client.torrent(hash, with_files=False)
        if after is None or after.progress < 1:
            raise StorageError("The client does not find all the pieces at the new place.")
        client.start(hash)

    def _shared_back(self, kind, source: Path, target: Path, info, client) -> None:
        from torrentlinker.storage_moves import move_torrent, rename_in_torrent

        try:
            save = Path(info["save_path"])
            if kind == "rename":
                rename_in_torrent(
                    client, info["hash"], target.relative_to(save).as_posix(),
                    source.relative_to(save).as_posix(),
                )  # fmt: skip
            else:
                move_torrent(client, info["hash"], save)
        except Exception:  # noqa: BLE001 - the original error is the one to report
            pass

    def _unseed(self, source: Path, actor: str) -> None:
        """Trashing seeded files takes the torrent out of its client, without its data."""
        if not (seeds := self.seeds(source)):
            return
        top, info, client = self._owner(source, seeds, "trash")
        if top != source:
            raise StorageError(f"{source.name} is part of a torrent: trash the torrent as a whole.")
        client.remove(info["hash"], delete_files=False)

    def _seeded(self, kind: str, source: Path, target: Path, seeds, item, cancelled) -> None:
        from torrentlinker.storage_moves import StorageMoveError

        seeds = list({info["hash"]: (top, info) for top, info in seeds}.values())
        if len(seeds) > 1 and all(top == source for top, _ in seeds):
            return self._shared(kind, source, target, seeds, item, cancelled)
        top, info, client = self._owner(source, seeds, kind)
        try:
            if kind == "rename":
                self._rename_in_client(source, target, info, client, item)
            else:
                self._move_in_client(source, target, top, info, client, item, cancelled)
        except StorageMoveError as error:
            raise StorageError(str(error)) from error

    def _rename_in_client(self, source: Path, target: Path, info, client, item) -> None:
        from torrentlinker.storage_moves import rename_in_torrent

        save = Path(info["save_path"])
        if not (target.is_relative_to(save) and source.is_relative_to(save)):
            raise StorageError("A seeded file is renamed inside its torrent's folder.")
        old, new = source.relative_to(save).as_posix(), target.relative_to(save).as_posix()
        rename_in_torrent(client, info["hash"], old, new)
        self._prune(source.parent, target)
        item.update(
            verified=target.exists() and not source.exists(), final=str(target),
            undo={"client": {"id": info["client_id"], "hash": info["hash"],
                             "old": old, "new": new}},
            note=f"Renommé dans le client ({info['client']})",
        )  # fmt: skip
        if not item["verified"]:
            raise StorageError(f"{info['client']} did not rename {source.name} on disk.")

    def _move_in_client(self, source, target, top, info, client, item, cancelled) -> None:
        from torrentlinker.storage_moves import move_torrent

        if top != source:
            raise StorageError(f"{source.name} is part of a torrent: move the torrent as a whole.")
        if target.name != source.name:
            raise StorageError(
                f"A seeded torrent keeps its name: {target.name} is taken. Skip it or replace it."
            )
        destination, save = target.parent, Path(info["save_path"])
        destination.mkdir(parents=True, exist_ok=True)
        if same_device(source, destination):
            move_torrent(client, info["hash"], destination)
            item.update(
                final=str(target), verified=target.exists() and not source.exists(),
                undo={"client": {"id": info["client_id"], "hash": info["hash"], "back": str(save)}},
                note=f"Déplacé par {info['client']} : instantané, il continue de partager",
            )  # fmt: skip
        elif getattr(client, "repoint", None) is None:
            # The client copies across disks itself; the app rechecks what it wrote.
            move_torrent(client, info["hash"], destination)
            self._recheck(client, info["hash"], source, target, save)
            name = info["client"]
            item.update(final=str(target), verified=True,
                        note=f"Copié par {name}, revérifié : il partage depuis ici")  # fmt: skip
        else:
            self._copy_then_repoint(source, target, info, client, item, cancelled)
        if not item["verified"]:
            raise StorageError(f"{info['client']} did not move {source.name}.")

    def _prune(self, folder: Path, kept: Path) -> None:
        """A rename into a new folder leaves the old one empty: that empty folder goes."""
        while (
            folder not in self.storage.roots
            and not kept.is_relative_to(folder)
            and folder.is_dir()
            and not any(folder.iterdir())
        ):
            folder.rmdir()
            folder = folder.parent

    @staticmethod
    def _recheck(client, hash: str, source: Path, target: Path, save: Path) -> None:
        from torrentlinker.storage_moves import StorageMoveError, _wait, move_torrent

        recheck = getattr(client, "recheck", None)
        if recheck is not None:
            recheck(hash)
            _wait(client, hash, lambda t: "checking" not in t.state.lower(), 300)
        after = client.torrent(hash, with_files=False)
        if after is None or after.progress < 1:
            try:
                move_torrent(client, hash, save)
            except StorageMoveError:
                pass
            raise StorageError("The client does not find all the pieces at the destination.")

    def _copy_then_repoint(self, source, target, info, client, item, cancelled) -> None:
        """Copy and verify, point the client at the copy and recheck; only then does the
        source go to its disk's trash. Any failure leaves the torrent seeding at the source."""
        from torrentlinker.storage_moves import StorageMoveError, _found, _wait

        torrent = _found(client, info["hash"])
        data = getattr(client, "export_torrent", lambda h: None)(info["hash"])
        self._copy(source, target, item, cancelled)
        client.pause(info["hash"])
        try:
            client.repoint(info["hash"], str(target.parent), data)
            client.recheck(info["hash"])
            _wait(client, info["hash"], lambda t: "checking" not in t.state.lower(), 600)
            after = client.torrent(info["hash"], with_files=False)
            if after is None or after.progress < 1:
                raise StorageMoveError("The client does not find all the pieces at the copy.")
        except Exception:
            client.repoint(info["hash"], str(torrent.save_path), data)
            self._discard(target)
            raise
        finally:
            client.start(info["hash"])
        stored = self.storage.trash(source, "system", "Déplacé vers un autre disque")
        item.update(
            final=str(target), verified=True, undo=None,
            note=f"Copié, vérifié : {info['client']} partage depuis la copie",
        )  # fmt: skip
        item["trashed"] = stored["id"]

    @staticmethod
    def _discard(copy: Path) -> None:
        """Remove the copy this task made when it could not be used."""
        if copy.is_dir():
            shutil.rmtree(copy, ignore_errors=True)
        else:
            copy.unlink(missing_ok=True)

    def _copy(self, source: Path, target: Path, item, cancelled) -> None:
        total = max(1, sum(f.stat().st_size for f in self._files(source)))
        done = 0
        began = time.monotonic()
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
                        # What is left, at the speed so far (the verification is not counted).
                        item["eta"] = round((time.monotonic() - began) * (total - done) / done)
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
        if "client" in action:
            result = self._undo_in_client(action["client"])
        elif "rename" in action:
            now, before = Path(action["rename"][0]), Path(action["rename"][1])
            if os.path.lexists(before) or not os.path.lexists(now):
                raise StorageError("The files changed since: nothing was undone.")
            os.rename(now, before)
            if before.is_dir():
                self.followed(now, before)
            result = str(before)
        else:
            if "remove" in action and (copy := Path(action["remove"])).exists():
                self.storage.trash(copy, actor, "Déplacement annulé")
            result = self.storage.restore(action["restore"], actor)
        item.update(state="undone", undo=None)
        return result

    def _undo_in_client(self, action: dict[str, Any]) -> str:
        from torrentlinker.storage_moves import StorageMoveError, move_torrent, rename_in_torrent

        client = self.client_of(action["id"])
        if client is None:
            raise StorageError("The Torrent Client is not reachable.")
        try:
            if "back" in action:
                move_torrent(client, action["hash"], Path(action["back"]))
                return action["back"]
            rename_in_torrent(client, action["hash"], action["new"], action["old"])
        except StorageMoveError as error:
            raise StorageError(str(error)) from error
        return action["old"]
