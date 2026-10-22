"""Path Mappings against Deluge in a throwaway Docker container. Opt-in:

    data=$(mktemp -d)
    docker run -d --rm --name tl-deluge-paths -p 127.0.0.1:18113:8112 \\
        -e PUID=$(id -u) -e PGID=$(id -g) -v "$data:/data" lscr.io/linuxserver/deluge:2.2.0
    python scripts/deluge_sandbox.py http://127.0.0.1:18113
    TL_DELUGE_DOCKER=http://127.0.0.1:18113 TL_DELUGE_DOCKER_DATA="$data" \\
        pytest tests/test_deluge_docker_paths.py
    docker stop tl-deluge-paths

The container sees the folder $data as /data only, as a NAS or Docker volume would.
"""

import os
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.test_docker_paths import release
from tests.test_qbit_integration import digest, settle
from torrentlinker.deluge import DelugeApi
from torrentlinker.domain import LibraryFolder, PathMapping
from torrentlinker.matching import match
from torrentlinker.paths import MappedQbit, PathMapper, check_mappings, detect_mappings
from torrentlinker.reseed import start_reseed
from torrentlinker.scan import scan
from torrentlinker.store import Store
from torrentlinker.torrent_meta import read_torrent

HOST = os.environ.get("TL_DELUGE_DOCKER", "")
DATA = Path(os.environ.get("TL_DELUGE_DOCKER_DATA", "/nonexistent"))
PASSWORD = os.environ.get("TL_DELUGE_SANDBOX_PASSWORD", "deluge")
pytestmark = pytest.mark.skipif(not HOST, reason="set TL_DELUGE_DOCKER and TL_DELUGE_DOCKER_DATA")


@pytest.fixture
def deluge() -> Iterator[DelugeApi]:
    api = DelugeApi(HOST, PASSWORD)
    before = {t.hash for t in api.torrents(with_files=False)}
    yield api
    for t in api.torrents(with_files=False):
        if t.hash not in before:
            api.remove(t.hash)


def test_detect_finds_the_volume_and_check_confirms_it(deluge: DelugeApi) -> None:
    data = release(DATA / "ebooks", "Zweig.Le.Joueur.D.Echecs")
    h = deluge.add(data, "/data/ebooks", ["torrentlinker:test"])  # as the user set it up

    def files(t):  # type: ignore[no-untyped-def]
        return found.files if (found := deluge.torrent(t.hash)) else {}

    mine = [t for t in deluge.torrents(with_files=False) if t.hash == h]
    detection = detect_mappings(mine, [DATA / "ebooks"], files)

    [suggestion] = detection.suggestions
    assert suggestion.mapping == PathMapping(str(DATA), "/data")
    [check] = check_mappings(mine, [suggestion.mapping])
    assert (check.found, check.total) == (1, 1)
    assert deluge.default_save_path() == "/downloads"  # not on this computer


def test_a_reseed_through_the_mapping_is_verified_in_the_container(
    deluge: DelugeApi, tmp_path: Path
) -> None:
    data = release(DATA / "scene", "Sand.Indiana")
    meta = read_torrent(data)
    lib = DATA / "library"
    lib.mkdir()
    local = lib / "Indiana - George Sand.epub"  # the user's own name for it
    local.write_bytes((DATA / "scene" / "Sand.Indiana" / "Sand.Indiana.epub").read_bytes())
    [item] = scan(LibraryFolder(lib))
    before = digest(local)
    m = match(item, meta.files)
    assert m is not None and m.is_full
    mapped = MappedQbit(deluge, PathMapper([PathMapping(str(DATA), "/data")]))
    store = Store(tmp_path / "s.db")

    h = start_reseed(mapped, store, item, meta, m, meta.infohash)
    [outcome] = settle(mapped, store)  # type: ignore[arg-type]

    assert outcome.verified and outcome.started
    raw = deluge.torrent(h)
    assert raw is not None and str(raw.save_path) == "/data/library"
    assert raw.files == {local.name: local.stat().st_size}
    assert digest(local) == before


def test_without_the_mapping_deluge_cannot_find_the_data(deluge: DelugeApi, tmp_path: Path) -> None:
    data = release(DATA / "unmapped-scene", "Kafka.Le.Proces")
    meta = read_torrent(data)
    lib = DATA / "unmapped"
    (lib / "Kafka.Le.Proces").mkdir(parents=True)
    os.replace(DATA / "unmapped-scene" / "Kafka.Le.Proces", lib / "Kafka.Le.Proces")
    [item] = scan(LibraryFolder(lib))
    store = Store(tmp_path / "s.db")

    h = start_reseed(
        MappedQbit(deluge, PathMapper([])),
        store,
        item,
        meta,
        match(item, meta.files),  # type: ignore[arg-type]
        meta.infohash,
    )
    t0 = time.time()
    [outcome] = settle(deluge, store, timeout=30)  # type: ignore[arg-type]

    assert not outcome.verified  # Deluge looked for this computer's path in the container
    assert time.time() - t0 < 30
    assert deluge.torrent(h) is None
    assert store.rejections(item.path)


def test_a_plan_download_goes_to_the_download_folder_as_deluge_sees_it(
    deluge: DelugeApi,
) -> None:
    from torrentlinker.plan import PlanCandidate
    from torrentlinker.send import send_one

    src = DATA / "elsewhere"
    data = release(src, "Zen.Release")
    meta = read_torrent(data)
    folder = DATA / "downloads" / "ebooks"
    mapped = MappedQbit(deluge, PathMapper([PathMapping(str(DATA), "/data")]))

    h = send_one(mapped, PlanCandidate(meta.infohash, meta.name, 70_000, 1, 1, folder, 1), data)

    raw = deluge.torrent(h)
    assert raw is not None and str(raw.save_path) == "/data/downloads/ebooks"
    assert mapped.torrent(h).save_path == folder  # type: ignore[union-attr]
