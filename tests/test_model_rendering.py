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
