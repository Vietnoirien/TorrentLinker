"""Move or rename a seeded torrent's data through its Torrent Client (ADR-0029).

qBittorrent, Deluge and Transmission move and rename the files themselves. rTorrent and
µTorrent cannot, so the app stops the torrent, moves the files on disk, points the client
at the new place, rechecks and starts it again. Whatever fails, the torrent is started
again, at its old place when nothing moved or the move was undone.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from pathlib import Path, PurePosixPath

from torrentlinker.domain import Torrent
from torrentlinker.qbit import Qbit


class StorageMoveError(RuntimeError):
    """The move or rename did not happen; the message says why and where the torrent is."""


def refusal(torrent: Torrent) -> str | None:
    """Why this torrent's files must not move now, or None."""
    if any(
        t == "torrentlinker:verifying" or t.startswith("torrentlinker:link") for t in torrent.tags
    ):
        return "This torrent is under Reseed Verification or keeps its names through a Link Folder."
    if "checking" in torrent.state.lower():
        return "This torrent is being checked."
    return None


def _found(client: Qbit, hash: str) -> Torrent:
    torrent = client.torrent(hash)
    if torrent is None:
        raise StorageMoveError("The torrent is no longer in the Torrent Client.")
    if (why := refusal(torrent)) is not None:
        raise StorageMoveError(why)
    return torrent


def _wait(client: Qbit, hash: str, done: Callable[[Torrent], bool], timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while True:
        current = client.torrent(hash, with_files=False)
        if current is not None and done(current):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.1)


def _roots(torrent: Torrent) -> list[str]:
    """The top-level names the torrent owns inside its save path."""
    return sorted({PurePosixPath(name).parts[0] for name in torrent.files})


def _relocate_on_disk(torrent: Torrent, destination: Path) -> list[tuple[Path, Path]]:
    done: list[tuple[Path, Path]] = []
    destination.mkdir(parents=True, exist_ok=True)
    try:
        if destination.stat().st_dev != torrent.save_path.stat().st_dev:
            raise StorageMoveError(
                "Moving across disks is a copy: it goes through the transfer engine, not a rename."
            )
        for name in _roots(torrent):
            source, target = torrent.save_path / name, destination / name
            if os.path.lexists(target):
                raise StorageMoveError(f"{target} already exists.")
            os.rename(source, target)
            done.append((source, target))
    except Exception:
        for source, target in reversed(done):
            os.rename(target, source)
        raise
    return done


def move_torrent(
    client: Qbit,
    hash: str,
    destination: Path,
    *,
    torrent_file: Callable[[], bytes] | None = None,
    timeout: float = 60,
) -> None:
    """Move the torrent's data to `destination` (a folder, in this app's view of the paths)."""
    torrent = _found(client, hash)
    if torrent.save_path == destination:
        return
    relocate = getattr(client, "set_location", None)
    if relocate is not None:
        relocate(hash, str(destination))
        if not _wait(client, hash, lambda t: t.save_path == destination, timeout):
            raise StorageMoveError(
                f"The Torrent Client did not report {destination}; the torrent stays at "
                f"{torrent.save_path} until it does."
            )
        return
    repoint = getattr(client, "repoint", None)
    if repoint is None:
        raise StorageMoveError("This Torrent Client cannot move a torrent that is already added.")
    data = (
        torrent_file() if torrent_file else getattr(client, "export_torrent", lambda h: None)(hash)
    )
    client.pause(hash)
    moved: list[tuple[Path, Path]] = []
    try:
        moved = _relocate_on_disk(torrent, destination)
        repoint(hash, str(destination), data)
        client.recheck(hash)
        if not _wait(client, hash, lambda t: "checking" not in t.state.lower(), timeout):
            raise StorageMoveError("The recheck did not finish in time.")
        after = client.torrent(hash, with_files=False)
        if after is None or after.progress < 1:
            raise StorageMoveError("The Torrent Client does not find the files at the new place.")
    except Exception as error:
        for source, target in reversed(moved):
            if os.path.lexists(target) and not os.path.lexists(source):
                os.rename(target, source)
        if moved:
            try:
                repoint(hash, str(torrent.save_path), data)
            except Exception:  # noqa: BLE001 - the original error matters more
                pass
        raise (
            error
            if isinstance(error, StorageMoveError)
            else StorageMoveError(f"{error}. The torrent stays at {torrent.save_path}.")
        ) from error
    finally:
        client.start(hash)


def rename_in_torrent(
    client: Qbit,
    hash: str,
    old: str,
    new: str,
    *,
    torrent_file: Callable[[], bytes] | None = None,
    timeout: float = 60,
) -> None:
    """Rename a path inside the torrent (relative to its save path) in its Torrent Client.

    rTorrent and µTorrent can only follow a rename of the torrent's own folder: that is a
    disk rename, then the same re-point and recheck as a move."""
    torrent = _found(client, hash)
    if getattr(client, "repoint", None) is None:
        client.rename_file(hash, old, new)
        return
    old_parts, new_parts = PurePosixPath(old).parts, PurePosixPath(new).parts
    if len(old_parts) != len(new_parts) or old_parts[1:] != new_parts[1:]:
        raise StorageMoveError(
            "This Torrent Client cannot rename files inside a torrent: only its folder. "
            "Keep the names through a Link Folder instead."
        )
    if any(
        len(PurePosixPath(n).parts) < 2 or PurePosixPath(n).parts[0] != old_parts[0]
        for n in torrent.files
    ):
        raise StorageMoveError("Only a torrent's own folder can be renamed in this Torrent Client.")
    client.pause(hash)
    source, target = torrent.save_path / old_parts[0], torrent.save_path / new_parts[0]
    done = False
    try:
        if os.path.lexists(target):
            raise StorageMoveError(f"{target} already exists.")
        os.rename(source, target)
        done = True
        data = (
            torrent_file()
            if torrent_file
            else getattr(client, "export_torrent", lambda h: None)(hash)
        )
        client.repoint(hash, str(torrent.save_path), data, new_parts[0])  # type: ignore[attr-defined]
        client.recheck(hash)
        _wait(client, hash, lambda t: "checking" not in t.state.lower(), timeout)
    except Exception as error:
        if done and os.path.lexists(target) and not os.path.lexists(source):
            os.rename(target, source)
        raise StorageMoveError(f"{error}. The torrent keeps its old name.") from error
    finally:
        client.start(hash)
