"""Capture the real French Qt widgets with offline example data, without user settings.

Run from the repository root: QT_QPA_PLATFORM=offscreen .venv/bin/python scripts/capture_docs.py
Requires the development dependencies. No torrents are downloaded or sent to a client.
"""

import socket
import sys
import time
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import httpx
from PySide6.QtCore import QPoint, QTimer
from PySide6.QtGui import QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox, QSplitter

from torrentlinker import i18n
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
from torrentlinker.gui.library_folder_dialog import LibraryFolderDialog
from torrentlinker.gui.main_window import MainWindow
from torrentlinker.gui.settings_dialog import SettingsDialog
from torrentlinker.gui.theme import ThemeFollower, apply_theme
from torrentlinker.indexer import Candidate, Indexer
from torrentlinker.library import LibraryEntry
from torrentlinker.seeding import Seeding, SeedingRow, zen_torrent
from torrentlinker.store import Store
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


def capture(widget, name):
    QTest.qWait(150)
    if not widget.grab().save(str(OUTPUT / f"{name}.png")):
        raise RuntimeError(f"Could not save {name}")


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    app = QApplication(sys.argv)
    app.setApplicationName("TorrentLinker")
    apply_theme(app, "dark")
    translators = i18n.install(app, "fr")  # noqa: F841
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
        folders = [
            LibraryFolder(Path("/exemple/Films"), kind=ContentKind.MOVIE),
            LibraryFolder(Path("/exemple/Modeles-3D"), kind=ContentKind.MODEL_3D),
        ]
        categories = {
            2000: IndexerCategory("Films & Vidéos"),
            2010: IndexerCategory("Animation", 2000),
            7000: IndexerCategory("Ebook"),
            7010: IndexerCategory("Livres", 7000),
        }
        settings = Settings(
            language="fr", theme="dark", library_folders=folders, indexer_categories=categories
        )
        window = MainWindow(settings, root / "settings.json", Store(root / "state.db"))
        window.resize(1440, 920)
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
            pixmap.save(str(OUTPUT / "bienvenue.png"))
            dialog.accept()

        QTimer.singleShot(150, welcome)
        window.startup()
        window.setup_notice.hide()
        window.tabs.setEnabled(True)
        window.band.setEnabled(True)
        window.statusBar().showMessage("Données d’exemple pour la documentation")
        settings_dialog = SettingsDialog(settings, window)
        settings_dialog.resize(1120, 940)
        settings_dialog.show()
        capture(settings_dialog, "connexions")
        settings_dialog._add_mapping_row(PathMapping("/exemple/Films", "/data/Films"))
        settings_dialog.tabs.setCurrentIndex(4)
        capture(settings_dialog, "chemins")
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
        window.library_model.set_status(entries[1].item.path, "Correspondance complète trouvée")
        window.library_model.set_status(entries[2].item.path, "2 candidats à vérifier")
        window.tabs.setCurrentIndex(1)
        window.findChild(QSplitter).setSizes([850, 350])
        for col, width in enumerate((300, 265, 90, 145, 90)):
            window.library_view.setColumnWidth(col, width)
        capture(window, "bibliotheque")
        folder_dialog = LibraryFolderDialog(folders[0].path, window)
        folder_dialog.kind.setCurrentIndex(folder_dialog.kind.findData(ContentKind.MOVIE))
        folder_dialog.resize(540, 240)
        folder_dialog.show()
        capture(folder_dialog, "ajouter-dossier")
        folder_dialog.reject()

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
                    "Guide.de.modelisation.3D.epub",
                    Path("/exemple/Livres"),
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
        window.band.set_catalogue("données d’exemple")
        window.tabs.setCurrentIndex(0)
        capture(window, "zen")
        window.zen_tab.pages.setCurrentIndex(1)
        capture(window, "plan")
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
        capture(window, "recherche")
        for candidate in candidates[:2]:
            enqueue(window.store, indexer, candidate, Path("/exemple/Telechargements"))
        search.refresh_queue()
        search.show_queue()
        capture(window, "file")

        upload = window.upload_tab
        # Populate a real 3D form without filesystem inspection or online category lookups.
        upload._show_options = lambda: None
        upload._inspect = lambda: None
        upload._show_model = lambda: None
        upload._show_existing = lambda: upload._render_existing([])
        item = LocalItem(
            folders[1].path / "Support.de.telephone.stl", {"Support.de.telephone.stl": 4500000}
        )
        entry = LibraryEntry(folders[1], item, ItemState.ORPHAN)
        upload.set_entries([entry])
        upload.remember(entry, [])
        upload.select(item.path)
        window.tabs.setCurrentIndex(2)
        capture(window, "upload")
        window.hide()
        app.findChild(ThemeFollower).monitor.terminate()
        app.findChild(ThemeFollower).monitor.waitForFinished(1000)

    print(f"Screenshots saved in {OUTPUT}")


if __name__ == "__main__":
    main()
