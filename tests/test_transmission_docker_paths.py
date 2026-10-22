"""Path Mappings against Transmission in a throwaway Docker container. Opt-in:

    data=$(mktemp -d)
    docker run -d --rm --name tl-transmission-paths -p 127.0.0.1:19092:9091 \\
        -e PUID=$(id -u) -e PGID=$(id -g) -v "$data:/data" lscr.io/linuxserver/transmission:4.1.3
    python scripts/transmission_sandbox.py http://127.0.0.1:19092
    TL_TRANSMISSION_DOCKER=http://127.0.0.1:19092 TL_TRANSMISSION_DOCKER_DATA="$data" \\
        pytest tests/test_transmission_docker_paths.py
    docker stop tl-transmission-paths

The container sees the folder $data as /data only, as a NAS or Docker volume would.
"""

import os
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.test_docker_paths import release
from tests.test_qbit_integration import digest, settle
from torrentlinker.domain import LibraryFolder, PathMapping
from torrentlinker.matching import match
from torrentlinker.paths import MappedQbit, PathMapper, check_mappings, detect_mappings
from torrentlinker.reseed import start_reseed
from torrentlinker.scan import scan
from torrentlinker.store import Store
from torrentlinker.torrent_meta import read_torrent
from torrentlinker.transmission import TransmissionApi

HOST = os.environ.get("TL_TRANSMISSION_DOCKER", "")
DATA = Path(os.environ.get("TL_TRANSMISSION_DOCKER_DATA", "/nonexistent"))
pytestmark = pytest.mark.skipif(
    not HOST, reason="set TL_TRANSMISSION_DOCKER and TL_TRANSMISSION_DOCKER_DATA"
)


@pytest.fixture
def client() -> Iterator[TransmissionApi]:
    api = TransmissionApi(HOST)
    api.turn_off_partial_names()
    before = {t.hash for t in api.torrents(with_files=False)}
    yield api
    for t in api.torrents(with_files=False):
        if t.hash not in before:
            api.remove(t.hash)


def test_detect_finds_the_volume_and_check_confirms_it(client: TransmissionApi) -> None:
    data = release(DATA / "ebooks", "Zweig.Le.Joueur.D.Echecs")
    h = client.add(data, "/data/ebooks", ["torrentlinker:test"])  # as the user set it up

    def files(t):  # type: ignore[no-untyped-def]
        return found.files if (found := client.torrent(t.hash)) else {}

    mine = [t for t in client.torrents(with_files=False) if t.hash == h]
    detection = detect_mappings(mine, [DATA / "ebooks"], files)

    [suggestion] = detection.suggestions
    assert suggestion.mapping == PathMapping(str(DATA), "/data")
    [check] = check_mappings(mine, [suggestion.mapping])
    assert (check.found, check.total) == (1, 1)
    assert client.default_save_path().startswith("/downloads")  # not on this computer


def test_a_reseed_through_the_mapping_is_verified_in_the_container(
    client: TransmissionApi, tmp_path: Path
) -> None:
    data = release(DATA / "scene", "Sand.Indiana")
    meta = read_torrent(data)
    lib = DATA / "library"
    (lib / "Indiana").mkdir(parents=True)
    # The user's own names; Transmission renames names in place, not into other folders.
    local = lib / "Indiana" / "Indiana - George Sand.epub"
    local.write_bytes((DATA / "scene" / "Sand.Indiana" / "Sand.Indiana.epub").read_bytes())
    [item] = scan(LibraryFolder(lib))
    before = digest(local)
    m = match(item, meta.files)
    assert m is not None and m.is_full
    mapped = MappedQbit(client, PathMapper([PathMapping(str(DATA), "/data")]))
    store = Store(tmp_path / "s.db")

    h = start_reseed(mapped, store, item, meta, m, meta.infohash)
    [outcome] = settle(mapped, store)  # type: ignore[arg-type]

    assert outcome.verified and outcome.started
    raw = client.torrent(h)
    assert raw is not None and str(raw.save_path) == "/data/library"
    assert raw.files == {"Indiana/" + local.name: local.stat().st_size}
    assert digest(local) == before


def test_without_the_mapping_transmission_cannot_find_the_data(
    client: TransmissionApi, tmp_path: Path
) -> None:
    data = release(DATA / "unmapped-scene", "Kafka.Le.Proces")
    meta = read_torrent(data)
    lib = DATA / "unmapped"
    (lib / "Kafka.Le.Proces").mkdir(parents=True)
    os.replace(DATA / "unmapped-scene" / "Kafka.Le.Proces", lib / "Kafka.Le.Proces")
    [item] = scan(LibraryFolder(lib))
    store = Store(tmp_path / "s.db")

    h = start_reseed(
        MappedQbit(client, PathMapper([])),
        store,
        item,
        meta,
        match(item, meta.files),  # type: ignore[arg-type]
        meta.infohash,
    )
    t0 = time.time()
    [outcome] = settle(client, store, timeout=30)  # type: ignore[arg-type]

    assert not outcome.verified  # Transmission looked for this computer's path in the container
    assert time.time() - t0 < 30
    assert client.torrent(h) is None
    assert store.rejections(item.path)


def test_a_plan_download_goes_to_the_download_folder_as_transmission_sees_it(
    client: TransmissionApi,
) -> None:
    from torrentlinker.plan import PlanCandidate
    from torrentlinker.send import send_one

    src = DATA / "elsewhere"
    data = release(src, "Zen.Release")
    meta = read_torrent(data)
    folder = DATA / "downloads" / "ebooks"
    mapped = MappedQbit(client, PathMapper([PathMapping(str(DATA), "/data")]))

    h = send_one(mapped, PlanCandidate(meta.infohash, meta.name, 70_000, 1, 1, folder, 1), data)

    raw = client.torrent(h)
    assert raw is not None and str(raw.save_path) == "/data/downloads/ebooks"
    assert mapped.torrent(h).save_path == folder  # type: ignore[union-attr]
