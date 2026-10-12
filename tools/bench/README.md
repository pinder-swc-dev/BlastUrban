# BlastUrban orchestration benchmarks

These benchmarks measure control-plane overhead only. They do not call
`blockMesh`, `snappyHexMesh`, `setRefinedFields`, `blastFoam`, or any timestep.

SSH connection setup versus a reused ControlMaster connection:

```bash
python3 tools/bench/benchmark_ssh.py \
  --host SERVER --user USER --key ~/.ssh/blasturban_ed25519 --iterations 6
```

The tool runs only remote `true`, closes its own master connection, and prints
JSON timings. Disable connection reuse in the Web UI backend with
`BLASTURBAN_SSH_MULTIPLEX=0`.

Image readiness caching is enabled by default and keyed by immutable image ID
plus platform. Set `BLASTURBAN_IMAGE_READY_CACHE=0` to disable it. Benchmarking
the miss path starts a throwaway Docker container and therefore requires prior
approval for that exact container lifecycle on a shared server.

The full guarded backend smoke fixture is `smoke_webui.py`. It hard-codes the
approved 2026-10-02 job names and refuses to run unless
`--cleanup-confirmed` is supplied. All generated result pages contain
`SMOKE TEST — NOT CFD`; the script must not be generalized to arbitrary server
paths or used without a new deletion approval.

Server address, user, key, job root and image are required command-line
arguments so deployment-specific values are not stored in the repository.
