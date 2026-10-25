"""Opt-in multi-turn list acceptance against the local model, with no real downloads."""

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests import test_assistant_live
from tests.fake_qbit import FakeQbit
from torrentlinker.domain import PathMapping, Torrent
from torrentlinker.downloads import IndexerCategory
from torrentlinker.store import CatalogueRow

controlled = test_assistant_live.controlled
pytestmark = pytest.mark.skipif(
    not os.getenv("TL_LIVE_MODEL_URL"), reason="explicit local model endpoint required"
)


def list_workflow(controlled, tmp_path):
    browser, provider, clients, _ = controlled
    setup = browser.app.state.agent_service.setup
    root = tmp_path / "list-media"
    root.mkdir()
    (root / "existing.epub").write_bytes(b"book")
    setup.roots = (root,)
    setup.settings.path_mappings = [PathMapping(str(root), "/downloads")]
    setup.settings.indexer_categories = {
        2030: IndexerCategory("Films"),
        3000: IndexerCategory("Musique"),
        7000: IndexerCategory("Ebooks"),
        2040: IndexerCategory("Séries"),
        4000: IndexerCategory("Jeux vidéo"),
        5000: IndexerCategory("Logiciels"),
        8000: IndexerCategory("Modèles 3D"),
        7100: IndexerCategory("Bandes dessinées"),
        9000: IndexerCategory("Autres"),
    }
    setup.settings.download_folders.by_category = {2030: str(root), 3000: str(root)}
    setup.settings.free_space_margin = 0
    setup.save()
    client = FakeQbit()
    client.by_hash["a" * 40] = Torrent(
        "a" * 40, "Existing book", Path("/downloads"), files={"existing.epub": 4}, progress=1
    )
    setup._client = client
    setup._indexer = SimpleNamespace(
        url="https://test.invalid", redact=lambda value: value, unredact=lambda value: value
    )
    setup.store.save_catalogue(
        [
            CatalogueRow(
                f"{i:040x}",
                f"Film {i:02}",
                i * 1000,
                5,
                2030,
                f"https://test.invalid/{i}",
                "",
                1,
            )
            for i in range(1, 13)
        ]
        + [
            CatalogueRow(
                f"{100 + i:040x}",
                f"Album {i:02}",
                i * 100,
                5,
                3000,
                f"https://test.invalid/{100 + i}",
                "",
                1,
            )
            for i in range(1, 52)
        ]
        + [
            CatalogueRow(
                f"{base + i:040x}",
                f"{name} {i:02}",
                i * unit,
                5,
                category,
                f"https://test.invalid/{base + i}",
                "",
                1,
            )
            for base, category, name, unit in [
                (1000, 2040, "Série", 2000),
                (2000, 7000, "Ebook", 50),
                (3000, 4000, "Jeu vidéo", 5000),
                (4000, 5000, "Logiciel", 3000),
                (5000, 8000, "Modèle 3D", 200),
                (6000, 7100, "Bande dessinée", 100),
            ]
            for i in range(1, 7)
        ]
        + [CatalogueRow("f" * 40, "Tiny other", 1, 5, 9000, "https://test.invalid/other", "", 1)]
    )
    created = browser.post(
        "/api/assistant/conversations",
        json={
            "name": "Durable mixed torrent list",
            "provider_id": provider,
            "max_calls": 20,
            "max_seconds": 180,
            "policy": {
                "name": "Queue only",
                "clients": ["default"],
                "mode": "execute",
                "permissions": ["queue"],
                "daily_bytes": 0,
                "daily_torrents": 0,
                "reserve_bytes": 0,
            },
        },
    )
    assert created.is_success, created.text
    thread = created.json()["id"]
    return browser, thread, client, clients


def test_live_build_refine_extend_and_queue_a_durable_list_across_turns(controlled, tmp_path):
    browser, thread, client, clients = list_workflow(controlled, tmp_path)
    results = []
    for step, message in enumerate(
        [
            "Pour le client default, prépare une liste durable nommée Weekend contenant les "
            "10 films les plus légers du catalogue. Sauvegarde-la pour nos prochaines demandes. "
            "Ne mets rien en file et ne lance aucun téléchargement.",
            "Dans cette même liste Weekend, ne garde que les 5 films les plus légers. "
            "Sauvegarde cette modification, sans mettre en file ni télécharger.",
            "Ajoute maintenant les 50 albums de musique les plus légers du catalogue à Weekend. "
            "Conserve les 5 films déjà choisis. Sauvegarde, sans mettre en file ni télécharger.",
            "Affine seulement la partie films de Weekend : garde les 3 films les plus légers "
            "et conserve les 50 albums. Sauvegarde et donne le nombre total et le poids exact "
            "en octets. Ne mets rien en file et ne télécharge rien.",
            "Mets maintenant toute la liste Weekend sauvegardée en file de téléchargement. "
            "Utilise sa révision enregistrée, conserve la liste et ne démarre rien.",
        ],
        1,
    ):
        result = test_assistant_live.run(browser, thread, message, f"durable-list-turn-{step}")
        assert result["status"] == "completed", result
        results.append(result)
        assert not client.downloads and not client.started and not client.removed, result
        assert set(client.by_hash) == {"a" * 40}, result
        if step < 5:
            assert browser.get("/api/queue").json() == [], result
            writes = [
                event["result"]
                for event in result["events"]
                if event["tool"] in {"create_torrent_list", "edit_torrent_list"}
                and "revision" in event.get("result", {})
            ]
            assert writes, result
            expected_count, expected_bytes = [
                (10, 55_000),
                (5, 15_000),
                (55, 142_500),
                (53, 133_500),
            ][step - 1]
            assert (writes[-1]["count"], writes[-1]["total_size_bytes"]) == (
                expected_count,
                expected_bytes,
            ), result

    assert any(e["tool"] == "create_torrent_list" for e in results[0]["events"])
    for result in results[1:4]:
        assert any(e["tool"] == "edit_torrent_list" for e in result["events"]), result
    assert any(e["tool"] == "select_torrent_list" for e in results[-1]["events"])
    queued = browser.get("/api/queue").json()
    expected = {f"{i:040x}" for i in range(1, 4)} | {f"{100 + i:040x}" for i in range(1, 51)}
    assert {row["hash"] for row in queued} == expected
    assert len(queued) == 53
    assert all(client.reads == 0 for client in clients.values())


def test_live_mixed_categories_preserve_other_groups_and_deduplicate_additions(
    controlled, tmp_path
):
    browser, thread, client, _ = list_workflow(controlled, tmp_path)
    prompts = [
        "Pour le client default, crée une liste durable nommée Collection avec les 3 ebooks "
        "et les 3 séries les plus légers du catalogue. Sauvegarde-la. Ne mets rien en file "
        "et ne télécharge rien.",
        "Ajoute à Collection les 2 jeux vidéo et les 2 logiciels les plus légers du catalogue. "
        "Préserve les ebooks et les séries. Sauvegarde, sans mettre en file ni télécharger.",
        "Ajoute aussi les 2 modèles 3D et les 2 bandes dessinées les plus légers du catalogue "
        "à Collection. Conserve tout le reste et sauvegarde. "
        "Aucune mise en file ou téléchargement.",
        "Retire uniquement les séries de Collection. Conserve toutes les autres catégories "
        "et sauvegarde la liste. Ne mets rien en file et ne télécharge rien.",
        "Ajoute de nouveau les 3 ebooks les plus légers à Collection en évitant les doublons, "
        "tout en préservant les autres catégories. Sauvegarde et donne le total exact en octets. "
        "Ne mets rien en file et ne télécharge rien.",
    ]
    for step, (prompt, expected) in enumerate(
        zip(
            prompts,
            [(6, 12_300), (10, 36_300), (14, 37_200), (11, 25_200), (11, 25_200)],
            strict=True,
        ),
        1,
    ):
        result = test_assistant_live.run(browser, thread, prompt, f"mixed-categories-turn-{step}")
        assert result["status"] == "completed", result
        # Read through the public list service to verify storage, even when dedup is a no-op.
        service = browser.app.state.assistant
        _, actor = service.conversation(thread)
        saved = browser.app.state.agent_service.torrent_lists.listing(actor, "default", 0, 50)
        rows = saved["lists"]
        assert len(rows) == 1, saved
        assert (rows[0]["count"], rows[0]["total_size_bytes"]) == expected, result
        assert browser.get("/api/queue").json() == []
        assert not client.downloads and not client.started and not client.removed


def test_live_rediscovers_saved_mixed_list_and_compares_actual_client_states(controlled, tmp_path):
    from tests.test_web_jobs import finished
    from torrentlinker.agent.service import AgentRequest
    from torrentlinker.catalogue_selection import CatalogueCriteria

    browser, thread, client, _ = list_workflow(controlled, tmp_path)
    service = browser.app.state.agent_service
    _, actor = browser.app.state.assistant.conversation(thread)
    selected = service.request(
        actor,
        "fixture-mixed-selection",
        AgentRequest(
            kind="select-catalogue",
            client_id="default",
            catalogue_selection=CatalogueCriteria(
                categories=[2030, 3000, 2040, 7000, 4000, 5000, 8000, 7100], count=1000
            ),
        ),
    )
    assert finished(browser, selected["job_id"])["status"] == "completed"
    saved = service.torrent_lists.create(
        actor, "fixture-saved-list", "default", "Collection retrouvée", selected["job_id"]
    )
    assert saved["count"] == 99
    for number in [1, 101, 1001, 2001, 3001, 4001, 5001, 6001]:
        identity = f"{number:040x}"
        client.by_hash[identity] = Torrent(
            identity, f"Client item {number}", Path("/downloads"), progress=1, state="uploading"
        )
    for number, progress, state in [
        (3002, 1, "pausedUP"),
        (5002, 1, "checkingUP"),
        (102, 0.5, "downloading"),
    ]:
        identity = f"{number:040x}"
        client.by_hash[identity] = Torrent(
            identity, f"Client item {number}", Path("/downloads"), progress=progress, state=state
        )
    result = test_assistant_live.run(
        browser,
        thread,
        "Retrouve ma liste durable Collection retrouvée pour le client default. "
        "Compare-la à ce que le client contient actuellement : distingue les torrents en seed "
        "actif, terminés mais en pause, terminés dans un autre état, incomplets et absents. "
        "Donne les comptes exacts pour toute la liste, sans confondre un torrent en pause ou "
        "en vérification avec du seed actif. Ne modifie ni la liste ni le client.",
        "durable-list-rediscovery-comparison",
    )
    assert result["status"] == "completed", result
    assert any(e["tool"] == "list_torrent_lists" for e in result["events"]), result
    comparisons = [
        e["result"] for e in result["events"] if e["tool"] == "compare_torrent_list_client"
    ]
    assert comparisons, result
    assert {key: value["count"] for key, value in comparisons[-1]["groups"].items()} == {
        "actively_seeding": 8,
        "completed_paused": 1,
        "completed_other": 1,
        "incomplete": 1,
        "absent": 88,
    }
    latest = service.torrent_lists.listing(actor, "default", 0, 50)["lists"][0]
    assert latest["revision"] == saved["revision"]
    assert browser.get("/api/queue").json() == []
    assert not client.downloads and not client.started and not client.removed
