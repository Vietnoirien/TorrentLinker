"""Empty-folder verification through the authenticated owner API."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from torrentlinker.domain import Torrent
from torrentlinker.torrent_meta import read_torrent
from torrentlinker.web.app import create_app


class ProbeClient:
    def __init__(self, root):
        self.root = root
        self.added = []
        self.removed = []
        self.present = None

    def check(self):
        return "test"

    def folder_settings(self):
        return []

    def torrents(self, **kwargs):
        return []

    def add(self, data, save_path, tags):
        import io

        import torf

        meta = read_torrent(data)
        torrent = torf.Torrent.read_stream(io.BytesIO(data))
        assert torrent.private and not torrent.trackers
        assert save_path == "/downloads"
        assert len(meta.files) == 1
        # NAS/container daemons commonly run under a different UID.
        assert (self.root / meta.name).stat().st_mode & 0o444 == 0o444
        assert torrent.verify(self.root / meta.name)
        self.added.append(meta)
        self.present = meta.infohash
        return meta.infohash

    def recheck(self, hash):
        assert hash == self.present

    def torrent(self, hash, **kwargs):
        if hash == self.present:
            return Torrent(hash, "probe", Path("/downloads"), progress=1, state="pausedUP")

    def piece_states(self, hash):
        return [2]

    def remove(self, hash, *, delete_files=False):
        assert not delete_files
        self.removed.append(hash)
        self.present = None


def test_owner_verifies_and_saves_empty_mapping_without_a_seeded_sample(tmp_path):
    root = tmp_path / "media"
    root.mkdir()
    client = ProbeClient(root)
    with TestClient(
        create_app(
            tmp_path / "config",
            password="test-password-long",
            roots=(root,),
            connector=lambda *a, **kw: client,
        )
    ) as browser:
        browser.headers["X-TorrentLinker"] = "1"
        browser.post("/api/login", json={"password": "test-password-long"})
        assert (
            browser.post(
                "/api/setup/client",
                json={
                    "client": "qbittorrent",
                    "host": "https://seedbox.example",
                    "username": "owner",
                },
            ).status_code
            == 200
        )
        result = browser.post(
            "/api/setup/folder",
            json={
                "local": str(root),
                "client_path": "/downloads",
                "purpose": "download",
            },
        )
        assert result.status_code == 200, result.text
        assert result.json()["verification"] == "temporary-file"
        assert browser.get("/api/setup").json()["download_folder"] == str(root)
        assert len(client.added) == 1
        assert client.removed == [client.added[0].infohash]
        assert list(root.iterdir()) == []
        body = {"local": str(root), "client_path": "/downloads", "purpose": "download"}
        assert browser.post("/api/setup/test-folder", json=body).status_code == 200
        assert len(client.added) == 1  # reuse a recent proof for this exact mounted folder
        assert (
            browser.post(
                "/api/setup/client",
                json={
                    "client": "qbittorrent",
                    "host": "https://seedbox.example",
                    "username": "owner",
                    "password": "replacement-test-password",
                },
            ).status_code
            == 200
        )
        assert browser.post("/api/setup/test-folder", json=body).status_code == 200
        assert len(client.added) == 2  # credential changes invalidate previous proofs
        assert len(client.removed) == 2
        assert list(root.iterdir()) == []


@pytest.mark.parametrize("failure", ["recheck", "add", "cleanup", "timeout"])
def test_failed_probe_keeps_existing_files_and_never_saves_mapping(tmp_path, monkeypatch, failure):
    from torrentlinker import folder_probe

    root = tmp_path / "media"
    root.mkdir()
    original = root / "keep.txt"
    original.write_text("untouched")
    client = ProbeClient(root)
    if failure == "timeout":
        monkeypatch.setattr(folder_probe, "PROBE_TIMEOUT", 0)
    else:
        method = {"recheck": "recheck", "add": "add", "cleanup": "remove"}[failure]
        original_method = getattr(client, method)

        def fail(*args, **kwargs):
            if failure == "add":
                original_method(*args, **kwargs)  # accepted, but response was lost
            raise ValueError("simulated client failure")

        monkeypatch.setattr(client, method, fail)
    with TestClient(
        create_app(
            tmp_path / "config",
            password="test-password-long",
            roots=(root,),
            connector=lambda *a, **kw: client,
        )
    ) as browser:
        browser.headers["X-TorrentLinker"] = "1"
        browser.post("/api/login", json={"password": "test-password-long"})
        browser.post(
            "/api/setup/client", json={"client": "qbittorrent", "host": "https://box.example"}
        )
        result = browser.post(
            "/api/setup/folder",
            json={
                "local": str(root),
                "client_path": "/downloads",
                "purpose": "download",
            },
        )
        assert result.status_code == 400
        assert not browser.get("/api/setup").json()["download_folder"]
        assert list(root.iterdir()) == [original]
        assert original.read_text() == "untouched"
        if failure == "cleanup":
            assert "Remove it from the Torrent Client" in result.json()["detail"]
        else:
            assert client.present is None
