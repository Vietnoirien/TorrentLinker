import pytest
from PySide6.QtCore import QUrl
from PySide6.QtGui import QTextDocument

from torrentlinker import documentation as docs
from torrentlinker.config import Settings
from torrentlinker.gui.documentation import DocumentationTab
from torrentlinker.gui.main_window import MainWindow
from torrentlinker.store import Store


def test_offline_guides_links_history_language_and_images(qtbot):
    tab = DocumentationTab("en")
    qtbot.addWidget(tab)
    tab.resize(900, 650)
    tab.show()
    assert "Install and configure" in tab.browser.toPlainText()
    tab._follow(QUrl("torrents.md"))
    assert "Manage torrents" in tab.browser.toPlainText()
    image = tab.browser.document().resource(
        QTextDocument.ResourceType.ImageResource,
        QUrl.fromLocalFile(str(docs.document_path("guide/images/en/zen.png"))),
    )
    assert not image.isNull()
    assert image.width() <= tab.browser.viewport().width()
    tab.browser.backward()
    assert "Install and configure" in tab.browser.toPlainText()
    tab.language.setCurrentIndex(tab.language.findData("fr"))
    assert "Installer" in tab.browser.toPlainText()
    tab.filter.setText("torrents")
    torrent_guide = next(
        tab.chapters.item(i)
        for i in range(tab.chapters.count())
        if tab.chapters.item(i).text() == "Gérer les torrents"
    )
    assert not torrent_guide.isHidden()
    assert tab.chapters.item(0).isHidden()


def test_documentation_navigation_without_connections(qtbot, tmp_path):
    window = MainWindow(Settings(), tmp_path / "settings.json", Store(tmp_path / "store.db"))
    qtbot.addWidget(window)
    window.documentation_button.click()
    guide = window.documentation_tab
    assert window.tabs.currentWidget() is guide
    assert window.documentation_button.isChecked()
    assert not window.reader_button.isChecked()
    assert window.reading_room is None
    window.tabs.setCurrentIndex(1)
    assert not window.documentation_button.isChecked()
    window.documentation_button.click()
    assert window.documentation_tab is guide
    window._lock_reading_room()
    assert window.tabs.currentWidget() is guide


@pytest.mark.parametrize("name", ["../pyproject.toml", "research/secrets.md", "/etc/passwd"])
def test_documentation_rejects_non_public_paths(name):
    with pytest.raises(ValueError):
        docs.document_path(name)


def test_installed_documentation_lookup(monkeypatch, tmp_path):
    guide = tmp_path / "share/torrentlinker/docs/guide/en/getting-started.md"
    guide.parent.mkdir(parents=True)
    guide.write_text("# Installed guide")
    monkeypatch.setattr(docs.sys, "_MEIPASS", tmp_path / "missing", raising=False)
    monkeypatch.setattr(docs.sys, "prefix", str(tmp_path))
    assert docs.document_path("guide/en/getting-started.md") == guide


def test_idle_guide_does_not_reload_or_flash_wait_cursor_after_resizing(qtbot, monkeypatch):
    from PySide6.QtWidgets import QApplication

    from torrentlinker.gui.documentation import GuideBrowser

    loads = []
    original = GuideBrowser.loadResource

    def observe(self, kind, url):
        if kind == QTextDocument.ResourceType.MarkdownResource:
            cursor = QApplication.overrideCursor()
            loads.append(cursor.shape() if cursor else None)
        return original(self, kind, url)

    monkeypatch.setattr(GuideBrowser, "loadResource", observe)
    tab = DocumentationTab("en")
    qtbot.addWidget(tab)
    tab.resize(1070, 735)
    tab.show()
    tab.open_guide("guide/en/web-docker.md")
    qtbot.wait(700)
    loads.clear()
    qtbot.wait(800)
    assert not loads, f"Idle guide reloads and wait cursors: {loads}"
    tab.browser.verticalScrollBar().setValue(300)
    tab.resize(760, 620)
    qtbot.wait(700)
    loads.clear()
    qtbot.wait(800)
    assert not loads, f"Resized guide keeps reloading: {loads}"
    assert tab.browser.verticalScrollBar().value() > 0
