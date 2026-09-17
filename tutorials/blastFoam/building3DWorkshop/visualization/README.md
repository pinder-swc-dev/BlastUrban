# 3D town and blast viewers

`towntest.stl` mixes buildings and street-ground triangles, producing open and
multiply connected edges. `prepareTownSTL.py` extracts the 29 closed building
parts into `constant/triSurface/townBuildings.stl`. Keep the original STL as
the source. Rebuild the repaired model and its Domain preview with:

```bash
python3 visualization/prepareTownSTL.py
python3 visualization/exportTownPreview.py
```

Open `townMeshPreview.html` to inspect the gray town surface with edges inside
the yellow `blockMesh` Domain. The generated preview is ignored by Git and has
no simulated pressure or temperature fields.

This repository does not include calculated fields or HTML viewers. Run
`townDemo` or prepare a fresh `townRun`, then export the calculated wall and
blast-wave VTK results with:

```bash
cd townDemo
python3 ../visualization/exportTownBlast3D.py --case .
```

The resulting `townDemo/blast3D.html` is a standalone offline 3D time viewer;
`blast3D.surfaceStats.csv` lists exact wall-patch maxima and 110 kPa wave
extent at each displayed time.
Use `paraFoam -builtin` from the case directory to open the decomposed
calculation in ParaView; select the `walls` patch, choose `Surface With Edges`, and color by
`overpressure`, `overpressureMax`, or `T` at the saved times.
Use `sh prepareTownRun.sh anotherName` to stage another fresh run; the script
refuses to replace an existing case directory.
Switch between blast-area and whole-town camera views, rotate by dragging,
zoom with the wheel, play time, and switch wall coloring
between instantaneous overpressure, peak overpressure, and air temperature
near the wall. `Surface with Edges` is enabled for the building and blast-wave
surfaces; each can be switched independently. Color ranges are editable.

The town exporter needs Python VTK (`python3-vtk`) and matching
`postProcessing/surfaces/overpressure_walls.vtk.series`,
`overpressureMax_walls.vtk.series`, `T_walls.vtk.series`, and
`p_pContours.vtk.series`. It samples at most 128 frames, splits the original
STL triangles twice for display, and maps each display triangle to a CFD
wall-patch face. The viewer lists exact maxima over the full wall patch in
addition to the sampled display colors. Simulation data retain the full mesh
and 25-microsecond output frequency. Use `--max-frames`, `--subdivisions`, or
`--wave-triangles` to adjust viewer size; invalid frames are skipped. The
existing `exportBlast3D.py` remains the exporter for the old L_Wall VTK
layout. The blue isosurface visualizes a pressure level, not smoke;
temperature is the fluid-side boundary value, not temperature inside the
solid wall.
