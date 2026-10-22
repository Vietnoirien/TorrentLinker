from __future__ import annotations

import html
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
    QStackedWidget,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from torrentlinker.clients import connect
from torrentlinker.config import Settings
from torrentlinker.credentials import get_secret, set_secret
from torrentlinker.domain import ContentKind, LibraryFolder, PathMapping, Torrent, TorrentClient
from torrentlinker.downloads import DownloadFolders, IndexerCategory
from torrentlinker.gui.errors import offer_whole_names
from torrentlinker.gui.tasks import run_in_background
from torrentlinker.gui.zen_view import WARNING, class_label
from torrentlinker.indexer import Caps, Indexer
from torrentlinker.paths import (
    Detection,
    MappingCheck,
    check_mappings,
    detect_mappings,
    unreachable_download_folders,
)
from torrentlinker.qbit import ClientApi, is_api_key
from torrentlinker.queries import default_categories
from torrentlinker.zen import ZenClass, ZenProfile

log = logging.getLogger(__name__)

QBIT_PASSWORD = "qbit-password"
QBIT_API_KEY = "qbit-api-key"
DELUGE_PASSWORD = "deluge-password"
TRANSMISSION_PASSWORD = "transmission-password"
INDEXER_API_KEY = "indexer-api-key"
# Up to 4 more keys of the same c411 account, each within its own limits (ADR-0008).
EXTRA_INDEXER_KEYS = tuple(f"indexer-api-key-{n}" for n in range(2, 6))
ANNOUNCE_URL = "announce-url"  # holds the passkey: a secret like the keys (ADR-0011)
TMDB_API_KEY = "tmdb-api-key"

COL_PATH, COL_KIND, COL_DEPTH = range(3)
COL_LOCAL, COL_QBIT, COL_CHECK = range(3)
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
                self._keyring_note(), self._client_box(), self._indexer_box(), self._tmdb_box()
            ),
            self.tr("Connections"),
        )
        self.tabs.addTab(self._page(self._folders_box()), self.tr("Library Folders"))
        self.tabs.addTab(
            self._page(self._search_box(), self._matching_box()), self.tr("Search && Matching")
        )
        self.tabs.addTab(self._page(self._downloads_box(), fill=True), self.tr("Download Folders"))
        self.tabs.addTab(self._page(self._paths_box(), fill=True), self.tr("Client Paths"))
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
    def _page(*boxes: QWidget, fill: bool = False) -> QScrollArea:
        """A scrollable tab; with `fill` its boxes grow with the window (long tables)."""
        body = QWidget()
        layout = QVBoxLayout(body)
        for box in boxes:
            layout.addWidget(box, 1 if fill else 0)
        if not fill:
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
        self.badge_bonus = QDoubleSpinBox()
        self.badge_bonus.setRange(0, 100)
        self.badge_bonus.setDecimals(1)
        self.badge_bonus.setSuffix(" %")
        self.badge_bonus.setValue(z.badge_bonus * 100)
        self.badge_bonus.setToolTip(
            self.tr(
                "What your shop badges add (Pondération + while worn, Pondération ++ once "
                "owned), on top of your Class maximum. c411 shows it under Zen → Bonus; "
                "its API does not report it."
            )
        )
        form.addRow(self.tr("Shop badges bonus"), self.badge_bonus)
        self.seed_hours = QDoubleSpinBox()
        self.seed_hours.setRange(0, 24)
        self.seed_hours.setDecimals(1)
        self.seed_hours.setSuffix(self.tr(" h"))
        self.seed_hours.setValue(z.seed_hours)
        self.seed_hours.setToolTip(
            self.tr("Hours a day your torrent client runs; under 30 minutes earns nothing")
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
            badge_bonus=self.badge_bonus.value() / 100,
            seed_hours=self.seed_hours.value(),
            torrent_cap=self.torrent_cap.value(),
        )

    # Torrent client --------------------------------------------------------

    def _client_box(self) -> QGroupBox:
        box = QGroupBox(self.tr("Torrent client"))
        layout = QVBoxLayout(box)
        self.client = QComboBox()
        for client in TorrentClient:
            self.client.addItem(client.display_name, client.value)
        self.client.setCurrentIndex(self.client.findData(self.settings.client.value))
        choice = QFormLayout()
        choice.addRow(self.tr("Client"), self.client)
        layout.addLayout(choice)
        self.client_forms = QStackedWidget()
        self.client_forms.addWidget(self._qbit_form())
        self.client_forms.addWidget(self._deluge_form())
        self.client_forms.addWidget(self._transmission_form())
        self.client_forms.setCurrentIndex(self.client.currentIndex())
        self.client.currentIndexChanged.connect(self.client_forms.setCurrentIndex)
        layout.addWidget(self.client_forms)
        test = QPushButton(self.tr("Test connection"))
        test.clicked.connect(self._test_qbit)
        row = QHBoxLayout()
        row.addWidget(test)
        row.addStretch()
        layout.addLayout(row)
        hint = QLabel(
            self.tr(
                "Your torrent client in Docker, on a NAS or on another computer? Tell the app "
                "how it sees your folders in the Client Paths tab."
            )
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        return box

    def _chosen_client(self) -> TorrentClient:
        return TorrentClient(self.client.currentData())

    def _deluge_form(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(0, 0, 0, 0)
        self.deluge_host = QLineEdit(self.settings.deluge.host)
        self.deluge_password = self._secret_field(DELUGE_PASSWORD)
        form.addRow(self.tr("Web UI address"), self.deluge_host)
        form.addRow(self.tr("Web UI password"), self.deluge_password)
        note = QLabel(
            self.tr(
                "Deluge 2. Turn on its Label plugin (Preferences → Plugins): TorrentLinker "
                "labels the torrents it adds to follow their Verification."
            )
        )
        note.setWordWrap(True)
        form.addRow("", note)
        return page

    def _transmission_form(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(0, 0, 0, 0)
        self.transmission_host = QLineEdit(self.settings.transmission.host)
        self.transmission_user = QLineEdit(self.settings.transmission.username)
        self.transmission_password = self._secret_field(TRANSMISSION_PASSWORD)
        form.addRow(self.tr("Remote address"), self.transmission_host)
        form.addRow(self.tr("Username"), self.transmission_user)
        form.addRow(self.tr("Password"), self.transmission_password)
        note = QLabel(
            self.tr(
                "Turn on remote access in Transmission (Preferences → Remote). Reseeds need "
                "“Append .part to incomplete files' names” off: TorrentLinker offers to turn "
                "it off. Transmission renames file and folder names in place only, so a "
                "Match needing other folders cannot be Reseeded with it."
            )
        )
        note.setWordWrap(True)
        form.addRow("", note)
        return page

    def _qbit_form(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(0, 0, 0, 0)
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
        form.addRow(self.tr("WebUI address"), self.qbit_host)
        form.addRow(self.tr("Username"), self.qbit_user)
        form.addRow(self.tr("Password"), self.qbit_password)
        form.addRow(self.tr("API key"), self.qbit_api_key)
        return page

    def _form_qbit(self) -> ClientApi | None:
        """The torrent client as the form describes it, saved or not; None if the qBittorrent
        API key is malformed."""
        client = self._chosen_client()
        if client is TorrentClient.DELUGE:
            return connect(client, self.deluge_host.text(), "", self.deluge_password.text())
        if client is TorrentClient.TRANSMISSION:
            return connect(
                client,
                self.transmission_host.text(),
                self.transmission_user.text(),
                self.transmission_password.text(),
            )
        key = self.qbit_api_key.text().strip()
        if key and not is_api_key(key):
            QMessageBox.warning(
                self,
                self.tr("qBittorrent"),
                self.tr("An API key looks like qbt_ followed by 28 letters and digits."),
            )
            return None
        return connect(
            client, self.qbit_host.text(), self.qbit_user.text(), self.qbit_password.text(), key
        )

    def _test_qbit(self) -> None:
        if (api := self._form_qbit()) is None:
            return
        name = self._chosen_client().display_name

        def failed(e: Exception) -> None:
            if not offer_whole_names(self, e, then=self._test_qbit):
                QMessageBox.warning(self, name, str(e))

        run_in_background(
            api.check,
            lambda v: QMessageBox.information(
                self, name, self.tr("Connected to {0} {1}").format(name, v)
            ),
            failed,
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
        self.extra_keys = [self._secret_field(name) for name in EXTRA_INDEXER_KEYS]
        extra = QVBoxLayout()
        for n, field in enumerate(self.extra_keys, 2):
            field.setPlaceholderText(self.tr("Key {0} (optional)").format(n))
            extra.addWidget(field)
        note = QLabel(
            self.tr(
                "Up to 4 more keys of the same c411 account (5 in all). c411 limits each key "
                "separately: each request goes to the key that is free soonest, and a key "
                "c411 asks to wait rests while the others go on."
            )
        )
        note.setWordWrap(True)
        extra.addWidget(note)
        form.addRow(self.tr("More API keys"), extra)
        self.announce_url = self._secret_field(ANNOUNCE_URL)
        self.announce_url.setPlaceholderText(
            self.tr("Optional: your private announce URL, for Uploads")
        )
        form.addRow(self.tr("Announce URL"), self.announce_url)
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
        return Indexer(
            self.indexer_url.text().strip(),
            self.indexer_key.text().strip(),
            extra_keys=[f.text().strip() for f in self.extra_keys],
        )

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
        self.folders = QTableWidget(0, 3)
        self.folders.setHorizontalHeaderLabels(
            [self.tr("Folder"), self.tr("Content Kind"), self.tr("Scan depth")]
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
        return choose_directory(self, title, start)

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

    def _read_folders(self) -> list[LibraryFolder]:
        result = []
        for r in range(self.folders.rowCount()):
            cell = self.folders.item(r, COL_PATH)
            kind, depth = (
                self.folders.cellWidget(r, COL_KIND),
                self.folders.cellWidget(r, COL_DEPTH),
            )
            assert cell is not None and isinstance(kind, QComboBox) and isinstance(depth, QSpinBox)
            result.append(
                LibraryFolder(Path(cell.text()), depth.value(), ContentKind(kind.currentData()))
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
        # Long merged labels (one id covering several c411 categories) are elided, with
        # the full label as tooltip, so the folder columns stay visible.
        header.setSectionResizeMode(COL_CATEGORY, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(COL_FOLDER, QHeaderView.ResizeMode.Interactive)
        header.resizeSection(COL_FOLDER, 240)
        header.setSectionResizeMode(COL_RESOLVED, QHeaderView.ResizeMode.Interactive)
        header.resizeSection(COL_RESOLVED, 220)
        self.download_table.setTextElideMode(Qt.TextElideMode.ElideRight)
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
            name.setToolTip(f"{info.name} ({cat})")
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

    # Client Paths ----------------------------------------------------------

    def _paths_box(self) -> QGroupBox:
        box = QGroupBox(self.tr("Torrent client in Docker, on a NAS or on another computer"))
        layout = QVBoxLayout(box)
        intro = QLabel(
            self.tr(
                "Fill this in only if your torrent client sees your folders under other paths "
                "than this computer does. For example, it runs in Docker and sees /data, "
                "while this computer reaches the same files as /mnt/nas or Z:\\. Detect finds "
                "the paths from the client's own torrents, then Check counts the torrents "
                "each path leads to."
            )
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.mappings = QTableWidget(0, 3)
        self.mappings.setHorizontalHeaderLabels(
            [self.tr("On this computer"), self.tr("In the client"), self.tr("Check")]
        )
        header = self.mappings.horizontalHeader()
        header.setSectionResizeMode(COL_LOCAL, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(COL_QBIT, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(COL_CHECK, QHeaderView.ResizeMode.ResizeToContents)
        self.mappings.verticalHeader().setVisible(False)
        for m in self.settings.path_mappings:
            self._add_mapping_row(m)
        layout.addWidget(self.mappings)
        row = QHBoxLayout()
        add = QPushButton(self.tr("Add folder…"))
        add.setToolTip(
            self.tr("Choose a folder on this computer, then type how your torrent client sees it")
        )
        add.clicked.connect(self._pick_mapping)
        remove = QPushButton(self.tr("Remove"))
        remove.clicked.connect(lambda: self.mappings.removeRow(self.mappings.currentRow()))
        self.detect_button = QPushButton(self.tr("Detect"))
        self.detect_button.setToolTip(
            self.tr(
                "Look for your torrent client's torrents in your Library and Download Folders and "
                "the folders above them, and add the paths that lead there"
            )
        )
        self.detect_button.clicked.connect(self._detect_paths)
        self.check_button = QPushButton(self.tr("Check"))
        self.check_button.setToolTip(
            self.tr("Count, for each path, the client's torrents whose folder is found here")
        )
        self.check_button.clicked.connect(lambda: self._check_paths())
        row.addWidget(add)
        row.addWidget(remove)
        row.addStretch()
        row.addWidget(self.detect_button)
        row.addWidget(self.check_button)
        layout.addLayout(row)
        self.paths_status = QLabel()
        self.paths_status.setTextFormat(Qt.TextFormat.RichText)
        self._status_lines: list[tuple[str, bool]] = []  # text, is a warning
        self.paths_status.setWordWrap(True)
        self.paths_status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.paths_status)
        return box

    def _add_mapping_row(self, m: PathMapping) -> None:
        r = self.mappings.rowCount()
        self.mappings.insertRow(r)
        self.mappings.setItem(r, COL_LOCAL, QTableWidgetItem(m.local))
        self.mappings.setItem(r, COL_QBIT, QTableWidgetItem(m.qbit))
        check = QTableWidgetItem("")
        check.setFlags(check.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.mappings.setItem(r, COL_CHECK, check)

    def _pick_mapping(self) -> None:
        if path := self._choose_dir(self.tr("Choose a folder on this computer")):
            self._add_mapping_row(PathMapping(path, ""))
            row = self.mappings.rowCount() - 1
            self.mappings.setCurrentCell(row, COL_QBIT)
            if cell := self.mappings.item(row, COL_QBIT):
                self.mappings.editItem(cell)

    def _read_mappings(self) -> list[PathMapping]:
        result = []
        for r in range(self.mappings.rowCount()):
            local, qbit = self.mappings.item(r, COL_LOCAL), self.mappings.item(r, COL_QBIT)
            if local and qbit and local.text().strip() and qbit.text().strip():
                m = PathMapping(local.text().strip(), qbit.text().strip())
                if m not in result:
                    result.append(m)
        return result

    def _local_folders(self) -> list[Path]:
        downloads = self._read_download_folders()
        paths = [f.path for f in self._read_folders()]
        paths += [Path(p) for p in [*downloads.by_category.values(), downloads.default] if p]
        return list(dict.fromkeys(paths))

    def _paths_busy(self, busy: bool, text: str = "") -> None:
        self.detect_button.setEnabled(not busy)
        self.check_button.setEnabled(not busy)
        if text:
            self._set_status([(line, False) for line in text.splitlines()])

    def _set_status(self, lines: list[tuple[str, bool]]) -> None:
        """Show these lines under the paths; warnings in the warning color."""
        self._status_lines = lines
        self.paths_status.setText(
            "<br>".join(
                f'<span style="color: {WARNING.name()}">{html.escape(text)}</span>'
                if warning
                else html.escape(text)
                for text, warning in lines
            )
        )

    def _detect_paths(self) -> None:
        folders = self._local_folders()
        if not folders:
            self.paths_status.setText(
                self.tr(
                    "Add your Library Folders or Download Folders first: Detect looks for "
                    "your torrent client's files in them."
                )
            )
            return
        if (api := self._form_qbit()) is None:
            return

        def work() -> Detection:
            def files(t: Torrent) -> dict[str, int]:
                found = api.torrent(t.hash)
                return found.files if found else {}

            return detect_mappings(api.torrents(with_files=False), folders, files)

        self._paths_busy(
            True, self.tr("Looking for your torrent client's torrents on this computer…")
        )
        run_in_background(work, self._detected, self._paths_failed)

    def _detected(self, d: Detection) -> None:
        known = set(self._read_mappings())
        added = [s for s in d.suggestions if s.mapping not in known]
        for s in added:
            self._add_mapping_row(s.mapping)
        lines = []
        for s in d.suggestions:
            lines.append(
                self.tr("{0} ↔ {1}: {2} torrents found").format(
                    s.mapping.local, s.mapping.qbit, s.torrents
                )
            )
        if d.same_paths:
            lines.append(
                self.tr("{0} torrents are at the same path here: they need no mapping.").format(
                    d.same_paths
                )
            )
        if d.not_found:
            lines.append(
                self.tr("Not found on this computer: {0}").format(", ".join(d.not_found[:4]))
                + (" …" if len(d.not_found) > 4 else "")
            )
        if not d.suggestions and not d.same_paths:
            lines.insert(
                0,
                self.tr(
                    "None of your torrent client's torrents was found in your folders. Add "
                    "the folder where this computer sees its downloads as a Download Folder "
                    "or Library Folder, then detect again; or add the path by hand."
                ),
            )
        elif added:
            lines.insert(0, self.tr("{0} paths added. Save to use them.").format(len(added)))
        self._paths_busy(False, "\n".join(lines))
        if self._read_mappings():
            self._check_paths(keep_status=True)

    def _check_paths(self, keep_status: bool = False) -> None:
        if (api := self._form_qbit()) is None:
            return
        if not keep_status:
            self._set_status([])
        for r in range(self.mappings.rowCount()):
            if cell := self.mappings.item(r, COL_CHECK):
                cell.setText("…")
        mappings = self._read_mappings()
        downloads = self._read_download_folders()
        download_paths = [
            Path(p) for p in [*downloads.by_category.values(), downloads.default] if p
        ]

        def work() -> tuple[list[MappingCheck], list[Path], str]:
            default = api.default_save_path()
            checks = check_mappings(api.torrents(with_files=False), mappings)
            return checks, unreachable_download_folders(download_paths, mappings, default), default

        self._paths_busy(True)
        run_in_background(work, self._checked, self._paths_failed)

    def _checked(self, result: tuple[list[MappingCheck], list[Path], str]) -> None:
        checks, unreachable, default = result
        lines = []
        for c in checks:
            if c.mapping is None:
                if c.total:
                    lines.append(
                        self.tr("Outside every path above: {0} of {1} torrents found here.").format(
                            c.found, c.total
                        )
                    )
                continue
            for r in range(self.mappings.rowCount()):
                local, qbit = self.mappings.item(r, COL_LOCAL), self.mappings.item(r, COL_QBIT)
                if (
                    local
                    and qbit
                    and PathMapping(local.text().strip(), qbit.text().strip()) == c.mapping
                ):
                    cell = self.mappings.item(r, COL_CHECK)
                    assert cell is not None
                    ok = c.found == c.total
                    cell.setText(
                        self.tr("no torrent")
                        if not c.total
                        else (self.tr("✓ {0} of {1}") if ok else self.tr("⚠ {0} of {1}")).format(
                            c.found, c.total
                        )
                    )
                    cell.setForeground(QColor() if ok else WARNING)
                    cell.setToolTip(
                        self.tr("Not found here: {0}").format(", ".join(c.missing))
                        if c.missing
                        else ""
                    )
        if unreachable:
            lines.append(
                self.tr(
                    "Your torrent client's own download folder ({0}) does not exist on this "
                    "computer, and no path above covers these Download Folders: {1}. The "
                    "client probably cannot save into them."
                ).format(default, ", ".join(map(str, unreachable)))
            )
        self._paths_busy(False)
        warnings = [(line, True) for line in lines[len(lines) - bool(unreachable) :]]
        notes = [(line, False) for line in lines[: len(lines) - bool(unreachable)]]
        self._set_status(self._status_lines + notes + warnings)

    def _paths_failed(self, error: Exception) -> None:
        self._paths_busy(False, self.tr("Could not reach your torrent client: {0}").format(error))

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
            DELUGE_PASSWORD: self.deluge_password.text(),
            TRANSMISSION_PASSWORD: self.transmission_password.text(),
            INDEXER_API_KEY: self.indexer_key.text().strip(),
            TMDB_API_KEY: self.tmdb_key.text().strip(),
            ANNOUNCE_URL: self.announce_url.text().strip(),
            **{
                name: field.text().strip()
                for name, field in zip(EXTRA_INDEXER_KEYS, self.extra_keys, strict=True)
            },
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
        s.client = self._chosen_client()
        s.deluge.host = self.deluge_host.text().strip()
        s.transmission.host = self.transmission_host.text().strip()
        s.transmission.username = self.transmission_user.text().strip()
        s.qbit.host = self.qbit_host.text().strip()
        s.qbit.username = self.qbit_user.text().strip()
        s.indexer.url = self.indexer_url.text().strip()
        s.library_folders = self._read_folders()
        s.kind_categories = self._read_categories()
        s.zen = self._read_zen()
        s.free_space_margin = self.margin.value() / 100
        s.indexer_categories = dict(self._categories)
        s.download_folders = self._read_download_folders()
        s.path_mappings = self._read_mappings()
        s.matching.size_tolerance = self.tolerance.value() / 100
        s.matching.min_partial_coverage = self.coverage.value() / 100
        s.matching.ignore_patterns = [
            line.strip() for line in self.ignore.toPlainText().splitlines() if line.strip()
        ]
        log.info("settings saved: %d Library Folders", len(s.library_folders))
        self.accept()


def extra_indexer_keys() -> list[str]:
    """The Indexer keys saved after the main one, in order, without empty ones."""
    return [k for name in EXTRA_INDEXER_KEYS if (k := get_secret(name))]


def choose_directory(parent: QWidget, title: str, start: str = "") -> str:
    """A folder the user picks, or "" if they cancel."""
    options = QFileDialog.Option.ShowDirsOnly
    if sys.platform.startswith("linux"):
        # The desktop-portal picker can hand back an empty path under Wayland.
        options |= QFileDialog.Option.DontUseNativeDialog
    path = QFileDialog.getExistingDirectory(parent, title, start or str(Path.home()), options)
    log.info("folder picked: %r", path)
    return path
