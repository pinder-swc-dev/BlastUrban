# BlastUrban CFD feature matrix

"Installed solver support" means present in the vendored `src/` tree. It has
**not** been confirmed by compiling, since no OpenFOAM was available.
Status values: IMPLEMENTED, PARTIAL, MISSING, UNSUPPORTED, VERIFIED, BLOCKED.
Nothing is VERIFIED against a solver run in this session.
Upstream reference: https://github.com/synthetik-technologies/blastfoam

| Feature | Existing BlastUrban use | Installed source support | Gap / defect | Proposed CFD-only change | Files affected | Integration risk | Status | Evidence |
|---|---|---|---|---|---|---|---|---|
| Multiphase + ideal-gas EOS | air phase, two-phase template | `specie/equationOfStates`, `twoPhase/multiphaseFluidBlastThermo` | none found | none | – | – | IMPLEMENTED | source present; no run |
| Specialized EOS / activation / afterburn (inventory only) | C4 JWL in template (not modified) | JWL, tabulated, Arrhenius/linear/pressure/programmed activation, constant/linear/Miller afterburn | out of scope (task excludes energetic-material work) | none | – | – | IMPLEMENTED (upstream), not touched | directory listing |
| Sod shock tube | upstream case in `validation/blastFoam/Sod_shockTube` | – | plots only, no pass/fail | exact solver + analyzer | `validation/blastUrbanCFD/*` | none (new files) | PARTIAL | exact solver unit tests pass (8/8); solver run **not executed** |
| Acoustic pulse, pressure-wave reflection, conservation test | missing | – | no case | not created: a case I cannot run would be unverified | – | – | MISSING | – |
| Mesh convergence | missing as automated test | – | – | `run_sod_convergence.sh` (N=125…1000) | `validation/blastUrbanCFD/*` | none | PARTIAL | script `bash -n` only |
| AMR | `adaptiveFvMesh` + `densityGradient`, levels/cap configurable | `dynamicFvMesh/*`, `errorEstimators/*` (Lohner, delta, scaledDelta, fieldValue also present) | possible zero hysteresis (audit obs. 3); conservation after remap untested | needs AMR run before any change | `constant/dynamicMeshDict` (SHARED_READ_ONLY) | medium | PARTIAL | – |
| Time integration RK1–RK4 | builder allow-list RK1–RK4SSP | Euler, RK1SSP, RK2, RK2SSP, RK3SSP, RK4, RK4SSP, RKF45 | temporal-convergence test missing | study via runner script | – | none | PARTIAL | dir listing |
| Spatial 2nd/3rd order | vanAlbada; quadraticMUSCL option | `reconstruction/{linear,quadratic,upwind}MUSCL` | no convergence evidence | study via runner | – | none | PARTIAL | – |
| Flux schemes HLLC/AUSM+/Kurganov/Tadmor | all four allowed by builder | all four present, `TypeName`s match builder strings | no correctness defect established; no benchmark comparison done | compare in Sod study | – | none | PARTIAL | grep of `TypeName` |
| MPI | `decomposePar` + `mpirun`, scotch | OpenFOAM standard + `fvMeshBalance` | no serial-vs-parallel test | needs server run | – | none | PARTIAL | – |
| OpenFOAM utilities compatibility | Allrun uses blockMesh, snappyHexMesh, decomposePar, … | OpenFOAM 9 | not testable here | none | – | – | UNSUPPORTED to verify locally | no OpenFOAM on host |
| Output compatibility | fields/VTK series listed in audit | – | none altered | none | – | – | IMPLEMENTED (unchanged) | protected hashes identical |

## Blocked items

- Any solver compile/run, mesh-quality, AMR conservation, MPI and ParaView checks: BLOCKED on a host with OpenFOAM 9 + blastFoam (Ubuntu worker image or the Docker daemon, which is not running here).
- Changing `dynamicMeshDict`/`fvSchemes` defaults: BLOCKED by SHARED_READ_ONLY classification and by the rule that numerical changes need convergence evidence.
