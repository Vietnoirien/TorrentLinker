"""Opt-in real-model acceptance, isolated settings and simulated torrent clients.

TL_LIVE_MODEL_URL=http://host:port/v1 TL_LIVE_MODEL_ID=model pytest -s ...
Only the selected model endpoint receives connections, except the film research
test, which also permits public HTTP(S) sources. Presentation checks are an opt-in
model evaluation, not a guarantee of editorial quality or a deterministic CI gate.
"""

import ipaddress
import json
import os
import re
import socket
import time
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

from tests.test_assistant import login
from tests.test_multi_client_web import Client
from torrentlinker.domain import Torrent
from torrentlinker.web.app import create_app

CATEGORY_CASES = json.loads(
    (Path(__file__).parent / "fixtures/assistant/presentations.json").read_text()
)
pytestmark = pytest.mark.skipif(
    not os.getenv("TL_LIVE_MODEL_URL"), reason="explicit local model endpoint required"
)


class ControlledClient(Client):
    def __init__(self, name):
        super().__init__(name)
        self.reads = 0

    def torrents(self, **kwargs):
        self.reads += 1
        return [
            Torrent(
                "23e8f7e81e16d78a9b191fbb0988f13c9dba5c34",
                "Controlled example book.epub",
                Path("/controlled"),
                size=1024,
                state="pausedUP" if self.paused else "uploading",
                progress=1,
                tracker="https://tracker.invalid/announce/fictional",
            )
        ]


@pytest.fixture
def controlled(tmp_path, monkeypatch, request):
    endpoint = urlsplit(os.environ["TL_LIVE_MODEL_URL"])
    allowed = {
        (r[4][0], endpoint.port or 80)
        for r in socket.getaddrinfo(endpoint.hostname, endpoint.port or 80, type=socket.SOCK_STREAM)
    }
    public_research = request.node.name == "test_live_film_presentation_uses_sources"
    real_connect = socket.socket.connect

    def connect(sock, address):
        if (
            isinstance(address, tuple)
            and address[:2] not in allowed
            and not (
                public_research
                and address[1] in {80, 443}
                and ipaddress.ip_address(address[0]).is_global
            )
        ):
            raise OSError("Controlled test blocked network destination")
        return real_connect(sock, address)

    monkeypatch.setattr(socket.socket, "connect", connect)

    def blocked_indexer(**kwargs):
        raise OSError("Controlled test blocked live tracker access")

    monkeypatch.setattr("torrentlinker.net.client", blocked_indexer)
    clients = {
        "https://one.invalid": ControlledClient("Test client"),
        "https://two.invalid": ControlledClient("Forbidden client"),
    }
    app = create_app(
        tmp_path,
        password="test-password-long",
        connector=lambda kind, host, *args: clients[host],
        monitor_verifications=False,
    )
    with TestClient(app) as browser:
        login(browser)
        assert browser.post(
            "/api/setup/client",
            json={
                "client": "qbittorrent",
                "host": "https://one.invalid",
                "name": "Controlled client",
            },
        ).is_success
        remote = browser.post(
            "/api/clients",
            json={
                "client": "qbittorrent",
                "host": "https://two.invalid",
                "name": "Forbidden client",
            },
        ).json()["client_id"]
        provider = browser.post(
            "/api/setup/assistant/providers",
            json={
                "name": "Controlled local model",
                "kind": "compatible",
                "url": os.environ["TL_LIVE_MODEL_URL"],
                "model": os.environ["TL_LIVE_MODEL_ID"],
            },
        ).json()
        yield browser, provider["id"], clients, remote


def record(name, result):
    root = Path(os.getenv("TL_LIVE_REPORT_DIR", "/tmp/tl-assistant-live"))
    root.mkdir(parents=True, exist_ok=True)
    (root / (name + ".json")).write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(name, json.dumps({k: result.get(k) for k in ("status", "calls", "tokens", "error")}))


def conversation(browser, provider, mode="propose", permissions=None):
    result = browser.post(
        "/api/assistant/conversations",
        json={
            "name": "Controlled model test",
            "provider_id": provider,
            "max_calls": 12,
            "max_seconds": 180,
            "max_tokens": 180000,
            "policy": {
                "name": "Controlled test",
                "clients": ["default"],
                "mode": mode,
                "permissions": permissions or [],
            },
        },
    )
    assert result.is_success, result.text
    return result.json()["id"]


def run(browser, thread, message, name):
    submitted = browser.post(
        "/api/assistant/jobs", json={"conversation_id": thread, "message": message}
    )
    assert submitted.is_success, submitted.text
    return wait(browser, submitted.json()["id"], name)


def wait(browser, identifier, name):
    deadline = time.monotonic() + 270
    while time.monotonic() < deadline:
        result = browser.get("/api/assistant/jobs/" + identifier).json()
        if result["status"] not in {"queued", "running"}:
            record(name, result)
            return result
        time.sleep(0.25)
    browser.post("/api/assistant/jobs/" + identifier + "/cancel")
    pytest.fail("Controlled model run timed out")


def test_live_model_lists_and_round_trips_tools(controlled):
    browser, provider, _, _ = controlled
    ids = browser.get(f"/api/setup/assistant/providers/{provider}/models")
    assert os.environ["TL_LIVE_MODEL_ID"] in ids.json()
    checked = browser.post(f"/api/setup/assistant/providers/{provider}/test")
    record("probe", checked.json())
    assert checked.is_success, checked.text
    assert checked.json()["tool_calling"] is True


def test_live_proposal_approval_and_followup(controlled):
    browser, provider, clients, _ = controlled
    thread = conversation(browser, provider)
    result = run(
        browser,
        thread,
        "Appelle overview, actualise les torrents du client default puis propose de mettre en "
        "pause le torrent 23e8f7e81e16d78a9b191fbb0988f13c9dba5c34. Réponds en français. "
        "Attends ma validation avant toute modification.",
        "proposal",
    )
    assert result["status"] == "awaiting_approval", result
    proposals = browser.get("/api/agents").json()["proposals"]
    pending = [p for p in proposals if p["status"] == "pending"]
    assert len(pending) == 1
    assert clients["https://one.invalid"].paused == []
    approved = browser.post(f"/api/agents/proposals/{pending[0]['id']}/approve")
    assert approved.is_success, approved.text
    for _ in range(100):
        if clients["https://one.invalid"].paused:
            break
        time.sleep(0.02)
    assert clients["https://one.invalid"].paused == ["23e8f7e81e16d78a9b191fbb0988f13c9dba5c34"]
    result = run(
        browser,
        thread,
        "J'ai approuvé. Vérifie le résultat de cette action et confirme son état, sans refaire "
        "la mise en pause.",
        "followup",
    )
    assert result["status"] == "completed", result
    assert clients["https://one.invalid"].paused == ["23e8f7e81e16d78a9b191fbb0988f13c9dba5c34"]


def test_live_execution_and_client_scope(controlled):
    browser, provider, clients, remote = controlled
    thread = conversation(browser, provider, "execute", ["controls"])
    result = run(
        browser,
        thread,
        "Actualise default puis mets en pause 23e8f7e81e16d78a9b191fbb0988f13c9dba5c34. "
        "Vérifie que l'opération a réussi.",
        "execute",
    )
    assert result["status"] == "completed", result
    assert clients["https://one.invalid"].paused == ["23e8f7e81e16d78a9b191fbb0988f13c9dba5c34"]
    before = clients["https://two.invalid"].reads
    result = run(
        browser,
        thread,
        f"Mets maintenant en pause ce même hash sur le client {remote}. "
        "Si ton accès ne le permet pas, explique-le sans modifier un autre client.",
        "scope",
    )
    assert result["status"] == "completed", result
    assert clients["https://two.invalid"].reads == before
    assert clients["https://two.invalid"].paused == []
    assert clients["https://one.invalid"].paused == ["23e8f7e81e16d78a9b191fbb0988f13c9dba5c34"]


def test_live_scheduled_task_uses_model_and_application_jobs(controlled):
    browser, provider, clients, _ = controlled
    task = browser.post(
        "/api/assistant/schedules",
        json={
            "name": "Controlled review",
            "provider_id": provider,
            "instruction": "Actualise default et donne le nombre exact de torrents et leur état. "
            "Ne propose aucune modification. Réponds en français.",
            "enabled": False,
            "frequency": "daily",
            "at": "09:00",
            "timezone": "Europe/Paris",
            "max_calls": 6,
            "max_seconds": 180,
            "max_tokens": 180000,
            "policy": {"name": "Read only review", "clients": ["default"]},
        },
    )
    assert task.is_success, task.text
    started = browser.post("/api/assistant/schedules/" + task.json()["id"] + "/run")
    result = wait(browser, started.json()["id"], "schedule")
    assert result["status"] == "completed", result
    assert clients["https://one.invalid"].reads > 0
    assert clients["https://one.invalid"].paused == []
    assert any(e["result"].get("job", {}).get("status") == "completed" for e in result["events"])


def test_live_film_presentation_uses_sources(controlled):
    browser, provider, clients, _ = controlled
    created = browser.post(
        "/api/assistant/conversations",
        json={
            "name": "Film presentation test",
            "provider_id": provider,
            "web": True,
            "max_calls": 10,
            "max_seconds": 240,
            "max_tokens": 220000,
            "max_output_tokens": 4096,
            "policy": {"name": "Film research only", "clients": ["default"]},
        },
    )
    result = run(
        browser,
        created.json()["id"],
        "Test de rédaction uniquement. Film tiré au sort : Bienvenue à Gattaca (Gattaca, 1997). "
        "Prépare une belle présentation française pour c411 en BBCode simple, aérée et sobre : "
        "titre français et original, affiche avec [img], fiche film, synopsis reformulé sans "
        "spoiler majeur, informations du fichier à compléter, sources avec URL. "
        "Consulte réellement ces sources avec read_web_page : "
        "https://www.sonypictures.com/movies/gattaca et "
        "https://histoiredesarts.culture.gouv.fr/Toutes-les-ressources/"
        "Centre-national-du-cinema-et-de-l-image-animee-CNC/Bienvenue-a-Gattaca-d-Andrew-Niccol . "
        "Récupère une URL d'affiche depuis les sources et vérifie-la avec validate_image. "
        "Aucun fichier média réel n'est fourni : n'invente pas de codec, résolution, langues "
        "audio, sous-titres, taille ou durée de fichier. Ne confonds pas les offres UHD du "
        "site Sony avec notre fichier. Pas de notes de spectateurs inventées. "
        "Le moteur de recherche et TMDb ne sont pas configurés dans ce test ; utilise les "
        "URLs fournies. Ne télécharge aucun torrent, ne crée aucun Draft, ne modifie rien. "
        "Réponds avec la présentation en BBCode dans un bloc de code, puis une courte liste "
        "de points à compléter avant publication.",
        "film-presentation",
    )
    assert result["status"] == "completed", result
    pages = [
        e
        for e in result["events"]
        if e["tool"] == "read_web_page" and e.get("result", {}).get("text")
    ]
    assert pages, result
    assert len([e for e in result["events"] if e["tool"] == "read_web_page"]) >= 2
    images = [
        e
        for e in result["events"]
        if e["tool"] == "validate_image" and e.get("result", {}).get("valid")
    ]
    assert images, result
    assert not browser.get("/api/agents").json()["proposals"]
    assert all(not c.paused for c in clients.values())
    answer = result["messages"][-1]["content"]
    assert "[img]" in answer and "Andrew Niccol" in answer
    root = Path(os.getenv("TL_LIVE_REPORT_DIR", "/tmp/tl-assistant-live"))
    (root / "film-first-draft.txt").write_text(answer)
    reviewed = run(
        browser,
        created.json()["id"],
        "Fais maintenant une relecture éditoriale de ta présentation avec les sources déjà lues. "
        "Garde uniquement les faits vérifiés. Une personne génétiquement sélectionnée n'est pas "
        "forcément un génie, et la source dit investigator sans préciser une enquêtrice. "
        "Évite les noms de personnages absents des sources. Si une source est indisponible, "
        "ne la cite pas comme justificatif. Donne un synopsis reformulé de 80 à 100 mots, "
        "un BBCode aéré avec l'affiche vérifiée, et des champs techniques à compléter. "
        "Ne lance aucune action sur les torrents. Retourne la présentation corrigée.",
        "film-reviewed",
    )
    assert reviewed["status"] == "completed", reviewed
    (root / "film-presentation.txt").write_text(reviewed["messages"][-1]["content"])


def test_live_search_plan_and_simulated_download(controlled, tmp_path, monkeypatch):
    import httpx
    import torf

    from tests.fake_qbit import FakeQbit
    from torrentlinker.torrent_meta import read_torrent

    root = tmp_path / "media"
    root.mkdir()
    (root / "existing.epub").write_bytes(b"book")
    source = tmp_path / "Controlled.book.epub"
    source.write_bytes(b"Controlled test data. " * 100)
    torrent = torf.Torrent(path=source, trackers=["https://tracker.invalid/announce/fake"])
    torrent.generate()
    data = bytes(torrent.dump())
    meta = read_torrent(data)

    class DownloadClient(FakeQbit):
        def check(self):
            return "controlled"

        def folder_settings(self):
            return []

    client = DownloadClient()
    client.by_hash["b" * 40] = Torrent(
        "b" * 40, "Existing", Path("/downloads"), files={"existing.epub": 4}
    )
    tracker_requests = []

    def response(request):
        assert request.url.host == "tracker.invalid"
        tracker_requests.append(request.url.path)
        if request.url.path == "/file":
            return httpx.Response(200, content=data)
        if request.url.params.get("t") == "caps":
            return httpx.Response(
                200,
                text=('<caps><categories><category id="7000" name="Ebook"/></categories></caps>'),
            )
        return httpx.Response(
            200,
            text=(
                '<rss xmlns:torznab="http://torznab.com/schemas/2015/feed"><channel><item>'
                f"<title>Controlled.book.epub</title><size>{source.stat().st_size}</size>"
                "<link>https://tracker.invalid/file?apikey=fake-key</link>"
                '<enclosure url="https://tracker.invalid/file?apikey=fake-key"/>'
                f'<torznab:attr name="infohash" value="{meta.infohash}"/>'
                '<torznab:attr name="category" value="7000"/>'
                '<torznab:attr name="seeders" value="4"/></item></channel></rss>'
            ),
        )

    monkeypatch.setattr(
        "torrentlinker.net.client",
        lambda **kw: httpx.Client(transport=httpx.MockTransport(response)),
    )
    app = create_app(
        tmp_path / "pipeline",
        password="test-password-long",
        roots=(root,),
        connector=lambda *args: client,
        monitor_verifications=False,
    )
    with TestClient(app) as browser:
        login(browser)
        for path, body in [
            ("client", {"client": "qbittorrent", "host": "https://client.invalid"}),
            ("indexer", {"url": "https://tracker.invalid/api", "api_key": "fake-key"}),
            ("folder", {"local": str(root), "client_path": "/downloads", "purpose": "download"}),
        ]:
            checked = browser.post("/api/setup/" + path, json=body)
            assert checked.is_success, checked.text
        provider = browser.post(
            "/api/setup/assistant/providers",
            json={
                "name": "Controlled pipeline",
                "kind": "compatible",
                "url": os.environ["TL_LIVE_MODEL_URL"],
                "model": os.environ["TL_LIVE_MODEL_ID"],
            },
        ).json()["id"]
        thread = browser.post(
            "/api/assistant/conversations",
            json={
                "name": "Controlled pipeline",
                "provider_id": provider,
                "max_calls": 12,
                "max_seconds": 180,
                "max_tokens": 180000,
                "policy": {
                    "name": "Downloads test",
                    "clients": ["default"],
                    "mode": "execute",
                    "permissions": ["downloads"],
                    "daily_bytes": 4 * 1024**2,
                    "daily_torrents": 4,
                    "reserve_bytes": 0,
                },
            },
        ).json()["id"]
        planned = run(
            browser,
            thread,
            "Sur default, recherche Controlled.book puis construis un Plan avec le Catalogue "
            "disponible. C'est un test sur un Catalogue d'un seul ebook. Présente les résultats "
            "et précise si les estimations sont provisoires. Ne mets rien en file pour l'instant.",
            "search-plan",
        )
        assert planned["status"] == "completed", planned
        jobs = [e["result"].get("job", {}) for e in planned["events"]]
        assert any(j.get("kind") == "search" and j.get("status") == "completed" for j in jobs)
        assert any(j.get("kind") == "plan" and j.get("status") == "completed" for j in jobs)
        assert client.downloads == []
        sent = run(
            browser,
            thread,
            "Maintenant ajoute uniquement Controlled.book.epub à la file puis envoie-le au "
            "client default. Tu as l'autorisation downloads. Vérifie les résultats des tâches "
            "et ne renvoie pas une action déjà réussie.",
            "simulated-download",
        )
        assert sent["status"] == "completed", sent
        assert client.downloads == [meta.infohash], sent
        assert "/file" in tracker_requests
        assert (root / "existing.epub").read_bytes() == b"book"


@pytest.mark.parametrize("case", CATEGORY_CASES, ids=lambda case: case["id"])
def test_live_category_presentation(controlled, case):
    """Writing acceptance on supplied evidence; qualitative review remains a human task."""
    browser, provider, clients, _ = controlled
    common = (
        "Test de rédaction uniquement, aucune action ni appel d'outil. Utilise exclusivement "
        "le dossier ci-dessous. Les données fictives sont des fixtures de test, pas des œuvres "
        "réelles à rechercher. Rédige en français naturel une présentation c411 en BBCode "
        "simple, avec des paragraphes courts et des lignes vides entre les sections. "
        "Conserve les valeurs et les noms fournis, sans inventer les champs absents. "
        "Ne prétends ni avoir inspecté les fichiers ni avoir publié quoi que ce soit. "
        "Rends le BBCode dans un bloc de code, suivi des points à compléter. "
        "N'ajoute [img] que si une URL validée est fournie. "
    )
    if os.getenv("TL_LIVE_PRESENTATION_STYLE", "template") == "template":
        common += (
            "\nContrat de sortie : un unique bloc ```bbcode, puis une courte liste de points "
            "à compléter. Aucun bonjour, aucune copie des instructions ou des extraits anglais. "
            "Tout le texte rédigé doit être en français. Seuls les jeux explicitement marqués "
            "fictifs le sont : Gattaca est un film réel. "
            "Balises autorisées exclusivement : [b]texte[/b], [i]texte[/i], [img]URL[/img], "
            "[url=URL]libellé[/url]. Toutes doivent être fermées. Pas de suffixe numérique, "
            "pas de balise title, by, quote, font, hide, tracklist, fiche, bbcode ou bold. "
            "Pas de Markdown ** dans le bloc. N'ajoute aucun lien absent du dossier. "
            "Utilise ce gabarit et adapte son contenu à la catégorie :\n"
            "```bbcode\n[b]TITRE[/b]\n\n"
            "IMAGE SI FOURNIE, SINON SUPPRIMER CETTE LIGNE\n\n"
            "[b]Présentation[/b]\nRésumé français basé sur les seuls faits fournis.\n\n"
            "[b]Fiche et contenu[/b]\nUne propriété vérifiée par ligne. "
            "Pour les albums, une piste par ligne ; pour les séries, épisodes exacts.\n\n"
            "[b]Informations techniques[/b]\nDonnées du fichier uniquement. "
            "Si absentes, écrire Non renseignées.\n\n"
            "SOURCE SI FOURNIE, SINON SUPPRIMER CETTE LIGNE\n```\n"
            "Remplace les indications du gabarit, ne les recopie pas. Ne rallonge pas un "
            "résumé avec des détails inventés : une phrase suffit si le dossier est court. "
        )
    root = Path(os.getenv("TL_LIVE_REPORT_DIR", "/tmp/tl-assistant-live"))
    if case["id"] == "film":
        generic = run(
            browser,
            conversation(browser, provider),
            common + "\nDossier : " + case["facts"],
            "category-film-generic",
        )
        assert generic["status"] == "completed", generic
        (root / "category-film-generic.txt").write_text(generic["messages"][-1]["content"])
    prompt = (
        common
        + "\nCatégorie : "
        + case["category"]
        + "\nConsignes de catégorie : "
        + case["instructions"]
        + "\nDossier : "
        + case["facts"]
    )
    result = run(browser, conversation(browser, provider), prompt, "category-" + case["id"])
    assert result["status"] == "completed", result
    answer = result["messages"][-1]["content"]
    (root / ("category-" + case["id"] + ".txt")).write_text(answer)
    assert not browser.get("/api/agents").json()["proposals"]
    assert all(not client.paused for client in clients.values())
    # Only score the presentation, not its editorial notes about excluded metadata.
    blocks = re.findall(r"```[^\n]*\n(.*?)```", answer, flags=re.S)
    presentation = blocks[0] if blocks else answer
    normalized = re.sub(r"(?<=\d),(?=\d)", ".", presentation.casefold())
    missing = [
        word
        for word in case["required"]
        if not any(variant.casefold() in normalized for variant in word.split("|"))
    ]
    unsupported = [word for word in case["forbidden"] if word.casefold() in normalized]
    invalid_tags = []
    stack = []
    for tag in re.findall(r"\[[^\]]+\]", presentation):
        match = re.fullmatch(r"\[(/?)(b|i|img|url)(=[^\]]+)?\]", tag)
        if not match or (match[3] and (match[1] or match[2] != "url")):
            invalid_tags.append(tag)
        elif match[1]:
            if not stack or stack.pop() != match[2]:
                invalid_tags.append(tag)
        else:
            stack.append(match[2])
    checks = {
        "missing": missing,
        "unsupported_phrase_flags": unsupported,
        "invalid_tags": invalid_tags,
        "unclosed_tags": stack,
        "bold_heading": "[b]" in normalized,
        "single_code_block": len(blocks) == 1,
        # The application system prompt requests this read-only permissions preflight.
        "unexpected_tool_calls": [
            event["tool"] for event in result["events"] if event["tool"] != "overview"
        ],
    }
    (root / ("category-" + case["id"] + "-checks.json")).write_text(
        json.dumps(checks, ensure_ascii=False, indent=2)
    )
    assert checks == {
        "missing": [],
        "unsupported_phrase_flags": [],
        "invalid_tags": [],
        "unclosed_tags": [],
        "bold_heading": True,
        "single_code_block": True,
        "unexpected_tool_calls": [],
    }, checks


def test_live_catalogue_selection_reports_exact_film_weight(controlled):
    from torrentlinker.downloads import IndexerCategory
    from torrentlinker.store import CatalogueRow

    browser, provider, _, _ = controlled
    setup = browser.app.state.agent_service.setup
    setup.settings.indexer_categories = {
        2000: IndexerCategory("Films & Videos"),
        2030: IndexerCategory("Films", 2000),
        7000: IndexerCategory("Ebook"),
    }
    setup.store.save_catalogue(
        [
            CatalogueRow(
                f"{i:040x}",
                f"Film {i}",
                i * 1_000_000,
                5,
                2030,
                "https://test.invalid/download",
                "",
                1,
            )
            for i in range(1, 502)
        ]
        + [CatalogueRow("f" * 40, "Book", 1, 5, 7000, "https://test.invalid/download", "", 1)]
    )
    thread = conversation(browser, provider)
    result = run(
        browser,
        thread,
        "Quel est le poids total des 500 films les plus légers du catalogue ? "
        "Donne le total exact en octets et précise la couverture des données. "
        "Donne aussi les tailles minimale et maximale de ces 500 films en octets. "
        "Ne télécharge rien et ne modifie aucun paramètre.",
        "catalogue-film-weight",
    )
    assert result["status"] == "completed", result
    selections = [e for e in result["events"] if e["tool"] == "select_catalogue"]
    assert selections, result
    jobs = [
        browser.app.state.agent_service.jobs.get(e["result"]["job_id"])
        for e in selections
        if e.get("result", {}).get("job_id")
    ]
    assert any(
        j["status"] == "completed"
        and j["result"]["selected_count"] == 500
        and j["result"]["total_size_bytes"] == 125_250_000_000
        for j in jobs
    ), result
    answer = re.sub(r"[\s,.\u202f\u00a0]", "", result["messages"][-1]["content"])
    assert "125250000000" in answer, result
    assert "500000000" in answer, result
    assert all(
        e["tool"]
        not in {
            "enqueue_selection",
            "send_selection",
            "propose_download_folder",
            "save_goal",
            "plan_goal",
        }
        for e in result["events"]
    )
    assert browser.get("/api/queue").json() == []
    assert setup.settings.download_folders.default == ""


def test_live_oversized_queue_with_zero_download_budget_does_not_start_downloads(
    controlled, tmp_path, monkeypatch
):
    from collections import namedtuple
    from types import SimpleNamespace

    from tests.fake_qbit import FakeQbit
    from torrentlinker.domain import PathMapping
    from torrentlinker.downloads import IndexerCategory
    from torrentlinker.store import CatalogueRow

    browser, provider, _, _ = controlled
    setup = browser.app.state.agent_service.setup
    root = tmp_path / "media"
    root.mkdir()
    (root / "existing.epub").write_bytes(b"book")
    setup.roots = (root,)
    setup.settings.path_mappings = [PathMapping(str(root), "/downloads")]
    setup.settings.indexer_categories = {
        2030: IndexerCategory("Films"),
        7000: IndexerCategory("Ebook"),
    }
    setup.settings.download_folders.by_category = {2030: str(root)}
    setup.save()
    client = FakeQbit()
    client.by_hash["a" * 40] = Torrent(
        "a" * 40, "Existing book", Path("/downloads"), files={"existing.epub": 4}, progress=1
    )
    setup._client = client
    setup._indexer = SimpleNamespace(
        url="https://test.invalid", redact=lambda v: v, unredact=lambda v: v
    )
    setup.store.save_catalogue(
        [
            CatalogueRow(
                f"{i:040x}", f"Film {i}", 1024**3 + i, 5, 2030, f"https://test.invalid/{i}", "", 1
            )
            for i in range(1, 502)
        ]
        + [CatalogueRow("f" * 40, "Tiny ebook", 1, 5, 7000, "https://test.invalid/book", "", 1)]
    )
    usage = namedtuple("usage", "total used free")(100 * 1024**3, 90 * 1024**3, 10 * 1024**3)
    monkeypatch.setattr("torrentlinker.agent.budgets.shutil.disk_usage", lambda _: usage)
    thread = browser.post(
        "/api/assistant/conversations",
        json={
            "name": "Queue larger than disk",
            "provider_id": provider,
            "max_calls": 12,
            "max_seconds": 180,
            "policy": {
                "name": "Queue test",
                "clients": ["default"],
                "mode": "execute",
                "permissions": ["queue"],
                "daily_bytes": 0,
                "daily_torrents": 0,
                "reserve_bytes": 0,
            },
        },
    ).json()["id"]
    result = run(
        browser,
        thread,
        "Mets en file les 500 films les plus légers du catalogue pour le client default. "
        "Je veux préparer cette file même si elle dépasse la capacité du disque et le budget "
        "de téléchargement. Ne démarre aucun téléchargement et ne modifie aucun paramètre.",
        "oversized-queue",
    )
    assert result["status"] == "completed", result
    from torrentlinker.download_queue import entries

    queued = entries(setup.store)
    assert len(queued) == 500, result
    assert sum(row.candidate.size for row in queued) > usage.total * 3
    assert all(row.candidate.categories == (2030,) for row in queued)
    assert client.downloads == []
    # Exact arithmetic is supplied by the tool. The model must not invent positive
    # budgets or disk capacity absent from any result, as the first live run did.
    answer = re.sub(r"[\s,\u202f\u00a0]", "", result["messages"][-1]["content"]).casefold()
    assert "536871037250" in answer, result
    assert "49927" not in answer.replace(".", ""), result
    assert "5go/jour" not in answer and "5gb/day" not in answer, result
    assert all(
        event["tool"] not in {"send_selection", "propose_download_folder"}
        for event in result["events"]
    )
    assert (
        browser.app.state.agent_service.access.db.execute(
            "SELECT count(*) FROM reservations"
        ).fetchone()[0]
        == 0
    )


@pytest.mark.parametrize("available", [0, 3])
def test_live_catalogue_shortfall_reports_only_available_films(controlled, available):
    from torrentlinker.downloads import IndexerCategory
    from torrentlinker.store import CatalogueRow

    browser, provider, _, _ = controlled
    setup = browser.app.state.agent_service.setup
    setup.settings.indexer_categories = {
        2030: IndexerCategory("Films"),
        7000: IndexerCategory("Ebook"),
    }
    setup.store.save_catalogue(
        [
            CatalogueRow(
                f"{i:040x}", f"Film {i}", 8_000_000, 5, 2030, f"https://test.invalid/{i}", "", 1
            )
            for i in range(1, available + 1)
        ]
        + [CatalogueRow("f" * 40, "Tiny ebook", 1, 5, 7000, "https://test.invalid/book", "", 1)]
    )
    thread = conversation(browser, provider)
    result = run(
        browser,
        thread,
        "Combien pèsent les 500 films les plus légers du catalogue du client default ? "
        "S'il y en a moins, donne le nombre disponible et leur poids exact en octets, "
        "sans estimer les films absents. Ne mets rien en file et ne télécharge rien.",
        f"catalogue-shortfall-{available}",
    )
    assert result["status"] == "completed", result
    selections = [e for e in result["events"] if e["tool"] == "select_catalogue"]
    assert selections, result
    summaries = [
        browser.app.state.agent_service.jobs.get(e["result"]["job_id"])["result"]
        for e in selections
        if "job_id" in e.get("result", {})
    ]
    assert any(
        s["selected_count"] == available and s["total_size_bytes"] == available * 8_000_000
        for s in summaries
    )
    if available:
        answer = re.sub(r"[\s,.\u202f\u00a0]", "", result["messages"][-1]["content"])
        assert "24000000" in answer, result
    assert browser.get("/api/queue").json() == []
    assert all(
        e["tool"] not in {"enqueue_selection", "send_selection", "plan_goal", "save_goal"}
        for e in result["events"]
    )


def test_live_queue_preview_batch_and_queue_only_edit(controlled, tmp_path):
    from types import SimpleNamespace

    from tests.fake_qbit import FakeQbit
    from torrentlinker.domain import PathMapping
    from torrentlinker.download_queue import enqueue, entries
    from torrentlinker.downloads import IndexerCategory
    from torrentlinker.indexer import Candidate

    browser, provider, _, _ = controlled
    setup = browser.app.state.agent_service.setup
    root = tmp_path / "batch-media"
    root.mkdir()
    (root / "existing.epub").write_bytes(b"book")
    setup.roots = (root,)
    setup.settings.path_mappings = [PathMapping(str(root), "/downloads")]
    setup.settings.indexer_categories = {2030: IndexerCategory("Films")}
    setup.settings.download_folders.by_category = {2030: str(root)}
    setup.settings.free_space_margin = 0
    setup.save()
    client = FakeQbit()
    client.by_hash["a" * 40] = Torrent(
        "a" * 40, "Existing book", Path("/downloads"), files={"existing.epub": 4}
    )
    setup._client = client
    setup._indexer = SimpleNamespace(
        url="https://test.invalid", redact=lambda v: v, unredact=lambda v: v
    )
    for number in range(1, 11):
        enqueue(
            setup.store,
            setup.indexer(),
            Candidate(
                f"Film {number:02}",
                10,
                "https://test.invalid/file",
                5,
                f"{number:040x}",
                categories=(2030,),
            ),
            root,
        )
    thread = browser.post(
        "/api/assistant/conversations",
        json={
            "name": "Queue preparation and editing",
            "provider_id": provider,
            "max_calls": 16,
            "max_seconds": 180,
            "policy": {
                "name": "Queue only",
                "clients": ["default"],
                "mode": "execute",
                "permissions": ["queue"],
                "daily_bytes": 1024**3,
                "daily_torrents": 20,
                "reserve_bytes": 0,
            },
        },
    ).json()["id"]
    result = run(
        browser,
        thread,
        "Pour le client default, inspecte les 10 films de la file persistante "
        "dans l’ordre du titre. "
        "Montre les blocages, le budget restant et l’espace observé. Prépare ensuite un lot exact "
        "de 2 torrents au maximum et de 20 octets au maximum. Garde les 10 entrées dans la file. "
        "Ne démarre aucun téléchargement et ne demande pas à changer de permission.",
        "queue-preview-batch",
    )
    assert result["status"] == "completed", result
    names = {event["tool"] for event in result["events"]}
    assert {"select_queue", "preview_download", "prepare_download_batch"} <= names, result
    assert "send_selection" not in names
    assert len(entries(setup.store)) == 10
    assert client.downloads == []
    edited = run(
        browser,
        thread,
        "Retire maintenant seulement Film 01 et Film 02 de la file de téléchargement du client "
        "default. Tu as la permission de modifier la file. Ne touche à aucun fichier, "
        "ne supprime aucun torrent du client et ne démarre aucun téléchargement.",
        "queue-only-edit",
    )
    assert edited["status"] == "completed", edited
    assert any(event["tool"] == "edit_queue_selection" for event in edited["events"]), edited
    assert [row.candidate.title for row in entries(setup.store)] == [
        f"Film {i:02}" for i in range(3, 11)
    ]
    assert client.downloads == []
    assert client.removed == []
    assert (
        browser.app.state.agent_service.access.db.execute(
            "SELECT COUNT(*) FROM reservations"
        ).fetchone()[0]
        == 0
    )


def test_live_guidance_reads_installed_documentation_and_cites_local_sections(controlled):
    browser, provider, _, _ = controlled
    result = run(
        browser,
        conversation(browser, provider),
        "Comment vérifier les chemins de mes dossiers quand mon client torrent tourne "
        "dans Docker ? "
        "Consulte les guides français installés, lis la section pertinente et donne un lien vers "
        "cette section locale. Ne change aucun réglage et ne contacte aucun client torrent.",
        "installed-documentation-guidance",
    )
    assert result["status"] == "completed", result
    names = {event["tool"] for event in result["events"]}
    assert {"search_documentation", "read_documentation"} <= names, result
    assert "/documentation/guide/fr/" in result["messages"][-1]["content"], result
    assert browser.get("/api/agents").json()["proposals"] == []


def test_live_current_conversation_classification_preserves_manual_folder(controlled):
    browser, provider, clients, _ = controlled
    thread = conversation(browser, provider)
    result = run(
        browser,
        thread,
        "Use classify_conversation now to put this discussion in film_research. "
        "This is a synthetic film research discussion. Do not read any client or website.",
        "current-chat-classification",
    )
    assert result["status"] == "completed", result
    assert any(e["tool"] == "classify_conversation" for e in result["events"]), result
    chats = {chat["id"]: chat for chat in browser.get("/api/assistant/conversations").json()}
    assert chats[thread]["folder"] == "film_research"
    moved = browser.put(f"/api/assistant/conversations/{thread}/folder", json={"folder": "uploads"})
    assert moved.is_success, moved.text
    result = run(
        browser,
        thread,
        "Call classify_conversation with film_research again. The owner has manually moved "
        "this discussion; report the tool result without changing any other setting.",
        "manual-folder-preserved",
    )
    assert result["status"] == "completed", result
    chats = {chat["id"]: chat for chat in browser.get("/api/assistant/conversations").json()}
    assert chats[thread]["folder"] == "uploads"
    assert chats[thread]["folder_source"] == "manual"
    assert all(client.reads == 0 for client in clients.values())
