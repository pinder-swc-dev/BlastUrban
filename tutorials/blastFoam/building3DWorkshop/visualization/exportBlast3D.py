#!/usr/bin/env python3
"""Build a self-contained 3D time viewer from blastFoam VTK surface series."""

import argparse
import base64
import csv
import hashlib
import json
import math
import re
import struct
import zlib
from pathlib import Path

import numpy as np
import vtk
from vtk.util.numpy_support import numpy_to_vtk, vtk_to_numpy


def series(case, relative):
    path = case / relative
    entries = json.loads(path.read_text(encoding="utf-8"))["files"]
    return {round(float(item["time"]), 12): path.parent / item["name"] for item in entries}


def read_triangles(path, target_cells=None, transfer_fields=False):
    with path.open("rb") as source:
        if not source.read(24).startswith(b"# vtk DataFile"):
            raise ValueError(f"Invalid VTK header in {path}")
    reader = vtk.vtkPolyDataReader()
    reader.SetFileName(str(path))
    reader.Update()
    triangulate = vtk.vtkTriangleFilter()
    triangulate.SetInputConnection(reader.GetOutputPort())
    triangulate.Update()
    mesh = triangulate.GetOutput()
    source_mesh = mesh
    source_ids = None
    if target_cells and mesh.GetNumberOfCells() > target_cells:
        decimate = vtk.vtkDecimatePro()
        decimate.SetInputConnection(triangulate.GetOutputPort())
        decimate.SetTargetReduction(1 - target_cells / mesh.GetNumberOfCells())
        decimate.PreserveTopologyOff()
        decimate.Update()
        mesh = decimate.GetOutput()
        if transfer_fields:
            centers = vtk.vtkCellCenters()
            centers.SetInputData(source_mesh)
            centers.Update()
            locator = vtk.vtkStaticPointLocator()
            locator.SetDataSet(centers.GetOutput())
            locator.BuildLocator()
            source_ids = []
            for i in range(mesh.GetNumberOfCells()):
                face = mesh.GetCell(i)
                centroid = tuple(sum(mesh.GetPoint(face.GetPointId(j))[k] for j in range(3)) / 3 for k in range(3))
                source_ids.append(locator.FindClosestPoint(centroid))
    if not mesh.GetNumberOfCells():
        raise ValueError(f"No triangles in {path}")
    coords = [[round(x, 3) for x in mesh.GetPoint(i)] for i in range(mesh.GetNumberOfPoints())]
    faces = [[mesh.GetCell(i).GetPointId(j) for j in range(3)] for i in range(mesh.GetNumberOfCells())]
    return mesh, {"points": coords, "faces": faces}, source_mesh, source_ids


def wall_fields(mesh, path, source_ids=None):
    cells = mesh.GetCellData()
    result = {}
    for name, key, factor in (
        ("overpressure", "op", 0.001),
        ("overpressureMax", "opMax", 0.001),
        ("T", "temp", 1),
    ):
        field = cells.GetArray(name)
        if field is None:
            raise ValueError(f"Missing {name} in {path}")
        indices = source_ids if source_ids is not None else range(mesh.GetNumberOfCells())
        result[key] = [round(field.GetTuple1(i) * factor, 2) for i in indices]
    return result


def wave_overpressure(mesh, path, ambient_pa, source_ids=None):
    """Map real pressure samples onto the compact CFD iso-surface geometry."""
    mesh, field = cell_array(mesh, "p", path)
    indices = source_ids if source_ids is not None else range(mesh.GetNumberOfCells())
    values = []
    for index in indices:
        value = (field.GetTuple1(index) - ambient_pa) * 0.001
        values.append(round(value if math.isfinite(value) else 0.0, 2))
    return values


def first_series(case, relatives, required=True):
    """Read the first available series path, supporting old and compact cases."""
    for relative in relatives:
        path = case / relative
        if path.is_file():
            return series(case, relative)
    if required:
        raise ValueError(f"Missing VTK series; checked: {', '.join(relatives)}")
    return {}


def cell_array(mesh, name, path):
    """Return a cell array, converting interpolated point data when necessary."""
    field = mesh.GetCellData().GetArray(name)
    if field is not None:
        return mesh, field
    if mesh.GetPointData().GetArray(name) is None:
        raise ValueError(f"Missing {name} in {path}")
    converter = vtk.vtkPointDataToCellData()
    converter.SetInputData(mesh)
    converter.PassPointDataOff()
    converter.Update()
    converted = converter.GetOutput()
    field = converted.GetCellData().GetArray(name)
    if field is None:
        raise ValueError(f"Cannot convert point field {name} in {path}")
    return converted, field


def surface_voxels(mesh, requested_size, max_voxels):
    """Quantize a real triangle surface into a bounded Cartesian voxel shell.

    The returned cells reference the source face whose samples occupied each
    voxel. This keeps calculated wall/wave fields attached to real geometry;
    it does not fill an invented solid volume or change the solver mesh.
    """
    points = mesh.get("points", [])
    faces = mesh.get("faces", [])
    if requested_size <= 0 or max_voxels < 1:
        raise ValueError("Voxel size and limit must be positive")
    if not points or not faces:
        return {
            "origin": [0, 0, 0], "size": requested_size,
            "requestedSize": requested_size, "cells": [], "adaptive": False,
        }

    area = 0.0
    for face in faces:
        a, b, c = (points[index] for index in face[:3])
        u = [b[axis] - a[axis] for axis in range(3)]
        v = [c[axis] - a[axis] for axis in range(3)]
        cross = (
            u[1] * v[2] - u[2] * v[1],
            u[2] * v[0] - u[0] * v[2],
            u[0] * v[1] - u[1] * v[0],
        )
        area += 0.5 * math.sqrt(sum(value * value for value in cross))

    # Avoid allocating millions of 0.1 m samples before applying the cap.
    size = max(requested_size, math.sqrt(max(area, 0.0) / max_voxels) * 0.95)
    cells = {}
    origin = [0.0, 0.0, 0.0]
    for _ in range(6):
        origin = [math.floor(min(point[axis] for point in points) / size) * size for axis in range(3)]
        cells = {}
        over_limit = False
        for face_index, face in enumerate(faces):
            a, b, c = (points[index] for index in face[:3])
            longest = max(math.dist(a, b), math.dist(b, c), math.dist(c, a))
            steps = max(1, math.ceil(longest / (size * 0.85)))
            for row in range(steps + 1):
                for column in range(steps + 1 - row):
                    u = row / steps
                    v = column / steps
                    w = 1.0 - u - v
                    sample = [w * a[axis] + u * b[axis] + v * c[axis] for axis in range(3)]
                    key = tuple(math.floor((sample[axis] - origin[axis]) / size) for axis in range(3))
                    cells.setdefault(key, face_index)
                    if len(cells) > max_voxels:
                        over_limit = True
                        break
                if over_limit:
                    break
            if over_limit:
                break
        if not over_limit:
            break
        size *= 1.15
    if len(cells) > max_voxels:
        raise ValueError(f"Cannot bound surface voxels to {max_voxels:,} cells")
    return {
        "origin": [round(value, 6) for value in origin],
        "size": round(size, 6),
        "requestedSize": requested_size,
        "cells": [[*key, face_index] for key, face_index in sorted(cells.items())],
        "adaptive": size > requested_size * 1.000001,
    }


def stl_geometry(path):
    """Read the repaired STL itself for model-voxel display geometry."""
    reader = vtk.vtkSTLReader()
    reader.SetFileName(str(path))
    reader.Update()
    triangulate = vtk.vtkTriangleFilter()
    triangulate.SetInputConnection(reader.GetOutputPort())
    triangulate.Update()
    mesh = triangulate.GetOutput()
    if not mesh.GetNumberOfCells():
        raise ValueError(f"Empty STL model: {path}")
    return {
        "points": [[float(value) for value in mesh.GetPoint(index)] for index in range(mesh.GetNumberOfPoints())],
        "faces": [
            [mesh.GetCell(index).GetPointId(corner) for corner in range(3)]
            for index in range(mesh.GetNumberOfCells())
        ],
    }


def case_stl_path(case):
    """Resolve the case-controlled STL name instead of assuming a template name."""
    tri_surface = case / "constant/triSurface"
    try:
        text = (case / "system/snappyHexMeshDict").read_text(encoding="utf-8")
        match = re.search(r'\bfile\s+"([^"/]+\.stl)"\s*;', text, re.I)
        if match:
            path = tri_surface / match.group(1)
            if path.is_file():
                return path
    except OSError:
        pass
    candidates = sorted(tri_surface.glob("*.stl"))
    if len(candidates) == 1:
        return candidates[0]
    raise ValueError(f"Cannot identify one case STL in {tri_surface}")


def map_voxels_to_faces(voxels, field_geometry):
    """Map STL voxels to the nearest calculated wall face for real fields."""
    centers = vtk.vtkPoints()
    for face in field_geometry["faces"]:
        centers.InsertNextPoint(tuple(
            sum(field_geometry["points"][index][axis] for index in face) / len(face)
            for axis in range(3)
        ))
    cloud = vtk.vtkPolyData()
    cloud.SetPoints(centers)
    locator = vtk.vtkStaticPointLocator()
    locator.SetDataSet(cloud)
    locator.BuildLocator()
    origin, size = voxels["origin"], voxels["size"]
    for cell in voxels["cells"]:
        point = tuple(origin[axis] + (cell[axis] + 0.5) * size for axis in range(3))
        cell[3] = locator.FindClosestPoint(point)
    return voxels


def reference_surface(path, target_cells):
    """Create one shared wall mesh and centroids for mapping all time fields."""
    mesh, geometry, _, _ = read_triangles(path, target_cells)
    centroids = []
    for face_index in range(mesh.GetNumberOfCells()):
        face = mesh.GetCell(face_index)
        centroids.append(tuple(
            sum(mesh.GetPoint(face.GetPointId(j))[axis] for j in range(face.GetNumberOfPoints()))
            / face.GetNumberOfPoints()
            for axis in range(3)
        ))
    return geometry, centroids


def mapped_wall_fields(paths, centroids):
    """Map real sampled wall fields onto a shared, compact wall geometry."""
    surfaces = {}
    for name, path in paths.items():
        reader = vtk.vtkPolyDataReader()
        reader.SetFileName(str(path))
        reader.Update()
        mesh = reader.GetOutput()
        if not mesh.GetNumberOfCells():
            raise ValueError(f"Empty sampled wall surface: {path}")
        mesh, _ = cell_array(mesh, name, path)
        surfaces[name] = mesh
    reference = surfaces["overpressure"]
    centers = vtk.vtkCellCenters()
    centers.SetInputData(reference)
    centers.Update()
    locator = vtk.vtkStaticPointLocator()
    locator.SetDataSet(centers.GetOutput())
    locator.BuildLocator()
    source_ids = [locator.FindClosestPoint(point) for point in centroids]
    result = {}
    stats = {}
    for source, target, factor in (
        ("overpressure", "op", 0.001),
        ("overpressureMax", "opMax", 0.001),
        ("T", "temp", 1),
    ):
        _, field = cell_array(surfaces[source], source, paths[source])
        stats[target] = round(field.GetRange()[1] * factor, 2)
        fallback = 300 if source == "T" else 0
        values = []
        for index in source_ids:
            value = field.GetTuple1(index) * factor
            values.append(round(value if math.isfinite(value) else fallback, 2))
        result[target] = values
    return result, stats


def png_chunk(kind, payload):
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)


def rgba_png(width, height, rgba):
    """Encode an RGBA numpy array as PNG without an additional image package."""
    rows = b"".join(b"\0" + rgba[row].tobytes() for row in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + png_chunk(b"IHDR", header) + png_chunk(b"IDAT", zlib.compress(rows, 6)) + png_chunk(b"IEND", b"")


def bounded_plane_grid(u_span, v_span, requested_spacing, max_pixels):
    """Return an adaptive display grid that never exceeds the pixel cap."""
    if u_span < 0 or v_span < 0 or requested_spacing <= 0 or max_pixels < 1:
        raise ValueError("Invalid voxel-plane dimensions")
    spacing = requested_spacing
    for _ in range(8):
        width = max(1, math.ceil(u_span / spacing))
        height = max(1, math.ceil(v_span / spacing))
        pixels = width * height
        if pixels <= max_pixels:
            return width, height, spacing
        spacing *= math.sqrt(pixels / max_pixels) * 1.000001
    raise ValueError(f"Cannot bound voxel plane to {max_pixels:,} cells")


def voxel_plane(path, plane_name, spacing, low_kpa, high_kpa, max_pixels=500_000):
    """Resample a calculated axis-aligned surface onto uniform cell-centre pixels."""
    reader = vtk.vtkPolyDataReader()
    reader.SetFileName(str(path))
    reader.Update()
    source = reader.GetOutput()
    if not source.GetNumberOfCells():
        raise ValueError(f"Empty sampled pressure surface: {path}")
    if source.GetPointData().GetArray("overpressure") is None:
        if source.GetCellData().GetArray("overpressure") is None:
            raise ValueError(f"Missing overpressure in {path}")
        converter = vtk.vtkCellDataToPointData()
        converter.SetInputData(source)
        converter.PassCellDataOff()
        converter.Update()
        source = converter.GetOutput()
    bounds = source.GetBounds()
    if plane_name in {"ground", "zNormal"}:
        u_axis, v_axis, fixed_axis = 0, 1, 2
    elif plane_name == "xNormal":
        u_axis, v_axis, fixed_axis = 1, 2, 0
    elif plane_name == "yNormal":
        u_axis, v_axis, fixed_axis = 0, 2, 1
    else:
        raise ValueError(f"Unknown pressure plane: {plane_name}")
    u_min, u_max = bounds[2 * u_axis], bounds[2 * u_axis + 1]
    v_min, v_max = bounds[2 * v_axis], bounds[2 * v_axis + 1]
    fixed = (bounds[2 * fixed_axis] + bounds[2 * fixed_axis + 1]) / 2
    requested_spacing = spacing
    width, height, spacing = bounded_plane_grid(
        u_max - u_min, v_max - v_min, requested_spacing, max_pixels
    )
    u_values = u_min + (np.arange(width, dtype=np.float32) + 0.5) * spacing
    v_values = v_min + (np.arange(height, dtype=np.float32) + 0.5) * spacing
    uu, vv = np.meshgrid(u_values, v_values)
    query_points = np.empty((width * height, 3), dtype=np.float32)
    query_points[:, fixed_axis] = fixed
    query_points[:, u_axis] = uu.ravel()
    query_points[:, v_axis] = vv.ravel()
    points = vtk.vtkPoints()
    points.SetData(numpy_to_vtk(query_points, deep=True))
    query = vtk.vtkPolyData()
    query.SetPoints(points)
    probe = vtk.vtkProbeFilter()
    probe.SetInputData(query)
    probe.SetSourceData(source)
    probe.ComputeToleranceOn()
    probe.Update()
    sampled = probe.GetOutput().GetPointData()
    field = sampled.GetArray("overpressure")
    mask_field = sampled.GetArray("vtkValidPointMask")
    if field is None or mask_field is None:
        raise ValueError(f"Cannot resample overpressure from {path}")
    values = vtk_to_numpy(field).astype(np.float32, copy=False) * 0.001
    valid = vtk_to_numpy(mask_field).astype(bool, copy=False) & np.isfinite(values)
    scale = max(high_kpa - low_kpa, 1e-9)
    position = np.clip((values - low_kpa) / scale, 0, 1) * 4
    stops = np.asarray(((24, 84, 170), (55, 200, 239), (255, 229, 101), (251, 130, 58), (212, 40, 67)), dtype=np.float32)
    indexes = np.minimum(3, np.floor(position).astype(np.intp))
    fractions = (position - indexes)[:, None]
    rgb = np.rint(stops[indexes] * (1 - fractions) + stops[indexes + 1] * fractions).astype(np.uint8)
    rgba = np.empty((width * height, 4), dtype=np.uint8)
    rgba[:, :3] = rgb
    rgba[:, 3] = np.where(valid, 235, 0).astype(np.uint8)
    encoded = base64.b64encode(rgba_png(width, height, rgba.reshape(height, width, 4))).decode("ascii")
    origin = [0.0, 0.0, 0.0]
    origin[fixed_axis] = fixed
    origin[u_axis] = u_min
    origin[v_axis] = v_min
    u_vector = [0.0, 0.0, 0.0]
    v_vector = [0.0, 0.0, 0.0]
    u_vector[u_axis] = width * spacing
    v_vector[v_axis] = height * spacing
    return {
        "origin": [round(value, 4) for value in origin],
        "u": [round(value, 4) for value in u_vector],
        "v": [round(value, 4) for value in v_vector],
        "width": width,
        "height": height,
        "cellSize": spacing,
        "requestedCellSize": requested_spacing,
        "adaptive": spacing > requested_spacing * 1.000001,
        "validCells": int(valid.sum()),
        "png": "data:image/png;base64," + encoded,
    }


def nice_ceiling(value):
    if value <= 0:
        return 1
    scale = 10 ** math.floor(math.log10(value))
    for step in (1, 2, 5, 10):
        if value <= step * scale:
            return step * scale
    return 10 * scale


def blast_sources(case):
    """Read all configured charge centres without inventing missing metadata."""
    try:
        payload = json.loads((case / "case-builder.json").read_text(encoding="utf-8"))
        config = payload.get("config", {})
        configured = config.get("sources")
        if isinstance(configured, list) and configured:
            sources = []
            for source in configured:
                centre = [float(value) for value in source["centre"]]
                if len(centre) != 3 or not all(math.isfinite(value) for value in centre):
                    raise ValueError("invalid source centre")
                sources.append(
                    {
                        "centre": centre,
                        "mass": float(source["mass"]),
                        "delay": float(source.get("delay", 0.0)),
                    }
                )
            return sources
        legacy = config.get("charge_centre")
        if isinstance(legacy, (list, tuple)) and len(legacy) == 3:
            return [{"centre": [float(value) for value in legacy], "mass": config.get("charge_mass"), "delay": 0.0}]
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        pass
    text = (case / "constant/phaseProperties").read_text(encoding="utf-8")
    match = re.search(r"\bpoints\s*\((.*?)\)\s*;", text, re.S)
    if not match:
        return []
    points = re.findall(
        r"\(\s*([-+\d.eE]+)\s+([-+\d.eE]+)\s+([-+\d.eE]+)\s*\)",
        match.group(1),
    )
    return [{"centre": [float(value) for value in point], "mass": None, "delay": 0.0} for point in points]


def ambient_pressure(case):
    """Read the case reference pressure used to define overpressure."""
    try:
        payload = json.loads((case / "case-builder.json").read_text(encoding="utf-8"))
        value = float(payload.get("config", {}).get("ambient_pressure"))
        if math.isfinite(value) and value > 0:
            return value
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        pass
    try:
        text = (case / "0/p").read_text(encoding="utf-8")
        match = re.search(r"\binternalField\s+uniform\s+([-+0-9.eE]+)\s*;", text)
        if match:
            value = float(match.group(1))
            if math.isfinite(value) and value > 0:
                return value
    except (OSError, ValueError):
        pass
    return 101298.0


def wave_iso_kpa(case):
    """Return the pContours iso pressure (kPa) written into system/controlDict."""
    try:
        text = (case / "system/controlDict").read_text(encoding="utf-8")
    except OSError:
        return None
    match = re.search(r"pContours\s*\{[^}]*?isoValues\s*\(\s*([-+0-9.eE]+)\s*\)", text, re.S)
    return round(float(match.group(1)) / 1000, 3) if match else None


def result_lineage(case, stl_path):
    """Validate and return the Weapon scenario linkage for this case, if present."""
    scenario_path = case / "weapon-scenario-draft.json"
    geometry_path = case / "weapon-geometry.json"
    georeference_path = case / "weapon-georeference.json"
    paths = (scenario_path, geometry_path, georeference_path)
    present = [path.is_file() for path in paths]
    if not any(present):
        return {}
    if not all(present):
        raise ValueError("Incomplete Weapon scenario lineage in case")

    scenario = json.loads(scenario_path.read_text(encoding="utf-8"))
    geometry = json.loads(geometry_path.read_text(encoding="utf-8"))
    georeference = json.loads(georeference_path.read_text(encoding="utf-8"))
    scenario_geometry = scenario.get("geometry", {})
    records = geometry.get("files", [])
    if (
        scenario.get("schema_version") != 1
        or not isinstance(scenario.get("scenario_id"), str)
        or not scenario["scenario_id"].strip()
        or geometry.get("schema_version") != 1
        or georeference.get("schema_version") != 1
        or not isinstance(records, list)
    ):
        raise ValueError("Invalid Weapon scenario lineage metadata")

    stl_name = Path(scenario_geometry.get("stl", "")).name
    georeference_name = Path(scenario_geometry.get("georeference_manifest", "")).name
    stl_record = next((item for item in records if item.get("name") == stl_name), None)
    georeference_record = next(
        (item for item in records if item.get("name") == georeference_name), None
    )
    if not stl_record or not georeference_record:
        raise ValueError("Weapon geometry manifest does not reference its STL and georeference")

    def digest(path):
        value = hashlib.sha256()
        with path.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                value.update(block)
        return value.hexdigest()

    stl_digest = digest(stl_path)
    georeference_digest = digest(georeference_path)
    if stl_record.get("sha256") != stl_digest:
        raise ValueError("Weapon geometry checksum does not match the case STL")
    if georeference_record.get("sha256") != georeference_digest:
        raise ValueError("Weapon georeference checksum does not match its manifest")

    return {
        "scenario_id": scenario["scenario_id"],
        "geometry_sha256": stl_digest,
        "geometry_manifest_sha256": digest(geometry_path),
        "georeference_sha256": georeference_digest,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--max-frames", type=int, default=48)
    parser.add_argument("--wave-triangles", type=int, default=1600)
    parser.add_argument("--wall-triangles", type=int, default=3000)
    parser.add_argument("--voxel-size", type=float, default=0.1)
    parser.add_argument("--max-model-voxels", type=int, default=6000)
    parser.add_argument("--max-wave-voxels", type=int, default=2500)
    parser.add_argument("--voxel-min-kpa", type=float, default=-50.0)
    parser.add_argument("--voxel-max-kpa", type=float, default=50.0)
    parser.add_argument("--model-label", default="VTK simulation output")
    args = parser.parse_args()
    if (
        args.max_frames < 1 or args.wave_triangles < 100 or args.wall_triangles < 100
        or args.voxel_size <= 0 or args.voxel_min_kpa >= args.voxel_max_kpa
        or args.max_model_voxels < 1 or args.max_wave_voxels < 1
    ):
        parser.error("frame and triangle limits must be positive")
    case = args.case.resolve()
    output = args.output or case / "blast3D.html"
    sources = blast_sources(case)
    charge_centres = [source["centre"] for source in sources]
    charge = (
        [sum(point[axis] for point in charge_centres) / len(charge_centres) for axis in range(3)]
        if charge_centres else None
    )
    ambient_pa = ambient_pressure(case)
    sampled_walls = {
        name: first_series(case, (
            f"postProcessing/wallSurfaces/{name}_walls.vtk.series",
            f"postProcessing/surfaces/{name}_walls.vtk.series",
        ), required=False)
        for name in ("overpressure", "overpressureMax", "T")
    }
    compact_walls = all(sampled_walls.values())
    walls = {} if compact_walls else first_series(case, ("VTK/walls.vtk.series",))
    waves = first_series(case, (
        "postProcessing/blastSurfaces/p_pContours.vtk.series",
        "postProcessing/surfaces/p_pContours.vtk.series",
    ))
    contour_series = {
        name: first_series(case, (
            f"postProcessing/pressureSlices/overpressure_{name}.vtk.series",
            f"postProcessing/surfaces/overpressure_{name}.vtk.series",
        ), required=False)
        for name in ("ground", "xNormal", "yNormal", "zNormal")
    }
    required_times = [set(waves)]
    required_times.extend(set(items) for items in sampled_walls.values()) if compact_walls else required_times.append(set(walls))
    matching_times = sorted(
        t for t in set.intersection(*required_times)
        if t > 0 and waves[t].exists()
    )
    if not matching_times:
        raise ValueError("No matching walls and pContours VTK times were found")
    stride = max(1, math.ceil(len(matching_times) / args.max_frames))
    times = matching_times[::stride]
    if times[-1] != matching_times[-1]:
        times.append(matching_times[-1])
    wall_geometry = None
    wall_centroids = None
    if compact_walls:
        wall_geometry, wall_centroids = reference_surface(
            sampled_walls["overpressure"][times[0]], args.wall_triangles
        )
    frames = []
    skipped = []
    skipped_layers = []
    bounds = [math.inf, -math.inf, math.inf, -math.inf, math.inf, -math.inf]
    for time in times:
        try:
            if compact_walls:
                wall, stats = mapped_wall_fields(
                    {name: sampled_walls[name][time] for name in sampled_walls},
                    wall_centroids,
                )
            else:
                _, wall, source_mesh, source_ids = read_triangles(
                    walls[time], args.wall_triangles, transfer_fields=True
                )
                wall.update(wall_fields(source_mesh, walls[time], source_ids))
                stats = {
                    "op": round(max(wall["op"], default=0), 2),
                    "opMax": round(max(wall["opMax"], default=0), 2),
                    "temp": round(max(wall["temp"], default=0), 2),
                }
            _, wave, source_wave, wave_source_ids = read_triangles(
                waves[time], args.wave_triangles, transfer_fields=True
            )
            wave["op"] = wave_overpressure(
                source_wave, waves[time], ambient_pa, wave_source_ids
            )
            wave_voxels = surface_voxels(wave, args.voxel_size, args.max_wave_voxels)
            voxels = {}
            for name, entries in contour_series.items():
                if time not in entries or not entries[time].exists():
                    continue
                try:
                    voxels[name] = voxel_plane(
                        entries[time], name, args.voxel_size,
                        args.voxel_min_kpa, args.voxel_max_kpa,
                    )
                except ValueError as error:
                    skipped_layers.append((time, name, str(error)))
        except (KeyError, ValueError) as error:
            skipped.append((time, str(error)))
            continue
        mesh_values = [wave]
        if wall_geometry is not None:
            mesh_values.append(wall_geometry)
        else:
            mesh_values.append(wall)
        for mesh_data in mesh_values:
            for x, y, z in mesh_data["points"]:
                bounds[0] = min(bounds[0], x)
                bounds[1] = max(bounds[1], x)
                bounds[2] = min(bounds[2], y)
                bounds[3] = max(bounds[3], y)
                bounds[4] = min(bounds[4], z)
                bounds[5] = max(bounds[5], z)
        stats["waveRadius"] = (
            round(
                max(
                    (min(math.dist(point, centre) for centre in charge_centres) for point in wave["points"]),
                    default=0,
                ),
                2,
            )
            if charge_centres else 0
        )
        stats["waveOpMin"] = round(min(wave["op"], default=0), 2)
        stats["waveOpMax"] = round(max(wave["op"], default=0), 2)
        frames.append({
            "time": time, "wall": wall, "wave": wave,
            "waveVoxels": wave_voxels, "voxels": voxels, "stats": stats,
        })
    if not frames:
        raise ValueError(f"All matching VTK frames were invalid: {skipped[:4]}")
    center = [(bounds[i] + bounds[i + 1]) / 2 for i in (0, 2, 4)]
    radius = max(bounds[i + 1] - bounds[i] for i in (0, 2, 4)) / 2
    wall_reference = wall_geometry if wall_geometry is not None else frames[0]["wall"]
    model_voxels = map_voxels_to_faces(
        surface_voxels(
            stl_geometry(case_stl_path(case)),
            args.voxel_size,
            args.max_model_voxels,
        ),
        wall_reference,
    )
    highest_wall_face = max((cell[3] for cell in model_voxels["cells"]), default=-1)
    for frame in frames:
        for field in ("op", "opMax", "temp"):
            if highest_wall_face >= len(frame["wall"].get(field, [])):
                raise ValueError(f"Model voxel field mapping exceeds wall {field} samples")
    data = {
        "result_schema_version": 1,
        "frames": frames,
        "center": center,
        "radius": max(radius, 1),
        "bounds": bounds,
        "model": args.model_label,
        "waveIsoKPa": wave_iso_kpa(case),
        "ambientPressureKPa": round(ambient_pa * 0.001, 3),
        "blastCenter": charge,
        "blastCenters": charge_centres,
        "blastSources": sources,
        "blastRadius": max(
            5,
            min(
                max(radius, 1),
                max((math.dist(charge, centre) for centre in charge_centres), default=0) + 8,
                30,
            ),
        ),
        "wallGeometry": wall_geometry,
        "modelVoxels": model_voxels,
        "contourRange": [args.voxel_min_kpa, args.voxel_max_kpa],
        "voxelSize": args.voxel_size,
        "ranges": {
            "op": [0, nice_ceiling(max(max(frame["wall"]["op"], default=0) for frame in frames))],
            "opMax": [0, nice_ceiling(max(max(frame["wall"]["opMax"], default=0) for frame in frames))],
            "temp": [min(300, min(min(frame["wall"]["temp"], default=300) for frame in frames)),
                     nice_ceiling(max(max(frame["wall"]["temp"], default=300) for frame in frames))],
        },
    }
    stl_path = case_stl_path(case)
    data.update(result_lineage(case, stl_path))
    template = (Path(__file__).parent / "viewer_template.html").read_text(encoding="utf-8")
    output.write_text(template.replace("__BLAST_DATA__", json.dumps(data, separators=(",", ":"))), encoding="utf-8")
    json_output = output.with_suffix(".json")
    json_output.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    csv_path = output.with_suffix(".surfaceStats.csv")
    with csv_path.open("w", newline="", encoding="utf-8") as destination:
        writer = csv.writer(destination)
        writer.writerow(("time_ms", "wall_overpressure_max_kPa", "wall_peak_max_kPa",
                         "wall_air_temperature_max_K", "wave_radius_m", "display_wave_faces"))
        for frame in frames:
            stats = frame["stats"]
            writer.writerow((round(frame["time"] * 1000, 5), stats["op"], stats["opMax"],
                             stats["temp"], stats["waveRadius"], len(frame["wave"]["faces"])))
    print(f"Wrote {output} and {json_output} ({len(frames)} frames, {output.stat().st_size / 1048576:.1f} MiB HTML)")
    if skipped:
        print(f"Skipped {len(skipped)} invalid VTK frame(s): {skipped[:4]}")
    if skipped_layers:
        print(f"Skipped {len(skipped_layers)} invalid display layer(s): {skipped_layers[:4]}")


if __name__ == "__main__":
    main()
