from __future__ import annotations

import logging
import sys
from pathlib import Path

from keyring.errors import KeyringError
from PySide6.QtCore import QT_TRANSLATE_NOOP, QCoreApplication, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from torrentlinker.config import Settings
from torrentlinker.credentials import get_secret, set_secret
from torrentlinker.domain import ContentKind, LibraryFolder, PathMapping
from torrentlinker.gui.tasks import run_in_background
from torrentlinker.indexer import Caps, Indexer
from torrentlinker.qbit import QbitApi
from torrentlinker.queries import default_categories

log = logging.getLogger(__name__)

QBIT_PASSWORD = "qbit-password"
INDEXER_API_KEY = "indexer-api-key"
TMDB_API_KEY = "tmdb-api-key"

COL_PATH, COL_KIND, COL_DEPTH, COL_MAPPING = range(4)


KIND_LABELS = {
    ContentKind.MOVIE: QT_TRANSLATE_NOOP("ContentKind", "Movies"),
    ContentKind.SERIES: QT_TRANSLATE_NOOP("ContentKind", "Series"),
    ContentKind.MUSIC: QT_TRANSLATE_NOOP("ContentKind", "Music"),
    ContentKind.EBOOK: QT_TRANSLATE_NOOP("ContentKind", "Ebooks"),
    ContentKind.GAME: QT_TRANSLATE_NOOP("ContentKind", "Games"),
    ContentKind.MODEL_3D: QT_TRANSLATE_NOOP("ContentKind", "3D models"),
    ContentKind.OTHER: QT_TRANSLATE_NOOP("ContentKind", "Other"),
}


def kind_label(kind: ContentKind) -> str:
    return QCoreApplication.translate("ContentKind", str(KIND_LABELS[kind]))


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Settings"))
        self.resize(820, 720)
        self.settings = settings
        self._loaded_secrets: dict[str, str] = {}

        self.tabs = QTabWidget()
        self.tabs.addTab(
            self._page(
                self._keyring_note(), self._qbit_box(), self._indexer_box(), self._tmdb_box()
            ),
            self.tr("Connections"),
        )
        self.tabs.addTab(self._page(self._folders_box()), self.tr("Library Folders"))
        self.tabs.addTab(
            self._page(self._search_box(), self._matching_box()), self.tr("Search && Matching")
        )
        self.tabs.addTab(self._page(self._general_box()), self.tr("General"))

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        outer = QVBoxLayout(self)
        outer.addWidget(self.tabs)
        outer.addWidget(buttons)

    @staticmethod
    def _page(*boxes: QWidget) -> QScrollArea:
        body = QWidget()
        layout = QVBoxLayout(body)
        for box in boxes:
            layout.addWidget(box)
        layout.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(body)
        return scroll

    def _keyring_note(self) -> QLabel:
        note = QLabel(
            self.tr(
                "Passwords and API keys are stored in your system keyring, "
                "never in TorrentLinker's settings file."
            )
        )
        note.setWordWrap(True)
        return note

    def _secret_field(self, name: str) -> QLineEdit:
        self._loaded_secrets[name] = get_secret(name)
        field = QLineEdit(self._loaded_secrets[name])
        field.setEchoMode(QLineEdit.EchoMode.Password)
        reveal = field.addAction(
            self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogContentsView),
            QLineEdit.ActionPosition.TrailingPosition,
        )
        reveal.setCheckable(True)
        reveal.setToolTip(self.tr("Show / hide"))
        reveal.toggled.connect(
            lambda shown: field.setEchoMode(
                QLineEdit.EchoMode.Normal if shown else QLineEdit.EchoMode.Password
            )
        )
        return field

    # General ---------------------------------------------------------------

    def _general_box(self) -> QGroupBox:
        box = QGroupBox(self.tr("General"))
        form = QFormLayout(box)
        self.language = QComboBox()
        self.language.addItem(self.tr("Automatic (system language)"), "auto")
        self.language.addItem("English", "en")
        self.language.addItem("Français", "fr")
        self.language.setCurrentIndex(max(self.language.findData(self.settings.language), 0))
        self.language.setToolTip(self.tr("Takes effect after restarting the app"))
        form.addRow(self.tr("Language"), self.language)
        return box

    # qBittorrent -----------------------------------------------------------

    def _qbit_box(self) -> QGroupBox:
        box = QGroupBox(self.tr("qBittorrent"))
        form = QFormLayout(box)
        self.qbit_host = QLineEdit(self.settings.qbit.host)
        self.qbit_user = QLineEdit(self.settings.qbit.username)
        self.qbit_password = self._secret_field(QBIT_PASSWORD)
        test = QPushButton(self.tr("Test connection"))
        test.clicked.connect(self._test_qbit)
        form.addRow(self.tr("WebUI address"), self.qbit_host)
        form.addRow(self.tr("Username"), self.qbit_user)
        form.addRow(self.tr("Password"), self.qbit_password)
        form.addRow("", test)
        return box

    def _test_qbit(self) -> None:
        api = QbitApi(self.qbit_host.text(), self.qbit_user.text(), self.qbit_password.text())
        run_in_background(
            api.check,
            lambda v: QMessageBox.information(
                self, self.tr("qBittorrent"), self.tr("Connected to qBittorrent {0}").format(v)
            ),
            lambda e: QMessageBox.warning(self, self.tr("qBittorrent"), str(e)),
        )

    # Indexer ---------------------------------------------------------------

    def _indexer_box(self) -> QGroupBox:
        box = QGroupBox(self.tr("Indexer (Torznab)"))
        form = QFormLayout(box)
        self.indexer_url = QLineEdit(self.settings.indexer.url)
        self.indexer_key = self._secret_field(INDEXER_API_KEY)
        test = QPushButton(self.tr("Test Indexer"))
        test.clicked.connect(self._test_indexer)
        hint = QLabel(
            self.tr('On c411, generate your key at <a href="{0}">{0}</a>').format(
                "https://c411.org/user/integrations"
            )
        )
        hint.setOpenExternalLinks(True)
        form.addRow(self.tr("Torznab URL"), self.indexer_url)
        form.addRow(self.tr("API key"), self.indexer_key)
        form.addRow("", hint)
        form.addRow("", test)
        return box

    def _tmdb_box(self) -> QGroupBox:
        box = QGroupBox(self.tr("TMDb (optional)"))
        form = QFormLayout(box)
        self.tmdb_key = self._secret_field(TMDB_API_KEY)
        self.tmdb_key.setPlaceholderText(self.tr("Optional: finds IDs for movies and series"))
        hint = QLabel(
            self.tr('Free key at <a href="{0}">{0}</a>').format(
                "https://www.themoviedb.org/settings/api"
            )
        )
        hint.setOpenExternalLinks(True)
        form.addRow(self.tr("TMDb API key"), self.tmdb_key)
        form.addRow("", hint)
        return box

    def _form_indexer(self) -> Indexer:
        return Indexer(self.indexer_url.text().strip(), self.indexer_key.text().strip())

    def _test_indexer(self) -> None:
        run_in_background(
            self._form_indexer().caps,
            lambda caps: QMessageBox.information(
                self,
                self.tr("Indexer"),
                self.tr("Indexer OK: {0} categories").format(len(caps.categories)),
            ),
            lambda e: QMessageBox.warning(self, self.tr("Indexer"), str(e)),
        )

    # Library Folders -------------------------------------------------------

    def _folders_box(self) -> QGroupBox:
        box = QGroupBox(self.tr("Library Folders"))
        layout = QVBoxLayout(box)
        self.folders = QTableWidget(0, 4)
        self.folders.setHorizontalHeaderLabels(
            [
                self.tr("Folder"),
                self.tr("Content Kind"),
                self.tr("Scan depth"),
                self.tr("qBittorrent sees it as"),
            ]
        )
        header = self.folders.horizontalHeaderItem(COL_MAPPING)
        if header:
            header.setToolTip(
                self.tr("Path Mapping: fill in only if qBittorrent runs in Docker, on a NAS…")
            )
        self.folders.horizontalHeader().setSectionResizeMode(
            COL_PATH, QHeaderView.ResizeMode.Stretch
        )
        for f in self.settings.library_folders:
            self._add_folder_row(f)
        layout.addWidget(self.folders)

        row = QHBoxLayout()
        self.typed_folder = QLineEdit()
        self.typed_folder.setPlaceholderText(self.tr("…or type a folder path and press Enter"))
        self.typed_folder.returnPressed.connect(self._add_typed_folder)
        add = QPushButton(self.tr("Add folder…"))
        add.clicked.connect(self._pick_folder)
        remove = QPushButton(self.tr("Remove"))
        remove.clicked.connect(lambda: self.folders.removeRow(self.folders.currentRow()))
        row.addWidget(add)
        row.addWidget(self.typed_folder, 1)
        row.addWidget(remove)
        layout.addLayout(row)
        return box

    def _add_typed_folder(self) -> None:
        path = Path(self.typed_folder.text().strip()).expanduser()
        if not path.is_dir():
            QMessageBox.warning(
                self, self.tr("Library Folders"), self.tr("Not a folder: {0}").format(path)
            )
            return
        self._add_folder_row(LibraryFolder(path))
        self.typed_folder.clear()

    def _pick_folder(self) -> None:
        options = QFileDialog.Option.ShowDirsOnly
        if sys.platform.startswith("linux"):
            # The desktop-portal picker can hand back an empty path under Wayland.
            options |= QFileDialog.Option.DontUseNativeDialog
        path = QFileDialog.getExistingDirectory(
            self, self.tr("Choose a Library Folder"), str(Path.home()), options
        )
        log.info("folder picked: %r", path)
        if path:
            self._add_folder_row(LibraryFolder(Path(path)))

    def _add_folder_row(self, folder: LibraryFolder) -> None:
        r = self.folders.rowCount()
        self.folders.insertRow(r)
        path_cell = QTableWidgetItem(str(folder.path))
        path_cell.setFlags(path_cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.folders.setItem(r, COL_PATH, path_cell)
        kind = QComboBox()
        for k in ContentKind:
            kind.addItem(kind_label(k), k)
        kind.setCurrentIndex(list(ContentKind).index(folder.kind))
        self.folders.setCellWidget(r, COL_KIND, kind)
        depth = QSpinBox()
        depth.setRange(1, 5)
        depth.setValue(folder.depth)
        self.folders.setCellWidget(r, COL_DEPTH, depth)
        mapped = folder.mapping.qbit if folder.mapping else ""
        self.folders.setItem(r, COL_MAPPING, QTableWidgetItem(mapped))

    def _read_folders(self) -> list[LibraryFolder]:
        result = []
        for r in range(self.folders.rowCount()):
            cell = self.folders.item(r, COL_PATH)
            kind, depth = (
                self.folders.cellWidget(r, COL_KIND),
                self.folders.cellWidget(r, COL_DEPTH),
            )
            assert cell is not None and isinstance(kind, QComboBox) and isinstance(depth, QSpinBox)
            path = Path(cell.text())
            mapped_cell = self.folders.item(r, COL_MAPPING)
            mapped = mapped_cell.text().strip() if mapped_cell else ""
            mapping = PathMapping(str(path), mapped) if mapped else None
            result.append(
                LibraryFolder(path, depth.value(), ContentKind(kind.currentData()), mapping)
            )
        return result

    # Search ----------------------------------------------------------------

    def _search_box(self) -> QGroupBox:
        box = QGroupBox(self.tr("Search"))
        form = QFormLayout(box)
        self.category_fields: dict[ContentKind, QLineEdit] = {}
        for kind in ContentKind:
            field = QLineEdit(", ".join(str(c) for c in self.settings.categories(kind)))
            field.setPlaceholderText(self.tr("All categories"))
            self.category_fields[kind] = field
            form.addRow(self.tr("Categories: {0}").format(kind_label(kind)), field)
        fill = QPushButton(self.tr("Fill categories from the Indexer"))
        fill.clicked.connect(self._fill_categories)
        form.addRow("", fill)
        return box

    def _fill_categories(self) -> None:
        run_in_background(
            self._form_indexer().caps,
            self._apply_caps,
            lambda e: QMessageBox.warning(self, self.tr("Indexer"), str(e)),
        )

    def _apply_caps(self, caps: Caps) -> None:
        names = "\n".join(f"{i}  {n}" for i, n in sorted(caps.categories.items()))
        for kind, cats in default_categories(caps.categories).items():
            field = self.category_fields[kind]
            field.setText(", ".join(str(c) for c in cats))
            field.setToolTip(names)

    def _read_categories(self) -> dict[ContentKind, list[int]]:
        result = {}
        for kind, field in self.category_fields.items():
            cats = [
                int(c) for c in field.text().replace(";", ",").split(",") if c.strip().isdigit()
            ]
            if cats:
                result[kind] = cats
        return result

    # Matching --------------------------------------------------------------

    def _matching_box(self) -> QGroupBox:
        box = QGroupBox(self.tr("Matching"))
        form = QFormLayout(box)
        self.tolerance = QDoubleSpinBox()
        self.tolerance.setRange(0, 20)
        self.tolerance.setDecimals(1)
        self.tolerance.setSuffix(" %")
        self.tolerance.setValue(self.settings.matching.size_tolerance * 100)
        form.addRow(self.tr("Size tolerance before fetching a .torrent"), self.tolerance)
        self.coverage = QSpinBox()
        self.coverage.setRange(1, 100)
        self.coverage.setSuffix(" %")
        self.coverage.setValue(round(self.settings.matching.min_partial_coverage * 100))
        form.addRow(self.tr("Minimum coverage of a Partial Match"), self.coverage)
        self.ignore = QPlainTextEdit("\n".join(self.settings.matching.ignore_patterns))
        self.ignore.setToolTip(self.tr("One pattern per line, matched against each path segment"))
        self.ignore.setMaximumHeight(100)
        form.addRow(self.tr("Ignored Files"), self.ignore)
        return box

    # Save ------------------------------------------------------------------

    def _save_secrets(self) -> None:
        """Write the keys that changed; a keyring problem must not lose the other settings."""
        fields = {
            QBIT_PASSWORD: self.qbit_password.text(),
            INDEXER_API_KEY: self.indexer_key.text().strip(),
            TMDB_API_KEY: self.tmdb_key.text().strip(),
        }
        try:
            for name, value in fields.items():
                if value != self._loaded_secrets.get(name):
                    set_secret(name, value)
        except KeyringError as e:
            log.warning("keyring write failed: %s", e)
            QMessageBox.warning(
                self,
                self.tr("Keyring unavailable"),
                self.tr("Your keys could not be saved in the system keyring: {0}").format(e),
            )

    def _save(self) -> None:
        self._save_secrets()
        s = self.settings
        s.language = self.language.currentData()
        s.qbit.host = self.qbit_host.text().strip()
        s.qbit.username = self.qbit_user.text().strip()
        s.indexer.url = self.indexer_url.text().strip()
        s.library_folders = self._read_folders()
        s.kind_categories = self._read_categories()
        s.matching.size_tolerance = self.tolerance.value() / 100
        s.matching.min_partial_coverage = self.coverage.value() / 100
        s.matching.ignore_patterns = [
            line.strip() for line in self.ignore.toPlainText().splitlines() if line.strip()
        ]
        log.info("settings saved: %d Library Folders", len(s.library_folders))
        self.accept()
