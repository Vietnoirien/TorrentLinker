from __future__ import annotations

import logging
import sys
from pathlib import Path

from keyring.errors import KeyringError
from PySide6.QtCore import QT_TRANSLATE_NOOP, QCoreApplication, Qt
from PySide6.QtGui import QColor
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
from torrentlinker.downloads import DownloadFolders, IndexerCategory
from torrentlinker.gui.tasks import run_in_background
from torrentlinker.gui.zen_view import class_label
from torrentlinker.indexer import Caps, Indexer
from torrentlinker.qbit import QbitApi, is_api_key
from torrentlinker.queries import default_categories
from torrentlinker.zen import ZenClass, ZenProfile

log = logging.getLogger(__name__)

QBIT_PASSWORD = "qbit-password"
QBIT_API_KEY = "qbit-api-key"
INDEXER_API_KEY = "indexer-api-key"
TMDB_API_KEY = "tmdb-api-key"

COL_PATH, COL_KIND, COL_DEPTH, COL_MAPPING = range(4)
COL_CATEGORY, COL_FOLDER, COL_RESOLVED = range(3)
RED = QColor("#c62828")


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
        self.tabs.addTab(self._page(self._downloads_box()), self.tr("Download Folders"))
        self.tabs.addTab(self._page(self._zen_box()), self.tr("Zen"))
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

    # Zen -------------------------------------------------------------------

    def _zen_box(self) -> QGroupBox:
        box = QGroupBox(self.tr("Zen Profile"))
        form = QFormLayout(box)
        z = self.settings.zen
        self.zen_class = QComboBox()
        for c in ZenClass:
            self.zen_class.addItem(class_label(c), c)
        self.zen_class.setCurrentIndex(list(ZenClass).index(z.zen_class))
        form.addRow(self.tr("Class"), self.zen_class)
        self.tree_bonus = QDoubleSpinBox()
        self.tree_bonus.setRange(0, 5)
        self.tree_bonus.setDecimals(1)
        self.tree_bonus.setSuffix(" %")
        self.tree_bonus.setValue(z.tree_bonus * 100)
        self.tree_bonus.setToolTip(
            self.tr("Bonus of the progression tree already unlocked on c411")
        )
        form.addRow(self.tr("Tree bonus unlocked"), self.tree_bonus)
        self.seed_hours = QDoubleSpinBox()
        self.seed_hours.setRange(0, 24)
        self.seed_hours.setDecimals(1)
        self.seed_hours.setSuffix(self.tr(" h"))
        self.seed_hours.setValue(z.seed_hours)
        self.seed_hours.setToolTip(
            self.tr("Hours a day qBittorrent runs; under 30 minutes earns nothing")
        )
        form.addRow(self.tr("Seed hours per day"), self.seed_hours)
        self.torrent_cap = QSpinBox()
        self.torrent_cap.setRange(0, 100_000)
        self.torrent_cap.setSpecialValueText(self.tr("No cap"))
        self.torrent_cap.setValue(z.torrent_cap)
        self.torrent_cap.setToolTip(self.tr("Most torrents you want to seed at once"))
        form.addRow(self.tr("Torrent cap"), self.torrent_cap)
        self.margin = QSpinBox()
        self.margin.setRange(0, 90)
        self.margin.setSuffix(" %")
        self.margin.setValue(round(self.settings.free_space_margin * 100))
        self.margin.setToolTip(
            self.tr("Share of each disk holding Download Folders that a Plan leaves free")
        )
        form.addRow(self.tr("Free space kept on each disk"), self.margin)
        return box

    def _read_zen(self) -> ZenProfile:
        return ZenProfile(
            zen_class=ZenClass(self.zen_class.currentData()),  # Qt hands enum data back as str
            tree_bonus=self.tree_bonus.value() / 100,
            seed_hours=self.seed_hours.value(),
            torrent_cap=self.torrent_cap.value(),
        )

    # qBittorrent -----------------------------------------------------------

    def _qbit_box(self) -> QGroupBox:
        box = QGroupBox(self.tr("qBittorrent"))
        form = QFormLayout(box)
        self.qbit_host = QLineEdit(self.settings.qbit.host)
        self.qbit_user = QLineEdit(self.settings.qbit.username)
        self.qbit_password = self._secret_field(QBIT_PASSWORD)
        self.qbit_api_key = self._secret_field(QBIT_API_KEY)
        self.qbit_api_key.setPlaceholderText(self.tr("qbt_… (qBittorrent 5.2 or later)"))
        self.qbit_api_key.setToolTip(
            self.tr(
                "Generate it in qBittorrent: Options → WebUI → API key. When filled, it is "
                "used instead of the username and password; leave it empty on older versions."
            )
        )
        test = QPushButton(self.tr("Test connection"))
        test.clicked.connect(self._test_qbit)
        form.addRow(self.tr("WebUI address"), self.qbit_host)
        form.addRow(self.tr("Username"), self.qbit_user)
        form.addRow(self.tr("Password"), self.qbit_password)
        form.addRow(self.tr("API key"), self.qbit_api_key)
        form.addRow("", test)
        return box

    def _test_qbit(self) -> None:
        key = self.qbit_api_key.text().strip()
        if key and not is_api_key(key):
            QMessageBox.warning(
                self,
                self.tr("qBittorrent"),
                self.tr("An API key looks like qbt_ followed by 28 letters and digits."),
            )
            return
        api = QbitApi(self.qbit_host.text(), self.qbit_user.text(), self.qbit_password.text(), key)
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

    def _choose_dir(self, title: str, start: str = "") -> str:
        options = QFileDialog.Option.ShowDirsOnly
        if sys.platform.startswith("linux"):
            # The desktop-portal picker can hand back an empty path under Wayland.
            options |= QFileDialog.Option.DontUseNativeDialog
        path = QFileDialog.getExistingDirectory(self, title, start or str(Path.home()), options)
        log.info("folder picked: %r", path)
        return path

    def _pick_folder(self) -> None:
        if path := self._choose_dir(self.tr("Choose a Library Folder")):
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

    # Download Folders ------------------------------------------------------

    def _downloads_box(self) -> QGroupBox:
        box = QGroupBox(self.tr("Download Folders"))
        layout = QVBoxLayout(box)
        note = QLabel(
            self.tr(
                "Where Plan torrents are downloaded. A subcategory uses its own folder, else "
                "its category's, else the default. A category left without any is excluded "
                "from Plans. A Download Folder may lie inside a Library Folder: downloads "
                "only ever create their own files."
            )
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        default_row = QHBoxLayout()
        self.default_download = QLineEdit(self.settings.download_folders.default)
        self.default_download.setPlaceholderText(
            self.tr("No default: unset categories are excluded")
        )
        self.default_download.textChanged.connect(self._update_resolved)
        browse = QPushButton(self.tr("Choose…"))
        browse.clicked.connect(self._choose_default_download)
        default_row.addWidget(QLabel(self.tr("Default")))
        default_row.addWidget(self.default_download, 1)
        default_row.addWidget(browse)
        layout.addLayout(default_row)

        self._categories: dict[int, IndexerCategory] = dict(self.settings.indexer_categories)
        self.download_table = QTableWidget(0, 3)
        self.download_table.setHorizontalHeaderLabels(
            [self.tr("Category"), self.tr("Download Folder"), self.tr("Used")]
        )
        header = self.download_table.horizontalHeader()
        header.setSectionResizeMode(COL_CATEGORY, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COL_FOLDER, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(COL_RESOLVED, QHeaderView.ResizeMode.Stretch)
        self.download_table.verticalHeader().setVisible(False)
        self.download_table.setMinimumHeight(300)
        self.download_table.itemChanged.connect(lambda _item: self._update_resolved())
        layout.addWidget(self.download_table)
        self._fill_download_table(self.settings.download_folders.by_category)

        row = QHBoxLayout()
        load = QPushButton(self.tr("Load categories from the Indexer"))
        load.clicked.connect(self._load_download_categories)
        choose = QPushButton(self.tr("Choose folder for the selected category…"))
        choose.clicked.connect(self._choose_category_download)
        row.addWidget(load)
        row.addStretch()
        row.addWidget(choose)
        layout.addLayout(row)
        return box

    def _ordered_categories(self) -> list[int]:
        """Categories, each followed by its subcategories."""
        tops = sorted(c for c, v in self._categories.items() if v.parent not in self._categories)
        ordered = []
        for top in tops:
            ordered.append(top)
            ordered += sorted(c for c, v in self._categories.items() if v.parent == top)
        return ordered

    def _fill_download_table(self, folders: dict[int, str]) -> None:
        table = self.download_table
        table.blockSignals(True)
        table.setRowCount(0)
        for cat in self._ordered_categories():
            r = table.rowCount()
            table.insertRow(r)
            info = self._categories[cat]
            indent = "    " if info.parent in self._categories else ""
            name = QTableWidgetItem(f"{indent}{info.name} ({cat})")
            name.setFlags(name.flags() & ~Qt.ItemFlag.ItemIsEditable)
            name.setData(Qt.ItemDataRole.UserRole, cat)
            table.setItem(r, COL_CATEGORY, name)
            table.setItem(r, COL_FOLDER, QTableWidgetItem(folders.get(cat, "")))
            used = QTableWidgetItem()
            used.setFlags(used.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(r, COL_RESOLVED, used)
        table.blockSignals(False)
        self._update_resolved()

    def _read_download_folders(self) -> DownloadFolders:
        by_category = {}
        for r in range(self.download_table.rowCount()):
            cat_cell = self.download_table.item(r, COL_CATEGORY)
            folder_cell = self.download_table.item(r, COL_FOLDER)
            if cat_cell and folder_cell and folder_cell.text().strip():
                by_category[int(cat_cell.data(Qt.ItemDataRole.UserRole))] = (
                    folder_cell.text().strip()
                )
        return DownloadFolders(by_category, self.default_download.text().strip())

    def _update_resolved(self) -> None:
        folders = self._read_download_folders()
        table = self.download_table
        table.blockSignals(True)
        for r in range(table.rowCount()):
            cat_cell, used = table.item(r, COL_CATEGORY), table.item(r, COL_RESOLVED)
            if cat_cell is None or used is None:
                continue
            path = folders.resolve(int(cat_cell.data(Qt.ItemDataRole.UserRole)), self._categories)
            if path is None:
                used.setText(self.tr("No Download Folder: excluded from Plans"))
                used.setForeground(RED)
            else:
                used.setText(str(path))
                used.setForeground(self.palette().text().color())
        table.blockSignals(False)

    def _choose_default_download(self) -> None:
        if path := self._choose_dir(
            self.tr("Default Download Folder"), self.default_download.text()
        ):
            self.default_download.setText(path)

    def _choose_category_download(self) -> None:
        r = self.download_table.currentRow()
        cell = self.download_table.item(r, COL_FOLDER) if r >= 0 else None
        if cell is not None and (path := self._choose_dir(self.tr("Download Folder"), cell.text())):
            cell.setText(path)

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

    def _set_categories(self, caps: Caps) -> None:
        folders = self._read_download_folders().by_category
        self._categories = {
            c: IndexerCategory(name, caps.parents.get(c)) for c, name in caps.categories.items()
        }
        self._fill_download_table(folders)

    def _load_download_categories(self) -> None:
        run_in_background(
            self._form_indexer().caps,
            self._set_categories,
            lambda e: QMessageBox.warning(self, self.tr("Indexer"), str(e)),
        )

    def _apply_caps(self, caps: Caps) -> None:
        self._set_categories(caps)
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
            QBIT_API_KEY: self.qbit_api_key.text().strip(),
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
        s.zen = self._read_zen()
        s.free_space_margin = self.margin.value() / 100
        s.indexer_categories = dict(self._categories)
        s.download_folders = self._read_download_folders()
        s.matching.size_tolerance = self.tolerance.value() / 100
        s.matching.min_partial_coverage = self.coverage.value() / 100
        s.matching.ignore_patterns = [
            line.strip() for line in self.ignore.toPlainText().splitlines() if line.strip()
        ]
        log.info("settings saved: %d Library Folders", len(s.library_folders))
        self.accept()
