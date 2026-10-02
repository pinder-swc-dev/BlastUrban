# BlastUrban architecture

This document distinguishes the system that exists today from the intended
production architecture. Proposed components are not implemented merely by
being shown here.

## Current architecture

The current product is a trusted, single-user engineering workflow. The UI and
controller run locally on macOS; computation runs in a Docker container on an
Ubuntu server reachable over SSH.

```text
┌──────────────────────── macOS workstation ────────────────────────┐
│ Browser                                                          │
│   └─ static HTML/JavaScript UI                                   │
│        └─ HTTP on 127.0.0.1:8765                                │
│             └─ Python ThreadingHTTPServer                        │
│                  ├─ STL inspect/repair/preview                   │
│                  ├─ scenario validation                         │
│                  ├─ OpenFOAM case generation                    │
│                  └─ SSH + rsync administration                  │
│                                                                  │
│ ~/BlastUrbanWorkspace/{temp,cases,results}                       │
└──────────────────────────────┬───────────────────────────────────┘
                               │ SSH key + rsync
                               ▼
┌──────────────────────── Ubuntu host ─────────────────────────────┐
│ Per-job directory                                                │
│   ├─ generated OpenFOAM case and runner scripts                  │
│   ├─ JSON status file                                            │
│   └─ solver and post-processing logs                             │
│                                                                  │
│ systemd --user transient unit                                    │
│   └─ docker run --rm, CPU/RAM limits, bind mount job at /case   │
│        ├─ OpenFOAM Foundation 9                                  │
│        ├─ blastFoam                                              │
│        └─ Python VTK post-processing                             │
│                                                                  │
│ results-web/                                                     │
│   ├─ blast3D.html (self-contained)                               │
│   ├─ surface statistics CSV                                     │
│   └─ selected diagnostics/logs                                   │
└──────────────────────────────┬───────────────────────────────────┘
                               │ rsync
                               ▼
                       Local iframe/viewer
```

### Current component map

| Component | Implementation | Boundary |
| --- | --- | --- |
| UI | `tools/blast_case_ui/web/index.html` | trusted local browser |
| Local controller | `tools/blast_case_ui/blast_case_web.py` | localhost-only HTTP |
| Scenario/case logic | `tools/blast_case_ui/blast_case_builder.py` | Python dataclass + generated files |
| CFD template | `tutorials/blastFoam/building3DWorkshop/` | trusted repository content |
| Worker launcher | `tools/blast_case_ui/assets/server-docker-job.sh` | Ubuntu host + systemd user |
| Compute worker | Docker image with OpenFOAM 9 + blastFoam | bind-mounted `/case` |
| Post-processing | `makeWebResults.sh`, `exportBlast3D.py` | VTK to standalone HTML/CSV |
| Job persistence | case directory + `server-job-status.json` | filesystem only |

### Current trust model

The person operating the browser is also an administrator of the calculation
server. They may select SSH keys, Docker images, containers, local case paths,
and remote work directories. This is acceptable only because the HTTP server
binds to `127.0.0.1` and the workflow is explicitly an administration tool.

## Target architecture

The production client must submit a validated scenario, not an OpenFOAM case or
shell scripts.

```text
External Web Client
        │ HTTPS
        ▼
Reverse Proxy / API Gateway
        │
        ▼
FastAPI Application
  ├─ authentication + authorization
  ├─ typed scenario/upload validation
  ├─ job API and event stream
  └─ signed/authorized result access
        │
        ├──────────────► Metadata database
        │                  jobs, transitions, ownership, audit
        ▼
Durable Job Queue
        │
        ▼
Host Worker Controller ─────► Persistent job storage
  ├─ server-owned templates       input/ geometry/ case/
  ├─ concurrency policy           logs/ postprocess/ results/
  ├─ timeouts/quotas
  └─ isolated Docker worker
        │
        ▼
OpenFOAM 9 + blastFoam
        │
        ▼
Result Processor
  ├─ versioned manifest
  ├─ geometry/GLB
  ├─ lazy-loaded field frames
  ├─ surfaces and engineering metrics
  └─ probes/reports
        │
        ▼
Result API / object storage / CDN
        │
        ▼
WebGL scientific viewer
```

Administration remains separate:

```text
Tailscale/private network -> SSH -> host maintenance and debugging
HTTPS gateway             -> authenticated application API only
```

The Docker daemon and compute container are never exposed as client-facing
network services.

## Stable domain contracts

### Scenario input

The canonical input should be a versioned scenario document plus separately
uploaded geometry. It contains SI units, domain, source, ambient conditions,
mesh controls, solver controls, probes, requested outputs, and resource class.
It must not contain arbitrary OpenFOAM dictionaries or commands.

### Job identity and storage

Every job receives an immutable identifier independent of its display name.
Recommended storage layout:

```text
/srv/blast/
├── templates/
├── jobs/<job-id>/
│   ├── input/
│   ├── geometry/
│   ├── case/
│   ├── logs/
│   ├── postprocess/
│   └── metadata.json
├── results/<job-id>/
└── cache/
```

The metadata store is authoritative for ownership and state. Filesystem status
JSON may remain a worker-side transport detail, but not the only job database.

### Job lifecycle

```text
CREATED -> UPLOADING -> VALIDATING -> READY -> QUEUED -> PREPARING_CASE
        -> MESHING -> INITIALIZING -> RUNNING -> POST_PROCESSING
        -> GENERATING_WEB_DATA -> COMPLETED
```

Failures retain stage-specific diagnostics:

```text
VALIDATION_FAILED  MESH_FAILED  SOLVER_FAILED  POSTPROCESS_FAILED
CANCELLED          TIMEOUT      OUT_OF_MEMORY  INTERNAL_ERROR
```

Transitions must be persisted atomically, include timestamps and progress
metadata, and be idempotent under retry.

### Web result contract

The target result is a versioned manifest and independently fetchable assets,
not a full OpenFOAM case or one unbounded HTML payload:

```text
results/<job-id>/
├── manifest.json
├── geometry/
│   ├── buildings.glb
│   └── ground.glb
├── frames/<physical-time>/
├── surfaces/
│   ├── peak_overpressure.glb
│   ├── positive_impulse.glb
│   └── arrival_time.glb
├── probes/<probe-id>.json
└── report/summary.json
```

Every field records name, physical meaning, source, units, coordinate system,
time, range, and any decimation/interpolation applied. Frame identifiers must
preserve actual simulation time.

## Separation rules

1. Physics lives in trusted OpenFOAM templates and solver code.
2. Scenario validation is independent of transport and UI rendering.
3. The API owns authentication, authorization, and public contracts.
4. The job manager owns state, queueing, cancellation, retries, and policy.
5. The worker owns case materialization and controlled execution.
6. Result processing owns scientific conversion and provenance.
7. Visualization consumes the result contract; it does not infer physics.
8. UI labels and units come from result metadata where possible.

## Migration strategy

Do not replace the working SSH tool in one step. Introduce boundaries in this
order:

1. **Stabilize contracts** — version the scenario, job-state, failure, and
   result-manifest schemas; add architecture decision records.
2. **Extract pure case generation** — make the current builder consume only a
   typed scenario and produce a deterministic case inside a server-controlled
   workspace.
3. **Create persistent job model** — immutable IDs, transition history,
   ownership fields, timestamps, log references, and idempotency keys.
4. **Add FastAPI gateway** — authentication, upload limits, typed endpoints,
   job status/log events; keep it separate from Docker access.
5. **Add queue and host worker controller** — begin with one concurrent job,
   atomic claiming, cancellation, timeouts, recovery after restart, and disk
   quotas.
6. **Move case generation server-side** — public clients send scenario + STL;
   only trusted server templates generate dictionaries and scripts.
7. **Version web results** — manifest, GLB/binary surfaces, probes, metrics,
   progressive frame loading, and provenance.
8. **Build the WebGL viewer** — physical-time timeline, layers, units, probes,
   slices and iso-surfaces derived from actual data.
9. **Harden and benchmark** — threat model, rate limits, failure injection,
   resource measurements, CFD regression, accessibility, and load tests.
10. **Retire or retain the SSH adapter explicitly** — either keep it as a
    private admin tool or remove it after feature parity.

## Decisions still required

Create ADRs before implementation for at least:

- job metadata database and queue technology;
- worker isolation and Docker privilege model;
- web result manifest and binary encoding;
- authentication/tenant model;
- private administration and public ingress;
- retention, quotas, cleanup, and failed-job evidence;
- progress extraction from OpenFOAM logs;
- compatibility/versioning between API, templates, image, and result schema.
