# BlastUrban CFD audit

Status: static audit. The authoring workstation (macOS) has no OpenFOAM and no
running Docker daemon, so **nothing in this audit was compiled or solver-run**.
Evidence is from reading files, running the Python unit tests, and `git`.

## Execution pipeline (traced)

UI (`tools/blast_case_ui/web`) → local controller (`blast_case_web.py`) →
`blast_case_builder.py` renders a case from `tutorials/blastFoam/building3DWorkshop`
→ SSH/rsync → `server-docker-job.sh` → container (OpenFOAM 9 + blastFoam) →
`Allrun`: surfaceCheck, surfaceFeatures, blockMesh, decomposePar, snappyHexMesh,
addEmptyPatch, setRefinedFields, `blastFoam`, blastToVTK, calculateImpulse →
`makeWebResults.sh` / `exportBlast3D.py` → `blast3D.html`, CSV.

## Solver dependencies

OpenFOAM Foundation 9 (Ubuntu 22.04 worker image), blastFoam built from `src/`
and `applications/` (vendored upstream; `git diff HEAD -- src applications/solvers`
is empty, and `src/` last changed in the import commit, so it matches the vendored
upstream at that commit). Solver in use: `blastFoam` (two-phase `c4`/`air`).

## Effective numerics of the shipped template

| Item | Value | File |
|---|---|---|
| Flux scheme | Tadmor (builder allows HLLC, AUSM+, Kurganov, Tadmor) | `system/fvSchemes` |
| Time integrator | RK2SSP (builder allows RK1–RK4SSP) | `system/fvSchemes` |
| Reconstruction | vanAlbada (3rd order option: quadraticMUSCL Minmod) | `system/fvSchemes` |
| Time step | adjustable, maxCo 0.3, maxDeltaT 2.5e-7 | `system/controlDict` |
| AMR | `adaptiveFvMesh`, `densityGradient`, maxRefinement 2, maxCells 2e6, balance 0.15 | `constant/dynamicMeshDict` |
| Decomposition | scotch, 4 subdomains (builder overrides to match cores) | `system/decomposeParDict` |

Flux scheme runtime names in `src/` match the builder allow-list
(`Tadmor`, `Kurganov`, `HLLC`, `AUSM+` are `TypeName`s; `AUSM+up`, `HLL`, `HLLCP`, `Roe` also exist).

## Classification

| Class | Paths |
|---|---|
| PROTECTED | `tools/blast_case_ui/web/**`, `blast_case_web.py`, `test_blast_case_web.py`, `assets/**` (job runner, entrypoint), `Dockerfile*`, `tools/blast_case_ui/Dockerfile.*`, `.github/**`, `.remote.env.example`, `tools/bench/**`, `BlastUrbanUI.command`, `debian/**`, `tutorials/.../visualization/**` (result-viewer contract) |
| CFD_MODIFIABLE | `validation/blastUrbanCFD/**` (new, isolated); `docs/BLASTURBAN_CFD_*.md` (new) |
| SHARED_READ_ONLY | `src/**`, `applications/**` (upstream-vendored, no defect established); `tutorials/blastFoam/building3DWorkshop/{system,constant,0}` (template consumed by the builder, output fields/names are a contract; the C4/JWL `phaseProperties` is also out of scope by the task's weapon-model exclusion); `case-builder.json` schema; `Allrun` |
| UNKNOWN_REQUIRES_REVIEW | `tools/blast_case_ui/blast_case_builder.py` (writes the CFD dictionaries but is also the API-facing config schema, so ownership is shared); `docs/*` pre-existing |

No file in the UNKNOWN class was edited.

## Existing tests

- `tools/blast_case_ui/test_*.py`: 60 Python tests (builder 14, web 38, VTK source 8). Builder + VTK-source suites run on this host: 22 tests OK. Web tests not run (not CFD-owned).
- `validation/blastFoam/*`: upstream benchmark cases (Sod, double Mach, Sedov, Woodward–Colella, 2D Riemann...) with digitized references. No automated pass/fail; plots only.
- `applications/test/Test-*`: upstream utility tests.
- No test compares serial vs MPI, checks conservation, or checks AMR.

## I/O contracts recorded (must not change)

Fields `p, T, U, rho.*, alpha.c4, overpressure, overpressureMax, impulse`;
surfaces `ground, walls, pContours, x/y/zNormal` as `vtkTimeSeries`; write interval
2.5e-5 s; `case-builder.json` keys (`flux_scheme`, `time_integrator`, `spatial_order`,
`dynamic_levels`, `refine_interval`, `mpi`, ...); `server-job-status.json`.

## Observations needing a solver run to resolve (not defects)

1. Sod case: `T 0.56` in `setFieldsDict` vs. `R = 8314.47/11640.3 ≈ 0.714`, `Cv=1.78575` (γ=1.4) implies `T = p/(ρR) = 1.4`. Probably unused because blastFoam derives T from (p, ρ), but unconfirmed.
2. Template uses `solver diagonal` for all fields (correct for explicit Godunov-type solver; no issue).
3. `unrefineLevel == lowerRefineLevel == 0.1` in `dynamicMeshDict`: zero hysteresis may cause refine/unrefine flicker. Needs an AMR run to judge; the file is template-owned (SHARED_READ_ONLY) so no change was made.
