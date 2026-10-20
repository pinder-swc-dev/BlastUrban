# blastFoam feature integration in BlastUrban

This matrix distinguishes solver capability from what the BlastUrban case
builder can safely configure. A capability is not marked production-ready
until its inputs are validated and written into the generated case manifest.

| blastFoam feature | BlastUrban integration | Current guard |
|---|---|---|
| Arbitrary phases and EOS | Solver supports it; builder currently generates the reviewed two-phase `c4 air` template | New explosive phases remain data-gated until a versioned material registry and validation case exist |
| JWL EOS | Active in the current C4 template | MK-82/MK-84 filler data must not be substituted into the C4 JWL coefficients |
| Constant/linear/Miller afterburn | Runtime models and tutorial examples are retained in the repository | Not exposed by the Weapon workflow until a complete, reviewed coefficient set is supplied |
| Tutorials and validation cases | Retained as authoritative syntax/examples | They are references, not automatic proof for a different material/case |
| AMR | Generated through `adaptiveFvMesh`; interval, level and cell cap are configurable | Cell cap must exceed the base mesh; convergence remains the operator's responsibility |
| Single/multi-point detonation | Active; up to 16 sources with independent mass, centre and delay | Charge resolution, domain containment and overlap are validated |
| 1st–4th order time integration | UI/API supports `RK1SSP`, `RK2SSP`, `RK3SSP`, `RK4SSP` | Default remains the accepted `RK2SSP` |
| 2nd/3rd order spatial reconstruction | UI/API supports accepted van-Albada second order and tutorial-proven `quadraticMUSCL Minmod` third order | Default remains second order; a changed scheme requires convergence testing |
| Shock flux schemes | UI/API supports `Tadmor`, `Kurganov`, `HLLC`, `AUSM+` | Only runtime names compiled in this source tree are accepted; default remains `Tadmor` |
| MPI | Active through generated `decomposeParDict` and `mpirun` workflow | Rank count is validated and must match allocated server cores |
| OpenFOAM mesh/pre/post tools | Existing preflight/Allrun/Web export pipeline uses standard utilities | Server image readiness verifies each required executable before submission |

## Generated-case contract

The numerical choices are stored in `case-builder.json` and rendered into
`system/fvSchemes`. This makes a result auditable and prevents the UI from
claiming a higher-order method while the case still uses template defaults.

Supported fields:

```json
{
  "flux_scheme": "Tadmor",
  "time_integrator": "RK2SSP",
  "spatial_order": 2,
  "dynamic_levels": 2,
  "refine_interval": 5,
  "mpi": 10
}
```

Changing a numerical scheme creates a new case; generated cases are never
silently rewritten. Performance profiles control resource/cadence defaults,
while numerical choices remain explicit and independently recorded.

## Material/afterburn gate

The current builder may adjust C4 mass, position, delay and loaded density but
does not replace the complete reactant/product EOS, thermodynamics, activation
and afterburn parameter set. Enabling Tritonal, H6 or PBXN-109 therefore needs:

1. a versioned material schema containing a cohesive parameter set;
2. unit/convention conversion tests;
3. generated-dictionary regression tests;
4. free-field validation for peak pressure, impulse and arrival time; and
5. explicit scientific approval and provenance.

The required evidence is listed in the root document
`docs/MK82_MK84_CFD_DATA_CHECKLIST.md`.
