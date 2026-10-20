# ADR 0004: Multiple discrete C4 sources

## Context

The localhost case builder previously exposed one C4 centre and mass. blastFoam
already reads lists of detonation `points`, `delays`, and optional radii, while
`setRefinedFields` can initialize more than one discrete explosive region. A UI
that only duplicated detonation points would be scientifically wrong because it
would not create explosive mass at the additional locations.

## Decision

The internal scenario contract accepts a `sources` list. Every item contains a
three-dimensional `centre` in metres, a C4 `mass` in kilograms, and a
non-negative `delay` in seconds. All sources currently share the C4 material,
density, and refinement level.

The builder writes one `sphericalMassToCell` region per source and writes
matching `points` and `delays` lists in `phaseProperties`. It rejects empty or
non-finite values, delays outside the simulated interval, sources outside the
domain or intersecting the building surface, and overlapping charge spheres.
The localhost UI caps a scenario at 16 sources. Historical clients and cases
remain compatible through the existing single `charge_centre` and
`charge_mass` fields, which normalize to one effective source.

Result export records every configured centre. Source markers and focus choices
are setup metadata; they are not labelled as CFD fields. Pressure geometry and
colour continue to come only from calculated VTK data.

## Alternatives considered

- Multiple initiation points inside one charge: supported by blastFoam but does
  not represent separate user-specified masses.
- One phase per source: allows different explosives, but substantially expands
  thermodynamic configuration and is not needed for the current all-C4 scope.
- Combine masses into one equivalent sphere: loses position and wave-interaction
  behaviour and was rejected.

## Consequences

Case generation, validation, preview, manifests, result metadata, and local case
summaries understand multiple sources. Mesh and solver cost can rise around
every charge. Simultaneous and delayed activation are structurally supported,
but quantitative engineering use still requires mesh-convergence and a
scientific regression against an approved multi-charge reference case.

## Affected systems

- `tools/blast_case_ui/blast_case_builder.py`
- `tools/blast_case_ui/blast_case_web.py`
- `tools/blast_case_ui/web/index.html`
- `tutorials/blastFoam/building3DWorkshop/visualization/`
