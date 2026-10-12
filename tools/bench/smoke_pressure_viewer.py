#!/usr/bin/env python3
"""Exercise the pressure-slice viewer with synthetic VTK; this is not CFD."""

from __future__ import annotations

import argparse
import base64
import json
import re
import struct
import subprocess
import tempfile
from pathlib import Path

import vtk


MARKER = "SMOKE TEST — NOT CFD / ไม่ใช่ผล CFD"
TIMES = (0.0001, 0.0002)
FACES = ((0, 1, 2), (0, 2, 3))


def write_poly(path: Path, points, name: str, values, point_data: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    poly = vtk.vtkPolyData()
    vtk_points = vtk.vtkPoints()
    for point in points:
        vtk_points.InsertNextPoint(*point)
    cells = vtk.vtkCellArray()
    for ids in FACES:
        triangle = vtk.vtkTriangle()
        for index, value in enumerate(ids):
            triangle.GetPointIds().SetId(index, value)
        cells.InsertNextCell(triangle)
    poly.SetPoints(vtk_points)
    poly.SetPolys(cells)
    array = vtk.vtkFloatArray()
    array.SetName(name)
    for value in values:
        array.InsertNextValue(value)
    (poly.GetPointData() if point_data else poly.GetCellData()).AddArray(array)
    writer = vtk.vtkPolyDataWriter()
    writer.SetFileName(str(path))
    writer.SetInputData(poly)
    writer.SetFileTypeToASCII()
    if not writer.Write():
        raise RuntimeError(f"Cannot write {path}")


def build_fixture(case: Path) -> None:
    (case / "constant").mkdir(parents=True)
    (case / "system").mkdir()
    (case / "constant/phaseProperties").write_text("points (((0 0 0)));\n")
    (case / "system/controlDict").write_text("pContours { isoValues (110000); }\n")
    wall = ((0, 0, 0), (1, 0, 0), (1, 1, 1), (0, 1, 1))
    ground = ((-2, -2, 0), (2, -2, 0), (2, 2, 0), (-2, 2, 0))
    layers = {
        "ground": ground,
        "xNormal": ((0, -2, -2), (0, 2, -2), (0, 2, 2), (0, -2, 2)),
        "yNormal": ((-2, 0, -2), (2, 0, -2), (2, 0, 2), (-2, 0, 2)),
        "zNormal": ground,
    }
    roots = {
        "wall": case / "postProcessing/wallSurfaces",
        "blast": case / "postProcessing/blastSurfaces",
        "slice": case / "postProcessing/pressureSlices",
    }
    entries = {}
    for frame, time_value in enumerate(TIMES, 1):
        folder = f"{time_value:g}"
        for name, base in (("overpressure", 10000), ("overpressureMax", 15000), ("T", 300)):
            filename = f"{name}_walls.vtk"
            write_poly(roots["wall"] / folder / filename, wall, name, (base + frame * 100, base + frame * 200))
            entries.setdefault((roots["wall"], filename), []).append({"name": f"{folder}/{filename}", "time": time_value})
        filename = "p_pContours.vtk"
        write_poly(roots["blast"] / folder / filename, ground, "p", (110000, 110000))
        entries.setdefault((roots["blast"], filename), []).append({"name": f"{folder}/{filename}", "time": time_value})
        for layer, points in layers.items():
            filename = f"overpressure_{layer}.vtk"
            write_poly(
                roots["slice"] / folder / filename, points, "overpressure",
                (-5000 + frame * 1000, 12000 + frame * 1000, -4000, 8000), True,
            )
            entries.setdefault((roots["slice"], filename), []).append({"name": f"{folder}/{filename}", "time": time_value})
    for (root, filename), items in entries.items():
        (root / f"{filename}.series").write_text(json.dumps({"file-series-version": "1.0", "files": items}))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exporter", type=Path, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="blasturban-viewer-smoke-") as directory:
        case = Path(directory) / "case"
        build_fixture(case)
        output = Path(directory) / "blast3D.html"
        subprocess.run(
            ["/usr/bin/python3", str(args.exporter), "--case", str(case), "--output", str(output),
             "--model-label", MARKER],
            check=True,
        )
        text = output.read_text(encoding="utf-8")
        match = re.search(r"const data = (.*);\ndocument", text)
        if match is None:
            raise RuntimeError("Viewer data was not embedded")
        data = json.loads(match.group(1))
        assert data["model"] == MARKER
        assert len(data["frames"]) == 2
        assert data["wallGeometry"]["faces"]
        assert data["ambientPressureKPa"] == 101.298
        assert data["frames"][0]["wave"]["op"] == [8.7, 8.7]
        assert set(data["frames"][0]["voxels"]) == {"ground", "xNormal", "yNormal", "zNormal"}
        ground = data["frames"][0]["voxels"]["ground"]
        assert ground["cellSize"] == 0.1
        assert ground["validCells"] > 0
        assert ground["png"].startswith("data:image/png;base64,")
        png = base64.b64decode(ground["png"].split(",", 1)[1])
        assert png.startswith(b"\x89PNG\r\n\x1a\n")
        assert struct.unpack(">II", png[16:24]) == (ground["width"], ground["height"])
        print("VISUALIZATION_SMOKE=PASS")
        print("SMOKE TEST — NOT CFD / ไม่ใช่ผล CFD")
        print(f"HTML_BYTES={output.stat().st_size}")
        print(f"GROUND_GRID={ground['width']}x{ground['height']} @ {ground['cellSize']}m")


if __name__ == "__main__":
    main()
