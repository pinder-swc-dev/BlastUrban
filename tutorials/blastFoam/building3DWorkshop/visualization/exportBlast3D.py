#!/usr/bin/env python3
"""Build a self-contained 3D time viewer from blastFoam VTK surface series."""

import argparse
import csv
import json
import math
import re
from pathlib import Path

import vtk


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


def nice_ceiling(value):
    if value <= 0:
        return 1
    scale = 10 ** math.floor(math.log10(value))
    for step in (1, 2, 5, 10):
        if value <= step * scale:
            return step * scale
    return 10 * scale


def blast_centre(case):
    text = (case / "constant/phaseProperties").read_text(encoding="utf-8")
    match = re.search(r"\bpoints\s+\(\(([-+\d.eE]+)\s+([-+\d.eE]+)\s+([-+\d.eE]+)\)\)", text)
    return [float(value) for value in match.groups()] if match else None


def wave_iso_kpa(case):
    """Return the pContours iso pressure (kPa) written into system/controlDict."""
    try:
        text = (case / "system/controlDict").read_text(encoding="utf-8")
    except OSError:
        return None
    match = re.search(r"pContours\s*\{[^}]*?isoValues\s*\(\s*([-+0-9.eE]+)\s*\)", text, re.S)
    return round(float(match.group(1)) / 1000, 3) if match else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--max-frames", type=int, default=96)
    parser.add_argument("--wave-triangles", type=int, default=2500)
    parser.add_argument("--wall-triangles", type=int, default=6000)
    parser.add_argument("--model-label", default="VTK simulation output")
    args = parser.parse_args()
    if args.max_frames < 1 or args.wave_triangles < 100 or args.wall_triangles < 100:
        parser.error("frame and triangle limits must be positive")
    case = args.case.resolve()
    output = args.output or case / "blast3D.html"
    charge = blast_centre(case)
    walls = series(case, "VTK/walls.vtk.series")
    waves = series(case, "postProcessing/surfaces/p_pContours.vtk.series")
    matching_times = sorted(
        t for t in walls.keys() & waves.keys()
        if t > 0 and walls[t].exists() and waves[t].exists()
    )
    if not matching_times:
        raise ValueError("No matching walls and pContours VTK times were found")
    stride = max(1, math.ceil(len(matching_times) / args.max_frames))
    times = matching_times[::stride]
    if times[-1] != matching_times[-1]:
        times.append(matching_times[-1])
    frames = []
    skipped = []
    bounds = [math.inf, -math.inf, math.inf, -math.inf, math.inf, -math.inf]
    for time in times:
        try:
            _, wall, source_mesh, source_ids = read_triangles(walls[time], args.wall_triangles, transfer_fields=True)
            wall.update(wall_fields(source_mesh, walls[time], source_ids))
            _, wave, _, _ = read_triangles(waves[time], args.wave_triangles)
        except ValueError:
            skipped.append(time)
            continue
        for mesh_data in (wall, wave):
            for x, y, z in mesh_data["points"]:
                bounds[0] = min(bounds[0], x)
                bounds[1] = max(bounds[1], x)
                bounds[2] = min(bounds[2], y)
                bounds[3] = max(bounds[3], y)
                bounds[4] = min(bounds[4], z)
                bounds[5] = max(bounds[5], z)
        stats = {
            "op": round(max(wall["op"], default=0), 2),
            "opMax": round(max(wall["opMax"], default=0), 2),
            "temp": round(max(wall["temp"], default=0), 2),
            "waveRadius": round(max((math.dist(point, charge) for point in wave["points"]), default=0), 2)
            if charge else 0,
        }
        frames.append({"time": time, "wall": wall, "wave": wave, "stats": stats})
    if not frames:
        raise ValueError("All matching VTK frames were invalid")
    center = [(bounds[i] + bounds[i + 1]) / 2 for i in (0, 2, 4)]
    radius = max(bounds[i + 1] - bounds[i] for i in (0, 2, 4)) / 2
    data = {
        "frames": frames,
        "center": center,
        "radius": max(radius, 1),
        "bounds": bounds,
        "model": args.model_label,
        "waveIsoKPa": wave_iso_kpa(case),
        "blastCenter": charge,
        "blastRadius": max(5, min(max(radius, 1), 18)),
        "ranges": {
            "op": [0, nice_ceiling(max(max(frame["wall"]["op"], default=0) for frame in frames))],
            "opMax": [0, nice_ceiling(max(max(frame["wall"]["opMax"], default=0) for frame in frames))],
            "temp": [min(300, min(min(frame["wall"]["temp"], default=300) for frame in frames)),
                     nice_ceiling(max(max(frame["wall"]["temp"], default=300) for frame in frames))],
        },
    }
    template = (Path(__file__).parent / "viewer_template.html").read_text(encoding="utf-8")
    output.write_text(template.replace("__BLAST_DATA__", json.dumps(data, separators=(",", ":"))), encoding="utf-8")
    csv_path = output.with_suffix(".surfaceStats.csv")
    with csv_path.open("w", newline="", encoding="utf-8") as destination:
        writer = csv.writer(destination)
        writer.writerow(("time_ms", "wall_overpressure_max_kPa", "wall_peak_max_kPa",
                         "wall_air_temperature_max_K", "wave_radius_m", "display_wave_faces"))
        for frame in frames:
            stats = frame["stats"]
            writer.writerow((round(frame["time"] * 1000, 5), stats["op"], stats["opMax"],
                             stats["temp"], stats["waveRadius"], len(frame["wave"]["faces"])))
    print(f"Wrote {output} ({len(frames)} frames, {output.stat().st_size / 1048576:.1f} MiB)")
    if skipped:
        print(f"Skipped {len(skipped)} invalid VTK frame(s): {', '.join(str(t) for t in skipped)}")


if __name__ == "__main__":
    main()
