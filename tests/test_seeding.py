from dataclasses import replace
from pathlib import Path

import pytest

from torrentlinker.domain import Torrent
from torrentlinker.seeding import observe_swarm, seeding
from torrentlinker.store import CatalogueRow, Store
from torrentlinker.zen import GB, ZenClass, ZenProfile

URL = "https://c411.org/api/torznab"


def torrent(name: str, tracker: str, state: str = "uploading", days: float = 90) -> Torrent:
    return Torrent(
        name,
        name,
        Path("/data"),
        tracker=tracker,
        swarm_seeders=100,
        seeding_time=days * 86400,
        size=4 * GB,
        state=state,
    )


def test_only_indexer_torrents_are_listed_and_only_seeding_ones_earn() -> None:
    torrents = [
        torrent("a", "https://tracker.c411.org/announce/x"),
        torrent("b", "https://tracker.c411.org/announce/x", state="stoppedUP"),
        torrent("c", "udp://tracker.opentrackr.org:1337/announce"),
    ]

    view = seeding(ZenProfile(ZenClass.TANKER), torrents, URL)

    assert [r.torrent.name for r in view.rows] == ["a", "b"]
    assert view.rows[0].zen == pytest.approx(1.7 / 7)
    assert view.rows[1].zen is None
    assert view.count == 1
    assert view.day.total == pytest.approx(1.7 / 7)


@pytest.mark.parametrize(
    "state,seeds,expected",
    [("uploading", 5, 4), ("downloading", 5, 5), ("uploading", -1, 100), ("downloading", 0, 0)],
)
def test_tracker_counts_update_only_swarm_data_in_the_catalogue(
    tmp_path: Path, state: str, seeds: int, expected: int
) -> None:
    store = Store(tmp_path / "s.db")
    row = CatalogueRow("a" * 40, "Book", 4 * GB, 100, 7000, "u", "d", 123, "zen-lab")
    other = replace(row, infohash="b" * 40)
    store.save_catalogue([row, other])
    t = replace(
        torrent(row.infohash, "https://tracker.c411.org/announce"), state=state, swarm_seeders=seeds
    )
    unrelated = replace(t, hash=other.infohash, tracker="udp://tracker.example/announce")

    cached = observe_swarm(store, [t, unrelated], URL)

    assert cached[row.infohash] == replace(row, seeders=expected)
    assert store.catalogue([other.infohash]) == [other]


def test_estimates_use_cached_counts_until_the_tracker_responds_and_keep_the_category() -> None:
    row = CatalogueRow("a" * 40, "Torrent", 4 * GB, 100, 6000, "u", "d", 0, "zen-lab")
    t = replace(torrent(row.infohash, "https://tracker.c411.org/announce"), swarm_seeders=-1)
    profile = ZenProfile(ZenClass.SWARM_KEEPER)
    cache = {row.infohash: row}

    provisional = seeding(profile, [t], URL, catalogue=cache)
    fresh = seeding(profile, [replace(t, swarm_seeders=5)], URL, catalogue=cache)

    assert provisional.active[0].seeders == 101
    assert provisional.active[0].category == 6000
    assert fresh.active[0].seeders == 5
    assert fresh.day.total > provisional.day.total


@pytest.mark.parametrize(
    "raw,expected",
    [({}, -1), ({"num_complete": -1}, -1), ({"num_complete": 0}, 0), ({"num_complete": 5}, 5)],
)
def test_qbit_adapter_keeps_unknown_counts_distinct_from_a_reported_zero(
    raw: dict[str, int], expected: int
) -> None:
    from torrentlinker.qbit import QbitApi

    data = {
        "hash": "a" * 40,
        "name": "Book",
        "save_path": "/data",
        "tags": "",
        "progress": 0,
        "state": "downloading",
        **raw,
    }
    qbit = QbitApi.__new__(QbitApi)
    assert qbit._torrent(data, with_files=False).swarm_seeders == expected


def test_c411_alternate_tracker_films_are_counted_and_categorized(tmp_path):
    store = Store(tmp_path / "s.db")
    row = CatalogueRow("a" * 40, "Film", 4 * GB, 10, 2000, "u", "d", 123, "zen-lab")
    store.save_catalogue([row])
    film = torrent(row.infohash, "https://tk.c411.tw/announce/private")
    cached = observe_swarm(store, [film], URL)
    view = seeding(ZenProfile(), [film], URL, catalogue=cached)
    assert len(view.rows) == 1
    assert view.rows[0].category == 2000
    assert view.count == 1
