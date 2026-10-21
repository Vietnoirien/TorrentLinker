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
        # Real clock: qBittorrent may sit at 0% for a second or more before a requested
        # check starts, and that must not count as a failed Verification.
        outcomes = check_verifications(qbit, store)
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
    listing = sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*"))
    assert (lib / "Zweig" / "a.epub").exists(), (listing, t)
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


def test_an_api_key_authenticates_and_a_wrong_one_is_refused(qbit: QbitApi) -> None:
    import qbittorrentapi

    from torrentlinker.qbit import is_api_key

    version = tuple(int(x) for x in qbit.check().lstrip("v").split(".")[:2])
    if version < (5, 2):
        pytest.skip("API keys need qBittorrent 5.2+")
    key = qbit.rotate_api_key()
    try:
        assert is_api_key(key)
        assert QbitApi(HOST, "", "", api_key=key).check() == qbit.check()
        # The sandbox lets localhost in without login, but a key that is sent is checked.
        wrong = "qbt_" + ("A" if key[4] != "A" else "B") * 28
        with pytest.raises(qbittorrentapi.exceptions.APIError):
            QbitApi(HOST, "", "", api_key=wrong).check()
    finally:
        qbit.delete_api_key()


def test_a_plan_torrent_downloads_into_its_download_folder_tagged_zen(
    tmp_path: Path, qbit: QbitApi
) -> None:
    from torrentlinker.plan import PlanCandidate
    from torrentlinker.send import ZEN_TAG, Refused, send_one

    src = tmp_path / "elsewhere" / "Zen.Release"
    src.mkdir(parents=True)
    (src / "a.bin").write_bytes(os.urandom(40000))
    data = make_torrent(src)
    meta = read_torrent(data)
    folder = tmp_path / "dl"

    h = send_one(qbit, PlanCandidate(meta.infohash, meta.name, 40000, 1, 1, folder, 1), data)

    t = qbit.torrent(h)
    assert t is not None
    assert t.save_path == folder
    assert ZEN_TAG in t.tags
    assert not t.state.startswith(("stopped", "paused"))  # started, downloading

    other = tmp_path / "dl2"
    (other / "Zen.Release").mkdir(parents=True)
    (other / "Zen.Release" / "a.bin").write_bytes(b"mine")
    qbit.remove(h)
    for _ in range(50):  # removal is asynchronous too
        if qbit.torrent(h) is None:
            break
        time.sleep(0.1)
    with pytest.raises(Refused, match="overwrite"):
        send_one(qbit, PlanCandidate(meta.infohash, meta.name, 40000, 1, 1, other, 1), data)
    assert qbit.torrent(h) is None  # never added
    assert (other / "Zen.Release" / "a.bin").read_bytes() == b"mine"


AUTH_HOST = os.environ.get("TL_QBIT_SANDBOX_AUTH", "")
AUTH_PASSWORD_FILE = os.environ.get("TL_QBIT_SANDBOX_AUTH_PASSWORD_FILE", "")


@pytest.mark.skipif(
    not (AUTH_HOST and AUTH_PASSWORD_FILE),
    reason="set TL_QBIT_SANDBOX_AUTH and TL_QBIT_SANDBOX_AUTH_PASSWORD_FILE",
)
def test_tasks_starting_together_share_one_login() -> None:
    import threading

    password = Path(AUTH_PASSWORD_FILE).read_text().strip()
    for _ in range(5):
        api = QbitApi(AUTH_HOST, "sandbox", password)  # a fresh app start: no session yet
        errors: list[str] = []

        def first_call(api: QbitApi = api, errors: list[str] = errors) -> None:
            try:
                api.torrents(with_files=False)
            except Exception as e:  # noqa: BLE001 - collected for the assertion
                errors.append(f"{type(e).__name__}: {e}")

        threads = [threading.Thread(target=first_call) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
