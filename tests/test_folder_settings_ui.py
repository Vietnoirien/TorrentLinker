"""Visible folder verification and category inheritance on desktop and WebUI."""

import os
import socket
import threading
import time
from pathlib import Path

import pytest

from tests.test_folder_probe import ProbeClient
from torrentlinker.config import Settings
from torrentlinker.domain import PathMapping
from torrentlinker.downloads import DownloadFolders, IndexerCategory


def categories():
    return {
        2000: IndexerCategory("Films & Videos"),
        2030: IndexerCategory("Animation", 2000),
        2031: IndexerCategory("Series", 2030),
        3000: IndexerCategory("Audio"),
        3010: IndexerCategory("Audio", 3000),
        7000: IndexerCategory("Ebook"),
    }


def test_desktop_checks_empty_mapping_and_shows_category_branches(qtbot, tmp_path, monkeypatch):
    from torrentlinker.gui.settings_dialog import COL_CHECK, SettingsDialog

    client = ProbeClient(tmp_path)
    client.default_save_path = lambda: "/downloads"
    monkeypatch.setattr("torrentlinker.gui.settings_dialog.connect", lambda *a, **kw: client)
    settings = Settings()
    settings.path_mappings = [PathMapping(str(tmp_path), "/downloads")]
    settings.indexer_categories = categories()
    dialog = SettingsDialog(settings)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.check_button.click()
    qtbot.waitUntil(lambda: "verified" in dialog.mappings.item(0, COL_CHECK).text(), timeout=10000)
    assert len(client.added) == 1 and len(client.removed) == 1
    assert list(tmp_path.iterdir()) == []
    assert dialog.download_table.item(0, 0).font().bold()
    assert "└─ Animation" in dialog.download_table.item(1, 0).text()
    assert "Films & Videos › Animation › Series" in dialog.download_table.item(2, 0).toolTip()
    if output := os.getenv("TL_WEB_SCREENSHOTS"):
        from PySide6.QtWidgets import QApplication, QListWidget

        from torrentlinker.gui.theme import apply_theme

        app = QApplication.instance()
        apply_theme(app, "light")
        Path(output).mkdir(parents=True, exist_ok=True)
        dialog.resize(1200, 1000)
        navigation = dialog.findChild(QListWidget, "navigation")
        navigation.setCurrentRow(3)
        app.processEvents()
        dialog.grab().save(str(Path(output) / "folder-settings-desktop.png"))
        navigation.setCurrentRow(4)
        app.processEvents()
        dialog.grab().save(str(Path(output) / "folder-check-desktop.png"))


@pytest.mark.skipif(os.getenv("TL_WEB_BROWSER") != "1", reason="opt-in browser test")
def test_browser_category_tree_and_empty_folder_save(tmp_path):
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    from torrentlinker.web.app import create_app
    from torrentlinker.web.security import ServerSecrets
    from torrentlinker.web.setup import Setup

    config, root = tmp_path / "config", tmp_path / "media"
    config.mkdir()
    root.mkdir()
    client = ProbeClient(root)
    setup = Setup(config, (root,), ServerSecrets(config), lambda *a, **kw: client)
    setup.configured = True
    setup.settings.indexer_categories = categories()
    setup.settings.path_mappings = [PathMapping(str(root), "/downloads")]
    setup.settings.download_folders = DownloadFolders({2000: str(root)})
    setup.save()
    app = create_app(
        config, password="test-password-long", service_override=setup, monitor_verifications=False
    )
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.02)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1400, "height": 1050}, locale="en-US")
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"http://127.0.0.1:{port}/")
            page.locator("#login-password").fill("test-password-long")
            page.locator("#login-form button").click()
            page.locator("[data-view=setup]").first.click()
            page.locator(".steps [data-step=storage]").click()
            picker = page.locator("#library-download-form .category-picker")
            picker.locator("summary").click()
            expect(picker.get_by_role("button", name="Audio › Audio", exact=True)).to_be_visible()
            picker.get_by_role(
                "button", name="Films & Videos › Animation › Series", exact=True
            ).click()
            expect(picker.locator("summary")).to_have_text("Films & Videos › Animation › Series")
            expect(page.locator("#library-download-feedback")).to_contain_text(str(root))
            page.locator("#library-download-path").fill(str(root))
            page.locator("#library-download-form .primary").click()
            expect(page.locator("#library-download-feedback")).to_contain_text(
                "verified and saved", timeout=15000
            )
            assert len(client.added) == 1 and len(client.removed) == 1
            assert list(root.iterdir()) == []
            picker.locator("summary").click()
            if output := os.getenv("TL_WEB_SCREENSHOTS"):
                Path(output).mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(Path(output) / "folder-settings-web.png"), full_page=True)
                picker.locator(".category-branches").screenshot(
                    path=str(Path(output) / "category-menu-web.png")
                )
            picker.press("Escape")
            expect(picker).not_to_have_attribute("open", "")
            assert not errors, errors
            browser.close()
    finally:
        server.should_exit = True
        thread.join(5)
