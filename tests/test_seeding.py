from pathlib import Path

import pytest

from torrentlinker.domain import Torrent
from torrentlinker.seeding import seeding
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
