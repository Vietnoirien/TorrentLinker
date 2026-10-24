import threading
import time
from pathlib import Path

from fastapi.testclient import TestClient

from torrentlinker.domain import Torrent
from torrentlinker.web.app import create_app


def login(browser):
    browser.headers["X-TorrentLinker"] = "1"
    assert browser.post("/api/login", json={"password": "test-password-long"}).status_code == 200


def finished(browser, identifier):
    for _ in range(200):
        job = browser.get(f"/api/jobs/{identifier}").json()
        if job["status"] not in {"queued", "running"}:
            return job
        time.sleep(0.01)
    raise AssertionError("Job did not finish")


class Client:
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()
        self.paused = []

    def check(self):
        return "fake"

    def folder_settings(self):
        return []

    def torrents(self, **kwargs):
        return [Torrent("a" * 40, "Book", Path("/remote"), size=1024)]

    def torrent(self, hash, **kwargs):
        return self.torrents()[0]

    def pause(self, hash):
        self.started.set()
        self.release.wait(5)
        self.paused.append(hash)


def test_job_survives_browser_logout_and_is_visible_after_server_restart(tmp_path: Path):
    client = Client()
    app = create_app(tmp_path, password="test-password-long", connector=lambda *args: client)
    with TestClient(app) as browser:
        login(browser)
        browser.post("/api/setup/client", json={"client": "deluge", "host": "https://box.example"})
        created = browser.post(
            "/api/jobs", json={"kind": "manage", "action": "pause", "hashes": ["a" * 40]}
        )
        assert created.status_code == 202, created.text
        identifier = created.json()["id"]
        assert client.started.wait(2)
        changed = browser.post(
            "/api/setup/client", json={"client": "deluge", "host": "https://other.example"}
        )
        assert changed.status_code == 409
        browser.post("/api/logout")
        client.release.set()
        login(browser)
        job = finished(browser, identifier)
        assert job["status"] == "completed", job
        assert job["result"][0]["outcome"] == "sent"
    with TestClient(
        create_app(tmp_path, password="test-password-long", connector=lambda *args: client)
    ) as browser:
        login(browser)
        assert browser.get(f"/api/jobs/{identifier}").json()["status"] == "completed"
    assert client.paused == ["a" * 40]


def test_delete_requires_a_single_use_confirmation_bound_to_selected_torrents(tmp_path: Path):
    class DeletingClient(Client):
        def remove(self, hash, *, delete_files=False):
            self.paused.append((hash, delete_files))

    client = DeletingClient()
    with TestClient(
        create_app(tmp_path, password="test-password-long", connector=lambda *args: client)
    ) as browser:
        login(browser)
        browser.post("/api/setup/client", json={"client": "deluge", "host": "https://box.example"})
        body = {"kind": "manage", "action": "delete", "hashes": ["a" * 40]}
        assert browser.post("/api/jobs", json=body).status_code == 409
        preview = browser.post("/api/confirm", json=body).json()
        assert preview["torrents"][0]["name"] == "Book"
        assert "Torrent Client" in preview["warning"]
        body["confirmation"] = preview["token"]
        job = browser.post("/api/jobs", json=body)
        assert job.status_code == 202, job.text
        assert finished(browser, job.json()["id"])["status"] == "completed"
        assert client.paused == [("a" * 40, True)]
        assert browser.post("/api/jobs", json=body).status_code == 409


def test_torrents_are_paged_sorted_and_never_expose_announce_keys(tmp_path: Path):
    class ListingClient(Client):
        def torrents(self, **kwargs):
            return [
                Torrent(
                    "a" * 40,
                    "Alpha",
                    Path("/remote"),
                    size=1024,
                    state="uploading",
                    tracker="https://c411.org/announce/private-passkey",
                    connected_seeds=4,
                    connected_peers=2,
                ),
                Torrent("b" * 40, "Beta", Path("/remote"), size=4096),
            ]

    with TestClient(
        create_app(tmp_path, password="test-password-long", connector=lambda *args: ListingClient())
    ) as browser:
        login(browser)
        browser.post("/api/setup/client", json={"client": "deluge", "host": "https://box.example"})
        response = browser.post("/api/jobs", json={"kind": "refresh"})
        assert response.status_code == 202, response.text
        job = finished(browser, response.json()["id"])
        assert job["status"] == "completed", job
        result = browser.get(
            "/api/torrents", params={"sort": "size", "descending": True, "limit": 1}
        )
        assert result.json()["total"] == 2
        assert result.json()["rows"][0]["name"] == "Beta"
        result = browser.get("/api/torrents", params={"q": "Alpha"})
        assert result.json()["rows"][0]["peers"] == 2
        assert result.json()["rows"][0]["zen"] is not None
        assert "private-passkey" not in result.text


def test_search_can_queue_a_selected_result_but_remote_unmounted_sends_are_refused(
    tmp_path: Path, monkeypatch
):
    import httpx

    from torrentlinker import net

    def response(request):
        if request.url.params.get("t") == "caps":
            return httpx.Response(
                200, text='<caps><categories><category id="7000" name="Ebook"/></categories></caps>'
            )
        return httpx.Response(
            200,
            text=(
                '<rss xmlns:torznab="http://torznab.com/schemas/2015/feed"><channe'
                "l><item><title>Selected book</title><size>1024</size><link>https:"
                "//tracker.example/download?apikey=private-key</link><torznab:attr"
                ' name="infohash" '
                'value="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"/><torznab:attr '
                'name="seeders" value="4"/></item></channel></rss>'
            ),
        )

    monkeypatch.setattr(
        net, "client", lambda **kwargs: httpx.Client(transport=httpx.MockTransport(response))
    )
    with TestClient(
        create_app(tmp_path, password="test-password-long", connector=lambda *args: Client())
    ) as browser:
        login(browser)
        browser.post("/api/setup/client", json={"client": "deluge", "host": "https://box.example"})
        assert (
            browser.post(
                "/api/setup/indexer",
                json={"url": "https://tracker.example/api", "api_key": "private-key"},
            ).status_code
            == 200
        )
        created = browser.post("/api/jobs", json={"kind": "search", "query": "book"})
        assert created.status_code == 202, created.text
        job = finished(browser, created.json()["id"])
        assert job["status"] == "completed", job
        assert job["result"]["rows"][0]["title"] == "Selected book"
        assert "private-key" not in str(job)
        queued = browser.post("/api/jobs", json={"kind": "enqueue", "hashes": ["a" * 40]})
        assert queued.status_code == 400, queued.text
        assert "folder" in queued.text.lower()


def test_scan_runs_off_request_and_rejects_files_outside_storage(tmp_path: Path):
    root = tmp_path / "media"
    root.mkdir()
    (root / "Book.epub").write_bytes(b"book")

    class FilesClient(Client):
        def files(self, hash):
            return {"Book.epub": 4}

    with TestClient(
        create_app(
            tmp_path / "config",
            password="test-password-long",
            roots=(root,),
            connector=lambda *args: FilesClient(),
        )
    ) as browser:
        login(browser)
        browser.post("/api/setup/client", json={"client": "deluge", "host": "https://box.example"})
        browser.post(
            "/api/setup/folder",
            json={"local": str(root), "client_path": "/remote", "kind": "ebook"},
        )
        response = browser.post("/api/jobs", json={"kind": "scan"})
        assert response.status_code == 202, response.text
        job = finished(browser, response.json()["id"])
        assert job["status"] == "completed", job
        rows = browser.get("/api/library").json()["rows"]
        assert rows[0]["name"] == "Book.epub"
        outside = tmp_path / "private.txt"
        outside.write_text("private")
        (root / "escape.txt").symlink_to(outside)
        response = browser.post("/api/jobs", json={"kind": "scan"})
        job = finished(browser, response.json()["id"])
        assert job["status"] == "failed"
        # A failed refresh preserves the previous successful library.
        assert browser.get("/api/library").json()["rows"] == rows


def test_planning_without_mounted_storage_is_explicitly_unavailable(tmp_path: Path):
    with TestClient(
        create_app(tmp_path, password="test-password-long", connector=lambda *args: Client())
    ) as browser:
        login(browser)
        browser.post("/api/setup/client", json={"client": "deluge", "host": "https://box.example"})
        response = browser.post("/api/jobs", json={"kind": "plan"})
        assert response.status_code == 400
        assert "folder" in response.text.lower()


def test_missing_download_mount_is_not_treated_as_empty_storage(tmp_path: Path):
    root = tmp_path / "media"
    root.mkdir()
    (root / "Book.epub").write_bytes(b"book")

    class FilesClient(Client):
        def files(self, hash):
            return {"Book.epub": 4}

    with TestClient(
        create_app(
            tmp_path / "config",
            password="test-password-long",
            roots=(root,),
            connector=lambda *args: FilesClient(),
        )
    ) as browser:
        login(browser)
        browser.post("/api/setup/client", json={"client": "deluge", "host": "https://box.example"})
        assert (
            browser.post(
                "/api/setup/folder",
                json={"local": str(root), "client_path": "/remote", "purpose": "download"},
            ).status_code
            == 200
        )
        (root / "Book.epub").unlink()
        root.rmdir()
        response = browser.post("/api/jobs", json={"kind": "send-queue"})
        assert response.status_code == 400, response.text
        assert "storage" in response.text.lower() or "folder" in response.text.lower()
        # A disconnected mount can leave its empty mountpoint behind.
        root.mkdir()
        response = browser.post("/api/jobs", json={"kind": "send-queue"})
        assert response.status_code == 202, response.text
        job = finished(browser, response.json()["id"])
        assert job["status"] == "failed"
        assert "mapping" in job["error"].lower()


def test_selected_download_uses_verified_client_path_and_survives_queue_reload(
    tmp_path, monkeypatch
):
    import httpx

    from tests.fake_qbit import FakeQbit
    from tests.test_send import release
    from torrentlinker import net
    from torrentlinker.torrent_meta import read_torrent

    data = release(tmp_path)
    meta = read_torrent(data)
    root = tmp_path / "media"
    root.mkdir()
    (root / "existing.epub").write_bytes(b"book")

    class DownloadingClient(FakeQbit):
        def check(self):
            return "fake"

        def folder_settings(self):
            return []

    client = DownloadingClient()
    client.by_hash["a" * 40] = Torrent(
        "a" * 40, "Existing", Path("/downloads"), files={"existing.epub": 4}
    )

    def response(request):
        if request.url.path == "/file":
            return httpx.Response(200, content=data)
        if request.url.params.get("t") == "caps":
            return httpx.Response(200, text="<caps><categories/></caps>")
        return httpx.Response(
            200,
            text=(
                '<rss xmlns:torznab="http://torznab.com/schemas/2015/feed"><channel><item>'
                "<title>Film.2020</title><size>5001</size>"
                "<link>https://tracker.example/file?apikey=private-key</link>"
                '<enclosure url="https://tracker.example/file?apikey=private-key"/>'
                f'<torznab:attr name="infohash" value="{meta.infohash}"/>'
                '<torznab:attr name="seeders" value="4"/></item></channel></rss>'
            ),
        )

    monkeypatch.setattr(
        net, "client", lambda **kwargs: httpx.Client(transport=httpx.MockTransport(response))
    )

    def app():
        return create_app(
            tmp_path / "config",
            password="test-password-long",
            roots=(root,),
            connector=lambda *args: client,
        )

    with TestClient(app()) as browser:
        login(browser)
        assert (
            browser.post(
                "/api/setup/client", json={"client": "qbittorrent", "host": "https://box.example"}
            ).status_code
            == 200
        )
        assert (
            browser.post(
                "/api/setup/indexer",
                json={"url": "https://tracker.example/api", "api_key": "private-key"},
            ).status_code
            == 200
        )
        assert (
            browser.post(
                "/api/setup/folder",
                json={"local": str(root), "client_path": "/downloads", "purpose": "download"},
            ).status_code
            == 200
        )
        job = browser.post("/api/jobs", json={"kind": "search", "query": "Film"}).json()
        assert finished(browser, job["id"])["status"] == "completed"
        job = browser.post("/api/jobs", json={"kind": "enqueue", "hashes": [meta.infohash]}).json()
        assert finished(browser, job["id"])["result"]["queued"] == 1
    with TestClient(app()) as browser:
        login(browser)
        assert browser.get("/api/queue").json()[0]["status"] == "queued"
        job = browser.post("/api/jobs", json={"kind": "send-queue"}).json()
        result = finished(browser, job["id"])
        assert result["status"] == "completed", result
        assert result["result"]["added"] == 1, result
        assert browser.get("/api/queue").json()[0]["status"] == "sent"
        assert client.by_hash[meta.infohash].save_path == Path("/downloads")
        job = browser.post("/api/jobs", json={"kind": "send-queue"}).json()
        assert finished(browser, job["id"])["result"]["added"] == 0
    assert client.downloads == [meta.infohash]


def test_upload_preview_uses_local_profile_without_publishing(tmp_path: Path):
    root = tmp_path / "media"
    root.mkdir()
    (root / "Object.stl").write_text("solid model\nendsolid model\n")

    class FilesClient(Client):
        def files(self, hash):
            return {}

    with TestClient(
        create_app(
            tmp_path / "config",
            password="test-password-long",
            roots=(root,),
            connector=lambda *args: FilesClient(),
        )
    ) as browser:
        login(browser)
        browser.post("/api/setup/client", json={"client": "deluge", "host": "https://box.example"})
        browser.post(
            "/api/setup/folder",
            json={"local": str(root), "client_path": "/remote", "kind": "3d-model"},
        )
        job = browser.post("/api/jobs", json={"kind": "scan"}).json()
        assert finished(browser, job["id"])["status"] == "completed"
        created = browser.post(
            "/api/jobs", json={"kind": "upload-preview", "path": str(root / "Object.stl")}
        )
        assert created.status_code == 202, created.text
        preview = finished(browser, created.json()["id"])
        assert preview["status"] == "completed", preview
        assert preview["result"]["title"] == "Object.NOTAG.STL"
        assert preview["result"]["files"][0]["size"] == 27
        assert preview["result"]["warnings"]
        assert not preview["result"]["refusals"]
