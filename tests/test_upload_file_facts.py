"""Structured Upload preparation uses extracted facts without inventing rip source."""

import wave

from fastapi.testclient import TestClient

from tests.test_upload_queue import UploadClient
from tests.test_web_jobs import finished, login
from torrentlinker.web.app import create_app


def test_audio_preview_has_measured_track_facts_and_complete_generated_labels(tmp_path):
    album = tmp_path / "Album"
    album.mkdir()
    path = album / "01.wav"
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(44100)
        audio.writeframes(b"\0\0" * 44100)
    with TestClient(
        create_app(
            tmp_path / "config",
            password="test-password-long",
            roots=(album,),
            connector=lambda *args: UploadClient(),
        )
    ) as browser:
        login(browser)
        browser.post(
            "/api/setup/client", json={"client": "qbittorrent", "host": "https://box.example"}
        )
        browser.post(
            "/api/setup/folder",
            json={"local": str(album), "client_path": "/music", "kind": "music", "depth": 1},
        )
        scan = browser.post("/api/jobs", json={"kind": "scan"}).json()
        assert finished(browser, scan["id"])["status"] == "completed"
        job = browser.post(
            "/api/jobs",
            json={
                "kind": "upload-preview",
                "path": str(path),
                "upload": {"category": 3, "subcategory": 18},
            },
        ).json()
        result = finished(browser, job["id"])
        assert result["status"] == "completed", result
        preview = result["result"]
    facts = preview["file_facts"]
    assert facts["file_count"] == 1
    assert facts["audio"][0]["sample_rate"] == 44100
    assert facts["audio"][0]["bits"] == 16
    assert facts["audio"][0]["duration"] == 1
    assert facts["audio"][0]["measured_bitrate_kbps"] > 0
    assert facts["rip_source"]["kind"] == "unknown"
    assert "Fichiers : 1" in preview["nfo"]
    assert "Débit :" in preview["nfo"]
    assert preview["nfo_origin"] == "generated"
    assert "description.source" in {x["field"] for x in preview["presentation"]["missing_fields"]}


def test_unreadable_audio_remains_in_count_and_tracklist(tmp_path):
    from torrentlinker.matching import IgnoreList
    from torrentlinker.scan import scan_item
    from torrentlinker.upload import PROFILES, UploadRequest, upload_files
    from torrentlinker.upload_facts import known_fields
    from torrentlinker.upload_presentation import file_evidence

    album = tmp_path / "Album"
    album.mkdir()
    (album / "broken.flac").write_bytes(b"not an audio stream")
    item = scan_item(album)
    profile = PROFILES[3]
    profile.inspect(item, IgnoreList.default())
    request = UploadRequest(
        item,
        "Album.FLAC-NOTAG",
        upload_files(item, "Album.FLAC-NOTAG", IgnoreList.default()),
        "",
        "",
        3,
        18,
        {},
        {},
    )
    evidence = file_evidence(request)
    assert evidence["file_count"] == 1
    assert evidence["audio"] == []
    assert evidence["unreadable_audio"][0]["file"].endswith("broken.flac")
    fields = known_fields(request, evidence)
    assert fields["tracks"] == "1"
    assert "broken (duration unknown)" in fields["tracklist"]
    assert "duration" not in fields
