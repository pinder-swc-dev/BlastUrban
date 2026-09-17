#!/usr/bin/env python3
"""Extract closed buildings from the town STL, leaving the street as the ground patch."""

import argparse
from collections import Counter, defaultdict
from pathlib import Path

import vtk


def inside_xy(point, triangle, mesh):
    x, y = point
    a, b, c = [mesh.GetPoint(i) for i in triangle]
    denominator = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
    if abs(denominator) < 1e-9:
        return False
    u = ((b[1] - c[1]) * (x - c[0]) + (c[0] - b[0]) * (y - c[1])) / denominator
    v = ((c[1] - a[1]) * (x - c[0]) + (a[0] - c[0]) * (y - c[1])) / denominator
    return u >= -1e-6 and v >= -1e-6 and u + v <= 1 + 1e-6


def edges_for(faces, selected):
    incident = defaultdict(list)
    for i in selected:
        face = faces[i]
        for j in range(3):
            incident[tuple(sorted((face[j], face[(j + 1) % 3])))].append(i)
    return incident


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    case = Path(__file__).resolve().parent.parent
    parser.add_argument("--input", type=Path, default=case / "constant/triSurface/towntest.stl")
    parser.add_argument("--output", type=Path, default=case / "constant/triSurface/townBuildings.stl")
    args = parser.parse_args()

    reader = vtk.vtkSTLReader()
    reader.SetFileName(str(args.input))
    reader.Update()
    mesh = reader.GetOutput()
    faces = [tuple(mesh.GetCell(i).GetPointId(j) for j in range(3)) for i in range(mesh.GetNumberOfCells())]
    if not faces:
        raise ValueError("Input STL has no triangles")

    ground, roofs, walls = [], [], []
    for i, face in enumerate(faces):
        z = [mesh.GetPoint(j)[2] for j in face]
        if max(abs(value) for value in z) < 1e-5:
            ground.append(i)
        elif max(z) - min(z) < 1e-5:
            roofs.append(i)
        else:
            walls.append(i)

    bottoms = set()
    for i in ground:
        vertices = [mesh.GetPoint(j) for j in faces[i]]
        centroid = (sum(p[0] for p in vertices) / 3, sum(p[1] for p in vertices) / 3)
        if any(inside_xy(centroid, faces[j], mesh) for j in roofs):
            bottoms.add(i)

    # Two street triangles overlap roof footprints at their centroids but
    # leave open edges. Remove any such bottom triangles by edge topology.
    pruned = 0
    while True:
        incident = edges_for(faces, bottoms | set(roofs) | set(walls))
        dangling = {i for ids in incident.values() if len(ids) == 1 for i in ids if i in bottoms}
        if not dangling:
            break
        bottoms -= dangling
        pruned += len(dangling)

    selected = bottoms | set(roofs) | set(walls)
    counts = Counter(len(ids) for ids in edges_for(faces, selected).values())
    if set(counts) != {2}:
        raise ValueError(f"Buildings are not manifold after extraction: {dict(counts)}")

    polygons = vtk.vtkCellArray()
    for i in sorted(selected):
        triangle = vtk.vtkTriangle()
        for j, point_id in enumerate(faces[i]):
            triangle.GetPointIds().SetId(j, point_id)
        polygons.InsertNextCell(triangle)
    output = vtk.vtkPolyData()
    output.SetPoints(mesh.GetPoints())
    output.SetPolys(polygons)
    normals = vtk.vtkPolyDataNormals()
    normals.SetInputData(output)
    normals.ConsistencyOn()
    normals.AutoOrientNormalsOn()
    normals.SplittingOff()
    normals.Update()
    writer = vtk.vtkSTLWriter()
    writer.SetFileName(str(args.output))
    writer.SetInputConnection(normals.GetOutputPort())
    writer.SetFileTypeToBinary()
    if not writer.Write():
        raise IOError(f"Could not write {args.output}")
    print(f"Wrote {args.output}: {len(selected)} closed building triangles; removed {len(ground)-len(bottoms)} street triangles ({pruned} dangling)")


if __name__ == "__main__":
    main()
