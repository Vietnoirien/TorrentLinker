"""Opt-in RSS acceptance with the real model and isolated source/client fixtures."""

import os

import pytest

from tests import test_assistant_live
from tests.test_feeds import Source, release
from torrentlinker.feeds import FeedService

controlled = test_assistant_live.controlled
pytestmark = pytest.mark.skipif(
    not os.getenv("TL_LIVE_MODEL_URL"), reason="explicit local model endpoint required"
)


def test_local_model_creates_edits_and_recovers_category_subscriptions(controlled):
    browser, provider, clients, _ = controlled
    source = Source()
    source.rows = [release(title="RSS acceptance fixture")]
    control = browser.app.state.agent_service.feed_control
    control.feeds.indexer = lambda: source
    thread = test_assistant_live.conversation(browser, provider, "execute", ["queue"], max_calls=24)
    result = test_assistant_live.run(
        browser,
        thread,
        "Crée trois abonnements RSS pour le client default : 'Films à découvrir' pour les "
        "films, 'Bibliothèque EPUB' pour les livres et 'Atelier 3D' pour tous les modèles 3D. "
        "Prévisualise avant chaque enregistrement. Consultation uniquement, toutes les 30 "
        "minutes, sans filtre de titre. Pour les films, taille maximum 8 000 000 000 octets, "
        "préférence 1080p puis 720p et HEVC puis H264, et préfère plus de seeders, "
        "puis la taille plus petite pour départager. "
        "Pour les livres préfère EPUB. Ne change pas les dossiers et ne télécharge rien. "
        "Vérifie les abonnements réellement enregistrés avant de répondre.",
        "rss-create-categories",
    )
    assert result["status"] == "completed", result
    rows = browser.get("/api/feeds").json()
    assert len(rows) == 3, rows
    by_name = {r["name"]: r for r in rows}
    expected = {"Films à découvrir": 2030, "Bibliothèque EPUB": 7020, "Atelier 3D": 8010}
    for name, category in expected.items():
        row = by_name[name]
        assert row["categories"] == [category], row
        assert row["mode"] == "review_only" and row["client_id"] == "default"
        assert row["interval_minutes"] == 30 and not row["query"]
    film = by_name["Films à découvrir"]
    prefs = film["preferences"]
    assert prefs["max_size"] == 8_000_000_000
    assert prefs["prefer_small"] is True
    assert prefs["preferred"]["quality"] == ["1080p", "720p"]
    assert [v.lower() for v in prefs["preferred"]["codec"]] == ["hevc", "h264"]
    assert prefs["priorities"].index("seeders") < prefs["priorities"].index("size")
    assert [
        v.lower() for v in by_name["Bibliothèque EPUB"]["preferences"]["preferred"]["format"]
    ] == ["epub"]
    updated = test_assistant_live.run(
        browser,
        thread,
        "Mets Atelier 3D en pause et passe Films à découvrir à 60 minutes. Conserve tous "
        "les critères et les trois abonnements, sans doublon. Vérifie le résultat.",
        "rss-edit-subscriptions",
    )
    assert updated["status"] == "completed", updated
    restored = FeedService(control.feeds.path, lambda: source)
    rows = browser.get("/api/feeds").json()
    assert len(rows) == 3
    by_name = {r["name"]: r for r in rows}
    assert by_name["Atelier 3D"]["paused"] is True
    assert by_name["Films à découvrir"]["interval_minutes"] == 60
    assert by_name["Films à découvrir"]["preferences"] == prefs
    assert len(restored.subscriptions()) == 3
    assert browser.get("/api/queue").json() == []
    assert all(not c.paused for c in clients.values())
    test_assistant_live.record(
        "rss-subscriptions-verified", {"status": "passed", "subscriptions": rows}
    )
