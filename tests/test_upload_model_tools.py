"""External MCP and web review share saved image assets and exact revisions."""

from fastapi.testclient import TestClient

from tests.test_agent_torrent_lists import tool
from tests.test_upload_completeness import complete_form
from tests.test_upload_queue import UploadClient
from tests.test_web_jobs import finished, login
from torrentlinker.web.app import create_app

OBJ = "v 0 0 0\nv 1 0 0\nv 0 1 0\nv 0 0 1\nf 1 2 3\nf 1 2 4\n"


def test_mcp_renders_all_parts_then_saves_and_edits_private_review(tmp_path):
    media = tmp_path / "media"
    pack = media / "Pack"
    pack.mkdir(parents=True)
    for index in range(13):
        (pack / f"piece-{index}.obj").write_text(OBJ)
    app = create_app(
        tmp_path / "config",
        password="test-password-long",
        roots=(media,),
        connector=lambda *args: UploadClient(),
    )
    with TestClient(app) as browser:
        login(browser)
        browser.post(
            "/api/setup/client", json={"client": "qbittorrent", "host": "https://box.example"}
        )
        browser.post(
            "/api/setup/folder",
            json={
                "local": str(media),
                "client_path": "/models",
                "kind": "3d-model",
            },
        )
        scan = browser.post("/api/jobs", json={"kind": "scan"}).json()
        assert finished(browser, scan["id"])["status"] == "completed"
        grant = browser.post(
            "/api/agents",
            json={
                "name": "Upload editor",
                "clients": ["default"],
                "mode": "execute",
                "permissions": ["uploads"],
            },
        ).json()
        browser.put("/api/agents", json={"enabled": True})
        token = grant["token"]
        inspected = tool(browser, token, "inspect_3d_models", client_id="default", path=str(pack))
        inventory = finished(browser, inspected["job_id"])
        assert inventory["status"] == "completed", inventory
        models = inventory["result"]["models"]
        assert len(models) == 13
        assert models[0]["triangles"] == 2
        pieces = [row["file"] for row in models]
        rendered = tool(
            browser,
            token,
            "create_3d_contact_sheet",
            client_id="default",
            path=str(pack),
            pieces=pieces,
            cameras={pieces[0]: {"preset": "front", "roll": 90}},
        )
        render_job = finished(browser, rendered["job_id"])
        assert render_job["status"] == "completed", render_job
        result = render_job["result"]
        assert result["complete"] is True
        assert result["covered"] == pieces
        assert len(result["artifacts"]) == 2
        from tests.test_agent_access import call

        pixels = call(
            browser,
            token,
            "read_upload_asset",
            {
                "client_id": "default",
                "path": str(pack),
                "asset_id": result["artifacts"][0]["asset_id"],
            },
        )
        assert pixels["content"][0]["type"] == "image"
        assert pixels["content"][0]["mimeType"] == "image/png"
        assert result["artifacts"][0]["metadata"]["pieces"][0]["camera"]["roll"] == 90
        form = complete_form(10, 53)
        form["description"] = form["description"].replace(
            "[img]https://example.org/cover.jpg[/img]", ""
        )
        form.update(
            image="",
            nfo_origin="generated",
            assets=[row["asset_id"] for row in result["artifacts"]],
        )
        partial = tool(
            browser,
            token,
            "preview_upload",
            client_id="default",
            path=str(pack),
            upload={**form, "assets": form["assets"][:1]},
        )
        partial_job = finished(browser, partial["job_id"])
        assert partial_job["status"] == "completed", partial_job
        assert len(partial_job["result"]["file_facts"]["image_coverage"]["missing"]) == 4
        assert partial_job["result"]["presentation"]["local_review_ready"] is False
        saved = tool(
            browser,
            token,
            "save_upload_draft",
            request_id="save",
            client_id="default",
            path=str(pack),
            upload=form,
        )
        saved_job = finished(browser, saved["job_id"])
        assert saved_job["status"] == "completed", saved_job
        draft = saved_job["result"]
        assert draft["review"]["presentation"]["local_review_ready"] is True
        assert draft["review"]["presentation"]["send_ready"] is False
        page = tool(
            browser,
            token,
            "present_upload_drafts",
            request_id="present",
            client_id="default",
            drafts=[{"draft_id": draft["id"], "revision": 1}],
        )
        detail = tool(
            browser,
            token,
            "get_presentation_item",
            presentation_id=page["presentation_id"],
            item_id="0",
        )
        queue_preview = browser.get(f"/api/upload/queue/{draft['id']}/preview?revision=1").json()
        assert detail["description_images"] == queue_preview["description_images"]
        assert len(detail["description_images"]) == 2
        edited = tool(
            browser,
            token,
            "update_upload_fields",
            request_id="edit",
            client_id="default",
            draft_id=draft["id"],
            revision=1,
            fields={"title": "Edited.Pack.OBJ-NOTAG"},
            synopsis="Une collection de treize pièces pour impression 3D.",
            field_sources={"title": "owner"},
        )
        changed = finished(browser, edited["job_id"])
        assert changed["status"] == "completed", changed
        assert changed["result"]["revision"] == 2
        assert changed["result"]["form"]["title"] == "Edited.Pack.OBJ-NOTAG"
        assert changed["result"]["form"]["assets"] == form["assets"]
        conflicted = tool(
            browser,
            token,
            "update_upload_fields",
            request_id="conflict",
            client_id="default",
            draft_id=draft["id"],
            revision=2,
            fields={"format": "STEP"},
            field_sources={"format": "owner"},
        )
        conflict_job = finished(browser, conflicted["job_id"])
        assert conflict_job["status"] == "completed", conflict_job
        saved_conflict = conflict_job["result"]
        assert "[b]Format :[/b] STEP" in saved_conflict["form"]["description"]
        assert saved_conflict["form"]["field_provenance"]["format"]["kind"] == "user_supplied"
        evidence = saved_conflict["review"]["file_facts"]
        assert evidence["fields"]["format"]["extracted_value"] == "obj"
        assert saved_conflict["review"]["presentation"]["local_review_ready"] is False
        assert all(path.read_text() == OBJ for path in pack.glob("*.obj"))


def test_synopsis_only_mcp_edit_preserves_every_other_form_field(tmp_path):
    from tests.test_agent_access import call

    media = tmp_path / "media"
    media.mkdir()
    path = media / "Object.stl"
    path.write_text("solid model\nendsolid model\n")
    app = create_app(
        tmp_path / "config",
        password="test-password-long",
        roots=(media,),
        connector=lambda *args: UploadClient(),
    )
    with TestClient(app) as browser:
        login(browser)
        browser.post(
            "/api/setup/client", json={"client": "qbittorrent", "host": "https://box.example"}
        )
        browser.post(
            "/api/setup/folder",
            json={"local": str(media), "client_path": "/models", "kind": "3d-model"},
        )
        scan = browser.post("/api/jobs", json={"kind": "scan"}).json()
        assert finished(browser, scan["id"])["status"] == "completed"
        queued = browser.post(
            "/api/jobs",
            json={
                "kind": "upload-queue",
                "path": str(path),
                "upload": {**complete_form(10, 51), "image": "", "nfo_origin": "original"},
            },
        ).json()
        saved = finished(browser, queued["id"])
        assert saved["status"] == "completed", saved
        draft = saved["result"]
        grant = browser.post(
            "/api/agents",
            json={
                "name": "Editor",
                "clients": ["default"],
                "mode": "execute",
                "permissions": ["uploads"],
            },
        ).json()
        browser.put("/api/agents", json={"enabled": True})
        for misplaced in ("description", "synopsis", "description.synopsis"):
            rejected = call(
                browser,
                grant["token"],
                "update_upload_fields",
                {
                    "request_id": "wrong-" + misplaced,
                    "client_id": "default",
                    "draft_id": draft["id"],
                    "revision": draft["revision"],
                    "fields": {misplaced: "Texte relu localement."},
                },
            )["structuredContent"]
            assert "top-level synopsis" in rejected["error"]
            unchanged = browser.get("/api/upload/queue").json()[0]
            assert unchanged["revision"] == draft["revision"]
            assert unchanged["form"] == draft["form"]
        edited = tool(
            browser,
            grant["token"],
            "update_upload_fields",
            request_id="synopsis-only",
            client_id="default",
            draft_id=draft["id"],
            revision=draft["revision"],
            synopsis="Texte relu localement.",
        )
        changed = finished(browser, edited["job_id"])
        assert changed["status"] == "completed", changed
        result = changed["result"]
        assert result["id"] == draft["id"] and result["revision"] == draft["revision"] + 1
        assert "Texte relu localement." in result["form"]["description"]
        assert {k: v for k, v in result["form"].items() if k != "description"} == {
            k: v for k, v in draft["form"].items() if k != "description"
        }
        assert path.read_text() == "solid model\nendsolid model\n"
