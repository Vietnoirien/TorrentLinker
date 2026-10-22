"""The Upload tab: Orphans no Candidate matches, made into c411 Drafts (ADR-0011)."""

from __future__ import annotations

import html
import shutil
import threading
from collections.abc import Callable
from pathlib import Path

import httpx
from PySide6.QtCore import QT_TRANSLATE_NOOP, QCoreApplication, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QImage, QPixmap, QTextDocument
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from torrentlinker import net
from torrentlinker.archives import Unpacked, is_archive, unpack, unpacked
from torrentlinker.bbcode import bbcode_to_html
from torrentlinker.domain import ContentKind, ItemState, LocalItem
from torrentlinker.gui.errors import error_text, offer_whole_names
from torrentlinker.gui.library_model import human_size
from torrentlinker.gui.model_viewer import ModelPanel
from torrentlinker.gui.settings_dialog import kind_label
from torrentlinker.gui.tasks import run_in_background, run_with_progress
from torrentlinker.indexer import Candidate, Indexer
from torrentlinker.library import LibraryEntry
from torrentlinker.matching import IgnoreList
from torrentlinker.options import (
    Chosen,
    OptionType,
    category_options,
    fresh_options,
    options_body,
)
from torrentlinker.qbit import Qbit
from torrentlinker.review import CheckedCandidate
from torrentlinker.store import Store
from torrentlinker.upload import (
    PROFILES,
    Judgement,
    PreparedUpload,
    Problem,
    Refusal,
    UploadFile,
    UploadProfile,
    UploadRequest,
    UploadStopped,
    UploadWarning,
    category_name,
    create_upload,
    default_category,
    find_existing,
    missing_options,
    seed_upload,
    upload_files,
)

C411_UPLOAD_PAGE = "https://c411.org/upload"
IMAGE_MAX_BYTES = 10_000_000

# Subcategory labels, by c411 id, for every profile.
SUBCATEGORY_LABELS = {
    51: QT_TRANSLATE_NOOP("Subcategory", "Objects"),
    52: QT_TRANSLATE_NOOP("Subcategory", "Characters"),
    53: QT_TRANSLATE_NOOP("Subcategory", "Pack"),
    11: QT_TRANSLATE_NOOP("Subcategory", "Audiobooks"),
    12: QT_TRANSLATE_NOOP("Subcategory", "Comic strips (BD)"),
    13: QT_TRANSLATE_NOOP("Subcategory", "Comics"),
    14: QT_TRANSLATE_NOOP("Subcategory", "Books"),
    15: QT_TRANSLATE_NOOP("Subcategory", "Manga"),
    16: QT_TRANSLATE_NOOP("Subcategory", "Press"),
    59: QT_TRANSLATE_NOOP("Subcategory", "Sheet music & tablature"),
    60: QT_TRANSLATE_NOOP("Subcategory", "Journals & technical manuals"),
    1: QT_TRANSLATE_NOOP("Subcategory", "Animation"),
    2: QT_TRANSLATE_NOOP("Subcategory", "Animated series"),
    3: QT_TRANSLATE_NOOP("Subcategory", "Concert"),
    4: QT_TRANSLATE_NOOP("Subcategory", "Documentary"),
    57: QT_TRANSLATE_NOOP("Subcategory", "Documentary series"),
    5: QT_TRANSLATE_NOOP("Subcategory", "TV programme"),
    6: QT_TRANSLATE_NOOP("Subcategory", "Movie"),
    7: QT_TRANSLATE_NOOP("Subcategory", "TV series"),
    8: QT_TRANSLATE_NOOP("Subcategory", "Stage show"),
    9: QT_TRANSLATE_NOOP("Subcategory", "Sport"),
    10: QT_TRANSLATE_NOOP("Subcategory", "Music videos"),
    54: QT_TRANSLATE_NOOP("Subcategory", "Collection"),
    21: QT_TRANSLATE_NOOP("Subcategory", "Other"),
    22: QT_TRANSLATE_NOOP("Subcategory", "Training"),
    23: QT_TRANSLATE_NOOP("Subcategory", "Linux"),
    24: QT_TRANSLATE_NOOP("Subcategory", "macOS"),
    25: QT_TRANSLATE_NOOP("Subcategory", "Smartphone"),
    26: QT_TRANSLATE_NOOP("Subcategory", "Tablet"),
    27: QT_TRANSLATE_NOOP("Subcategory", "Windows"),
    28: QT_TRANSLATE_NOOP("Subcategory", "Other"),
    29: QT_TRANSLATE_NOOP("Subcategory", "Linux"),
    30: QT_TRANSLATE_NOOP("Subcategory", "macOS"),
    31: QT_TRANSLATE_NOOP("Subcategory", "Microsoft"),
    32: QT_TRANSLATE_NOOP("Subcategory", "Nintendo"),
    33: QT_TRANSLATE_NOOP("Subcategory", "Smartphone"),
    34: QT_TRANSLATE_NOOP("Subcategory", "Sony"),
    35: QT_TRANSLATE_NOOP("Subcategory", "Tablet"),
    36: QT_TRANSLATE_NOOP("Subcategory", "Windows"),
    55: QT_TRANSLATE_NOOP("Subcategory", "VR"),
    39: QT_TRANSLATE_NOOP("Subcategory", "Applications"),
    40: QT_TRANSLATE_NOOP("Subcategory", "Maps"),
    41: QT_TRANSLATE_NOOP("Subcategory", "Miscellaneous"),
    37: QT_TRANSLATE_NOOP("Subcategory", "Emulators"),
    38: QT_TRANSLATE_NOOP("Subcategory", "ROMs / ISOs"),
    17: QT_TRANSLATE_NOOP("Subcategory", "Karaoke"),
    18: QT_TRANSLATE_NOOP("Subcategory", "Music"),
    19: QT_TRANSLATE_NOOP("Subcategory", "Podcasts & radio"),
    20: QT_TRANSLATE_NOOP("Subcategory", "Samples"),
}


def refusal_text(r: Refusal) -> str:
    if r.problem is Problem.ARCHIVE:
        return QCoreApplication.translate(
            "Upload", "c411 refuses archives ({0}), and this one cannot be read"
        ).format(r.detail)
    if r.problem is Problem.OPTION_MISSING:
        return QCoreApplication.translate("Upload", "Choose a value for {0}").format(r.detail)
    if r.problem is Problem.NO_3D_FILE:
        return QCoreApplication.translate("Upload", "No 3D file (STL, 3MF, OBJ, STEP, GCODE…)")
    if r.problem is Problem.NO_EBOOK_FORMAT:
        return QCoreApplication.translate(
            "Upload",
            "No accepted format (PDF, EPUB, MOBI, DjVu, CBR, CBZ, JPG/PNG, MP3, M4A/M4B, FLAC)",
        )
    if r.problem is Problem.NO_AUDIO_FILE:
        return QCoreApplication.translate("Upload", "No audio file (FLAC, MP3, M4A, WAV, OGG…)")
    if r.problem is Problem.AUDIO_FORMAT:
        return QCoreApplication.translate(
            "Upload", "c411 does not accept these formats: {0}"
        ).format(r.detail)
    if r.problem is Problem.LOW_BITRATE:
        return QCoreApplication.translate("Upload", "Bitrate too low: {0}").format(r.detail)
    if r.problem is Problem.NEEDS_CUE:
        return QCoreApplication.translate("Upload", "A single-file album needs its .cue sheet")
    if r.problem is Problem.MIXED_AUDIO:
        return QCoreApplication.translate(
            "Upload", "One format and bitrate per album, found: {0}"
        ).format(r.detail)
    if r.problem is Problem.NO_MEDIAINFO:
        return QCoreApplication.translate(
            "Upload",
            "MediaInfo is not installed: install libmediainfo (for example the "
            "libmediainfo0v5 package) to upload videos",
        )
    if r.problem is Problem.NO_VIDEO_FILE:
        return QCoreApplication.translate("Upload", "No video file (MKV, MP4, M4V, AVI, TS, M2TS)")
    if r.problem is Problem.BAD_CONTAINER:
        return QCoreApplication.translate(
            "Upload", "c411 does not accept these containers: {0}"
        ).format(r.detail)
    if r.problem is Problem.GPU_ENCODER:
        return QCoreApplication.translate("Upload", "GPU encoders are forbidden ({0})").format(
            r.detail
        )
    if r.problem is Problem.LOW_VIDEO_BITRATE:
        return QCoreApplication.translate("Upload", "Video bitrate too low: {0}").format(r.detail)
    if r.problem is Problem.BANNED_TEAM:
        return QCoreApplication.translate("Upload", "Banned team or source: {0}").format(r.detail)
    if r.problem is Problem.NO_FRENCH:
        return QCoreApplication.translate(
            "Upload", "No French audio and no full French subtitles in {0}"
        ).format(r.detail)
    if r.problem is Problem.MIXED_PACK:
        return QCoreApplication.translate(
            "Upload",
            "The files of a pack must share their specs and their team; they differ in: {0}",
        ).format(r.detail)
    if r.problem is Problem.DOWNLOADER:
        return QCoreApplication.translate(
            "Upload", "Downloader executables are forbidden: {0}"
        ).format(r.detail)
    if r.problem is Problem.BIN_NO_CUE:
        return QCoreApplication.translate("Upload", "A .bin image needs its .cue sheet")
    if r.problem is Problem.CLONECD_INCOMPLETE:
        return QCoreApplication.translate("Upload", "A CloneCD image is missing: {0}").format(
            r.detail
        )
    if r.problem is Problem.PASSWORD_ARCHIVE:
        return QCoreApplication.translate("Upload", "Password-protected archives: {0}").format(
            r.detail
        )
    if r.problem is Problem.CONSOLE_CONTAINER:
        return QCoreApplication.translate(
            "Upload", "Files this console does not take (archives are fine, one per game): {0}"
        ).format(r.detail)
    if r.problem is Problem.FORBIDDEN_TOOL:
        return QCoreApplication.translate(
            "Upload", "Trainers, hack tools and hypervisor cracks are forbidden: {0}"
        ).format(r.detail)
    if r.problem is Problem.ISO_NOT_ALLOWED:
        return QCoreApplication.translate(
            "Upload",
            "An .iso is only allowed for a crack, repack or scene release: extract it first",
        )
    return QCoreApplication.translate("Upload", "No file to upload")


def warning_text(w: UploadWarning) -> str:
    if w.judgement is Judgement.PACK_THEME:
        return QCoreApplication.translate("Upload", "A pack must have one coherent theme")
    if w.judgement is Judgement.FRENCH_ONLY:
        return QCoreApplication.translate("Upload", "c411 accepts eBooks in French only")
    if w.judgement is Judgement.NO_DUPLICATE:
        return QCoreApplication.translate(
            "Upload", "Duplicates are strictly forbidden (another format is not one)"
        )
    if w.judgement is Judgement.FEW_FORMATS:
        return QCoreApplication.translate("Upload", "At most two or three formats of the same book")
    if w.judgement is Judgement.WHOLE_VOLUMES:
        return QCoreApplication.translate("Upload", "A pack must hold whole volumes")
    if w.judgement is Judgement.EVERY_VOLUME:
        return QCoreApplication.translate("Upload", "A BD pack must hold every volume")
    if w.judgement is Judgement.FRENCH_TITLE:
        if w.detail:
            return QCoreApplication.translate(
                "Upload", "The release title must be the French one: {0}"
            ).format(w.detail)
        return QCoreApplication.translate(
            "Upload",
            "The release title must be the French one (the original goes in the description)",
        )
    if w.judgement is Judgement.FORBIDDEN_SOURCE:
        return QCoreApplication.translate(
            "Upload",
            "Forbidden sources: CAM, TS, upscales, Plex transcodes, films still in cinemas",
        )
    if w.judgement is Judgement.INCOMPLETE_SEASON:
        return QCoreApplication.translate("Upload", "Incomplete season, missing: {0}").format(
            w.detail
        )
    if w.judgement is Judgement.WEB_PLATFORM:
        return QCoreApplication.translate(
            "Upload", "A WEB release must name its VOD platform in the description"
        )
    if w.judgement is Judgement.MICKEY_TAG:
        return QCoreApplication.translate(
            "Upload", "The MICKEY tag is a known detag: check the original release"
        )
    if w.judgement is Judgement.SLOTS:
        return QCoreApplication.translate(
            "Upload",
            "c411 keeps 28 slots per release: check the existing releases for a free one",
        )
    if w.judgement is Judgement.VERSION_ACTIVATION:
        return QCoreApplication.translate(
            "Upload", "State the version and how it is activated (NFO and description)"
        )
    if w.judgement is Judgement.NO_ALPHA:
        return QCoreApplication.translate("Upload", "No alpha or early-access versions")
    if w.judgement is Judgement.RETRO_ONLY:
        return QCoreApplication.translate(
            "Upload", "Only retro cartridge and floppy platforms, and arcade"
        )
    if w.judgement is Judgement.NO_MIXED_MACHINES:
        return QCoreApplication.translate(
            "Upload", "Do not mix machines in one pack (except MAME): {0}"
        ).format(w.detail)
    if w.judgement is Judgement.RELEASE_TYPE:
        return QCoreApplication.translate(
            "Upload", "Release type decided from the files: {0} (edit the name to change it)"
        ).format(w.detail)
    if w.judgement is Judgement.INSTALL_NOTE:
        return QCoreApplication.translate(
            "Upload", "An install note is mandatory unless the release is portable"
        )
    if w.judgement is Judgement.NO_IPTV:
        return QCoreApplication.translate("Upload", "No IPTV software")
    if w.judgement is Judgement.OLDER_VERSION:
        return QCoreApplication.translate(
            "Upload", "An older version of the same generation is removed when this one is accepted"
        )
    if w.judgement is Judgement.ONE_PER_RELEASE:
        return QCoreApplication.translate(
            "Upload",
            "One scene version, plus one repack with language or bonus options, one repacker "
            "release and one portable per scene release; a repack must be compressed and "
            "smaller than the scene release: this is {0}",
        ).format(w.detail)
    if w.judgement is Judgement.OFFICIAL_TRAINING:
        return QCoreApplication.translate(
            "Upload", "Official video trainings only (audio at 64 kbps or more)"
        )
    if w.judgement is Judgement.PLUGIN_HOST:
        return QCoreApplication.translate(
            "Upload",
            "A plugin or extension needs its host software on the tracker, compatible with "
            "that version, with a link to it in the description",
        )
    if w.judgement is Judgement.ORIGINAL_CRACK:
        return QCoreApplication.translate(
            "Upload", "Find the original crack and use the cracker's or repacker's own name"
        )
    if w.judgement is Judgement.UPDATE_ONLY:
        return QCoreApplication.translate(
            "Upload",
            "An update holds only the update files (not a new full pack), states the crack "
            "used, and is one per game version",
        )
    if w.judgement is Judgement.ONE_GOG:
        return QCoreApplication.translate("Upload", "One GOG version per game")
    if w.judgement is Judgement.ONE_PER_CONSOLE:
        return QCoreApplication.translate("Upload", "One version per console game")
    if w.judgement is Judgement.REGION:
        if w.detail:
            return QCoreApplication.translate(
                "Upload", "Region {0}: PAL/EU, NTSC/US, NTSC-J/JP or HK, one release each"
            ).format(w.detail)
        return QCoreApplication.translate(
            "Upload", "State the region: PAL/EU, NTSC/US, NTSC-J/JP or HK"
        )
    if w.judgement is Judgement.NO_TRANSCODE:
        return QCoreApplication.translate(
            "Upload", "No transcodes (MP3 to FLAC, 128 to 320 kbps, stereo to 5.1)"
        )
    if w.judgement is Judgement.SHORT_SINGLE:
        return QCoreApplication.translate("Upload", "Singles are accepted from 20 minutes only")
    if w.judgement is Judgement.DISCOGRAPHY:
        return QCoreApplication.translate(
            "Upload", "Discographies are accepted for inactive artists only"
        )
    if w.judgement is Judgement.CD_RIP_MISSING:
        return QCoreApplication.translate("Upload", "A CD-Rip needs: {0}").format(w.detail)
    if w.judgement is Judgement.CD_RIP_LINKS:
        return QCoreApplication.translate(
            "Upload",
            "A CD-Rip's description gives the catalogue number and a Discogs or MusicBrainz link",
        )
    return QCoreApplication.translate(
        "Upload", "c411 forbids files from independent creators who live off them"
    )


class UploadTab(QWidget):
    """Pick an Orphan with no Match, name and describe it by c411's rules, and save it as
    a Draft. An archive is unpacked first, into a new folder, if the user agrees."""

    upload_started = Signal(object)  # Path of the Local Item, now being verified
    unpacked = Signal(object)  # Path of the new folder: the Library needs a Scan

    def __init__(
        self,
        store: Store,
        indexer: Callable[[], Indexer],
        qbit: Callable[[], Qbit],
        ignore: Callable[[], IgnoreList],
        announce: Callable[[], str],
        folder: Path,
        http: httpx.Client | None = None,
    ) -> None:
        super().__init__()
        self.store = store
        self.indexer = indexer
        self.qbit = qbit
        self.ignore = ignore
        self.announce = announce
        self.folder = folder  # where the .torrent and .nfo files are kept
        self._http = http  # tests' own; otherwise one per image, through today's proxy
        self.entries: list[LibraryEntry] = []
        self.searched: dict[Path, list[CheckedCandidate]] = {}
        self.shown: list[LibraryEntry] = []
        self.entry: LibraryEntry | None = None
        self.unpack_target: Unpacked | None = None  # the selected archive, once unpacked
        self._listings: dict[Path, Unpacked | None] = {}  # archives read so far
        self._to_select: tuple[Path, Path] | None = None  # (new folder, its archive)
        self.files: list[UploadFile] = []
        self._picked: dict[Path, int] = {}  # the category the user chose, by Local Item
        self._existing: dict[tuple[Path, int], list[Candidate]] = {}  # searched this session
        self._searching: set[tuple[Path, int]] = set()
        self._edited: set[str] = set()  # name, nfo, description: left alone once edited
        self._stop = threading.Event()
        self._image_url = ""  # the URL whose image the preview shows
        self.option_types: list[OptionType] = []  # the subcategory's, once read
        self._option_widgets: dict[int, QComboBox | QListWidget] = {}
        self._picks: Chosen = {}  # what the user chose, which the profile's suggestion yields to
        self._options_for: int | None = None  # the subcategory whose options are awaited
        self._options_state = ""  # what the Options box says while no selector shows
        self._inspected: set[tuple[Path, int]] = set()  # items a profile has read, by category
        self._inspecting: set[tuple[Path, int]] = set()  # ... being read now

        layout = QVBoxLayout(self)
        self.notice = QLabel()
        self.notice.setWordWrap(True)
        layout.addWidget(self.notice)

        # Left: the Orphans
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        filters = QHBoxLayout()
        self.kind_filter = QComboBox()
        self.kind_filter.addItem(self.tr("All kinds"), None)
        for kind in ContentKind:
            self.kind_filter.addItem(kind_label(kind), kind)
        self.kind_filter.currentIndexChanged.connect(self._fill)
        self.show_all = QCheckBox(self.tr("Show all"))
        self.show_all.setToolTip(self.tr("Also show Orphans not searched yet or refused"))
        self.show_all.toggled.connect(self._fill)
        filters.addWidget(self.kind_filter, 1)
        filters.addWidget(self.show_all)
        left_layout.addLayout(filters)
        self.items = QTableWidget(0, 4)
        self.items.setHorizontalHeaderLabels(
            [self.tr("Local Item"), self.tr("Kind"), self.tr("Size"), self.tr("Status")]
        )
        self.items.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.items.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.items.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.items.verticalHeader().hide()
        header = self.items.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in (1, 2):
            header.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        header.resizeSection(3, 200)
        self.items.itemSelectionChanged.connect(self._item_selected)
        left_layout.addWidget(self.items)

        # Right: the release
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        form = QFormLayout()
        self.category = QComboBox()
        self.category.currentIndexChanged.connect(self._category_picked)
        self.source = QLineEdit()
        self.source.setPlaceholderText(self.tr("Where it comes from; empty for NOTAG"))
        self.source.textChanged.connect(self._regenerate)
        self.subcategory = QComboBox()
        self.subcategory.currentIndexChanged.connect(self._subcategory_changed)
        self.name = QLineEdit()
        self.name.textEdited.connect(lambda: self._edited.add("name"))
        self.name.textChanged.connect(self._name_changed)
        self.image_url = QLineEdit()
        self.image_url.setPlaceholderText(self.tr("https://… an image of it, required by c411"))
        self.image_url.textChanged.connect(self._image_changed)
        form.addRow(self.tr("Category"), self.category)
        form.addRow(self.tr("Source"), self.source)
        form.addRow(self.tr("Subcategory"), self.subcategory)
        form.addRow(self.tr("Release name"), self.name)
        form.addRow(self.tr("Image URL"), self.image_url)
        right_layout.addLayout(form)
        self.options_box = QGroupBox(self.tr("Options"))
        options_layout = QVBoxLayout(self.options_box)
        self.options_form = QFormLayout()
        options_layout.addLayout(self.options_form)
        status_row = QHBoxLayout()
        self.options_status = QLabel()
        self.options_status.setWordWrap(True)
        status_row.addWidget(self.options_status, 1)
        self.options_refresh = QPushButton(self.tr("Refresh options"))
        self.options_refresh.setToolTip(self.tr("Read this subcategory's options from c411 again"))
        self.options_refresh.clicked.connect(lambda: self._show_options(refresh=True))
        status_row.addWidget(self.options_refresh)
        options_layout.addLayout(status_row)
        right_layout.addWidget(self.options_box)
        self.problems = QLabel()
        self.problems.setWordWrap(True)
        self.problems.setStyleSheet("color: #c0392b")
        right_layout.addWidget(self.problems)
        self.warnings = QLabel()  # judgement rules: amber, the Draft can still be saved
        self.warnings.setWordWrap(True)
        self.warnings.setStyleSheet("color: #b9770e")
        right_layout.addWidget(self.warnings)

        # What c411 already has: information only, collapsible
        self.existing_box = QGroupBox()
        self.existing_box.setCheckable(True)
        self.existing_box.toggled.connect(self._existing_toggled)
        existing_layout = QVBoxLayout(self.existing_box)
        self.existing_body = QWidget()
        body_layout = QVBoxLayout(self.existing_body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        self.existing_status = QLabel()
        self.existing_status.setWordWrap(True)
        self.existing_view = QTextBrowser()
        self.existing_view.setOpenExternalLinks(True)
        self.existing_view.setMaximumHeight(120)
        body_layout.addWidget(self.existing_status)
        body_layout.addWidget(self.existing_view)
        existing_layout.addWidget(self.existing_body)
        right_layout.addWidget(self.existing_box)

        self.pages = QTabWidget()
        self.file_table = QTableWidget(0, 3)
        self.file_table.setHorizontalHeaderLabels(
            [self.tr("In the torrent"), self.tr("Your file"), self.tr("Size")]
        )
        self.file_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.file_table.verticalHeader().hide()
        fh = self.file_table.horizontalHeader()
        fh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        fh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        fh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.pages.addTab(self.file_table, self.tr("Files"))

        description_page = QWidget()
        dl = QVBoxLayout(description_page)
        dl.setContentsMargins(0, 0, 0, 0)
        split = QSplitter(Qt.Orientation.Horizontal)
        self.description = QPlainTextEdit()
        self.description.textChanged.connect(self._description_changed)
        self.preview = QTextBrowser()
        self.preview.setOpenExternalLinks(True)
        split.addWidget(self.description)
        split.addWidget(self.preview)
        dl.addWidget(split)
        reset_description = QPushButton(self.tr("Reset from the template"))
        reset_description.clicked.connect(lambda: self._reset("description"))
        dl.addWidget(reset_description, 0, Qt.AlignmentFlag.AlignRight)
        self.pages.addTab(description_page, self.tr("Description"))

        nfo_page = QWidget()
        nl = QVBoxLayout(nfo_page)
        nl.setContentsMargins(0, 0, 0, 0)
        self.nfo = QPlainTextEdit()
        self.nfo.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.nfo.setStyleSheet("font-family: monospace")
        self.nfo.textChanged.connect(lambda: self._edited.add("nfo"))
        nl.addWidget(self.nfo)
        reset_nfo = QPushButton(self.tr("Reset from the files"))
        reset_nfo.clicked.connect(lambda: self._reset("nfo"))
        nl.addWidget(reset_nfo, 0, Qt.AlignmentFlag.AlignRight)
        self.pages.addTab(nfo_page, self.tr("NFO"))

        image_page = QWidget()
        il = QVBoxLayout(image_page)
        self.image = QLabel(self.tr("Enter the image URL above"))
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setMinimumHeight(200)
        il.addWidget(self.image, 1)
        self.pages.addTab(image_page, self.tr("Image"))
        self.model_panel = ModelPanel(
            folder, lambda: self.name.text().strip(), self.ignore, self._image_is_sheet
        )
        self.model_tab = self.pages.addTab(self.model_panel, self.tr("3D view"))
        right_layout.addWidget(self.pages, 1)

        actions = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.hide()
        actions.addWidget(self.progress, 1)
        self.stop_button = QPushButton(self.tr("Stop"))
        self.stop_button.clicked.connect(self._stop.set)
        self.stop_button.hide()
        actions.addWidget(self.stop_button)
        actions.addStretch()
        self.create_button = QPushButton()
        self.create_button.clicked.connect(self.create_draft)
        actions.addWidget(self.create_button)
        right_layout.addLayout(actions)

        main = QSplitter(Qt.Orientation.Horizontal)
        main.addWidget(left)
        main.addWidget(right)
        main.setSizes([450, 750])
        layout.addWidget(main, 1)

        drafts_box = QGroupBox(self.tr("Your c411 Drafts"))
        drafts_layout = QVBoxLayout(drafts_box)
        self.drafts = QTableWidget(0, 3)
        self.drafts.setHorizontalHeaderLabels(
            [self.tr("Draft"), self.tr("Category"), self.tr("Modified")]
        )
        self.drafts.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.drafts.verticalHeader().hide()
        self.drafts.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.drafts.setMaximumHeight(120)
        drafts_layout.addWidget(self.drafts)
        row = QHBoxLayout()
        self.drafts_status = QLabel()
        row.addWidget(self.drafts_status, 1)
        refresh = QPushButton(self.tr("Refresh"))
        refresh.clicked.connect(self.refresh_drafts)
        row.addWidget(refresh)
        open_page = QPushButton(self.tr("Open c411's upload page"))
        open_page.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(C411_UPLOAD_PAGE)))
        row.addWidget(open_page)
        drafts_layout.addLayout(row)
        layout.addWidget(drafts_box)

        self._image_timer = QTimer(self)
        self._image_timer.setSingleShot(True)
        self._image_timer.setInterval(600)
        self._image_timer.timeout.connect(self._load_image)
        self._fill()
        self._show_entry()

    # The Library -----------------------------------------------------------

    def set_entries(self, entries: list[LibraryEntry]) -> None:
        self.entries = entries
        if self._to_select is not None:
            folder, archive = self._to_select
            if any(e.item.path == folder for e in entries):
                # Searching the archive compared its contents too (ADR-0007).
                if archive in self.searched:
                    self.searched[folder] = self.searched[archive]
                self._to_select = None
                self._fill()
                self.select(folder)
                return
        self._fill()

    def remember(self, entry: LibraryEntry, checked: list[CheckedCandidate]) -> None:
        """An Orphan's latest search, from the Library."""
        self.searched[entry.item.path] = checked
        self._fill()

    def select(self, path: Path) -> None:
        """Show the Upload form for this Local Item, even if the filters hid it."""
        if all(e.item.path != path for e in self.shown):
            self.kind_filter.setCurrentIndex(0)
            self.show_all.setChecked(True)
        for r, e in enumerate(self.shown):
            if e.item.path == path:
                self.items.selectRow(r)
                return

    def candidates(self) -> list[LibraryEntry]:
        """Every Orphan; only some may become Uploads (see why_not)."""
        return [e for e in self.entries if e.state is ItemState.ORPHAN]

    def needs_unpacking(self, entry: LibraryEntry) -> bool:
        """An archive whose only fault is being one: unpacked, it may become an Upload."""
        profile = self._profile_of(entry)
        if profile is None or not is_archive(entry.item):
            return False
        found = profile.refusals(entry.item, self.ignore(), self._subcategory_of(entry))
        return bool(found) and all(r.problem is not Problem.NO_FILE for r in found)

    def why_not(self, entry: LibraryEntry) -> str | None:
        """Why this Orphan cannot be uploaded now; None when it can, an archive included
        (it is unpacked first)."""
        category = self._category_of(entry)
        if category is None:
            return self.tr("Choose a category")
        profile = PROFILES.get(category)
        if profile is None:
            return self.tr("Uploads to {0} are not supported yet").format(category_name(category))
        checked = self.searched.get(entry.item.path)
        if checked is None:
            return self.tr("Search it first: c411 may already have it")
        if any(v.match for v in checked):
            return self.tr("c411 already has it: Reseed it from the Library")
        if self.needs_unpacking(entry):
            return None
        if found := profile.refusals(entry.item, self.ignore(), self._subcategory_of(entry)):
            return "; ".join(refusal_text(r) for r in found)
        return None

    def _subcategory_of(self, entry: LibraryEntry) -> int | None:
        """The subcategory the form shows for the selected item; the list knows none."""
        return self.subcategory.currentData() if entry is self.entry else None

    def _fill(self) -> None:
        selected = self.entry.item.path if self.entry else None
        kind = self.kind_filter.currentData()
        everything = self.show_all.isChecked()
        rows = []
        for e in self.candidates():
            if kind is not None and e.folder.kind is not kind:
                continue
            reason = self.why_not(e)
            if reason and not everything:
                continue
            rows.append((reason is not None, e.item.path.name.casefold(), e, reason))
        rows.sort(key=lambda r: (r[0], r[1]))
        self.shown = [e for _, _, e, _ in rows]
        self.items.blockSignals(True)
        self.items.setRowCount(len(rows))
        for r, (_, _, e, reason) in enumerate(rows):
            status = reason or (
                self.tr("Archive: unpack it to upload")
                if self.needs_unpacking(e)
                else self.tr("Ready")
            )
            cells = [e.item.path.name, kind_label(e.folder.kind), human_size(e.item.size), status]
            for c, text in enumerate(cells):
                cell = QTableWidgetItem(text)
                cell.setToolTip(text)
                if reason:
                    cell.setForeground(Qt.GlobalColor.gray)
                self.items.setItem(r, c, cell)
        self.items.blockSignals(False)
        if selected is not None and selected not in {e.item.path for e in self.shown}:
            self.entry = None
            self._show_entry()
        for r, e in enumerate(self.shown):
            if e.item.path == selected:
                self.items.selectRow(r)
        hidden = len(self.candidates()) - len(self.shown)
        if not self.announce():
            self.notice.setText(
                self.tr("Enter your Announce URL in Settings → Connections to make Uploads.")
            )
        elif not self.shown and not everything:
            self.notice.setText(
                self.tr(
                    "No Orphan is ready to upload. Search your Orphans in the Library, or "
                    "tick Show all to pick a category and see why the {0} others are not "
                    "ready."
                ).format(hidden)
            )
        else:
            self.notice.setText(
                self.tr(
                    "Orphans that a search found no Match for. Each Upload is saved as a "
                    "Draft on c411, where you publish it."
                )
            )
        self._update_actions()

    # The release -----------------------------------------------------------

    def _category_of(self, entry: LibraryEntry) -> int | None:
        """The user's pick, else what the Library Folder's Content Kind proposes."""
        return self._picked.get(entry.item.path, default_category(entry.folder.kind))

    def _profile_of(self, entry: LibraryEntry) -> UploadProfile | None:
        category = self._category_of(entry)
        return PROFILES.get(category) if category is not None else None

    def profile(self) -> UploadProfile | None:
        return self._profile_of(self.entry) if self.entry else None

    def _fill_categories(self) -> None:
        """The picker lists every profile; a category proposed but not supported yet
        shows first, so the picker never says otherwise than the status."""
        self.category.blockSignals(True)
        self.category.clear()
        current = self._category_of(self.entry) if self.entry else None
        if current not in PROFILES:
            self.category.addItem(
                category_name(current) if current is not None else self.tr("Choose a category"),
                current,
            )
        for category in PROFILES:
            self.category.addItem(category_name(category), category)
        self.category.setCurrentIndex(self.category.findData(current))
        self.category.blockSignals(False)
        self.category.setEnabled(self.entry is not None)

    def _category_picked(self) -> None:
        """Another category is another profile: its refusals, subcategories and texts."""
        category = self.category.currentData()
        if self.entry is None or category is None:
            return
        self._picked[self.entry.item.path] = category
        self._show_entry()
        self._fill()

    def source_item(self) -> LocalItem | None:
        """What the Upload is made of: the selected item, or the archive as unpacked."""
        if self.entry is None:
            return None
        if self.needs_unpacking(self.entry):
            return self.unpack_target.item if self.unpack_target else None
        return self.entry.item

    def _item_selected(self) -> None:
        rows = self.items.selectionModel().selectedRows()
        entry = self.shown[rows[0].row()] if rows else None
        if entry is self.entry:
            return
        self.entry = entry
        self._show_entry()

    def _show_entry(self) -> None:
        self._edited.clear()
        self._picks = {}
        self.unpack_target = None
        entry, profile = self.entry, self.profile()
        if entry is not None and self.needs_unpacking(entry):
            self._read_archive(entry)
        self._fill_categories()
        self.subcategory.blockSignals(True)
        self.subcategory.clear()
        if profile is not None:
            for sub in profile.subcategories:
                label = SUBCATEGORY_LABELS.get(sub.id, sub.label)
                self.subcategory.addItem(
                    QCoreApplication.translate("Subcategory", str(label)), sub.id
                )
        self.subcategory.blockSignals(False)
        self._choose_subcategory()
        for field in (self.source, self.name, self.image_url, self.subcategory):
            field.setEnabled(profile is not None)
        self._show_options()
        self._regenerate()
        self._inspect()
        self._show_existing()
        self._show_model()

    def _inspect(self) -> None:
        """Let the profile read what the files say (tags, MediaInfo) off the GUI thread,
        then redo what depends on it. An archive not yet unpacked has nothing to read."""
        profile, item = self.profile(), self.source_item()
        if profile is None or item is None or not item.path.exists():
            return
        key = (item.path, profile.category)
        if key in self._inspected:
            return
        self._inspected.add(key)
        self._inspecting.add(key)
        ignore = self.ignore()

        def current() -> bool:
            return isValid(self) and self.source_item() is item and self.profile() is profile

        def done(_: object) -> None:
            self._inspecting.discard(key)
            if current():
                self._show_options()
                self._regenerate()
                self._show_existing()  # the profile may now look an item up by ids

        def failed(error: Exception) -> None:
            self._inspected.discard(key)  # selecting the item again retries
            self._inspecting.discard(key)
            if current():
                self._show_existing()

        run_in_background(lambda: profile.inspect(item, ignore), done, failed)

    def _subcategory_changed(self) -> None:
        """Another subcategory has other options, and the old picks do not apply."""
        self._picks = {}
        self._show_options()
        self._regenerate()
        self._show_existing()

    # What c411 already has ---------------------------------------------------

    def _existing_toggled(self, expanded: bool) -> None:
        self.existing_body.setVisible(expanded)

    def _show_existing(self) -> None:
        """List the releases c411 already has of the selected item: one search per item
        and category, off the GUI thread, kept for the session."""
        entry, profile = self.entry, self.profile()
        if entry is None or profile is None:
            self.existing_box.hide()
            return
        self.existing_box.show()
        key = (entry.item.path, profile.category)
        if key in self._existing:
            self._render_existing(self._existing[key])
            return
        self._render_existing(None)
        if key in self._searching or key in self._inspecting:
            return  # an inspection first: its answers may give the search ids
        self._searching.add(key)
        query = profile.existing_query(entry.item, self.ignore())
        indexer = self.indexer()
        search, by_ids = indexer.search, indexer.by_tmdb

        def current() -> bool:
            return (
                self.entry is not None
                and self.entry.item.path == key[0]
                and ((p := self.profile()) is not None and p.category == key[1])
            )

        def done(found: list[Candidate]) -> None:
            self._searching.discard(key)
            self._existing[key] = found
            if isValid(self) and current():
                self._render_existing(found)

        def failed(error: Exception) -> None:
            self._searching.discard(key)  # not kept: selecting the item again retries
            if isValid(self) and current():
                self._render_existing(None, error_text(error))

        run_in_background(lambda: find_existing(search, query, key[1], by_ids), done, failed)

    def _render_existing(self, found: list[Candidate] | None, error: str = "") -> None:
        """`found` None: still searching, or failed with `error`."""
        title = self.tr("Already on c411")
        self.existing_view.hide()
        if found is None:
            self.existing_box.setTitle(title)
            self.existing_status.setText(
                self.tr("c411 could not be searched: {0}").format(error)
                if error
                else self.tr("Searching c411…")
            )
            return
        if not found:
            self.existing_box.setTitle(title)
            self.existing_status.setText(self.tr("Nothing found on c411."))
            return
        self.existing_box.setTitle(f"{title} ({len(found)})")
        self.existing_status.setText(
            self.tr("Releases c411 already has, for information: Team Pending refuses duplicates.")
        )
        seeders = self.tr("seeders")
        rows = "".join(
            "<li>"
            + (
                f'<a href="{html.escape(c.details_url, quote=True)}">{html.escape(c.title)}</a>'
                if c.details_url.startswith(("https://", "http://"))
                else html.escape(c.title)
            )
            + f" — {human_size(c.size)}, {c.seeders} {html.escape(seeders)}</li>"
            for c in found
        )
        self.existing_view.setHtml(f"<ul>{rows}</ul>")
        self.existing_view.show()

    def _image_is_sheet(self) -> bool:
        profile = self.profile()
        return profile is not None and profile.image_is_sheet(self.subcategory.currentData())

    def _show_model(self) -> None:
        """The 3D page follows the selection; an archive's models are not on disk yet."""
        profile, entry = self.profile(), self.entry
        shown = profile is not None and profile.renders_models
        self.pages.setTabVisible(self.model_tab, shown)
        usable = entry is not None and shown and not self.needs_unpacking(entry)
        self.model_panel.set_item(entry.item if usable and entry else None)

    def _choose_subcategory(self) -> None:
        profile, item = self.profile(), self.source_item()
        if profile is not None and item is not None:
            default = profile.default_subcategory(item, self.ignore())
            self.subcategory.blockSignals(True)
            self.subcategory.setCurrentIndex(self.subcategory.findData(default))
            self.subcategory.blockSignals(False)

    def _read_archive(self, entry: LibraryEntry) -> None:
        """List the archive off the GUI thread; 7-Zip may take a moment."""
        path = entry.item.path
        if path in self._listings:
            self.unpack_target = self._listings[path]
            return
        self.problems.setText(self.tr("Reading the archive…"))

        def done(target: Unpacked | None) -> None:
            self._listings[path] = target
            if self.entry is not None and self.entry.item.path == path:
                self.unpack_target = target
                self._choose_subcategory()
                self._show_options()  # the profile may suggest from the unpacked files
                self._regenerate()

        run_in_background(lambda: unpacked(entry.item), done, lambda e: done(None))

    # Category Options ------------------------------------------------------

    def chosen_options(self) -> Chosen:
        """The values the selectors show, by option type id."""
        chosen: Chosen = {}
        for option_id, widget in self._option_widgets.items():
            if isinstance(widget, QListWidget):
                chosen[option_id] = [
                    widget.item(r).data(Qt.ItemDataRole.UserRole)
                    for r in range(widget.count())
                    if widget.item(r).checkState() == Qt.CheckState.Checked
                ]
            else:
                value = widget.currentData()
                chosen[option_id] = [] if value is None else [value]
        return chosen

    def missing_options(self) -> list[Refusal]:
        return missing_options(self.option_types, self.chosen_options())

    def _show_options(self, refresh: bool = False) -> None:
        """Show the selectors of the chosen subcategory: from the store when kept for less
        than a week, else read from c411 off the GUI thread."""
        subcategory = self.subcategory.currentData()
        self._options_for = subcategory
        self._clear_options()
        if self.profile() is None or subcategory is None:
            self._set_options_state("")
            return
        if not refresh and (kept := fresh_options(self.store, subcategory)) is not None:
            self._options_read(subcategory, kept)
            return
        self._set_options_state(self.tr("Reading the options…"))
        try:
            fetch = self.indexer().category_options
        except Exception as e:  # noqa: BLE001 - shown where the options would be
            self._options_failed(subcategory, e)
            return
        store = self.store
        run_in_background(
            lambda: category_options(store, fetch, subcategory, refresh=refresh),
            lambda types: self._options_read(subcategory, types),
            lambda e: self._options_failed(subcategory, e),
        )

    def _clear_options(self) -> None:
        self.option_types = []
        self._option_widgets = {}
        while self.options_form.rowCount():
            self.options_form.removeRow(0)

    def _set_options_state(self, text: str) -> None:
        """Say why no selector shows (reading, failed), or hide the box when there are
        none to show."""
        self._options_state = text
        self.options_status.setText(text)
        self.options_refresh.setVisible(bool(text) and text != self.tr("Reading the options…"))
        self.options_box.setVisible(bool(text) or bool(self.option_types))
        self._name_changed()

    def _options_failed(self, subcategory: int, error: Exception) -> None:
        if not isValid(self) or subcategory != self._options_for:
            return
        self._clear_options()
        self._set_options_state(
            self.tr("Could not read the options: {0}").format(error_text(error))
        )

    def _options_read(self, subcategory: int, types: list[OptionType]) -> None:
        if not isValid(self) or subcategory != self._options_for:
            return  # the tab is gone, or another subcategory was chosen meanwhile
        self._clear_options()
        self.option_types = types
        item, profile = self.source_item(), self.profile()
        suggested = (
            profile.suggested_options(item, self.ignore(), types) if profile and item else {}
        )
        wanted = {**suggested, **self._picks}
        for t in types:
            label = f"{t.name} *" if t.required else t.name
            widget: QComboBox | QListWidget
            if t.multiple:
                widget = QListWidget()
                widget.setMaximumHeight(110)
                for v in t.values:
                    entry = QListWidgetItem(v.label)
                    entry.setData(Qt.ItemDataRole.UserRole, v.id)
                    entry.setFlags(entry.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    on = v.id in wanted.get(t.id, [])
                    entry.setCheckState(Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
                    widget.addItem(entry)
                widget.itemChanged.connect(lambda _item, o=t.id: self._option_picked(o))
            else:
                widget = QComboBox()
                widget.addItem("—", None)
                for v in t.values:
                    widget.addItem(v.label, v.id)
                first = next(iter(wanted.get(t.id, [])), None)
                widget.setCurrentIndex(max(widget.findData(first), 0))
                widget.currentIndexChanged.connect(lambda _i, o=t.id: self._option_picked(o))
            if t.required:
                widget.setToolTip(self.tr("c411 requires this one"))
            self._option_widgets[t.id] = widget
            self.options_form.addRow(label, widget)
        self._set_options_state("")

    def _option_picked(self, option_id: int) -> None:
        """The user's choice for this option wins over the profile's suggestion."""
        self._picks[option_id] = self.chosen_options()[option_id]
        self._name_changed()

    def _regenerate(self) -> None:
        """Fill what the user has not edited from the profile: name, NFO, description."""
        profile, item = self.profile(), self.source_item()
        if profile is None or item is None:
            if "name" not in self._edited:
                self.name.clear()
            self._name_changed()
            return
        name = profile.suggested_name(
            item, self.ignore(), self.source.text(), self.subcategory.currentData()
        )
        if "name" not in self._edited and name != self.name.text():
            self.name.setText(name)  # which recomputes the rest
        else:
            self._name_changed()

    def _name_changed(self) -> None:
        profile, entry, item = self.profile(), self.entry, self.source_item()
        title = self.name.text().strip()
        problems = [self.why_not(entry)] if entry else []
        if entry is not None and self.needs_unpacking(entry):
            if entry.item.path not in self._listings:
                problems.append(self.tr("Reading the archive…"))
            elif self.unpack_target is None:
                problems.append(self.tr("This archive cannot be read: install 7-Zip to unpack it."))
            else:
                problems.append(
                    self.tr(
                        "c411 refuses archives: it will be unpacked into {0}, next to it."
                    ).format(self.unpack_target.item.path)
                )
        self.files = []
        if profile is not None and item is not None and title:
            if found := profile.refusals(item, self.ignore(), self.subcategory.currentData()):
                problems += [refusal_text(r) for r in found]
            if profile.dotted_names and (" " in title or not title.isascii()):
                problems.append(
                    self.tr("A release name has dots between words, no spaces and no accents.")
                )
            try:
                self.files = upload_files(item, title, self.ignore(), profile.media_extensions)
            except ValueError as e:
                problems.append(str(e))
        if entry is not None and profile is not None:
            if self._options_state:
                problems.append(self._options_state)
            problems += [refusal_text(r) for r in self.missing_options()]
        self.problems.setText("\n".join(p for p in problems if p))
        judged = (
            profile.warnings(item, self.ignore(), self.subcategory.currentData())
            if profile is not None and item is not None and title
            else []
        )
        self.warnings.setText("\n".join(warning_text(w) for w in judged))
        self._show_files()
        self.model_panel.refresh()
        if profile is not None and self.files:
            if "nfo" not in self._edited:
                self._set_text(self.nfo, profile.nfo(title, self.files))
            if "description" not in self._edited:
                self._set_text(self.description, self._template())
        elif not self.files:
            self._set_text(self.nfo, "")
            self._set_text(self.description, "")
        self._update_actions()

    def _template(self) -> str:
        profile = self.profile()
        if profile is None or not self.files:
            return ""
        return profile.description(
            self.name.text().strip(),
            self.files,
            self.source.text().strip(),
            self.image_url.text().strip(),
        )

    def _show_files(self) -> None:
        self.file_table.setRowCount(len(self.files))
        for r, f in enumerate(self.files):
            for c, text in enumerate([f.torrent_path, f.local_path, human_size(f.size)]):
                self.file_table.setItem(r, c, QTableWidgetItem(text))
        self.pages.setTabText(0, self.tr("Files ({0})").format(len(self.files)))

    def _set_text(self, editor: QPlainTextEdit, text: str) -> None:
        editor.blockSignals(True)
        editor.setPlainText(text)
        editor.blockSignals(False)
        if editor is self.description:
            self._render_description()

    def _description_changed(self) -> None:
        self._edited.add("description")
        self._render_description()

    def _render_description(self) -> None:
        self.preview.setHtml(bbcode_to_html(self.description.toPlainText()))

    def _reset(self, what: str) -> None:
        self._edited.discard(what)
        self._name_changed()

    # The image -------------------------------------------------------------

    def _image_changed(self) -> None:
        if "description" not in self._edited:
            self._set_text(self.description, self._template())
        self._image_timer.start()

    def _load_image(self) -> None:
        url = self.image_url.text().strip()
        self._image_url = url
        if not url.startswith(("https://", "http://")):
            self.image.setPixmap(QPixmap())
            self.image.setText(self.tr("Enter the image URL above") if not url else url)
            return
        self.image.setText(self.tr("Loading the image…"))
        http = self._http or net.client(timeout=20, follow_redirects=True)

        def fetch() -> bytes:
            with http.stream("GET", url) as r:
                r.raise_for_status()
                data = b""
                for chunk in r.iter_bytes():
                    data += chunk
                    if len(data) > IMAGE_MAX_BYTES:
                        raise ValueError("image larger than 10 Mo")
                return data

        run_in_background(
            fetch, lambda data: self._image_loaded(url, data), lambda e: self._image_failed(url, e)
        )

    def _image_loaded(self, url: str, data: bytes) -> None:
        if url != self._image_url:
            return
        image = QImage.fromData(data)
        if image.isNull():
            self._image_failed(url, ValueError(self.tr("not an image")))
            return
        self.image.setPixmap(
            QPixmap.fromImage(image).scaled(
                480,
                360,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        self.preview.document().addResource(
            QTextDocument.ResourceType.ImageResource, QUrl(url), image
        )
        self._render_description()

    def _image_failed(self, url: str, error: Exception) -> None:
        if url == self._image_url:
            self.image.setPixmap(QPixmap())
            self.image.setText(self.tr("Could not load the image: {0}").format(error_text(error)))

    # Making the Upload -----------------------------------------------------

    def _update_actions(self) -> None:
        entry, profile = self.entry, self.profile()
        archive = entry is not None and self.needs_unpacking(entry)
        self.create_button.setText(self.tr("Unpack…") if archive else self.tr("Create Draft"))
        self.create_button.setToolTip(
            self.tr("Unpack the archive into a new folder next to it, then prepare its Upload")
            if archive
            else self.tr(
                "Make the torrent, save it with the NFO and description as a Draft on c411, "
                "then seed from your files. You publish it on c411."
            )
        )
        title = self.name.text().strip()
        ready = (
            entry is not None
            and self.why_not(entry) is None
            and bool(self.files)
            and (
                profile is None
                or not profile.dotted_names
                or (" " not in title and title.isascii())
            )
            and bool(self.nfo.toPlainText().strip())
            and bool(self.announce())
            and not self._options_state
            and not self.missing_options()
            and not self.progress.isVisible()
        )
        self.create_button.setEnabled(ready)

    def create_draft(self) -> None:
        entry, profile = self.entry, self.profile()
        if entry is None or profile is None or not self.files:
            return
        if self.needs_unpacking(entry):
            self._unpack(entry)
            return
        if not self.image_url.text().strip():
            answer = QMessageBox.question(
                self,
                self.tr("No image"),
                self.tr(
                    "c411 requires an image in the description. Save the Draft anyway and add "
                    "the image on c411 before publishing?"
                ),
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        request = UploadRequest(
            entry.item,
            self.name.text().strip(),
            self.files,
            self.nfo.toPlainText(),
            self.description.toPlainText(),
            profile.category,
            self.subcategory.currentData(),
            options_body(self.option_types, self.chosen_options()),
            profile.draft_fields(entry.item, self.ignore(), self.files),
        )
        store, announce, indexer, folder, stop = (
            self.store,
            self.announce(),
            self.indexer(),
            self.folder,
            self._stop,
        )
        self._start_progress()

        def work(report: Callable[[object], None]) -> PreparedUpload:
            return create_upload(
                request,
                announce,
                folder,
                indexer.save_draft,
                store,
                report=lambda done, total: report((done, total)),
                stopped=stop.is_set,
            )

        run_with_progress(
            work, self._progressed, lambda prepared: self._drafted(entry, prepared), self._failed
        )

    def _start_progress(self) -> None:
        self._stop.clear()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.show()
        self.stop_button.show()
        self._update_actions()

    def _progressed(self, value: tuple[int, int]) -> None:
        done, total = value
        self.progress.setValue(int(100 * done / total) if total else 100)

    # Archives --------------------------------------------------------------

    def _unpack(self, entry: LibraryEntry) -> None:
        target = self.unpack_target
        if target is None:
            return
        folder = target.item.path
        if folder.exists():
            QMessageBox.information(
                self,
                self.tr("Unpack"),
                self.tr(
                    "{0} already exists. If it holds this archive unpacked, scan the Library "
                    "and pick that folder."
                ).format(folder),
            )
            return
        free = shutil.disk_usage(target.archive.parent).free
        if free < target.size:
            QMessageBox.warning(
                self,
                self.tr("Unpack"),
                self.tr("Unpacking needs {0}, but only {1} is free on that disk.").format(
                    human_size(target.size), human_size(free)
                ),
            )
            return
        answer = QMessageBox.question(
            self,
            self.tr("Unpack"),
            self.tr(
                "c411 refuses archives. Unpack {0} into the new folder\n{1}?\n\n"
                "It writes {2} in {3} files; {4} is free on that disk. Nothing is "
                "overwritten. The Upload is then made from the unpacked files; once it seeds, "
                "you are offered to move the archive to the trash."
            ).format(
                target.archive.name,
                folder,
                human_size(target.size),
                len(target.item.files),
                human_size(free),
            ),
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._start_progress()
        self.stop_button.hide()  # unpacking runs to the end, or undoes itself on failure
        store = self.store

        def work(report: Callable[[object], None]) -> Path:
            unpack(target, lambda done, total: report((done, total)))
            store.remember_unpacked(folder, target.archive)
            return folder

        run_with_progress(
            work, self._progressed, lambda f: self._unpacked(f, entry.item.path), self._failed
        )

    def _unpacked(self, folder: Path, archive: Path) -> None:
        self._done()
        self._to_select = (folder, archive)
        self.unpacked.emit(folder)

    # Seeding ---------------------------------------------------------------

    def _drafted(self, entry: LibraryEntry, prepared: PreparedUpload) -> None:
        self.progress.setRange(0, 0)
        self.stop_button.hide()
        self.refresh_drafts()
        self._seed(entry, prepared)

    def _seed(self, entry: LibraryEntry, prepared: PreparedUpload) -> None:
        qbit, store = self.qbit(), self.store
        run_in_background(
            lambda: seed_upload(qbit, store, entry.item, prepared),
            lambda _hash: self._seeding(entry, prepared),
            lambda e: self._seed_failed(entry, prepared, e),
        )

    def _seeding(self, entry: LibraryEntry, prepared: PreparedUpload) -> None:
        self._done()
        self.upload_started.emit(entry.item.path)
        QMessageBox.information(
            self,
            self.tr("Draft saved"),
            self.tr(
                "{0} is saved as a Draft on c411 and is being verified in your torrent "
                "client. Once it seeds, open c411's upload page, load the Draft, check it and "
                "publish it."
            ).format(prepared.saved.title),
        )

    def _seed_failed(self, entry: LibraryEntry, prepared: PreparedUpload, error: Exception) -> None:
        self._done()
        if offer_whole_names(self, error, then=lambda: self._seed(entry, prepared)):
            return
        QMessageBox.warning(
            self,
            self.tr("Not seeding"),
            self.tr(
                "The Draft is saved on c411, but its torrent could not be added to your "
                "torrent client: {0}\n\nc411 refuses an upload whose uploader is not "
                "seeding: do not publish it before it seeds."
            ).format(error_text(error)),
        )

    def _failed(self, error: Exception) -> None:
        self._done()
        if isinstance(error, UploadStopped):
            return
        QMessageBox.warning(self, self.tr("Upload failed"), error_text(error))

    def _done(self) -> None:
        self.progress.hide()
        self.stop_button.hide()
        self._update_actions()

    # Drafts ----------------------------------------------------------------

    def refresh_drafts(self) -> None:
        if not self.announce():
            return
        indexer = self.indexer()
        self.drafts_status.setText(self.tr("Reading your Drafts…"))
        run_in_background(indexer.drafts, self._show_drafts, self._drafts_failed)

    def _show_drafts(self, drafts: list[dict[str, object]]) -> None:
        self.drafts.setRowCount(len(drafts))
        for r, d in enumerate(drafts):
            category = d.get("subcategory") or d.get("category") or ""
            if isinstance(category, dict):
                category = category.get("name", "")
            modified = str(d.get("updatedAt") or "")[:16].replace("T", " ")
            for c, text in enumerate([str(d.get("name") or ""), str(category), modified]):
                self.drafts.setItem(r, c, QTableWidgetItem(text))
        self.drafts_status.setText(self.tr("{0}/15 Drafts on c411").format(len(drafts)))

    def _drafts_failed(self, error: Exception) -> None:
        self.drafts_status.setText(error_text(error))
