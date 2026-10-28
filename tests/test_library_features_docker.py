"""Opt-in Library acceptance against an isolated qBittorrent with synthetic media only."""

import os
import threading
import time
import uuid
from pathlib import Path

import pytest

from tests.torrents import make_torrent
from torrentlinker.domain import LibraryFolder, PathMapping
from torrentlinker.indexer import Candidate
from torrentlinker.library import build_library
from torrentlinker.matching import IgnoreList
from torrentlinker.qbit import QbitApi
from torrentlinker.reseed import check_verifications
from torrentlinker.review import remember_candidates
from torrentlinker.torrent_meta import read_torrent
from torrentlinker.web.library import Library
from torrentlinker.web.security import ServerSecrets
from torrentlinker.web.setup import Setup

HOST = os.getenv("TL_QBIT_DOCKER", "")
ROOT = Path(os.getenv("TL_QBIT_DOCKER_DATA", "/nonexistent"))
pytestmark = pytest.mark.skipif(not HOST, reason="requires disposable TL_QBIT_DOCKER")


@pytest.fixture
def context(tmp_path):
    root = ROOT / uuid.uuid4().hex
    root.mkdir()
    config = tmp_path / "config"
    config.mkdir()
    api = QbitApi(HOST, "", "")
    setup = Setup(config, (root,), ServerSecrets(config), lambda *args: api)
    setup.configured = True
    setup.settings.library_folders = [LibraryFolder(root)]
    setup.settings.path_mappings = [PathMapping(str(ROOT), "/data")]
    library = Library(setup)
    before = {t.hash for t in api.torrents()}
    try:
        yield library, root, api
    finally:
        for torrent in api.torrents():
            if torrent.hash not in before:
                api.remove(torrent.hash)


def test_real_client_checks_copy_while_stopped_then_requires_explicit_start(context):
    library, root, api = context
    video = root / "sample.mkv"
    original = os.urandom(1024 * 1024)
    video.write_bytes(original)
    data = make_torrent(video)
    meta = read_torrent(data)
    changed = b"X" * 128 + original[128:]
    video.write_bytes(changed)
    library.entries = build_library(
        library.setup.settings.library_folders, [], IgnoreList.default()
    )
    candidate = Candidate(
        "Sample",
        len(original),
        "https://example.invalid/download",
        seeders=2,
        infohash=meta.infohash,
    )
    preview = library.diagnose(str(video), candidate, data, threading.Event())
    prepared = library.prepare_repair(
        preview["id"], str(root), threading.Event(), experimental=True
    )
    assert prepared["status"] == "checking"
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        row = library.refresh_repair(preview["id"])
        if row["status"] == "ready":
            break
        time.sleep(0.2)
    assert row["status"] == "ready", row
    assert api.torrent(meta.infohash).state in {"stoppedDL", "pausedDL"}
    # A new service instance reads pending state without starting a torrent.
    restarted = Library(library.setup)
    assert restarted.repairs().rows()[0]["status"] == "ready"
    assert api.torrent(meta.infohash).state in {"stoppedDL", "pausedDL"}
    started = restarted.start_repair(preview["id"], preview["id"])
    assert started["status"] == "downloading"
    api.pause(meta.infohash)
    assert video.read_bytes() == changed
    assert Path(prepared["copy"]).stat().st_ino != video.stat().st_ino


def test_real_client_reseeds_pack_from_two_folders_without_copying(context, monkeypatch):
    library, root, api = context
    original = root / "TargetPack"
    original.mkdir()
    for i in (1, 2):
        (original / f"episode{i}.mkv").write_bytes(os.urandom(100000 + i))
    data = make_torrent(original)
    meta = read_torrent(data)
    paths = []
    before = {}
    for i in (1, 2):
        folder = root / f"Season{i}"
        folder.mkdir()
        path = (original / f"episode{i}.mkv").rename(folder / f"local{i}.mkv")
        paths.append(str(folder))
        before[path] = path.read_bytes()
    original.rmdir()
    library.entries = build_library(
        library.setup.settings.library_folders, [], IgnoreList.default()
    )
    selection = library.combine(paths, threading.Event())
    candidate = Candidate(
        meta.name,
        sum(meta.files.values()),
        "https://example.invalid/dl",
        infohash=meta.infohash,
        metadata={"discovery": "compatible"},
    )

    class Indexer:
        def fetch_torrent(self, candidate):
            return data

        def redact(self, value):
            return value

        def unredact(self, value):
            return value

    indexer = Indexer()
    monkeypatch.setattr(library.setup, "indexer", lambda: indexer)
    remember_candidates(library.setup.store, indexer, Path(selection["path"]), [candidate])
    result = library.reseed(selection["path"], meta.infohash, threading.Event())
    assert result["status"] == "verifying"
    deadline = time.monotonic() + 30
    outcomes = []
    while time.monotonic() < deadline:
        outcomes = check_verifications(library.client(), library.setup.store)
        if outcomes:
            break
        time.sleep(0.2)
    assert outcomes and outcomes[0].verified, outcomes
    assert all(path.read_bytes() == content for path, content in before.items())
    assert set(api.torrent(meta.infohash).files) == {"Season1/local1.mkv", "Season2/local2.mkv"}
