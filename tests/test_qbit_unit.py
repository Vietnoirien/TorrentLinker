from pathlib import Path

import pytest

from tests.torrents import make_torrent
from torrentlinker.qbit import AlreadyInClient, QbitApi
from torrentlinker.torrent_meta import read_torrent


class Client:
    """qBittorrent's API refusing an add, with the torrent already listed or not."""

    def __init__(self, listed: bool) -> None:
        self.listed = listed

    def torrents_add(self, **kwargs: object) -> str:
        return "Fails."

    def torrents_info(self, torrent_hashes: str) -> list[object]:
        return [object()] if self.listed else []


def torrent(tmp_path: Path) -> bytes:
    (tmp_path / "book.epub").write_bytes(b"x" * 1000)
    return make_torrent(tmp_path / "book.epub")


@pytest.mark.parametrize("listed,error", [(True, AlreadyInClient), (False, RuntimeError)])
def test_a_refused_add_says_when_the_torrent_is_already_there(
    tmp_path: Path, listed: bool, error: type[Exception]
) -> None:
    api = QbitApi("http://127.0.0.1:1", "", "")
    api._client = Client(listed)
    data = torrent(tmp_path)
    assert read_torrent(data).infohash

    with pytest.raises(error) as raised:
        api.download(data, str(tmp_path), [])

    assert ("already in qBittorrent" in str(raised.value)) == listed
