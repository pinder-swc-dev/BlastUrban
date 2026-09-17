#!/usr/bin/env python3
"""Build an offline 3D preview of the repaired town STL inside the blockMesh domain."""

import argparse
import json
import re
from pathlib import Path

import vtk


def domain_from_blockmesh(path):
    text = re.sub(r"//[^\n]*", "", path.read_text(encoding="utf-8"))
    section = re.search(r"vertices\s*\((.*?)\);", text, re.S)
    if not section:
        raise ValueError(f"No vertices in {path}")
    number = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
    vertices = [tuple(map(float, groups)) for groups in re.findall(rf"\(\s*({number})\s+({number})\s+({number})\s*\)", section.group(1))]
    if len(vertices) != 8:
        raise ValueError(f"Expected 8 block vertices; found {len(vertices)}")
    return [min(v[0] for v in vertices), max(v[0] for v in vertices),
            min(v[1] for v in vertices), max(v[1] for v in vertices),
            min(v[2] for v in vertices), max(v[2] for v in vertices)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    case = args.case.resolve()
    path = case / "constant/triSurface/townBuildings.stl"
    reader = vtk.vtkSTLReader()
    reader.SetFileName(str(path))
    reader.Update()
    mesh = reader.GetOutput()
    points = [[round(x, 3) for x in mesh.GetPoint(i)] for i in range(mesh.GetNumberOfPoints())]
    faces = [[mesh.GetCell(i).GetPointId(j) for j in range(3)] for i in range(mesh.GetNumberOfCells())]
    if not faces:
        raise ValueError(f"No faces in {path}")
    domain = domain_from_blockmesh(case / "system/blockMeshDict")
    for point in points:
        if any(point[axis] < domain[axis * 2] - 0.01 or point[axis] > domain[axis * 2 + 1] + 0.01 for axis in range(3)):
            raise ValueError("Town geometry lies outside the blockMesh domain")
    wall = {"points": points, "faces": faces, "op": [0] * len(faces), "opMax": [0] * len(faces), "temp": [300] * len(faces)}
    center = [(domain[i] + domain[i + 1]) / 2 for i in (0, 2, 4)]
    radius = max(domain[i + 1] - domain[i] for i in (0, 2, 4)) / 2
    data = {"frames": [{"time": 0, "wall": wall, "wave": {"points": [], "faces": []}}],
            "center": center, "radius": radius, "bounds": domain, "domain": domain,
            "model": "townBuildings STL | Domain preview (ยังไม่ใช่ผลระเบิด)", "preview": True}
    template = (Path(__file__).parent / "viewer_template.html").read_text(encoding="utf-8")
    output = args.output or case / "townMeshPreview.html"
    output.write_text(template.replace("__BLAST_DATA__", json.dumps(data, separators=(",", ":"))), encoding="utf-8")
    print(f"Wrote {output}: {len(points)} vertices, {len(faces)} faces; domain {domain}")


if __name__ == "__main__":
    main()
