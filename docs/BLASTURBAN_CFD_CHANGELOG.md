# BlastUrban CFD changelog

## 2026-10-13

Added (all new files, no existing file modified by this work):

- `validation/blastUrbanCFD/cfd_verify.py`: ASCII-field reader, finite/positive checks, conservation totals, L1 error, observed order, exact ideal-gas Sod solution.
- `validation/blastUrbanCFD/test_cfd_verify.py`: 8 unit tests.
- `validation/blastUrbanCFD/run_sod_convergence.sh`: copies the upstream Sod case to a new directory and runs N=125/250/500/1000 for a chosen flux scheme/integrator. Refuses to reuse an output directory.
- `validation/blastUrbanCFD/analyze_sod.py`: L1 errors, orders, PASS/FAIL.
- `docs/BLASTURBAN_CFD_{AUDIT,FEATURE_MATRIX,CHANGELOG,VERIFICATION}.md`.

Not changed, deliberately: `src/`, `applications/`, the building3DWorkshop template,
`blast_case_builder.py`, and everything PROTECTED. No CFD defect was verified, so
per the task rules no solver or numerical-scheme source was altered.
No reverts were needed.
