"""Members 2 (#129): the sign-in card and Paramètres → Utilisateurs in an actual browser."""

import os
import socket
import threading
import time

import pytest

from tests.shell_support import shell_navigate
from tests.test_web_plan_execution import prepared
from torrentlinker.web.app import create_app

pytestmark = pytest.mark.skipif(os.getenv("TL_WEB_BROWSER") != "1", reason="opt-in browser test")


def test_the_owner_creates_edits_and_disables_a_member_who_signs_in_by_name(tmp_path):
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    config, setup, _, _ = prepared(tmp_path)
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
                expect(page.get_by_label("Sign-in name")).to_be_visible()
                page.get_by_role("button", name="I am the owner").click()
                expect(page.get_by_label("Sign-in name")).to_be_hidden()
                page.get_by_label("Server password").fill("wrong-password-long")
                page.locator("#login-form button.primary").click()
                expect(page.locator("#login-error")).to_have_text("Incorrect password.")
                page.get_by_label("Server password").fill("test-password-long")
                page.locator("#login-form button.primary").click()
                shell_navigate(page, "setup")
                panel = page.frame_locator("#settings-frame")
                panel.get_by_role("button", name="Users", exact=True).click()
                expect(panel.get_by_text("every right, cannot be restricted")).to_be_visible()

                panel.get_by_role("button", name="Create an account with a password").click()
                dialog = panel.locator("dialog[open]")
                dialog.get_by_label("Display name").fill("Léa")
                dialog.get_by_label("Preset").select_option(label="Family")
                dialog.get_by_label("Sign-in name").fill("lea")
                dialog.get_by_label("Password").fill("lea-password-long")
                dialog.get_by_role("button", name="Create the account").click()
                expect(panel.get_by_text("Léa can now sign in")).to_be_visible()
                card = panel.locator(".client-card", has=panel.get_by_role("heading", name="Léa"))
                expect(card.get_by_text("Active · Family")).to_be_visible()
                caps = card.locator(".member-cap input[type=number]")
                expect(caps.nth(0)).to_have_value("5")
                expect(caps.nth(1)).to_have_value("100")

                # Without Request, the caps go; the Owner-only rights stay locked.
                card.get_by_label("Request films").uncheck()
                expect(card.locator(".member-cap input[type=checkbox]").first).to_be_disabled()
                expect(card.get_by_label("Upload")).to_be_disabled()
                card.get_by_role("button", name="Save", exact=True).click()
                expect(panel.get_by_text("Member saved")).to_be_visible()
                expect(card.get_by_text("Active · Custom")).to_be_visible()
                lea = app.state.accounts.members()[0]
                assert "request" not in lea["permissions"]
                assert lea["caps"]["requests_per_week"] is None

                # A Member signs in by name; disabling ends their session at once.
                other = browser.new_context(locale="fr-FR").new_page()
                other.goto(page.url.split("#")[0])
                other.get_by_label("Identifiant").fill("lea")
                other.get_by_label("Mot de passe", exact=True).fill("wrong-password-long")
                other.locator("#login-form button.primary").click()
                expect(other.locator("#login-error")).to_have_text(
                    "Identifiant ou mot de passe incorrect."
                )
                other.get_by_label("Mot de passe", exact=True).fill("lea-password-long")
                with other.expect_response("**/api/login") as signed:
                    other.locator("#login-form button.primary").click()
                assert signed.value.ok
                assert other.evaluate("fetch('api/shell').then(r => r.status)") == 200

                page.once("dialog", lambda prompt: prompt.accept())
                card.get_by_role("button", name="Disable").click()
                expect(card.get_by_text("Disabled · Custom")).to_be_visible()
                assert other.evaluate("fetch('api/shell').then(r => r.status)") == 401
                page.once("dialog", lambda prompt: prompt.accept())
                card.get_by_role("button", name="Delete").click()
                expect(panel.get_by_role("heading", name="Léa")).to_have_count(0)
                assert app.state.accounts.members() == []
                assert not errors
                browser.close()
        finally:
            server.should_exit = True
            worker.join(timeout=5)


def test_an_invitation_link_with_its_qr_code_lets_the_person_join(tmp_path):
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    config, setup, _, _ = prepared(tmp_path)
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
                page.get_by_role("button", name="I am the owner").click()
                page.get_by_label("Server password").fill("test-password-long")
                page.locator("#login-form button.primary").click()
                shell_navigate(page, "setup")
                panel = page.frame_locator("#settings-frame")
                panel.get_by_role("button", name="Users", exact=True).click()
                panel.get_by_role("button", name="Invite someone").click()
                dialog = panel.locator("dialog[open]")
                dialog.get_by_label("Display name").fill("Karim")
                dialog.get_by_label("Preset").select_option(label="Family")
                dialog.get_by_label("Message (optional)").fill("Voici les films")
                dialog.get_by_label("Link valid for").select_option(label="7 days")
                dialog.get_by_role("button", name="Create the link").click()
                expect(dialog.get_by_role("heading", name="Invitation for Karim")).to_be_visible()
                expect(dialog.get_by_role("img", name="QR code of the link")).to_be_visible()
                url = dialog.get_by_label("Invitation link").input_value()
                assert "/join#" in url
                dialog.get_by_role("button", name="Close").click()
                card = panel.locator(".client-card", has=panel.get_by_role("heading", name="Karim"))
                expect(card.get_by_text("Invitation sent, expires in 7 d · Family")).to_be_visible()
                card.get_by_role("button", name="Show the link").click()
                expect(panel.locator("dialog[open]").get_by_label("Invitation link")).to_have_value(
                    url
                )
                panel.locator("dialog[open]").get_by_role("button", name="Close").click()

                other = browser.new_context(locale="fr-FR").new_page()
                other.on("pageerror", lambda error: errors.append(str(error)))
                other.goto(url)
                expect(
                    other.get_by_role("heading", name="Le propriétaire vous invite")
                ).to_be_visible()
                expect(other.get_by_text("« Voici les films »")).to_be_visible()
                expect(
                    other.get_by_text("Demander des films, jusqu’à 5 par semaine")
                ).to_be_visible()
                join = other.get_by_role("button", name="Rejoindre")
                other.get_by_label("Identifiant de connexion").fill("karim")
                other.get_by_label("Mot de passe", exact=True).fill("karim-password")
                other.get_by_label("Confirmer le mot de passe").fill("karim-passwor")
                expect(other.get_by_text("Les deux mots de passe diffèrent.")).to_be_visible()
                expect(join).to_be_disabled()
                other.get_by_label("Confirmer le mot de passe").fill("karim-password")
                join.click()
                expect(other.get_by_role("heading", name="Bienvenue, Karim")).to_be_visible()
                assert other.evaluate("fetch('api/shell').then(r => r.status)") == 200

                other.goto("about:blank")
                other.goto(url)
                expect(other.get_by_role("heading", name="Ce lien a déjà servi")).to_be_visible()
                assert app.state.accounts.verify("karim", "karim-password")
                assert not errors
                browser.close()
        finally:
            server.should_exit = True
            worker.join(timeout=5)
