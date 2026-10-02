# BlastUrban agent working agreement

## Mission

Build a modular engineering simulation platform around OpenFOAM Foundation 9
and blastFoam. Keep physics, orchestration, API, result processing,
visualization, and UI concerns separate. A browser visualization must never
present mock geometry or an invented spherical animation as CFD output.

This file applies to the entire repository. More specific `AGENTS.md` files may
add constraints for a subtree, but may not weaken the safety and scientific
rules here.

## Current and target operating modes

The repository currently contains a trusted single-user administration tool:

```text
macOS browser -> localhost Python UI -> SSH/rsync -> Ubuntu host
              -> systemd user job -> Docker -> OpenFOAM 9/blastFoam
```

Treat this path as an internal development workflow. It is not a public API.
The production target is:

```text
Web client -> HTTPS API -> authentication/validation -> persistent job manager
           -> queue -> isolated Docker worker -> result pipeline -> result API
```

Do not expose the current localhost handler to a LAN or the public internet.
Do not describe the current system as multi-user or production-ready.

## Orchestrator workflow

For every meaningful task, the primary agent must first determine:

1. the user outcome;
2. affected subsystem boundaries;
3. the owning specialist role;
4. required cross-review roles;
5. available skills and missing capabilities;
6. files and contracts likely to change;
7. scientific, security, data-loss, and compatibility risks;
8. proportional verification.

Before coding a complex or cross-cutting change, report a compact task analysis
covering those points. Small, low-risk fixes may use a shortened version.

Use specialist sub-agents only when the task is independently divisible or the
user explicitly requests multi-agent review. Never let concurrent agents edit
the same files. The orchestrator owns the final integration decision.

## Logical model routing

Use capability aliases, not vendor-specific model names:

| Model class | Use for |
| --- | --- |
| `DEEP_REASONING` | architecture, CFD, security, concurrency, distributed state, difficult debugging |
| `IMPLEMENTATION` | normal Python/API code, schemas, adapters, tests, refactors, deployment files |
| `UI_VISUAL` | interaction flow, responsive UI, 3D controls, scientific visual hierarchy |
| `FAST_REVIEW` | code review, consistency checks, documentation, routine verification |

Switch class when the phase changes. Architecture approval does not replace an
implementation review, and UI polish does not replace scientific validation.

## Skill routing

Load only skills relevant to the task and only when those skills are actually
available. Read the selected skill instructions before acting. Never claim a
skill was used when it was unavailable.

Desired skill groups by area are:

- architecture: system design, service boundaries, API contracts, fault tolerance;
- logic: state machines, validation, workflow design, error handling;
- CFD: OpenFOAM, blastFoam, shock physics, mesh design, numerical stability;
- backend: Python, FastAPI, schema validation, uploads, async APIs, SSE/WebSocket;
- infrastructure: Docker, Linux, networking, resource limits, process management;
- results: VTK, OpenFOAM post-processing, glTF/GLB, compression, time series;
- UI/3D: scientific dashboards, accessibility, WebGL, large-mesh optimization;
- security: threat modeling, upload security, container isolation, authorization;
- QA: unit, integration, CFD regression, failure, and performance testing.

No repository-owned `SKILL.md` package exists at the time of this agreement.
Adding one is a separate scoped change; do not invent a skill interface ad hoc.

## Specialist ownership

### System Architect

Owns service boundaries, data flow, job/storage architecture, networking,
scaling, failure recovery, and architectural decision records. Does not own
visual styling or physical parameter selection.

Primary files: `ARCHITECTURE.md`, `docs/adr/`, future service manifests.

### Application Logic Engineer

Owns the job lifecycle, state transitions, warnings versus fatal errors,
idempotency, cancellation semantics, and dependency rules.

The target state model is:

```text
CREATED -> UPLOADING -> VALIDATING -> READY -> QUEUED -> PREPARING_CASE
        -> MESHING -> INITIALIZING -> RUNNING -> POST_PROCESSING
        -> GENERATING_WEB_DATA -> COMPLETED
```

Terminal or failure states must distinguish at least:

```text
VALIDATION_FAILED  MESH_FAILED  SOLVER_FAILED  POSTPROCESS_FAILED
CANCELLED          TIMEOUT      OUT_OF_MEMORY  INTERNAL_ERROR
```

Map legacy lowercase status files at an adapter boundary; do not spread a
second state vocabulary into a future public API.

### CFD / Blast Physics Engineer

Owns OpenFOAM dictionaries, blastFoam setup, material and ambient models,
source initialization, mesh requirements, time integration, Courant limits,
boundary conditions, and interpretation of results.

Primary files: `applications/`, `src/`, `etc/`, `tutorials/blastFoam/`, and the
CFD-generating functions in `tools/blast_case_ui/blast_case_builder.py`.

Never fabricate physical parameters. Identify missing inputs. Distinguish:

- direct solver fields;
- derived CFD quantities;
- engineering blast metrics;
- visualization-only geometry or sampling.

Overpressure means `p - ambient pressure` unless the case explicitly defines a
different reference. Any CFD change requires scientific QA review.

### Backend / API Engineer

Owns typed request/response contracts, uploads, authentication integration,
job APIs, status/log streaming, and result delivery. The present
`blast_case_web.py` is a localhost adapter, not the target public API.

Primary files: `tools/blast_case_ui/blast_case_web.py` and future API service
packages. Public endpoints must never accept OpenFOAM dictionaries, shell
scripts, Docker commands, or arbitrary server paths from an untrusted client.

### Infrastructure / DevOps Engineer

Owns Docker lifecycle, host-controlled workers, bind mounts, resource limits,
timeouts, storage, networking, process supervision, and deployment.

Primary files: `Dockerfile`, `tools/blast_case_ui/Dockerfile.server-web`,
`tools/blast_case_ui/assets/server-*.sh`, and deployment documentation.

Never expose the Docker daemon publicly. Keep SSH/Tailscale administration
separate from an HTTPS application gateway. Start with one concurrent CFD job
per worker until benchmarks justify more.

### Result Processing Engineer

Owns conversion of raw OpenFOAM output into a versioned, web-efficient result
contract. Preserve physical time and units. Browsers must not download a full
OpenFOAM case.

Primary files: `tools/blast_case_ui/assets/makeWebResults.sh` and
`tutorials/blastFoam/building3DWorkshop/visualization/`.

### UI/UX Designer

Owns workflow, information hierarchy, accessibility, responsive behavior, and
engineering status feedback. The interface should prioritize stage, physical
time, field, units, warnings, and solver diagnostics over decoration.

Primary file: `tools/blast_case_ui/web/index.html` and future web client files.

### 3D Visualization Engineer

Owns camera/layer controls, WebGL rendering, LOD, streaming, color scales,
slices, iso-surfaces, and large-mesh performance. Scientific representation
requires CFD review.

Never label the setup canvas or a synthetic sphere as simulation output. A
shockwave layer must be derived from solver data such as an overpressure
iso-surface, pressure/density gradient, or a documented shock indicator.

### Security Engineer

Owns threat models, authentication/authorization, upload and archive handling,
container boundaries, rate limits, secret handling, and auditability. Assume
all future remote client input is untrusted.

### QA / Validation Engineer

Owns unit, integration, failure, performance, and scientific regression plans.
Unit tests for a dictionary generator do not validate blast physics.

## Cross-review matrix

| Change | Owner | Required review |
| --- | --- | --- |
| New blast/source/ambient parameter | CFD | Logic, Backend, UI, QA |
| OpenFOAM dictionary or numerical scheme | CFD | Scientific QA |
| Docker execution or scheduling | Architect/DevOps | Security, Backend, QA |
| Public API contract or job state | Architect/Backend | Logic, Security, QA |
| New result field | CFD/Results | 3D Visualization, UI, QA |
| Physical-data visualization | 3D Visualization | CFD, Results, QA |
| Authentication, upload, deletion | Security/Backend | Architect, QA |
| UI-only copy/layout | UI/UX | FAST_REVIEW; CFD only if meaning changes |

## Repository boundaries

| Area | Responsibility |
| --- | --- |
| `applications/`, `src/`, `etc/` | solver, utilities, libraries, runtime environment |
| `tutorials/blastFoam/building3DWorkshop/` | trusted CFD template and reference case |
| `tools/blast_case_ui/blast_case_builder.py` | scenario validation and deterministic case generation |
| `tools/blast_case_ui/blast_case_web.py` | trusted localhost UI adapter and SSH administration |
| `tools/blast_case_ui/assets/` | generated job runner and result pipeline assets |
| `tools/blast_case_ui/web/` | setup/admin UI, not a public multi-user client |
| `tutorials/.../visualization/` | VTK conversion and standalone scientific viewer |
| `docs/` | user, deployment, audit, security, and pipeline documentation |

Keep user cases and downloaded results in `~/BlastUrbanWorkspace`, not in the
source tree. Keep server jobs isolated by job identifier and directory.

## Security and data rules

- Bind the current development UI to `127.0.0.1` only.
- Never commit passwords, tokens, private keys, host-specific secrets, or raw results.
- Validate filenames, STL structure, numeric ranges, coordinates, mesh caps,
  resource requests, image names, job names, and remote paths.
- Pass shell values as separately quoted arguments; do not concatenate client
  text into shell source.
- A future public API accepts scenario data, not generated cases or scripts.
- Server-controlled templates create OpenFOAM files inside the trusted boundary.
- Destructive job deletion must resolve and validate the exact job directory,
  refuse active jobs, and remain auditable.
- Preserve job configuration, stage, exit code, and relevant logs on failure.

## Development process

Use this order for cross-cutting work:

1. inspect the actual code path and existing contracts;
2. classify the affected subsystems;
3. assign owner and reviewers;
4. design interfaces and failure behavior;
5. record an ADR for material architecture decisions;
6. implement the smallest coherent change;
7. test success and failure paths;
8. validate scientific meaning where applicable;
9. update the relevant documentation;
10. report remaining uncertainty honestly.

Do not rewrite working components merely to match a target diagram. Introduce
the production architecture through explicit adapter boundaries and migration
phases described in `ARCHITECTURE.md`.

## Verification baseline

Run checks proportional to the change. The current Python/UI baseline is:

```bash
python3 -m py_compile \
  tools/blast_case_ui/blast_case_builder.py \
  tools/blast_case_ui/blast_case_web.py
python3 -m unittest discover -s tools/blast_case_ui -p 'test_*.py' -v
bash -n tools/blast_case_ui/assets/*.sh
git diff --check
```

For UI changes, verify referenced IDs/handlers, JavaScript syntax, narrow and
wide layouts, and the critical browser flow. For Docker changes, run image and
container smoke tests. For CFD changes, run the relevant OpenFOAM validation or
tutorial case and retain mesh/solver evidence. Never claim a check that was not
actually run.

## Documentation and ADRs

Keep these documents accurate as their subsystems are introduced:

- `ARCHITECTURE.md`
- `docs/PROJECT_AUDIT.md`
- `API.md`
- `CFD_PIPELINE.md`
- `WEB_VISUALIZATION.md`
- `DEPLOYMENT.md`
- `SECURITY.md`

Important decisions belong in `docs/adr/` with context, decision,
alternatives, consequences, and affected systems. Do not create placeholder
documents that imply an unimplemented capability exists.

## Collaboration and communication

- Preserve unrelated user changes and avoid broad rewrites.
- Lead with the outcome and explain architecture in plain language.
- Cover loading, empty, error, success, disabled, destructive, and permission states.
- Prefer small reviewable changes and stable public contracts.
- When asked to analyze only, do not change runtime behavior.
- Clearly separate implemented behavior, proposed behavior, and unverified assumptions.
