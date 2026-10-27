"""Capture the real Assistant widgets with isolated, fictional data and a model stub."""

from pathlib import Path
from tempfile import TemporaryDirectory

import httpx
from fastapi.testclient import TestClient
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from torrentlinker import i18n
from torrentlinker.gui.assistant import AssistantEditor, AssistantTab
from torrentlinker.gui.theme import apply_theme
from torrentlinker.web.app import create_app

application = QApplication([])
application.setApplicationName("TorrentLinker documentation")
apply_theme(application, "dark")

for language in ("fr", "en"):
    french = language == "fr"
    translators = i18n.install(application, language)
    question = (
        "Prépare un Plan de trois ebooks, dans une limite de 30 Mio. Présente-moi les choix."
        if french
        else "Prepare a Plan of three ebooks within 30 MiB. Show me the choices."
    )
    answer = (
        "Je peux préparer ce Plan après avoir actualisé les torrents et le Catalogue.\n\n"
        "Client autorisé : qBittorrent. Budget demandé : 30 Mio, trois torrents maximum.\n\n"
        "Le mode Propositions seules attend votre validation avant tout téléchargement.\n\n"
        "Exemple de documentation : aucune donnée réelle ni action sur c411."
        if french
        else "I can prepare this Plan after refreshing the torrents and Catalogue.\n\n"
        "Allowed client: qBittorrent. Requested budget: 30 MiB, at most three torrents.\n\n"
        "Proposals only mode waits for your approval before downloading.\n\n"
        "Documentation example: no real data or c411 actions."
    )

    def response(request, answer=answer):
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"role": "assistant", "content": answer}}],
                "usage": {"total_tokens": 120},
            },
        )

    with TemporaryDirectory(prefix="tl-assistant-docs-") as temporary:
        app = create_app(
            Path(temporary),
            password="documentation-only-password",
            assistant_transport=httpx.MockTransport(response),
        )
        with TestClient(app) as browser:
            browser.headers["X-TorrentLinker"] = "1"
            browser.post("/api/login", json={"password": "documentation-only-password"})
            provider = browser.post(
                "/api/setup/assistant/providers",
                json={"name": "Ollama local", "kind": "ollama", "model": "modele-local"},
            ).json()
            conversation = {
                "name": "Mon prochain Plan" if french else "My next Plan",
                "provider_id": provider["id"],
                "policy": {"name": "Assistant", "clients": ["default"]},
            }
            c = browser.post("/api/assistant/conversations", json=conversation).json()
            run = browser.post(
                "/api/assistant/jobs", json={"conversation_id": c["id"], "message": question}
            ).json()
            for _ in range(100):
                if browser.get("/api/assistant/jobs/" + run["id"]).json()["status"] == "completed":
                    break
                QTest.qWait(20)
            output = Path("docs/guide/images") / ("en" if not french else "")
            output.mkdir(parents=True, exist_ok=True)
            widget = AssistantTab(lambda app=app: app.state.assistant)
            widget.setWindowTitle("TorrentLinker · Assistant")
            widget.resize(1080, 720)
            widget.show()
            widget.activate()
            widget.select_conversation(c["id"])
            widget.refresh_run()
            QTest.qWait(100)
            assert widget.grab().save(str(output / "assistant.png"))
            editor = AssistantEditor(
                app.state.assistant,
                task=True,
                initial={
                    **conversation,
                    "name": "Bilan quotidien" if french else "Daily review",
                    "instruction": (
                        "Actualise mes torrents. Compare les gains de Zen au Plan "
                        "et propose des ajustements."
                        if french
                        else "Refresh my torrents. Compare Zen income to the Plan "
                        "and propose adjustments."
                    ),
                    "enabled": False,
                },
            )
            editor.show()
            QTest.qWait(100)
            assert editor.grab().save(str(output / "assistant-task.png"))
            editor.close()
            widget.close()
    for translator in translators:
        application.removeTranslator(translator)
