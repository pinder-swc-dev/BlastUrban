# ADR 0005: Bounded surface-voxel display

## Context

The CFD result viewer displayed STL walls and the pressure iso-surface as
triangles. Cartesian pressure slices already used 0.1 m display cells, but that
did not make the three-dimensional building or wave shell appear voxelized.
Exporting every 0.1 m box for a large town or every time frame can exceed a
browser's practical memory and Canvas rendering budget.

## Decision

The result adapter quantizes the repaired STL and each calculated pressure
iso-surface into a Cartesian **surface** voxel shell. Model cells map to the
nearest sampled wall face for calculated colour fields. Wave cells reference
their original iso-surface face and therefore its calculated overpressure.

The requested display size is 0.1 m. The exporter raises the effective size
when required to keep at most 6,000 model cells and 2,500 wave cells per frame,
and records both requested and effective sizes. The viewer reports those values
and defaults to voxel rendering while retaining triangle rendering as a
diagnostic fallback.

## Alternatives considered

- Change the OpenFOAM mesh to uniform 0.1 m hexahedra: rejected because it
  changes numerics, greatly increases resources, and stair-steps STL boundaries.
- Fill every voxel inside each building: rejected because only the visible
  boundary is needed and filling would increase payload without CFD meaning.
- Smooth the triangle mesh: rejected as the requested representation is a box
  grid and smoothing can imply unsupported geometric precision.

## Consequences

Voxel size is display resolution, not CFD resolution. Large geometry uses
adaptive display LOD, so the effective cell size may exceed 0.1 m. Browser work
is bounded, while all positions and colours remain derived from STL or solver
output. Scientific accuracy remains governed by the solver mesh and requires
the usual mesh-convergence checks.

## Affected systems

- `tutorials/blastFoam/building3DWorkshop/visualization/exportBlast3D.py`
- `tutorials/blastFoam/building3DWorkshop/visualization/viewer_template.html`
- `tools/blast_case_ui/assets/makeWebResults.sh`
