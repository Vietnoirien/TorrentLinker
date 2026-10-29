"""Prove a Path Mapping with disposable content verified by a stopped torrent."""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

import torf

from torrentlinker.qbit import Qbit

PROBE_TIMEOUT = 30.0
CHECKING = {"checkingUP", "checkingDL", "checkingResumeData", "queuedForChecking", "moving"}


def verify_folder(client: Qbit, local: Path, remote: str) -> None:
    """Create only our own file, check it without starting, and clean both sides.

    A unique random payload gives this test its own info hash. Removal always keeps
    client data; only the file created here is unlinked locally.
    """
    try:
        fd, name = tempfile.mkstemp(prefix=".torrentlinker-path-check-", suffix=".bin", dir=local)
    except OSError as error:
        raise ValueError(
            "The Path Mapping has no seeded sample and TorrentLinker cannot create a temporary "
            "file in this folder. Allow write access to the mounted folder "
            "to check it automatically."
        ) from error
    path = Path(name)
    identity = os.fstat(fd)
    hash = ""
    attempted = False
    try:
        with os.fdopen(fd, "wb") as stream:
            # Only random disposable bytes are exposed. The daemon may run as another
            # UID on a NAS or in Docker; mkstemp's 0600 would falsely reject that mapping.
            if hasattr(os, "fchmod"):
                os.fchmod(stream.fileno(), 0o644)
            else:
                os.chmod(path, 0o644)
            stream.write(os.urandom(16384))
            stream.flush()
            os.fsync(stream.fileno())
        torrent = torf.Torrent(path=path, private=True, piece_size=16384)
        torrent.generate()
        hash = str(torrent.infohash)
        # Never take ownership of an existing torrent, even on an improbable collision.
        if client.torrent(hash, with_files=False) is not None:
            raise ValueError(
                "The temporary Path Mapping verification torrent already exists. Retry the check."
            )
        attempted = True
        client.add(torrent.dump(), remote, [])  # Qbit.add's contract is stopped.
        client.recheck(hash)
        deadline = time.monotonic() + PROBE_TIMEOUT
        while time.monotonic() < deadline:
            current = client.torrent(hash, with_files=False)
            if current and current.state not in CHECKING and current.progress >= 1.0:
                return
            time.sleep(0.2)
        raise ValueError(
            "The Torrent Client could not verify the temporary file. Check the Path Mapping "
            "and the client's read permissions, then retry. No download was started."
        )
    except ValueError:
        raise
    except Exception as error:
        raise ValueError(
            "Path Mapping verification failed. Check the Torrent Client connection and "
            "folder permissions, then retry."
        ) from error
    finally:
        try:
            if attempted:
                try:
                    client.remove(hash, delete_files=False)
                    cleanup_deadline = time.monotonic() + 5
                    while client.torrent(hash, with_files=False) is not None:
                        if time.monotonic() >= cleanup_deadline:
                            raise ValueError("The temporary torrent is still present.")
                        time.sleep(0.1)
                except Exception as error:
                    raise ValueError(
                        f"Could not remove temporary verification torrent {hash}. "
                        "Remove it from the Torrent Client without deleting files, then retry."
                    ) from error
        finally:
            # A concurrently replaced file is not ours to delete.
            if path.exists():
                current_stat = path.lstat()
                if (current_stat.st_dev, current_stat.st_ino) == (identity.st_dev, identity.st_ino):
                    path.unlink()
