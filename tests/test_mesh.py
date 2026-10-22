import struct
from pathlib import Path

import numpy as np
import pytest

from torrentlinker.mesh import (
    FIELD_OF_VIEW,
    ISO_PITCH,
    ISO_YAW,
    SHEET_MODELS,
    SHEET_WIDTH,
    MeshError,
    display_buffer,
    frame_distance,
    is_previewable,
    limit_triangles,
    load_mesh,
    parse_3mf,
    parse_obj,
    parse_stl,
    prepare_display,
    previewable,
    sheet_layout,
    sheet_models,
)

MODELS = Path(__file__).parent / "fixtures" / "models"  # a 10 x 20 x 30 box, 12 triangles


def extent(mesh) -> list[float]:  # type: ignore[no-untyped-def]
    low, high = mesh.bounds()
    return [float(v) for v in high - low]


def test_a_binary_stl_even_one_starting_with_solid_is_read() -> None:
    mesh = load_mesh(MODELS / "cube-binary.stl")

    assert mesh.triangle_count == 12
    assert extent(mesh) == [10, 20, 30]


def test_an_ascii_stl_is_read() -> None:
    mesh = load_mesh(MODELS / "cube-ascii.stl")

    assert mesh.triangle_count == 12
    assert extent(mesh) == [10, 20, 30]


def test_an_obj_is_read_with_its_polygons_cut_into_triangles_and_groups_ignored() -> None:
    mesh = load_mesh(MODELS / "box.obj")

    assert mesh.triangle_count == 12  # six quads
    assert extent(mesh) == [10, 20, 30]


def test_an_obj_face_may_count_vertices_from_the_end() -> None:
    mesh = load_mesh(MODELS / "box-relative.obj")

    assert mesh.triangles.tolist() == [[0, 1, 2], [0, 2, 3]]


def test_a_3mf_places_each_build_item_and_component_by_its_transform() -> None:
    mesh = load_mesh(MODELS / "two-boxes.3mf")

    assert mesh.triangle_count == 24
    low, high = mesh.bounds()
    # box one at the origin; box two moved 100 along x by its component, 50 along y by its item
    assert low.tolist() == [0, 0, 0]
    assert high.tolist() == [110, 70, 30]


def test_garbage_is_refused_whatever_its_extension(tmp_path: Path) -> None:
    for name in ("a.stl", "a.obj", "a.3mf"):
        (tmp_path / name).write_bytes(b"not a model at all")
        with pytest.raises(MeshError):
            load_mesh(tmp_path / name)
    (tmp_path / "a.step").write_bytes(b"ISO-10303-21;")
    with pytest.raises(MeshError, match="No preview"):
        load_mesh(tmp_path / "a.step")


def test_a_truncated_binary_stl_is_refused() -> None:
    whole = (MODELS / "cube-binary.stl").read_bytes()

    with pytest.raises(MeshError):
        parse_stl(whole[:-10])


def test_an_obj_pointing_to_missing_vertices_is_refused() -> None:
    with pytest.raises(MeshError):
        parse_obj("v 0 0 0\nv 1 0 0\nf 1 2 9\n")


def test_a_3mf_without_a_model_is_refused() -> None:
    import io
    import zipfile

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("readme.txt", "hello")

    with pytest.raises(MeshError, match="no 3D model"):
        parse_3mf(out.getvalue())


def test_only_the_three_mesh_formats_can_be_previewed() -> None:
    paths = ["b.STL", "a.3mf", "c.step", "d.gcode", "e.OBJ", "f.blend", "dir.stl/readme"]

    assert [is_previewable(p) for p in paths] == [True, True, False, False, True, False, False]
    assert previewable(paths) == ["a.3mf", "b.STL", "e.OBJ"]


def test_display_data_is_centred_y_up_and_flat_shaded() -> None:
    shown = display_buffer(load_mesh(MODELS / "cube-binary.stl"))

    assert (shown.triangles, shown.shown, shown.vertex_count) == (12, 12, 36)
    data = np.frombuffer(shown.buffer, dtype=np.float32).reshape(-1, 6)
    position, normal = data[:, :3], data[:, 3:]
    # Z-up in the file (height 30) is Y-up on screen, around the origin
    assert (position.max(axis=0) - position.min(axis=0)).tolist() == [10, 30, 20]
    assert position.min(axis=0).tolist() == [-5, -15, -10]
    assert np.allclose(np.linalg.norm(normal, axis=1), 1)
    assert shown.radius == pytest.approx(np.linalg.norm([10, 20, 30]) / 2)
    assert shown.half_extents == (5, 15, 10)  # Y-up: the file's Z (30) is the height


def test_a_big_mesh_is_decimated_to_its_cap_and_keeps_its_shape() -> None:
    # a 40 x 40 grid of squares, 3200 triangles, bent into a bowl
    side = 41
    xs, ys = np.meshgrid(np.arange(side), np.arange(side))
    vertices = np.stack([xs.ravel(), ys.ravel(), (xs.ravel() - 20) ** 2 / 40], axis=1)
    index = np.arange(side * side).reshape(side, side)
    a, b, c, d = index[:-1, :-1], index[:-1, 1:], index[1:, 1:], index[1:, :-1]
    triangles = np.concatenate(
        [np.stack([a, b, c], -1).reshape(-1, 3), np.stack([a, c, d], -1).reshape(-1, 3)]
    )
    from torrentlinker.mesh import Mesh

    mesh = Mesh(vertices.astype(np.float32), triangles.astype(np.int32))

    fewer = limit_triangles(mesh, 800)

    assert 100 < fewer.triangle_count <= 800
    low, high = fewer.bounds()
    assert high[0] - low[0] > 35 and high[1] - low[1] > 35  # still spans the bowl
    assert limit_triangles(mesh, 5000) is mesh  # under the cap: untouched
    assert display_buffer(mesh, 800).triangles == 3200  # the file's own count is kept


def test_a_large_binary_stl_is_prepared_within_its_cap(tmp_path: Path) -> None:
    rng = np.random.default_rng(1)
    count = 200_000
    record = np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])
    triangles = np.zeros(count, record)
    triangles["v"] = rng.random((count, 3, 3), dtype=np.float32) * 100
    path = tmp_path / "big.stl"
    path.write_bytes(b"\0" * 80 + struct.pack("<I", count) + triangles.tobytes())

    shown = prepare_display(path, cap=20_000)

    assert shown.triangles == count
    assert 0 < shown.shown <= 20_000


def projected_fill(half: tuple[float, float, float], distance: float, aspect: float) -> float:
    """How much of the half view (1 = touching the edge) the box's corners reach, seen
    from the isometric angle with a camera `distance` away: independent of mesh.py."""
    import itertools
    import math

    yaw, pitch = math.radians(ISO_YAW), math.radians(ISO_PITCH)
    eye = distance * np.array(
        [math.sin(yaw) * math.cos(pitch), math.sin(pitch), math.cos(yaw) * math.cos(pitch)]
    )
    forward = -eye / np.linalg.norm(eye)
    right = np.cross(forward, [0, 1, 0])
    right /= np.linalg.norm(right)
    up = np.cross(right, forward)
    tan_v = math.tan(math.radians(FIELD_OF_VIEW) / 2)
    worst = 0.0
    for signs in itertools.product((-1, 1), repeat=3):
        offset = np.array(signs) * half - eye
        depth = offset @ forward
        worst = max(
            worst, abs(offset @ right) / depth / (tan_v * aspect), abs(offset @ up) / depth / tan_v
        )
    return worst


def test_the_camera_stands_where_the_whole_box_just_fits_whatever_the_view_shape() -> None:
    box = (5.0, 15.0, 10.0)

    for aspect in (0.4, 1.0, 1.33, 2.5):
        distance = frame_distance(box, aspect)
        fill = projected_fill(box, distance, aspect)
        assert fill == pytest.approx(1 / 1.08, abs=1e-6)  # touches nothing, wastes little
    assert frame_distance(box, 0.5) > frame_distance(box, 2.0)  # a narrow view needs more room
    assert frame_distance((0, 0, 0), 1) > 0  # a flat or empty box does not divide by zero


def test_the_view_opens_isometric() -> None:
    assert ISO_PITCH == pytest.approx(35.264, abs=1e-3)


def test_a_contact_sheet_is_at_least_1000_px_wide_with_room_for_each_name() -> None:
    for count in range(1, SHEET_MODELS + 1):
        layout = sheet_layout(count)
        assert layout.width == SHEET_WIDTH >= 1000
        assert len(layout.cells) == count
        for cell in layout.cells:
            x, y, w, h = cell.picture
            lx, ly, lw, lh = cell.label
            assert (lx, ly, lw) == (x, y + h, w) and lh > 0  # the name right under it
            assert x >= 0 and x + w <= layout.width and ly + lh <= layout.height
        rectangles = [c.picture for c in layout.cells]
        assert len(set(rectangles)) == count  # nothing overlaps another


def test_a_contact_sheet_is_as_square_as_three_columns_allow() -> None:
    def shape(count: int) -> tuple[int, int]:
        cells = sheet_layout(count).cells
        return len({c.picture[1] for c in cells}), len({c.picture[0] for c in cells})

    assert [shape(n) for n in (1, 2, 4, 5, 9)] == [(1, 1), (1, 2), (2, 2), (2, 3), (3, 3)]
    assert len(sheet_layout(20).cells) == SHEET_MODELS  # never more than nine


def test_a_pack_sheet_shows_its_first_nine_models_by_name() -> None:
    paths = [f"Pack/m{i:02}.stl" for i in range(15)] + ["Pack/readme.txt", "Pack/a.step"]

    shown = sheet_models(paths)

    assert shown == [f"Pack/m{i:02}.stl" for i in range(9)]
