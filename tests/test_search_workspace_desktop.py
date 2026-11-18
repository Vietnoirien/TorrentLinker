"""The native host renders and operates the same Search panel as Web."""

import os
import subprocess
import sys

from tests.test_web_search import fake_net


def test_desktop_shared_search_navigation(qtbot, tmp_path, monkeypatch, request):
    if not os.getenv("TL_SEARCH_NATIVE_CHILD"):
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", request.node.nodeid],
            env={
                **os.environ,
                "TL_SEARCH_NATIVE_CHILD": "1",
                "QTWEBENGINE_CHROMIUM_FLAGS": "--disable-gpu",
                "QT_QUICK_BACKEND": "software",
            },
            capture_output=True,
            text=True,
            timeout=90,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return
    from types import SimpleNamespace

    from PySide6.QtCore import QSettings

    from tests.test_community_interfaces import js, wait_js
    from torrentlinker.config import Settings
    from torrentlinker.credentials import set_secret
    from torrentlinker.gui import search_workspace
    from torrentlinker.gui.search_workspace import SearchTab

    monkeypatch.setattr(
        search_workspace,
        "QSettings",
        lambda: QSettings(str(tmp_path / "ui.ini"), QSettings.Format.IniFormat),
    )
    from torrentlinker.store import Store

    fake_net(monkeypatch, [])
    settings = Settings()
    settings.indexer.url = "https://c411.org/api"
    from PySide6.QtWidgets import QFileDialog

    from torrentlinker.downloads import IndexerCategory

    settings.indexer_categories = {
        2000: IndexerCategory("Films"),
        2030: IndexerCategory("Film", 2000),
    }
    target = tmp_path / "films"
    target.mkdir()
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a: str(target))
    owner = SimpleNamespace(
        settings=settings,
        settings_path=tmp_path / "settings.json",
        store=Store(tmp_path / "store.sqlite"),
    )
    tab = SearchTab(owner)
    qtbot.addWidget(tab)
    # Fake public Indexer network only; all panel/service code remains real.
    set_secret("indexer-api-key", "private-key")
    tab.resize(1280, 900)
    tab.show()
    board = tab.board
    wait_js(qtbot, board, "document.querySelector('#search-pills').textContent.includes('Films')")
    wait_js(qtbot, board, "document.querySelectorAll('.sr-row').length===2")
    js(
        qtbot,
        board,
        "document.querySelector('#search-query').value='film';"
        "document.querySelector('#search-form .primary').click()",
    )
    try:
        wait_js(
            qtbot,
            board,
            "document.querySelectorAll('.sr-row').length===2 && "
            "!document.querySelector('#search-status').textContent.includes('Searching')",
        )
    except Exception:
        print(js(qtbot, board, "document.body.innerText"))
        print(tab.board.jobs.list())
        raise
    js(
        qtbot,
        board,
        "document.querySelector('.sr-row input').click();"
        "document.querySelector('#queue-search').click()",
    )
    wait_js(qtbot, board, "document.querySelector('#folder-dialog').open")
    js(qtbot, board, "document.querySelector('#folder-dialog .path-row button').click()")
    wait_js(qtbot, board, "document.querySelector('#folder-dialog input').value.length>0")
    js(qtbot, board, "document.querySelector('#folder-dialog .primary').click()")
    wait_js(qtbot, board, "!document.querySelector('#folder-dialog').open")
    wait_js(
        qtbot, board, "document.querySelector('#search-queue-link').textContent.includes('(1)')"
    )
    assert str(target) in owner.settings.download_folders.by_category.values()
    js(qtbot, board, "document.querySelectorAll('.dl-button')[1].click()")
    wait_js(
        qtbot, board, "document.querySelector('#search-queue-link').textContent.includes('(2)')"
    )
    assert not js(qtbot, board, "document.querySelector('#folder-dialog').open")
    js(qtbot, board, "document.querySelector('#search-queue-link').click()")
    wait_js(qtbot, board, "!document.querySelector('#queue').hidden")
    js(qtbot, board, "document.querySelector('#back-results').click()")
    wait_js(qtbot, board, "!document.querySelector('#results').hidden")
    assert js(qtbot, board, "document.querySelector('#search-query').value") == "film"
    assert js(qtbot, board, "document.querySelectorAll('.sr-row').length") == 2
    from tests.test_web_search import HASHES
    from torrentlinker.domain import Torrent
    from torrentlinker.seeding import Seeding, SeedingRow
    from torrentlinker.zen import ZenDay

    tab.set_seeding(
        Seeding([SeedingRow(Torrent(HASHES[1], "Title 2", tmp_path), None)], ZenDay(), [])
    )
    wait_js(qtbot, board, "document.querySelectorAll('.mark-client').length===1")
    if folder := os.getenv("TL_SEARCH_SCREENSHOTS"):
        from pathlib import Path

        Path(folder).mkdir(parents=True, exist_ok=True)
        assert tab.grab().save(str(Path(folder) / "search-desktop.png"))
    tab.resize(800, 560)
    wait_js(qtbot, board, "window.innerWidth <= 800")
    assert js(qtbot, board, "document.documentElement.scrollWidth <= window.innerWidth")
    for selector in ("#search-form .primary", "#search-queue-link"):
        js(qtbot, board, f"document.querySelector('{selector}').scrollIntoView()")
        assert js(
            qtbot,
            board,
            f"""(() => {{
            const r = document.querySelector('{selector}').getBoundingClientRect();
            return r.left >= 0 && r.right <= innerWidth && r.top >= 0 && r.bottom <= innerHeight;
        }})()""",
        )
    js(
        qtbot,
        board,
        "document.querySelector('#search-density-compact').click();document.querySelector('#search-posters').click()",
    )
    qtbot.waitUntil(lambda: search_workspace.QSettings().value("search/density") == "compact")
    tab.stop()
    board.close()
    tab.close()
    reopened = SearchTab(owner)
    qtbot.addWidget(reopened)
    reopened.show()
    wait_js(
        qtbot,
        reopened.board,
        "document.querySelector('#search-density-compact')?.getAttribute('aria-pressed')==='true'",
    )
    assert (
        js(
            qtbot,
            reopened.board,
            "document.querySelector('#search-posters').getAttribute('aria-pressed')",
        )
        == "false"
    )
    reopened.stop()
    reopened.board.close()
