# Project audit: 3D Urban Blast Effect Simulator

Audit date: 2026-09-22
Scope: repository structure, local WebUI, case generation, remote execution,
OpenFOAM/blastFoam integration, result processing, security, performance, and
development governance.

This is a repository audit, not proof of CFD accuracy or production readiness.
Items under **Current** are implemented. Items under **Target** or
**Recommendation** are proposals.

## Executive assessment

BlastUrban already provides a useful trusted engineering workflow: it can
inspect and repair STL geometry, generate a three-dimensional OpenFOAM 9 case,
submit it over SSH, run blastFoam in a resource-limited Docker container, and
convert selected VTK surfaces into a standalone HTML viewer.

It is not yet the external-client platform described in the target design. The
present Python server is a localhost administration monolith, the client-side
tool generates and transfers executable cases, jobs have no durable database or
queue, and the result viewer loads one embedded JSON payload rather than a
versioned, progressively loaded scientific dataset.

The correct next step is contract and architecture stabilization—not a new CFD
solver and not a wholesale rewrite.

## 1. Repository structure

| Path | Current responsibility |
| --- | --- |
| `applications/` | blastFoam solvers, utilities, and tests |
| `src/` | blastFoam/OpenFOAM libraries and physical/numerical models |
| `etc/` | BlastUrban runtime environment and code templates |
| `tutorials/blastFoam/building3DWorkshop/` | urban reference case, STL, dictionaries, scripts, visualization |
| `tools/blast_case_ui/` | desktop/browser case builder, local controller, tests, worker assets |
| `docs/` | Thai installation, usage, development, and remote-operation guides |
| `.github/workflows/` | package build and OpenFOAM validation/tutorial workflows |
| `Dockerfile` | Debian-package-based blastFoam runtime image |
| `~/BlastUrbanWorkspace/` | external user temp files, generated cases, and downloaded results |

The repository mixes upstream solver source, application-specific tutorial
content, and a newer local/remote orchestration prototype. These are identifiable
but not yet packaged as independent services.

## 2. Current architecture

```text
Browser on Mac
  -> localhost HTML/JavaScript UI
  -> Python ThreadingHTTPServer
  -> STL validation/repair + case generation
  -> SSH/rsync
  -> Ubuntu host systemd user unit
  -> ephemeral Docker worker with /case bind mount
  -> OpenFOAM 9 + blastFoam
  -> VTK/Python post-processing
  -> results-web rsync back to Mac
```

Detailed current and target maps are in [`../ARCHITECTURE.md`](../ARCHITECTURE.md).

Strengths worth preserving:

- UI binds to `127.0.0.1`, not the LAN;
- generated cases do not overwrite existing local directories;
- job directories are isolated;
- SSH values are passed as quoted positional arguments;
- remote deletion resolves and validates the exact path;
- status JSON uses atomic replacement;
- worker containers have CPU, memory, PID, and shared-memory limits;
- systemd lets jobs survive SSH disconnection;
- the client fetches compact web results rather than the full OpenFOAM case.

## 3. Existing frontend

The frontend is a single Thai HTML/JavaScript application in
`tools/blast_case_ui/web/index.html`. It supports:

- STL upload, scale, inspection, limited hole repair, and automatic domain/mesh settings;
- a rotatable setup preview showing model, domain grid, source, probes, and planes;
- source/surface collision checks and resource estimates;
- case export;
- SSH server and Docker readiness tests;
- job submission, polling, log retrieval, cancellation, cleanup, and result display.

The setup preview is a Canvas 2D projection of geometry and configuration. It
is useful for placement but is not CFD output. The UI correctly needs to keep
that distinction visible.

Gaps:

- no authenticated user/session or job ownership;
- no durable job dashboard across browsers/machines;
- progress is not divided into mesh, initialization, solver, and exporter stages;
- no live simulation time, elapsed time, CPU/RAM telemetry, or warning stream;
- server administration and normal simulation submission share the same UI;
- the current viewer is an iframe containing a self-contained returned HTML file.

## 4. Existing backend

`tools/blast_case_ui/blast_case_web.py` is a dependency-free local adapter based
on `ThreadingHTTPServer`. It combines static file serving, uploads, STL actions,
case validation/export, SSH provisioning, Docker image administration, job
control, logs, result transfer, and cleanup.

This is appropriate for a localhost prototype but not a public service because
there is no:

- FastAPI/Pydantic contract layer;
- authentication, authorization, or tenant/job ownership;
- database, migrations, or idempotency;
- rate limiting, upload concurrency policy, or API observability;
- durable event stream or WebSocket/SSE status channel;
- separation between application endpoints and infrastructure administration.

The handler converts broad exceptions to HTTP 400, so clients cannot reliably
distinguish validation, conflict, unavailable worker, or internal failure.

## 5. Docker configuration

Current execution uses a host-controlled `docker run --rm` with a per-job bind
mount and systemd user unit. This is directionally correct.

Important gaps and inconsistencies:

- root `Dockerfile` is based on Ubuntu 20.04 while the stated worker target is Ubuntu 22.04;
- the current workflow can mutate a running container with `apt-get` and save it
  using `docker commit`, which is not reproducible;
- image selection uses tags rather than a recorded immutable digest;
- the compute worker runs as UID 0 because blastFoam is stored below `/root`;
- no `cap-drop`, `no-new-privileges`, read-only root filesystem, explicit
  seccomp/AppArmor policy, network disablement, wall-clock timeout, or disk quota;
- there is no global concurrency limit, so multiple submissions can race for
  the same CPU and RAM;
- the Docker smoke check does not establish numerical validity.

Critical runtime finding: the root worker invokes MPI but currently does not
pass `OMPI_ALLOW_RUN_AS_ROOT=1` and `OMPI_ALLOW_RUN_AS_ROOT_CONFIRM=1`.
Standard OpenMPI commonly aborts in this situation. This is a likely cause of
the recent generic compute failure, but it must be confirmed from the stored
systemd/solver log. The durable fix is a non-root worker image installed outside
`/root`; permitting root MPI should only be an interim compatibility measure.

## 6. OpenFOAM/blastFoam integration

The project targets OpenFOAM Foundation 9 and reuses blastFoam rather than
creating a new solver. The builder generates:

- `blockMeshDict`, `snappyHexMeshDict`, and surface feature extraction;
- MPI decomposition;
- dynamic refinement controls;
- spherical explosive initialization and blastFoam phase properties;
- ambient pressure, adaptive timestep, Courant limit, probes, surfaces, and iso-surface output;
- preflight, mesh, initialization, solver, VTK, and impulse commands.

Implemented validation includes STL topology, finite coordinates, scale,
domain containment, source collision, charge resolution, probe containment,
time controls, cell limits, and rough RAM/disk estimates.

Scientific gaps:

- the UI allows arbitrary explosive density while the generator keeps the C4
  JWL constants, detonation energy, detonation velocity, and heat capacity;
  changing density alone does not define a validated explosive material. The
  current generated user case was observed with `2500 kg/m³` against the C4
  parameter set. Production input should select a locked, versioned material
  preset or provide a complete expert-reviewed parameter set;
- ambient pressure can change while the template's ambient temperature,
  density, and some phase-reference values remain fixed, so the initial
  thermodynamic state may become inconsistent;
- no formal verification that repaired geometry remains physically intended;
- no automated mesh-quality gate with structured thresholds and error codes;
- source initialization can warn when discretized mass differs from requested
  mass, but the pipeline does not parse that warning into an acceptance gate;
- probes are checked against the domain but not solid occupancy, and OpenFOAM
  may silently adjust a requested probe location;
- automatic domain padding is geometric and does not check shock/acoustic
  travel to the boundary before `endTime`; the outer conditions are not a
  documented non-reflecting blast boundary;
- no regression linking generated urban cases to accepted blast metrics;
- estimates are heuristics, not measured models calibrated by mesh/solver benchmarks;
- exposed parameters are effectively C4-specific even though a generic
  `explosive_equivalent.type` appears in the target example;
- probe output currently focuses on pressure and does not expose all target
  histories/metrics;
- arrival time, positive impulse, velocity, Mach, and density are not all
  available in the current web result contract.

Never label a case as physically validated merely because generation or unit
tests pass.

## 7. Job handling

Current state is stored in each case directory as `server-job-status.json`.
The principal states are:

```text
queued  running  postprocessing  complete
failed  viewer_failed  stopped  not_submitted  not_found
```

There is no central queue, immutable UUID, ownership, transition history,
worker lease, heartbeat, retry attempt, or reconciliation after host restart.
The single `running` stage covers preflight, meshing, initialization, and the
solver, so a failed job cannot be classified without reading logs.

Each submission immediately creates a systemd unit. Automatic CPU selection is
a point-in-time load estimate and can race with another simultaneous submit.
Start production scheduling with `max_concurrent_simulations = 1`.

## 8. Current simulation input format

`CaseConfig` is a Python dataclass and the generated `case-builder.json` uses
`schema_version: 1`. Inputs cover geometry scale, domain, mesh/refinement caps,
source position/mass/density, probes, plane point, time controls, ambient
pressure, iso-pressure, MPI ranks, and output mode.

This is a solid seed for a scenario schema, but the transport currently mirrors
HTML field names and the server receives a complete generated case. The target
must use a versioned declarative scenario with explicit SI units, typed warning
codes, output requests, and provenance. The server—not an external client—must
materialize OpenFOAM dictionaries and scripts from trusted templates.

## 9. Current result format

The current pipeline produces selected VTK wall/wave surfaces, a standalone
`blast3D.html`, and a surface statistics CSV. It preserves actual physical time
in frames and distinguishes calculated results from the geometry-only preview.

Gaps:

- no versioned `manifest.json`;
- geometry and all frames are embedded as JSON in one HTML file;
- no GLB/glTF or compressed binary field representation;
- no lazy loading, range requests, cache keys, or independent frame API;
- no standardized provenance, coordinate system, units metadata, image digest,
  config hash, decimation metadata, or checksum verification;
- probe histories and several engineering metrics are absent from the web package.

Two current correctness issues need priority review:

- wall maxima and CSV statistics are currently computed from the decimated
  display sample in the generic exporter, not guaranteed from every source
  wall cell; the viewer/documentation must not call them exact patch maxima;
- the viewer labels the pressure contour as `110 kPa` even though the iso value
  is configurable and represents absolute pressure. With the default ambient
  `101298 Pa`, an absolute `110000 Pa` contour is about `8.702 kPa`
  overpressure, not `110 kPa` overpressure.

The pressure iso-surface can also be legitimately empty or absent for some
frames. That should make the wave layer optional rather than fail an otherwise
valid CFD result export.

## 10. Current 3D visualization

The result viewer uses actual VTK-derived wall fields and pressure iso-surface
geometry. It supports physical-time playback, field selection, surface/edge
modes, camera rotation/zoom, and editable color ranges.

It is a CPU Canvas renderer rather than WebGL/Three.js. Geometry is decimated
and frame count is capped, but the browser still parses the whole payload at
startup. This will not scale to large city meshes, multiple fields, long time
series, slicing, or volume rendering.

The next viewer must consume validated scientific assets and support LOD,
progressive frame loading, stable units/color maps, probe charts, surface
metrics, and layers whose physical derivation is documented.

## 11. Existing `AGENTS.md`

The previous file contained useful generic engineering and UI rules but did not
map ownership to this repository or distinguish the trusted SSH prototype from
the production target. It has been updated with:

- orchestrator, specialist, model, and skill routing;
- repository ownership boundaries;
- scientific/security invariants;
- cross-review rules;
- canonical target lifecycle;
- verification and ADR policy.

## 12. Existing skills

No repository-owned `SKILL.md` files are present; `.agents/` and `.codex/` are
empty. The active development environment exposes only general Codex/plugin
skills, not dedicated OpenFOAM, FastAPI, Docker-security, or scientific-viewer
skill packages. Agents must not pretend the desired skill list is installed.

Repository-specific skills may be added later after stable workflows and
contracts exist. Until then, route by logical specialist responsibility and
inspect primary code/documentation directly.

## 13. Missing components

Production-critical missing components are:

1. versioned public scenario/API schemas;
2. FastAPI gateway and authentication/authorization;
3. persistent job database and state transition history;
4. durable queue and single-concurrency worker policy;
5. server-side trusted case materialization;
6. immutable Ubuntu 22.04 worker image and image provenance;
7. non-root hardened worker;
8. structured stage/progress/error extraction;
9. versioned web-result manifest and binary asset pipeline;
10. WebGL viewer with progressive loading;
11. probe/metric APIs;
12. threat model, retention/quota policy, audit log, and recovery plan;
13. end-to-end, failure-injection, performance, and scientific regression tests;
14. formal API, CFD pipeline, deployment, security, and visualization documents.

## 14. Architectural risks

- `blast_case_web.py` is a large cross-layer monolith and will become harder to
  secure or test if public API features are added directly.
- case generation on the client makes the worker execute transferred scripts;
- filesystem-only job state cannot support reliable retries or multi-user ownership;
- no queue/admission control allows oversubscription;
- image mutation and tags make runs difficult to reproduce;
- two runner paths (`server-docker-job.sh` and `server-run-auto.sh`) risk divergent behavior;
- post-processing failures are currently summarized as “needs Python VTK” even
  when the actual cause may be missing fields/series, an empty iso-surface,
  invalid data, or memory exhaustion;
- local admin workflow and future public workflow could be confused without an explicit boundary.

## 15. Security risks

The localhost server has no authentication and exposes powerful SSH/Docker
administration endpoints. It must remain loopback-only. A compromised returned
HTML viewer is currently served from the same origin and loaded in an iframe
without a sandbox; such content could call privileged local endpoints.

Other high-priority risks:

- a public caller could submit a local path containing modified scripts;
- SSH user membership in the Docker group is effectively root-equivalent;
- `StrictHostKeyChecking=accept-new` trusts the first connection;
- no tenant boundary, rate limit, upload quota, result authorization, or audit trail;
- 8 GiB local uploads plus unbounded request threads are unsuitable for public exposure;
- root worker and broad writable mount increase impact of a compromised case/tool;
- downloaded result integrity is not verified against a trusted manifest.

## 16. Performance risks

- no global job concurrency or admission control;
- resource estimates are uncalibrated and disk space is checked only coarsely;
- whole-directory rsync is workable on LAN but not an application result protocol;
- embedded JSON HTML requires full download and parse before first render;
- Canvas triangle sorting is CPU-bound and lacks GPU LOD/streaming;
- STL analysis, preview sampling, and large uploads run within a threaded local process;
- no output quota, frame budget policy, or automatic raw-result retention tier;
- no benchmark suite for mesh size, wall time, peak memory, result size, or viewer FPS.

## 17. Recommended development order

1. Preserve the current path as a **trusted localhost admin tool** and diagnose
   the active OpenMPI/root failure from its stored log.
2. Approve architecture/trust boundaries and record ADRs for job model, queue,
   worker, results, ingress, and retention.
3. Define versioned scenario, validation, job-state, error, and result-manifest contracts.
4. Extract deterministic case generation behind a transport-neutral interface.
5. Add persistent job metadata and explicit stage transitions before adding FastAPI.
6. Introduce FastAPI, authentication, ownership, upload limits, and read-only
   status/log/result endpoints.
7. Add a durable queue and host worker controller with one concurrent job,
   cancellation, timeout, heartbeat, restart reconciliation, and quotas.
8. Build an immutable Ubuntu 22.04, OpenFOAM 9, blastFoam, VTK worker image;
   move runtime outside `/root` and run non-root.
9. Move all case/script generation to the trusted server boundary.
10. Define and implement the web-result manifest, binary/GLB assets, probes,
    metrics, provenance, and progressive delivery.
11. Build the WebGL scientific viewer against that contract.
12. Add security hardening, failure injection, benchmark gates, and scientific
    regression evidence before public deployment.

## Validation performed for this audit

- repository and documentation inventory;
- source inspection of the local HTTP routes and validation/case builder;
- inspection of Docker/systemd/SSH/rsync worker paths;
- inspection of OpenFOAM dictionaries and generated workflow;
- inspection of VTK export and viewer implementation;
- inspection of Python unit tests and GitHub OpenFOAM validation workflow.

No production FastAPI service, queue, database, or multi-user deployment was
found. No full urban CFD run was executed as part of this documentation audit.

## Job lifecycle audit — 2026-09-30

Scope: `server-docker-job.sh`, readiness checks and status reporting in
`blast_case_web.py`. Verified against a Colima Ubuntu VM (systemd 255, Docker,
image `local/blastfoam9:web`, linux/amd64 emulated on aarch64) using a guarded
smoke fixture. No mesh or solver step was run, so no CFD claim follows from it.

| # | Risk | Result | Fix |
| --- | --- | --- | --- |
| 1 | `bash -lc` runs `~/.bash_logout` (`clear_console` fails without a TTY) | Reproduced: readiness returned 1 in the image although every command and VTK existed | All container commands use `bash -c`; one shared `IMAGE_READY_CHECK` |
| 2 | EXIT trap referenced a function-local `backup` | Reproduced with a stand-alone script: `backup: unbound variable`, exit 1 after `complete` was written | Trap uses globals only (`finish_execute`); no local backup — the requested `decomposeParDict` is kept as `decomposeParDict.requested` |
| 3 | UI trusted `server-job-status.json` alone | Confirmed in code | `ExecStopPost` records the real unit result in `server-job-unit-result.json`; `status` reconciles it and reports `failed/status_mismatch` if they disagree |
| 4 | Early failure could leave `queued` | Confirmed in code | Runner writes `running` first, an EXIT trap writes `failed/runner_aborted`, and `ExecStopPost` covers a SIGKILLed runner |
| 5 | `command -v` misses broken runtimes | Confirmed in code | Readiness also runs `blastFoam -help` (exit 4 = present but not executable) |

Additional fixes: OpenMPI refused to start as root (`OMPI_ALLOW_RUN_AS_ROOT*` is
now set, ownership is still returned to the submitting user); `numberOfSubdomains`
is set to the CPU limit and verified before start; orphan containers are removed
by name after stop/kill/abort (`docker run --init`, `TimeoutStopSec=30`); OOM is
reported as `failure=out_of_memory` from `docker inspect`; the localhost adapter
rejects non-loopback `Host` and foreign `Origin` headers (DNS rebinding / CSRF);
a case must contain the full `REQUIRED_CASE_FILES` list locally and again on
the server after rsync; job deletion also refuses a job whose systemd unit is
active.

Status JSON gained `unit`, `failure` (`calculation_failed`, `out_of_memory`,
`postprocess_failed`, `runner_aborted`, `status_mismatch`, `submit_failed`,
`stopped`) and `last_log`; `status` adds a `systemd` object. The legacy
lowercase `state` vocabulary is unchanged and must still be mapped to the
target state model at the adapter boundary.

Not verified: real CFD runs, OOM kill (code path only), Safari layouts
(no browser automation was run), Docker on the production Ubuntu server.

### Follow-up (same day)

Scope decision: the blastFoam calculation setup is accepted as-is and was not
changed. Observation left for a CFD/QA owner: the template's reactant
`pRef 101298` in `constant/phaseProperties` is not linked to the UI
"ambient pressure" field (`controlDict` and `0/p` are). Identical at the
default value; differs only if the user changes ambient pressure.

UI / packaging / transfer changes: the viewer reads the pContours iso value from
`system/controlDict` (`waveIsoKPa`) instead of a fixed "110 kPa" and labels it as
absolute `p`; the server job list cross-checks the systemd unit; result fetch is
refused unless the job is `complete`; `rsync --delete` on result fetch is limited
to folders carrying a `.blasturban-results` marker; a Finder-selected case survives
library refreshes; repeated status-poll failures are shown; the `.tar.gz` option
is labelled as an extra copy that is not used for the transfer.
Fetch gating (remote script) was not exercised end-to-end after this change.

### Layout and Slurm-path audit (same day)

Layout was measured with WebKit (WKWebView, the Safari engine) at 1920, 1440,
1280, 1180, 1024, 820 and 400 px on all four tabs; Safari's "Allow remote
automation" is off, so Safari itself was not driven. Result: no document-level
vertical scroll at 1024 px and wider; at 1180 px and below the server tab's action
buttons (send, status, logs, fetch, stop) were below the fold and are now a sticky
bar. Not measured: keyboard focus order, contrast ratios, real browsers other than
WebKit.

`server-run-auto.sh` (Slurm / standalone path, not used by the Web UI): sbatch
failure and early `die` could leave `queued`/`waiting`/`running`; a `kill` of the
script waited for the whole calculation because bash defers traps behind a
foreground child. Fixed with an EXIT trap installed after the case lock is held
(so a refused duplicate run cannot overwrite the live job's status), a
`viewer_failed` state matching the Docker runner, and heavy steps run in their own
process group. Verified on Linux with a stub `blastFoam` (no solver run): success,
calculation failure, web-export failure, early failure, duplicate refusal, and
SIGTERM (`stopped`, `decomposeParDict` restored, no child left). Slurm itself
(`sbatch`/`scancel`) was not available and is untested.
