"""Native media browsing and playback, backed by the shared saved inventory."""

from __future__ import annotations

import random
import re
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import (
    QEvent,
    QFile,
    QIODevice,
    QRectF,
    QSettings,
    QSignalBlocker,
    QSize,
    Qt,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QFont,
    QIcon,
    QImage,
    QImageReader,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPalette,
    QPixmap,
)
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QAbstractItemView,
    QBoxLayout,
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSlider,
    QSplitter,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from torrentlinker.gui.tasks import run_in_background


class VerifiedPrefixDevice(QIODevice):
    """A read-only, seekable view of a fixed verified prefix, never of missing pieces."""

    def __init__(self, path, verified_bytes: int, parent=None) -> None:
        super().__init__(parent)
        self.file = QFile(str(path))
        self.limit = int(verified_bytes)
        if not self.file.open(QIODevice.OpenModeFlag.ReadOnly):
            raise ValueError("The preview file cannot be opened read-only.")
        if not 0 < self.limit <= self.file.size():
            self.file.close()
            raise ValueError("The verified preview range is no longer available.")
        self.open(QIODevice.OpenModeFlag.ReadOnly | QIODevice.OpenModeFlag.Unbuffered)

    def isSequential(self) -> bool:
        return False

    def size(self) -> int:
        return self.limit

    def seek(self, position: int) -> bool:
        if position < 0 or position > self.limit:
            return False
        return self.file.seek(position) and super().seek(position)

    def bytesAvailable(self) -> int:
        return max(0, self.limit - self.pos())

    def atEnd(self) -> bool:
        return self.pos() >= self.limit

    def readData(self, maximum: int) -> bytes:
        remaining = self.limit - self.file.pos()
        return bytes(self.file.read(min(max(0, maximum), max(0, remaining))).data())

    def writeData(self, _data: bytes | bytearray | memoryview, _length: int) -> int:
        return -1

    def close(self) -> None:
        super().close()
        self.file.close()


class MediaTileButton(QPushButton):
    def sizeHint(self):
        return self.layout().sizeHint() if self.layout() else super().sizeHint()

    def minimumSizeHint(self):
        return self.layout().minimumSize() if self.layout() else super().minimumSizeHint()


class MediaHero(QWidget):
    """Artwork stays behind a readable, native title and action composition."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.picture = QImage()
        self.mode = "cinematic"
        self.setObjectName("mediaHero")
        self.setMinimumHeight(440)
        self.box = QHBoxLayout(self)
        self.box.setContentsMargins(34, 34, 34, 34)
        self.box.setSpacing(28)
        self.copy = QWidget()
        self.copy.setMaximumWidth(620)
        text = QVBoxLayout(self.copy)
        text.setContentsMargins(0, 0, 0, 0)
        text.addStretch()
        self.kicker = QLabel(self.tr("FROM YOUR LIBRARY FOLDERS"))
        self.kicker.setStyleSheet("color: #85d8cb; font-size: 10px; letter-spacing: 2px;")
        text.addWidget(self.kicker)
        self.title = QLabel()
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        self.title.setWordWrap(True)
        self.title.setStyleSheet("font-size: 48px; font-weight: 750; color: #f3f4ef;")
        text.addWidget(self.title)
        self.metadata = QLabel()
        self.metadata.setTextFormat(Qt.TextFormat.PlainText)
        self.metadata.setWordWrap(True)
        self.metadata.setStyleSheet("color: #c7d0d2; font-size: 12px;")
        text.addWidget(self.metadata)
        self.synopsis = QLabel()
        self.synopsis.setTextFormat(Qt.TextFormat.PlainText)
        self.synopsis.setWordWrap(True)
        self.synopsis.setStyleSheet("color: #c7d0d2; font-size: 13px; line-height: 1.7;")
        text.addSpacing(12)
        text.addWidget(self.synopsis)
        self.action_layout = QHBoxLayout()
        self.action_layout.setSpacing(10)
        text.addSpacing(16)
        text.addLayout(self.action_layout)
        text.addStretch()
        self.box.addWidget(self.copy, 3, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.strip = QListWidget()
        self.strip.setObjectName("mediaFocusStrip")
        self.strip.setViewMode(QListView.ViewMode.IconMode)
        self.strip.setFlow(QListView.Flow.LeftToRight)
        self.strip.setWrapping(False)
        self.strip.setMovement(QListView.Movement.Static)
        self.strip.setResizeMode(QListView.ResizeMode.Adjust)
        self.strip.setWordWrap(True)
        self.strip.setGridSize(QSize(130, 196))
        self.strip.setIconSize(QSize(112, 148))
        self.strip.setFixedHeight(208)
        self.strip.setMinimumWidth(200)
        self.strip.setMaximumWidth(430)
        self.box.addWidget(self.strip, 2, Qt.AlignmentFlag.AlignBottom)
        self.strip.hide()

    def set_picture(self, picture):
        self.picture = picture
        self.update()

    def set_mode(self, mode):
        self.mode = mode
        self.strip.setVisible(mode == "focus")
        self._arrange()

    def _arrange(self):
        narrow_focus = self.mode == "focus" and self.width() < 900
        self.box.setDirection(
            QBoxLayout.Direction.TopToBottom if narrow_focus else QBoxLayout.Direction.LeftToRight
        )
        self.setMinimumHeight(630 if narrow_focus else 490 if self.mode == "focus" else 440)
        self.title.setStyleSheet(
            "font-size: "
            + ("36" if self.width() < 700 else "48")
            + "px; font-weight: 750; color: #f3f4ef;"
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._arrange()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.fillRect(self.rect(), QColor("#12212a"))
        if not self.picture.isNull():
            scale = max(self.width() / self.picture.width(), self.height() / self.picture.height())
            width, height = self.width() / scale, self.height() / scale
            source = QRectF(
                (self.picture.width() - width) / 2,
                (self.picture.height() - height) / 2,
                width,
                height,
            )
            painter.drawImage(QRectF(self.rect()), self.picture, source)
        horizontal = QLinearGradient(0, 0, self.width(), 0)
        horizontal.setColorAt(0, QColor(12, 18, 22, 245))
        horizontal.setColorAt(0.55, QColor(12, 18, 22, 172))
        horizontal.setColorAt(1, QColor(12, 18, 22, 28))
        painter.fillRect(self.rect(), horizontal)
        vertical = QLinearGradient(0, 0, 0, self.height())
        vertical.setColorAt(0, QColor(16, 19, 21, 40))
        vertical.setColorAt(0.65, QColor(16, 19, 21, 0))
        vertical.setColorAt(1, QColor("#101315"))
        painter.fillRect(self.rect(), vertical)
        painter.end()


class MediaTab(QWidget):
    """One native player session whose lifetime is independent of browsing and chat."""

    PICTURE_CACHE_LIMIT = 24 * 1024 * 1024

    scan_progress = Signal(object)
    layout_changed = Signal(str)

    def __init__(
        self,
        get_service: Callable[[], Any],
        client_id: Callable[[], str],
        add_folder: Callable[[], None],
    ) -> None:
        super().__init__()
        self.get_service = get_service
        self.client_id = client_id
        self.service: Any = None
        self.library: Any = None
        self.session_id = ""
        self.token = ""
        self.session_client = ""
        self.command_ack = 0
        self.credentials: QSettings | None = None
        self.state: dict[str, Any] = {
            "current_id": "",
            "queue": [],
            "index": 0,
            "position": 0,
            "duration": 0,
            "paused": True,
            "volume": 1.0,
            "shuffle": False,
            "repeat": "off",
        }
        self.rows: list[dict[str, Any]] = []
        self.conversation_id = ""
        self.current_playlist = ""
        self.assistant: Any = None
        self.scan_stop: threading.Event | None = None
        self.pending_seek: int | None = None
        self.last_source = ""
        self.current_row: dict[str, Any] = {}
        self.subtitle_cues: list[tuple[float, float, str]] = []
        self.offset = 0
        self.next_offset: int | None = None
        self.preview_id = ""
        self.preview_item = ""
        self.preview_device: VerifiedPrefixDevice | None = None
        self.preview_generation = 0
        self.preview_checked = 0.0
        self.preview_check_pending = False
        self.browse_generation = 0
        self.art_generation = 0
        self.detail_row: dict[str, Any] = {}
        self.art_stop = threading.Event()
        self.player: Any = None
        self.audio: Any = None
        self.video = QVideoWidget(self)

        self._build_presentation(add_folder)

    def _build_presentation(self, add_folder) -> None:
        self.media_layout = "cinematic"
        self.featured_id = ""
        self.picture_cache: OrderedDict[str, QImage] = OrderedDict()
        self._picture_cache_bytes = 0
        self.continue_rows: list[dict[str, Any]] = []
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.setObjectName("mediaWorkspace")
        self.setStyleSheet("""
            QWidget#mediaWorkspace, QWidget#mediaCanvas { background: #101315; color: #f1f3ef; }
            QListWidget#mediaPosters, QListWidget#mediaFocusStrip {
                background: transparent; color: #edf0ee; border: none; outline: 0;
            }
            QListWidget#mediaPosters::item:selected,
            QListWidget#mediaFocusStrip::item:selected {
                background: rgba(121, 211, 197, 43); border-radius: 7px; }
            QListWidget#mediaPosters::item:hover,
            QListWidget#mediaFocusStrip::item:hover {
                background: rgba(255, 255, 255, 14); border-radius: 7px; }
            QPushButton#mediaPrimary { background: #eff3ed; color: #13211f;
                border: 0; border-radius: 6px; padding: 10px 18px; font-weight: 650; }
            QPushButton#mediaSecondary { background: rgba(255, 255, 255, 29); color: #f3f4ef;
                border: 0; border-radius: 6px; padding: 10px 16px; }
            QPushButton#mediaDisclosure { padding: 7px 12px; }
            QLabel#mediaSection { color: #f1f3ef; font-size: 20px; font-weight: 600; }
        """)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(self.splitter)
        left = QWidget()
        left_box = QVBoxLayout(left)
        left_box.setContentsMargins(0, 0, 0, 0)
        left_box.setSpacing(0)
        self.splitter.addWidget(left)
        self.content_scroll = QScrollArea()
        self.content_scroll.setWidgetResizable(True)
        self.content_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.content_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.canvas = QWidget()
        self.canvas.setObjectName("mediaCanvas")
        self.body = QVBoxLayout(self.canvas)
        self.body.setContentsMargins(24, 18, 24, 24)
        self.body.setSpacing(18)
        self.content_scroll.setWidget(self.canvas)
        left_box.addWidget(self.content_scroll, 1)
        widget: QWidget
        self.header_box = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        navigation = QWidget()
        header = QHBoxLayout(navigation)
        header.setContentsMargins(0, 0, 0, 0)
        tools = QWidget()
        tools_box = QHBoxLayout(tools)
        tools_box.setContentsMargins(0, 0, 0, 0)
        self.kind = QComboBox()
        self.kind.addItem(self.tr("Video"), "video")
        self.kind.addItem(self.tr("Music"), "music")
        self.view = QComboBox()
        self.search = QLineEdit()
        self.search.setPlaceholderText(self.tr("Search saved media"))
        self.search.setMaximumWidth(240)
        self.layout_combo = QComboBox()
        self.layout_combo.setObjectName("media-layout")
        self.layout_combo.setAccessibleName(self.tr("Media layout"))
        self.layout_combo.addItem(self.tr("Cinematic home"), "cinematic")
        self.layout_combo.addItem(self.tr("Focus"), "focus")
        self.layout_combo.addItem(self.tr("Collection"), "collection")
        self.library_disclosure = QPushButton(self.tr("Library options"))
        self.library_disclosure.setObjectName("mediaDisclosure")
        self.library_disclosure.setCheckable(True)
        self.chat = QPushButton(self.tr("Chat"))
        for widget in (self.kind, self.view, self.search):
            header.addWidget(widget)
        header.addStretch()
        for widget in (self.layout_combo, self.library_disclosure, self.chat):
            tools_box.addWidget(widget)
        self.header_box.addWidget(navigation, 1)
        self.header_box.addWidget(tools)
        self.body.addLayout(self.header_box)
        self.content_scroll.viewport().installEventFilter(self)
        self.library_panel = QWidget()
        maintenance = QVBoxLayout(self.library_panel)
        maintenance.setContentsMargins(0, 0, 0, 0)
        folder_row = QHBoxLayout()
        self.refresh_button = QPushButton(self.tr("Refresh folders"))
        self.cancel_scan = QPushButton(self.tr("Cancel scan"))
        self.cancel_scan.setEnabled(False)
        self.folder_button = QPushButton(self.tr("Add folder…"))
        self.folder_button.clicked.connect(add_folder)
        for widget in (self.refresh_button, self.cancel_scan, self.folder_button):
            folder_row.addWidget(widget)
        folder_row.addStretch()
        maintenance.addLayout(folder_row)
        filters_row = QHBoxLayout()
        self.filter_labels = {
            "genre": self.tr("Any genre"),
            "year": self.tr("Any year"),
            "language": self.tr("Any language"),
            "availability": self.tr("Any availability"),
        }
        self.filters: dict[str, QComboBox] = {}
        for name in ("genre", "year", "language", "availability"):
            combo = QComboBox()
            combo.addItem(self.filter_labels[name], "")
            combo.currentIndexChanged.connect(self.refresh)
            self.filters[name] = combo
            filters_row.addWidget(combo)
        self.filter_panel = QWidget()
        self.filter_panel.setLayout(filters_row)
        filters_row.setContentsMargins(0, 0, 0, 0)
        self.library_panel.hide()
        self.library_disclosure.toggled.connect(self.library_panel.setVisible)
        self.library_disclosure.toggled.connect(
            lambda checked: self.filter_panel.setVisible(
                checked or self.media_layout == "collection" or self.kind.currentData() == "music"
            )
        )
        self.body.addWidget(self.library_panel)
        self.body.addWidget(self.filter_panel)
        self.notice = QLabel()
        self.notice.setWordWrap(True)
        self.body.addWidget(self.notice)
        self.empty = QLabel(
            self.tr(
                "Add a Library Folder, then Refresh folders to find videos and music. "
                "Media discovery does not need an Indexer connection."
            )
        )
        self.empty.setWordWrap(True)
        self.empty.setStyleSheet("color: #a7b3b6; padding: 24px 0;")
        self.body.addWidget(self.empty)
        self.hero = MediaHero()
        self.play_button = QPushButton(self.tr("Play selected"))
        self.play_button.setObjectName("mediaPrimary")
        self.play_button.clicked.connect(self.play_selected)
        self.info_button = QPushButton(self.tr("More info"))
        self.info_button.setObjectName("mediaSecondary")
        self.info_button.clicked.connect(self.open_details)
        self.enqueue_button = QPushButton(self.tr("Add to queue"))
        self.enqueue_button.setObjectName("mediaSecondary")
        self.enqueue_button.clicked.connect(self.enqueue_selected)
        self.preview_button = QPushButton(self.tr("Preview downloaded portion"))
        self.preview_button.setObjectName("mediaPrimary")
        self.preview_button.clicked.connect(self.start_preview)
        self.refresh_preview = QPushButton(self.tr("Refresh preview"))
        self.refresh_preview.clicked.connect(self.start_preview)
        self.action_bar = QWidget()
        actions_box = QHBoxLayout(self.action_bar)
        actions_box.setContentsMargins(0, 0, 0, 0)
        for widget in (
            self.play_button,
            self.preview_button,
            self.info_button,
            self.enqueue_button,
            self.refresh_preview,
        ):
            actions_box.addWidget(widget)
        actions_box.addStretch()
        self.hero.action_layout.addWidget(self.action_bar)
        self.body.addWidget(self.hero)
        self.collection_heading = QLabel(self.tr("Your collection"))
        self.collection_heading.setStyleSheet("font-size: 34px; font-weight: 650; color: #f2f4f0;")
        self.body.addWidget(self.collection_heading)
        self.collection_selection = QWidget()
        collection_box = QVBoxLayout(self.collection_selection)
        collection_box.setContentsMargins(0, 0, 0, 0)
        self.collection_title = QLabel()
        self.collection_title.setStyleSheet("font-size: 20px; color: #f1f3ef; font-weight: 600;")
        self.collection_title.setTextFormat(Qt.TextFormat.PlainText)
        collection_box.addWidget(self.collection_title)
        self.collection_actions = QHBoxLayout()
        collection_box.addLayout(self.collection_actions)
        self.body.addWidget(self.collection_selection)
        self.continue_heading = QLabel(self.tr("Continue watching"))
        self.continue_heading.setObjectName("mediaSection")
        self.body.addWidget(self.continue_heading)
        self.continue_panel = QWidget()
        self.continue_box = QHBoxLayout(self.continue_panel)
        self.continue_box.setContentsMargins(0, 0, 0, 0)
        self.continue_box.setSpacing(16)
        self.body.addWidget(self.continue_panel)
        shelf_header = QHBoxLayout()
        self.shelf_heading = QLabel(self.tr("Recently added"))
        self.shelf_heading.setObjectName("mediaSection")
        self.page_count = QLabel()
        self.page_count.setStyleSheet("color: #9aa9ad; font-size: 11px;")
        shelf_header.addWidget(self.shelf_heading)
        shelf_header.addStretch()
        shelf_header.addWidget(self.page_count)
        self.body.addLayout(shelf_header)
        self.results = QListWidget()
        self.results.setObjectName("mediaPosters")
        self.results.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.results.itemSelectionChanged.connect(self.show_detail)
        self.results.itemDoubleClicked.connect(lambda _item: self.play_selected())
        self.hero.strip.itemSelectionChanged.connect(self._focus_selection)
        self.body.addWidget(self.results)
        pages = QHBoxLayout()
        self.previous_page = QPushButton(self.tr("Previous page"))
        self.next_page = QPushButton(self.tr("Next page"))
        self.previous_page.clicked.connect(lambda: self._page(max(0, self.offset - 100)))
        self.next_page.clicked.connect(lambda: self._page(self.next_offset or 0))
        pages.addStretch()
        pages.addWidget(self.previous_page)
        pages.addWidget(self.next_page)
        self.body.addLayout(pages)
        self.body.addStretch()
        self.details = QDialog(self)
        self.details.setWindowTitle(self.tr("Media details"))
        self.details.resize(620, 560)
        detail_box = QVBoxLayout(self.details)
        self.artwork = QLabel()
        self.artwork.setAlignment(Qt.AlignmentFlag.AlignCenter)
        detail_box.addWidget(self.artwork)
        self.description = QLabel()
        self.description.setWordWrap(True)
        self.description.setTextFormat(Qt.TextFormat.PlainText)
        detail_box.addWidget(self.description)
        self.releases = QComboBox()
        self.episodes = QComboBox()
        self.more_releases = QPushButton(self.tr("More releases"))
        self.more_episodes = QPushButton(self.tr("More episodes"))
        self.more_releases.clicked.connect(lambda: self._more_detail("releases"))
        self.more_episodes.clicked.connect(lambda: self._more_detail("episodes"))
        for combo, more in (
            (self.releases, self.more_releases),
            (self.episodes, self.more_episodes),
        ):
            line = QHBoxLayout()
            line.addWidget(combo, 1)
            line.addWidget(more)
            detail_box.addLayout(line)
        self.watched = QCheckBox(self.tr("Watched"))
        self.watched.clicked.connect(self._watched)
        detail_box.addWidget(self.watched)
        detail_actions = QHBoxLayout()
        detail_play = QPushButton(self.tr("Play selected"))
        detail_play.clicked.connect(self.play_selected)
        detail_play.clicked.connect(self.details.hide)
        detail_preview = QPushButton(self.tr("Preview downloaded portion"))
        detail_preview.clicked.connect(self.start_preview)
        detail_preview.clicked.connect(self.details.hide)
        close_details = QPushButton(self.tr("Close"))
        close_details.clicked.connect(self.details.hide)
        for widget in (detail_play, detail_preview, close_details):
            detail_actions.addWidget(widget)
        detail_box.addLayout(detail_actions)
        self.detail_widgets = [
            self.artwork,
            self.description,
            self.releases,
            self.episodes,
            self.watched,
        ]
        self.player_panel = QWidget()
        player_box = QVBoxLayout(self.player_panel)
        player_box.setContentsMargins(12, 8, 12, 8)
        player_box.setSpacing(6)
        self.video.setMinimumHeight(160)
        self.video.setMaximumHeight(240)
        player_box.addWidget(self.video)
        self.caption = QLabel()
        self.caption.setTextFormat(Qt.TextFormat.PlainText)
        self.caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.caption.setWordWrap(True)
        player_box.addWidget(self.caption)
        self.now_playing = QLabel(self.tr("Nothing playing"))
        transport = QHBoxLayout()
        previous = QPushButton(self.tr("Previous"))
        previous.clicked.connect(lambda: self.command("previous"))
        self.pause = QPushButton(self.tr("Play / pause"))
        self.pause.clicked.connect(self.toggle_pause)
        next_button = QPushButton(self.tr("Next"))
        next_button.clicked.connect(lambda: self.command("next"))
        self.seek = QSlider(Qt.Orientation.Horizontal)
        self.seek.setRange(0, 0)
        self.seek.sliderReleased.connect(lambda: self.command("seek", position=self.seek.value()))
        self.elapsed = QLabel("0:00 / 0:00")
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(100)
        self.volume.setMaximumWidth(90)
        self.volume.setAccessibleName(self.tr("Volume"))
        self.volume.sliderReleased.connect(
            lambda: self.command("volume", volume=self.volume.value() / 100)
        )
        for widget in (
            previous,
            self.pause,
            next_button,
            self.now_playing,
            self.seek,
            self.elapsed,
            self.volume,
        ):
            transport.addWidget(widget)
        player_box.addLayout(transport)
        options = QHBoxLayout()
        self.shuffle = QCheckBox(self.tr("Shuffle"))
        self.shuffle.clicked.connect(lambda on: self.command("shuffle", shuffle=on))
        self.repeat = QComboBox()
        for label, value in (
            (self.tr("Repeat off"), "off"),
            (self.tr("Repeat all"), "all"),
            (self.tr("Repeat one"), "one"),
        ):
            self.repeat.addItem(label, value)
        self.repeat.currentIndexChanged.connect(
            lambda: self.command("repeat", repeat=self.repeat.currentData())
        )
        self.subtitles = QComboBox()
        self.subtitles.addItem(self.tr("Subtitles off"), -1)
        self.subtitles.currentIndexChanged.connect(self._select_subtitle)
        self.queue_disclosure = QPushButton(self.tr("Queue & playlists"))
        self.queue_disclosure.setCheckable(True)
        for widget in (self.shuffle, self.repeat, self.subtitles):
            options.addWidget(widget)
        options.addStretch()
        options.addWidget(self.queue_disclosure)
        player_box.addLayout(options)
        self.external = QPushButton(self.tr("Open in external player"))
        self.external.clicked.connect(self.open_external)
        self.external.hide()
        player_box.addWidget(self.external)
        self.queue_panel = QWidget()
        queue_box = QHBoxLayout(self.queue_panel)
        self.queue = QListWidget()
        self.queue.setMaximumHeight(150)
        self.queue.itemDoubleClicked.connect(self._queue_play)
        queue_box.addWidget(self.queue, 1)
        queue_controls = QVBoxLayout()
        remove = QPushButton(self.tr("Remove from queue"))
        remove.clicked.connect(self.remove_from_queue)
        self.save_playlist = QPushButton(self.tr("Save queue as playlist…"))
        self.save_playlist.clicked.connect(self._save_playlist)
        self.playlists = QComboBox()
        self.load_playlist = QPushButton(self.tr("Load playlist"))
        self.load_playlist.clicked.connect(self._load_playlist)
        delete_playlist = QPushButton(self.tr("Delete playlist"))
        delete_playlist.clicked.connect(self._delete_playlist)
        for widget in (
            remove,
            self.save_playlist,
            self.playlists,
            self.load_playlist,
            delete_playlist,
        ):
            queue_controls.addWidget(widget)
        queue_box.addLayout(queue_controls)
        self.queue_panel.hide()
        self.queue_disclosure.toggled.connect(self.queue_panel.setVisible)
        player_box.addWidget(self.queue_panel)
        self.playback_widgets = [
            self.now_playing,
            previous,
            self.pause,
            next_button,
            self.seek,
            self.elapsed,
            self.volume,
            self.shuffle,
            self.repeat,
            self.subtitles,
        ]
        self.queue_widgets = [
            self.queue,
            remove,
            self.save_playlist,
            self.playlists,
            self.load_playlist,
            delete_playlist,
        ]
        left_box.addWidget(self.player_panel)
        self.refresh_button.clicked.connect(self.start_scan)
        self.cancel_scan.clicked.connect(self._cancel_media_scan)
        self.scan_progress.connect(lambda value: self.notice.setText(str(value)))
        self.kind.currentIndexChanged.connect(self._kind_changed)
        self.view.currentIndexChanged.connect(self.refresh)
        self.search.textChanged.connect(self.refresh)
        self.chat.clicked.connect(self.open_chat)
        self.layout_combo.currentIndexChanged.connect(self._layout_selected)
        self._kind_changed()
        self.heartbeat = QTimer(self)
        self.heartbeat.setInterval(1000)
        self.heartbeat.timeout.connect(self.report)
        self.set_media_layout("cinematic")
        self._update_panes()

    def _cancel_media_scan(self) -> None:
        if self.scan_stop:
            self.scan_stop.set()

    def _layout_selected(self) -> None:
        value = self.layout_combo.currentData()
        self.set_media_layout(value)
        self.layout_changed.emit(value)

    def set_media_layout(self, value: str) -> None:
        value = value if value in {"cinematic", "focus", "collection"} else "cinematic"
        self.media_layout = value
        with QSignalBlocker(self.layout_combo):
            self.layout_combo.setCurrentIndex(self.layout_combo.findData(value))
        self.hero.set_mode(value)
        collection = value == "collection" or self.kind.currentData() == "music"
        if collection:
            self.collection_actions.addWidget(self.action_bar)
        else:
            self.hero.action_layout.addWidget(self.action_bar)
        self.library_disclosure.setChecked(False)
        self.filter_panel.setVisible(collection)
        self._configure_browse_layout()
        self._refresh_focus_strip()
        self._update_panes()

    def open_details(self) -> None:
        if self.selected_ids():
            self.details.show()
            self.details.raise_()

    def _focus_selection(self) -> None:
        items = self.hero.strip.selectedItems()
        if not items:
            return
        identifier = items[0].data(Qt.ItemDataRole.UserRole)
        for index in range(self.results.count()):
            item = self.results.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == identifier:
                with QSignalBlocker(self.results):
                    self.results.clearSelection()
                    item.setSelected(True)
                self.show_detail()
                break

    def _refresh_focus_strip(self) -> None:
        with QSignalBlocker(self.hero.strip):
            self.hero.strip.clear()
            rows = list(self.rows)
            featured = next((row for row in rows if row["id"] == self.featured_id), None)
            if featured:
                rows = [featured, *[row for row in rows if row["id"] != self.featured_id]]
            for row in rows:
                item = QListWidgetItem(self._card_title(row))
                item.setData(Qt.ItemDataRole.UserRole, row["id"])
                picture = self.picture_cache.get(row["id"])
                item.setIcon(
                    self._cover_icon(picture, QSize(112, 148))
                    if picture is not None
                    else self._placeholder_icon(row["kind"])
                )
                item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
                self.hero.strip.addItem(item)
                item.setSelected(row["id"] == self.featured_id)

    @staticmethod
    def _time_label(seconds: float) -> str:
        seconds = max(0, int(seconds))
        return (
            f"{seconds // 3600}:{seconds // 60 % 60:02d}:{seconds % 60:02d}"
            if seconds >= 3600
            else f"{seconds // 60}:{seconds % 60:02d}"
        )

    def _show_feature(self, row: dict[str, Any]) -> None:
        self.featured_id = row["id"]
        self.hero.title.setText(row["title"])
        self.collection_title.setText(row["title"])
        facts = [
            str(row[key])
            for key in ("year", "artist", "album", "genre", "language")
            if row.get(key)
        ]
        if row.get("identity_source") == "filename":
            facts.insert(0, self.tr("Filename metadata"))
        if row.get("duration"):
            facts.append(self._time_label(float(row["duration"])))
        if row.get("position"):
            facts.append(self.tr("Resume at {0}").format(self._time_label(float(row["position"]))))
        self.hero.metadata.setText(" · ".join(facts))
        synopsis = str(row.get("description") or "")
        self.hero.synopsis.setText(synopsis[:360] + ("…" if len(synopsis) > 360 else ""))
        self.hero.set_picture(self.picture_cache.get(row["id"], QImage()))
        self.play_button.setText(
            self.tr("Resume") if row.get("position") else self.tr("Play selected")
        )
        self._refresh_focus_strip()

    def _render_continue(self) -> None:
        while self.continue_box.count():
            item = self.continue_box.takeAt(0)
            if item is not None:
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()
        self.continue_heading.setText(
            self.tr("Continue watching")
            if self.kind.currentData() == "video"
            else self.tr("Continue listening")
        )
        for row in self.continue_rows[:4]:
            button = MediaTileButton()
            button.setMinimumHeight(165)
            button.setStyleSheet(
                "QPushButton { border: 0; background: transparent; padding: 0; "
                "text-align: left; color: #edf1ef; }"
            )
            button.setMinimumWidth(140)
            column = QVBoxLayout(button)
            column.setContentsMargins(0, 0, 0, 0)
            column.setSpacing(5)
            still = QLabel()
            still.setFixedHeight(105)
            still.setAlignment(Qt.AlignmentFlag.AlignCenter)
            still.setStyleSheet("background: #17242b; border-radius: 6px;")
            picture = self.picture_cache.get(row["id"])
            if picture is not None:
                still.setPixmap(
                    QPixmap.fromImage(picture).scaled(
                        240,
                        105,
                        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
            else:
                still.setPixmap(self._placeholder_icon(row["kind"]).pixmap(80, 90))
            column.addWidget(still)
            progress = QProgressBar()
            progress.setTextVisible(False)
            progress.setFixedHeight(3)
            progress.setRange(0, 100)
            duration = float(row.get("duration") or 0)
            progress.setValue(
                min(100, round(100 * float(row.get("position") or 0) / duration)) if duration else 0
            )
            progress.setStyleSheet(
                "QProgressBar { background: rgba(255, 255, 255, 37); border: none; } "
                "QProgressBar::chunk { background: #79d3c5; }"
            )
            column.addWidget(progress)
            label = QLabel(row["title"])
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setWordWrap(True)
            label.setStyleSheet("color: #e9eeeb; font-size: 12px;")
            column.addWidget(label)
            position = QLabel(self._time_label(float(row.get("position") or 0)))
            position.setStyleSheet("color: #9eacb0; font-size: 10px;")
            column.addWidget(position)
            for child in button.findChildren(QWidget):
                child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            button.clicked.connect(
                lambda _checked=False, identifier=row["id"]: self.command(
                    "play", media_ids=[identifier], index=0
                )
            )
            self.continue_box.addWidget(button, 1)
        self.continue_box.addStretch()

    def rebind(
        self,
        get_service: Callable[[], Any],
        client_id: Callable[[], str],
        add_folder: Callable[[], None],
    ) -> None:
        """Keep the current player when a settings change replaces its main window."""
        self._invalidate_preview_request()
        self.get_service = get_service
        self.client_id = client_id
        self.folder_button.clicked.disconnect()
        self.folder_button.clicked.connect(add_folder)
        if self.assistant:
            self.assistant.get_service = get_service
        if self.library and self.state["current_id"] and not self.preview_id:
            try:
                self.library.resolve(self.session_client, self.state["current_id"])
            except (OSError, ValueError) as error:
                self.player.stop()
                self.player.setSource(QUrl())
                self.state["current_id"] = ""
                self.last_source = ""
                self.notice.setText(str(error))

    def activate(self) -> None:
        try:
            if self.library is not None and self.session_client != self.client_id():
                self.stop()
                self.player.deleteLater()
                self.audio.deleteLater()
                self.library = None
                self.state.update(current_id="", queue=[], index=0, position=0)
                self.last_source = ""
                self.command_ack = 0
                self.conversation_id = ""
            if self.library is None:
                self.service = self.get_service()
                self.library = self.service.agent.media
                self.session_client = self.client_id()
                self.credentials = QSettings(
                    str(self.service.agent.setup.path.with_name("media-desktop.ini")),
                    QSettings.Format.IniFormat,
                )
                self.credentials.beginGroup(self.session_client)
                saved_id = str(self.credentials.value("session", ""))
                saved_token = str(self.credentials.value("token", ""))
                session = None
                if saved_id and saved_token:
                    try:
                        session = self.library.session(saved_id, saved_token)
                        self.session_id, self.token = saved_id, saved_token
                        self.conversation_id = str(self.credentials.value("conversation", ""))
                    except (OSError, ValueError):
                        pass
                if session is None:
                    session = self.library.open_session(self.session_client, "desktop")
                    self.session_id, self.token = session["id"], session["token"]
                    self.conversation_id = ""
                self.credentials.setValue("session", self.session_id)
                self.credentials.setValue("token", self.token)
                self.credentials.setValue("conversation", self.conversation_id)
                self.credentials.sync()
                QFile.setPermissions(
                    self.credentials.fileName(),
                    QFile.Permission.ReadOwner | QFile.Permission.WriteOwner,
                )
                self.state.update(session["state"])
                self.current_playlist = self.state.get("context", {}).get("playlist", "")
                self.command_ack = int(self.state.get("command_ack", 0))
                self.player = QMediaPlayer(self)
                self.audio = QAudioOutput(self)
                self.player.setAudioOutput(self.audio)
                self.player.setVideoOutput(self.video)
                self.player.errorOccurred.connect(self._codec_error)
                self.player.positionChanged.connect(self._position_changed)
                self.player.durationChanged.connect(self._duration_changed)
                self.player.mediaStatusChanged.connect(self._media_status)
                self.player.tracksChanged.connect(self._subtitle_tracks)
                self.audio.setVolume(float(self.state["volume"]))
                self.volume.setValue(round(float(self.state["volume"]) * 100))
                with QSignalBlocker(self.shuffle), QSignalBlocker(self.repeat):
                    self.shuffle.setChecked(bool(self.state["shuffle"]))
                    self.repeat.setCurrentIndex(max(0, self.repeat.findData(self.state["repeat"])))
                self.heartbeat.start()
                try:
                    self._load_current(play=False)
                except (OSError, ValueError) as error:
                    self.notice.setText(str(error))
                    self._render_queue()
                self._apply_commands(session.get("commands", []))
            self.refresh()
        except Exception as error:
            self.notice.setText(str(error))

    def _kind_changed(self) -> None:
        values = (
            (
                (self.tr("All"), "all"),
                (self.tr("Recent"), "recent"),
                (self.tr("Continue watching"), "continue"),
                (self.tr("Films"), "films"),
                (self.tr("Series"), "series"),
            )
            if self.kind.currentData() == "video"
            else (
                (self.tr("Tracks"), "tracks"),
                (self.tr("Albums"), "albums"),
                (self.tr("Artists"), "artists"),
            )
        )
        with QSignalBlocker(self.view):
            self.view.clear()
            for label, value in values:
                self.view.addItem(label, value)
        self.set_media_layout(self.media_layout)
        self.refresh()

    def _configure_browse_layout(self) -> bool:
        cards = self.kind.currentData() == "video" or self.view.currentData() in {
            "albums",
            "artists",
        }
        self.results.setViewMode(
            QListView.ViewMode.IconMode if cards else QListView.ViewMode.ListMode
        )
        self.results.setFlow(QListView.Flow.LeftToRight if cards else QListView.Flow.TopToBottom)
        self.results.setResizeMode(QListView.ResizeMode.Adjust)
        self.results.setMovement(QListView.Movement.Static)
        self.results.setWrapping(cards)
        self.results.setWordWrap(cards)
        self.results.setUniformItemSizes(cards)
        self.results.setSpacing(8 if cards else 2)
        dense = self.media_layout == "collection"
        self.results.setGridSize(
            QSize(156, 226) if cards and dense else QSize(180, 248) if cards else QSize()
        )
        self.results.setIconSize(
            QSize(116, 154) if cards and dense else QSize(128, 170) if cards else QSize(40, 40)
        )
        self.results.setMinimumHeight(470 if dense and cards else 280 if cards else 120)
        self.results.setMaximumHeight(1200 if dense else 560 if cards else 240)
        return cards

    def eventFilter(self, watched, event):
        if watched is self.content_scroll.viewport() and event.type() == QEvent.Type.Resize:
            self.header_box.setDirection(
                QBoxLayout.Direction.TopToBottom
                if event.size().width() < 950
                else QBoxLayout.Direction.LeftToRight
            )
        return super().eventFilter(watched, event)

    def _cover_icon(self, picture: QImage, size: QSize | None = None) -> QIcon:
        size = size or self.results.iconSize()
        pixmap = QPixmap.fromImage(picture).scaled(
            size,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        left = max(0, (pixmap.width() - size.width()) // 2)
        top = max(0, (pixmap.height() - size.height()) // 2)
        return QIcon(pixmap.copy(left, top, size.width(), size.height()))

    def _placeholder_icon(self, kind: str) -> QIcon:
        cover = QPixmap(128, 170)
        palette = self.palette()
        cover.fill(palette.color(QPalette.ColorRole.AlternateBase))
        painter = QPainter(cover)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(palette.color(QPalette.ColorRole.Mid))
        painter.drawRoundedRect(1, 1, 125, 167, 8, 8)
        painter.setPen(palette.color(QPalette.ColorRole.Text))
        if kind == "video":
            triangle = QPainterPath()
            triangle.moveTo(48, 53)
            triangle.lineTo(48, 105)
            triangle.lineTo(88, 79)
            triangle.closeSubpath()
            painter.fillPath(triangle, palette.color(QPalette.ColorRole.Highlight))
        else:
            font = QFont(painter.font())
            font.setPointSize(40)
            painter.setFont(font)
            painter.drawText(
                cover.rect().adjusted(0, 12, 0, -40), Qt.AlignmentFlag.AlignCenter, "♪"
            )
        font = QFont(painter.font())
        font.setPointSize(10)
        painter.setFont(font)
        painter.drawText(
            cover.rect().adjusted(0, 128, 0, -12),
            Qt.AlignmentFlag.AlignCenter,
            self.tr("Video") if kind == "video" else self.tr("Music"),
        )
        painter.end()
        return QIcon(cover)

    def _card_title(self, row: dict[str, Any]) -> str:
        view = self.view.currentData()
        title = (
            row.get("album")
            if view == "albums"
            else row.get("artist")
            if view == "artists"
            else row["title"]
        ) or row["title"]
        title = str(title)
        if len(title) > 52:
            title = title[:49] + "…"
        subtitle = str(row.get("artist") or "") if view == "albums" else str(row.get("year") or "")
        if row.get("track_count"):
            subtitle = self.tr(" · {0} tracks").format(row["track_count"]).lstrip(" ·")
        if not row.get("available", True):
            subtitle += self.tr(" · unavailable")
        return title + ("\n" + subtitle[:30] if subtitle else "")

    def _context(self) -> dict[str, Any]:
        return {
            "kind": self.kind.currentData(),
            "view": self.view.currentData(),
            "q": self.search.text(),
            **{key: combo.currentData() for key, combo in self.filters.items()},
            "selected_ids": self.selected_ids(),
            "preview_id": self.preview_id,
            "playlist": self.current_playlist,
        }

    def _page(self, offset: int) -> None:
        self.offset = offset
        self.refresh(keep_page=True)

    def refresh(self, *_args: Any, keep_page: bool = False) -> None:
        if self.library is None:
            return
        context = self._context()
        context.pop("selected_ids")
        context.pop("preview_id")
        context.pop("playlist")
        if not keep_page:
            self.offset = 0
        self.browse_generation += 1
        generation = self.browse_generation
        library, client, offset = self.library, self.session_client, self.offset
        self.results.setEnabled(False)
        self.notice.setText(self.tr("Loading saved media…"))

        def work():
            continuation = {**context, "view": "continue"}
            return (
                library.listing(client, offset=offset, **context),
                library.playlists(client),
                library.listing(client, limit=4, **continuation)["rows"],
            )

        def done(payload):
            if not isValid(self) or generation != self.browse_generation:
                return
            self.results.setEnabled(True)
            self._show_listing(*payload)

        def failed(error):
            if isValid(self) and generation == self.browse_generation:
                self.results.setEnabled(True)
                self.notice.setText(str(error))

        run_in_background(work, done, failed)

    def _show_listing(
        self,
        result: dict[str, Any],
        playlists: list[dict[str, Any]],
        continuation: list[dict[str, Any]],
    ) -> None:
        try:
            selected = self.selected_ids()
            self.continue_rows = continuation
            self.next_offset = result.get("next_offset")
            self.previous_page.setEnabled(self.offset > 0)
            self.next_page.setEnabled(bool(result.get("has_more")))
            self.page_count.setText(self.tr("{0} saved items").format(result["total"]))
            self.rows = result["rows"]
            cards = self._configure_browse_layout()
            placeholder = self._placeholder_icon(self.kind.currentData())
            self.results.clear()
            for row in self.rows:
                title = row["title"]
                if row.get("artist"):
                    title = f"{row['artist']} · {title}"
                if row.get("album"):
                    title += f" · {row['album']}"
                if row.get("track_count"):
                    title += self.tr(" · {0} tracks").format(row["track_count"])
                if row.get("release") and self.view.currentData() not in {"albums", "artists"}:
                    title += f" · {row['release']}"
                if not row.get("available", True):
                    title += self.tr(" · unavailable")
                item = QListWidgetItem(self._card_title(row) if cards else title)
                item.setToolTip(title)
                item.setIcon(placeholder)
                if cards:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
                    grid = self.results.gridSize()
                    item.setSizeHint(QSize(grid.width() - 4, grid.height() - 8))
                item.setData(Qt.ItemDataRole.UserRole, row["id"])
                self.results.addItem(item)
            if self.rows:
                identifier = next(
                    (value for value in selected if any(row["id"] == value for row in self.rows)),
                    self.featured_id,
                )
                for index in range(self.results.count()):
                    item = self.results.item(index)
                    if item.data(Qt.ItemDataRole.UserRole) == identifier:
                        item.setSelected(True)
                if not self.selected_ids():
                    self.results.item(0).setSelected(True)
            else:
                self.detail_row = {}
                self.featured_id = ""
                self.hero.title.setText(self.tr("Your library"))
                self.hero.synopsis.clear()
                self.hero.metadata.clear()
                self.hero.set_picture(QImage())
            self._render_continue()
            self._load_artwork([*self.rows, *continuation])
            for name, combo in self.filters.items():
                current = combo.currentData()
                values = result.get("filters", {}).get(name, [])
                if name == "availability":
                    values = ["available", "unfinished", "unavailable"]
                with QSignalBlocker(combo):
                    combo.clear()
                    combo.addItem(self.filter_labels[name], "")
                    for value in values:
                        combo.addItem(str(value), str(value))
                    combo.setCurrentIndex(max(0, combo.findData(current)))
            self.notice.setText("; ".join(str(error) for error in result.get("errors", [])))
            with QSignalBlocker(self.playlists):
                self.playlists.clear()
                for playlist in playlists:
                    self.playlists.addItem(playlist["name"], playlist)
            self.empty.setVisible(not bool(self.rows))
            if not self.rows:
                self.empty.setText(
                    self.tr(
                        "No media matches this view. Add a Library Folder or Refresh folders "
                        "to discover local files, then adjust the search and filters."
                    )
                )
            self._update_panes()
        except Exception as error:
            self.notice.setText(str(error))

    def _update_panes(self) -> None:
        chosen = bool(self.selected_ids())
        active = bool(self.last_source)
        video = self.kind.currentData() == "video"
        collection = self.media_layout == "collection" or not video
        focus = self.media_layout == "focus" and video
        self.hero.setVisible(not collection and bool(self.rows) and chosen)
        self.collection_heading.setVisible(collection)
        self.collection_heading.setText(self.tr("Your collection") if video else self.tr("Music"))
        self.collection_selection.setVisible(collection and chosen)
        self.results.setVisible(not focus and bool(self.rows))
        self.shelf_heading.setVisible(not focus and bool(self.rows))
        self.shelf_heading.setText(
            self.tr("Recently added")
            if self.view.currentData() == "all"
            else self.view.currentText()
        )
        self.page_count.setVisible(bool(self.rows))
        self.previous_page.setVisible(self.offset > 0)
        self.next_page.setVisible(self.next_offset is not None)
        continuation = bool(self.continue_rows) and not collection
        self.continue_heading.setVisible(continuation)
        self.continue_panel.setVisible(continuation)
        for widget in self.detail_widgets:
            widget.setVisible(chosen)
        self.more_episodes.setVisible(chosen and bool(self.detail_row.get("episodes_has_more")))
        self.more_releases.setVisible(chosen and bool(self.detail_row.get("releases_has_more")))
        self.action_bar.setVisible(chosen)
        self.play_button.setVisible(bool(self.detail_row.get("available")))
        self.play_button.setEnabled(bool(self.detail_row.get("available")))
        self.enqueue_button.setEnabled(bool(self.detail_row.get("available")))
        self.preview_button.setVisible(
            chosen
            and self.detail_row.get("kind") == "video"
            and self.detail_row.get("availability") == "unfinished"
        )
        self.refresh_preview.setVisible(
            chosen and self.preview_item == self.detail_row.get("id") and bool(self.preview_id)
        )
        self.player_panel.setVisible(active or bool(self.state["queue"]))
        self.video.setVisible(active and self.current_row.get("kind") == "video")
        self.caption.setVisible(active and bool(self.subtitle_cues))
        for widget in self.playback_widgets:
            widget.setVisible(active)
        for widget in self.queue_widgets:
            widget.setVisible(bool(self.state["queue"]) or self.kind.currentData() == "music")

    def selected_ids(self) -> list[str]:
        return [item.data(Qt.ItemDataRole.UserRole) for item in self.results.selectedItems()]

    def show_detail(self) -> None:
        ids = self.selected_ids()
        if not ids or self.library is None:
            self._update_panes()
            return
        try:
            row = self.library.detail(self.session_client, ids[0])
            self.detail_row = row
            self._show_feature(row)
            info = [row["title"]]
            if row.get("identity_source") == "filename":
                info.append(self.tr("Title and release details guessed from filename"))
            for name in ("year", "genre", "language", "description", "reason"):
                if row.get(name):
                    info.append(str(row[name]))
            if row.get("season") is not None or row.get("episode") is not None:
                info.append(
                    self.tr("Filename metadata: season {0}, episode {1}").format(
                        row.get("season", "?"), row.get("episode", "?")
                    )
                )
            if row["kind"] == "video":
                labels = [str(track["label"]) for track in row.get("subtitles", [])]
                info.append(
                    self.tr("External subtitles: {0}").format(", ".join(labels))
                    if labels
                    else self.tr("No known external subtitles.")
                )
                info.append(self.tr("Embedded subtitle tracks are discovered during playback."))
            self.description.setText("\n".join(info))
            self.watched.setChecked(bool(row.get("watched")))
            for combo, name in ((self.releases, "releases"), (self.episodes, "episodes")):
                combo.clear()
                combo.addItem(
                    self.tr("Choose releases")
                    if name == "releases"
                    else self.tr("Choose episodes"),
                    "",
                )
                for entry in row.get(name, []):
                    combo.addItem(entry.get("release") or entry["title"], entry["id"])
            self.artwork.clear()
            self.preview_button.setVisible(
                row["kind"] == "video" and row.get("availability") == "unfinished"
            )
            self.refresh_preview.setVisible(
                self.preview_item == row["id"] and bool(self.preview_id)
            )
            self._load_artwork([row], detail=True)
            self._update_panes()

        except Exception as error:
            self.notice.setText(str(error))

    def _more_detail(self, name: str) -> None:
        ids = self.selected_ids()
        offset = self.detail_row.get(name + "_next_offset")
        if not ids or offset is None:
            return
        library, client, identifier = self.library, self.session_client, ids[0]
        button = self.more_episodes if name == "episodes" else self.more_releases
        button.setEnabled(False)

        def work():
            return library.detail(client, identifier, **{name + "_offset": offset})

        def done(row):
            if not isValid(self) or ids != self.selected_ids():
                return
            button.setEnabled(True)
            combo = self.episodes if name == "episodes" else self.releases
            for entry in row.get(name, []):
                combo.addItem(entry.get("release") or entry["title"], entry["id"])
            self.detail_row[name + "_next_offset"] = row.get(name + "_next_offset")
            self.detail_row[name + "_has_more"] = row.get(name + "_has_more")
            self._update_panes()

        def failed(error):
            if isValid(self):
                button.setEnabled(True)
                self.notice.setText(str(error))

        run_in_background(work, done, failed)

    def _cache_picture(self, identifier: str, picture: QImage) -> QImage:
        previous = self.picture_cache.pop(identifier, None)
        if previous is not None:
            self._picture_cache_bytes -= previous.sizeInBytes()
            if previous.width() * previous.height() >= picture.width() * picture.height():
                picture = previous
        size = picture.sizeInBytes()
        if size <= self.PICTURE_CACHE_LIMIT:
            self.picture_cache[identifier] = picture
            self._picture_cache_bytes += size
        while self._picture_cache_bytes > self.PICTURE_CACHE_LIMIT:
            _, evicted = self.picture_cache.popitem(last=False)
            self._picture_cache_bytes -= evicted.sizeInBytes()
        # Displayed QImages and QPixmaps own their shared pixels after cache eviction.
        return picture

    def _load_artwork(self, rows: list[dict[str, Any]], *, detail: bool = False) -> None:
        if not detail:
            self.art_stop.set()
            self.art_stop = threading.Event()
            self.art_generation += 1
        generation, stop = self.art_generation, self.art_stop
        library, client = self.library, self.session_client
        selected = self.selected_ids()

        def work():
            images = []
            for row in rows:
                if stop.is_set():
                    break
                if not row.get("artwork_url"):
                    continue
                try:
                    path = library.artwork(client, row["id"])
                    if not path:
                        continue
                    reader = QImageReader(str(path))
                    dimensions = reader.size()
                    if dimensions.width() * dimensions.height() > 32_000_000:
                        continue
                    reader.setScaledSize(
                        dimensions.scaled(
                            1600 if detail else 256,
                            900 if detail else 340,
                            Qt.AspectRatioMode.KeepAspectRatio,
                        )
                    )
                    picture = reader.read()
                    if not picture.isNull():
                        images.append((row["id"], picture))
                except (OSError, ValueError):
                    continue
            return images

        def done(images):
            if not isValid(self) or generation != self.art_generation or stop.is_set():
                return
            for identifier, picture in images:
                cached = self._cache_picture(identifier, picture)
                if identifier == self.featured_id:
                    self.hero.set_picture(cached)
                if detail:
                    if selected == self.selected_ids():
                        self.artwork.setPixmap(
                            QPixmap.fromImage(picture).scaled(
                                160,
                                160,
                                Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation,
                            )
                        )
                else:
                    for index in range(self.results.count()):
                        item = self.results.item(index)
                        if item.data(Qt.ItemDataRole.UserRole) == identifier:
                            item.setIcon(self._cover_icon(picture))
                            break
            self._refresh_focus_strip()
            self._render_continue()

        run_in_background(work, done, lambda _error: None)

    def start_preview(self) -> None:
        ids = self._chosen_ids()
        if not ids:
            return
        identifier = ids[0]
        self.preview_generation += 1
        generation = self.preview_generation
        library, client, session_id = self.library, self.session_client, self.session_id
        self.preview_button.setEnabled(False)
        self.refresh_preview.setEnabled(False)
        self.notice.setText(self.tr("Checking downloaded pieces with qBittorrent…"))

        def work():
            preview = library.create_preview(client, identifier)
            try:
                path, size = library.preview_source(client, preview["preview_id"])
                return preview, path, size
            except Exception:
                library.close_preview(client, preview["preview_id"])
                raise

        def apply_preview(result):
            preview, path, size = result
            if (
                not isValid(self)
                or generation != self.preview_generation
                or self.library is not library
                or self.session_client != client
                or self.session_id != session_id
            ):
                library.close_preview(client, preview["preview_id"])
                return
            self._close_preview()
            self.preview_id = preview["preview_id"]
            self.preview_item = identifier
            self.preview_device = VerifiedPrefixDevice(path, size, self)
            self.preview_checked = time.monotonic()
            self.last_source = identifier
            self.current_row = library.detail(client, identifier)
            self.subtitle_cues = []
            self.caption.clear()
            self.state.update(current_id=identifier, queue=[identifier], index=0)
            self.pending_seek = None
            self.player.setSourceDevice(self.preview_device, QUrl("verified-preview.mp4"))
            self.now_playing.setText(
                self.tr("Preview of downloaded portion · {0}% verified").format(
                    round(100 * preview["progress"])
                )
            )
            self.notice.setText(
                self.tr(
                    "Only downloaded pieces are exposed to the player. "
                    "Refresh preview after more pieces arrive. "
                    "Some formats need the missing end before they can play."
                )
            )
            self.video.show()
            self.external.hide()
            self.preview_button.setEnabled(True)
            self.refresh_preview.setEnabled(True)
            self.refresh_preview.show()
            self._render_queue()
            self.player.play()
            self.report()

        def ready(result):
            try:
                apply_preview(result)
            except Exception as error:
                library.close_preview(client, result[0]["preview_id"])
                self._close_preview()
                failed(error)

        def failed(error):
            if isValid(self) and generation == self.preview_generation:
                self.notice.setText(str(error))
                self.preview_button.setEnabled(True)
                self.refresh_preview.setEnabled(True)

        run_in_background(work, ready, failed)

    def _invalidate_preview_request(self) -> None:
        self.preview_generation += 1
        self.preview_button.setEnabled(True)
        self.refresh_preview.setEnabled(True)

    def _close_preview(self) -> None:
        if self.preview_device is not None:
            self.player.setSource(QUrl())
            self.preview_device.close()
            self.preview_device.deleteLater()
            self.preview_device = None
        if self.preview_id and self.library:
            self.library.close_preview(self.session_client, self.preview_id)
        self.preview_id = ""
        self.preview_item = ""
        self.refresh_preview.hide()

    def _check_preview(self) -> None:
        if self.preview_check_pending or time.monotonic() - self.preview_checked < 5:
            return
        preview_id, library, client = self.preview_id, self.library, self.session_client
        self.preview_check_pending = True
        self.preview_checked = time.monotonic()

        def done(_result):
            if isValid(self):
                self.preview_check_pending = False

        def failed(error):
            if isValid(self):
                self.preview_check_pending = False
                if self.preview_id == preview_id:
                    self._close_preview()
                    self.state["current_id"] = ""
                    self.last_source = ""
                    self.notice.setText(str(error))

        run_in_background(lambda: library.preview_source(client, preview_id), done, failed)

    def _chosen_ids(self) -> list[str]:
        for combo in (self.episodes, self.releases):
            if combo.currentData():
                return [combo.currentData()]
        selected = self.selected_ids()
        view = self.view.currentData()
        if self.kind.currentData() != "music" or view not in {"albums", "artists"}:
            return selected
        ids = []
        for row in self.rows:
            if row["id"] not in selected:
                continue
            filters = (
                {"album_id": row["album_id"]}
                if view == "albums" and row.get("album_id")
                else {"artist": row["artist"]}
                if view == "artists" and row.get("artist")
                else {}
            )
            if not filters:
                ids.append(row["id"])
                continue
            offset = 0
            while len(ids) < 1000:
                page = self.library.listing(
                    self.session_client,
                    kind="music",
                    view="tracks",
                    offset=offset,
                    limit=200,
                    **filters,
                )
                ids.extend(entry["id"] for entry in page["rows"])
                if not page.get("has_more"):
                    break
                offset = page["next_offset"]
        return list(dict.fromkeys(ids))[:1000]

    def play_selected(self) -> None:
        try:
            ids = self._chosen_ids()
            if ids:
                self.command("play", media_ids=ids, index=0)
        except Exception as error:
            self.notice.setText(str(error))

    def enqueue_selected(self) -> None:
        try:
            ids = self._chosen_ids()
            if ids:
                self.queue_disclosure.setChecked(True)
                self.command(
                    "queue", media_ids=[*self.state["queue"], *ids], index=self.state["index"]
                )
        except Exception as error:
            self.notice.setText(str(error))

    def toggle_pause(self) -> None:
        self.command(
            "pause"
            if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
            else "play"
        )

    def command(self, action: str, **values: Any) -> None:
        if self.library is None:
            return
        try:
            if action in {"queue", "pause", "next", "previous"} or (
                action == "play" and (not self.preview_id or "media_ids" in values)
            ):
                self._invalidate_preview_request()
            result = self.library.session(self.session_id, self.token, action=action, **values)
            self._apply_commands(result.get("commands", []))
            self.report()
        except Exception as error:
            self.notice.setText(str(error))

    def _apply_commands(self, commands: list[dict[str, Any]]) -> None:
        for command in commands:
            sequence = int(command["sequence"])
            if sequence <= self.command_ack:
                continue
            action = command["action"]
            if action in {"queue", "pause", "next", "previous"} or (
                action == "play" and (not self.preview_id or "media_ids" in command)
            ):
                self._invalidate_preview_request()
            if action == "play" and self.preview_id and "media_ids" not in command:
                self.player.play()
                self.command_ack = sequence
                continue
            if action in {"play", "queue"}:
                was_playing = self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
                if "media_ids" in command:
                    self.state["queue"] = command["media_ids"]
                    self.state["index"] = command.get("index", 0)
                self._load_current(play=action == "play" or was_playing)
                if action == "play":
                    self.player.play()
            elif action == "pause":
                self.player.pause()
            elif action == "seek":
                self.player.setPosition(int(float(command["position"]) * 1000))
            elif action == "volume":
                self.audio.setVolume(float(command["volume"]))
                self.volume.setValue(round(float(command["volume"]) * 100))
            elif action in {"next", "previous"}:
                self._advance(1 if action == "next" else -1)
            elif action == "shuffle":
                self.state["shuffle"] = bool(command["shuffle"])
                with QSignalBlocker(self.shuffle):
                    self.shuffle.setChecked(self.state["shuffle"])
            elif action == "repeat":
                self.state["repeat"] = command["repeat"]
                with QSignalBlocker(self.repeat):
                    self.repeat.setCurrentIndex(max(0, self.repeat.findData(command["repeat"])))
            self.command_ack = sequence

    def _load_current(self, play: bool) -> None:
        queue = self.state["queue"]
        if not queue:
            self._close_preview()
            self.player.stop()
            self.player.setSource(QUrl())
            self.state.update(current_id="", index=0)
            self.last_source = ""
            self.queue.clear()
            self.now_playing.setText(self.tr("Nothing playing"))
            self._update_panes()
            return
        index = max(0, min(int(self.state["index"]), len(queue) - 1))
        self.state["index"] = index
        identifier = queue[index]
        if identifier != self.last_source or self.preview_id:
            self._invalidate_preview_request()
            path = self.library.resolve(self.session_client, identifier)
            row = self.library.detail(self.session_client, identifier)
            self._close_preview()
            self.last_source = identifier
            self.current_row = row
            self.subtitle_cues = []
            self.caption.clear()
            self.state["current_id"] = identifier
            self.pending_seek = round(float(row.get("position") or 0) * 1000)
            self.external.hide()
            self.now_playing.setText(row["title"])
            self.player.setSource(QUrl.fromLocalFile(str(path)))
            self.video.setVisible(row["kind"] == "video")
        if play:
            self.player.play()
        self._render_queue()

    def _render_queue(self) -> None:
        self.queue.clear()
        for media_id in self.state["queue"]:
            try:
                title = self.library.detail(self.session_client, media_id)["title"]
            except Exception:
                title = self.tr("Unavailable media")
            self.queue.addItem(title)
        self.queue.setCurrentRow(int(self.state["index"]))
        self._update_panes()

    def _advance(self, step: int) -> None:
        queue = self.state["queue"]
        if not queue:
            return
        index = int(self.state["index"]) + step
        if self.state["shuffle"] and len(queue) > 1:
            index = random.choice([i for i in range(len(queue)) if i != self.state["index"]])
        if index >= len(queue) or index < 0:
            if self.state["repeat"] != "all":
                self.player.pause()
                return
            index %= len(queue)
        self.state["index"] = index
        self._load_current(play=True)

    def _queue_play(self, item: QListWidgetItem) -> None:
        self.command("play", media_ids=self.state["queue"], index=self.queue.row(item))

    def remove_from_queue(self) -> None:
        index = self.queue.currentRow()
        if index < 0:
            return
        queue = list(self.state["queue"])
        queue.pop(index)
        current_index = int(self.state["index"])
        if index < current_index:
            current_index -= 1
        self.command("queue", media_ids=queue, index=max(0, min(current_index, len(queue) - 1)))
        if not queue:
            self.player.stop()
            self.player.setSource(QUrl())
            self.last_source = ""
            self.state["current_id"] = ""
            self.queue.clear()

    def _save_playlist(self) -> None:
        if self.library is None or not self.state["queue"]:
            return
        name, ok = QInputDialog.getText(self, self.tr("Playlist"), self.tr("Name"))
        if ok and name.strip():
            try:
                self.library.save_playlist(self.session_client, name.strip(), self.state["queue"])
                self.current_playlist = name.strip()
                self.refresh()
            except Exception as error:
                self.notice.setText(str(error))

    def _load_playlist(self) -> None:
        playlist = self.playlists.currentData()
        if playlist:
            self.current_playlist = playlist["name"]
            self.command("queue", media_ids=playlist["media_ids"], index=0)

    def _delete_playlist(self) -> None:
        playlist = self.playlists.currentData()
        if playlist:
            try:
                self.library.delete_playlist(self.session_client, playlist["id"])
                self.refresh()
            except Exception as error:
                self.notice.setText(str(error))

    def _watched(self, watched: bool) -> None:
        ids = self.selected_ids()
        if ids and self.library:
            try:
                self.library.watched(self.session_client, ids[0], watched)
            except Exception as error:
                self.notice.setText(str(error))

    def report(self) -> None:
        if not self.library:
            return
        try:
            if self.preview_id:
                self._check_preview()
            elif self.state["current_id"]:
                try:
                    self.library.resolve(self.session_client, self.state["current_id"])
                except (OSError, ValueError):
                    self.player.stop()
                    self.player.setSource(QUrl())
                    self.state["current_id"] = ""
                    self.last_source = ""
                    raise
            self.state.update(
                position=self.player.position() / 1000,
                duration=self.player.duration() / 1000,
                paused=self.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState,
                volume=self.audio.volume(),
            )
            result = self.library.session(
                self.session_id,
                self.token,
                report={**self.state, "command_ack": self.command_ack},
                context=self._context(),
            )
            self._apply_commands(result.get("commands", []))
        except Exception as error:
            self.notice.setText(str(error))

    def _position_changed(self, position: int) -> None:
        seconds = position / 1000
        self.caption.setText(
            "\n".join(text for start, end, text in self.subtitle_cues if start <= seconds < end)
        )
        if not self.seek.isSliderDown():
            self.seek.setValue(position // 1000)
        self.elapsed.setText(
            f"{position // 60000}:{position // 1000 % 60:02d} / "
            f"{self.player.duration() // 60000}:{self.player.duration() // 1000 % 60:02d}"
        )

    def _duration_changed(self, duration: int) -> None:
        self.seek.setMaximum(duration // 1000)

    def _media_status(self, status: QMediaPlayer.MediaStatus) -> None:
        if status in {QMediaPlayer.MediaStatus.LoadedMedia, QMediaPlayer.MediaStatus.BufferedMedia}:
            if self.pending_seek is not None:
                self.player.setPosition(self.pending_seek)
                self.pending_seek = None
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            if self.preview_id:
                self.player.pause()
                self.notice.setText(
                    self.tr("End of downloaded portion. Refresh preview after more pieces arrive.")
                )
                return
            if self.state["repeat"] == "one":
                self.player.setPosition(0)
                self.player.play()
            else:
                self._advance(1)

    def _select_subtitle(self) -> None:
        if self.player is None:
            return
        value = self.subtitles.currentData()
        self.subtitle_cues = []
        self.caption.clear()
        self.player.setActiveSubtitleTrack(value if isinstance(value, int) else -1)
        if not isinstance(value, str):
            return
        try:
            data, _mime = self.library.subtitle(self.session_client, self.last_source, value)
            text = data.decode("utf-8-sig", errors="replace").replace("\r", "")
            timing = re.compile(r"(?:(\d+):)?(\d{2}):(\d{2})[.,](\d{3})")
            for block in re.split(r"\n\s*\n", text):
                lines = block.splitlines()
                for index, line in enumerate(lines):
                    if "-->" not in line:
                        continue
                    times = timing.findall(line)
                    if len(times) != 2:
                        continue
                    seconds = [
                        int(hour or 0) * 3600 + int(minute) * 60 + int(second) + int(ms) / 1000
                        for hour, minute, second, ms in times
                    ]
                    caption = re.sub(r"<[^>]*>", "", "\n".join(lines[index + 1 :]))
                    self.subtitle_cues.append((seconds[0], seconds[1], caption))
            self._position_changed(self.player.position())
            self._update_panes()
        except Exception as error:
            self.notice.setText(str(error))

    def _subtitle_tracks(self) -> None:
        with QSignalBlocker(self.subtitles):
            self.subtitles.clear()
            self.subtitles.addItem(self.tr("Subtitles off"), -1)
            for index, _track in enumerate(self.player.subtitleTracks()):
                self.subtitles.addItem(self.tr("Embedded subtitle {0}").format(index + 1), index)
            for subtitle in self.current_row.get("subtitles", []):
                self.subtitles.addItem(subtitle["label"], subtitle["id"])
        self.player.setActiveSubtitleTrack(-1)

    def _codec_error(self, *_args: Any) -> None:
        if self.player.error() != QMediaPlayer.Error.NoError:
            self.notice.setText(
                (
                    self.tr(
                        "Preview cannot play yet. "
                        "This format may need the missing end of the file. "
                        "Wait and refresh preview. "
                    )
                    if self.preview_id
                    else self.tr("Playback failed. This format or codec may be unsupported. ")
                )
                + self.player.errorString()
            )
            self.external.setVisible(not bool(self.preview_id))

    def open_external(self) -> None:
        if self.library and self.state["current_id"] and not self.preview_id:
            try:
                path = self.library.resolve(self.session_client, self.state["current_id"])
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
            except Exception as error:
                self.notice.setText(str(error))

    def start_scan(self) -> None:
        if self.library is None or self.scan_stop is not None:
            return
        self.scan_stop = threading.Event()
        stop = self.scan_stop
        self.refresh_button.setEnabled(False)
        self.cancel_scan.setEnabled(True)
        self.notice.setText(self.tr("Scanning Library Folders…"))
        run_in_background(
            lambda: self.library.scan(self.session_client, stop, self.scan_progress.emit),
            self._scan_done,
            self._scan_failed,
        )

    def _scan_done(self, _result: Any) -> None:
        if not isValid(self):
            return
        self.scan_stop = None
        self.refresh_button.setEnabled(True)
        self.cancel_scan.setEnabled(False)
        self.refresh()

    def _scan_failed(self, error: Exception) -> None:
        if not isValid(self):
            return
        self._scan_done(None)
        self.notice.setText(str(error))

    def open_chat(self) -> None:
        if self.library is None:
            return
        try:
            self.report()
            self.conversation_id = self.service.media_chat(
                self.session_id,
                self.token,
                self.conversation_id,
            )["conversation_id"]
            if self.credentials:
                self.credentials.setValue("conversation", self.conversation_id)
                self.credentials.sync()
            if self.assistant is None:
                from torrentlinker.gui.assistant import AssistantTab

                self.assistant = AssistantTab(self.get_service)
                close_chat = QPushButton(self.tr("Close chat"))
                close_chat.clicked.connect(self.assistant.hide)
                self.assistant.layout().insertWidget(0, close_chat)
                self.splitter.addWidget(self.assistant)
                self.splitter.setSizes([700, 500])
            self.assistant.show()
            self.assistant.activate()
            self.assistant.select_conversation(self.conversation_id)
            self.assistant.prompt.setFocus()
        except Exception as error:
            self.notice.setText(str(error))

    def stop(self) -> None:
        self._invalidate_preview_request()
        if self.player is None or not self.heartbeat.isActive():
            return
        if self.scan_stop:
            self.scan_stop.set()
        self.player.pause()
        self.report()
        self.heartbeat.stop()
        self.player.stop()
        self._close_preview()
        self.art_stop.set()
