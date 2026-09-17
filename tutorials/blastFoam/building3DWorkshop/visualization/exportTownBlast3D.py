#!/usr/bin/env python3
"""Export real town wall and blast-wave sampled surfaces to an offline 3D viewer."""

import argparse
import csv
import json
import math
import re
from pathlib import Path

import vtk

from exportBlast3D import read_triangles, series


def read_polydata(path):
    reader = vtk.vtkPolyDataReader()
    reader.SetFileName(str(path))
    reader.Update()
    mesh = reader.GetOutput()
    if not mesh.GetNumberOfCells():
        raise ValueError(f"Empty sampled wall surface: {path}")
    return mesh


def model_surface(path, subdivisions):
    reader = vtk.vtkSTLReader()
    reader.SetFileName(str(path))
    reader.Update()
    subdivide = vtk.vtkLinearSubdivisionFilter()
    subdivide.SetInputConnection(reader.GetOutputPort())
    subdivide.SetNumberOfSubdivisions(subdivisions)
    subdivide.Update()
    mesh = subdivide.GetOutput()
    if not mesh.GetNumberOfCells():
        raise ValueError(f"Empty town STL: {path}")
    points = [[round(x, 3) for x in mesh.GetPoint(i)] for i in range(mesh.GetNumberOfPoints())]
    faces = [[mesh.GetCell(i).GetPointId(j) for j in range(3)] for i in range(mesh.GetNumberOfCells())]
    centroids = []
    for ids in faces:
        centroids.append(tuple(sum(mesh.GetPoint(i)[axis] for i in ids) / 3 for axis in range(3)))
    return {"points": points, "faces": faces}, centroids


def mapped_fields(paths, centroids):
    surfaces = {name: read_polydata(path) for name, path in paths.items()}
    reference = surfaces["overpressure"]
    n_cells = reference.GetNumberOfCells()
    for name, mesh in surfaces.items():
        if mesh.GetNumberOfCells() != n_cells:
            raise ValueError(f"Wall surface geometry differs for {name}: {paths[name]}")
    centers = vtk.vtkCellCenters()
    centers.SetInputData(reference)
    centers.Update()
    locator = vtk.vtkStaticPointLocator()
    locator.SetDataSet(centers.GetOutput())
    locator.BuildLocator()
    ids = [locator.FindClosestPoint(point) for point in centroids]
    result = {}
    stats = {}
    for source, target, factor in (
        ("overpressure", "op", 0.001),
        ("overpressureMax", "opMax", 0.001),
        ("T", "temp", 1),
    ):
        field = surfaces[source].GetCellData().GetArray(source)
        if field is None:
            raise ValueError(f"Missing cell field {source}: {paths[source]}")
        stats[target] = round(field.GetRange()[1] * factor, 2)
        fallback = 300 if source == "T" else 0
        values = []
        for i in ids:
            value = field.GetTuple1(i) * factor
            values.append(round(value if math.isfinite(value) else fallback, 2))
        result[target] = values
    return result, stats


def nice_ceiling(value):
    if value <= 0:
        return 1
    scale = 10 ** math.floor(math.log10(value))
    for step in (1, 2, 5, 10):
        if value <= step * scale:
            return step * scale
    return 10 * scale


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", type=Path, default=Path(__file__).resolve().parent.parent / "townRun")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--max-frames", type=int, default=128)
    parser.add_argument("--wave-triangles", type=int, default=2500)
    parser.add_argument("--subdivisions", type=int, default=2,
                        help="Split each original STL triangle for finer wall-field display")
    args = parser.parse_args()
    if args.max_frames < 1 or args.wave_triangles < 100 or args.subdivisions not in range(4):
        parser.error("frame and triangle limits must be positive")
    case = args.case.resolve()
    output = args.output or case / "blast3D.html"
    phase_text = (case / "constant/phaseProperties").read_text(encoding="utf-8")
    match = re.search(r"\bpoints\s+\(\(([-+\d.eE]+)\s+([-+\d.eE]+)\s+([-+\d.eE]+)\)\)", phase_text)
    if match is None:
        raise ValueError("Cannot find blast initiation point in phaseProperties")
    charge = [float(value) for value in match.groups()]
    wall, centroids = model_surface(case / "constant/triSurface/townBuildings.stl", args.subdivisions)
    sampled = {
        name: series(case, f"postProcessing/surfaces/{name}_walls.vtk.series")
        for name in ("overpressure", "overpressureMax", "T")
    }
    waves = series(case, "postProcessing/surfaces/p_pContours.vtk.series")
    times = sorted(set.intersection(*(set(items) for items in (*sampled.values(), waves))))
    times = [t for t in times if t > 0 and all(sampled[name][t].exists() for name in sampled)]
    if not times:
        raise ValueError("No matching calculated wall and blast-wave frames")
    stride = max(1, math.ceil(len(times) / args.max_frames))
    selected = times[::stride]
    if selected[-1] != times[-1]:
        selected.append(times[-1])
    frames = []
    skipped = []
    for time in selected:
        try:
            fields, stats = mapped_fields({name: sampled[name][time] for name in sampled}, centroids)
            if waves[time].exists():
                try:
                    _, wave, full_wave, _ = read_triangles(waves[time], args.wave_triangles)
                    stats["waveRadius"] = round(max(
                        math.dist(full_wave.GetPoint(i), charge)
                        for i in range(full_wave.GetNumberOfPoints())), 2)
                except ValueError:
                    wave = {"points": [], "faces": []}
                    stats["waveRadius"] = 0
            else:
                wave = {"points": [], "faces": []}
                stats["waveRadius"] = 0
        except ValueError as error:
            skipped.append((time, str(error)))
            continue
        frames.append({"time": time, "wall": {**wall, **fields}, "wave": wave, "stats": stats})
    if not frames:
        raise ValueError("All calculated frames were invalid")
    points = wall["points"]
    bounds = [min(p[i] for p in points) if j % 2 == 0 else max(p[i] for p in points)
              for i in range(3) for j in range(2)]
    center = [(bounds[i] + bounds[i + 1]) / 2 for i in (0, 2, 4)]
    radius = max(bounds[i + 1] - bounds[i] for i in (0, 2, 4)) / 2
    data = {
        "frames": frames, "center": center, "radius": radius, "bounds": bounds,
        "model": "townBuildings.stl · calculated blastFoam fields",
        "blastCenter": [charge[0], charge[1], charge[2] + 5], "blastRadius": 18,
        "ranges": {
            "op": [0, nice_ceiling(max(max(f["wall"]["op"]) for f in frames))],
            "opMax": [0, nice_ceiling(max(max(f["wall"]["opMax"]) for f in frames))],
            "temp": [300, nice_ceiling(max(max(f["wall"]["temp"]) for f in frames))],
        },
    }
    template = (Path(__file__).parent / "viewer_template.html").read_text(encoding="utf-8")
    output.write_text(template.replace("__BLAST_DATA__", json.dumps(data, separators=(",", ":"))), encoding="utf-8")
    csv_path = output.with_suffix(".surfaceStats.csv")
    with csv_path.open("w", newline="", encoding="utf-8") as destination:
        writer = csv.writer(destination)
        writer.writerow(("time_ms", "wall_overpressure_max_kPa", "wall_peak_max_kPa",
                         "wall_air_temperature_max_K", "wave_110kPa_radius_m", "display_wave_faces"))
        for frame in frames:
            stats = frame["stats"]
            writer.writerow((round(frame["time"] * 1000, 5), stats["op"], stats["opMax"],
                             stats["temp"], stats["waveRadius"], len(frame["wave"]["faces"])))
    print(f"Wrote {output} ({len(frames)} calculated frames, {output.stat().st_size / 1048576:.1f} MiB)")
    if skipped:
        print(f"Skipped {len(skipped)} invalid frame(s): {skipped[:4]}")


if __name__ == "__main__":
    main()
