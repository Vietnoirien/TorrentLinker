"""The Upload tab's 3D preview and the PNGs it captures for the description (ADR-0011).

c411's image upload refuses an API key, so the app renders the model itself and saves a
PNG the user adds on c411's upload page while reviewing the Draft. The live view is a
QtQuick3D scene in a widget. Captures use the shared CPU worker with the same camera
basis, perspective distance and view framing. Source geometry is never modified.
"""

from __future__ import annotations

import json
import multiprocessing
import sys
import threading
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QByteArray, QSize, Qt, QUrl, Signal
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QImage,
    QOffscreenSurface,
    QOpenGLContext,
    QPainter,
    QSurfaceFormat,
    QVector3D,
)
from PySide6.QtOpenGL import QOpenGLFramebufferObject, QOpenGLFramebufferObjectFormat
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuick import (
    QQuickGraphicsDevice,
    QQuickItem,
    QQuickRenderControl,
    QQuickRenderTarget,
    QQuickWindow,
    QSGRendererInterface,
)
from PySide6.QtQuick3D import QQuick3DGeometry
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import delete

from torrentlinker.domain import LocalItem
from torrentlinker.gui.controls import set_role
from torrentlinker.gui.errors import error_text
from torrentlinker.gui.tasks import run_in_background
from torrentlinker.matching import IgnoreList
from torrentlinker.mesh import (
    ISO_PITCH,
    ISO_YAW,
    DisplayMesh,
    frame_distance,
    prepare_display,
    previewable,
    sheet_layout,
)
from torrentlinker.model_rendering import Camera

QML = Path(__file__).with_name("model_view.qml")
CAPTURE_SIZE = QSize(1200, 900)  # c411 wants at least 1000 px wide
BACKGROUND = QColor("#eceff1")

# The offscreen renderer draws through an OpenGL context, so Qt Quick must use RHI on OpenGL
# (Qt falls back to software on the offscreen platform, which cannot draw 3D; Windows
# defaults to Direct3D). Set before any Qt Quick window exists.
QQuickWindow.setSceneGraphBackend("rhi")
QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.OpenGL)


class RenderUnavailable(Exception):
    """No OpenGL here: the model can be shown nowhere, so no image can be captured."""


def _context_format() -> QSurfaceFormat:
    fmt = QSurfaceFormat()
    fmt.setDepthBufferSize(24)
    fmt.setStencilBufferSize(8)
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    return fmt


def _probe_gl() -> None:
    """Child process: create and bind the OpenGL context, exiting 0 if that works."""
    app = QGuiApplication(sys.argv[:1])
    context = QOpenGLContext()
    context.setFormat(_context_format())
    surface = QOffscreenSurface()
    if context.create():
        surface.setFormat(context.format())
        surface.create()
        if context.makeCurrent(surface):
            context.doneCurrent()
            del app
            return
    sys.exit(1)


_gl_probed: dict[str, bool] = {}


def gl_is_safe() -> bool:
    """Whether an OpenGL context can be created here. Through GLX (X11, XWayland) a failing
    driver raises a fatal X error that kills or crashes the whole process, so the first
    attempt on such a platform is made in a child process; elsewhere the in-process
    create() reports failure safely."""
    platform = QGuiApplication.platformName()
    if not sys.platform.startswith("linux") or platform not in ("xcb", "offscreen"):
        return True
    if platform not in _gl_probed:
        child = multiprocessing.get_context("spawn").Process(target=_probe_gl)
        child.start()
        child.join(30)
        if child.is_alive():
            child.kill()
            child.join()
        _gl_probed[platform] = child.exitcode == 0
    return _gl_probed[platform]


def make_geometry(display: DisplayMesh) -> QQuick3DGeometry:
    """The scene's mesh: float32 position and normal for each triangle corner. The caller
    keeps it alive for as long as the scene shows it."""
    geometry = QQuick3DGeometry()
    geometry.setStride(DisplayMesh.STRIDE)
    geometry.setPrimitiveType(QQuick3DGeometry.PrimitiveType.Triangles)
    attribute = QQuick3DGeometry.Attribute
    geometry.addAttribute(attribute.Semantic.PositionSemantic, 0, attribute.ComponentType.F32Type)
    geometry.addAttribute(attribute.Semantic.NormalSemantic, 12, attribute.ComponentType.F32Type)
    geometry.setVertexData(QByteArray(display.buffer))
    r = display.radius
    geometry.setBounds(QVector3D(-r, -r, -r), QVector3D(r, r, r))
    return geometry


class OffscreenScene:
    """Renders the 3D scene to an image without a window, through Qt Quick's render
    control and an OpenGL texture. Use as a context manager; GUI thread only."""

    def __init__(self) -> None:
        self._open = False
        self._target: QOpenGLFramebufferObject | None = None
        if QGuiApplication.instance() is None:
            raise RenderUnavailable("No application")
        if not gl_is_safe():
            raise RenderUnavailable("OpenGL is not available")
        self.context = QOpenGLContext()
        self.context.setFormat(_context_format())
        self.surface = QOffscreenSurface()
        if not self.context.create():
            raise RenderUnavailable("OpenGL is not available")
        self.surface.setFormat(self.context.format())
        self.surface.create()
        if not self.context.makeCurrent(self.surface):
            raise RenderUnavailable("OpenGL is not available")
        self.control = QQuickRenderControl()
        self.window = QQuickWindow(self.control)
        self.window.setGraphicsDevice(QQuickGraphicsDevice.fromOpenGLContext(self.context))
        if not self.control.initialize():
            self.context.doneCurrent()
            raise RenderUnavailable("Qt Quick cannot draw with this OpenGL")
        self.engine = QQmlEngine()
        component = self.component = QQmlComponent(self.engine, QUrl.fromLocalFile(str(QML)))
        root = component.create()
        if not isinstance(root, QQuickItem):
            self.control.invalidate()
            self.context.doneCurrent()
            raise RenderUnavailable("; ".join(e.toString() for e in component.errors()))
        self.root = root
        self.root.setParentItem(self.window.contentItem())
        self._open = True

    def __enter__(self) -> OffscreenScene:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        """Tear the scene down in Qt Quick's order: items, then the window, the render
        control and last the OpenGL context; any other order crashes."""
        if not self._open:
            return
        self._open = False
        self.context.makeCurrent(self.surface)
        self._target = None
        delete(self.root)
        self.control.invalidate()
        delete(self.window)
        delete(self.control)
        delete(self.engine)
        self.context.doneCurrent()
        delete(self.surface)
        delete(self.context)

    def render(
        self, display: DisplayMesh, yaw: float, pitch: float, zoom: float, size: QSize
    ) -> QImage:
        """The model seen from (yaw, pitch) degrees, `zoom` times its framing distance."""
        self.context.makeCurrent(self.surface)
        geometry = make_geometry(display)
        root = self.root
        root.setProperty("meshGeometry", geometry)
        root.setProperty("radius", display.radius)
        aspect = size.width() / size.height()
        root.setProperty("baseDistance", frame_distance(display.half_extents, aspect))
        root.setProperty("yaw", yaw)
        root.setProperty("pitch", pitch)
        root.setProperty("zoom", zoom)
        root.setWidth(size.width())
        root.setHeight(size.height())
        self.window.setGeometry(0, 0, size.width(), size.height())
        fmt = QOpenGLFramebufferObjectFormat()
        fmt.setAttachment(QOpenGLFramebufferObject.Attachment.CombinedDepthStencil)
        target = QOpenGLFramebufferObject(size, fmt)
        self.window.setRenderTarget(QQuickRenderTarget.fromOpenGLTexture(target.texture(), size))
        self._target = target  # until the next frame: Qt Quick still holds its texture
        app = QGuiApplication.instance()
        for _ in range(3):  # the scene settles over a few frames
            if app is not None:
                app.processEvents()
            self.control.polishItems()
            self.control.beginFrame()
            self.control.sync()
            self.control.render()
            self.control.endFrame()
        image = target.toImage()
        root.setProperty("meshGeometry", None)
        self.context.doneCurrent()
        return image


def contact_sheet(scene: OffscreenScene, models: list[tuple[str, DisplayMesh]]) -> QImage:
    """Up to nine models in a grid, each at the isometric angle with its file name below."""
    layout = sheet_layout(len(models))
    sheet = QImage(layout.width, layout.height, QImage.Format.Format_RGB32)
    sheet.fill(Qt.GlobalColor.white)
    painter = QPainter(sheet)
    font = QFont()
    font.setPixelSize(26)
    painter.setFont(font)
    metrics = QFontMetrics(font)
    for cell, (name, display) in zip(layout.cells, models, strict=False):
        x, y, w, h = cell.picture
        painter.drawImage(x, y, scene.render(display, ISO_YAW, ISO_PITCH, 1.0, QSize(w, h)))
        lx, ly, lw, lh = cell.label
        text = metrics.elidedText(name, Qt.TextElideMode.ElideMiddle, lw - 8)
        painter.setPen(QColor("#263238"))
        painter.drawText(lx, ly, lw, lh, Qt.AlignmentFlag.AlignCenter, text)
    painter.end()
    return sheet


class ModelViewer(QWidget):
    """The interactive view: drag to rotate, wheel to zoom, double-click to start over.
    It opens at the isometric angle, framed on the model's bounding sphere."""

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.view = QQuickWidget()
        self.view.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        self.view.setClearColor(BACKGROUND)
        self.view.setMinimumHeight(260)
        self.view.setSource(QUrl.fromLocalFile(str(QML)))
        layout.addWidget(self.view)
        self.display: DisplayMesh | None = None
        self._geometry: QQuick3DGeometry | None = None
        root = self.view.rootObject()
        self.root: QQuickItem | None = root if isinstance(root, QQuickItem) else None
        if self.root is not None:
            self.root.setProperty("interactive", True)
            self.root.setProperty("background", BACKGROUND)
            self.root.widthChanged.connect(self._frame)
            self.root.heightChanged.connect(self._frame)
            self.root.reset.connect(self.reset_view)  # type: ignore[attr-defined]

    def show_mesh(self, display: DisplayMesh | None) -> None:
        self.display = display
        if self.root is None:
            return
        self._geometry = make_geometry(display) if display else None
        self.root.setProperty("meshGeometry", self._geometry)
        self.reset_view()

    def reset_view(self) -> None:
        if self.root is None:
            return
        self.root.setProperty("yaw", ISO_YAW)
        self.root.setProperty("pitch", ISO_PITCH)
        self.root.setProperty("zoom", 1.0)
        self._frame()

    def _frame(self) -> None:
        """Back the camera off until the model fits whatever the view's shape is."""
        if self.root is None or self.display is None:
            return
        aspect = max(self.root.width(), 1) / max(self.root.height(), 1)
        self.root.setProperty("radius", self.display.radius)
        self.root.setProperty("baseDistance", frame_distance(self.display.half_extents, aspect))

    def view_state(self) -> tuple[float, float, float]:
        """(yaw, pitch, zoom) as the user has turned the model."""
        if self.root is None:
            return ISO_YAW, ISO_PITCH, 1.0
        return (
            float(self.root.property("yaw")),
            float(self.root.property("pitch")),
            float(self.root.property("zoom")),
        )


class ModelPanel(QWidget):
    """The Upload tab's 3D page: the viewer for the chosen Local Item, a Capture button
    that saves a PNG in the Upload's folder, and for a Pack a contact sheet of its models."""

    saved = Signal(object)  # Path of a PNG just written

    def __init__(
        self,
        folder: Path,
        title: Callable[[], str],
        ignore: Callable[[], IgnoreList],
        is_pack: Callable[[], bool],
    ) -> None:
        super().__init__()
        self.folder = folder  # the app's uploads/, each Upload gets a folder of its own in it
        self.title = title
        self.ignore = ignore
        self.is_pack = is_pack
        self.item: LocalItem | None = None
        self.files: list[Path] = []  # the models the viewer can draw, by path
        self._generation = 0  # which load is current: a late result of an old one is dropped
        self._busy = False
        self.asset_ids: list[str] = []
        self.cameras: dict[Path, Camera] = {}
        self._render_stop = threading.Event()
        self._shown_path: Path | None = None

        layout = QVBoxLayout(self)
        self.message = QLabel()
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.models = QComboBox()
        self.models.currentIndexChanged.connect(self._model_chosen)
        layout.addWidget(self.models)
        self.viewer = ModelViewer()
        layout.addWidget(self.viewer, 1)
        row = QHBoxLayout()
        self.capture_button = QPushButton(self.tr("Capture"))
        set_role(self.capture_button, "primary")
        self.capture_button.setToolTip(
            self.tr("Save the view as a PNG of at least 1000 px to add on c411")
        )
        self.capture_button.clicked.connect(self.capture)
        self.sheet_button = QPushButton(self.tr("Capture the Pack sheet"))
        self.sheet_button.setToolTip(
            self.tr("Save labelled pages covering every model in the Pack")
        )
        self.sheet_button.clicked.connect(self.capture_sheet)
        self.reset_button = QPushButton(self.tr("Reset the view"))
        set_role(self.reset_button, "quiet")
        self.reset_button.clicked.connect(self.viewer.reset_view)
        self.open_button = QPushButton(self.tr("Open the folder"))
        set_role(self.open_button, "quiet")
        self.open_button.clicked.connect(self.open_folder)
        for button in (self.capture_button, self.sheet_button, self.reset_button):
            row.addWidget(button)
        row.addStretch()
        row.addWidget(self.open_button)
        layout.addLayout(row)
        self.paths = QLabel()
        self.paths.setWordWrap(True)
        self.paths.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.paths)
        self.set_item(None)

    # What is shown --------------------------------------------------------------

    def upload_folder(self) -> Path:
        """Where this Upload's images go: its own folder in uploads/, never the Library."""
        return self.folder / self.title()

    def png_files(self) -> list[Path]:
        folder = self.upload_folder()
        return sorted(folder.glob("*.png")) if self.title() and folder.is_dir() else []

    def set_item(self, item: LocalItem | None) -> None:
        """Show this Local Item's model, if it holds one the viewer can read."""
        self._render_stop.set()
        self.asset_ids = []
        self.cameras = {}
        self._shown_path = None
        self.item = item
        self._generation += 1
        self.files = []
        self.models.blockSignals(True)
        self.models.clear()
        if item is not None:
            content = {p for p in item.files if not self.ignore().matches(p)}
            self.files = [item.save_path / p for p in previewable(content)]
            for path in self.files:
                self.models.addItem(path.name, path)
        self.models.blockSignals(False)
        self.viewer.show_mesh(None)
        if item is None:
            self._say(self.tr("Pick an Orphan to see its model."))
        elif not self.files:
            self._say(
                self.tr(
                    "No preview: only STL, OBJ and 3MF models can be drawn here, and this "
                    "item has none. Make the description's image yourself and add it on c411."
                )
            )
        else:
            self._model_chosen()
        self.refresh()

    def refresh(self) -> None:
        """After the name or subcategory changed: which buttons apply, and the PNGs saved."""
        has_model = self.viewer.display is not None
        named = bool(self.title())
        self.models.setVisible(len(self.files) > 1)
        self.viewer.setVisible(bool(self.files))
        self.capture_button.setEnabled(has_model and named and not self._busy)
        self.capture_button.setVisible(bool(self.files))
        self.reset_button.setVisible(bool(self.files))
        self.sheet_button.setVisible(bool(self.files) and self.is_pack())
        self.sheet_button.setEnabled(named and not self._busy)
        self.open_button.setEnabled(named)
        found = self.png_files()
        self.paths.setText(
            self.tr("Images for c411, in {0}:\n{1}").format(
                self.upload_folder(), "\n".join(p.name for p in found)
            )
            if found
            else (
                self.tr("The images you capture are saved in {0}").format(self.upload_folder())
                if named
                else ""
            )
        )

    def _say(self, text: str) -> None:
        self.message.setText(text)
        self.message.setVisible(bool(text))

    def _remember_camera(self):

        if self._shown_path is not None and self.viewer.display is not None:
            yaw, pitch, zoom = self.viewer.view_state()
            root = self.viewer.root
            if root is not None:
                self.cameras[self._shown_path] = Camera.from_viewer(
                    yaw,
                    pitch,
                    zoom,
                    float(root.property("baseDistance")),
                    max(root.width(), 1) / max(root.height(), 1),
                )

    def _model_chosen(self) -> None:
        self._remember_camera()
        path = self.models.currentData()
        if path is None:
            return
        self._shown_path = path
        self._generation += 1
        generation = self._generation
        self.viewer.show_mesh(None)
        self._say(self.tr("Reading {0}…").format(path.name))
        run_in_background(
            lambda: prepare_display(path),
            lambda display: self._loaded(generation, display),
            lambda e: self._load_failed(generation, path, e),
        )

    def _loaded(self, generation: int, display: DisplayMesh) -> None:
        if generation != self._generation:
            return
        self.viewer.show_mesh(display)
        state = self.cameras.get(self._shown_path) if self._shown_path is not None else None
        if state is not None and self.viewer.root is not None:
            self.viewer.root.setProperty("yaw", state.yaw)
            self.viewer.root.setProperty("pitch", 90 - state.pitch)
            self.viewer.root.setProperty("zoom", 1 / state.zoom)
        if display.shown < display.triangles:
            self._say(
                self.tr("Shown with {0} of its {1} triangles.").format(
                    display.shown, display.triangles
                )
            )
        else:
            self._say("")
        self.refresh()

    def _load_failed(self, generation: int, path: Path, error: Exception) -> None:
        if generation != self._generation:
            return
        self._say(
            self.tr("{0} cannot be drawn: {1}. Add the image yourself on c411.").format(
                path.name, error_text(error)
            )
        )
        self.refresh()

    # Capturing ------------------------------------------------------------------

    def _next_png(self, stem: str) -> Path:
        """`<stem>.png`, or the first `<stem>-2.png`… not taken: captures are never overwritten."""
        folder = self.upload_folder()
        path = folder / f"{stem}.png"
        n = 2
        while path.exists():
            path = folder / f"{stem}-{n}.png"
            n += 1
        return path

    def capture(self) -> None:
        path = self.models.currentData()
        if path is not None and self.title() and not self._busy:
            self._capture_models([path])

    def capture_sheet(self) -> None:
        if self.files and self.title() and not self._busy:
            self._capture_models(list(self.files))

    def _capture_models(self, chosen):
        from torrentlinker.model_rendering import render_models
        from torrentlinker.upload_assets import Assets, publish_render_pages

        self._remember_camera()
        states = [self.cameras.get(path, Camera()) for path in chosen]
        self._render_stop = stop = threading.Event()
        generation = self._generation
        self._busy = True
        self._say(self.tr("Rendering {0} models…").format(len(chosen)))
        self.refresh()
        item_path = str(self.item.path) if self.item else ""
        output_folder = self.upload_folder()
        stem = self.title() + ("-pack" if len(chosen) > 1 else "")

        def read():
            result = render_models(chosen, states, stop, lambda _: None)
            assets = Assets(self.folder.parent)
            artifacts = publish_render_pages(
                result["pages"], assets, item_path, selection=[str(path) for path in chosen]
            )
            ids = [asset["asset_id"] for asset in artifacts]
            saved_paths = []
            output_folder.mkdir(parents=True, exist_ok=True)
            for page, asset in zip(result["pages"], artifacts, strict=True):
                metadata = asset["metadata"]
                path = output_folder / (stem + ".png")
                number = 2
                while path.exists():
                    path = output_folder / f"{stem}-{number}.png"
                    number += 1
                saved_paths.append(path)
                path.write_bytes(page["png"])
                path.with_suffix(".json").write_text(json.dumps(metadata))
            return result, ids, saved_paths

        def loaded(answer):
            self._busy = False
            if generation != self._generation:
                self.refresh()
                return
            result, ids, saved_paths = answer
            self.asset_ids = ids
            for path in saved_paths:
                self.saved.emit(path)
            self._say(
                self.tr("Saved {0} pages covering {1} models. Unsupported: {2}.").format(
                    len(ids), len(result["covered"]), len(result["unsupported"])
                )
            )
            self.refresh()

        run_in_background(read, loaded, self._sheet_failed)

    def _sheet_failed(self, error: Exception) -> None:
        self._busy = False
        self._say(self.tr("The sheet failed: {0}").format(error_text(error)))
        self.refresh()

    def _save(self, image: QImage, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not image.save(str(path)):
            self._say(self.tr("Could not write {0}").format(path))
        else:
            self._say(
                self.tr("Saved {0} ({1} × {2} px)").format(path.name, image.width(), image.height())
            )
            self.saved.emit(path)
        self.refresh()

    def open_folder(self) -> None:
        folder = self.upload_folder()
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))


__all__ = ["ModelPanel", "ModelViewer", "OffscreenScene", "RenderUnavailable", "contact_sheet"]
