from fastapi.testclient import TestClient

from tests.test_agent_access import call
from tests.test_web_jobs import finished, login
from torrentlinker.web.app import create_app


def test_mcp_upload_draft_and_seeding_require_owner_approval(tmp_path, monkeypatch):
    import httpx

    from tests.fake_qbit import FakeQbit
    from torrentlinker import net

    class UploadClient(FakeQbit):
        def check(self):
            return "fake"

        def folder_settings(self):
            return []

    def response(request):
        if request.url.params.get("t") == "caps":
            return httpx.Response(200, text="<caps><categories/></caps>")
        if request.method == "POST":
            return httpx.Response(200, json={"data": {"id": 123}})
        return httpx.Response(200, json={"data": []})

    monkeypatch.setattr(
        net, "client", lambda **kwargs: httpx.Client(transport=httpx.MockTransport(response))
    )
    root = tmp_path / "media"
    models, other = root / "models", root / "other"
    models.mkdir(parents=True)
    other.mkdir()
    item = models / "Object.stl"
    item.write_text("solid model\nendsolid model\n")
    client = UploadClient()
    with TestClient(
        create_app(
            tmp_path / "config",
            password="test-password-long",
            roots=(root,),
            connector=lambda *args: client,
        )
    ) as browser:
        login(browser)
        grant = browser.post(
            "/api/agents", json={"name": "Upload test", "clients": ["default"]}
        ).json()
        browser.put("/api/agents", json={"enabled": True})
        token = grant["token"]
        sequence = 0

        def submit(operation):
            nonlocal sequence
            sequence += 1
            request = {
                "request_id": f"upload-{sequence}",
                "operation": {**operation, "client_id": "default"},
            }
            proposal = call(browser, token, "propose_action", request)["structuredContent"]
            if operation["kind"] in ("upload-draft", "upload-seed"):
                assert proposal["requires_owner_approval"] is True
                assert proposal["job_id"] == ""
                approved = browser.post(f"/api/agents/proposals/{proposal['id']}/approve")
                assert approved.status_code == 200, approved.text
                proposal = approved.json()
            return httpx.Response(202, json={"id": proposal["job_id"]})

        browser.post(
            "/api/setup/client", json={"client": "qbittorrent", "host": "https://box.example"}
        )
        assert (
            browser.post(
                "/api/setup/indexer",
                json={"url": "https://c411.org/api/torznab", "api_key": "fake-key"},
            ).status_code
            == 200
        )
        browser.post("/api/setup/announce", json={"value": "https://c411.org/announce/fake"})
        browser.post(
            "/api/setup/folder",
            json={"local": str(models), "client_path": "/models", "kind": "3d-model"},
        )
        job = submit({"kind": "scan"}).json()
        assert finished(browser, job["id"])["status"] == "completed"
        job = submit(
            {
                "kind": "upload-draft",
                "path": str(item),
                "upload": {"image": "https://images.example/model.png", "reviewed": True},
            },
        ).json()
        draft = finished(browser, job["id"])
        assert draft["status"] == "completed", draft
        assert (
            browser.post(
                "/api/setup/folder", json={"local": str(other), "client_path": "/other"}
            ).status_code
            == 200
        )
        assert (
            browser.post("/api/setup/remove-folder", json={"local": str(other)}).status_code == 200
        )
        job = submit({"kind": "upload-seed", "hashes": [draft["result"]["hash"]]}).json()
        seeded = finished(browser, job["id"])
        assert seeded["status"] == "completed", seeded
        assert seeded["result"]["status"] == "verifying"
        assert item.read_text() == "solid model\nendsolid model\n"
