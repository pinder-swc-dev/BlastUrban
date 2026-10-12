#!/usr/bin/env python3
"""Core utilities for building a three-dimensional blastFoam urban case.

The module intentionally uses only the Python standard library.  The desktop
UI imports it, but it is also useful from tests or a future web front end.
"""

from __future__ import annotations

import json
import math
import os
import platform
import re
import shutil
import statistics
import struct
import subprocess
import tarfile
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Tuple


Vec3 = Tuple[float, float, float]
Triangle = Tuple[Vec3, Vec3, Vec3]


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TEMPLATE = REPO_ROOT / "tutorials/blastFoam/building3DWorkshop"
UI_ASSETS = Path(__file__).with_name("assets")


def foam_number(value: float) -> str:
    """Return a stable number representation accepted by OpenFOAM."""
    if not math.isfinite(value):
        raise ValueError("OpenFOAM values must be finite")
    if value == 0:
        return "0"
    absolute = abs(value)
    if absolute < 1e-4 or absolute >= 1e7:
        return f"{value:.9g}"
    return f"{value:.9f}".rstrip("0").rstrip(".")


def foam_vec(value: Vec3) -> str:
    return "(" + " ".join(foam_number(v) for v in value) + ")"


def safe_case_name(value: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    name = name.strip("._-")
    if not name:
        raise ValueError("Case name is empty")
    if name in {".", ".."}:
        raise ValueError("Invalid case name")
    return name


@dataclass(frozen=True)
class Bounds:
    minimum: Vec3
    maximum: Vec3

    @property
    def span(self) -> Vec3:
        return tuple(self.maximum[i] - self.minimum[i] for i in range(3))  # type: ignore[return-value]

    @property
    def centre(self) -> Vec3:
        return tuple((self.maximum[i] + self.minimum[i]) / 2 for i in range(3))  # type: ignore[return-value]

    @property
    def diagonal(self) -> float:
        return math.sqrt(sum(v * v for v in self.span))

    def contains(self, point: Vec3, margin: float = 0.0) -> bool:
        return all(
            self.minimum[i] + margin <= point[i] <= self.maximum[i] - margin
            for i in range(3)
        )


@dataclass
class StlReport:
    path: str
    encoding: str
    scale: float
    triangles: int
    bounds: Bounds
    surface_area: float
    signed_volume: float
    unique_vertices: int
    open_edges: Optional[int]
    non_manifold_edges: Optional[int]
    degenerate_triangles: int
    min_edge: float
    median_edge: float
    max_edge: float
    topology_complete: bool
    external_output: str = ""
    external_returncode: Optional[int] = None

    @property
    def errors(self) -> List[str]:
        result: List[str] = []
        if self.triangles <= 0:
            result.append("ไม่พบ triangle ในไฟล์ STL")
        if self.degenerate_triangles:
            result.append(f"พบ triangle ที่มีพื้นที่เป็นศูนย์ {self.degenerate_triangles:,} รายการ")
        if self.open_edges:
            result.append(f"พบขอบเปิด (open edges) {self.open_edges:,} ขอบ")
        if self.non_manifold_edges:
            result.append(f"พบขอบ non-manifold {self.non_manifold_edges:,} ขอบ")
        if self.external_returncode not in (None, 0):
            result.append(f"surfaceCheck จบด้วยรหัส {self.external_returncode}")
        return result

    @property
    def warnings(self) -> List[str]:
        result: List[str] = []
        if not self.topology_complete:
            result.append("โมเดลใหญ่เกินขีดจำกัด internal topology check; ให้ยืนยันด้วย surfaceCheck บน server")
        if self.signed_volume < 0:
            result.append("signed volume เป็นลบ: normal ของผิวส่วนใหญ่อาจหันเข้าด้านใน")
        if self.bounds.diagonal <= 0:
            result.append("โมเดลไม่มีขนาดเชิงปริมาตร")
        return result

    def readable_summary(self) -> str:
        b = self.bounds
        s = b.span
        status = "ERROR" if self.errors else ("WARNING" if self.warnings else "OK")
        lines = [
            f"สถานะ: {status}",
            f"ไฟล์: {self.path}",
            f"รูปแบบ: {self.encoding}; scale = {foam_number(self.scale)}",
            f"Triangles: {self.triangles:,}; vertices ไม่ซ้ำ: "
            + (f"{self.unique_vertices:,}" if self.unique_vertices >= 0 else "ไม่ได้เก็บสำหรับโมเดลขนาดใหญ่"),
            f"Bounds min: {foam_vec(b.minimum)} m",
            f"Bounds max: {foam_vec(b.maximum)} m",
            f"ขนาด X × Y × Z: {foam_number(s[0])} × {foam_number(s[1])} × {foam_number(s[2])} m",
            f"พื้นที่ผิว: {foam_number(self.surface_area)} m²",
            f"ปริมาตร signed: {foam_number(self.signed_volume)} m³",
            f"ขนาด edge min / median / max: {foam_number(self.min_edge)} / "
            f"{foam_number(self.median_edge)} / {foam_number(self.max_edge)} m",
        ]
        if self.topology_complete:
            lines.append(
                f"Open edges: {self.open_edges or 0:,}; non-manifold edges: "
                f"{self.non_manifold_edges or 0:,}; degenerate: {self.degenerate_triangles:,}"
            )
        else:
            lines.append("Topology: ตรวจเพียงบางส่วน เนื่องจากโมเดลมีขนาดใหญ่มาก")
        for item in self.errors:
            lines.append("ERROR: " + item)
        for item in self.warnings:
            lines.append("WARNING: " + item)
        if self.external_output:
            lines.extend(["", "--- OpenFOAM surfaceCheck ---", self.external_output.rstrip()])
        return "\n".join(lines)


@dataclass
class RepairResult:
    source: str
    output: str
    weld_tolerance_m: float
    max_hole_size_m: float
    welded_vertices: int
    removed_degenerate: int
    removed_duplicate_faces: int
    boundary_loops_found: int
    holes_filled: int
    holes_skipped_too_large: int
    holes_skipped_not_planar: int
    holes_skipped_complex: int
    triangles_added: int
    report_before: StlReport
    report_after: StlReport

    def readable_summary(self) -> str:
        lines = [
            "ผลการซ่อมโมเดล",
            f"ไฟล์ที่กำลังใช้งานหลังซ่อม: {self.output}",
            f"เชื่อมจุดที่อยู่ใกล้กัน: {self.welded_vertices:,} จุด",
            f"ลบหน้าที่เสีย/ซ้ำ: {self.removed_degenerate:,} / {self.removed_duplicate_faces:,}",
            f"พบขอบรูแบบวงปิด: {self.boundary_loops_found:,} วง",
            f"ปิดรูสำเร็จ: {self.holes_filled:,} รู (เพิ่ม {self.triangles_added:,} triangles)",
        ]
        skipped = self.holes_skipped_too_large + self.holes_skipped_not_planar + self.holes_skipped_complex
        if skipped:
            lines.append(
                f"ยังไม่ปิด {skipped:,} รู: ใหญ่เกินกำหนด {self.holes_skipped_too_large:,}, "
                f"ผิวไม่เรียบ {self.holes_skipped_not_planar:,}, รูปทรงซับซ้อน {self.holes_skipped_complex:,}"
            )
        before = self.report_before.open_edges if self.report_before.open_edges is not None else -1
        after = self.report_after.open_edges if self.report_after.open_edges is not None else -1
        lines.append(f"ขอบเปิดก่อน/หลัง: {before:,} → {after:,}")
        if self.report_after.errors:
            lines.append("ยังต้องแก้เพิ่มเติม: " + "; ".join(self.report_after.errors))
        else:
            lines.append("โมเดลปิดเรียบร้อย พร้อมสร้างพื้นที่คำนวณ")
        return "\n".join(lines)


def _binary_stl_info(path: Path) -> Tuple[bool, int]:
    size = path.stat().st_size
    if size < 84:
        return False, 0
    with path.open("rb") as handle:
        header = handle.read(84)
    triangle_count = struct.unpack("<I", header[80:84])[0]
    expected_size = 84 + triangle_count * 50
    # A few CAD exporters append a small metadata/footer block after the
    # standard binary STL records.  Requiring exact size misclassifies those
    # files as ASCII and makes a valid model appear empty.  ASCII STL text at
    # bytes 80..83 almost always decodes to a count far larger than the file.
    binary_layout = expected_size <= size and (
        triangle_count > 0
        or b"\x00" in header
        or not header.lstrip().lower().startswith(b"solid")
    )
    return binary_layout, triangle_count


def iter_stl_triangles(path: Path) -> Iterator[Triangle]:
    """Yield triangles from an ASCII or binary STL without third-party modules."""
    is_binary, triangle_count = _binary_stl_info(path)
    if is_binary:
        record = struct.Struct("<12fH")
        with path.open("rb") as handle:
            handle.seek(84)
            for _ in range(triangle_count):
                data = handle.read(record.size)
                if len(data) != record.size:
                    raise ValueError("ไฟล์ Binary STL ขาดหายก่อนอ่าน triangles ครบ")
                values = record.unpack(data)
                triangle = (
                    (values[3], values[4], values[5]),
                    (values[6], values[7], values[8]),
                    (values[9], values[10], values[11]),
                )
                if not all(math.isfinite(value) for point in triangle for value in point):
                    raise ValueError("Binary STL มีพิกัด NaN หรือ Infinity")
                yield triangle
        return

    vertices: List[Vec3] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line_number, line in enumerate(handle, 1):
            fields = line.strip().split()
            if fields and fields[0].lower() == "vertex":
                if len(fields) != 4:
                    raise ValueError(f"รูปแบบ vertex ใน ASCII STL ไม่ถูกต้องที่บรรทัด {line_number}")
                try:
                    point = (float(fields[1]), float(fields[2]), float(fields[3]))
                except ValueError as exc:
                    raise ValueError(f"พิกัดใน ASCII STL ไม่ใช่ตัวเลขที่บรรทัด {line_number}") from exc
                if not all(math.isfinite(value) for value in point):
                    raise ValueError(f"ASCII STL มีพิกัด NaN หรือ Infinity ที่บรรทัด {line_number}")
                vertices.append(point)
                if len(vertices) == 3:
                    yield (vertices[0], vertices[1], vertices[2])
                    vertices.clear()
    if vertices:
        raise ValueError("ไฟล์ ASCII STL ไม่สมบูรณ์: triangle สุดท้ายมี vertex ไม่ครบ 3 จุด")


def _sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: Vec3, b: Vec3) -> Vec3:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _norm(a: Vec3) -> float:
    return math.sqrt(_dot(a, a))


def _scaled(point: Vec3, scale: float) -> Vec3:
    return (point[0] * scale, point[1] * scale, point[2] * scale)


def analyse_stl(
    path: Path,
    scale: float = 1.0,
    run_external: bool = True,
    topology_triangle_limit: int = 1_500_000,
    external_timeout: int = 180,
) -> StlReport:
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    if scale <= 0 or not math.isfinite(scale):
        raise ValueError("Scale must be a positive finite number")

    is_binary, binary_count = _binary_stl_info(path)
    topology_complete = not is_binary or binary_count <= topology_triangle_limit
    minima = [math.inf, math.inf, math.inf]
    maxima = [-math.inf, -math.inf, -math.inf]
    area = 0.0
    volume = 0.0
    triangle_count = 0
    degenerate = 0
    # Exact vertex/edge sets consume substantial RAM.  The configured limit
    # keeps a multi-million-triangle model from exhausting a desktop merely
    # while preparing a server job.
    vertices = set() if topology_complete else None
    edges: Optional[Dict[Tuple[Vec3, Vec3], int]] = {} if topology_complete else None
    edge_sample: List[float] = []
    edge_min = math.inf
    edge_max = 0.0
    edge_total = 0

    for triangle in iter_stl_triangles(path):
        tri = tuple(_scaled(point, scale) for point in triangle)  # type: ignore[assignment]
        triangle_count += 1
        if topology_complete and triangle_count > topology_triangle_limit:
            # Binary STL count is known from its header; ASCII count is not.
            # Drop the large topology sets as soon as an ASCII file crosses
            # the same safety limit.
            topology_complete = False
            vertices = None
            edges = None
        for point in tri:
            if vertices is not None:
                vertices.add(point)
            for axis in range(3):
                minima[axis] = min(minima[axis], point[axis])
                maxima[axis] = max(maxima[axis], point[axis])
        cross = _cross(_sub(tri[1], tri[0]), _sub(tri[2], tri[0]))
        twice_area = _norm(cross)
        area += twice_area / 2
        volume += _dot(tri[0], _cross(tri[1], tri[2])) / 6
        if twice_area <= 1e-24:
            degenerate += 1
        for start, end in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
            length = _norm(_sub(end, start))
            edge_min = min(edge_min, length)
            edge_max = max(edge_max, length)
            edge_total += 1
            if len(edge_sample) < 500_000:
                edge_sample.append(length)
            if edges is not None:
                key = (start, end) if start <= end else (end, start)
                edges[key] = edges.get(key, 0) + 1

    if triangle_count == 0:
        bounds = Bounds((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
        edge_min = 0.0
    else:
        bounds = Bounds(tuple(minima), tuple(maxima))  # type: ignore[arg-type]
    median_edge = statistics.median(edge_sample) if edge_sample else 0.0
    open_edges = sum(1 for count in edges.values() if count == 1) if edges is not None else None
    non_manifold = sum(1 for count in edges.values() if count > 2) if edges is not None else None

    external_output = ""
    external_returncode: Optional[int] = None
    surface_check = shutil.which("surfaceCheck") if run_external else None
    if surface_check:
        try:
            process = subprocess.run(
                [surface_check, str(path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=external_timeout,
                check=False,
            )
            external_output = process.stdout
            external_returncode = process.returncode
        except (OSError, subprocess.TimeoutExpired) as exc:
            external_output = f"ไม่สามารถเรียก surfaceCheck: {exc}"
            external_returncode = -1
    elif run_external and platform.system() == "Darwin":
        # OpenFOAM Foundation is normally run in Linux/Docker on macOS.  Use an
        # already-installed image when available; never pull an image behind
        # the user's back.  BLASTFOAM_DOCKER_IMAGE can override the candidates.
        docker = shutil.which("docker")
        configured_image = os.environ.get("BLASTFOAM_DOCKER_IMAGE", "").strip()
        candidates = [
            item
            for item in (
                configured_image,
                "local/blastfoam9:6.2.0-of9-complete",
                "local/blastfoam9:6.2.0-of9",
                "openfoam/openfoam9-graphical-apps:latest",
            )
            if item
        ]
        image = ""
        image_architecture = ""
        if docker:
            for candidate in candidates:
                try:
                    check = subprocess.run(
                        [docker, "image", "inspect", "--format", "{{.Architecture}}", candidate],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL,
                        text=True,
                        timeout=10,
                        check=False,
                    )
                except (OSError, subprocess.TimeoutExpired):
                    break
                if check.returncode == 0:
                    image = candidate
                    image_architecture = check.stdout.strip().lower()
                    break
        if docker and image:
            command = [docker, "run", "--rm"]
            if (
                platform.machine().lower() in {"arm64", "aarch64"}
                and image_architecture in {"amd64", "x86_64"}
            ):
                command.extend(["--platform", "linux/amd64"])
            command.extend(
                [
                    "--entrypoint", "/bin/bash",
                    "-v", f"{path.parent}:/stl:ro",
                    image,
                    "-lc",
                    'source /opt/openfoam9/etc/bashrc && surfaceCheck "$1"',
                    "surface-check",
                    f"/stl/{path.name}",
                ]
            )
            try:
                process = subprocess.run(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=external_timeout,
                    check=False,
                )
                external_output = f"Docker image: {image}\n" + process.stdout
                external_returncode = process.returncode
            except (OSError, subprocess.TimeoutExpired) as exc:
                external_output = f"ไม่สามารถเรียก Docker surfaceCheck: {exc}"
                external_returncode = -1

    return StlReport(
        path=str(path),
        encoding="binary" if is_binary else "ASCII",
        scale=scale,
        triangles=triangle_count,
        bounds=bounds,
        surface_area=area,
        signed_volume=volume,
        unique_vertices=len(vertices) if vertices is not None else -1,
        open_edges=open_edges,
        non_manifold_edges=non_manifold,
        degenerate_triangles=degenerate,
        min_edge=edge_min,
        median_edge=median_edge,
        max_edge=edge_max,
        topology_complete=topology_complete,
        external_output=external_output,
        external_returncode=external_returncode,
    )


def _write_binary_stl(path: Path, vertices: Sequence[Vec3], faces: Sequence[Tuple[int, int, int]]) -> None:
    if len(faces) > 0xFFFFFFFF:
        raise ValueError("STL มีจำนวน triangles มากเกินรูปแบบ binary STL")
    header_text = b"BlastUrban repaired STL - original file preserved"
    header = header_text + b"\0" * (80 - len(header_text))
    record = struct.Struct("<12fH")
    with path.open("wb") as handle:
        handle.write(header)
        handle.write(struct.pack("<I", len(faces)))
        for ia, ib, ic in faces:
            a, b, c = vertices[ia], vertices[ib], vertices[ic]
            normal = _cross(_sub(b, a), _sub(c, a))
            length = _norm(normal)
            if length > 0:
                normal = (normal[0] / length, normal[1] / length, normal[2] / length)
            handle.write(record.pack(*(normal + a + b + c + (0,))))


def _project_loop(vertices: Sequence[Vec3], loop: Sequence[int], normal: Vec3) -> Dict[int, Tuple[float, float]]:
    axis = max(range(3), key=lambda i: abs(normal[i]))
    if axis == 0:
        return {index: (vertices[index][1], vertices[index][2]) for index in loop}
    if axis == 1:
        return {index: (vertices[index][0], vertices[index][2]) for index in loop}
    return {index: (vertices[index][0], vertices[index][1]) for index in loop}


def _cross_2d(a: Tuple[float, float], b: Tuple[float, float], c: Tuple[float, float]) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _strictly_inside_triangle_2d(
    point: Tuple[float, float],
    a: Tuple[float, float],
    b: Tuple[float, float],
    c: Tuple[float, float],
    orientation: float,
    epsilon: float,
) -> bool:
    return all(
        value * orientation > epsilon
        for value in (
            _cross_2d(a, b, point),
            _cross_2d(b, c, point),
            _cross_2d(c, a, point),
        )
    )


def _triangulate_loop(vertices: Sequence[Vec3], loop: Sequence[int], normal: Vec3) -> Optional[List[Tuple[int, int, int]]]:
    """Triangulate a simple planar polygon with ear clipping."""
    if len(loop) < 3:
        return None
    projected = _project_loop(vertices, loop, normal)
    polygon = list(loop)
    signed_area = sum(
        projected[polygon[i]][0] * projected[polygon[(i + 1) % len(polygon)]][1]
        - projected[polygon[(i + 1) % len(polygon)]][0] * projected[polygon[i]][1]
        for i in range(len(polygon))
    )
    if abs(signed_area) <= 1e-24:
        return None
    orientation = 1.0 if signed_area > 0 else -1.0
    span = max(
        max(point[0] for point in projected.values()) - min(point[0] for point in projected.values()),
        max(point[1] for point in projected.values()) - min(point[1] for point in projected.values()),
        1.0,
    )
    epsilon = span * span * 1e-14
    triangles: List[Tuple[int, int, int]] = []
    guard = 0
    while len(polygon) > 3 and guard < len(loop) * len(loop):
        guard += 1
        clipped = False
        for i, current in enumerate(polygon):
            previous = polygon[i - 1]
            following = polygon[(i + 1) % len(polygon)]
            a, b, c = projected[previous], projected[current], projected[following]
            if _cross_2d(a, b, c) * orientation <= epsilon:
                continue
            if any(
                _strictly_inside_triangle_2d(projected[other], a, b, c, orientation, epsilon)
                for other in polygon
                if other not in {previous, current, following}
            ):
                continue
            triangles.append((previous, current, following))
            polygon.pop(i)
            clipped = True
            break
        if not clipped:
            return None
    if len(polygon) == 3:
        triangles.append((polygon[0], polygon[1], polygon[2]))
    return triangles


def repair_stl(
    source: Path,
    output: Path,
    scale: float,
    weld_tolerance_m: float = 0.001,
    max_hole_size_m: float = 2.0,
    triangle_limit: int = 2_000_000,
) -> RepairResult:
    """Repair small, simple STL defects without altering the source file.

    The conservative repair welds near-coincident points, removes degenerate
    and duplicate faces, and caps simple approximately planar boundary loops.
    It deliberately does not guess how to repair non-manifold intersections or
    large/non-planar missing surfaces.
    """
    source = Path(source).expanduser().resolve()
    output = Path(output).expanduser().resolve()
    if source == output:
        raise ValueError("ไฟล์ซ่อมต้องเป็นไฟล์ใหม่ ระบบจะไม่เขียนทับต้นฉบับ")
    if scale <= 0 or weld_tolerance_m < 0 or max_hole_size_m <= 0:
        raise ValueError("Scale และขนาดรูต้องมากกว่า 0; ระยะเชื่อมจุดต้องไม่ติดลบ")
    before = analyse_stl(source, scale, run_external=False, topology_triangle_limit=triangle_limit)
    if before.triangles > triangle_limit:
        raise ValueError(
            f"โมเดลมี {before.triangles:,} triangles เกินขีดจำกัดซ่อมอัตโนมัติ {triangle_limit:,}; "
            "ให้ลดความละเอียด STL หรือใช้เครื่องมือซ่อมเฉพาะทาง"
        )
    diagonal_m = max(before.bounds.diagonal, 1e-12)
    if weld_tolerance_m > diagonal_m * 0.01:
        raise ValueError("ระยะเชื่อมจุดมากกว่า 1% ของขนาดโมเดล เสี่ยงทำให้รูปทรงเสีย")
    tolerance_raw = weld_tolerance_m / scale
    max_hole_raw = max_hole_size_m / scale

    raw_triangles = list(iter_stl_triangles(source))
    exact_vertices = {point for triangle in raw_triangles for point in triangle}
    vertices: List[Vec3] = []
    buckets: Dict[Tuple[int, int, int], List[int]] = defaultdict(list)
    exact_map: Dict[Vec3, int] = {}

    def vertex_id(point: Vec3) -> int:
        if tolerance_raw <= 0:
            existing = exact_map.get(point)
            if existing is not None:
                return existing
            index = len(vertices)
            vertices.append(point)
            exact_map[point] = index
            return index
        cell = tuple(math.floor(value / tolerance_raw) for value in point)
        best: Optional[int] = None
        best_distance = tolerance_raw * tolerance_raw
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    for candidate in buckets.get((cell[0] + dx, cell[1] + dy, cell[2] + dz), ()):
                        distance = sum((point[i] - vertices[candidate][i]) ** 2 for i in range(3))
                        if distance <= best_distance:
                            best, best_distance = candidate, distance
        if best is not None:
            return best
        index = len(vertices)
        vertices.append(point)
        buckets[cell].append(index)
        return index

    faces: List[Tuple[int, int, int]] = []
    face_keys = set()
    removed_degenerate = 0
    removed_duplicate = 0
    for triangle in raw_triangles:
        face = tuple(vertex_id(point) for point in triangle)
        if len(set(face)) < 3:
            removed_degenerate += 1
            continue
        a, b, c = (vertices[index] for index in face)
        if _norm(_cross(_sub(b, a), _sub(c, a))) <= 1e-24:
            removed_degenerate += 1
            continue
        key = tuple(sorted(face))
        if key in face_keys:
            removed_duplicate += 1
            continue
        face_keys.add(key)
        faces.append(face)  # type: ignore[arg-type]

    edge_faces: Dict[Tuple[int, int], List[Tuple[int, int, int]]] = defaultdict(list)
    for face_index, face in enumerate(faces):
        for start, end in ((face[0], face[1]), (face[1], face[2]), (face[2], face[0])):
            edge_faces[tuple(sorted((start, end)))].append((face_index, start, end))
    open_edges = {edge: records[0] for edge, records in edge_faces.items() if len(records) == 1}
    adjacency: Dict[int, List[int]] = defaultdict(list)
    for start, end in open_edges:
        adjacency[start].append(end)
        adjacency[end].append(start)

    remaining = set(open_edges)
    loops: List[List[int]] = []
    complex_components = 0
    while remaining:
        seed = next(iter(remaining))
        stack = [seed[0], seed[1]]
        component_vertices = set()
        while stack:
            current = stack.pop()
            if current in component_vertices:
                continue
            component_vertices.add(current)
            stack.extend(adjacency[current])
        component_edges = {edge for edge in remaining if edge[0] in component_vertices}
        remaining -= component_edges
        if (
            len(component_edges) != len(component_vertices)
            or any(len(adjacency[vertex]) != 2 for vertex in component_vertices)
        ):
            complex_components += 1
            continue
        first = next(iter(component_vertices))
        loop = [first]
        previous = -1
        current = first
        for _ in range(len(component_vertices) + 1):
            candidates = [vertex for vertex in adjacency[current] if vertex != previous]
            if not candidates:
                break
            following = candidates[0]
            if following == first:
                break
            loop.append(following)
            previous, current = current, following
        if len(loop) == len(component_vertices) and first in adjacency[current]:
            loops.append(loop)
        else:
            complex_components += 1

    added_faces: List[Tuple[int, int, int]] = []
    filled = 0
    too_large = 0
    not_planar = 0
    triangulation_failed = complex_components
    for loop in loops:
        points = [vertices[index] for index in loop]
        spans = [max(point[i] for point in points) - min(point[i] for point in points) for i in range(3)]
        diameter = math.sqrt(sum(value * value for value in spans))
        if diameter > max_hole_raw:
            too_large += 1
            continue
        centroid = tuple(sum(point[i] for point in points) / len(points) for i in range(3))
        normal = (0.0, 0.0, 0.0)
        for i, point in enumerate(points):
            following = points[(i + 1) % len(points)]
            normal = (
                normal[0] + (point[1] - following[1]) * (point[2] + following[2]),
                normal[1] + (point[2] - following[2]) * (point[0] + following[0]),
                normal[2] + (point[0] - following[0]) * (point[1] + following[1]),
            )
        normal_length = _norm(normal)
        if normal_length <= 1e-20:
            not_planar += 1
            continue
        unit_normal = tuple(value / normal_length for value in normal)
        max_distance = max(abs(_dot(_sub(point, centroid), unit_normal)) for point in points)
        planar_limit = max(tolerance_raw * 5, diameter * 0.02, 1e-10)
        if max_distance > planar_limit:
            not_planar += 1
            continue

        same_direction = 0
        opposite_direction = 0
        for i, start in enumerate(loop):
            end = loop[(i + 1) % len(loop)]
            _, existing_start, existing_end = open_edges[tuple(sorted((start, end)))]
            if (existing_start, existing_end) == (start, end):
                same_direction += 1
            else:
                opposite_direction += 1
        cap_loop = list(reversed(loop)) if same_direction >= opposite_direction else list(loop)
        cap_normal = tuple(-value for value in unit_normal) if same_direction >= opposite_direction else unit_normal
        triangles = _triangulate_loop(vertices, cap_loop, cap_normal)
        if not triangles:
            triangulation_failed += 1
            continue
        added_faces.extend(triangles)
        filled += 1

    output.parent.mkdir(parents=True, exist_ok=True)
    _write_binary_stl(output, vertices, faces + added_faces)
    after = analyse_stl(output, scale, run_external=False, topology_triangle_limit=triangle_limit)
    return RepairResult(
        source=str(source),
        output=str(output),
        weld_tolerance_m=weld_tolerance_m,
        max_hole_size_m=max_hole_size_m,
        welded_vertices=max(0, len(exact_vertices) - len(vertices)),
        removed_degenerate=removed_degenerate,
        removed_duplicate_faces=removed_duplicate,
        boundary_loops_found=len(loops) + complex_components,
        holes_filled=filled,
        holes_skipped_too_large=too_large,
        holes_skipped_not_planar=not_planar,
        holes_skipped_complex=triangulation_failed,
        triangles_added=len(added_faces),
        report_before=before,
        report_after=after,
    )


def charge_radius(mass: float, density: float) -> float:
    if mass <= 0 or density <= 0:
        raise ValueError("Charge mass and density must be positive")
    return (3.0 * mass / density / (4.0 * math.pi)) ** (1.0 / 3.0)


def auto_domain(
    model: Bounds,
    horizontal_buffer: Optional[float] = None,
    top_buffer: Optional[float] = None,
) -> Bounds:
    span = model.span
    largest_horizontal = max(span[0], span[1], 1.0)
    h_buffer = horizontal_buffer if horizontal_buffer is not None else max(15.0, 0.25 * largest_horizontal)
    z_buffer = top_buffer if top_buffer is not None else max(15.0, 0.35 * max(span[2], 1.0))
    if h_buffer <= 0 or z_buffer <= 0:
        raise ValueError("Domain buffers must be positive")
    return Bounds(
        (model.minimum[0] - h_buffer, model.minimum[1] - h_buffer, model.minimum[2]),
        (model.maximum[0] + h_buffer, model.maximum[1] + h_buffer, model.maximum[2] + z_buffer),
    )


def mesh_divisions(domain: Bounds, target_cell: float) -> Tuple[int, int, int]:
    if target_cell <= 0:
        raise ValueError("Target base-cell size must be positive")
    return tuple(max(1, math.ceil(length / target_cell)) for length in domain.span)  # type: ignore[return-value]


def auto_surface_levels(base_cell: float, model: Bounds) -> Tuple[int, int]:
    target = max(0.10, min(0.50, max(model.span) / 250.0))
    maximum = max(1, min(8, math.ceil(math.log(max(base_cell / target, 1.0), 2))))
    return max(1, maximum - 1), maximum


def auto_charge_level(base_cell: float, mass: float, density: float, cells_across: int = 5) -> int:
    radius = charge_radius(mass, density)
    target = 2 * radius / max(cells_across, 2)
    return max(1, min(10, math.ceil(math.log(max(base_cell / target, 1.0), 2))))


@dataclass(frozen=True)
class ChargeSource:
    """One discrete C4 charge and its detonation time."""

    centre: Vec3
    mass: float
    delay: float = 0.0

    def radius(self, density: float) -> float:
        return charge_radius(self.mass, density)


@dataclass
class CaseConfig:
    case_name: str = "urbanBlast3D"
    stl_path: str = ""
    stl_scale: float = 1.0
    domain_min: Vec3 = (-20.0, -20.0, 0.0)
    domain_max: Vec3 = (90.0, 95.0, 55.0)
    divisions: Tuple[int, int, int] = (74, 77, 37)
    surface_min_level: int = 2
    surface_max_level: int = 3
    feature_level: int = 2
    snappy_max_cells: int = 3_000_000
    dynamic_max_cells: int = 3_000_000
    dynamic_max_refinement: int = 2
    refine_interval: int = 5
    location_in_mesh: Vec3 = (-10.0, -10.0, 1.0)
    charge_centre: Vec3 = (35.0, 20.0, 1.0)
    charge_mass: float = 10.0
    # Empty keeps the historical single-source fields authoritative.  New
    # clients populate this list and the first entry is mirrored into the
    # legacy fields at the adapter boundary.
    sources: List[ChargeSource] = field(default_factory=list)
    explosive_density: float = 1601.0
    charge_refinement_level: int = 6
    probes: List[Vec3] = field(default_factory=lambda: [(35.0, 15.0, 1.0), (40.0, 20.0, 1.0)])
    plane_point: Vec3 = (35.0, 20.0, 1.0)
    end_time: float = 0.0125
    initial_delta_t: float = 5e-8
    # The previous 2.5e-7 cap held a measured full case at maxCo ~= 0.022,
    # far below maxCo=0.3, and forced about 50k solver steps.  Keep the small
    # initial step but let CFL control the mature solution with an 8x cap.
    max_delta_t: float = 2e-6
    max_co: float = 0.3
    # Output cadence only; blastFoam time stepping remains controlled by
    # deltaT/maxDeltaT/maxCo.  The default produces 50 snapshots in 12.5 ms,
    # close to the 48 frames retained by the Web viewer.
    write_interval: float = 2.5e-4
    ambient_pressure: float = 101298.0
    pressure_iso_value: float = 110000.0
    mpi_ranks: int = 10
    output_binary: bool = True
    allow_surface_errors: bool = False
    performance_profile: str = "fast"

    @property
    def domain(self) -> Bounds:
        return Bounds(self.domain_min, self.domain_max)

    @property
    def base_cells(self) -> int:
        return self.divisions[0] * self.divisions[1] * self.divisions[2]

    @property
    def actual_cell_size(self) -> Vec3:
        return tuple(self.domain.span[i] / self.divisions[i] for i in range(3))  # type: ignore[return-value]

    @property
    def theoretical_charge_radius(self) -> float:
        return self.effective_sources[0].radius(self.explosive_density)

    @property
    def effective_sources(self) -> List[ChargeSource]:
        if self.sources:
            return list(self.sources)
        return [ChargeSource(self.charge_centre, self.charge_mass, 0.0)]

    @property
    def total_charge_mass(self) -> float:
        return sum(source.mass for source in self.effective_sources)

    def estimate(self) -> Dict[str, float]:
        frames = math.floor(self.end_time / self.write_interval + 1e-12)
        effective_cap = max(self.snappy_max_cells, self.dynamic_max_cells)
        ram_gib_at_cap = effective_cap * 5000 / (1024 ** 3)
        disk_gib_at_cap = effective_cap * 90 * frames / (1024 ** 3)
        return {
            "base_cells": float(self.base_cells),
            "frames": float(frames),
            "ram_gib_at_dynamic_cap": ram_gib_at_cap,
            "disk_gib_at_dynamic_cap": disk_gib_at_cap,
        }


def _point_triangle_distance(point: Vec3, triangle: Triangle) -> float:
    # Closest-point algorithm from Real-Time Collision Detection (Ericson).
    a, b, c = triangle
    ab, ac, ap = _sub(b, a), _sub(c, a), _sub(point, a)
    d1, d2 = _dot(ab, ap), _dot(ac, ap)
    if d1 <= 0 and d2 <= 0:
        return _norm(ap)
    bp = _sub(point, b)
    d3, d4 = _dot(ab, bp), _dot(ac, bp)
    if d3 >= 0 and d4 <= d3:
        return _norm(bp)
    vc = d1 * d4 - d3 * d2
    if vc <= 0 and d1 >= 0 and d3 <= 0:
        v = d1 / (d1 - d3)
        return _norm(_sub(point, (a[0] + v * ab[0], a[1] + v * ab[1], a[2] + v * ab[2])))
    cp = _sub(point, c)
    d5, d6 = _dot(ab, cp), _dot(ac, cp)
    if d6 >= 0 and d5 <= d6:
        return _norm(cp)
    vb = d5 * d2 - d1 * d6
    if vb <= 0 and d2 >= 0 and d6 <= 0:
        w = d2 / (d2 - d6)
        return _norm(_sub(point, (a[0] + w * ac[0], a[1] + w * ac[1], a[2] + w * ac[2])))
    va = d3 * d6 - d5 * d4
    if va <= 0 and (d4 - d3) >= 0 and (d5 - d6) >= 0:
        w = (d4 - d3) / ((d4 - d3) + (d5 - d6))
        edge = _sub(c, b)
        return _norm(_sub(point, (b[0] + w * edge[0], b[1] + w * edge[1], b[2] + w * edge[2])))
    denom = 1.0 / (va + vb + vc)
    v, w = vb * denom, vc * denom
    closest = (
        a[0] + ab[0] * v + ac[0] * w,
        a[1] + ab[1] * v + ac[1] * w,
        a[2] + ab[2] * v + ac[2] * w,
    )
    return _norm(_sub(point, closest))


def _ray_intersects(point: Vec3, direction: Vec3, triangle: Triangle) -> bool:
    epsilon = 1e-10
    a, b, c = triangle
    edge1, edge2 = _sub(b, a), _sub(c, a)
    h = _cross(direction, edge2)
    det = _dot(edge1, h)
    if -epsilon < det < epsilon:
        return False
    inverse = 1.0 / det
    s = _sub(point, a)
    u = inverse * _dot(s, h)
    if u < 0.0 or u > 1.0:
        return False
    q = _cross(s, edge1)
    v = inverse * _dot(direction, q)
    if v < 0.0 or u + v > 1.0:
        return False
    return inverse * _dot(edge2, q) > epsilon


def point_surface_relation(path: Path, scale: float, point: Vec3) -> Tuple[bool, float]:
    """Return (inside_closed_surface, minimum_distance_to_surface)."""
    direction = (1.0, 0.371390676, 0.529128784)
    intersections = 0
    minimum = math.inf
    for raw in iter_stl_triangles(Path(path)):
        triangle = tuple(_scaled(vertex, scale) for vertex in raw)  # type: ignore[assignment]
        minimum = min(minimum, _point_triangle_distance(point, triangle))
        if _ray_intersects(point, direction, triangle):
            intersections += 1
    return bool(intersections % 2), minimum


def validate_config(config: CaseConfig, report: Optional[StlReport] = None, inspect_points: bool = False) -> Tuple[List[str], List[str]]:
    errors: List[str] = []
    warnings: List[str] = []
    try:
        safe_case_name(config.case_name)
    except ValueError as exc:
        errors.append(str(exc))
    stl = Path(config.stl_path).expanduser()
    if not stl.is_file():
        errors.append(f"ไม่พบ STL: {stl}")
    if config.stl_scale <= 0:
        errors.append("STL scale ต้องมากกว่า 0")
    if any(config.domain_min[i] >= config.domain_max[i] for i in range(3)):
        errors.append("ค่า domain min ต้องน้อยกว่า max ทุกแกน")
    if any(value < 1 for value in config.divisions):
        errors.append("จำนวนเซลล์ Nx, Ny, Nz ต้องไม่น้อยกว่า 1")
    if config.divisions[2] <= 1:
        errors.append("Nz ต้องมากกว่า 1 สำหรับการคำนวณ 3D")
    if not (0 <= config.surface_min_level <= config.surface_max_level <= 10):
        errors.append("surface refinement level ต้องเป็น 0–10 และ min ไม่เกิน max")
    if config.feature_level < 0 or config.charge_refinement_level < 0:
        errors.append("refinement level ต้องไม่ติดลบ")
    if config.snappy_max_cells < config.base_cells:
        errors.append("snappy maxGlobalCells ต้องมากกว่าจำนวน base cells")
    if config.dynamic_max_cells < config.base_cells:
        errors.append("dynamic maxCells ต้องมากกว่าจำนวน base cells")
    if config.mpi_ranks < 1:
        errors.append("MPI ranks ต้องไม่น้อยกว่า 1")
    if config.performance_profile not in {"fast", "quality", "custom"}:
        errors.append("performance profile ต้องเป็น fast, quality หรือ custom")
    if not config.domain.contains(config.location_in_mesh):
        errors.append("locationInMesh อยู่นอก domain")
    sources = config.effective_sources
    if not sources:
        errors.append("ต้องมี Source อย่างน้อย 1 จุด")
    if len(sources) > 16:
        errors.append("รองรับ Source ได้ไม่เกิน 16 จุดต่อ Case")
    radii: List[float] = []
    charge_cell = (
        max(config.actual_cell_size) / (2 ** config.charge_refinement_level)
        if config.charge_refinement_level >= 0 and all(value > 0 for value in config.divisions)
        else 0.0
    )
    for index, source in enumerate(sources, 1):
        radius = 0.0
        try:
            radius = source.radius(config.explosive_density)
        except ValueError as exc:
            errors.append(f"Source {index}: {exc}")
        radii.append(radius)
        if source.delay < 0:
            errors.append(f"Source {index}: delay ต้องไม่ติดลบ")
        elif config.end_time > 0 and source.delay >= config.end_time:
            errors.append(f"Source {index}: delay ต้องน้อยกว่า endTime")
        if radius and not config.domain.contains(source.centre, margin=radius):
            errors.append(f"Source {index}: ทรงกลมระเบิดตัดหรืออยู่นอกขอบ domain")
        if radius and charge_cell:
            cells_across = 2 * radius / charge_cell
            if cells_across < 2:
                errors.append(
                    f"Source {index}: Charge refinement หยาบเกินไป "
                    f"({cells_across:.2f} cells ต่อเส้นผ่านศูนย์กลาง); "
                    "ต้องมีอย่างน้อย 2 และแนะนำ 5–8 cells"
                )
            elif cells_across < 4:
                warnings.append(
                    f"Source {index}: Charge มีเพียง {cells_across:.2f} cells "
                    "ต่อเส้นผ่านศูนย์กลาง; แนะนำเพิ่ม charge refinement"
                )
    for left in range(len(sources)):
        for right in range(left + 1, len(sources)):
            separation = math.dist(sources[left].centre, sources[right].centre)
            required = radii[left] + radii[right]
            if required > 0 and separation < required:
                errors.append(
                    f"Source {left + 1} และ Source {right + 1} ซ้อนกัน: "
                    f"ระยะศูนย์กลาง {separation:.4g} m < รัศมีรวม {required:.4g} m"
                )
    for index, probe in enumerate(config.probes, 1):
        if not config.domain.contains(probe):
            errors.append(f"Probe {index} อยู่นอก domain: {foam_vec(probe)}")
    if config.end_time <= 0 or config.initial_delta_t <= 0 or config.max_delta_t <= 0:
        errors.append("เวลาและ time step ต้องมากกว่า 0")
    if config.initial_delta_t > config.max_delta_t:
        warnings.append("initial deltaT มากกว่า maxDeltaT")
    if config.write_interval <= 0 or config.write_interval > config.end_time:
        errors.append("writeInterval ต้องมากกว่า 0 และไม่เกิน endTime")
    if not 0 < config.max_co <= 1:
        warnings.append("แนะนำ maxCo อยู่ในช่วง 0–1; งาน blast เริ่มที่ 0.2–0.3")
    if report:
        tolerance = max(report.bounds.diagonal * 1e-9, 1e-9)
        model_is_outside = any(
            report.bounds.minimum[i] < config.domain.minimum[i] - tolerance
            or report.bounds.maximum[i] > config.domain.maximum[i] + tolerance
            for i in range(3)
        )
        if model_is_outside:
            errors.append("Domain ครอบคลุม bounding box ของ STL ไม่ครบ")
        if report.errors and not config.allow_surface_errors:
            errors.append("STL มี surface errors; ซ่อมโมเดลหรือเลือกอนุญาตให้ export พร้อมคำเตือน")
        warnings.extend(report.warnings)
    estimate = config.estimate()
    if estimate["ram_gib_at_dynamic_cap"] > 52:
        warnings.append(
            f"dynamic cell cap อาจใช้ RAM ราว {estimate['ram_gib_at_dynamic_cap']:.1f} GiB "
            "ซึ่งเสี่ยงสำหรับ server RAM 64 GB"
        )
    if estimate["disk_gib_at_dynamic_cap"] > 500:
        warnings.append(
            f"กรณีแตะ cell cap ทุก frame อาจเขียนข้อมูลระดับ {estimate['disk_gib_at_dynamic_cap']:.0f} GiB; "
            "ควรตรวจพื้นที่และปรับ writeInterval"
        )
    if inspect_points and stl.is_file() and not (report and report.errors):
        inside, distance = point_surface_relation(stl, config.stl_scale, config.location_in_mesh)
        if inside:
            errors.append("locationInMesh อยู่ภายใน solid ของ STL")
        for index, (source, radius) in enumerate(zip(sources, radii), 1):
            inside, distance = point_surface_relation(stl, config.stl_scale, source.centre)
            if inside:
                errors.append(f"Source {index}: จุดศูนย์กลางระเบิดอยู่ภายใน solid ของ STL")
            if radius and distance < radius:
                errors.append(
                    f"Source {index}: ทรงกลมระเบิดตัดผิว STL: "
                    f"ระยะใกล้สุด {distance:.4g} m < รัศมี {radius:.4g} m"
                )
    return errors, warnings


def _replace_once(text: str, pattern: str, replacement: str, description: str, flags: int = 0) -> str:
    result, count = re.subn(pattern, replacement, text, count=1, flags=flags)
    if count != 1:
        raise RuntimeError(f"Template mismatch while replacing {description} (matches={count})")
    return result


def _foam_header(object_name: str, location: Optional[str] = None) -> str:
    location_line = f'    location    "{location}";\n' if location else ""
    return f"""/*--------------------------------*- C++ -*----------------------------------*\\
| BlastUrban Case Builder                                                   |
\\*---------------------------------------------------------------------------*/
FoamFile
{{
    version     2.0;
    format      ascii;
    class       dictionary;
{location_line}    object      {object_name};
}}
// ************************************************************************* //
"""


def _block_mesh_dict(config: CaseConfig) -> str:
    mn, mx = config.domain_min, config.domain_max
    nx, ny, nz = config.divisions
    return _foam_header("blockMeshDict") + f"""
convertToMeters 1;

vertices
(
    ({foam_number(mn[0])} {foam_number(mn[1])} {foam_number(mn[2])})
    ({foam_number(mx[0])} {foam_number(mn[1])} {foam_number(mn[2])})
    ({foam_number(mx[0])} {foam_number(mx[1])} {foam_number(mn[2])})
    ({foam_number(mn[0])} {foam_number(mx[1])} {foam_number(mn[2])})
    ({foam_number(mn[0])} {foam_number(mn[1])} {foam_number(mx[2])})
    ({foam_number(mx[0])} {foam_number(mn[1])} {foam_number(mx[2])})
    ({foam_number(mx[0])} {foam_number(mx[1])} {foam_number(mx[2])})
    ({foam_number(mn[0])} {foam_number(mx[1])} {foam_number(mx[2])})
);

blocks
(
    hex (0 1 2 3 4 5 6 7) ({nx} {ny} {nz}) simpleGrading (1 1 1)
);

edges ();

boundary
(
    ground
    {{
        type patch;
        faces ((0 1 2 3));
    }}
    outlet
    {{
        type patch;
        faces
        (
            (0 1 5 4)
            (1 2 6 5)
            (3 2 6 7)
            (0 3 7 4)
            (4 5 6 7)
        );
    }}
);

mergePatchPairs ();
// ************************************************************************* //
"""


def _snappy_dict(config: CaseConfig, stl_name: str, template: Path) -> str:
    text = (template / "system/snappyHexMeshDict").read_text(encoding="utf-8")
    old_stl = re.search(r'file\s+"([^"]+\.stl)"\s*;', text)
    if not old_stl:
        raise RuntimeError("Cannot find STL filename in snappyHexMeshDict template")
    old_name = old_stl.group(1)
    text = text.replace(f'file "{old_name}";', f'file "{stl_name}";', 1)
    text = _replace_once(text, r"(?m)^\s*scale\s+[^;]+;", f"        scale {foam_number(config.stl_scale)};", "STL scale")
    text = _replace_once(text, r"(?m)^\s*maxLocalCells\s+\d+\s*;", f"    maxLocalCells {max(500000, math.ceil(config.snappy_max_cells / config.mpi_ranks * 2))};", "maxLocalCells")
    text = _replace_once(text, r"(?m)^\s*maxGlobalCells\s+\d+\s*;", f"    maxGlobalCells {config.snappy_max_cells};", "maxGlobalCells")
    text = text.replace(
        f'file  "{Path(old_name).stem}.extendedFeatureEdgeMesh";',
        f'file  "{Path(stl_name).stem}.extendedFeatureEdgeMesh";',
        1,
    )
    text = _replace_once(
        text,
        r'(file\s+"[^\"]+\.extendedFeatureEdgeMesh"\s*;\s*\n\s*)level\s+\d+\s*;',
        rf"\g<1>level {config.feature_level};",
        "feature level",
    )
    text = _replace_once(
        text,
        r"(refinementSurfaces\s*\{\s*walls\s*\{\s*)level\s*\(\s*\d+\s+\d+\s*\)\s*;",
        rf"\g<1>level ({config.surface_min_level} {config.surface_max_level});",
        "surface refinement levels",
        flags=re.S,
    )
    text = _replace_once(
        text,
        r"(?m)^\s*locationInMesh\s+\([^;]+;[^\n]*",
        f"    locationInMesh {foam_vec(config.location_in_mesh)}; // Must be in the fluid region",
        "locationInMesh",
    )
    return text


def _surface_features_dict(stl_name: str) -> str:
    return _foam_header("surfaceFeaturesDict") + f"""
surfaces
(
    "{stl_name}"
);

includedAngle 120;

subsetFeatures
{{
    nonManifoldEdges yes;
    openEdges yes;
}}
// ************************************************************************* //
"""


def _set_fields_dict(config: CaseConfig) -> str:
    dx, dy, dz = config.actual_cell_size
    half_base_diagonal = 0.5 * math.sqrt(dx * dx + dy * dy + dz * dz)
    regions: List[str] = []
    for index, source in enumerate(config.effective_sources, 1):
        radius = source.radius(config.explosive_density)
        # The backup must contain at least one base-cell centre even when the
        # charge happens to lie on a cell vertex.  It is used only while the
        # true mass-derived sphere selects no cells during iterative refinement.
        backup_radius = max(radius * 4, half_base_diagonal * 1.05)
        regions.append(
            f"""    // Source {index}: {foam_number(source.mass)} kg C4, delay {foam_number(source.delay)} s
    sphericalMassToCell
    {{
        centre {foam_vec(source.centre)};
        radius {foam_number(radius)}; // theoretical radius; mass/rho control the selected volume
        mass {foam_number(source.mass)};
        rho {foam_number(config.explosive_density)};
        backup
        {{
            centre {foam_vec(source.centre)};
            radius {foam_number(backup_radius)};
        }}
        refineInternal yes;
        level {config.charge_refinement_level};
        fieldValues
        (
            volScalarFieldValue alpha.c4 1
        );
    }}"""
        )
    return _foam_header("setFieldsDict", "system") + f"""
fields (alpha.c4);
nBufferLayers 2;

defaultFieldValues
(
    volScalarFieldValue alpha.c4 0
);

regions
(
{chr(10).join(regions)}
);
// ************************************************************************* //
"""


def _phase_properties(config: CaseConfig, template: Path) -> str:
    text = (template / "constant/phaseProperties").read_text(encoding="utf-8")
    text = re.sub(r"(?m)^(\s*rho0\s+)[^;]+;", rf"\g<1>{foam_number(config.explosive_density)};", text)
    point_lines = "\n".join(f"            {foam_vec(source.centre)}" for source in config.effective_sources)
    delay_lines = "\n".join(f"            {foam_number(source.delay)}" for source in config.effective_sources)
    text = _replace_once(
        text,
        r"(?m)^\s*points\s+\(\([^;]+;[^\n]*",
        "        points\n"
        "        (\n"
        f"{point_lines}\n"
        "        ); // generated detonation points\n"
        "        delays\n"
        "        (\n"
        f"{delay_lines}\n"
        "        ); // generated activation delays [s]",
        "initiation points",
    )
    return text


def _control_dict(config: CaseConfig) -> str:
    probes = "\n".join(f"            {foam_vec(point)}" for point in config.probes)
    write_format = "binary" if config.output_binary else "ascii"
    p = foam_number(config.ambient_pressure)
    point = foam_vec(config.plane_point)
    return _foam_header("controlDict", "system") + f"""
application     blastFoam;
startFrom       startTime;
startTime       0;
stopAt          endTime;
endTime         {foam_number(config.end_time)};
deltaT          {foam_number(config.initial_delta_t)};
writeControl    adjustableRunTime;
writeInterval   {foam_number(config.write_interval)};
cycleWrite      0;
purgeWrite      2;
writeFormat     {write_format};
writePrecision  8;
writeCompression off;
timeFormat      general;
timePrecision   12;
runTimeModifiable true;
adjustTimeStep  yes;
maxCo           {foam_number(config.max_co)};
maxDeltaT       {foam_number(config.max_delta_t)};

functions
{{
    impulse
    {{
        type impulse;
        writeControl writeTime;
        pRef {p};
    }}
    overpressure
    {{
        type overpressure;
        writeControl writeTime;
        store yes;
        pRef {p};
    }}
    maxPImpulse
    {{
        type fieldMinMax;
        writeControl writeTime;
        fields (overpressure impulse);
    }}
    wallSurfaces
    {{
        type surfaces;
        writeControl adjustableRunTime;
        writeInterval {foam_number(config.write_interval)};
        interpolate false;
        interpolationScheme cellPointFace;
        surfaceFormat vtkTimeSeries;
        writeFormat binary;
        fields (overpressure overpressureMax T);
        surfaces
        (
            walls
            {{
                type patch;
                patches (walls);
                triangulate false;
            }}
        );
    }}
    blastSurfaces
    {{
        type surfaces;
        writeControl adjustableRunTime;
        writeInterval {foam_number(config.write_interval)};
        interpolate false;
        interpolationScheme cellPointFace;
        surfaceFormat vtkTimeSeries;
        writeFormat binary;
        fields (p);
        surfaces
        (
            pContours
            {{
                type isoSurface;
                isoField p;
                isoValues ({foam_number(config.pressure_iso_value)});
            }}
        );
    }}
    pressureSlices
    {{
        type surfaces;
        writeControl adjustableRunTime;
        writeInterval {foam_number(config.write_interval)};
        interpolate true;
        interpolationScheme cellPointFace;
        surfaceFormat vtkTimeSeries;
        writeFormat binary;
        fields (overpressure);
        surfaces
        (
            ground
            {{
                type patch;
                patches (ground);
                triangulate false;
            }}
            zNormal
            {{
                type cuttingPlane;
                planeType pointAndNormal;
                pointAndNormalDict {{ point {point}; normal (0 0 1); }}
                interpolate true;
            }}
            yNormal
            {{
                type cuttingPlane;
                planeType pointAndNormal;
                pointAndNormalDict {{ point {point}; normal (0 1 0); }}
                interpolate true;
            }}
            xNormal
            {{
                type cuttingPlane;
                planeType pointAndNormal;
                pointAndNormalDict {{ point {point}; normal (1 0 0); }}
                interpolate true;
            }}
        );
    }}
    pressureProbes
    {{
        type blastProbes;
        writeControl timeStep;
        writeInterval 1;
        adjustLocations yes;
        append yes;
        probeLocations
        (
{probes}
        );
        fields (p);
    }}
}};
// ************************************************************************* //
"""


def _dynamic_mesh_dict(config: CaseConfig) -> str:
    return _foam_header("dynamicMeshDict") + f"""
dynamicFvMesh   adaptiveFvMesh;
errorEstimator  densityGradient;

refineInterval  {config.refine_interval};

loadBalance
{{
    balance yes;
    balanceInterval 10;
    allowableImbalance 0.15;
    method scotch;
}}

lowerRefineLevel 0.1;
unrefineLevel   0.1;
nBufferLayers   3;
maxRefinement   {config.dynamic_max_refinement};
maxCells        {config.dynamic_max_cells};
dumpLevel       false;
// ************************************************************************* //
"""


def _decompose_dict(config: CaseConfig) -> str:
    return _foam_header("decomposeParDict", "system") + f"""
numberOfSubdomains {config.mpi_ranks};
method scotch;
distributed no;
roots ();
// ************************************************************************* //
"""


def _allrun(config: CaseConfig, stl_name: str) -> str:
    stl_stem = Path(stl_name).stem
    return f"""#!/bin/sh
set -eu
cd "${{0%/*}}" || exit 1

if [ -z "${{WM_PROJECT_DIR:-}}" ]; then
    echo "ERROR: Load OpenFOAM 9 and BlastUrban environments first." >&2
    echo "source /opt/openfoam9/etc/bashrc && source /path/to/BlastUrban/etc/bashrc" >&2
    exit 2
fi
. "$WM_PROJECT_DIR/bin/tools/RunFunctions"

SURFACE_CHECK_RUN_ID="allrun-$(date +%Y%m%d-%H%M%S)-$$"
export SURFACE_CHECK_RUN_ID
organizeSurfaceCheck()
{{
    ./organizeSurfaceCheckOutput.sh "{stl_stem}" >/dev/null 2>&1 || true
}}
trap organizeSurfaceCheck 0 1 2 15

echo "[1/9] Checking STL"
runApplication surfaceCheck "constant/triSurface/{stl_name}"
organizeSurfaceCheck
echo "[2/9] Extracting surface features"
runApplication surfaceFeatures
echo "[3/9] Creating {config.base_cells:,} base cells"
runApplication blockMesh
runApplication -s base checkMesh
echo "[4/9] Decomposing for {config.mpi_ranks} MPI ranks"
runApplication decomposePar -force -copyZero
echo "[5/9] Snapping the 3-D building mesh"
runParallel snappyHexMesh -overwrite
runParallel -s snapped checkMesh -allTopology
echo "[6/9] Creating internal patch"
runParallel addEmptyPatch internalPatch internal -overwrite
echo "[7/9] Refining and setting the C4 charge"
runParallel setRefinedFields
runParallel -s initialised checkMesh -latestTime
echo "[8/9] Running blastFoam"
runParallel blastFoam
echo "[9/9] Calculating probe impulse"
runApplication calculateImpulse pressureProbes
echo "Completed: $(pwd)"
"""


def _allclean() -> str:
    return """#!/bin/sh
set -eu
cd "${0%/*}" || exit 1
. "$WM_PROJECT_DIR/bin/tools/CleanFunctions"
cleanCase
for original in 0/*.orig; do
    [ -e "$original" ] || continue
    cp "$original" "${original%.orig}"
done
"""


def _server_readme(config: CaseConfig, report: StlReport) -> str:
    estimate = config.estimate()
    cell = config.actual_cell_size
    source_lines = "\n".join(
        f"  - Source {index}: `{foam_number(source.mass)}` kg at "
        f"`{foam_vec(source.centre)}` m, delay `{foam_number(source.delay)}` s, "
        f"radius `{foam_number(source.radius(config.explosive_density))}` m"
        for index, source in enumerate(config.effective_sources, 1)
    )
    return f"""# {config.case_name}: server run package

Generated by BlastUrban 3-D Case Builder. The original template was not modified.

## Main settings

- STL: `{Path(config.stl_path).name}`, scale `{foam_number(config.stl_scale)}`
- Scaled model: `{foam_vec(report.bounds.minimum)}` to `{foam_vec(report.bounds.maximum)}` m
- Domain: `{foam_vec(config.domain_min)}` to `{foam_vec(config.domain_max)}` m
- Base mesh: `{config.divisions[0]} x {config.divisions[1]} x {config.divisions[2]}` = `{config.base_cells:,}` cells
- Actual base-cell size: `{foam_vec(cell)}` m
- Wall refinement: `{config.surface_min_level}-{config.surface_max_level}`
- C4 Sources: `{len(config.effective_sources)}`, total mass `{foam_number(config.total_charge_mass)}` kg
{source_lines}
- Charge refinement: `{config.charge_refinement_level}`
- Simulation: `0-{foam_number(config.end_time)}` s, maxCo `{foam_number(config.max_co)}`
- Performance profile: `{config.performance_profile}`
- MPI ranks: `{config.mpi_ranks}`
- Dynamic cell cap: `{config.dynamic_max_cells:,}`
- Rough RAM at the cap (planning estimate only): `{estimate['ram_gib_at_dynamic_cap']:.1f}` GiB
- Output frames: approximately `{int(estimate['frames']):,}`

## Run on the calculation server

```bash
tar -xzf {config.case_name}.tar.gz
cd {config.case_name}
source /opt/openfoam9/etc/bashrc
source /path/to/BlastUrban/etc/bashrc
./server-run-auto.sh
```

`server-run-auto.sh` uses Slurm automatically when `sbatch` is available. On a
standalone Linux server it waits for sufficient free CPU/RAM, reserves resources
for other users, prevents duplicate runs of this case, and starts `Allrun` with
low CPU/I/O priority. Edit `server-job.env` to change the limits.

Monitor the calculation:

```bash
tail -f log.blastFoam
du -sh .
free -h
df -h .
```

`surfaceCheck` and `checkMesh` must be reviewed before accepting engineering results.
Connected-part OBJ files, zone VTK, and surface-check logs are grouped by run in
`diagnostics/surfaceCheck/<run-id>/` instead of being left in the case root.
After a successful run, `makeWebResults.sh` creates `results-web/blast3D.html`
and `{config.case_name}-web-result.tar.gz`. The offline viewer can display
overpressure, peak overpressure, temperature, Surface, Surface with Edges, or
hide each 3-D surface.
The RAM/disk figures are conservative planning estimates, not solver guarantees.
"""


def _preflight(config: CaseConfig, stl_name: str) -> str:
    stl_stem = Path(stl_name).stem
    return f"""#!/bin/sh
set -eu
cd "${{0%/*}}" || exit 1
for command in surfaceCheck surfaceFeatures blockMesh checkMesh decomposePar snappyHexMesh \
               addEmptyPatch setRefinedFields blastFoam blastToVTK calculateImpulse \
               mpirun; do
    command -v "$command" >/dev/null 2>&1 || {{ echo "ERROR: missing $command" >&2; exit 2; }}
done
echo "OpenFOAM: ${{WM_PROJECT_VERSION:-unknown}}"
echo "MPI ranks configured: {config.mpi_ranks}"
echo "RAM available:"
free -h || true
echo "Disk available:"
df -h .
SURFACE_CHECK_RUN_ID="preflight-$(date +%Y%m%d-%H%M%S)-$$"
export SURFACE_CHECK_RUN_ID
organizeSurfaceCheck()
{{
    ./organizeSurfaceCheckOutput.sh "{stl_stem}" >/dev/null 2>&1 || true
}}
trap organizeSurfaceCheck 0 1 2 15
if surfaceCheck "constant/triSurface/{stl_name}" > log.preflight.surfaceCheck 2>&1; then
    surface_status=0
else
    surface_status=$?
fi
cat log.preflight.surfaceCheck
organizeSurfaceCheck
if [ "$surface_status" -ne 0 ]; then
    echo "ERROR: surfaceCheck failed with status $surface_status" >&2
    exit "$surface_status"
fi
echo "Preflight passed. Review diagnostics/surfaceCheck/$SURFACE_CHECK_RUN_ID, then run ./Allrun"
"""


def _patch_initial_fields(target: Path, config: CaseConfig) -> None:
    for original in (target / "0").glob("*.orig"):
        runtime = original.with_suffix("")
        text = original.read_text(encoding="utf-8")
        if original.name == "rho.c4.orig":
            text = _replace_once(
                text,
                r"(?m)^(\s*internalField\s+uniform\s+)[^;]+;",
                rf"\g<1>{foam_number(config.explosive_density)};",
                "rho.c4 initial density",
            )
        elif original.name == "p.orig":
            text = _replace_once(
                text,
                r"(?m)^(\s*internalField\s+uniform\s+)[^;]+;",
                rf"\g<1>{foam_number(config.ambient_pressure)};",
                "ambient pressure",
            )
        original.write_text(text, encoding="utf-8")
        runtime.write_text(text, encoding="utf-8")


def create_case(
    config: CaseConfig,
    output_parent: Path,
    report: Optional[StlReport] = None,
    template: Path = DEFAULT_TEMPLATE,
    create_archive: bool = True,
) -> Tuple[Path, Optional[Path], List[str]]:
    """Create a new, non-overwriting case directory and optional tar.gz."""
    template = Path(template).resolve()
    output_parent = Path(output_parent).expanduser().resolve()
    if report is None:
        report = analyse_stl(Path(config.stl_path), config.stl_scale, run_external=False)
    errors, warnings = validate_config(config, report, inspect_points=True)
    if errors:
        raise ValueError("ไม่สามารถสร้าง case:\n- " + "\n- ".join(errors))
    case_name = safe_case_name(config.case_name)
    target = output_parent / case_name
    if target.exists():
        raise FileExistsError(f"Output already exists; จะไม่เขียนทับ: {target}")
    if not template.is_dir():
        raise FileNotFoundError(f"Template case not found: {template}")

    stl_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", Path(config.stl_path).name)
    if not stl_name.lower().endswith(".stl"):
        stl_name += ".stl"
    try:
        (target / "system").mkdir(parents=True)
        (target / "constant/triSurface").mkdir(parents=True)
        (target / "0").mkdir(parents=True)
        shutil.copy2(config.stl_path, target / "constant/triSurface" / stl_name)
        repair_sidecar = Path(config.stl_path).with_suffix(".repair.json")
        if repair_sidecar.is_file():
            shutil.copy2(repair_sidecar, target / "geometry-repair.json")
        for name in ("fvSchemes", "fvSolution"):
            shutil.copy2(template / "system" / name, target / "system" / name)
        for source in (template / "0").glob("*.orig"):
            shutil.copy2(source, target / "0" / source.name)

        (target / "system/blockMeshDict").write_text(_block_mesh_dict(config), encoding="utf-8")
        (target / "system/snappyHexMeshDict").write_text(_snappy_dict(config, stl_name, template), encoding="utf-8")
        (target / "system/surfaceFeaturesDict").write_text(_surface_features_dict(stl_name), encoding="utf-8")
        (target / "system/setFieldsDict").write_text(_set_fields_dict(config), encoding="utf-8")
        (target / "system/controlDict").write_text(_control_dict(config), encoding="utf-8")
        (target / "system/decomposeParDict").write_text(_decompose_dict(config), encoding="utf-8")
        (target / "constant/dynamicMeshDict").write_text(_dynamic_mesh_dict(config), encoding="utf-8")
        (target / "constant/phaseProperties").write_text(_phase_properties(config, template), encoding="utf-8")
        _patch_initial_fields(target, config)

        files = {
            "Allrun": _allrun(config, stl_name),
            "Allclean": _allclean(),
            "preflight.sh": _preflight(config, stl_name),
        }
        for filename, content in files.items():
            path = target / filename
            path.write_text(content, encoding="utf-8")
            path.chmod(0o755)
        organizer = target / "organizeSurfaceCheckOutput.sh"
        shutil.copy2(template / "organizeSurfaceCheckOutput.sh", organizer)
        organizer.chmod(0o755)
        for script_name in (
            "server-run-auto.sh",
            "server-docker-job.sh",
            "makeWebResults.sh",
            "runBlastToVTKIsolated.sh",
        ):
            script = target / script_name
            shutil.copy2(UI_ASSETS / script_name, script)
            script.chmod(0o755)
        (target / "visualization").mkdir()
        for visualizer_name in ("exportBlast3D.py", "viewer_template.html"):
            shutil.copy2(
                template / "visualization" / visualizer_name,
                target / "visualization" / visualizer_name,
            )
        estimated_memory = max(1, math.ceil(config.estimate()["ram_gib_at_dynamic_cap"]))
        reserve_cores = max(1, min(2, config.mpi_ranks - 1)) if config.mpi_ranks > 1 else 0
        (target / "server-job.env").write_text(
            "# Safe defaults generated for this case. Adjust for the server policy.\n"
            f"BLAST_JOB_NAME={case_name}\n"
            "BLAST_JOB_CORES=auto\n"
            f"BLAST_MAX_CORES={config.mpi_ranks}\n"
            f"BLAST_MIN_CORES={min(2, config.mpi_ranks)}\n"
            f"BLAST_RESERVE_CORES={reserve_cores}\n"
            f"BLAST_MEMORY_GIB={estimated_memory}\n"
            "BLAST_RESERVE_MEMORY_GIB=8\n"
            "BLAST_WALLTIME=24:00:00\n"
            "BLAST_SCHEDULER=auto\n"
            "BLAST_WAIT_FOR_RESOURCES=1\n"
            "BLAST_OPENFOAM_BASHRC=/opt/openfoam9/etc/bashrc\n"
            "BLAST_REPO_BASHRC=\n"
            "BLAST_SLURM_PARTITION=\n",
            encoding="utf-8",
        )
        (target / "SERVER_COMMANDS.md").write_text(_server_readme(config, report), encoding="utf-8")
        manifest = {
            "schema_version": 1,
            "generator": "BlastUrban 3-D Case Builder",
            "config": asdict(config),
            "stl_report": asdict(report),
            "warnings": warnings,
        }
        (target / "case-builder.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    except Exception:
        if target.exists():
            shutil.rmtree(target)
        raise

    archive: Optional[Path] = None
    if create_archive:
        archive = output_parent / f"{case_name}.tar.gz"
        if archive.exists():
            shutil.rmtree(target)
            raise FileExistsError(f"Archive already exists; จะไม่เขียนทับ: {archive}")
        with tarfile.open(archive, "w:gz") as handle:
            handle.add(target, arcname=case_name)
    return target, archive, warnings


def parse_vec(text: str) -> Vec3:
    fields = text.replace(",", " ").split()
    if len(fields) != 3:
        raise ValueError("ต้องใส่ตัวเลข 3 ค่า: x y z")
    result = tuple(float(item) for item in fields)
    if not all(math.isfinite(item) for item in result):
        raise ValueError("พิกัดต้องเป็นเลข finite")
    return result  # type: ignore[return-value]


def parse_probes(text: str) -> List[Vec3]:
    probes: List[Vec3] = []
    for line_number, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#", 1)[0].strip().strip("()")
        if not line:
            continue
        try:
            probes.append(parse_vec(line))
        except ValueError as exc:
            raise ValueError(f"Probe บรรทัด {line_number}: {exc}") from exc
    if not probes:
        raise ValueError("ต้องมี probe อย่างน้อย 1 จุด")
    return probes
