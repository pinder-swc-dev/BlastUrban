# Repaired town case

The previous `building3DWorkshopTest` setting used `towntest.stl` at `scale 1`
inside a 10 x 10 x 5 m Domain. The STL spans about 70 x 75 x 34 m, so that
Domain included only a small corner of the model. `surfaceCheck` also found
open and multiply connected edges because the STL combines streets with
buildings. The new `townBuildings.stl` keeps roofs, walls, and building base
caps but lets the `ground` patch represent the streets. It has 424 triangles,
29 closed parts, and bounds (1.12, 2.33, 0) to (69.26, 73.51, 34.15) m.

| Setting | New value | File |
| --- | --- | --- |
| Domain | (-20, -20, 0) to (90, 95, 55) m | `system/blockMeshDict` |
| Base mesh | 55 x 58 x 28 = 89,320 cells, about 2 m spacing | `system/blockMeshDict` |
| Building mesh | `townBuildings.stl`, scale 1, snap on, surface level 2-3 | `system/snappyHexMeshDict` |
| Fluid keep point | (35, 20, 1) m, on the open street | `system/snappyHexMeshDict` |
| Charge | 10 kg C4 at (35, 20, 1) m, charge refinement level 5 | `system/setFieldsDict`, `constant/phaseProperties` |
| Solver time | 0 to 12.5 ms, initial `deltaT` 50 ns, `maxCo` 0.3, `maxDeltaT` 250 ns | `system/controlDict` |
| Saved results | full fields and surfaces every 25 microseconds | `system/controlDict` |
| Surface fields | `p`, `overpressure`, `overpressureMax`, `T` on ground and walls | `system/controlDict` |

The preflight mesh was generated in an isolated `/tmp` case, not over the old
results. `snappyHexMesh` finished at 489,713 cells and ordinary `checkMesh`
reported `Mesh OK` with three 3D boundary patches; the walls patch had 123,476
faces. `setRefinedFields` at charge level 5 selected 28 charge cells and set
0.00668981 cubic metres of C4, or about 10.71 kg at 1601 kg/m3. `checkMesh`
after charge refinement was also OK. A serial `blastFoam` smoke run completed
to 1 microsecond without a fatal error. The more exhaustive
`checkMesh -allGeometry -allTopology` check flagged 32,612 concave polyhedral
cells, so watch Courant number and mesh-quality diagnostics during the full
run. The short run cannot establish stability over 12.5 ms.

A previous validation run produced a 489,776-cell four-process mesh and passed
ordinary `checkMesh`. Its runtime output and checkpoint are intentionally not
stored in Git. Run `sh prepareTownRun.sh` to stage a fresh `townRun`, then use
its `Allrun` script on the calculation server. Full town simulation and
25-microsecond result writing may require substantial compute time and storage.

## Town result case

`townDemo` uses the same repaired STL, 110 x 115 x 55 m Domain, base mesh,
wall patch and 10 kg C4 physics. The calculation point moved to (35, 23, 1)
m, 1.25 m from the nearest building surface, so the wave reaches the imported
buildings within the 2.5 ms result interval. The 1 m backup charge sphere
does not intersect the STL. The mesh uses feature level 1 and wall surface
levels 1-2 rather than 2-3, leaving 214,422 cells after snappy and 45,076
wall faces after charge setup. The level-5 charge occupies 31 cells and
0.00614652 m3, or about 9.84 kg at 1601 kg/m3. `checkMesh` reports `Mesh OK`.

The `townDemo` `controlDict` saves full fields and the `ground`, `walls`, and
110 kPa `pContours` surfaces every 25 microseconds in a 0-2.5 ms simulation.
It uses binary full-field writes, `maxCo 0.3`, and `maxDeltaT 3 us`; adaptive
mesh refinement runs every 5 steps with an 800,000-cell cap. These settings
reduce runtime while retaining smaller time steps than the old L_Wall run,
whose log shows about 6.25 us steps and a 6,138-cell mesh.

`visualization/exportTownBlast3D.py` reads the calculated
`postProcessing/surfaces/*_walls.vtk.series` and
`p_pContours.vtk.series` directly. It splits each triangle of the repaired
STL twice for display (424 to 6,784 faces), then paints each displayed face
from its nearest CFD wall-patch cell. This preserves the imported building
shape and catches smaller blast footprints than one color per raw STL
triangle. The viewer also lists the exact maxima across all CFD wall-patch
faces at each time; color on the display mesh is sampled and can miss a local
peak. Its blue wave is the 110 kPa pressure isosurface, and `T` is the
fluid-side temperature at the wall, not heat inside solid building material.
The exporter also writes `blast3D.surfaceStats.csv` with exact wall-patch
maxima and the farthest point of the 110 kPa isosurface from the charge.

In the previous validation run, the four-process `townDemo` solver completed
to 2.5 ms without a fatal error. Generated results are not included in Git.
Its final Courant maximum was 0.149, below the configured 0.3 cap, and
`checkMesh -parallel -latestTime` reported `Mesh OK` at 2.5 ms with 45,106
wall faces. The viewer contains all 100 calculated frames from 0.025 to
2.5 ms. Across the full CFD wall patch, instantaneous overpressure reached
1,394.52 kPa at 0.9 ms, cumulative peak reached 1,394.76 kPa, and the
fluid-side wall temperature reached 1,742.27 K at 0.425 ms. The 110 kPa
isosurface extended 4.94 m from the charge at 2.5 ms. Some interior volume
cells underwent strong transient rarefaction around 2.3 ms, although the
solver remained positive and the final wall VTK arrays were finite. Treat
these as demonstration results until mesh/time-step convergence and the
material/charge assumptions are validated for engineering use.

For a different STL, first check its actual units and bounds with
`surfaceCheck`. Adjust `scale` in `snappyHexMeshDict` only when source STL
units differ from case metres. Ensure `blockMeshDict` covers the model with
room for the propagating wave. Repair open or multiply connected edges, or
split street ground from building solids as `prepareTownSTL.py` does here.
Then update `surfaceFeaturesDict`, the STL filename and wall refinement in
`snappyHexMeshDict`, and put `locationInMesh` in the fluid. Set the physical
charge centre and radius in `setFieldsDict`, initiation point in
`phaseProperties`, and nearby sample planes and probes in `controlDict`.
Check `checkMesh` for a non-empty `walls` patch and inspect the wall-field VTK
series before exporting the viewer.
