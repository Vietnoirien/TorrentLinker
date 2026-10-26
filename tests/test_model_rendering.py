"""Shared rendering covers every selected piece and preserves source geometry."""

import threading

from torrentlinker.model_rendering import Camera, render_models

OBJ = "v 0 0 0\nv 1 0 0\nv 0 1 0\nv 0 0 1\nf 1 2 3\nf 1 2 4\n"


def test_more_than_nine_parts_have_explicit_complete_sheet_coverage(tmp_path):
    paths = []
    for index in range(13):
        path = tmp_path / f"piece-{index}.obj"
        path.write_text(OBJ)
        paths.append(path)
    result = render_models(paths, [Camera()] * len(paths), threading.Event(), lambda _: None)
    assert len(result["pages"]) == 2
    assert result["covered"] == [str(path) for path in paths]
    assert result["unsupported"] == []
    assert all(path.read_text() == OBJ for path in paths)
    assert result["pages"][0]["png"].startswith(b"\x89PNG")
    assert len(result["pages"][0]["pieces"]) == 9
    assert len(result["pages"][1]["pieces"]) == 4


def test_unsupported_piece_is_explicit_and_cancellation_stops_worker(tmp_path):
    import pytest

    invalid = tmp_path / "broken.stl"
    invalid.write_text("broken input")
    result = render_models([invalid], [Camera()], threading.Event(), lambda _: None)
    assert result["complete"] is False
    assert result["covered"] == []
    assert result["unsupported"][0]["file"] == str(invalid)
    stop = threading.Event()
    stop.set()
    with pytest.raises(InterruptedError, match="cancelled"):
        render_models([invalid], [Camera()], stop, lambda _: None)


def test_camera_changes_render_pixels_and_is_reproducible(tmp_path):
    path = tmp_path / "piece.obj"
    path.write_text(OBJ)
    first = render_models([path], [Camera.preset("front")], threading.Event(), lambda _: None)
    second = render_models([path], [Camera.preset("top")], threading.Event(), lambda _: None)
    assert first["pages"][0]["png"] != second["pages"][0]["png"]
    assert first["pages"][0]["pieces"][0]["camera"]["pitch"] == 90
    assert second["pages"][0]["pieces"][0]["camera"]["pitch"] == 0
    assert path.read_text() == OBJ


def test_inventory_above_render_limit_retains_every_piece_with_explicit_deferred_geometry(tmp_path):
    from torrentlinker.model_rendering import inspect_models

    paths = []
    for number in range(109):
        path = tmp_path / f"piece-{number}.obj"
        path.write_text(OBJ)
        paths.append(path)
    result = inspect_models(paths, threading.Event())
    assert result["count"] == 109
    assert len(result["models"]) == 109
    assert result["models"][0]["triangles"] == 2
    assert result["models"][-1]["geometry_status"] == "deferred"
    assert result["models"][-1]["geometry_reason"]


def test_cardinal_cameras_match_qml_z_up_view_basis():
    import numpy as np

    expected = {
        "front": ((0, -1, 0), (1, 0, 0), (0, 0, 1)),
        "back": ((0, 1, 0), (-1, 0, 0), (0, 0, 1)),
        "left": ((-1, 0, 0), (0, -1, 0), (0, 0, 1)),
        "right": ((1, 0, 0), (0, 1, 0), (0, 0, 1)),
        "top": ((0, 0, 1), (1, 0, 0), (0, 1, 0)),
        "bottom": ((0, 0, -1), (1, 0, 0), (0, -1, 0)),
    }
    for name, (toward, right, up) in expected.items():
        basis = Camera.preset(name).view_basis()
        np.testing.assert_allclose(basis, [right, up, toward], atol=1e-12)
    for near, far in [("front", "back"), ("left", "right"), ("top", "bottom")]:
        np.testing.assert_allclose(
            Camera.preset(near).view_basis()[2], -Camera.preset(far).view_basis()[2], atol=1e-12
        )


def test_opposite_cardinals_render_the_opposite_occluding_surface(tmp_path):
    import io

    from PIL import Image

    # A tilted triangle sits in front of a flat square. From the back the square
    # occludes it completely; rotating the same front image cannot reproduce that.
    geometry = (
        "v -2 1 -2\nv 2 1 -2\nv 2 1 2\nv -2 1 2\n"
        "v -1 -1 -1\nv 1 -1 -1\nv 0 0 1\n"
        "f 1 2 3\nf 1 3 4\nf 5 6 7\n"
    )
    for front, back, name in [("front", "back", "y"), ("left", "right", "x")]:
        text = geometry
        if name == "x":
            # Swap raw X/Y to move the occluding surfaces to the X sides.
            rows = []
            for line in geometry.splitlines():
                parts = line.split()
                rows.append(
                    " ".join([parts[0], parts[2], parts[1], parts[3]]) if parts[0] == "v" else line
                )
            text = "\n".join(rows)
        path = tmp_path / f"{name}.obj"
        path.write_text(text)
        images = []
        for preset in (front, back):
            result = render_models(
                [path], [Camera.preset(preset)], threading.Event(), lambda _: None
            )
            images.append(Image.open(io.BytesIO(result["pages"][0]["png"])))
        assert images[0].getpixel((600, 600)) != images[1].getpixel((600, 600))
