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
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Tuple


Vec3 = Tuple[float, float, float]
Triangle = Tuple[Vec3, Vec3, Vec3]


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TEMPLATE = REPO_ROOT / "tutorials/blastFoam/building3DWorkshop"


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


def _binary_stl_info(path: Path) -> Tuple[bool, int]:
    size = path.stat().st_size
    if size < 84:
        return False, 0
    with path.open("rb") as handle:
        header = handle.read(84)
    triangle_count = struct.unpack("<I", header[80:84])[0]
    return size == 84 + triangle_count * 50, triangle_count


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
                    raise ValueError("Binary STL ended before all triangles were read")
                values = record.unpack(data)
                yield (
                    (values[3], values[4], values[5]),
                    (values[6], values[7], values[8]),
                    (values[9], values[10], values[11]),
                )
        return

    vertices: List[Vec3] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line_number, line in enumerate(handle, 1):
            fields = line.strip().split()
            if fields and fields[0].lower() == "vertex":
                if len(fields) != 4:
                    raise ValueError(f"Invalid ASCII STL vertex at line {line_number}")
                try:
                    vertices.append((float(fields[1]), float(fields[2]), float(fields[3])))
                except ValueError as exc:
                    raise ValueError(f"Invalid number in ASCII STL at line {line_number}") from exc
                if len(vertices) == 3:
                    yield (vertices[0], vertices[1], vertices[2])
                    vertices.clear()
    if vertices:
        raise ValueError("ASCII STL has an incomplete triangle")


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
    snappy_max_cells: int = 6_000_000
    dynamic_max_cells: int = 8_000_000
    dynamic_max_refinement: int = 2
    refine_interval: int = 5
    location_in_mesh: Vec3 = (-10.0, -10.0, 1.0)
    charge_centre: Vec3 = (35.0, 20.0, 1.0)
    charge_mass: float = 10.0
    explosive_density: float = 1601.0
    charge_refinement_level: int = 6
    probes: List[Vec3] = field(default_factory=lambda: [(35.0, 15.0, 1.0), (40.0, 20.0, 1.0)])
    plane_point: Vec3 = (35.0, 20.0, 1.0)
    end_time: float = 0.0125
    initial_delta_t: float = 5e-8
    max_delta_t: float = 2.5e-7
    max_co: float = 0.3
    write_interval: float = 2.5e-5
    ambient_pressure: float = 101298.0
    pressure_iso_value: float = 110000.0
    mpi_ranks: int = 10
    output_binary: bool = True
    allow_surface_errors: bool = False

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
        return charge_radius(self.charge_mass, self.explosive_density)

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
    if not config.domain.contains(config.location_in_mesh):
        errors.append("locationInMesh อยู่นอก domain")
    radius = 0.0
    try:
        radius = config.theoretical_charge_radius
    except ValueError as exc:
        errors.append(str(exc))
    if radius and not config.domain.contains(config.charge_centre, margin=radius):
        errors.append("ทรงกลมระเบิดตัดหรืออยู่นอกขอบ domain")
    if radius and config.charge_refinement_level >= 0 and all(value > 0 for value in config.divisions):
        charge_cell = max(config.actual_cell_size) / (2 ** config.charge_refinement_level)
        cells_across = 2 * radius / charge_cell
        if cells_across < 2:
            errors.append(
                f"Charge refinement หยาบเกินไป ({cells_across:.2f} cells ต่อเส้นผ่านศูนย์กลาง); "
                "ต้องมีอย่างน้อย 2 และแนะนำ 5–8 cells"
            )
        elif cells_across < 4:
            warnings.append(
                f"Charge มีเพียง {cells_across:.2f} cells ต่อเส้นผ่านศูนย์กลาง; แนะนำเพิ่ม charge refinement"
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
        inside, distance = point_surface_relation(stl, config.stl_scale, config.charge_centre)
        if inside:
            errors.append("จุดศูนย์กลางระเบิดอยู่ภายใน solid ของ STL")
        if radius and distance < radius:
            errors.append(
                f"ทรงกลมระเบิดตัดผิว STL: ระยะใกล้สุด {distance:.4g} m < รัศมี {radius:.4g} m"
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
    radius = config.theoretical_charge_radius
    dx, dy, dz = config.actual_cell_size
    half_base_diagonal = 0.5 * math.sqrt(dx * dx + dy * dy + dz * dz)
    # The backup must contain at least one base-cell centre even when the
    # charge happens to lie on a cell vertex.  It is used only while the true
    # mass-derived sphere selects no cells during iterative refinement.
    backup_radius = max(radius * 4, half_base_diagonal * 1.05)
    return _foam_header("setFieldsDict", "system") + f"""
fields (alpha.c4);
nBufferLayers 2;

defaultFieldValues
(
    volScalarFieldValue alpha.c4 0
);

regions
(
    sphericalMassToCell
    {{
        centre {foam_vec(config.charge_centre)};
        radius {foam_number(radius)}; // theoretical radius; mass/rho control the selected volume
        mass {foam_number(config.charge_mass)};
        rho {foam_number(config.explosive_density)};
        backup
        {{
            centre {foam_vec(config.charge_centre)};
            radius {foam_number(backup_radius)};
        }}
        refineInternal yes;
        level {config.charge_refinement_level};
        fieldValues
        (
            volScalarFieldValue alpha.c4 1
        );
    }}
);
// ************************************************************************* //
"""


def _phase_properties(config: CaseConfig, template: Path) -> str:
    text = (template / "constant/phaseProperties").read_text(encoding="utf-8")
    text = re.sub(r"(?m)^(\s*rho0\s+)[^;]+;", rf"\g<1>{foam_number(config.explosive_density)};", text)
    text = _replace_once(
        text,
        r"(?m)^\s*points\s+\(\([^;]+;[^\n]*",
        f"        points     ({foam_vec(config.charge_centre)}); // generated detonation point",
        "initiation point",
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
    surfaces
    {{
        type surfaces;
        writeControl adjustableRunTime;
        writeInterval {foam_number(config.write_interval)};
        interpolate false;
        interpolationScheme cellPointFace;
        surfaceFormat vtkTimeSeries;
        fields (p overpressure overpressureMax T);
        surfaces
        (
            ground
            {{
                type patch;
                patches (ground);
                triangulate false;
            }}
            walls
            {{
                type patch;
                patches (walls);
                triangulate false;
            }}
            pContours
            {{
                type isoSurface;
                isoField p;
                isoValues ({foam_number(config.pressure_iso_value)});
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
dumpLevel       true;
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
    dt = foam_number(config.write_interval)
    return f"""#!/bin/sh
set -eu
cd "${{0%/*}}" || exit 1

if [ -z "${{WM_PROJECT_DIR:-}}" ]; then
    echo "ERROR: Load OpenFOAM 9 and BlastUrban environments first." >&2
    echo "source /opt/openfoam9/etc/bashrc && source /path/to/BlastUrban/etc/bashrc" >&2
    exit 2
fi
. "$WM_PROJECT_DIR/bin/tools/RunFunctions"

echo "[1/9] Checking STL"
runApplication surfaceCheck "constant/triSurface/{stl_name}"
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
echo "[9/9] Sampling results"
runParallel -s ground blastToVTK ground -dt {dt} -interpolationScheme cubicClamp
runParallel -s walls blastToVTK walls -dt {dt} -interpolationScheme linearClamp
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
    return f"""# {config.case_name}: server run package

Generated by BlastUrban 3-D Case Builder. The original template was not modified.

## Main settings

- STL: `{Path(config.stl_path).name}`, scale `{foam_number(config.stl_scale)}`
- Scaled model: `{foam_vec(report.bounds.minimum)}` to `{foam_vec(report.bounds.maximum)}` m
- Domain: `{foam_vec(config.domain_min)}` to `{foam_vec(config.domain_max)}` m
- Base mesh: `{config.divisions[0]} x {config.divisions[1]} x {config.divisions[2]}` = `{config.base_cells:,}` cells
- Actual base-cell size: `{foam_vec(cell)}` m
- Wall refinement: `{config.surface_min_level}-{config.surface_max_level}`
- Charge: `{foam_number(config.charge_mass)}` kg C4 at `{foam_vec(config.charge_centre)}` m
- Theoretical charge radius: `{foam_number(config.theoretical_charge_radius)}` m
- Charge refinement: `{config.charge_refinement_level}`
- Simulation: `0-{foam_number(config.end_time)}` s, maxCo `{foam_number(config.max_co)}`
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
./preflight.sh
./Allrun
```

Monitor the calculation:

```bash
tail -f log.blastFoam
du -sh .
free -h
df -h .
```

`surfaceCheck` and `checkMesh` must be reviewed before accepting engineering results.
The RAM/disk figures are conservative planning estimates, not solver guarantees.
"""


def _preflight(config: CaseConfig, stl_name: str) -> str:
    return f"""#!/bin/sh
set -eu
cd "${{0%/*}}" || exit 1
for command in surfaceCheck surfaceFeatures blockMesh checkMesh decomposePar snappyHexMesh setRefinedFields blastFoam mpirun; do
    command -v "$command" >/dev/null 2>&1 || {{ echo "ERROR: missing $command" >&2; exit 2; }}
done
echo "OpenFOAM: ${{WM_PROJECT_VERSION:-unknown}}"
echo "MPI ranks configured: {config.mpi_ranks}"
echo "RAM available:"
free -h || true
echo "Disk available:"
df -h .
surfaceCheck "constant/triSurface/{stl_name}" | tee log.preflight.surfaceCheck
echo "Preflight passed. Review log.preflight.surfaceCheck, then run ./Allrun"
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
