"""3D meshes for the Upload tab's preview: STL, OBJ and 3MF read into one type.

Only the geometry is read, never written or changed on disk. Models of c411's 3D
category are Z-up (the printers' convention); `display_buffer` turns them to the Y-up
the viewer draws. Everything here is plain numpy, so it runs on a worker thread.
"""

from __future__ import annotations

import io
import math
import re
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

# What the viewer can read; STEP, GCODE, BLEND, F3D, SLDPRT and FCStd are not meshes.
MESH_FORMATS = ("stl", "obj", "3mf")
DISPLAY_TRIANGLES = 300_000  # more is decimated for display: a GPU draws it, a GUI does not
SHEET_MODELS = 9  # a Pack's contact sheet shows at most this many models
SHEET_WIDTH = 1500  # px; c411 asks for at least 1000
ISO_YAW = 45.0  # degrees: the isometric angle the view opens at
ISO_PITCH = math.degrees(math.atan(1 / math.sqrt(2)))
FIELD_OF_VIEW = 30.0  # degrees, vertical


class MeshError(ValueError):
    """The file is not a mesh this module can read."""


@dataclass(frozen=True)
class Mesh:
    vertices: NDArray[np.float32]  # (n, 3)
    triangles: NDArray[np.int32]  # (m, 3) indices into vertices

    @property
    def triangle_count(self) -> int:
        return len(self.triangles)

    def bounds(self) -> tuple[NDArray[np.float32], NDArray[np.float32]]:
        used = self.vertices[np.unique(self.triangles)]
        return used.min(axis=0), used.max(axis=0)


@dataclass(frozen=True)
class DisplayMesh:
    """A mesh ready for the viewer: centred, Y-up, one flat-shaded triangle after another
    as float32 position and normal."""

    buffer: bytes
    vertex_count: int
    radius: float  # of the bounding sphere around the centre of the bounding box
    half_extents: tuple[float, float, float]  # of the bounding box around the origin, Y-up
    triangles: int  # in the file
    shown: int  # after decimation

    STRIDE = 24


def is_previewable(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return "." in name and name.rsplit(".", 1)[-1].casefold() in MESH_FORMATS


def previewable(paths: Iterable[str]) -> list[str]:
    """The model files of an item that can be drawn, by path."""
    return sorted(p for p in paths if is_previewable(p))


def load_mesh(path: Path) -> Mesh:
    ext = path.suffix.casefold()
    data = path.read_bytes()
    if ext == ".stl":
        return parse_stl(data)
    if ext == ".obj":
        return parse_obj(data.decode("utf-8", errors="replace"))
    if ext == ".3mf":
        return parse_3mf(data)
    raise MeshError(f"No preview for {ext or 'this file'}")


def parse_stl(data: bytes) -> Mesh:
    """Binary STL (80 bytes of header, a count, 50 bytes a triangle) or ASCII; some
    binary files start with `solid` too, so the size decides."""
    if len(data) >= 84:
        count = int.from_bytes(data[80:84], "little")
        if len(data) == 84 + 50 * count and count:
            record = np.dtype([("normal", "<f4", 3), ("vertices", "<f4", (3, 3)), ("pad", "<u2")])
            triangles = np.frombuffer(data, record, count, offset=84)
            return _unwelded(triangles["vertices"].reshape(-1, 3))
    if data.lstrip()[:5].lower() == b"solid":
        found = re.findall(rb"vertex\s+(\S+)\s+(\S+)\s+(\S+)", data, re.IGNORECASE)
        if found and len(found) % 3 == 0:
            try:
                vertices = np.array(found, dtype=np.float64).astype(np.float32)
            except ValueError as e:
                raise MeshError("Unreadable ASCII STL") from e
            return _unwelded(vertices)
    raise MeshError("Not a binary or ASCII STL file")


def parse_obj(text: str) -> Mesh:
    """Vertices and faces; groups, normals, textures and materials are ignored, and a
    polygon is cut into a fan of triangles."""
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int]] = []
    try:
        for line in text.splitlines():
            parts = line.split()
            if not parts:
                continue
            if parts[0] == "v" and len(parts) >= 4:
                vertices.append((float(parts[1]), float(parts[2]), float(parts[3])))
            elif parts[0] == "f" and len(parts) >= 4:
                ring = [_obj_index(p, len(vertices)) for p in parts[1:]]
                faces += [(ring[0], ring[i], ring[i + 1]) for i in range(1, len(ring) - 1)]
    except ValueError as e:
        raise MeshError("Unreadable OBJ file") from e
    if not vertices or not faces:
        raise MeshError("This OBJ file has no faces")
    triangles = np.array(faces, dtype=np.int32)
    if np.max(triangles) >= len(vertices) or np.min(triangles) < 0:
        raise MeshError("This OBJ file's faces point to missing vertices")
    return Mesh(np.array(vertices, dtype=np.float32), triangles)


def _obj_index(token: str, count: int) -> int:
    """`7`, `7/1`, `7//2` or `-1` (the last vertex so far) as a 0-based index."""
    n = int(token.split("/")[0])
    return n - 1 if n > 0 else count + n


def parse_3mf(data: bytes) -> Mesh:
    """The build items of `3D/3dmodel.model`, each object's meshes (and components)
    placed by their transforms, merged into one mesh. Units and materials are ignored."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = {n.casefold(): n for n in archive.namelist()}
            name = names.get("3d/3dmodel.model") or next(
                (n for k, n in names.items() if k.endswith(".model")), None
            )
            if name is None:
                raise MeshError("This 3MF file has no 3D model")
            root = ET.fromstring(archive.read(name))
    except (zipfile.BadZipFile, ET.ParseError) as e:
        raise MeshError("Unreadable 3MF file") from e
    objects = {o.get("id", ""): o for o in _children(root, "resources", "object")}
    items = [(i.get("objectid", ""), _transform(i.get("transform"))) for i in _build(root)]
    if not items:  # a build-less file: everything that is a mesh of its own
        items = [(i, np.eye(4)[:, :3]) for i, o in objects.items() if _children(o, "mesh")]
    parts: list[Mesh] = []
    for object_id, transform in items:
        _place(objects, object_id, transform, parts, depth=0)
    if not parts:
        raise MeshError("This 3MF file has no mesh")
    offsets = np.cumsum([0] + [len(p.vertices) for p in parts[:-1]])
    return Mesh(
        np.concatenate([p.vertices for p in parts]),
        np.concatenate([p.triangles + o for p, o in zip(parts, offsets, strict=True)]),
    )


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _children(node: ET.Element, *path: str) -> list[ET.Element]:
    """The descendants reached by following `path` by local tag name (namespaces are
    ignored: 3MF extensions add their own)."""
    found = [node]
    for step in path:
        found = [c for n in found for c in n if _local(c.tag) == step]
    return found


def _build(root: ET.Element) -> list[ET.Element]:
    return _children(root, "build", "item")


def _transform(text: str | None) -> NDArray[np.float64]:
    """3MF writes a 4x3 matrix row by row, applied to a row vector: `[x y z 1] · M`."""
    if not text:
        return np.eye(4)[:, :3]
    try:
        values = [float(v) for v in text.split()]
    except ValueError as e:
        raise MeshError("Unreadable 3MF transform") from e
    if len(values) != 12:
        raise MeshError("Unreadable 3MF transform")
    return np.array(values).reshape(4, 3)


def _compose(inner: NDArray[np.float64], outer: NDArray[np.float64]) -> NDArray[np.float64]:
    """The transform that applies `inner`, then `outer`."""
    column = [[0], [0], [0], [1]]
    return (np.hstack([inner, column]) @ np.hstack([outer, column]))[:, :3]


def _place(
    objects: dict[str, ET.Element],
    object_id: str,
    transform: NDArray[np.float64],
    parts: list[Mesh],
    depth: int,
) -> None:
    node = objects.get(object_id)
    if node is None or depth > 16:
        return
    for mesh in _children(node, "mesh"):
        vertices = np.array(
            [
                (float(v.get("x", 0)), float(v.get("y", 0)), float(v.get("z", 0)))
                for v in _children(mesh, "vertices", "vertex")
            ],
            dtype=np.float64,
        )
        triangles = np.array(
            [
                (int(t.get("v1", 0)), int(t.get("v2", 0)), int(t.get("v3", 0)))
                for t in _children(mesh, "triangles", "triangle")
            ],
            dtype=np.int32,
        )
        if not len(vertices) or not len(triangles):
            continue
        if np.max(triangles) >= len(vertices) or np.min(triangles) < 0:
            raise MeshError("This 3MF mesh points to missing vertices")
        placed = np.hstack([vertices, np.ones((len(vertices), 1))]) @ transform
        parts.append(Mesh(placed.astype(np.float32), triangles))
    for component in _children(node, "components", "component"):
        _place(
            objects,
            component.get("objectid", ""),
            _compose(_transform(component.get("transform")), transform),
            parts,
            depth + 1,
        )


def _unwelded(corners: NDArray[np.float32]) -> Mesh:
    """Three corners per triangle, as STL stores them."""
    corners = np.ascontiguousarray(corners, dtype=np.float32)
    return Mesh(corners, np.arange(len(corners), dtype=np.int32).reshape(-1, 3))


def limit_triangles(mesh: Mesh, cap: int) -> Mesh:
    """At most about `cap` triangles: vertices falling in the same cell of a grid over
    the bounding box merge into their average, and the triangles that collapse go. The
    grid is refined or coarsened until the count fits."""
    if mesh.triangle_count <= cap:
        return mesh
    low, high = mesh.bounds()
    extent = float(max(np.max(high - low), 1e-9))
    cells = max(4, int(math.sqrt(cap / 12)))
    best: Mesh | None = None
    merged = mesh
    for _ in range(10):
        merged = _cluster(mesh, low, extent / cells, cells)
        if merged.triangle_count > cap:
            cells = max(2, int(cells * 0.7))
            continue
        best = merged
        if merged.triangle_count >= cap // 2:
            break
        cells = int(cells * 1.4) + 1
    if best is None:  # triangles spread too evenly to merge: keep every n-th
        step = math.ceil(merged.triangle_count / cap)
        return Mesh(merged.vertices, merged.triangles[::step])
    return best


def _cluster(mesh: Mesh, origin: NDArray[np.float32], cell: float, cells: int) -> Mesh:
    grid = np.minimum(((mesh.vertices - origin) / cell).astype(np.int64), cells)
    side = cells + 1
    keys = grid[:, 0] + side * (grid[:, 1] + side * grid[:, 2])
    _, first, inverse = np.unique(keys, return_index=True, return_inverse=True)
    inverse = inverse.reshape(-1)
    counts = np.bincount(inverse).astype(np.float64)
    averaged = np.stack(
        [np.bincount(inverse, weights=mesh.vertices[:, axis]) / counts for axis in range(3)], axis=1
    )
    triangles = inverse[mesh.triangles]
    a, b, c = triangles[:, 0], triangles[:, 1], triangles[:, 2]
    kept = triangles[(a != b) & (b != c) & (a != c)]
    return Mesh(averaged.astype(np.float32), kept.astype(np.int32))


def display_buffer(mesh: Mesh, cap: int = DISPLAY_TRIANGLES) -> DisplayMesh:
    """The viewer's data: decimated to `cap` triangles, centred on the origin, turned
    from Z-up to Y-up, with a flat normal on each triangle."""
    shown = limit_triangles(mesh, cap)
    if not shown.triangle_count:
        raise MeshError("This model has no visible triangle")
    low, high = shown.bounds()
    centre = (low + high) / 2
    moved = shown.vertices - centre
    upright = np.stack([moved[:, 0], moved[:, 2], -moved[:, 1]], axis=1)
    corners = upright[shown.triangles]  # (m, 3, 3)
    normals = np.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0])
    length = np.linalg.norm(normals, axis=1, keepdims=True)
    normals = np.divide(normals, length, out=np.zeros_like(normals), where=length > 0)
    interleaved = np.concatenate(
        [corners, np.repeat(normals[:, None, :], 3, axis=1)], axis=2
    ).astype(np.float32)
    size = high - low  # Z-up; Y-up is (x, z, y)
    half = (float(size[0]) / 2, float(size[2]) / 2, float(size[1]) / 2)
    return DisplayMesh(
        interleaved.tobytes(),
        shown.triangle_count * 3,
        float(np.linalg.norm(size) / 2),
        half,
        mesh.triangle_count,
        shown.triangle_count,
    )


def prepare_display(path: Path, cap: int = DISPLAY_TRIANGLES) -> DisplayMesh:
    """Read a model file and make it displayable; slow for a big file, so run it off the
    GUI thread."""
    return display_buffer(load_mesh(path), cap)


def frame_distance(
    half_extents: Sequence[float],
    aspect: float,
    yaw: float = ISO_YAW,
    pitch: float = ISO_PITCH,
    margin: float = 1.08,
) -> float:
    """How far from the centre a camera looking at it from (yaw, pitch) degrees must stand
    for the bounding box (Y-up, with these half extents) to fit a view `aspect` wide, with
    `margin` to spare: the box's eight corners, projected."""
    tan_v = math.tan(math.radians(FIELD_OF_VIEW) / 2)
    tan_h = tan_v * aspect
    y, p = math.radians(yaw), math.radians(pitch)
    toward = (math.sin(y) * math.cos(p), math.sin(p), math.cos(y) * math.cos(p))  # camera
    right = (math.cos(y), 0.0, -math.sin(y))
    up = (
        -math.sin(y) * math.sin(p),
        math.cos(p),
        -math.cos(y) * math.sin(p),
    )
    hx, hy, hz = (max(abs(e), 1e-6) for e in half_extents)
    need = 0.0
    for sx in (-1, 1):
        for sy in (-1, 1):
            for sz in (-1, 1):
                corner = (sx * hx, sy * hy, sz * hz)
                along = sum(c * t for c, t in zip(corner, toward, strict=True))  # towards camera
                x = abs(sum(c * r for c, r in zip(corner, right, strict=True)))
                v = abs(sum(c * u for c, u in zip(corner, up, strict=True)))
                need = max(need, along + margin * x / tan_h, along + margin * v / tan_v)
    return need


@dataclass(frozen=True)
class Cell:
    """A model's place on a contact sheet: where its picture and its name go, in px."""

    picture: tuple[int, int, int, int]  # x, y, width, height
    label: tuple[int, int, int, int]


@dataclass(frozen=True)
class SheetLayout:
    width: int
    height: int
    cells: list[Cell]


def sheet_layout(
    count: int, width: int = SHEET_WIDTH, label: int = 56, gap: int = 24
) -> SheetLayout:
    """A grid for `count` models (at most SHEET_MODELS): as square as it gets, three
    columns at most, every picture 4:3 with its name under it."""
    count = max(1, min(count, SHEET_MODELS))
    columns = min(3, math.ceil(math.sqrt(count)))
    rows = math.ceil(count / columns)
    cell_width = (width - gap * (columns + 1)) // columns
    picture_height = cell_width * 3 // 4
    cells = []
    for i in range(count):
        row, column = divmod(i, columns)
        x = gap + column * (cell_width + gap)
        y = gap + row * (picture_height + label + gap)
        cells.append(
            Cell((x, y, cell_width, picture_height), (x, y + picture_height, cell_width, label))
        )
    height = gap + rows * (picture_height + label + gap)
    return SheetLayout(width, height, cells)


def sheet_models(paths: Sequence[str]) -> list[str]:
    """Which models a Pack's sheet shows: the first SHEET_MODELS drawable ones by path."""
    return previewable(paths)[:SHEET_MODELS]
