"""Optional live test against a dedicated, empty µTorrent Classic instance.

Set TL_UTORRENT_CONNECTION to a JSON file containing url, username and password,
and TL_UTORRENT_DATA to the local view of its default download folder. The test
uses a unique subfolder and removes only its own torrent jobs, keeping files.
"""

import hashlib
import json
import os
import time
from pathlib import Path
from uuid import uuid4

import pytest

from tests.torrents import make_torrent
from torrentlinker.domain import LocalItem, PathMapping
from torrentlinker.matching import Match
from torrentlinker.paths import MappedQbit, PathMapper
from torrentlinker.reseed import TAG, VERIFYING, check_verifications, start_reseed
from torrentlinker.store import SavedUpload, Store
from torrentlinker.torrent_meta import read_torrent
from torrentlinker.upload import PreparedUpload, UploadFile, seed_upload
from torrentlinker.utorrent import UtorrentApi, _path_module

pytestmark = pytest.mark.skipif(
    not os.environ.get("TL_UTORRENT_CONNECTION") or not os.environ.get("TL_UTORRENT_DATA"),
    reason="set TL_UTORRENT_CONNECTION and TL_UTORRENT_DATA for a dedicated test client",
)


@pytest.mark.parametrize("multi", [False, True])
def test_classic_live_management_and_download_paths_preserve_fixture_bytes(multi):
    connection = json.loads(Path(os.environ["TL_UTORRENT_CONNECTION"]).read_text())
    api = UtorrentApi(connection["url"], connection["username"], connection["password"])
    assert not api.torrents(with_files=False), "Use a dedicated, empty µTorrent instance"
    name = "torrentlinker-test-" + uuid4().hex
    local = Path(os.environ["TL_UTORRENT_DATA"]) / name
    local.mkdir()
    root = local / "Bundle" if multi else local
    root.mkdir(exist_ok=True)
    (root / "one.txt").write_bytes(b"TorrentLinker test fixture\n" * 4000)
    if multi:
        (root / "two.txt").write_bytes(b"Second disposable file\n" * 2000)
    original = {p: hashlib.sha256(p.read_bytes()).digest() for p in root.iterdir()}
    data = make_torrent(root if multi else root / "one.txt")
    base = api.default_save_path()
    target = _path_module(base).join(base, name)
    hash = None
    try:
        hash = api.download(data, target, ["torrentlinker:test"])
        for _ in range(100):
            item = api.torrent(hash)
            if item is not None and item.progress == 1:
                break
            time.sleep(0.1)
        assert item.progress == 1
        assert item.files == {p.name: p.stat().st_size for p in original}
        assert "torrentlinker:test" in item.tags
        assert api.torrents(tag="torrentlinker:test", with_files=False)[0].hash == hash
        assert item.trackers == ("https://tracker.example/announce",)
        api.pause(hash)
        assert api.torrent(hash).state == "stoppedUP"
        api.set_file_priority(hash, [0], 0)
        assert not api.file_listing(hash)[0].wanted
        api.set_file_priority(hash, [0], 1)
        assert api.file_listing(hash)[0].wanted
        api.recheck(hash)
        for _ in range(100):
            item = api.torrent(hash)
            if item.progress == 1 and not item.state.startswith("checking"):
                break
            time.sleep(0.1)
        assert item.progress == 1
        api.resume(hash)
    finally:
        if hash:
            api.remove(hash)
    assert api.torrent(hash) is None
    assert all(
        p.exists() and hashlib.sha256(p.read_bytes()).digest() == digest
        for p, digest in original.items()
    )


@pytest.mark.parametrize(
    "multi,rename,upload",
    [
        (False, False, False),
        (True, False, False),
        (False, True, False),
        (True, True, False),
        (False, True, True),
        (True, True, True),
    ],
)
def test_classic_live_reseed_and_upload_verify_before_start(tmp_path, multi, rename, upload):
    connection = json.loads(Path(os.environ["TL_UTORRENT_CONNECTION"]).read_text())

    def api():
        return UtorrentApi(connection["url"], connection["username"], connection["password"])

    raw = api()
    assert not raw.torrents(with_files=False), "Use a dedicated, empty µTorrent instance"
    base = Path(os.environ["TL_UTORRENT_DATA"])
    local = base / ("torrentlinker-reseed-" + uuid4().hex)
    local.mkdir()
    scene = tmp_path / "Scene"
    scene.mkdir()
    (scene / "one.txt").write_bytes(b"Disposable Reseed fixture\n" * 4000)
    if multi:
        (scene / "two.txt").write_bytes(b"Second file\n" * 7000)
    meta = read_torrent(make_torrent(scene if multi else scene / "one.txt"))
    pairs = {}
    original = {}
    for index, name in enumerate(meta.files):
        source = scene / name.split("/")[-1]
        local_name = f"Original/book-{index}.txt" if rename else name
        target = local / local_name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
        pairs[name] = local_name
        original[name] = (hashlib.sha256(target.read_bytes()).digest(), target.stat())
    # The Local Item's parent is the requested save directory, also for a file pack.
    item_path = (
        local / ("Original" if rename else "Scene") if multi else local / next(iter(pairs.values()))
    )
    if not multi and rename:
        # Keep the single file directly under the chosen save directory.
        old = local / next(iter(pairs.values()))
        new = local / "Original.txt"
        old.rename(new)
        pairs = {next(iter(meta.files)): new.name}
        item_path = new
    item = LocalItem(item_path, {p: meta.files[t] for t, p in pairs.items()})
    mapper = PathMapper([PathMapping(str(base), raw.default_save_path())])
    client = MappedQbit(raw, mapper)
    store = Store(tmp_path / "s.db")
    h = meta.infohash
    approvals = []
    try:

        def approve(plan):
            approvals.append(plan)
            return True

        if upload:
            prepared = PreparedUpload(
                SavedUpload(item.path, meta.name, h, None, 0),
                meta,
                [UploadFile(t, p, meta.files[t]) for t, p in pairs.items()],
            )
            seed_upload(client, store, item, prepared, approve_disk_renames=approve)
        else:
            start_reseed(
                client, store, item, meta, Match(pairs), "candidate", approve_disk_renames=approve
            )
        assert len(approvals) == int(rename)
        for _ in range(150):
            torrent = client.torrent(h)
            assert torrent.state not in {"downloading", "uploading"}
            if torrent.progress == 1 and torrent.state == "stoppedUP":
                break
            time.sleep(0.1)
        assert torrent.progress == 1 and torrent.state == "stoppedUP"
        # A fresh adapter must be able to recover/accept the persisted Verification.
        outcomes = check_verifications(MappedQbit(api(), mapper), store)
        assert len(outcomes) == 1 and outcomes[0].started
        assert client.torrent(h).tags == frozenset({TAG})
        assert VERIFYING not in client.torrent(h).tags
        for name, (digest, before) in original.items():
            target = local / name
            assert hashlib.sha256(target.read_bytes()).digest() == digest
            assert target.stat().st_ino == before.st_ino
            assert target.stat().st_mtime_ns == before.st_mtime_ns
    finally:
        if raw.torrent(h) is not None:
            raw.remove(h)
    assert raw.torrent(h) is None


def test_classic_live_bad_reseed_is_removed_without_downloading_or_changing_data(tmp_path):
    connection = json.loads(Path(os.environ["TL_UTORRENT_CONNECTION"]).read_text())
    raw = UtorrentApi(connection["url"], connection["username"], connection["password"])
    assert not raw.torrents(with_files=False), "Use a dedicated, empty µTorrent instance"
    base = Path(os.environ["TL_UTORRENT_DATA"])
    local = base / ("torrentlinker-bad-reseed-" + uuid4().hex)
    local.mkdir()
    source = tmp_path / "test.txt"
    source.write_bytes(b"original" * 16000)
    meta = read_torrent(make_torrent(source))
    file = local / source.name
    file.write_bytes(b"mismatch" * 16000)
    before = file.read_bytes(), file.stat().st_mtime_ns
    client = MappedQbit(raw, PathMapper([PathMapping(str(base), raw.default_save_path())]))
    store = Store(tmp_path / "s.db")
    try:
        start_reseed(
            client,
            store,
            LocalItem(file, meta.files),
            meta,
            Match({file.name: file.name}),
            "bad-candidate",
        )
        for _ in range(30):
            torrent = client.torrent(meta.infohash)
            assert torrent.state not in {"uploading", "downloading"}
            time.sleep(0.1)
        outcomes = check_verifications(client, store, now=lambda: 1e12)
        assert len(outcomes) == 1 and not outcomes[0].verified
        assert raw.torrent(meta.infohash) is None
        assert "bad-candidate" in store.rejections(file)
        assert (file.read_bytes(), file.stat().st_mtime_ns) == before
    finally:
        if raw.torrent(meta.infohash) is not None:
            raw.remove(meta.infohash)
