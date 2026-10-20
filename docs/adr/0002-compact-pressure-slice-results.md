# ADR 0002: Compact pressure-slice results

Status: accepted; default cadence and raw-field retention superseded in part by ADR 0003.

## Context

The original workflow wrote 500 full decomposed snapshots, 24 sampled
field/surface combinations, and a second `blastToVTK` ground/wall series. A
measured completed case occupied roughly 174 GiB including recovery artifacts.
The browser displayed walls and one pressure iso-surface but ignored the
already calculated ground and X/Y/Z cutting planes.

## Decision

- Keep blastFoam timestep, Courant control, mesh adaptation and physical models
  unchanged.
- Change the default output interval from `2.5e-5` to `1e-4` seconds (125
  snapshots for the default 12.5 ms case); users may lower it for denser output.
- Split sampled outputs into wall fields, one pressure iso-surface, and
  overpressure-only ground/cutting planes, written as binary VTK.
- Consume those solver-written surfaces directly and stop generating a
  duplicate ground/wall VTK series in `Allrun`.
- Share static wall geometry across web frames and render buildings solid by
  default. Resample the calculated ground/X/Y/Z pressure surfaces onto 0.1 m
  Cartesian display cells, encode them as nearest-neighbour PNG textures, and
  decode only the selected frame in the browser. Limit export to 48 frames and
  500,000 display cells per plane. If 0.1 m exceeds that cap, enlarge display
  spacing adaptively instead of failing the complete frame.

## Consequences

Storage and post-processing work are substantially lower by construction, but
the exact full-case reduction must be measured on the next completed run. The
default animation has one quarter of the previous temporal samples; this is an
output-resolution tradeoff, not a change to solver accuracy. The standalone
HTML remains an interim contract; the target architecture still uses versioned
binary assets and a result manifest.

The Cartesian cells are explicitly visualization samples. They do not replace
the body-fitted/adaptive OpenFOAM mesh, and values outside the encoded default
colour range of -50 to 50 kPa are colour-clamped without changing raw CFD data.

## Alternatives

- Gzip all OpenFOAM fields: rejected as the representative velocity field only
  shrank 6.4% with gzip level 1 while consuming additional CPU.
- Delete processor fields automatically after export: rejected because it is
  destructive, prevents restart/debug workflows, and requires explicit user
  approval under the project deletion policy.
- Smooth or fabricate a propagating geometry: rejected because visualization
  must be derived from calculated pressure fields.
