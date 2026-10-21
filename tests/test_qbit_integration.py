"""Reseed against a real qBittorrent. Opt-in: point TL_QBIT_SANDBOX at a throwaway instance.

    TL_QBIT_SANDBOX=http://127.0.0.1:18080 pytest tests/test_qbit_integration.py

The instance must accept localhost without login. Every torrent added is removed at the
end (data kept). Library files are copies under a temp folder; their bytes are checked
to be unchanged.
"""

import hashlib
import os
import shutil
import time
from pathlib import Path

import pytest

from tests.torrents import make_torrent
from torrentlinker.domain import ItemState, LibraryFolder
from torrentlinker.matching import match
from torrentlinker.qbit import QbitApi
from torrentlinker.reconcile import classify
from torrentlinker.reseed import (
    PARTIAL,
    VERIFYING,
    Outcome,
    check_verifications,
    start_reseed,
)
from torrentlinker.scan import scan
from torrentlinker.store import Store
from torrentlinker.torrent_meta import read_torrent

HOST = os.environ.get("TL_QBIT_SANDBOX", "")
pytestmark = pytest.mark.skipif(not HOST, reason="set TL_QBIT_SANDBOX")

EBOOK = Path(os.environ.get("TL_EBOOK", "/windocs/E-Book/Le joueur d'echecs - Stefan Zweig.epub"))
SCENE = "Le.Joueur.D'echecs.Stefan.Zweig.2013.FR.[EPUB]-NOTAG"


@pytest.fixture
def qbit():  # type: ignore[no-untyped-def]
    api = QbitApi(HOST, "", "")
    before = {t.hash for t in api.torrents()}
    yield api
    for t in api.torrents():
        if t.hash not in before:
            api.remove(t.hash)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def settle(qbit: QbitApi, store: Store, timeout: float = 60) -> list[Outcome]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        # A recheck right after the add is quick; RECHECK_GRACE only matters for failures.
        outcomes = check_verifications(qbit, store, now=lambda: time.time() + 60)
        if outcomes:
            return outcomes
        time.sleep(0.5)
    pytest.fail("Verification did not finish")


def library_with_ebook(tmp_path: Path) -> Path:
    lib = tmp_path / "E-Book"
    lib.mkdir()
    if EBOOK.exists():
        shutil.copy2(EBOOK, lib / EBOOK.name)
    else:
        (lib / EBOOK.name).write_bytes(os.urandom(67163))
    return lib


def scene_torrent(tmp_path: Path, content: bytes) -> bytes:
    scene = tmp_path / "scene" / f"{SCENE}.epub"
    scene.parent.mkdir()
    scene.write_bytes(content)
    return make_torrent(scene)


def test_full_match_under_another_name_is_renamed_verified_and_started(
    tmp_path: Path, qbit: QbitApi
) -> None:
    lib = library_with_ebook(tmp_path)
    [item] = scan(LibraryFolder(lib))
    before = digest(item.path)
    meta = read_torrent(scene_torrent(tmp_path, item.path.read_bytes()))
    m = match(item, meta.files)
    assert m is not None and m.is_full and m.renames
    store = Store(tmp_path / "s.db")

    h = start_reseed(qbit, store, item, meta, m, meta.infohash)
    [outcome] = settle(qbit, store)

    assert outcome.verified and outcome.started
    t = qbit.torrent(h)
    assert t is not None
    assert t.files == {item.path.name: item.size}
    assert VERIFYING not in t.tags
    assert classify([item], qbit.torrents()) == {item.path: ItemState.SEEDED}
    assert digest(item.path) == before


def test_partial_match_is_verified_on_local_pieces_and_left_stopped(
    tmp_path: Path, qbit: QbitApi
) -> None:
    pack = tmp_path / "scene" / "Zweig.Pack"
    pack.mkdir(parents=True)
    (pack / "a.epub").write_bytes(os.urandom(40000))
    (pack / "b.epub").write_bytes(os.urandom(40000))
    meta = read_torrent(make_torrent(pack))
    lib = tmp_path / "lib"
    (lib / "Zweig").mkdir(parents=True)
    shutil.copy2(pack / "a.epub", lib / "Zweig" / "a.epub")
    [item] = scan(LibraryFolder(lib))
    before = digest(lib / "Zweig" / "a.epub")
    m = match(item, meta.files)
    assert m is not None and not m.is_full
    store = Store(tmp_path / "s.db")

    h = start_reseed(qbit, store, item, meta, m, meta.infohash)
    [outcome] = settle(qbit, store)

    assert outcome.verified and not outcome.started
    t = qbit.torrent(h)
    assert t is not None and PARTIAL in t.tags
    assert t.state.startswith(("stopped", "paused"))  # 5.x and 4.x names
    assert not (lib / "Zweig" / "b.epub").exists()
    assert digest(lib / "Zweig" / "a.epub") == before


def test_same_size_but_different_data_fails_and_keeps_the_file(
    tmp_path: Path, qbit: QbitApi
) -> None:
    lib = library_with_ebook(tmp_path)
    [item] = scan(LibraryFolder(lib))
    before = digest(item.path)
    meta = read_torrent(scene_torrent(tmp_path, os.urandom(item.size)))
    store = Store(tmp_path / "s.db")

    h = start_reseed(qbit, store, item, meta, match(item, meta.files), meta.infohash)  # type: ignore[arg-type]
    [outcome] = settle(qbit, store)

    assert not outcome.verified
    assert qbit.torrent(h) is None
    assert digest(item.path) == before
    assert store.rejections(item.path)
