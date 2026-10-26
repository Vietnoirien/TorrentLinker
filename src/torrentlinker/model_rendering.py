"""CPU Presentation Images shared by desktop, MCP and headless web.

A disposable worker reads geometry and rasterizes only display copies. No GPU,
window, Qt event loop, source writes or public image hosting are involved.
"""

from __future__ import annotations

import io
import math
import multiprocessing
import threading
import time
from dataclasses import asdict, dataclass

import numpy as np

from torrentlinker.mesh import MeshError, limit_triangles, load_mesh

PRESETS = {
    "isometric": (45.0, 55.0, 0.0),
    "front": (0.0, 90.0, 0.0),
    "back": (180.0, 90.0, 0.0),
    "left": (-90.0, 90.0, 0.0),
    "right": (90.0, 90.0, 0.0),
    "top": (0.0, 0.0, 0.0),
    "bottom": (0.0, 180.0, 0.0),
}
_render_lock = threading.Lock()


@dataclass(frozen=True)
class Camera:
    yaw: float = 45.0
    pitch: float = 55.0
    roll: float = 0.0
    zoom: float = 1.0
    center_x: float = 0.0
    center_y: float = 0.0
    distance: float = 0.0  # Positive for a captured perspective camera, zero for auto-framed ortho.
    aspect: float = 1.0

    def __post_init__(self):
        if not all(math.isfinite(v) for v in asdict(self).values()):
            raise ValueError("Camera values must be finite.")
        if not 0.1 <= self.zoom <= 10 or max(abs(self.center_x), abs(self.center_y)) > 0.8:
            raise ValueError("Use zoom 0.1–10 and framing offsets between -0.8 and 0.8.")
        if self.distance < 0 or not 0.01 <= self.aspect <= 100:
            raise ValueError("Camera distance must be nonnegative and aspect between 0.01 and 100.")
        for field in ("yaw", "pitch", "roll"):
            object.__setattr__(self, field, (getattr(self, field) + 180) % 360 - 180)

    def view_basis(self):
        """Right, up and toward-camera vectors in raw Z-up coordinates.

        QML displays [x,z,-y], then orbits its Y-up camera with yaw and elevation.
        This basis applies that same view transform without rotating source geometry.
        """
        yaw, polar, roll = map(math.radians, (self.yaw, self.pitch, self.roll))
        cy, sy, cp, sp = math.cos(yaw), math.sin(yaw), math.cos(polar), math.sin(polar)
        basis = np.array([[cy, sy, 0], [-cp * sy, cp * cy, sp], [sp * sy, -sp * cy, cp]])
        cr, sr = math.cos(roll), math.sin(roll)
        return np.array([[cr, -sr, 0], [sr, cr, 0], [0, 0, 1]]) @ basis

    @classmethod
    def from_viewer(cls, yaw, elevation, distance_zoom, base_distance, aspect):
        """Keep the live QML perspective distance and invert its distance zoom."""
        return cls(
            yaw=yaw,
            pitch=90 - elevation,
            zoom=1 / distance_zoom,
            distance=base_distance * distance_zoom,
            aspect=aspect,
        )

    @classmethod
    def preset(cls, name="isometric", **changes):
        if name not in PRESETS:
            raise ValueError("Unknown camera preset. Use " + ", ".join(PRESETS))
        yaw, pitch, roll = PRESETS[name]
        return cls(**{"yaw": yaw, "pitch": pitch, "roll": roll, **changes})


def inspect_models(paths, stop=None, progress=None):
    """Inventory preserves every file and folder variant; names supply hints only."""
    import re

    paths = list(paths)
    rows = []
    for path in paths:
        text = str(path)
        parts = path.parts
        rows.append(
            {
                "file": text,
                "format": path.suffix.lower().removeprefix("."),
                "group": str(path.parent),
                "size_bytes": path.stat().st_size,
                "scale_hints": re.findall(r"1[ ,/_.-](?:4|9|12)\b", text),
                "supported_hint": any("support" in part.lower() for part in parts),
                "assembled_hint": bool(
                    re.search(r"(?:^|[^a-z])(merge[d]?|assembled|uncut)(?:[^a-z]|$)", text, re.I)
                ),
                "assembled_verified": False,
                "previewable": path.suffix.lower() in {".stl", ".obj", ".3mf"},
            }
        )
    if stop is not None and paths:
        geometry = render_models(
            paths[:108],
            [Camera()] * min(len(paths), 108),
            stop,
            progress or (lambda _: None),
            inspect_only=True,
        )
        by_file = {row["file"]: row for row in geometry["geometry"]}
        for index, row in enumerate(rows):
            row.update(by_file.get(row["file"], {}))
            if index >= 108:
                row.update(
                    geometry_status="deferred",
                    geometry_reason="Geometry inspection limited to 108 files per inventory; "
                    "select this piece for a separate preview.",
                )
    return {
        "models": rows,
        "count": len(rows),
        "notice": "Names indicate variants and assembled candidates, not proof of assembly.",
    }


def _draw(path, camera, size=400):
    from PIL import Image, ImageDraw

    if path.stat().st_size > 256_000_000:
        raise ValueError("Mesh exceeds the 256 MB preview input limit.")
    original = load_mesh(path)
    if not original.triangle_count or not np.isfinite(original.vertices).all():
        raise ValueError("Mesh is empty or contains non-finite coordinates.")
    mesh = limit_triangles(original, 20000)
    low, high = mesh.bounds()
    points = mesh.vertices.astype(np.float64) - (low + high) / 2
    points = points @ camera.view_basis().T
    xy = points[:, :2]
    if camera.distance:
        # Match the live camera's 30 degree vertical FOV and letterbox its aspect.
        depth = camera.distance - points[:, 2]
        viewport_height = size / max(1, camera.aspect)
        projected = (
            xy
            * (viewport_height / (2 * math.tan(math.radians(15))))
            / np.maximum(depth[:, None], 1e-9)
        )
    else:
        extent = max(float(np.ptp(xy[:, 0])), float(np.ptp(xy[:, 1])), 1e-9)
        projected = xy - (xy.min(axis=0) + xy.max(axis=0)) / 2
        projected *= (size * 0.82 / extent) * camera.zoom
    projected[:, 0] += size * (0.5 + camera.center_x / 2)
    projected[:, 1] = size * (0.5 + camera.center_y / 2) - projected[:, 1]
    triangles = mesh.triangles
    corners = points[triangles]
    normals = np.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0])
    norm = np.linalg.norm(normals, axis=1)
    normals /= np.maximum(norm[:, None], 1e-12)
    light = np.array([0.3, -0.4, 0.85])
    brightness = 0.3 + 0.7 * np.abs(normals @ light)
    image = Image.new("RGB", (size, size), "#f2f3f5")
    draw = ImageDraw.Draw(image)
    for index in np.argsort(corners[:, :, 2].mean(axis=1)):
        if camera.distance and np.any(camera.distance - corners[index, :, 2] <= 1e-6):
            continue
        polygon = [tuple(point) for point in projected[triangles[index]]]
        shade = float(brightness[index])
        draw.polygon(polygon, fill=tuple(int(c * shade) for c in (137, 171, 199)))
    return image, {
        "triangles": original.triangle_count,
        "shown": len(triangles),
        "bounds": [low.tolist(), high.tolist()],
        "camera": asdict(camera),
    }


def _worker(connection, paths, cameras, inspect_only):
    try:
        try:
            import resource

            resource.setrlimit(resource.RLIMIT_AS, (4_000_000_000, 4_000_000_000))
            resource.setrlimit(resource.RLIMIT_CPU, (120, 120))
        except ImportError:
            pass
        from PIL import Image, ImageDraw, ImageFont

        if inspect_only:
            geometry = []
            for index, path in enumerate(paths):
                connection.send({"progress": {"done": index, "total": len(paths)}})
                try:
                    if path.stat().st_size > 256_000_000:
                        raise ValueError("Mesh exceeds the 256 MB preview input limit.")
                    if path.suffix.lower() == ".stl" and path.stat().st_size > 16_000_000:
                        with path.open("rb") as stream:
                            header = stream.read(84)
                        count = int.from_bytes(header[80:84], "little") if len(header) == 84 else 0
                        if count and path.stat().st_size == 84 + 50 * count:
                            geometry.append(
                                {
                                    "file": str(path),
                                    "triangles": count,
                                    "bounds": None,
                                    "bounds_status": "Deferred for large binary STL; "
                                    "available in a successful render artifact.",
                                    "units": "not established by geometry",
                                }
                            )
                            continue
                    mesh = load_mesh(path)
                    low, high = mesh.bounds()
                    geometry.append(
                        {
                            "file": str(path),
                            "triangles": mesh.triangle_count,
                            "bounds": [low.tolist(), high.tolist()],
                            "units": "not established by geometry",
                        }
                    )
                except (OSError, ValueError) as error:
                    geometry.append({"file": str(path), "geometry_error": str(error)})
            connection.send({"result": {"geometry": geometry}})
            return
        pages, covered, unsupported = [], [], []
        for start in range(0, len(paths), 9):
            chosen = paths[start : start + 9]
            rows = math.ceil(len(chosen) / 3)
            cell_size = 1200 if len(paths) == 1 else 400
            columns = 1 if len(paths) == 1 else 3
            sheet = Image.new("RGB", (1200, rows * (cell_size + 48)), "white")
            draw = ImageDraw.Draw(sheet)
            font = ImageFont.load_default(size=14)
            metadata = []
            for cell, path in enumerate(chosen):
                index = start + cell
                connection.send(
                    {"progress": {"done": index, "total": len(paths), "file": str(path)}}
                )
                x, y = cell % columns * cell_size, cell // columns * (cell_size + 48)
                try:
                    image, facts = _draw(path, cameras[index], size=cell_size)
                    sheet.paste(image, (x, y))
                    covered.append(str(path))
                    metadata.append({"file": str(path), **facts})
                except (OSError, ValueError, MeshError) as error:
                    unsupported.append({"file": str(path), "reason": str(error)})
                    draw.text((x + 10, y + 180), "Preview unavailable", fill="red", font=font)
                label = path.name
                draw.text((x + 8, y + cell_size + 5), label[:48], fill="black", font=font)
                draw.text(
                    (x + 8, y + cell_size + 25),
                    str(path.parent.name)[:48],
                    fill="#555555",
                    font=font,
                )
            output = io.BytesIO()
            sheet.save(output, format="PNG")
            pages.append({"png": output.getvalue(), "pieces": metadata, "page": len(pages) + 1})
            connection.send({"page": pages[-1], "covered": covered, "unsupported": unsupported})
        connection.send(
            {
                "result": {
                    "covered": covered,
                    "unsupported": unsupported,
                    "selected": len(paths),
                    "renderer": "cpu",
                    "complete": not unsupported,
                }
            }
        )
    except Exception as error:
        connection.send({"error": str(error)})
    finally:
        connection.close()


def render_models(paths, cameras, stop, progress, *, inspect_only=False):
    """Render at most 108 selected pieces in one bounded cancellable worker."""
    if not 1 <= len(paths) <= 108 or len(cameras) != len(paths):
        raise ValueError("Select 1–108 pieces and one camera per piece.")
    while not _render_lock.acquire(timeout=0.1):
        if stop.is_set():
            raise InterruptedError("Rendering cancelled.")
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe(duplex=False)
    worker = context.Process(
        target=_worker, args=(child, list(paths), list(cameras), inspect_only), daemon=True
    )
    started_worker = False
    pages, covered, unsupported = [], [], []

    def interrupted_coverage(reason):
        if inspect_only:
            raise ValueError(reason)
        resolved = set(covered) | {row["file"] for row in unsupported}
        remaining = [
            {"file": str(path), "reason": reason} for path in paths if str(path) not in resolved
        ]
        return {
            "pages": pages,
            "covered": covered,
            "unsupported": [*unsupported, *remaining],
            "selected": len(paths),
            "renderer": "cpu",
            "complete": False,
            "resource_error": reason,
        }

    try:
        worker.start()
        started_worker = True
        child.close()
        started = time.monotonic()
        while True:
            if stop.is_set():
                raise InterruptedError("Rendering cancelled.")
            if time.monotonic() - started > 120:
                return interrupted_coverage("Preview exceeded its 120 second resource limit.")
            if parent.poll(0.1):
                try:
                    message = parent.recv()
                except EOFError:
                    return interrupted_coverage(
                        "Rendering worker stopped before completing "
                        "coverage. CPU or memory limit may be reached."
                    )
                if "progress" in message:
                    progress(message["progress"])
                elif "page" in message:
                    pages.append(message["page"])
                    covered, unsupported = message["covered"], message["unsupported"]
                elif "result" in message:
                    progress({"done": len(paths), "total": len(paths)})
                    return (
                        message["result"] if inspect_only else {**message["result"], "pages": pages}
                    )
                else:
                    raise ValueError("Rendering unavailable: " + message["error"])
            elif not worker.is_alive():
                return interrupted_coverage(
                    "Rendering worker stopped. Check memory and dependencies."
                )
    finally:
        if worker.is_alive():
            worker.terminate()
        if started_worker:
            worker.join(timeout=2)
        parent.close()
        child.close()
        _render_lock.release()
