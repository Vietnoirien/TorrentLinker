"""Opt-in real local-model Upload review with generated files and no tracker access."""

import hashlib
import os
import wave
import zipfile

import pytest

from tests import test_assistant_live
from tests.test_web_jobs import finished

DEMO_IMAGE = (
    "https://raw.githubusercontent.com/Vietnoirien/TorrentLinker/"
    "main/src/torrentlinker/assets/icon.png"
)

controlled = test_assistant_live.controlled
pytestmark = pytest.mark.skipif(
    not os.getenv("TL_LIVE_MODEL_URL"), reason="explicit local model endpoint required"
)


def sample_file(root, kind, language="en"):
    root.mkdir()
    if kind == "ebook":
        path = root / "Test Author - The Lunar Archive.epub"
        with zipfile.ZipFile(path, "w") as book:
            book.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
            book.writestr(
                "META-INF/container.xml",
                '<?xml version="1.0"?><container version="1.0" '
                'xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>'
                '<rootfile full-path="content.opf" media-type="application/oebps-package+xml"/>'
                "</rootfiles></container>",
            )
            book.writestr(
                "content.opf",
                '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" '
                'unique-identifier="id"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
                '<dc:identifier id="id">urn:uuid:tl-test-lunar</dc:identifier>'
                "<dc:title>The Lunar Archive</dc:title><dc:creator>Test Author</dc:creator>"
                f'<dc:language>{language}</dc:language></metadata><manifest><item id="chapter" '
                'href="chapter.xhtml" media-type="application/xhtml+xml"/></manifest>'
                '<spine><itemref idref="chapter"/></spine></package>',
            )
            book.writestr(
                "chapter.xhtml",
                '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Test</title></head>'
                "<body><h1>The Lunar Archive</h1><p>Un livre fictif pour tester "
                "les brouillons.</p></body></html>"
                if language == "fr"
                else "<body><h1>The Lunar Archive</h1><p>A fictional test book.</p></body></html>",
            )
    elif kind == "music":
        path = root / "Test Artist - Silence.wav"
        with wave.open(str(path), "wb") as audio:
            audio.setnchannels(2)
            audio.setsampwidth(2)
            audio.setframerate(44100)
            audio.writeframes(b"\x00" * 44100 * 4)
    else:
        path = root / "Test Triangle.stl"
        path.write_text(
            "solid triangle\nfacet normal 0 0 1\nouter loop\nvertex 0 0 0\n"
            "vertex 1 0 0\nvertex 0 1 0\nendloop\nendfacet\nendsolid triangle\n"
        )
    return path


@pytest.mark.parametrize(
    "kind,card_kind", [("ebook", "ebook"), ("music", "music"), ("3d-model", "model3d")]
)
def test_local_model_creates_and_presents_upload_drafts(controlled, tmp_path, kind, card_kind):
    browser, provider, clients, _ = controlled
    path = sample_file(tmp_path / "files" / "samples", kind, language="fr")
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    configured = browser.post(
        "/api/setup/folder",
        json={"local": str(path.parent), "client_path": "/test-samples", "kind": kind},
    )
    assert configured.is_success, configured.text
    submitted = browser.post("/api/jobs", json={"kind": "scan", "client_id": "default"})
    assert submitted.is_success, submitted.text
    assert finished(browser, submitted.json()["id"])["status"] == "completed"
    thread = test_assistant_live.conversation(
        browser, provider, "execute", ["uploads"], max_calls=24
    )
    result = test_assistant_live.run(
        browser,
        thread,
        f"Prépare un brouillon d'upload LOCAL pour le fichier de test {path} du client default. "
        f"Son type est {kind}. Enregistre-le dans la file locale, puis présente-le en carte "
        "cliquable pour que je puisse relire la description, le NFO et les fichiers. "
        "Utilise une présentation française complète suivant les exigences de la catégorie, "
        "précisant que c'est un fichier de test généré. Voici les faits de ces fixtures : "
        "Ebook : auteur Test Author, titre The Lunar Archive, contenu réellement français. "
        "Audio : artiste Test Artist, album Silence, année 2026, source création originale, "
        "une piste Silence de 1 seconde, WAV PCM 16 bits stéréo 44100 Hz, débit 1411.2 kb/s. "
        "3D : un triangle STL généré, sans autre contenu. N'utilise que les faits de la catégorie "
        "concernée et les tailles/nombres de fichiers retournés par les outils. "
        f"L’image de démonstration TorrentLinker est {DEMO_IMAGE} ; conserve cette "
        "URL sans la télécharger. Ne prétends pas que le contenu est prêt à publier : affiche "
        "les avertissements/refus éventuels. N'envoie rien à c411 et ne lance aucun "
        "téléchargement.",
        "upload-draft-" + kind,
    )
    assert result["status"] == "completed", result
    presentations = [
        event["result"]
        for event in result["events"]
        if event["tool"] == "present_upload_drafts"
        and event.get("result", {}).get("presentation_id")
    ]
    assert presentations, result
    drafts = browser.get("/api/upload/queue").json()
    assert len(drafts) == 1, drafts
    draft = drafts[0]
    assert draft["status"] == "queued"
    assert draft["path"] == str(path)
    assert draft["form"]["reviewed"] is False
    assert draft["review"]["presentation"]["status"] == "complete", draft["review"]
    page = browser.get(
        "/api/assistant/presentations/" + presentations[-1]["presentation_id"]
    ).json()
    assert page["count"] == 1
    item = page["items"][0]
    assert item["kind"] == card_kind
    assert item["draft_revision"] == draft["revision"]
    assert item["size_bytes"] == path.stat().st_size
    assert item["image_url"] == DEMO_IMAGE
    detail = browser.get(
        f"/api/assistant/presentations/{page['presentation_id']}/items/{item['item_id']}"
    ).json()
    queue_preview = browser.get(
        f"/api/upload/queue/{draft['id']}/preview?revision={draft['revision']}&client_id=default"
    ).json()
    for key in ("nfo", "files", "description_html", "upload_review", "upload_form"):
        assert detail[key] == queue_preview[key], key
    assert detail["nfo"] == draft["form"]["nfo"]
    assert detail["files"] == draft["files"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    assert not list(tmp_path.rglob("*.torrent"))
    assert browser.get("/api/queue").json() == []
    assert all(not client.paused for client in clients.values())
    test_assistant_live.record(
        "upload-draft-" + kind + "-verified",
        {"status": "passed", "draft": draft, "presentation": page, "detail": detail},
    )

    if kind == "ebook":
        updated = test_assistant_live.run(
            browser,
            thread,
            "Modifie le MÊME brouillon enregistré : ajoute à la description la phrase exacte "
            "'Relecture locale validée pour le test.' puis enregistre cette nouvelle révision "
            "localement et présente-la à nouveau en carte. Conserve les fichiers, le titre et "
            "l'image. Ne crée pas un deuxième brouillon et n'envoie rien à c411.",
            "upload-draft-ebook-refinement",
        )
        assert updated["status"] == "completed", updated
        rows = browser.get("/api/upload/queue").json()
        assert len(rows) == 1 and rows[0]["id"] == draft["id"], rows
        revised = rows[0]
        assert revised["revision"] > draft["revision"]
        assert "Relecture locale validée pour le test." in revised["form"]["description"]
        assert revised["form"]["image"] == draft["form"]["image"]
        assert revised["form"]["title"] == draft["form"]["title"]
        assert revised["files"] == draft["files"]
        shown = [
            event["result"]
            for event in updated["events"]
            if event["tool"] == "present_upload_drafts"
            and event.get("result", {}).get("presentation_id")
        ]
        assert shown and shown[-1]["items"][0]["draft_revision"] == revised["revision"]
        old = browser.get(
            f"/api/assistant/presentations/{page['presentation_id']}/items/{item['item_id']}"
        ).json()
        assert old["draft_changed"] is True
        assert old["description_html"] == detail["description_html"]
        assert (
            browser.get(
                f"/api/upload/queue/{draft['id']}/preview?revision={draft['revision']}"
            ).status_code
            == 409
        )
        latest = browser.get(
            f"/api/upload/queue/{draft['id']}/preview?revision={revised['revision']}"
        ).json()
        assert "Relecture locale validée pour le test." in latest["description_html"]
        assert revised["status"] == "queued" and not revised["form"]["reviewed"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == before
        assert not list(tmp_path.rglob("*.torrent"))
        test_assistant_live.record(
            "upload-draft-ebook-refinement-verified",
            {
                "status": "passed",
                "old_revision": draft["revision"],
                "new_revision": revised["revision"],
                "draft_id": revised["id"],
                "old_card_marked_changed": old["draft_changed"],
            },
        )


def test_local_model_reports_foreign_ebook_instead_of_presenting_it(controlled, tmp_path):
    browser, provider, _, _ = controlled
    path = sample_file(tmp_path / "files" / "foreign", "ebook", language="en")
    browser.post(
        "/api/setup/folder",
        json={"local": str(path.parent), "client_path": "/foreign", "kind": "ebook"},
    )
    job = browser.post("/api/jobs", json={"kind": "scan"}).json()
    assert finished(browser, job["id"])["status"] == "completed"
    thread = test_assistant_live.conversation(
        browser, provider, "execute", ["uploads"], max_calls=24
    )
    result = test_assistant_live.run(
        browser,
        thread,
        f"Prépare un brouillon local pour {path} sur default et montre-le uniquement si la "
        "présentation est complète. Vérifie la langue réelle dans les faits des outils, ne "
        "suppose pas du français. Si bloqué, enregistre le travail incomplet localement et "
        "explique précisément ce qui manque ou empêche la présentation. "
        f"Image de démonstration {DEMO_IMAGE} ; auteur Test Author. "
        "C'est un fichier de test. N'envoie et ne télécharge rien.",
        "upload-foreign-ebook",
    )
    assert result["status"] == "completed", result
    assert not any(
        e["tool"] == "present_upload_drafts" and e.get("result", {}).get("presentation_id")
        for e in result["events"]
    )
    rows = browser.get("/api/upload/queue").json()
    assert rows and rows[0]["review"]["presentation"]["status"] == "incomplete", rows
    assert any(
        "language" in f["field"] for f in rows[0]["review"]["presentation"]["missing_fields"]
    )
    assert not list(tmp_path.rglob("*.torrent"))
