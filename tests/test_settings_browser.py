"""Shared owner Settings drafts and secret handling in an actual browser."""

import os
import socket
import threading
import time
from dataclasses import replace

import pytest

from tests.test_web_plan_execution import prepared
from torrentlinker.web.app import create_app

pytestmark = pytest.mark.skipif(os.getenv("TL_WEB_BROWSER") != "1", reason="opt-in browser test")


@pytest.mark.parametrize("configured", [True, False])
def test_connection_drafts_survive_section_changes_and_failed_save(
    tmp_path, configured, monkeypatch
):
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    config, setup, client, _ = prepared(tmp_path)
    monkeypatch.setattr(client, "check", lambda: "fixture-client", raising=False)
    setup.configured = configured
    if not configured:
        setup.marker.unlink(missing_ok=True)
    setup.secrets.update({"tmdb-api-key": "private-existing-key"})
    app = create_app(
        config, password="test-password-long", service_override=setup, monitor_verifications=False
    )
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
        worker = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        worker.start()
        try:
            for _ in range(100):
                if server.started:
                    break
                time.sleep(0.02)
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                page = browser.new_page(viewport={"width": 1280, "height": 900}, locale="en-US")
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(f"http://127.0.0.1:{listener.getsockname()[1]}/")
                assert not errors
                page.locator("#login-password").fill("test-password-long")
                page.locator("#login-form button").click()
                page.locator("[data-view=setup]").first.click()
                panel = page.frame_locator("#settings-frame")
                name = panel.get_by_label("Client name", exact=True)
                expect(name).to_be_visible(timeout=5000)
                name.fill("Studio draft")
                panel.get_by_role("button", name="Clients", exact=True).click()
                panel.get_by_role("button", name="Connections", exact=True).click()
                expect(name).to_have_value("Studio draft")
                secret = panel.get_by_label("TMDb API key", exact=True)
                expect(secret).to_have_value("")
                expect(secret).to_have_attribute("placeholder", "Saved; leave blank to keep")
                secret.fill("replacement-key")
                page.route(
                    "**/api/settings/connections",
                    lambda route: route.fulfill(
                        status=409,
                        content_type="application/json",
                        body='{"detail":"Wait for active jobs before changing settings."}',
                    ),
                )
                panel.get_by_role("button", name="Save", exact=True).click()
                expect(panel.locator("#settings-error")).to_contain_text("Wait for active jobs")
                expect(name).to_have_value("Studio draft")
                expect(secret).to_have_value("replacement-key")
                page.unroute("**/api/settings/connections")
                panel.get_by_role("button", name="Save", exact=True).click()
                expect(panel.locator("#settings-status")).to_contain_text("Settings saved")
                expect(secret).to_have_value("")
                assert setup.configured
                if not configured:
                    assert setup.marker.read_text() == "connected"
                page.reload()
                page.locator("[data-view=setup]").first.click()
                expect(name).to_have_value("Studio draft")
                assert "private-existing-key" not in panel.locator("body").inner_text()
                panel.get_by_role("button", name="Clients", exact=True).click()
                panel.get_by_label("New client name", exact=True).fill("Seedbox")
                panel.get_by_role("button", name="Add client", exact=True).click()
                card = panel.locator(".client-card").filter(has_text="Seedbox")
                expect(card).to_be_visible()
                card.get_by_role("button", name="Make default", exact=True).click()
                expect(card).to_contain_text("Default")
                if configured:
                    second = next(
                        p.id for p in setup.settings.client_profiles if p.name == "Seedbox"
                    )
                    panel.get_by_role("button", name="Connections", exact=True).click()
                    stale_save = panel.get_by_role(
                        "button", name="Save", exact=True
                    ).element_handle()
                    pending = []

                    def delay_client(route):
                        pending.append((route, route.fetch()))

                    pattern = f"**/api/settings?client_id={second}"
                    page.route(pattern, delay_client)
                    page.locator("#target-client").select_option(second)
                    expect(panel.locator("#settings-body")).to_have_text("Loading Settings…")
                    for _ in range(100):
                        if pending:
                            break
                        page.wait_for_timeout(20)
                    assert pending
                    stale_save.evaluate("button => button.click()")
                    expect(panel.locator("#settings-error")).to_contain_text(
                        "Wait for the selected client"
                    )
                    assert setup.settings.profile(second).name == "Seedbox"
                    pending[0][0].fulfill(response=pending[0][1])
                    expect(panel.get_by_label("Client name", exact=True)).to_have_value("Seedbox")
                    page.unroute(pattern, delay_client)
                    page.locator("#target-client").select_option("default")
                    expect(panel.get_by_label("Client name", exact=True)).to_have_value(
                        "Studio draft"
                    )
                    panel.get_by_role("button", name="Clients", exact=True).click()
                page.once("dialog", lambda dialog: dialog.accept())
                card.get_by_role("button", name="Remove client", exact=True).click()
                expect(panel.locator(".client-card")).to_have_count(1)
                panel.get_by_role("button", name="General", exact=True).click()
                panel.get_by_label("Theme", exact=True).select_option("light")
                panel.get_by_label("Media interface", exact=True).select_option("focus")
                panel.get_by_role("button", name="Save", exact=True).click()
                expect(panel.locator("#settings-status")).to_contain_text("Settings saved")
                expect(panel.locator("html")).to_have_attribute("data-theme", "light")
                panel.get_by_role("button", name="Search & Matching", exact=True).click()
                panel.get_by_label("Ignored Files", exact=True).fill("*.nfo\n*.txt")
                panel.get_by_role("button", name="Save", exact=True).click()
                expect(panel.locator("#settings-status")).to_contain_text("Settings saved")
                panel.get_by_role("button", name="Zen", exact=True).click()
                panel.get_by_label("Seed hours per day", exact=True).fill("12")
                panel.get_by_role("button", name="Save", exact=True).click()
                expect(panel.locator("#settings-status")).to_contain_text("Settings saved")
                page.reload()
                page.locator("[data-view=setup]").first.click()
                panel.get_by_role("button", name="Zen", exact=True).click()
                expect(panel.get_by_label("Seed hours per day", exact=True)).to_have_value("12")
                # Changes made elsewhere refresh clean sections; edited drafts survive reopening.
                page.locator("[data-view=torrents]").click()
                setup.settings.zen = replace(setup.settings.zen, seed_hours=13)
                setup.save()
                page.locator("[data-view=setup]").first.click()
                panel.get_by_role("button", name="Zen", exact=True).click()
                expect(panel.get_by_label("Seed hours per day", exact=True)).to_have_value("13")
                panel.get_by_label("Seed hours per day", exact=True).fill("9")
                page.locator("[data-view=torrents]").click()
                setup.settings.zen = replace(setup.settings.zen, seed_hours=18)
                setup.save()
                page.locator("[data-view=setup]").first.click()
                panel.get_by_role("button", name="Zen", exact=True).click()
                expect(panel.get_by_label("Seed hours per day", exact=True)).to_have_value("9")
                for section in ("Library Folders", "Download Folders", "Client Paths"):
                    panel.locator("#settings-navigation").get_by_role(
                        "button", name=section, exact=True
                    ).click()
                    expect(panel.get_by_role("button", name="Browse…", exact=True)).to_be_visible()
                panel.locator("#settings-navigation").get_by_role(
                    "button", name="Assistant", exact=True
                ).click()
                expect(
                    panel.get_by_role("button", name="Add connection", exact=True)
                ).to_be_visible()
                panel.locator("#settings-navigation").get_by_role(
                    "button", name="Companion", exact=True
                ).click()
                expect(
                    panel.get_by_role("button", name="Save extension…", exact=True)
                ).to_be_visible()
                panel.locator("#settings-navigation").get_by_role(
                    "button", name="Agent access", exact=True
                ).click()
                expect(panel.locator("#agents-endpoint")).to_contain_text("mcp/")
                panel.get_by_role("button", name="New connection", exact=True).click()
                panel.locator("#agent-name").fill("Fixture agent")
                panel.get_by_role("button", name="Create connection", exact=True).click()
                expect(panel.locator("#agent-token")).not_to_have_value("")
                panel.locator("#settings-navigation").get_by_role(
                    "button", name="General", exact=True
                ).click()
                panel.locator("#settings-navigation").get_by_role(
                    "button", name="Agent access", exact=True
                ).click()
                expect(panel.locator("#agent-token-box")).to_be_hidden()
                expect(panel.locator("#agent-connections")).to_contain_text("Fixture agent")
                assert not errors
                browser.close()
        finally:
            server.should_exit = True
            worker.join(10)
