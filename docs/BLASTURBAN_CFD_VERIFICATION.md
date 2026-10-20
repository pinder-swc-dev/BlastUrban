# BlastUrban CFD verification

## Executed

| Check | Command | Result |
|---|---|---|
| Verification helpers | `cd validation/blastUrbanCFD && python3 -m unittest -v` | 8 tests OK (exact Sod star state p*=0.30313, u*=0.92745 vs Toro table; Rankine–Hugoniot across the shock; mass conservation of the exact profile; parser; order formula) |
| Existing builder/VTK-source tests | `cd tools/blast_case_ui && python3 -m unittest test_blast_case_builder test_blast_to_vtk_source` | 22 tests OK (run before any change; nothing in those files changed) |
| Protected files unchanged | SHA-256 of 22 protected files before vs. after | see "Protected-file evidence" |
| `src/`, `applications/solvers` unchanged | `git diff --quiet HEAD -- src applications/solvers` | clean |

## NOT executed (no OpenFOAM / Docker daemon on this host)

Compilation of any component; Sod run and convergence orders; temporal
convergence; mass/momentum/energy conservation of a solver run; mesh quality
(`checkMesh`); AMR conservation; serial-vs-MPI comparison; memory/timing;
ParaView/VTK readability of real output. **No result for these is claimed.**

To run on the Ubuntu worker:

```bash
source /opt/openfoam9/etc/bashrc; source /opt/blastfoam/etc/bashrc
cd validation/blastUrbanCFD
./run_sod_convergence.sh /tmp/sod_hllc HLLC "RK3SSP 4" 12   # use a fresh directory
python3 analyze_sod.py /tmp/sod_hllc 12
```

Run this for each of HLLC, AUSM+, Kurganov, Tadmor and each integrator before
comparing schemes. Caveats: the analyzer assumes `raw` sample files with columns
`x p rho Ux Uy Uz`, and aborts if the layout differs. The 0.5 minimum observed
order is a loose sanity bound, not a published rate. The Sod `T 0.56` question
(audit obs. 1) should be checked from the first run's log.

## Protected-file evidence

Baseline hashes were recorded before work began. After the work they are re-checked below.

Result: all 22 protected files hash-identical to the baseline (22 OK, 0 changed).
Note that the git working tree already held many uncommitted user modifications
before this work started; they were left as they were.
