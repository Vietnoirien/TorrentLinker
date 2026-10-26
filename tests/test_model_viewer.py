import shutil
import threading
from pathlib import Path

import pytest
from PySide6.QtGui import QDesktopServices, QImage

from torrentlinker.gui import model_viewer
from torrentlinker.gui.model_viewer import ModelPanel, OffscreenScene, RenderUnavailable
from torrentlinker.matching import IgnoreList
from torrentlinker.mesh import ISO_PITCH, ISO_YAW
from torrentlinker.scan import scan_item

MODELS = Path(__file__).parent / "fixtures" / "models"
TITLE = "Boite.NOTAG.STL"


@pytest.fixture
def gl() -> None:
    """Rendering needs OpenGL, which a machine without a display or GPU may lack."""
    try:
        with OffscreenScene():
            pass
    except RenderUnavailable as e:
        pytest.skip(f"no offscreen OpenGL here: {e}")


def library(tmp_path: Path, *names: str) -> Path:
    folder = tmp_path / "Library"
    folder.mkdir()
    for name in names:
        source = {"stl": "cube-binary.stl", "obj": "box.obj", "3mf": "two-boxes.3mf"}.get(
            name.rsplit(".", 1)[-1].lower()
        )
        if source:
            shutil.copy(MODELS / source, folder / name)
        else:
            (folder / name).write_bytes(b"ISO-10303-21;")
    return folder


def panel(qtbot, tmp_path: Path, pack: bool = False) -> ModelPanel:  # type: ignore[no-untyped-def]
    view = ModelPanel(tmp_path / "uploads", lambda: TITLE, IgnoreList.default, lambda: pack)
    qtbot.addWidget(view)
    view.show()
    return view


def loaded(qtbot, view: ModelPanel) -> None:  # type: ignore[no-untyped-def]
    qtbot.waitUntil(lambda: view.viewer.display is not None, timeout=10000)


def test_an_item_with_no_drawable_format_says_so_and_shows_no_viewer(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    folder = library(tmp_path, "Gear.step", "Print.gcode")
    view = panel(qtbot, tmp_path)

    view.set_item(scan_item(folder))

    assert "No preview" in view.message.text() and "STL, OBJ and 3MF" in view.message.text()
    assert view.viewer.isHidden() and view.capture_button.isHidden()
    assert view.viewer.display is None


def test_the_model_is_read_off_the_gui_thread_and_framed_isometrically(
    qtbot, tmp_path: Path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    folder = library(tmp_path, "Boite.stl")
    threads: list[threading.Thread] = []
    real = model_viewer.prepare_display

    def spy(path: Path, *args, **kwargs):  # type: ignore[no-untyped-def]
        threads.append(threading.current_thread())
        return real(path, *args, **kwargs)

    monkeypatch.setattr(model_viewer, "prepare_display", spy)
    view = panel(qtbot, tmp_path)

    view.set_item(scan_item(folder / "Boite.stl"))
    loaded(qtbot, view)

    assert threads and threads[0] is not threading.main_thread()
    assert view.viewer.view_state() == (ISO_YAW, ISO_PITCH, 1.0)
    assert view.viewer.root is not None and float(view.viewer.root.property("baseDistance")) > 1
    assert not view.viewer.isHidden() and not view.models.isVisible()  # one model: no choice


def test_a_folder_offers_each_model_it_holds(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    folder = library(tmp_path, "b.stl", "a.obj", "c.3mf", "d.step")
    view = panel(qtbot, tmp_path)
    holder = tmp_path / "Pack"
    holder.mkdir()
    for f in folder.iterdir():
        shutil.copy(f, holder / f.name)

    view.set_item(scan_item(holder))

    assert [view.models.itemText(i) for i in range(view.models.count())] == [
        "a.obj",
        "b.stl",
        "c.3mf",
    ]
    assert view.models.isVisible()
    loaded(qtbot, view)


def test_a_model_that_cannot_be_read_says_why_and_leaves_the_image_to_the_user(
    qtbot, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    folder = library(tmp_path)
    (folder / "Broken.stl").write_bytes(b"this is not a mesh")
    view = panel(qtbot, tmp_path)

    view.set_item(scan_item(folder / "Broken.stl"))

    qtbot.waitUntil(lambda: "cannot be drawn" in view.message.text(), timeout=10000)
    assert not view.capture_button.isEnabled()


def test_a_late_result_for_a_previous_item_is_ignored(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    folder = library(tmp_path, "Boite.stl")
    view = panel(qtbot, tmp_path)
    view.set_item(scan_item(folder / "Boite.stl"))
    loaded(qtbot, view)

    view.set_item(None)
    stale = view.viewer.display  # cleared with the item
    assert stale is None
    view._loaded(view._generation - 1, model_viewer.prepare_display(folder / "Boite.stl"))

    assert view.viewer.display is None


def test_capture_saves_a_png_of_at_least_1000_px_in_the_uploads_folder(
    qtbot, tmp_path: Path, gl
) -> None:  # type: ignore[no-untyped-def]
    folder = library(tmp_path, "Boite.stl")
    view = panel(qtbot, tmp_path)
    view.set_item(scan_item(folder / "Boite.stl"))
    loaded(qtbot, view)
    saved: list[Path] = []
    view.saved.connect(saved.append)

    view.capture()
    qtbot.waitUntil(lambda: len(saved) == 1, timeout=20000)
    view.capture()
    qtbot.waitUntil(lambda: len(saved) == 2, timeout=20000)

    first, second = view.upload_folder() / f"{TITLE}.png", view.upload_folder() / f"{TITLE}-2.png"
    assert saved == [first, second]  # a new capture never overwrites the previous one
    assert view.upload_folder() == tmp_path / "uploads" / TITLE
    image = QImage(str(first))
    assert image.width() >= 1000 and image.height() > 0
    colours = {
        image.pixelColor(x, y).name()
        for x in range(0, image.width(), 40)
        for y in range(0, image.height(), 40)
    }
    assert len(colours) > 2  # the model is drawn over the plain background
    assert not list(folder.glob("*.png"))  # nothing written in the Library
    assert first.name in view.paths.text() and second.name in view.paths.text()


def test_capture_follows_the_view_the_user_turned_it_to(qtbot, tmp_path: Path, gl) -> None:  # type: ignore[no-untyped-def]
    folder = library(tmp_path, "Boite.stl")
    view = panel(qtbot, tmp_path)
    view.set_item(scan_item(folder / "Boite.stl"))
    loaded(qtbot, view)
    view.capture()
    qtbot.waitUntil(lambda: not view._busy, timeout=20000)
    assert view.viewer.root is not None
    view.viewer.root.setProperty("yaw", 200.0)
    view.viewer.root.setProperty("zoom", 0.5)
    assert view.viewer.view_state() == (200.0, ISO_PITCH, 0.5)

    view.capture()
    qtbot.waitUntil(lambda: not view._busy, timeout=20000)

    near = QImage(str(view.upload_folder() / f"{TITLE}-2.png"))
    far = QImage(str(view.upload_folder() / f"{TITLE}.png"))
    assert near != far  # another angle and distance, another picture


def test_a_pack_sheet_has_a_grid_of_models_with_their_names(qtbot, tmp_path: Path, gl) -> None:  # type: ignore[no-untyped-def]
    folder = library(tmp_path, "a.stl", "b.obj", "c.3mf", "d.stl", "readme.txt")
    holder = tmp_path / "Pack"
    holder.mkdir()
    for f in folder.iterdir():
        shutil.copy(f, holder / f.name)
    view = panel(qtbot, tmp_path, pack=True)
    view.set_item(scan_item(holder))
    assert not view.sheet_button.isHidden()
    saved: list[Path] = []
    view.saved.connect(saved.append)

    view.sheet_button.click()

    qtbot.waitUntil(lambda: bool(saved), timeout=20000)
    assert saved == [view.upload_folder() / f"{TITLE}-pack.png"]
    sheet = QImage(str(saved[0]))
    assert sheet.width() >= 1000
    dark = [  # the file names are written under each of the 4 pictures
        sum(1 for x in range(0, sheet.width(), 3) if sheet.pixelColor(x, y).lightness() < 100)
        for y in range(0, sheet.height(), 8)
    ]
    assert sum(1 for n in dark if n) >= 4


def test_the_pack_sheet_button_is_only_for_a_pack(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    folder = library(tmp_path, "Boite.stl")
    view = panel(qtbot, tmp_path, pack=False)

    view.set_item(scan_item(folder / "Boite.stl"))

    assert view.sheet_button.isHidden() and not view.capture_button.isHidden()


def test_the_folder_opens_even_before_any_capture(qtbot, tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url.toLocalFile()))
    view = panel(qtbot, tmp_path)

    view.open_folder()

    assert opened == [str(tmp_path / "uploads" / TITLE)]
    assert (tmp_path / "uploads" / TITLE).is_dir()


@pytest.mark.parametrize("yaw,zoom", [(1125, 0.15), (-1125, 6.0)])
def test_capture_preserves_valid_extreme_viewer_camera_state(qtbot, tmp_path, yaw, zoom):
    import json

    folder = library(tmp_path, "Boite.stl")
    view = panel(qtbot, tmp_path)
    view.set_item(scan_item(folder / "Boite.stl"))
    loaded(qtbot, view)
    root = view.viewer.root
    assert root is not None
    root.setProperty("yaw", yaw)
    root.setProperty("pitch", 20.0)
    root.setProperty("zoom", zoom)
    base_distance = float(root.property("baseDistance"))
    saved = []
    view.saved.connect(saved.append)
    view.capture()
    qtbot.waitUntil(lambda: bool(saved), timeout=20000)
    metadata = json.loads(saved[0].with_suffix(".json").read_text())
    camera = metadata["pieces"][0]["camera"]
    assert camera["yaw"] == (yaw + 180) % 360 - 180
    assert camera["pitch"] == 70
    assert camera["zoom"] == pytest.approx(1 / zoom)
    assert camera["distance"] == pytest.approx(base_distance * zoom)
    assert not QImage(str(saved[0])).isNull()


def test_shared_camera_basis_matches_qml_orbit_of_y_up_display_geometry():
    import numpy as np
    from PySide6.QtGui import QQuaternion, QVector3D

    from torrentlinker.model_rendering import Camera

    raw = np.array([1.0, 2.0, 3.0])
    display_point = QVector3D(1, 3, -2)  # mesh.display_buffer's Z-up -> Y-up mapping.
    for yaw, elevation in ((45, 20), (123, -37), (-90, 0)):
        qml_camera = QQuaternion.fromEulerAngles(-elevation, yaw, 0)
        expected = qml_camera.conjugated().rotatedVector(display_point)
        camera = Camera(yaw=yaw, pitch=90 - elevation)
        np.testing.assert_allclose(
            camera.view_basis() @ raw, [expected.x(), expected.y(), expected.z()], atol=1e-5
        )
