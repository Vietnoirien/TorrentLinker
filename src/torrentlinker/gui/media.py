"""Native media browsing and playback, backed by the shared saved inventory."""

from __future__ import annotations

import random
import re
import threading
import time
from collections.abc import Callable
from functools import partial
from typing import Any
from uuid import uuid4

from PySide6.QtCore import (
    QEvent,
    QFile,
    QIODevice,
    QLocale,
    QObject,
    QRect,
    QRectF,
    QSettings,
    QSignalBlocker,
    QSize,
    QSizeF,
    Qt,
    QThread,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QActionGroup,
    QColor,
    QDesktopServices,
    QFont,
    QFontMetrics,
    QIcon,
    QPainter,
    QTextDocumentFragment,
)
from PySide6.QtMultimedia import (
    QMediaMetaData,
    QMediaPlayer,
    QVideoFrame,
    QVideoFrameFormat,
    QVideoSink,
)
from PySide6.QtMultimediaWidgets import QGraphicsVideoItem
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QGraphicsDropShadowEffect,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QSlider,
    QSplitter,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from torrentlinker.gui.controls import set_role
from torrentlinker.gui.media_audio import create_audio_output
from torrentlinker.gui.media_browser import MediaBrowserPanel
from torrentlinker.gui.tasks import run_in_background

# The Media Center chat panel and the media beside it never shrink below these.
CHAT_MIN_WIDTH = 320
MEDIA_MIN_WIDTH = 560
PREVIEW_WAIT_SECONDS = 300.0  # how long playback waits for the next downloaded pieces
PREVIEW_WAIT_AHEAD = 64 * 1024 * 1024  # how far past the downloaded part a read waits
AUTO_REFRESH_MS = 60_000  # Media rescans the Library Folders this often while open


class DownloadingFileDevice(QIODevice):
    """A read-only, seekable view of a file qBittorrent is downloading, like qBittorrent's own
    preview: the player sees the whole file, but only verified pieces are ever read.

    A read just past the downloaded part waits for the next pieces; a read far ahead (an
    index at the end of the file) finds nothing until its pieces arrive. Qt reads off the GUI
    thread, so waiting never freezes the window; abort() ends a wait before the player stops.
    """

    def __init__(self, path, size: int, piece_size: int, pieces, parent=None) -> None:
        super().__init__(parent)
        self.file = QFile(str(path))
        self.total, self.piece_size = int(size), int(piece_size)
        self.pieces = list(pieces)
        self.changed = threading.Condition()
        self.aborted = False
        self.stalled = False  # no new pieces within PREVIEW_WAIT_SECONDS: the preview ends
        if not self.file.open(QIODevice.OpenModeFlag.ReadOnly):
            raise ValueError("The preview file cannot be opened read-only.")
        if self.total <= 0 or self.piece_size <= 0 or not self.available(0):
            self.file.close()
            raise ValueError("The start of this file is not downloaded yet.")
        self.open(QIODevice.OpenModeFlag.ReadOnly | QIODevice.OpenModeFlag.Unbuffered)

    def update(self, pieces) -> None:
        """qBittorrent verified more pieces: wake a read waiting for them."""
        with self.changed:
            self.pieces = list(pieces)
            self.changed.notify_all()

    def abort(self) -> None:
        with self.changed:
            self.aborted = True
            self.changed.notify_all()

    def available(self, position: int) -> int:
        """Verified bytes from `position` on, up to the next missing piece."""
        piece = position // self.piece_size
        last = piece
        while last < len(self.pieces) and self.pieces[last]:
            last += 1
        return max(0, min(self.total, last * self.piece_size) - position)

    def downloaded(self) -> int:
        """The verified bytes from the start of the file."""
        return self.available(0)

    def isSequential(self) -> bool:
        return False

    def size(self) -> int:
        return self.total

    def seek(self, position: int) -> bool:
        if position < 0 or position > self.total:
            return False
        return super().seek(position)

    def bytesAvailable(self) -> int:
        return self.available(self.pos())

    def gives_up(self, position: int) -> bool:
        """Whether a read here ends instead of waiting for pieces."""
        return (
            self.aborted
            or self.stalled
            or position >= self.total
            or not self.available(position)
            and position > self.downloaded() + PREVIEW_WAIT_AHEAD
        )

    def atEnd(self) -> bool:
        # Qt's FFmpeg reader ends only when atEnd() says so: an empty read alone makes
        # it read again, forever.
        return self.gives_up(self.pos())

    def readData(self, maximum: int) -> bytes:
        position = self.pos()
        deadline = time.monotonic() + PREVIEW_WAIT_SECONDS
        with self.changed:
            while not (count := self.available(position)):
                if self.gives_up(position):
                    return b""
                if time.monotonic() >= deadline:
                    self.stalled = True
                    return b""
                self.changed.wait(0.5)
        if not self.file.seek(position):
            return b""
        return bytes(self.file.read(min(max(0, maximum), count)).data())

    def writeData(self, _data: bytes | bytearray | memoryview, _length: int) -> int:
        return -1

    def close(self) -> None:
        self.abort()
        super().close()
        self.file.close()


class MediaTileButton(QPushButton):
    def sizeHint(self):
        return self.layout().sizeHint() if self.layout() else super().sizeHint()

    def minimumSizeHint(self):
        return self.layout().minimumSize() if self.layout() else super().minimumSizeHint()


# Frame layouts DisplayFrames can halve: bytes per sample, and whether chroma is interleaved.
HALVABLE = {
    QVideoFrameFormat.PixelFormat.Format_P010: (2, True),
    QVideoFrameFormat.PixelFormat.Format_P016: (2, True),
    QVideoFrameFormat.PixelFormat.Format_NV12: (1, True),
    QVideoFrameFormat.PixelFormat.Format_NV21: (1, True),
    QVideoFrameFormat.PixelFormat.Format_YUV420P: (1, False),
    QVideoFrameFormat.PixelFormat.Format_YUV420P10: (2, False),
    QVideoFrameFormat.PixelFormat.Format_YV12: (1, False),
}


class DisplayFrames(QObject):
    """Prepares decoded frames for the picture, on the frame thread.

    The picture converts every frame on the GUI thread; a 4K frame took about 50 ms there,
    longer than a 24 fps frame lasts, so playback stuttered. While a frame is at least twice
    the picture's size it is halved first, a quarter of the work.

    Qt also draws HDR10 with two faults. It reads the mastering peak brightness 10,000 times
    too high, so highlights clip; and converting BT.2020's most saturated reds overflows into
    black blotches. HDR10 frames get the real peak and the BT.601 matrix, whose conversion
    stays in range at the cost of a slight hue shift.

    Frames reach convert() queued: Qt's video thread only posts them, so it never waits for
    the interpreter lock, which the GUI thread may hold while stopping it.
    """

    ready = Signal(QVideoFrame)

    def __init__(self) -> None:
        super().__init__()
        self.size = QSize()  # the picture, in device pixels; set from the GUI thread

    def convert(self, frame: QVideoFrame) -> None:
        self.ready.emit(self.prepared(frame, self.size))

    @staticmethod
    def prepared(frame: QVideoFrame, size: QSize = QSize()) -> QVideoFrame:
        source = frame.surfaceFormat()
        hdr = source.colorTransfer() == QVideoFrameFormat.ColorTransfer.ColorTransfer_ST2084
        layout = HALVABLE.get(source.pixelFormat())
        step = 1
        while (
            layout
            and size.width() > 0
            and frame.width() // (step * 2) >= size.width()
            and frame.height() // (step * 2) >= size.height()
        ):
            step *= 2
        if step == 1 and not hdr:
            return frame
        target = QVideoFrameFormat(source)
        if step > 1:
            target.setFrameSize(QSize(frame.width() // step & ~1, frame.height() // step & ~1))
            target.setViewport(QRect(0, 0, target.frameWidth(), target.frameHeight()))
        if hdr:
            if target.maxLuminance() > 10_000:  # 1,000 nits read as 10,000,000
                target.setMaxLuminance(target.maxLuminance() / 10_000)
            target.setColorSpace(QVideoFrameFormat.ColorSpace.ColorSpace_BT601)
        copy = QVideoFrame(target)
        if not frame.map(QVideoFrame.MapMode.ReadOnly):
            return frame
        try:
            if not copy.map(QVideoFrame.MapMode.WriteOnly):
                return frame
            if layout:
                DisplayFrames._sample(frame, copy, step, *layout)
            else:
                DisplayFrames._copy(frame, copy)
            copy.unmap()
        finally:
            frame.unmap()
        copy.setStartTime(frame.startTime())
        copy.setEndTime(frame.endTime())
        return copy

    @staticmethod
    def _plane(video: QVideoFrame, plane: int, rows: int, dtype):
        import numpy

        line = video.bytesPerLine(plane) // numpy.dtype(dtype).itemsize
        bits = numpy.frombuffer(video.bits(plane), dtype)
        rows = min(rows, bits.size // line)
        return bits[: rows * line].reshape(rows, line)

    @staticmethod
    def _sample(frame, copy, step: int, size: int, interleaved: bool) -> None:
        """Every step-th sample of each plane; numpy releases the interpreter lock."""
        import numpy

        dtype = numpy.uint16 if size == 2 else numpy.uint8
        width, height = copy.width(), copy.height()
        planes = [(0, height, width, 1)]
        planes += (
            [(1, height // 2, width // 2, 2)]
            if interleaved
            else [(1, height // 2, width // 2, 1), (2, height // 2, width // 2, 1)]
        )
        for plane, rows, columns, channels in planes:
            source = DisplayFrames._plane(frame, plane, rows * step, dtype)[::step]
            target = DisplayFrames._plane(copy, plane, rows, dtype)
            rows = min(rows, source.shape[0], target.shape[0])
            # Rows of (sample, channel): an interleaved chroma pair moves as one sample.
            picked = source[:rows, : columns * step * channels]
            picked = picked.reshape(rows, columns * step, channels)[:, ::step]
            placed = target[:rows, : columns * channels].reshape(rows, columns, channels)
            numpy.copyto(placed, picked)

    @staticmethod
    def _copy(frame, copy) -> None:
        import numpy

        for plane in range(frame.planeCount()):
            source = numpy.frombuffer(frame.bits(plane), numpy.uint8)
            target = numpy.frombuffer(copy.bits(plane), numpy.uint8)
            source_line, target_line = frame.bytesPerLine(plane), copy.bytesPerLine(plane)
            if source_line == target_line:
                count = min(source.size, target.size)
                numpy.copyto(target[:count], source[:count])
                continue
            rows = min(source.size // source_line, target.size // target_line)
            width = min(source_line, target_line)
            numpy.copyto(
                target[: rows * target_line].reshape(rows, target_line)[:, :width],
                source[: rows * source_line].reshape(rows, source_line)[:, :width],
            )


_FRAME_THREAD: QThread | None = None


def frame_thread() -> QThread:
    """The one thread that prepares frames, for every player; it stops when Python exits."""
    global _FRAME_THREAD
    if _FRAME_THREAD is None:
        import atexit

        _FRAME_THREAD = QThread()
        _FRAME_THREAD.setObjectName("TorrentLinker frames")
        _FRAME_THREAD.start()
        atexit.register(_stop_frame_thread)
    return _FRAME_THREAD


def _stop_frame_thread() -> None:
    if _FRAME_THREAD is not None and isValid(_FRAME_THREAD):
        _FRAME_THREAD.quit()
        _FRAME_THREAD.wait(5000)


class VideoSurface(QGraphicsView):
    """Qt video rendering and ordinary widget controls share one composited surface."""

    def __init__(self, parent=None):
        super().__init__(parent)
        scene = QGraphicsScene(self)
        self.setScene(scene)
        self.item = QGraphicsVideoItem()
        scene.addItem(self.item)
        self.frames: DisplayFrames | None = None
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setBackgroundBrush(QColor("black"))
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self.overlay = QWidget(self.viewport())
        self.overlay.setObjectName("mediaVideoOverlay")
        self.overlay.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.overlay.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        rect = self.viewport().rect()
        self.setSceneRect(QRectF(rect))
        self.item.setSize(QSizeF(rect.size()))
        self.overlay.setGeometry(rect)
        self.overlay.raise_()
        self.measure()

    def measure(self) -> None:
        """Tell the frame preparer how many device pixels the picture covers."""
        if self.frames is not None:
            ratio = self.devicePixelRatioF()
            size = self.viewport().size()
            self.frames.size = QSize(round(size.width() * ratio), round(size.height() * ratio))


class MediaTab(QWidget):
    """One native player session whose lifetime is independent of browsing and chat."""

    PICTURE_CACHE_LIMIT = 24 * 1024 * 1024

    scan_progress = Signal(object)
    # A video plays: background work that would hold the interpreter lock should wait,
    # or the frame thread misses frames.
    video_playing_changed = Signal(bool)
    layout_changed = Signal(str)
    center_mode_requested = Signal(bool)
    connections_requested = Signal()

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
        self.conversation_id = ""
        self.current_playlist = ""
        self.assistant: Any = None
        self.scan_stop: threading.Event | None = None
        self.scan_quiet = False  # an automatic refresh shows no progress
        self.pending_seek: int | None = None
        self.last_source = ""
        self.current_row: dict[str, Any] = {}
        self.subtitle_cues: list[tuple[float, float, str]] = []
        self.track_source_token = ""
        self.tracks_ready = False
        self.track_result: dict[str, Any] = {}
        self.last_track_failure: tuple[str, str] | None = None
        self.audio_choice: int | None = None
        self.subtitle_choice: int | str = -1
        self.preview_id = ""
        self.preview_item = ""
        self.preview_device: DownloadingFileDevice | None = None
        self.preview_generation = 0
        self.preview_checked = 0.0
        self.preview_check_pending = False
        self.player: Any = None
        self.audio: Any = None
        self.video = VideoSurface(self)
        self.embedded_caption = ""
        self._player_video_mode = False

        self.browser: MediaBrowserPanel | None = None
        self.browse_kind = "video"
        self.browse_selection: list[str] = []
        self.browse_context: dict[str, Any] = {}
        self.queue_music = True
        self._build_presentation(add_folder)

    def _build_presentation(self, add_folder) -> None:
        self.media_layout = "cinematic"
        self.adult = False  # the XXX tab, once adult content is enabled in Settings
        self.video_playing = False
        # The app refreshes the library the first time Media opens after it starts.
        self.refresh_on_first_open = False
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.setObjectName("mediaWorkspace")
        self.setStyleSheet("""
            QWidget#mediaWorkspace { background: #101315; color: #f1f3ef; }
            /* The Media Center is always dark: it recolors the shared button roles
               (gui/controls.py) and keeps their shapes. */
            QWidget#mediaWorkspace QPushButton, QWidget#mediaWorkspace QToolButton {
                background: rgba(255, 255, 255, 22); color: #eef2ef;
                border: 1px solid rgba(255, 255, 255, 34); }
            QWidget#mediaWorkspace QPushButton:hover, QWidget#mediaWorkspace QToolButton:hover {
                background: rgba(255, 255, 255, 38); border-color: #79d3c5; }
            QWidget#mediaWorkspace QPushButton:disabled,
            QWidget#mediaWorkspace QToolButton:disabled {
                background: rgba(255, 255, 255, 10); color: #75817f;
                border-color: rgba(255, 255, 255, 18); }
            QWidget#mediaWorkspace [role="primary"] { background: #eff3ed; color: #13211f;
                border-color: #eff3ed; font-weight: 650; }
            QWidget#mediaWorkspace [role="primary"]:hover { background: #ffffff;
                border-color: #79d3c5; }
            QWidget#mediaWorkspace [role="quiet"], QWidget#mediaWorkspace [role="icon"] {
                background: transparent; border-color: transparent; color: #c9d3d1; }
            QWidget#mediaWorkspace [role="quiet"]:hover,
            QWidget#mediaWorkspace [role="icon"]:hover {
                background: rgba(255, 255, 255, 30); border-color: transparent; color: #f3f6f4; }
            QWidget#mediaWorkspace [role="icon"]:checked { background: #203d39;
                border-color: #79d3c5; color: #93dfce; }
            QWidget#mediaWorkspace [role="tab"] { background: transparent; color: #b8c2c1;
                border: 0; border-bottom: 2px solid transparent; }
            QWidget#mediaWorkspace [role="tab"]:hover { color: #f0f5f1; background: transparent; }
            QWidget#mediaWorkspace [role="tab"]:checked { color: #f0f5f1;
                border-bottom: 2px solid #79d3c5; }
        """)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(self.splitter)
        left = QWidget()
        left_box = QVBoxLayout(left)
        left_box.setContentsMargins(0, 0, 0, 0)
        left_box.setSpacing(0)
        self.splitter.addWidget(left)
        self.media_column = left
        self.media_column_layout = left_box
        left.installEventFilter(self)
        widget: QWidget
        # Browsing is the shared bundled view; these hidden controls keep the host state.
        self.chat = QPushButton("✦", self)
        self.chat.setCheckable(True)
        self.chat.hide()
        self.center_button = QPushButton("⤢", self)
        self.center_button.setCheckable(True)
        self.center_button.clicked.connect(lambda checked: self.center_mode_requested.emit(checked))
        self.center_button.hide()
        self.folder_button = QPushButton(self.tr("Add folder…"), self)
        self.folder_button.clicked.connect(add_folder)
        self.folder_button.hide()
        self.notice = QLabel()
        self.notice.setWordWrap(True)
        self.notice.hide()
        left_box.addWidget(self.notice)
        self.refresh_preview = QPushButton(self.tr("Refresh preview"))
        set_role(self.refresh_preview, "quiet")
        self.refresh_preview.clicked.connect(self.start_preview)
        self.refresh_preview.hide()
        self.player_panel = QWidget()
        self.player_home_layout = left_box
        self.player_base_layout = left_box
        self.fullscreen_dialog = QDialog(self)
        self.fullscreen_dialog.setWindowTitle(self.tr("Media player"))
        self.fullscreen_layout = QVBoxLayout(self.fullscreen_dialog)
        self.fullscreen_layout.setContentsMargins(0, 0, 0, 0)
        self.fullscreen_dialog.finished.connect(self._leave_fullscreen)
        player_box = QVBoxLayout(self.player_panel)
        self.player_box = player_box
        player_box.setContentsMargins(12, 8, 12, 8)
        player_box.setSpacing(6)
        self.video.setMinimumHeight(300)
        player_box.addWidget(self.video, 1)
        self.video_overlay_box = QVBoxLayout(self.video.overlay)
        self.video_overlay_box.setContentsMargins(0, 0, 0, 0)
        self.player_back = QToolButton()
        self.player_back.setText("←")
        self.player_back.setToolTip(self.tr("Home"))
        self.player_back.setAccessibleName(self.tr("Home"))
        self.player_back.clicked.connect(self.dismiss_video)
        set_role(self.player_back, "icon")
        self.video_overlay_box.addWidget(self.player_back, 0, Qt.AlignmentFlag.AlignLeft)
        self.video_overlay_box.addStretch()
        self.caption = QLabel()
        self.caption.setTextFormat(Qt.TextFormat.PlainText)
        self.caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.caption.setWordWrap(True)
        # Outlined text instead of a box, sized to the picture in _scale_caption.
        outline = QGraphicsDropShadowEffect(self.caption)
        outline.setOffset(0, 0)
        outline.setBlurRadius(8)
        outline.setColor(QColor(0, 0, 0, 255))
        self.caption.setGraphicsEffect(outline)
        self.caption.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.video.overlay.installEventFilter(self)
        self._scale_caption()
        self.video_overlay_box.addWidget(self.caption, 0, Qt.AlignmentFlag.AlignHCenter)
        self.video_controls = QWidget()
        self.video_controls.setObjectName("mediaVideoControls")
        self.video_controls.setStyleSheet("""
            QWidget#mediaVideoControls { background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                stop:0 rgba(0,0,0,50),stop:1 rgba(0,0,0,210)); color: white; }
            QWidget#mediaVideoControls [role="icon"] { color: white; }
        """)
        controls_box = QVBoxLayout(self.video_controls)
        controls_box.setContentsMargins(14, 10, 14, 8)
        controls_box.setSpacing(5)
        self.seek = QSlider(Qt.Orientation.Horizontal)
        self.seek.setAccessibleName(self.tr("Seek"))
        self.seek.setRange(0, 0)
        self.seek.sliderReleased.connect(lambda: self.command("seek", position=self.seek.value()))
        controls_box.addWidget(self.seek)
        self.transport = QHBoxLayout()
        controls_box.addLayout(self.transport)
        self.previous_button = QPushButton()
        self.previous_button.clicked.connect(lambda: self._transport_step(-1))
        self.pause = QPushButton()
        self.pause.setAccessibleName(self.tr("Play / pause"))
        self.pause.clicked.connect(self.toggle_pause)
        self.next_button = QPushButton()
        self.next_button.clicked.connect(lambda: self._transport_step(1))
        previous, next_button = self.previous_button, self.next_button
        self.now_playing = QLabel(self.tr("Nothing playing"))
        self.now_playing.setTextFormat(Qt.TextFormat.PlainText)
        self.player_heading = QWidget()
        self.player_heading_box = QVBoxLayout(self.player_heading)
        self.player_heading_box.setContentsMargins(8, 8, 8, 8)
        self.player_heading_box.addWidget(self.now_playing)
        self.playing_description = QLabel()
        self.playing_description.setTextFormat(Qt.TextFormat.PlainText)
        self.playing_description.setWordWrap(True)
        self.player_heading_box.addWidget(self.playing_description)
        self.preview_refresh_home = QHBoxLayout()
        self.preview_refresh_home.addWidget(self.refresh_preview)
        self.player_heading_box.addLayout(self.preview_refresh_home)
        player_box.addWidget(self.player_heading)
        self.elapsed = QLabel("0:00 / 0:00")
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(100)
        self.volume.setMaximumWidth(90)
        self.volume.setAccessibleName(self.tr("Volume"))
        self.volume.setToolTip(self.tr("Volume"))
        self.volume.sliderReleased.connect(
            lambda: self.command("volume", volume=self.volume.value() / 100)
        )
        for widget in (previous, self.pause, next_button, self.elapsed, self.volume):
            self.transport.addWidget(widget)
        self.transport.addStretch()
        self.fullscreen_button = QPushButton()
        self.fullscreen_button.setObjectName("media-fullscreen")
        self.fullscreen_button.clicked.connect(self.toggle_fullscreen)
        self.player_options = QToolButton()
        self.player_options.setText("⋯")
        self.player_options.setAccessibleName(self.tr("Player options"))
        self.player_options.setToolTip(self.tr("Player options"))
        self.player_options.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.player_menu = QMenu(self.player_options)
        self.player_options.setMenu(self.player_menu)
        self.audio_menu = self.player_menu.addMenu(self.tr("Audio track"))
        self.subtitle_menu = self.player_menu.addMenu(self.tr("Subtitle track"))
        self.repeat_menu = self.player_menu.addMenu(self.tr("Repeat off"))
        self.shuffle_action = self.player_menu.addAction(self.tr("Shuffle"))
        self.shuffle_action.setCheckable(True)
        self.shuffle_action.triggered.connect(
            lambda checked: self.command("shuffle", shuffle=checked)
        )
        self.queue_action = self.player_menu.addAction(self.tr("Queue & playlists"))
        self.queue_action.setCheckable(True)
        self.player_menu.aboutToShow.connect(self._build_player_menu)
        self.player_menu.aboutToShow.connect(self._show_video_controls)
        self.player_menu.aboutToHide.connect(self._show_video_controls)
        self.transport.addWidget(self.player_options)
        self.transport.addWidget(self.fullscreen_button)
        for widget in (
            previous,
            self.pause,
            next_button,
            self.player_options,
            self.fullscreen_button,
        ):
            set_role(widget, "icon")
            widget.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.fullscreen_button.setObjectName("media-fullscreen")
        self.fullscreen_button.setIcon(
            self._player_icon(QStyle.StandardPixmap.SP_TitleBarMaxButton)
        )
        self.fullscreen_button.setToolTip(self.tr("Fullscreen"))
        self.fullscreen_button.setAccessibleName(self.tr("Fullscreen"))
        self.video_overlay_box.addWidget(self.video_controls)
        self.music_controls_home = QVBoxLayout()
        self.music_controls_home.setContentsMargins(0, 0, 0, 0)
        player_box.addLayout(self.music_controls_home)
        self.shuffle = QCheckBox(self.tr("Shuffle"), self.player_panel)
        self.shuffle.clicked.connect(lambda on: self.command("shuffle", shuffle=on))
        self.repeat = QComboBox(self.player_panel)
        for label, value in (
            (self.tr("Repeat off"), "off"),
            (self.tr("Repeat all"), "all"),
            (self.tr("Repeat one"), "one"),
        ):
            self.repeat.addItem(label, value)
        self.repeat.currentIndexChanged.connect(
            lambda: self.command("repeat", repeat=self.repeat.currentData())
        )
        self.audio_tracks = QComboBox(self.player_panel)
        self.audio_tracks.setAccessibleName(self.tr("Audio track"))
        self.audio_tracks.currentIndexChanged.connect(self._select_audio)
        self.subtitles = QComboBox(self.player_panel)
        self.subtitles.setAccessibleName(self.tr("Subtitle track"))
        self.subtitles.addItem(self.tr("Subtitles off"), -1)
        self.subtitles.currentIndexChanged.connect(self._select_subtitle)
        self.queue_disclosure = QPushButton(self.tr("Queue & playlists"), self.player_panel)
        self.queue_disclosure.setCheckable(True)
        self.queue_action.triggered.connect(
            lambda checked: self.queue_disclosure.setChecked(checked)
        )
        for widget in (
            self.shuffle,
            self.repeat,
            self.audio_tracks,
            self.subtitles,
            self.queue_disclosure,
        ):
            widget.hide()
        self.click_timer = QTimer(self)
        self.click_timer.setSingleShot(True)
        self.click_timer.timeout.connect(self.toggle_pause)
        self._swallow_release = False
        self.controls_timer = QTimer(self)
        self.controls_timer.setSingleShot(True)
        self.controls_timer.setInterval(2200)
        self.controls_timer.timeout.connect(self._hide_video_controls)
        for widget in (
            self.video,
            self.video.viewport(),
            self.video.overlay,
            self.video_controls,
            *self.video_controls.findChildren(QWidget),
        ):
            widget.installEventFilter(self)
        self._playback_controls_changed()
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
        self.playlists.setPlaceholderText(self.tr("Saved playlists"))
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
            self.audio_tracks,
            self.subtitles,
            self.fullscreen_button,
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
        self.scan_progress.connect(self._scan_progress)
        self.chat.clicked.connect(self.toggle_chat)
        self.heartbeat = QTimer(self)
        self.heartbeat.setInterval(1000)
        self.heartbeat.timeout.connect(self.report)
        # New films and episodes appear on their own while Media is open.
        self.auto_refresh = QTimer(self)
        self.auto_refresh.setInterval(AUTO_REFRESH_MS)
        self.auto_refresh.timeout.connect(self._auto_scan)
        self.set_media_layout("cinematic")
        self._update_panes()

    def _set_notice(self, text: str) -> None:
        self.notice.setText(text)
        browsing = self.browser is not None and self.browser.isVisible()
        self.notice.setVisible(bool(text) and not browsing)
        if browsing and self.browser is not None:
            self.browser.show_notice(text)

    def _open_queue(self) -> None:
        self.queue_disclosure.setChecked(True)
        self._update_panes()
        self.queue.setFocus()

    def set_adult(self, enabled: bool) -> None:
        """Show or hide the XXX tab (Settings → Adult content)."""
        if enabled == self.adult:
            return
        self.adult = enabled
        if self.browser is not None:
            self.browser.activate()

    def set_media_layout(self, value: str) -> None:
        value = value if value in {"cinematic", "focus", "collection"} else "cinematic"
        self.media_layout = value
        if self.browser is not None:
            self.browser.layout_value = value
            self.browser.activate()

    def set_center_mode(self, enabled: bool) -> None:
        if self.browser is not None:
            self.browser.center_mode = enabled
            self.browser.publish()
        self.center_button.setChecked(enabled)
        self.center_button.setText("↩" if enabled else "⤢")
        label = self.tr("Return to TorrentLinker") if enabled else self.tr("Media Center mode")
        self.center_button.setAccessibleName(label)
        self.center_button.setToolTip(label)

    def _transport_step(self, direction: int) -> None:
        if self._player_video_mode:
            self.command("seek", position=max(0, self.player.position() / 1000 + direction * 10))
        else:
            self.command("next" if direction > 0 else "previous")

    def _player_icon(self, standard: QStyle.StandardPixmap) -> QIcon:
        pixmap = self.style().standardIcon(standard).pixmap(24, 24)
        painter = QPainter(pixmap)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        painter.fillRect(pixmap.rect(), QColor("white"))
        painter.end()
        return QIcon(pixmap)

    def _playback_controls_changed(self, *_args) -> None:
        playing = (
            self.player is not None
            and self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        )
        self.pause.setIcon(
            self._player_icon(
                QStyle.StandardPixmap.SP_MediaPause
                if playing
                else QStyle.StandardPixmap.SP_MediaPlay
            )
        )
        self.pause.setToolTip(self.tr("Pause") if playing else self.tr("Play"))
        video = playing and self.current_row.get("kind") != "music"
        if video != self.video_playing:
            self.video_playing = video
            self.video_playing_changed.emit(video)
        self._show_video_controls()
        if self.browse_kind == "video" and self.current_row.get("kind") == "music":
            self._update_panes()  # the music bar follows play and pause while in Video

    def _scale_caption(self) -> None:
        self._fit_caption()

    def _fit_caption(self) -> None:
        """Size subtitles to the picture as it is now, and give every wrapped line room.

        The label gets the exact width it is measured at, so it never wraps onto more
        lines than its height allows; a long cue shrinks rather than leave the picture.
        """
        height = self.video.overlay.height() or 480
        width = max(200, self.video.overlay.width() * 9 // 10)
        text = self.caption.text()
        flags = int(Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap)
        size = max(16, min(56, height // 20))
        while True:
            font = QFont(self.caption.font())
            font.setPixelSize(size)
            font.setWeight(QFont.Weight.DemiBold)
            lines = QFontMetrics(font).boundingRect(QRect(0, 0, width, 100000), flags, text)
            if size <= 12 or lines.height() <= height * 2 // 5:
                break
            size -= 2
        if getattr(self, "caption_size", None) != size:
            self.caption_size = size
            # The page stylesheet would override a font set in code, so the size goes here.
            self.caption.setStyleSheet(
                f"color: white; background: transparent; font-size: {size}px; font-weight: 600;"
            )
        self.caption.setContentsMargins(0, 0, 0, size // 2)
        self.caption.setFixedWidth(width)
        self.caption.setFixedHeight(lines.height() + size // 2 + 4)

    def _show_video_controls(self) -> None:
        self.video_controls.show()
        self.player_back.show()
        if self._player_video_mode:
            self.video.viewport().unsetCursor()
            self.controls_timer.start()

    def _hide_video_controls(self) -> None:
        focus = QApplication.focusWidget()
        if not self._player_video_mode:
            self.controls_timer.stop()
            return
        if (
            self.player is None
            or self.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState
            or self.player_menu.isVisible()
            or (focus is not None and self.video_controls.isAncestorOf(focus))
        ):
            self.controls_timer.start()
            return
        self.video_controls.hide()
        self.player_back.hide()
        self.video.viewport().setCursor(Qt.CursorShape.BlankCursor)

    def _choose_menu_track(
        self, kind: str, identifier: str, token: str, media_id: str, _checked: bool = False
    ) -> None:
        if token != self.track_source_token or media_id != self.last_source:
            self.player_menu.close()
            return
        self.report()
        if token == self.track_source_token and media_id == self.last_source:
            self.command("select_track", kind=kind, track_id=identifier, source_token=token)

    def _build_player_menu(self) -> None:
        snapshot = self._track_state()
        token, media_id = snapshot["source_token"], snapshot["media_id"]
        for kind, menu, rows in (
            ("audio", self.audio_menu, snapshot["audio"]),
            ("subtitle", self.subtitle_menu, snapshot["subtitles"]),
        ):
            menu.clear()
            for previous_group in menu.findChildren(QActionGroup):
                previous_group.deleteLater()
            group = QActionGroup(menu)
            choices = (
                [
                    {
                        "id": "off",
                        "label": self.tr("Subtitles off"),
                        "selected": not any(row["selected"] for row in rows),
                    }
                ]
                if kind == "subtitle"
                else []
            ) + rows
            for row in choices:
                action = menu.addAction(row["label"])
                action.setCheckable(True)
                action.setChecked(row["selected"])
                action.setData(row["id"])
                group.addAction(action)
                action.triggered.connect(
                    partial(self._choose_menu_track, kind, row["id"], token, media_id)
                )
            menu.setEnabled(snapshot[f"{kind}_supported"])
        self.repeat_menu.clear()
        for previous_group in self.repeat_menu.findChildren(QActionGroup):
            previous_group.deleteLater()
        repeat_group = QActionGroup(self.repeat_menu)
        for index in range(self.repeat.count()):
            action = self.repeat_menu.addAction(self.repeat.itemText(index))
            action.setCheckable(True)
            action.setChecked(index == self.repeat.currentIndex())
            repeat_group.addAction(action)
            action.triggered.connect(lambda _checked=False, i=index: self.repeat.setCurrentIndex(i))
        self.shuffle_action.setChecked(self.shuffle.isChecked())
        self.queue_action.setChecked(self.queue_disclosure.isChecked())

    def _arrange_player(self) -> None:
        active_video = bool(self.last_source) and self.current_row.get("kind") == "video"
        self._player_video_mode = active_video
        if active_video:
            target = self.player_base_layout
            if not self.fullscreen_dialog.isVisible() and self.player_home_layout is not target:
                target.insertWidget(0, self.player_panel)
                self.player_home_layout = target
            if self.video_overlay_box.indexOf(self.video_controls) < 0:
                self.video_overlay_box.addWidget(self.video_controls)
            if self.player_heading_box.indexOf(self.now_playing) < 0:
                self.player_heading_box.insertWidget(0, self.now_playing)
            self.now_playing.setStyleSheet("font-size: 23px; font-weight: 600; color: #f1f3ef;")
            self.playing_description.setText(str(self.current_row.get("description") or ""))
            self.playing_description.setVisible(bool(self.playing_description.text()))
        else:
            if (
                not self.fullscreen_dialog.isVisible()
                and self.player_home_layout is not self.player_base_layout
            ):
                self.player_base_layout.addWidget(self.player_panel)
                self.player_home_layout = self.player_base_layout
            if self.music_controls_home.indexOf(self.video_controls) < 0:
                self.music_controls_home.addWidget(self.video_controls)
            if self.transport.indexOf(self.now_playing) < 0:
                self.transport.insertWidget(3, self.now_playing, 1)
            self.now_playing.setStyleSheet("color: #e7eeeb;")
        self.player_heading.setVisible(active_video and not self.fullscreen_dialog.isVisible())
        self.fullscreen_button.setVisible(active_video)
        for button, icon, label in (
            (
                self.previous_button,
                QStyle.StandardPixmap.SP_MediaSeekBackward,
                self.tr("Back 10 seconds") if active_video else self.tr("Previous"),
            ),
            (
                self.next_button,
                QStyle.StandardPixmap.SP_MediaSeekForward,
                self.tr("Forward 10 seconds") if active_video else self.tr("Next"),
            ),
        ):
            button.setIcon(self._player_icon(icon))
            button.setToolTip(label)
            button.setAccessibleName(label)
        if active_video and not self.fullscreen_dialog.isVisible():
            self.video.setFixedHeight(
                min(
                    max(300, self.media_column.height() - 90),
                    max(300, self.media_column.width() * 9 // 16),
                )
            )
        self._show_video_controls()

    def _embedded_subtitle_text(self, text: str) -> None:
        self.embedded_caption = (
            QTextDocumentFragment.fromHtml(text).toPlainText() if "<" in text else text
        )
        self._render_caption()

    def _render_caption(self) -> None:
        if isinstance(self.subtitle_choice, str):
            seconds = self.player.position() / 1000
            text = "\n".join(
                caption for start, end, caption in self.subtitle_cues if start <= seconds < end
            )
        else:
            text = self.embedded_caption if self.subtitle_choice >= 0 else ""
        if text != self.caption.text():
            self.caption.setText(text)
            self._fit_caption()
        self.caption.setVisible(bool(text) and self._player_video_mode)

    def toggle_fullscreen(self) -> None:
        if self.fullscreen_dialog.isVisible():
            self.fullscreen_dialog.reject()
        elif self.last_source:
            self._player_home_index = self.player_home_layout.indexOf(self.player_panel)
            self.fullscreen_layout.addWidget(self.player_panel)
            self.player_box.setContentsMargins(0, 0, 0, 0)
            self.video.setMinimumHeight(0)
            self.video.setMaximumHeight(16777215)
            self.fullscreen_button.setToolTip(self.tr("Exit fullscreen"))
            self.fullscreen_button.setAccessibleName(self.tr("Exit fullscreen"))
            self.player_heading.hide()
            self.fullscreen_dialog.showFullScreen()
            self.fullscreen_button.setFocus()

    def _leave_fullscreen(self) -> None:
        self.player_box.setContentsMargins(12, 8, 12, 8)
        self.player_home_layout.insertWidget(self._player_home_index, self.player_panel)
        self._arrange_player()
        self.fullscreen_button.setToolTip(self.tr("Fullscreen"))
        self.fullscreen_button.setAccessibleName(self.tr("Fullscreen"))
        self.player_panel.show()
        self.fullscreen_button.setFocus()

    @staticmethod
    def _time_label(seconds: float) -> str:
        seconds = max(0, int(seconds))
        return (
            f"{seconds // 3600}:{seconds // 60 % 60:02d}:{seconds % 60:02d}"
            if seconds >= 3600
            else f"{seconds // 60}:{seconds % 60:02d}"
        )

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
                self._set_notice(str(error))

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
                self.audio = create_audio_output(self)
                self.player.setAudioOutput(self.audio)
                self.decoder_sink = QVideoSink(self.player)
                self.display_frames = DisplayFrames()
                self.display_frames.moveToThread(frame_thread())
                self.destroyed.connect(self.display_frames.deleteLater)
                self.video.frames = self.display_frames
                self.video.measure()
                self.decoder_sink.videoFrameChanged.connect(
                    self.display_frames.convert, Qt.ConnectionType.QueuedConnection
                )
                self.display_frames.ready.connect(self.video.item.videoSink().setVideoFrame)
                self.decoder_sink.subtitleTextChanged.connect(self._embedded_subtitle_text)
                self.player.setVideoSink(self.decoder_sink)
                self.player.playbackStateChanged.connect(self._playback_controls_changed)
                self.player.errorOccurred.connect(self._codec_error)
                self.player.positionChanged.connect(self._position_changed)
                self.player.durationChanged.connect(self._duration_changed)
                self.player.mediaStatusChanged.connect(self._media_status)
                self.player.tracksChanged.connect(self._playback_tracks)
                self.player.sourceChanged.connect(self._track_source_changed)
                self.audio.setVolume(float(self.state["volume"]))
                self.volume.setValue(round(float(self.state["volume"]) * 100))
                with QSignalBlocker(self.shuffle), QSignalBlocker(self.repeat):
                    self.shuffle.setChecked(bool(self.state["shuffle"]))
                    self.repeat.setCurrentIndex(max(0, self.repeat.findData(self.state["repeat"])))
                self.heartbeat.start()
                try:
                    # Start on the library; Continue watching keeps the saved video position.
                    queue, index = self.state["queue"], int(self.state["index"])
                    current = queue[max(0, min(index, len(queue) - 1))] if queue else ""
                    if (
                        current
                        and self.library.detail(self.session_client, current)["kind"] == "video"
                    ):
                        self.state.update(current_id="", queue=[], index=0, position=0)
                    self._load_current(play=False)
                except (OSError, ValueError) as error:
                    self._set_notice(str(error))
                    self._render_queue()
                self.apply_player_commands(session.get("commands", []))
                if self.refresh_on_first_open:
                    self.refresh_on_first_open = False
                    folders = self.library.setup(self.session_client).settings.library_folders
                    if folders:
                        QTimer.singleShot(0, self.start_scan)
            self.refresh()
            QTimer.singleShot(0, self, self._auto_scan)  # dropped if the tab is deleted
            self.auto_refresh.start()
        except Exception as error:
            self._set_notice(str(error))

    def dismiss_video(self) -> None:
        """Return to browsing while preserving progress and the saved queue."""
        if self.fullscreen_dialog.isVisible():
            self.fullscreen_dialog.reject()
        self._invalidate_preview_request()
        if self.player is not None:
            if self.preview_device is not None:
                self.preview_device.abort()
            self.player.pause()
            self.report()
            self._clear_track_source()
            self.player.stop()
            self.player.setSource(QUrl())
        self._close_preview()
        self.last_source = ""
        self.current_row = {}
        self.state.update(current_id="", position=0, duration=0, paused=True)
        self.subtitle_cues = []
        self.caption.clear()
        self.now_playing.setText(self.tr("Nothing playing"))
        self._update_panes()
        self.report()

    def _leave_video_for_navigation(self, *_args) -> None:
        if self._player_video_mode:
            self.dismiss_video()

    def eventFilter(self, watched, event):
        if (
            watched is getattr(self, "media_column", None)
            and event.type() == QEvent.Type.Resize
            and hasattr(self, "controls_timer")
        ):
            self._arrange_player()
        if hasattr(self, "controls_timer"):
            surface = watched in (self.video, self.video.viewport(), self.video.overlay)
            if (
                event.type()
                in {
                    QEvent.Type.MouseMove,
                    QEvent.Type.Enter,
                    QEvent.Type.FocusIn,
                    QEvent.Type.KeyPress,
                }
                and watched is not self.media_column
            ):
                self._show_video_controls()
            if surface and event.type() == QEvent.Type.ContextMenu:
                self.player_menu.popup(event.globalPos())
                return True
            if watched is self.video.overlay and event.type() == QEvent.Type.Resize:
                self._scale_caption()
            if (
                surface
                and event.type() == QEvent.Type.MouseButtonDblClick
                and event.button() == Qt.MouseButton.LeftButton
            ):
                # The click that started this double-click must not pause.
                self.click_timer.stop()
                self._swallow_release = True
                self.toggle_fullscreen()
                return True
            if (
                surface
                and event.type() == QEvent.Type.MouseButtonRelease
                and event.button() == Qt.MouseButton.LeftButton
            ):
                self.video.setFocus()
                if self._swallow_release:
                    self._swallow_release = False
                else:
                    self.click_timer.start(QApplication.doubleClickInterval())
                return True
            if surface and event.type() == QEvent.Type.KeyPress:
                if event.key() == Qt.Key.Key_Space:
                    self.toggle_pause()
                    return True
                if event.key() in {Qt.Key.Key_Left, Qt.Key.Key_Right}:
                    self._transport_step(1 if event.key() == Qt.Key.Key_Right else -1)
                    return True
                if event.key() == Qt.Key.Key_F:
                    self.toggle_fullscreen()
                    return True
                if event.key() == Qt.Key.Key_Escape and self.fullscreen_dialog.isVisible():
                    self.fullscreen_dialog.reject()
                    return True
        return super().eventFilter(watched, event)

    def _context(self) -> dict[str, Any]:
        return {
            **self.browse_context,
            "kind": self.browse_kind,
            "selected_ids": self.browse_selection,
            "preview_id": self.preview_id,
            "playlist": self.current_playlist,
        }

    def refresh(self, *_args: Any) -> None:
        if self.library is None:
            return
        browser = self._ensure_browser()
        self._refresh_playlists()
        self._update_panes()
        browser.activate()

    def _refresh_playlists(self) -> None:
        """Fill the player's saved-playlist choice; the view lists its own."""
        try:
            playlists = self.library.playlists(self.session_client)
        except (OSError, ValueError) as error:
            self._set_notice(str(error))
            return
        name = self.current_playlist or self.playlists.currentText()
        with QSignalBlocker(self.playlists):
            self.playlists.clear()
            for playlist in playlists:
                self.playlists.addItem(playlist["name"], playlist)
            if playlists:
                self.playlists.setCurrentIndex(max(0, self.playlists.findText(name)))

    def _update_panes(self) -> None:
        active = bool(self.last_source)
        if not active and self.fullscreen_dialog.isVisible():
            self.fullscreen_dialog.reject()
        video = self.browse_kind == "video"
        active_video = active and self.current_row.get("kind") == "video"
        self.refresh_preview.setVisible(bool(self.preview_id))
        playing = (
            self.player is not None
            and self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        )
        # In Video, a music track keeps its bar only while it plays, so it can be paused.
        background_music = active and not active_video and video
        self.player_panel.setVisible(
            (active and not background_music)
            or (background_music and playing)
            or (not video and (bool(self.state["queue"]) or self.queue_disclosure.isChecked()))
        )
        self.video.setVisible(active_video)
        self._arrange_player()
        self._render_caption()
        for widget in self.playback_widgets:
            widget.setVisible(
                active
                and widget not in {self.shuffle, self.repeat, self.audio_tracks, self.subtitles}
            )
        self.fullscreen_button.setVisible(active_video)
        for widget in self.queue_widgets:
            widget.setVisible(bool(self.state["queue"]) or not video)
        if self.browser is not None:
            self.browser.setVisible(not active_video)

    def _ensure_browser(self) -> MediaBrowserPanel:
        if self.browser is not None:
            return self.browser
        self.browser = MediaBrowserPanel(
            lambda: self.get_service().agent, lambda: self.client_id(), self
        )
        self.browser.layout_value = self.media_layout
        self.browser.hostRequested.connect(self._browser_action)
        self.media_column_layout.insertWidget(1, self.browser, 1)
        self._publish_queue()
        return self.browser

    def _publish_queue(self) -> None:
        """Share the queue with the view without reloading its listing."""
        queue = list(self.state["queue"])
        if self.browser is not None and (
            queue != self.browser.queue or self.queue_music != self.browser.queue_music
        ):
            self.browser.queue, self.browser.queue_music = queue, self.queue_music
            self.browser.publish()

    def _browser_action(self, action: str, values: dict) -> None:
        if action == "playlists-changed":
            self._refresh_playlists()
        elif action == "play":
            self.command("play", media_ids=values["media_ids"], index=values.get("index", 0))
        elif action == "enqueue":
            self.queue_disclosure.setChecked(True)
            self.command(
                "queue",
                media_ids=[*self.state["queue"], *values.get("media_ids", [])][:1000],
                index=self.state["index"],
            )
        elif action == "queue":
            self._open_queue()
        elif action == "preview":
            self.browse_selection = [values["media_id"]]
            self.start_preview()
        elif action == "layout":
            self.set_media_layout(values["layout"])
            self.layout_changed.emit(values["layout"])
        elif action == "kind" and values.get("kind") in {"video", "music"}:
            self._leave_video_for_navigation()
            self.browse_kind = values["kind"]
            if self.browser is not None:
                self.browser.kind = self.browse_kind
                self.browser.view = "recent" if self.browse_kind == "video" else "albums"
            self._update_panes()
        elif action == "context":
            self.browse_context = {
                key: str(values.get(key, ""))[:1000]
                for key in ("view", "q", "genre", "year", "language", "availability")
            }
            if self.browser is not None and values.get("kind") in {"video", "music"}:
                self.browse_kind = self.browser.kind = values["kind"]
                self.browser.view = self.browse_context["view"]
        elif action == "selection":
            self.browse_selection = values.get("selected_ids", [])
        elif action == "chat":
            self.toggle_chat(not self.chat.isChecked())
        elif action == "center":
            self.center_mode_requested.emit(not self.center_button.isChecked())
        elif action == "settings":
            self.folder_button.click()

    def selected_ids(self) -> list[str]:
        return self.browse_selection

    def start_preview(self) -> None:
        ids = self.selected_ids()
        if not ids:
            return
        identifier = ids[0]
        self.preview_generation += 1
        generation = self.preview_generation
        library, client, session_id = self.library, self.session_client, self.session_id
        self.refresh_preview.setEnabled(False)
        self._set_notice(self.tr("Checking downloaded pieces with qBittorrent…"))

        def work():
            preview = library.create_preview(client, identifier)
            try:
                path, _prefix = library.preview_source(client, preview["preview_id"])
                return preview, path, library.preview_map(client, preview["preview_id"])
            except Exception:
                library.close_preview(client, preview["preview_id"])
                raise

        def apply_preview(result):
            preview, path, (size, piece_size, pieces) = result
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
            self.preview_device = DownloadingFileDevice(path, size, piece_size, pieces, self)
            self.preview_checked = time.monotonic()
            self.last_source = identifier
            self.current_row = library.detail(client, identifier)
            self.subtitle_cues = []
            self.caption.clear()
            self.state.update(current_id=identifier, queue=[identifier], index=0)
            self.pending_seek = None
            self._prepare_track_source()
            self.player.setSourceDevice(self.preview_device, QUrl("verified-preview.mp4"))
            self.now_playing.setText(
                self.tr("Preview of downloaded portion · {0}% verified").format(
                    round(100 * preview["progress"])
                )
            )
            self._set_notice(
                self.tr(
                    "Playing while it downloads: playback waits for the next pieces "
                    "when it catches up. Some formats need the missing end before they "
                    "can play."
                )
            )
            self.video.show()
            self.external.hide()
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
                self._set_notice(str(error))
                self.refresh_preview.setEnabled(True)

        run_in_background(work, ready, failed)

    def _invalidate_preview_request(self) -> None:
        self.preview_generation += 1
        self.refresh_preview.setEnabled(True)

    def _close_preview(self) -> None:
        if self.preview_device is not None:
            self.preview_device.abort()  # end a read waiting for pieces before stopping
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
        if self.preview_check_pending or time.monotonic() - self.preview_checked < 2:
            return
        preview_id, library, client = self.preview_id, self.library, self.session_client
        device = self.preview_device
        self.preview_check_pending = True
        self.preview_checked = time.monotonic()

        def done(result):
            if isValid(self):
                self.preview_check_pending = False
                if device is not None and device is self.preview_device:
                    device.update(result[2])
                    self.now_playing.setText(
                        self.tr("Preview of downloaded portion · {0}% verified").format(
                            round(100 * sum(result[2]) / max(1, len(result[2])))
                        )
                    )

        def failed(error):
            if isValid(self):
                self.preview_check_pending = False
                if self.preview_id == preview_id:
                    self._close_preview()
                    self.state["current_id"] = ""
                    self.last_source = ""
                    self._set_notice(str(error))

        run_in_background(lambda: library.preview_map(client, preview_id), done, failed)

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
            self.apply_player_commands(result.get("commands", []))
            self.report()
        except Exception as error:
            self._set_notice(str(error))

    def apply_player_commands(self, commands: list[dict[str, Any]]) -> None:
        """Apply sequenced commands from the attached authenticated player session."""
        for command in commands:
            sequence = int(command["sequence"])
            if sequence <= self.command_ack:
                continue
            action = command["action"]
            scoped_resume = (
                action == "play"
                and "media_ids" not in command
                and ("source_token" in command or "media_id" in command)
            )
            if scoped_resume:
                error = self._track_command_source_error(command)
                if error:
                    self.track_result = {"sequence": sequence, "applied": False, "error": error}
                    self.command_ack = sequence
                    continue
            if action in {"queue", "pause", "next", "previous"} or (
                action == "play" and (not self.preview_id or "media_ids" in command)
            ):
                self._invalidate_preview_request()
            if action == "select_track":
                self._apply_track_command(command)
                self.command_ack = sequence
                continue
            if action == "play" and self.preview_id and "media_ids" not in command:
                self.player.pause() if command.get("start_paused") else self.player.play()
                if scoped_resume:
                    self._track_resume_result(sequence)
                self.command_ack = sequence
                continue
            if action in {"play", "queue"}:
                was_playing = self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
                if "media_ids" in command:
                    self.state["queue"] = command["media_ids"]
                    self.state["index"] = command.get("index", 0)
                start_paused = bool(command.get("start_paused")) and action == "play"
                if start_paused:
                    self.player.pause()
                self._load_current(
                    play=(action == "play" or was_playing) and not start_paused,
                    load_token=str(command.get("load_token") or ""),
                )
                if action == "play":
                    self.player.pause() if start_paused else self.player.play()
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
            if scoped_resume:
                self._track_resume_result(sequence)
            self.command_ack = sequence

    def _load_current(self, play: bool, load_token: str = "") -> None:
        queue = self.state["queue"]
        if not queue:
            self._clear_track_source()
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
        if identifier != self.last_source or self.preview_id or load_token:
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
            self._prepare_track_source(load_token)
            self.player.setSource(QUrl.fromLocalFile(str(path)))
            if self.player.mediaStatus() in {
                QMediaPlayer.MediaStatus.LoadedMedia,
                QMediaPlayer.MediaStatus.BufferedMedia,
            }:
                self._playback_tracks()
            self.video.setVisible(row["kind"] == "video")
        if not self.track_source_token:
            self._prepare_track_source(load_token)
            self._playback_tracks()
        if play:
            self.player.play()
        self._render_queue()

    def _render_queue(self) -> None:
        self.queue.clear()
        self.queue_music = True
        for media_id in self.state["queue"]:
            try:
                row = self.library.detail(self.session_client, media_id)
                title = row["title"]
                self.queue_music = self.queue_music and row["kind"] == "music"
            except Exception:
                title = self.tr("Unavailable media")
            self.queue.addItem(title)
        self.queue.setCurrentRow(int(self.state["index"]))
        self._publish_queue()
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
                self._set_notice(str(error))

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
                self._set_notice(str(error))

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
            # Until the saved resume point is applied, the player reports 0; keep the saved one.
            position = self.player.position() if self.pending_seek is None else self.pending_seek
            self.state.update(
                position=position / 1000,
                duration=self.player.duration() / 1000,
                paused=self.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState,
                volume=self.audio.volume(),
            )
            result = self.library.session(
                self.session_id,
                self.token,
                report={
                    **self.state,
                    "command_ack": self.command_ack,
                    "track_state": self._track_state(),
                    **({"track_result": self.track_result} if self.track_result else {}),
                },
                context=self._context(),
            )
            self.apply_player_commands(result.get("commands", []))
            request = result.get("state", {}).get("track_request", {})
            if request.get("status") == "failed":
                failure = (str(request.get("source_token") or ""), str(request.get("error") or ""))
                if failure != self.last_track_failure:
                    self.last_track_failure = failure
                    self._set_notice(failure[1])
        except Exception as error:
            self._set_notice(str(error))

    def _position_changed(self, position: int) -> None:
        self._render_caption()
        if not self.seek.isSliderDown():
            self.seek.setValue(position // 1000)
        self.elapsed.setText(
            f"{self._time_label(position / 1000)} / "
            f"{self._time_label(self.player.duration() / 1000)}"
        )

    def _duration_changed(self, duration: int) -> None:
        self.seek.setMaximum(duration // 1000)

    def _media_status(self, status: QMediaPlayer.MediaStatus) -> None:
        if status in {QMediaPlayer.MediaStatus.LoadedMedia, QMediaPlayer.MediaStatus.BufferedMedia}:
            self.tracks_ready = bool(self.track_source_token)
            if self.pending_seek is not None:
                self.player.setPosition(self.pending_seek)
                self.pending_seek = None
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            if self.preview_id:
                self.player.pause()
                self._set_notice(
                    self.tr("End of downloaded portion. Refresh preview after more pieces arrive.")
                )
                return
            if self.state["repeat"] == "one":
                self.player.setPosition(0)
                self.player.play()
            else:
                self._advance(1)

    def _select_subtitle(self) -> bool:
        if self.player is None:
            return False
        value = self.subtitles.currentData()
        if value is None:
            return False
        self.subtitle_error = ""
        if isinstance(value, int):
            self.embedded_caption = ""
            self.subtitle_choice = value
            self.subtitle_cues = []
            self.caption.clear()
            self.player.setActiveSubtitleTrack(value)
            return self.player.activeSubtitleTrack() == value
        try:
            data, _mime = self.library.subtitle(self.session_client, self.last_source, value)
            text = data.decode("utf-8-sig", errors="replace").replace("\r", "")
            timing = re.compile(r"(?:(\d+):)?(\d{2}):(\d{2})[.,](\d{3})")
            cues = []
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
                    cues.append((seconds[0], seconds[1], caption))
            if not cues:
                raise ValueError(self.tr("Subtitle file has no readable timed cues."))
            self.subtitle_choice = value
            self.subtitle_cues = cues
            self.player.setActiveSubtitleTrack(-1)
            self._position_changed(self.player.position())
            self._update_panes()
            return True
        except Exception as error:
            self.subtitle_error = str(error)
            self._set_notice(str(error))
            with QSignalBlocker(self.subtitles):
                self.subtitles.setCurrentIndex(self.subtitles.findData(self.subtitle_choice))
            return False

    def _prepare_track_source(self, token: str = "") -> None:
        self.player_menu.close()
        self.track_source_token = token or str(uuid4())
        self.track_result = {}
        self.tracks_ready = False
        self._reset_track_choices()

    def _clear_track_source(self) -> None:
        self.track_source_token = ""
        self.track_result = {}
        self.tracks_ready = False

    def _track_source_changed(self) -> None:
        self._reset_track_choices()
        if self.player.source().isEmpty() and not self.preview_id:
            self._clear_track_source()

    @staticmethod
    def _track_language(metadata: QMediaMetaData) -> str:
        language = metadata.value(QMediaMetaData.Key.Language)
        if isinstance(language, QLocale.Language):
            if language in {QLocale.Language.AnyLanguage, QLocale.Language.C}:
                return ""
            return QLocale.languageToCode(language)
        return language if isinstance(language, str) else ""

    def _track_state(self) -> dict[str, Any]:
        ready = (
            self.tracks_ready
            and bool(self.track_source_token)
            and self.player is not None
            and self.player.error() == QMediaPlayer.Error.NoError
        )
        audio, subtitles = [], []
        if ready:
            for index, track in enumerate(self.player.audioTracks()[:100]):
                audio.append(
                    {
                        "id": f"audio:{index}",
                        "label": self._track_label(track, self.tr("Audio {0}").format(index + 1)),
                        "language": self._track_language(track),
                        "selected": self.player.activeAudioTrack() == index,
                    }
                )
            for index, track in enumerate(self.player.subtitleTracks()[:100]):
                subtitles.append(
                    {
                        "id": f"embedded:{index}",
                        "label": self._track_label(
                            track, self.tr("Embedded subtitle {0}").format(index + 1)
                        ),
                        "language": self._track_language(track),
                        "selected": self.player.activeSubtitleTrack() == index,
                    }
                )
            for track in self.current_row.get("subtitles", [])[: max(0, 100 - len(subtitles))]:
                subtitles.append(
                    {
                        "id": "external:" + track["id"],
                        "label": track["label"],
                        "language": str(track.get("language") or ""),
                        "selected": self.subtitle_choice == track["id"]
                        and self.player.activeSubtitleTrack() == -1,
                    }
                )
        for entry in audio + subtitles:
            entry["label"] = str(entry["label"])[:300]
            entry["language"] = str(entry["language"])[:300]
        return {
            "media_id": self.last_source,
            "source_token": self.track_source_token,
            "ready": ready,
            "audio_supported": ready and bool(audio),
            "subtitle_supported": ready,
            "audio": audio,
            "subtitles": subtitles[:100],
        }

    def _track_command_source_error(self, command: dict[str, Any]) -> str:
        if (
            not self.track_source_token
            or command.get("source_token") != self.track_source_token
            or command.get("media_id") != self.last_source
        ):
            return self.tr("Player source changed before track selection.")
        return ""

    def _track_resume_result(self, sequence: int) -> None:
        applied = self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        self.track_result = {
            "sequence": sequence,
            "applied": applied,
            "error": "" if applied else self.tr("Player did not resume playback."),
        }
        if applied:
            self._clear_track_failure_notice()

    def _apply_track_command(self, command: dict[str, Any]) -> None:
        error = self._track_command_source_error(command)
        inventory = self._track_state()
        kind, identifier = command.get("kind"), str(command.get("track_id") or "")
        if not error and not inventory["ready"]:
            error = self.tr("Track metadata is not ready.")
        if not error:
            options = inventory["audio"] if kind == "audio" else inventory["subtitles"]
            supported = inventory.get(f"{kind}_supported", False)
            valid = any(track["id"] == identifier for track in options)
            if not supported or (not valid and not (kind == "subtitle" and identifier == "off")):
                error = self.tr("Requested track is unavailable.")
        if not error:
            if kind == "audio":
                index = int(identifier.removeprefix("audio:"))
                with QSignalBlocker(self.audio_tracks):
                    self.audio_tracks.setCurrentIndex(self.audio_tracks.findData(index))
                self._select_audio()
                applied = self.player.activeAudioTrack() == index
            else:
                value = (
                    -1
                    if identifier == "off"
                    else int(identifier.removeprefix("embedded:"))
                    if identifier.startswith("embedded:")
                    else identifier.removeprefix("external:")
                )
                with QSignalBlocker(self.subtitles):
                    self.subtitles.setCurrentIndex(self.subtitles.findData(value))
                applied = self._select_subtitle()
            if not applied:
                error = self.tr("Player did not apply the requested track.")
                if kind == "subtitle":
                    error = getattr(self, "subtitle_error", "") or error
        self.track_result = {
            "sequence": int(command["sequence"]),
            "applied": not bool(error),
            "error": error,
        }
        if not error:
            self._clear_track_failure_notice()

    def _clear_track_failure_notice(self) -> None:
        if self.last_track_failure and self.notice.text() == self.last_track_failure[1]:
            self._set_notice("")

    def _reset_track_choices(self) -> None:
        self.audio_choice = None
        self.subtitle_choice = -1
        self.embedded_caption = ""
        self.subtitle_cues = []
        self.caption.clear()
        with QSignalBlocker(self.audio_tracks), QSignalBlocker(self.subtitles):
            self.audio_tracks.clear()
            self.subtitles.clear()
            self.subtitles.addItem(self.tr("Subtitles off"), -1)

    def _track_label(self, metadata: QMediaMetaData, fallback: str) -> str:
        labels = [fallback]
        language = metadata.value(QMediaMetaData.Key.Language)
        if isinstance(language, QLocale.Language) and language not in {
            QLocale.Language.AnyLanguage,
            QLocale.Language.C,
        }:
            labels.append(QLocale.languageToString(language))
        elif isinstance(language, str) and language:
            labels.append(language)
        title = metadata.stringValue(QMediaMetaData.Key.Title)
        if title and title not in labels:
            labels.append(title)
        return " · ".join(labels)

    def _select_audio(self) -> None:
        choice = self.audio_tracks.currentData()
        if self.player is not None and isinstance(choice, int):
            self.audio_choice = choice
            self.player.setActiveAudioTrack(choice)

    def _playback_tracks(self) -> None:
        self.tracks_ready = bool(self.track_source_token) and bool(
            self.player.audioTracks() or self.player.subtitleTracks() or self.player.videoTracks()
        )
        audio = self.player.audioTracks()
        if audio:
            choice = self.audio_choice
            if choice is None or not 0 <= choice < len(audio):
                choice = max(0, self.player.activeAudioTrack())
            with QSignalBlocker(self.audio_tracks):
                self.audio_tracks.clear()
                for index, track in enumerate(audio):
                    self.audio_tracks.addItem(
                        self._track_label(track, self.tr("Audio {0}").format(index + 1)), index
                    )
                self.audio_tracks.setCurrentIndex(self.audio_tracks.findData(choice))
            self.audio_choice = choice
            if self.player.activeAudioTrack() != choice:
                self.player.setActiveAudioTrack(choice)
        with QSignalBlocker(self.subtitles):
            self.subtitles.clear()
            self.subtitles.addItem(self.tr("Subtitles off"), -1)
            for index, track in enumerate(self.player.subtitleTracks()[:100]):
                self.subtitles.addItem(
                    self._track_label(track, self.tr("Embedded subtitle {0}").format(index + 1)),
                    index,
                )
            for subtitle in self.current_row.get("subtitles", []):
                self.subtitles.addItem(subtitle["label"], subtitle["id"])
            self.subtitles.setCurrentIndex(max(0, self.subtitles.findData(self.subtitle_choice)))
        choice = self.subtitle_choice if isinstance(self.subtitle_choice, int) else -1
        if self.player.activeSubtitleTrack() != choice:
            self.player.setActiveSubtitleTrack(choice)

    def _codec_error(self, *_args: Any) -> None:
        if self.player.error() != QMediaPlayer.Error.NoError:
            self._set_notice(
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
                self._set_notice(str(error))

    def _auto_scan(self) -> None:
        """Rescan quietly; the screen reloads only when the library changed."""
        if not self.isVisible() or self.library is None or self.video_playing:
            return
        if self.library.setup(self.session_client).settings.library_folders:
            self.start_scan(quiet=True)

    def start_scan(self, quiet: bool = False) -> None:
        if self.library is None or self.scan_stop is not None:
            return
        self.scan_quiet = quiet
        self.scan_stop = threading.Event()
        stop = self.scan_stop
        if not quiet:
            self._set_notice(self.tr("Scanning Library Folders…"))
        run_in_background(
            lambda: self.library.scan(self.session_client, stop, self.scan_progress.emit),
            self._scan_done,
            self._scan_failed,
        )

    def _scan_progress(self, value: Any) -> None:
        if self.scan_quiet:
            return
        if isinstance(value, dict) and "film_details" in value:
            self._set_notice(
                self.tr("Fetching film details from c411… {0} / {1}").format(
                    value["film_details"], value.get("of", "?")
                )
            )
        elif isinstance(value, dict) and "items" in value:
            self._set_notice(self.tr("Scanning Library Folders… {0} files").format(value["items"]))

    def _scan_done(self, result: Any) -> None:
        if not isValid(self):
            return
        self.scan_stop = None
        if not self.scan_quiet or (isinstance(result, dict) and result.get("changed")):
            self.refresh()

    def _scan_failed(self, error: Exception) -> None:
        if not isValid(self):
            return
        quiet = self.scan_quiet
        self._scan_done(None)
        if not quiet:
            self._set_notice(str(error))

    def toggle_chat(self, checked: bool = True) -> None:
        if checked:
            self.open_chat()
        else:
            self.close_chat()

    def open_chat(self, conversation_id: str = "", *, new: bool = False) -> None:
        if self.library is None:
            self.chat.setChecked(False)
            return
        try:
            self.report()
            self.conversation_id = self.service.media_chat(
                self.session_id,
                self.token,
                conversation_id or ("" if new else self.conversation_id),
                new=new,
            )["conversation_id"]
            if self.credentials:
                self.credentials.setValue("conversation", self.conversation_id)
                self.credentials.sync()
            opening = self.assistant is None or self.assistant.isHidden()
            if self.assistant is None:
                from torrentlinker.gui.assistant import AssistantTab

                self.assistant = AssistantTab(self.get_service, compact=True)
                self.assistant.setMinimumWidth(CHAT_MIN_WIDTH)
                self.assistant.closeRequested.connect(self.close_chat)
                self.assistant.connectionsRequested.connect(self.connections_requested.emit)
                self.assistant.conversationRequested.connect(
                    lambda identifier: self.open_chat(identifier, new=not identifier)
                )
                self.splitter.addWidget(self.assistant)
                self.splitter.setChildrenCollapsible(False)
                self.splitter.splitterMoved.connect(self._remember_chat_width)
            if opening:
                # Also on the first opening after a restart, when the panel is new.
                self.assistant.show()
                self._restore_chat_width()
            self.chat.setChecked(True)
            if self.browser is not None:
                self.browser.chat_open = True
                self.browser.publish()
            self.assistant.activate()
            self.assistant.select_conversation(self.conversation_id)
            self.assistant.prompt.setFocus()
        except Exception as error:
            self.chat.setChecked(False)
            self._set_notice(str(error))

    def close_chat(self) -> None:
        if self.assistant is not None and self.assistant.isVisible():
            self._remember_chat_width()
            self.assistant.hide()
        self.chat.setChecked(False)

        if self.browser is not None:
            self.browser.chat_open = False
            self.browser.publish()

    def _restore_chat_width(self) -> None:
        total = sum(self.splitter.sizes()) or self.splitter.width()
        saved = self.credentials.value("chat_width", 0) if self.credentials else 0
        try:
            width = int(str(saved or 0))
        except (TypeError, ValueError):
            width = 0
        width = width or total * 38 // 100
        # Keep the remembered width, but always leave the media side its minimum.
        width = max(CHAT_MIN_WIDTH, min(width, total - MEDIA_MIN_WIDTH))
        self.splitter.setSizes([max(0, total - width), width])

    def _remember_chat_width(self, *_args: Any) -> None:
        if self.assistant is None or not self.assistant.isVisible() or not self.credentials:
            return
        self.credentials.setValue("chat_width", self.splitter.sizes()[-1])
        self.credentials.sync()

    def stop(self) -> None:
        if self.fullscreen_dialog.isVisible():
            self.fullscreen_dialog.reject()
        self._invalidate_preview_request()
        if self.player is None or not self.heartbeat.isActive():
            return
        if self.scan_stop:
            self.scan_stop.set()
        if self.preview_device is not None:
            self.preview_device.abort()
        self.player.pause()
        self._clear_track_source()
        self.report()
        self.heartbeat.stop()
        self.auto_refresh.stop()
        self.player.stop()
        self._close_preview()
