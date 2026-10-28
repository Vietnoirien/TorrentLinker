"""Every Torrent Client reports the same facts about one torrent.

Each adapter reads a rich, realistic answer from its own fake (no real client is
contacted) and must produce the same `Torrent`, so the desktop and web Torrents
tabs show the same numbers whichever client is behind them.
"""

from pathlib import Path

import httpx
import pytest

from tests.test_deluge_unit import FakeWebUi
from tests.test_deluge_unit import api_for as deluge_api
from tests.test_qbit_unit import Synced
from tests.test_transmission_unit import FakeRpc
from tests.test_transmission_unit import api_for as transmission_api
from tests.test_utorrent_unit import WebUI, row
from torrentlinker.deluge import DelugeApi
from torrentlinker.domain import Torrent
from torrentlinker.qbit import QbitApi

H = "ab" * 20
NAME = "Jumanji.2017.MULTI.VF2.1080p.BluRay.x264-GHT"
SIZE = 8_200_000_000
TRACKERS = ("https://tracker.c411.org/announce", "https://backup.example/announce")
LABEL = "Films"

# What a person sees in the client for this torrent, whichever client it is.
EXPECTED = {
    "hash": H,
    "name": NAME,
    "size": SIZE,
    "progress": 0.5,
    "state": "downloading",
    "tracker": TRACKERS[0],
    "trackers": TRACKERS,
    "category": LABEL,
    "tags": frozenset({LABEL}),
    "download_rate": 3_400_000,
    "upload_rate": 120_000,
    "ratio": 2.4,
    "eta": 600,
    "connected_seeds": 5,
    "connected_peers": 2,
    "swarm_seeders": 40,
    "swarm_peers": 7,
}


def read(t: Torrent) -> dict:
    return {key: getattr(t, key) for key in EXPECTED} | {"save": str(t.save_path)}


def qbittorrent() -> Torrent:
    api = QbitApi("http://127.0.0.1:1", "", "")
    sync = Synced()
    sync.answers = [
        {
            "rid": 1,
            "full_update": True,
            "torrents": {
                H: {
                    "name": NAME,
                    "save_path": "/downloads",
                    "tags": LABEL,
                    "category": LABEL,
                    "progress": 0.5,
                    "state": "downloading",
                    "tracker": TRACKERS[0],
                    "total_size": SIZE,
                    "size": SIZE // 2,
                    "dlspeed": 3_400_000,
                    "upspeed": 120_000,
                    "ratio": 2.4,
                    "eta": 600,
                    "num_seeds": 5,
                    "num_leechs": 2,
                    "num_complete": 40,
                    "num_incomplete": 7,
                    "seeding_time": 3600,
                }
            },
            "trackers": {TRACKERS[0]: [H], TRACKERS[1]: [H]},
        }
    ]
    api._client = sync
    return api.torrents(with_files=False)[0]


def deluge() -> Torrent:
    web = FakeWebUi()
    api = deluge_api(web)
    web.torrents[H] = {
        "name": NAME,
        "download_location": "/downloads",
        "label": LABEL,
        "progress": 50.0,
        "state": "Downloading",
        "paused": False,
        "tracker": TRACKERS[0],
        "trackers": [{"url": u} for u in TRACKERS],
        "total_seeds": 40,
        "total_peers": 7,
        "seeding_time": 3600,
        "total_size": SIZE,
        "download_payload_rate": 3_400_000,
        "upload_payload_rate": 120_000,
        "ratio": 2.4,
        "eta": 600,
        "num_seeds": 5,
        "num_peers": 2,
        "files": [],
    }
    assert isinstance(api, DelugeApi)
    api.check()
    return api.torrents(with_files=False)[0]


def transmission() -> Torrent:
    rpc = FakeRpc()
    rpc.torrents[H] = {
        "hashString": H.upper(),
        "name": NAME,
        "downloadDir": "/downloads",
        "labels": [LABEL],
        "percentDone": 0.5,
        "status": 4,
        "error": 0,
        "trackers": [{"announce": u} for u in TRACKERS],
        "trackerStats": [{"seederCount": 40, "leecherCount": 7}, {"seederCount": 12}],
        "secondsSeeding": 3600,
        "totalSize": SIZE,
        "rateDownload": 3_400_000,
        "rateUpload": 120_000,
        "uploadRatio": 2.4,
        "eta": 600,
        "peers": [{"progress": 1.0}] * 5 + [{"progress": 0.2}] * 2,
    }
    api = transmission_api(rpc)
    return api.torrents(with_files=False)[0]


def utorrent() -> Torrent:
    web = WebUI()
    item = row(H, NAME, "C:\\Downloads", LABEL)
    item[1], item[3], item[4] = 201, SIZE, 500  # started, queued off, 50.0 %
    item[7], item[8], item[9], item[10] = 2400, 120_000, 3_400_000, 600
    item[12], item[13], item[14], item[15] = 2, 7, 5, 40
    web.jobs = {H: item}

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("action") == "getprops":
            props = [{"hash": H.upper(), "trackers": "\r\n".join(TRACKERS) + "\r\n"}]
            reply = httpx.Response(200, json={"build": 47390, "props": props})
            web.calls.append(dict(request.url.params))
            return reply
        return web.handle(request)

    from torrentlinker.utorrent import UtorrentApi

    api = UtorrentApi(
        "http://client:8081/gui/",
        "user",
        "secret",
        http=httpx.Client(transport=httpx.MockTransport(handle)),
    )
    return api.torrents(with_files=False)[0]


CLIENTS = {
    "qBittorrent": (qbittorrent, "/downloads"),
    "Deluge": (deluge, "/downloads"),
    "Transmission": (transmission, "/downloads"),
    # BitTorrent Classic speaks the same WebUI as µTorrent and uses the same adapter.
    "µTorrent / BitTorrent Classic": (utorrent, "C:\\Downloads"),
}


@pytest.mark.parametrize("client", CLIENTS)
def test_every_client_reports_the_same_facts(client):
    build, save = CLIENTS[client]
    got = read(build())
    expected = EXPECTED | {"save": str(Path(save))}
    if client == "Transmission":
        # Transmission has labels, which are this app's tags, but no separate category.
        expected |= {"category": ""}
    missing = {k: (got[k], v) for k, v in expected.items() if got[k] != v}
    assert not missing, f"{client} differs: {missing}"


@pytest.mark.parametrize("client", CLIENTS)
def test_no_client_reports_a_started_torrent_as_seeding_or_leaves_unknowns_silent(client):
    torrent = CLIENTS[client][0]()
    assert not torrent.is_seeding
    # -1 would mean "not reported": every client here reports all of these.
    assert torrent.swarm_seeders >= 0 and torrent.swarm_peers >= 0
    assert torrent.connected_seeds >= 0 and torrent.connected_peers >= 0
    assert torrent.eta >= 0 and torrent.total_size == SIZE


def test_qbittorrent_names_every_tracker_when_one_torrent_is_asked_for():
    api = QbitApi("http://127.0.0.1:1", "", "")

    class Client:
        def torrents_info(self, torrent_hashes):
            return [{"hash": H, "name": NAME, "save_path": "/d", "progress": 1.0, "state": "x"}]

        def torrents_trackers(self, hash):
            return [
                {"url": "** [DHT] **"},
                {"url": TRACKERS[0]},
                {"url": TRACKERS[1]},
            ]

    api._client = Client()
    found = api.torrent(H, with_files=False)
    assert found is not None and found.trackers == TRACKERS
