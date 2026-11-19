"""Catalogue controls through the owner API and the desktop bundled view."""

import httpx
from fastapi.testclient import TestClient

from tests.test_catalogue_sync import native_indexer
from tests.test_web_jobs import finished, login
from tests.test_web_plan_execution import prepared
from torrentlinker.web.app import create_app


def test_category_fetch_only_updates_selected_root_and_exposes_cards(tmp_path):
    config, setup, _, _ = prepared(tmp_path)
    roots = []

    def listing(request):
        query = dict(request.url.params)
        if "category" in query:
            roots.append(int(query["category"]))
        return httpx.Response(
            200,
            json={
                "data": [],
                "meta": {"page": 1, "perPage": 100, "total": 0, "totalPages": 1, "categories": []},
            },
        )

    setup._indexer = native_indexer(listing)
    app = create_app(
        config, password="test-password-long", service_override=setup, monitor_verifications=False
    )
    with TestClient(app) as browser:
        login(browser)
        cards = browser.get("/api/zen/catalogue").json()["cards"]
        assert next(c for c in cards if c["root"] == 2)["ours"] == 3
        assert not any(c["root"] == 8 for c in cards)
        submitted = browser.post("/api/jobs", json={"kind": "catalogue", "catalogue_root": 3})
        assert submitted.status_code == 202
        result = finished(browser, submitted.json()["id"])
        assert result["status"] == "completed", result
        assert roots and set(roots) == {3}
        cards = result["result"]["cards"]
        assert next(c for c in cards if c["root"] == 3)["state"] == "done"
        for root in (8, 999):
            invalid = browser.post("/api/jobs", json={"kind": "catalogue", "catalogue_root": root})
            assert invalid.status_code in (400, 422)


def test_desktop_cards_fetch_pause_language_and_resize(qtbot):
    from tests.test_community_interfaces import js, wait_js
    from torrentlinker.gui.zen_view import CatalogueBox, CategoryCard

    view = CatalogueBox()
    qtbot.addWidget(view)
    view.language = "en"
    view.resize(1100, 720)
    view.set_cards([CategoryCard(1, "Films & Vidéos", 3, 10, "paused")])
    view.set_state(False, True)
    view.show()
    wait_js(qtbot, view, "document.querySelector('[data-root=\"1\"]')!==null")
    assert js(qtbot, view, "document.body.textContent.includes('7 missing')")
    with qtbot.waitSignal(view.category_requested) as received:
        js(qtbot, view, "document.querySelector('[data-root=\"1\"] button').click()")
    assert received.args == [1]
    with qtbot.waitSignal(view.start_requested):
        js(qtbot, view, "document.querySelector('#catalogue-fetch').click()")
    view.set_state(True, False)
    wait_js(qtbot, view, "document.querySelector('[data-root=\"1\"] button').disabled")
    with qtbot.waitSignal(view.pause_requested):
        js(qtbot, view, "document.querySelector('#catalogue-pause').click()")
    view.language = "fr"
    view.refresh()
    view.resize(390, 700)
    wait_js(qtbot, view, "document.documentElement.lang==='fr'")
    assert js(qtbot, view, "document.documentElement.scrollWidth<=innerWidth")
    assert js(qtbot, view, "document.body.textContent.includes('manquants')")
