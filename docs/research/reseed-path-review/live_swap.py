"""Destructive only to generated fixtures. Requires an explicitly configured throwaway client."""

import hashlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from tests.torrents import make_torrent
from torrentlinker.domain import PathMapping
from torrentlinker.matching import match
from torrentlinker.paths import MappedQbit, PathMapper
from torrentlinker.qbit import QbitApi
from torrentlinker.reseed import start_reseed
from torrentlinker.scan import scan_item
from torrentlinker.store import Store
from torrentlinker.torrent_meta import read_torrent

root = Path(os.environ["TL_RESEED_AUDIT_DATA"]).resolve()
root.mkdir(parents=True, exist_ok=True)
failures = []
api = QbitApi(os.environ["TL_RESEED_AUDIT_HOST"], "", "")
client = MappedQbit(api, PathMapper([PathMapping(str(root), "/data")]))
for trial in range(3):
    base = Path(tempfile.mkdtemp(prefix="swap-clean-", dir=root))
    source, local = base / "source" / "Show", base / "library" / "Show"
    source.mkdir(parents=True)
    local.mkdir(parents=True)
    (source / "a.mkv").write_bytes(b"a" * 40000)
    (source / "b.mkv").write_bytes(b"b" * 50000)
    (local / "a.mkv").write_bytes(b"b" * 50000)
    (local / "b.mkv").write_bytes(b"a" * 40000)

    def snapshot(folder=local):
        return {
            f.name: hashlib.sha256(f.read_bytes()).hexdigest()
            for f in folder.iterdir()
            if f.is_file()
        }

    before = snapshot()
    meta = read_torrent(make_torrent(source))
    item = scan_item(local)
    found = match(item, meta.files)
    store = Store(base / "state.db")
    result = {"trial": trial, "base": str(base), "before": before, "pairs": found.pairs}
    try:
        start_reseed(client, store, item, meta, found, meta.infohash)
        result["setup"] = "started"
    except Exception as e:
        result["setup"] = type(e).__name__ + ": " + str(e)
    if client.torrent(meta.infohash):
        client.remove(meta.infohash)
    time.sleep(2)
    after = snapshot()
    result.update(after=after, unchanged=before == after, pending=store.verification_hashes())
    print(json.dumps(result), flush=True)

    if before != after:
        failures.append(str(base))
assert not failures, f"Reseed moved library files in {len(failures)} trials: {failures}"
