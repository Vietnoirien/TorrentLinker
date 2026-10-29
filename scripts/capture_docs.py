"""Capture real Qt widgets in French or English with offline example data.

Run from the repository root: QT_QPA_PLATFORM=offscreen .venv/bin/python scripts/capture_docs.py
Add --language en for English screenshots. French is the default.
Requires the development dependencies. No torrents are downloaded or sent to a client.
"""

import argparse
import socket
import sys
import time
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import httpx
from PySide6.QtCore import QPoint, QSettings, QTimer
from PySide6.QtGui import QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox, QSplitter

from torrentlinker import i18n
from torrentlinker.agent.access import Grant
from torrentlinker.agent.desktop import DesktopSetup
from torrentlinker.config import Settings
from torrentlinker.domain import (
    ContentKind,
    ItemState,
    LibraryFolder,
    LocalItem,
    PathMapping,
    Torrent,
)
from torrentlinker.download_queue import enqueue
from torrentlinker.downloads import IndexerCategory
from torrentlinker.gui.agent_access import AgentAccess
from torrentlinker.gui.main_window import MainWindow
from torrentlinker.gui.settings_dialog import SettingsDialog
from torrentlinker.gui.theme import ThemeFollower, apply_theme
from torrentlinker.indexer import Candidate, Indexer
from torrentlinker.library import LibraryEntry
from torrentlinker.matching import FileComparison, Match
from torrentlinker.review import CheckedCandidate
from torrentlinker.seeding import Seeding, SeedingRow, zen_torrent
from torrentlinker.store import Store
from torrentlinker.torrent_meta import TorrentMeta
from torrentlinker.web.app import create_app
from torrentlinker.web.uploads import UploadForm
from torrentlinker.zen import estimate

OUTPUT = Path(__file__).resolve().parents[1] / "docs/guide/images"
TREE = {
    "data": [
        {
            "id": 1,
            "name": "Films & Vidéos",
            "slug": "films-videos",
            "subcategories": [{"id": 6, "name": "Film", "slug": "film"}],
        }
    ]
}
FACETS = {
    "data": [{"slug": "genre", "name": "Genre", "values": [{"id": 39, "value": "Animation"}]}]
}


def capture(widget, name, output):
    QTest.qWait(150)
    if not widget.grab().save(str(output / f"{name}.png")):
        raise RuntimeError(f"Could not save {name}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--language", choices=("fr", "en"), default="fr")
    language = parser.parse_args().language
    output = OUTPUT / "en" if language == "en" else OUTPUT
    output.mkdir(parents=True, exist_ok=True)

    def localize(french, english):
        return english if language == "en" else french

    app = QApplication(sys.argv)
    app.setApplicationName("TorrentLinker")
    apply_theme(app, "dark")
    translators = i18n.install(app, language)  # noqa: F841
    with ExitStack() as stack, TemporaryDirectory(prefix="tl-docs-") as temp:
        # Guard against accidental real credentials or network calls, including background tasks.
        stack.enter_context(patch("keyring.get_password", return_value=None))
        stack.enter_context(
            patch("keyring.set_password", side_effect=RuntimeError("offline capture"))
        )
        stack.enter_context(
            patch.object(socket.socket, "connect", side_effect=RuntimeError("offline capture"))
        )
        root = Path(temp)
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(root / "qt"))
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.SystemScope, str(root / "qt"))
        folders = [
            LibraryFolder(
                Path(localize("/exemple/Films", "/example/Movies")), kind=ContentKind.MOVIE
            ),
            LibraryFolder(
                Path(localize("/exemple/Modeles-3D", "/example/3D-Models")),
                kind=ContentKind.MODEL_3D,
            ),
        ]
        categories = {
            2000: IndexerCategory("Films & Vidéos"),
            2010: IndexerCategory("Animation", 2000),
            7000: IndexerCategory("Ebook"),
            7010: IndexerCategory("Livres", 7000),
        }
        settings = Settings(
            language=language, theme="dark", library_folders=folders, indexer_categories=categories
        )
        window = MainWindow(settings, root / "settings.json", Store(root / "state.db"))
        window.resize(1600, 1000)
        window.show()
        window.open_settings = lambda: None

        def welcome():
            dialog = app.activeModalWidget()
            if not isinstance(dialog, QMessageBox):
                QTimer.singleShot(25, welcome)
                return
            pixmap = window.grab()
            painter = QPainter(pixmap)
            painter.drawPixmap(
                QPoint(
                    (window.width() - dialog.width()) // 2, (window.height() - dialog.height()) // 2
                ),
                dialog.grab(),
            )
            painter.end()
            pixmap.save(str(output / "bienvenue.png"))
            dialog.accept()

        QTimer.singleShot(150, welcome)
        window.startup()
        window.setup_notice.hide()
        window.tabs.setEnabled(True)
        window.band.setEnabled(True)
        window.statusBar().showMessage(
            localize(
                "Données d’exemple pour la documentation", "Example data for the documentation"
            )
        )
        agent_setup = DesktopSetup(settings, root / "settings.json", window.store)
        agent_service = create_app(
            root / "agents",
            password="offline-documentation-only",
            service_override=agent_setup,
            monitor_verifications=False,
        ).state.agent_service
        # Temporary offline grant; discard its token and never display it in the capture.
        agent_service.access.create(
            Grant(name=localize("Mon assistant", "My assistant"), clients=["default"])
        )
        window.agent_access_widget = lambda parent: AgentAccess(
            agent_service, "http://127.0.0.1:8790/mcp/", parent
        )
        settings_dialog = SettingsDialog(settings, window)
        settings_dialog.resize(1120, 940)
        settings_dialog.show()
        capture(settings_dialog, "connexions", output)
        settings_dialog._add_mapping_row(
            PathMapping(
                localize("/exemple/Films", "/example/Movies"),
                localize("/data/Films", "/data/Movies"),
            )
        )
        settings_dialog.tabs.setCurrentIndex(4)
        capture(settings_dialog, "chemins", output)
        settings_dialog.show_agent_access()
        for _ in range(100):
            QTest.qWait(20)
            if settings_dialog.agent_access.connections.count():
                break
        capture(settings_dialog, "agent-access", output)
        settings_dialog.reject()

        names = [
            "Big.Buck.Bunny.2008.1080p.mkv",
            "Sintel.2010.1080p.mkv",
            "Tears.of.Steel.2012.1080p.mkv",
            "Elephants.Dream.2006.1080p.mkv",
        ]
        entries = [
            LibraryEntry(
                folders[0],
                LocalItem(folders[0].path / name, {name: (i + 1) * 1024**3}),
                ItemState.SEEDED if i == 0 else ItemState.ORPHAN,
            )
            for i, name in enumerate(names)
        ]
        window.library_model.set_entries(entries)
        window.library_model.set_status(
            entries[1].item.path, localize("Correspondance complète trouvée", "Full match found")
        )
        window.library_model.set_status(
            entries[2].item.path, localize("2 candidats à vérifier", "2 candidates to check")
        )
        window.tabs.setCurrentIndex(1)
        window.library_workspace.split.setSizes([260, 440])
        for col, width in enumerate((300, 265, 90, 145, 90)):
            window.library_view.setColumnWidth(col, width)
        selected = entries[1]
        relative, size = next(iter(selected.item.files.items()))
        checked = CheckedCandidate(
            Candidate(
                "Sintel.2010.1080p",
                size,
                "https://example.invalid/sintel",
                seeders=12,
                infohash="a" * 40,
            ),
            meta=TorrentMeta(relative, "a" * 40, {relative: size}, b""),
            comparison=FileComparison({relative: relative}),
            match=Match({relative: relative}),
        )
        window.review.remember(selected, [checked])
        window.review.set_entry(selected)
        window.review.details_tabs.setCurrentIndex(1)
        capture(window, "bibliotheque", output)
        window.library_workspace.sections.setCurrentIndex(1)
        capture(window, "ajouter-dossier", output)
        window.library_workspace.sections.setCurrentIndex(0)
        window.review.details_tabs.setCurrentIndex(4)
        window.library_workspace.expand_review()
        window.review.evidence.render(
            {
                "observations": [
                    {
                        "file": relative,
                        "source": "embedded-title",
                        "field": "resolution",
                        "claim": "2160p",
                        "observed": "1080p",
                        "confidence": "measured",
                    }
                ],
                "provenance": [],
            }
        )
        capture(window, "library-evidence", output)
        window.library_workspace.expand_review()

        rows = [
            SeedingRow(
                Torrent(
                    str(i) * 40,
                    name,
                    folders[0].path,
                    state="stalledUP",
                    swarm_seeders=6 + i * 4,
                    seeding_time=(10 + i * 5) * 86400,
                    size=i * 1024**3,
                ),
                0.12 + i * 0.04,
                2010,
                note=2.4 + i * 0.6,
            )
            for i, name in enumerate(names, 1)
        ]
        rows.append(
            SeedingRow(
                Torrent(
                    "f" * 40,
                    localize("Guide.de.modelisation.3D.epub", "3D.Modelling.Guide.epub"),
                    Path(localize("/exemple/Livres", "/example/Books")),
                    state="stalledUP",
                    swarm_seeders=9,
                    seeding_time=30 * 86400,
                    size=40 * 1024**2,
                ),
                0.03,
                7010,
                note=3.1,
            )
        )
        active = [replace(zen_torrent(row.torrent, None), category=row.category) for row in rows]
        day = estimate(settings.zen, active)
        rows = [
            replace(row, zen=value, note=score)
            for row, value, score in zip(rows, day.per_torrent, day.notes, strict=True)
        ]
        view = Seeding(rows, day, active, categories)
        window.zen_tab.seeding_view.show_seeding(view)
        window.zen_tab.seeding_view.table.expandAll()
        window.band.set_balance(120)
        window.band.set_seeding(view)
        window.band.set_catalogue(localize("données d’exemple", "example data"))
        window.tabs.setCurrentIndex(0)
        capture(window, "zen", output)
        window.zen_tab.pages.setCurrentIndex(1)
        capture(window, "plan", output)
        window.zen_tab.pages.setCurrentIndex(0)

        indexer = Indexer(
            "https://c411.org/api",
            "documentation-example",
            http=httpx.Client(
                transport=httpx.MockTransport(
                    lambda req: httpx.Response(
                        200, json=TREE if req.url.path == "/api/categories" else FACETS
                    )
                )
            ),
        )
        search = window.search_tab
        search.indexer = lambda: indexer
        window.tabs.setCurrentIndex(3)
        for _ in range(100):
            QTest.qWait(20)
            if search.filters.ready:
                break
        search.category.select_category(-6)
        for _ in range(100):
            QTest.qWait(20)
            if search.filters.ready:
                break
        search.query.setText("Blender")
        candidates = [
            Candidate(
                name,
                (i + 1) * 1024**3,
                f"https://example.invalid/{i}",
                8 + i * 5,
                str(i + 1) * 40,
                categories=(2010,),
                published_at=time.time() - (i + 1) * 3600,
            )
            for i, name in enumerate(names)
        ]
        search._show_results(candidates, indexer)
        search.results.selectRow(0)
        for column, width in enumerate((360, 90, 70, 135, 80, 85, 85, 90)):
            search.results.setColumnWidth(column, width)
        capture(window, "recherche", output)
        for candidate in candidates[:2]:
            enqueue(
                window.store,
                indexer,
                candidate,
                Path(localize("/exemple/Telechargements", "/example/Downloads")),
            )
        search.refresh_queue()
        search.show_queue()
        capture(window, "file", output)

        upload = window.upload_tab
        # Populate a real 3D form without filesystem inspection or online category lookups.
        upload._show_options = lambda: None
        upload._inspect = lambda: None
        upload._show_model = lambda: None
        upload._show_existing = lambda: upload._render_existing([])
        item = LocalItem(
            folders[1].path / localize("Support.de.telephone.stl", "Phone.Stand.stl"),
            {localize("Support.de.telephone.stl", "Phone.Stand.stl"): 4500000},
        )
        entry = LibraryEntry(folders[1], item, ItemState.ORPHAN)
        upload.set_entries([entry])
        upload.remember(entry, [])
        upload.select(item.path)
        form = UploadForm(
            category=upload.profile().category,
            subcategory=upload.subcategory.currentData(),
            title=upload.name.text(),
            description=localize(
                "Support de téléphone de démonstration. À relire avant envoi.",
                "Example phone stand. Review before sending.",
            ),
            nfo=upload.nfo.toPlainText(),
        ).model_dump()
        record = window.store.save_local_draft(
            {
                "path": str(item.path),
                "form": form,
                "files": [{"path": name, "size": size} for name, size in item.files.items()],
                "extra": {},
                "review": {},
            }
        )
        upload.local_drafts.options_callback = lambda _: []
        upload.local_drafts.record = record
        upload.local_drafts.load()
        upload.local_drafts.refresh()
        upload.workspaces.setCurrentWidget(upload.local_drafts)
        window.tabs.setCurrentIndex(2)
        capture(window, "upload", output)
        upload.local_drafts.pages.setCurrentIndex(4)
        capture(window, "upload-review", output)
        manager = window.torrents_tab
        manager.refresh = lambda: None
        manager.set_seeding(view)
        manager.model.update(
            [
                replace(
                    row.torrent,
                    trackers=("https://c411.org/announce/example",),
                    connected_seeds=4,
                    connected_peers=2,
                )
                for row in rows
            ]
        )
        manager._group()
        window.tabs.setCurrentWidget(window.torrent_stack.parentWidget())
        window.torrent_stack.setCurrentWidget(manager)
        QTest.qWait(150)
        manager.findChild(QSplitter).setSizes([260, 1080])
        manager.tree.expandAll()
        manager.connection.setText(
            localize("Connecté · données d’exemple", "Connected · example data")
        )
        manager.table.selectRow(0)
        capture(window, "torrents", output)
        window._open_documentation()
        window.documentation_tab.open_guide(f"guide/{language}/torrents.md")
        capture(window, "documentation", output)
        window.hide()
        app.findChild(ThemeFollower).monitor.terminate()
        app.findChild(ThemeFollower).monitor.waitForFinished(1000)

    print(f"Screenshots saved in {output}")


if __name__ == "__main__":
    main()
