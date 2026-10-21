#!/usr/bin/env bash
# Run one generated BlastUrban case in a resource-limited Docker container.
set -Eeuo pipefail

case_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
cd "$case_dir"
status_file="$case_dir/server-job-status.json"
unit_file="$case_dir/server-job-unit.txt"
unit_result_file="$case_dir/server-job-unit-result.json"
container_file="$case_dir/server-job-container.txt"
stop_marker="$case_dir/.server-job-stop-requested"
decompose="$case_dir/system/decomposeParDict"
requested_decompose="$case_dir/system/decomposeParDict.requested"

# Container commands run through plain `bash -c`, never a login shell: Ubuntu's
# ~/.bash_logout calls clear_console, which fails without a terminal and turns
# an explicit successful `exit` into status 1.
container_environment='set +e
for setup in /opt/openfoam9/etc/bashrc /root/OpenFOAM/OpenFOAM-9/etc/bashrc /root/OpenFOAM/OpenFOAM-v9/etc/bashrc; do
    if [ -f "$setup" ]; then source "$setup"; break; fi
done
for setup in /opt/blastfoam/etc/bashrc /opt/BlastUrban/etc/bashrc /workspace/BlastUrban/etc/bashrc /root/OpenFOAM/blastfoam/etc/bashrc; do
    if [ -f "$setup" ]; then source "$setup"; break; fi
done
set -e'

die() { printf 'server-docker-job: %s\n' "$*" >&2; exit 1; }
positive_int() { [[ $1 =~ ^[1-9][0-9]*$ ]]; }
safe_value() { [[ $1 =~ ^[A-Za-z0-9_./:@+-]+$ ]]; }
is_terminal() { [[ $1 == complete || $1 == failed || $1 == viewer_failed || $1 == stopped ]]; }

linger_state() {
    local value
    command -v loginctl >/dev/null 2>&1 || { printf 'unknown\n'; return; }
    value=$(loginctl show-user "$(id -un)" -p Linger --value 2>/dev/null || true)
    case "$value" in
        yes|no) printf '%s\n' "$value" ;;
        *) printf 'unknown\n' ;;
    esac
}

short_hash() {
    python3 - "$1" <<'PY'
import hashlib, sys
print(hashlib.sha256(sys.argv[1].encode("utf-8")).hexdigest()[:6])
PY
}

# Docker and systemd identifiers share a conservative 63-character ceiling.
# Keep the collision-resistant hash and unique suffix intact when truncating.
resource_name() {
    local original=$1 unique=$2 base slug digest suffix maximum
    base=$(basename -- "$original")
    while [[ $base == blasturban-* ]]; do base=${base#blasturban-}; done
    slug=$(printf '%s' "$base" | tr -cd 'A-Za-z0-9_.-')
    slug=${slug:-job}
    digest=$(short_hash "$base")
    suffix="-${digest}-${unique}"
    maximum=$((63 - ${#suffix} - 11))
    (( maximum >= 1 )) || die "resource name suffix is too long"
    slug=${slug:0:maximum}
    printf 'blasturban-%s%s\n' "$slug" "$suffix"
}

current_state() {
    python3 - "$status_file" <<'PY' 2>/dev/null || true
import json, sys
try:
    with open(sys.argv[1], encoding="utf-8") as stream:
        print(str(json.load(stream).get("state", "")))
except (OSError, ValueError, AttributeError):
    pass
PY
}

# These globals cross status writes inside one runner process.  write_status
# also preserves their previous JSON values when called by ExecStopPost.
job_linger=unknown
job_accept_no_linger=false
job_docker_exit_code=""
job_oom_killed=""

# write_status STATE MESSAGE [CORES] [MEMORY_GIB] [EXIT_CODE] [FAILURE_KIND] [LAST_LOG]
write_status() {
    local state=$1 message=$2 cores=${3:-0} memory=${4:-0} code=${5:-0}
    local failure=${6:-} last_log=${7:-} active_container="" unit=""
    [[ ! -f $container_file ]] || active_container=$(<"$container_file")
    [[ ! -f $unit_file ]] || unit=$(<"$unit_file")
    python3 - "$status_file" "$state" "$message" "$cores" "$memory" "$code" \
        "$active_container" "$unit" "$failure" "$last_log" "$job_linger" \
        "$job_accept_no_linger" "$job_docker_exit_code" "$job_oom_killed" <<'PY'
import json, os, socket, sys, tempfile
from datetime import datetime, timezone
(
    path, state, message, cores, memory, code, container, unit, failure, last_log,
    linger, accept_no_linger, docker_exit_code, oom_killed,
) = sys.argv[1:]
previous = {}
try:
    with open(path, encoding="utf-8") as stream:
        previous = json.load(stream)
except (OSError, ValueError, TypeError):
    pass
if not isinstance(previous, dict):
    previous = {}
now = datetime.now(timezone.utc)
now_text = now.isoformat()
if linger == "unknown" and previous.get("linger") in {"yes", "no", "unknown"}:
    linger = previous["linger"]
if accept_no_linger == "false" and previous.get("accept_no_linger") is True:
    accept_no_linger = "true"
if not docker_exit_code:
    docker_exit = previous.get("docker_exit_code")
else:
    docker_exit = int(docker_exit_code)
if not oom_killed:
    oom = previous.get("oom_killed")
elif oom_killed in {"true", "false"}:
    oom = oom_killed == "true"
else:
    oom = None
data = {
    "state": state,
    "message": message,
    "created_utc": previous.get("created_utc") or now_text,
    "state_started_utc": (
        previous.get("state_started_utc")
        if previous.get("state") == state and previous.get("state_started_utc")
        else now_text
    ),
    "updated_utc": now_text,
    "host": socket.gethostname(),
    "pid": os.getpid(),
    "cores": int(cores),
    "memory_gib_limit": int(memory),
    "exit_code": int(code),
    "container": container,
    "unit": unit,
    "linger": linger,
    "accept_no_linger": accept_no_linger == "true",
    "docker_exit_code": docker_exit,
    "oom_killed": oom,
}
if state in {"complete", "failed", "viewer_failed", "stopped"}:
    data["completed_utc"] = previous.get("completed_utc") or now_text
if failure:
    data["failure"] = failure
if last_log:
    data["last_log"] = last_log
fd, temporary = tempfile.mkstemp(prefix=".server-job-status-", dir=os.path.dirname(path))
with os.fdopen(fd, "w", encoding="utf-8") as stream:
    json.dump(data, stream, indent=2, ensure_ascii=False)
    stream.write("\n")
os.replace(temporary, path)
PY
}

newest_log() {
    local newest
    newest=$(ls -1t log.* 2>/dev/null | head -n 1 || true)
    printf '%s' "$newest"
}

remove_job_containers() {
    [[ -f $container_file ]] || return 0
    local name
    while IFS= read -r name; do
        safe_value "$name" || continue
        docker rm -f "$name" >/dev/null 2>&1 || true
    done < "$container_file"
    rm -f "$container_file"
}

submit_job() {
    local image=$1 cores=$2 memory=$3 platform=${4:-} accept_no_linger=${5:-false}
    safe_value "$image" || die "invalid Docker image name"
    positive_int "$cores" || die "cores must be a positive integer"
    positive_int "$memory" || die "memory must be a positive integer GiB value"
    [[ -z $platform ]] || safe_value "$platform" || die "invalid Docker platform"
    local host_cores
    host_cores=$(getconf _NPROCESSORS_ONLN 2>/dev/null || nproc)
    (( cores <= host_cores )) || die "requested $cores cores but the server has only $host_cores"
    command -v docker >/dev/null 2>&1 || die "docker is not installed on the server"
    docker image inspect "$image" >/dev/null 2>&1 || die "Docker image not found: $image"
    command -v systemd-run >/dev/null 2>&1 || die "systemd-run is not installed"
    systemctl --user show-environment >/dev/null 2>&1 || {
        die "systemd user service is unavailable; ask admin to run: loginctl enable-linger $(id -un)"
    }
    [[ $accept_no_linger == true || $accept_no_linger == false ]] \
        || die "accept_no_linger must be true or false"
    job_linger=$(linger_state)
    job_accept_no_linger=$accept_no_linger
    if [[ $job_linger != yes && $job_accept_no_linger != true ]]; then
        die "systemd Linger=$job_linger; submission refused because the job may stop after logout. Ask an administrator to run: sudo loginctl enable-linger $(id -un), or explicitly accept the logout risk in the Web UI"
    fi
    [[ -f $decompose ]] || die "missing system/decomposeParDict"
    if [[ -f $unit_file ]]; then
        local previous_unit
        previous_unit=$(<"$unit_file")
        if systemctl --user is-active --quiet "$previous_unit" 2>/dev/null; then
            die "this case is already running as $previous_unit"
        fi
    fi
    local unit
    unit=$(resource_name "$case_dir" "$(date +%Y%m%d%H%M%S)-$$")
    rm -f "$unit_result_file" "$stop_marker"
    printf '%s\n' "$unit" > "$unit_file"
    write_status queued "submitted to systemd; waiting to start Docker" "$cores" "$memory"
    # ExecStopPost records the real unit result even when the runner itself is
    # killed, so status JSON can never stay queued/running or claim success alone.
    if ! systemd-run --user --quiet --collect --unit="$unit" \
        --property=Nice=10 --property=CPUWeight=25 --property=IOWeight=25  \
        --property=TimeoutStopSec=30 \
        --property="ExecStopPost=$case_dir/server-docker-job.sh record-unit-result" \
        "$case_dir/server-docker-job.sh" execute "$image" "$cores" "$memory" "$platform" \
        "$job_linger" "$job_accept_no_linger"; then
        write_status failed "systemd-run could not start the job unit" "$cores" "$memory" 1 submit_failed
        die "systemd-run could not start $unit"
    fi
    printf '%s\n' "$unit"
}

# Globals used by the EXIT trap; a trap must not depend on function locals.
job_cores=0
job_memory=0
final_status_written=0

finish_execute() {
    local code=$?
    trap - EXIT
    remove_job_containers
    if (( final_status_written == 0 )); then
        if [[ -f $stop_marker ]]; then
            write_status stopped "job stopped by user" "$job_cores" "$job_memory" "$code" stopped "$(newest_log)" || true
        else
            write_status failed "job runner ended before writing a final status (exit $code)" \
                "$job_cores" "$job_memory" "$code" runner_aborted "$(newest_log)" || true
        fi
    fi
    exit "$code"
}

final_status() {
    final_status_written=1
    write_status "$@"
}

execute_job() {
    local image=$1 cores=$2 memory=$3 platform=${4:-} linger=${5:-unknown} accept_no_linger=${6:-false}
    positive_int "$cores" || die "invalid execute request"
    positive_int "$memory" || die "invalid execute request"
    job_cores=$cores
    job_memory=$memory
    job_linger=$linger
    job_accept_no_linger=$accept_no_linger
    trap finish_execute EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
    write_status running "preparing Docker job" "$cores" "$memory"

    local memory_high=$((memory > 4 ? memory - 4 : memory))
    local viewer_memory=$((memory < 6 ? memory : 6))
    local result_case container host_uid host_gid platform_args=()
    result_case=$(basename "$case_dir" | tr -cd 'A-Za-z0-9_.-' | cut -c1-80)
    container=$(resource_name "$case_dir" "$$")
    host_uid=$(id -u)
    host_gid=$(id -g)
    [[ -z $platform ]] || platform_args=(--platform "$platform")

    # MPI ranks must equal the CPU limit.  Keep the runtime value in place so
    # decomposeParDict, processor* directories, and logs stay consistent; the
    # originally requested file is preserved once for audit.
    [[ -f $decompose ]] || die "missing system/decomposeParDict"
    [[ -f $requested_decompose ]] || cp "$decompose" "$requested_decompose"
    local runtime_decompose
    runtime_decompose=$(mktemp "$case_dir/system/.decomposeParDict.XXXXXX")
    awk -v count="$cores" '
        /^[[:space:]]*numberOfSubdomains[[:space:]]+/ && !changed {
            sub(/[0-9]+[[:space:]]*;/, count ";"); changed=1
        }
        { print }
    ' "$requested_decompose" > "$runtime_decompose"
    grep -Eq "^[[:space:]]*numberOfSubdomains[[:space:]]+${cores};" "$runtime_decompose" \
        || { rm -f "$runtime_decompose"; die "could not set numberOfSubdomains to $cores"; }
    mv -f "$runtime_decompose" "$decompose"

    local code oom
    docker rm -f "$container" >/dev/null 2>&1 || true
    printf '%s\n' "$container" > "$container_file"
    write_status running "Docker is meshing or calculating blastFoam" "$cores" "$memory"
    # The container runs as root so it can source root-owned environments;
    # OpenMPI refuses root unless explicitly allowed.  Ownership is returned
    # to the submitting user before the container exits.
    if docker run --init --name "$container" ${platform_args[@]+"${platform_args[@]}"} \
        --cpus "$cores" --memory "${memory}g" --memory-reservation "${memory_high}g" \
        --pids-limit 8192 --shm-size 2g \
        --user 0:0 --env HOME=/root \
        --env OMPI_ALLOW_RUN_AS_ROOT=1 --env OMPI_ALLOW_RUN_AS_ROOT_CONFIRM=1 \
        --env BLAST_HOST_UID="$host_uid" --env BLAST_HOST_GID="$host_gid" \
        --volume "$case_dir:/case" --workdir /case --entrypoint /bin/bash \
        "$image" -c "
            fix_case_owner() { chown -R \"\$BLAST_HOST_UID:\$BLAST_HOST_GID\" /case >/dev/null 2>&1 || true; }
            trap fix_case_owner EXIT
            $container_environment
            command -v blastFoam >/dev/null
            ./preflight.sh
            ./Allrun
        "; then
        code=0
    else
        code=$?
    fi
    oom=$(docker inspect --format '{{.State.OOMKilled}}' "$container" 2>/dev/null || printf unknown)
    job_docker_exit_code=$code
    job_oom_killed=$oom
    remove_job_containers
    if (( code != 0 )); then
        if [[ -f $stop_marker ]]; then
            final_status stopped "job stopped by user" "$cores" "$memory" "$code" stopped "$(newest_log)"
        elif [[ $oom == true ]]; then
            final_status failed "container exceeded the ${memory} GiB memory limit (OOM killed)" \
                "$cores" "$memory" "$code" out_of_memory "$(newest_log)"
        else
            final_status failed "Docker/OpenFOAM calculation failed with exit code $code; inspect $(newest_log)" \
                "$cores" "$memory" "$code" calculation_failed "$(newest_log)"
        fi
        exit "$code"
    fi

    write_status postprocessing "calculation finished; creating Web 3-D result" "$cores" "$memory"
    local viewer_container viewer_cpus
    viewer_container=$(resource_name "$case_dir" "$$-web")
    viewer_cpus=$((cores < 2 ? cores : 2))
    docker rm -f "$viewer_container" >/dev/null 2>&1 || true
    printf '%s\n' "$viewer_container" > "$container_file"
    if docker run --init --name "$viewer_container" ${platform_args[@]+"${platform_args[@]}"} --cpus "$viewer_cpus" --memory "${viewer_memory}g" \
        --user 0:0 --env HOME=/root --env BLAST_CASE_NAME="$result_case" \
        --env BLAST_HOST_UID="$host_uid" --env BLAST_HOST_GID="$host_gid" \
        --volume "$case_dir:/case" --workdir /case --entrypoint /bin/bash \
        "$image" -c '
            fix_case_owner() { chown -R "$BLAST_HOST_UID:$BLAST_HOST_GID" /case >/dev/null 2>&1 || true; }
            trap fix_case_owner EXIT
            ./makeWebResults.sh
        '; then
        code=0
    else
        code=$?
    fi
    oom=$(docker inspect --format '{{.State.OOMKilled}}' "$viewer_container" 2>/dev/null || printf unknown)
    job_docker_exit_code=$code
    job_oom_killed=$oom
    remove_job_containers
    if (( code != 0 )); then
        if [[ -f $stop_marker ]]; then
            final_status stopped "job stopped by user during Web export" "$cores" "$memory" "$code" stopped
        else
            final_status viewer_failed \
                "OpenFOAM completed but Web export failed with exit code $code; check Python VTK and log" \
                "$cores" "$memory" "$code" postprocess_failed
        fi
        exit "$code"
    fi
    final_status complete "calculation and Web 3-D result completed" "$cores" "$memory"
}

# Called by systemd (ExecStopPost) after the job unit's main process ends.
record_unit_result() {
    local unit=""
    [[ ! -f $unit_file ]] || unit=$(<"$unit_file")
python3 - "$unit_result_file" "$unit" "${SERVICE_RESULT:-unknown}" \
        "${EXIT_CODE:-unknown}" "${EXIT_STATUS:-unknown}" <<'PY'
import json, os, sys, tempfile
from datetime import datetime, timezone
path, unit, result, exit_code, exit_status = sys.argv[1:]
data = {
    "unit": unit,
    "service_result": result,
    "exit_code": exit_code,
    "exit_status": exit_status,
    "recorded_utc": datetime.now(timezone.utc).isoformat(),
}
fd, temporary = tempfile.mkstemp(prefix=".server-job-unit-", dir=os.path.dirname(path))
with os.fdopen(fd, "w", encoding="utf-8") as stream:
    json.dump(data, stream, indent=2)
    stream.write("\n")
os.replace(temporary, path)
PY
    remove_job_containers
    local state status_code=${EXIT_STATUS//[^0-9]/}
    status_code=${status_code:-1}
    state=$(current_state)
    if [[ ${SERVICE_RESULT:-} == success ]]; then
        if ! is_terminal "$state"; then
            write_status failed "systemd unit succeeded but the runner left state '$state'" \
                0 0 0 status_mismatch "$(newest_log)"
        fi
    else
        if [[ -f $stop_marker ]]; then
            [[ $state == stopped ]] || write_status stopped "job stopped by user" 0 0 0 stopped "$(newest_log)"
        elif [[ $state == complete ]]; then
            write_status failed \
                "status said complete but systemd reported ${SERVICE_RESULT:-unknown} (exit ${EXIT_STATUS:-unknown})" \
                0 0 "$status_code" status_mismatch "$(newest_log)"
        elif ! is_terminal "$state"; then
            write_status failed \
                "systemd unit ended (${SERVICE_RESULT:-unknown}, exit ${EXIT_STATUS:-unknown}) before a final status" \
                0 0 "$status_code" runner_aborted "$(newest_log)"
        fi
    fi
}

stop_job() {
    : > "$stop_marker"
    if [[ -f $container_file ]]; then
        local name
        while IFS= read -r name; do
            safe_value "$name" || continue
            docker stop --time 20 "$name" >/dev/null 2>&1 || true
        done < "$container_file"
    fi
    if [[ -f $unit_file ]]; then
        systemctl --user stop "$(<"$unit_file")" 2>/dev/null || true
    fi
    remove_job_containers
    local state
    state=$(current_state)
    is_terminal "$state" || write_status stopped "job stopped by user" 0 0 0 stopped
}

# Print status JSON reconciled with the systemd unit.  A job whose unit has
# ended without a final status is persisted as failed so that listings and
# deletion safeguards see the same state.
show_status() {
    local unit="" live=""
    [[ ! -f $unit_file ]] || unit=$(<"$unit_file")
    if [[ -n $unit ]] && safe_value "$unit" && command -v systemctl >/dev/null 2>&1; then
        live=$(systemctl --user show "$unit" --property=LoadState,ActiveState,SubState,Result,ExecMainStatus 2>/dev/null || true)
    fi
    python3 - "$status_file" "$unit_result_file" "$unit" "$live" <<'PY'
import json, os, re, sys, tempfile
from datetime import datetime, timezone

status_path, result_path, unit, live_text = sys.argv[1:]

def load(path):
    try:
        with open(path, encoding="utf-8") as stream:
            value = json.load(stream)
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}

status = load(status_path) or {"state": "not_submitted"}
recorded = load(result_path)
live = dict(line.split("=", 1) for line in live_text.splitlines() if "=" in line)
active_states = {"queued", "running", "postprocessing"}
state = str(status.get("state", ""))
unit_running = live.get("ActiveState") in {"active", "activating", "deactivating", "reloading"}
unit_gone = live.get("LoadState") == "not-found" or live.get("ActiveState") in {"inactive", "failed"}
age = 0.0
try:
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(str(status.get("updated_utc")))).total_seconds()
except (TypeError, ValueError):
    pass

def valid_postprocess_recovery(status_value, recorded_value):
    recovery = status_value.get("recovery")
    if not isinstance(recovery, dict):
        return False
    if not (
        recovery.get("method") in {
            "postprocess_only_adaptive_voxel_export",
            "postprocess_reused_identical_vtk_export",
        }
        and recovery.get("cfd_rerun") is False
        and recovery.get("postprocess_exit_code") == 0
        and recovery.get("viewer_verified") is True
        and recovery.get("archive_sha256_verified") is True
    ):
        return False
    case_dir = os.path.dirname(status_path)
    viewer = os.path.join(case_dir, "results-web", "blast3D.html")
    archive_name = recovery.get("archive_name", "")
    if not isinstance(archive_name, str) or os.path.basename(archive_name) != archive_name:
        return False
    archive = os.path.join(case_dir, archive_name)
    try:
        if os.path.getsize(viewer) != int(recovery.get("viewer_html_bytes", -1)):
            return False
        if os.path.getsize(archive) <= 0:
            return False
        recovered_at = datetime.fromisoformat(str(recovery.get("recovered_utc")))
        recorded_at = datetime.fromisoformat(str(recorded_value.get("recorded_utc")))
        return recovered_at >= recorded_at
    except (OSError, TypeError, ValueError):
        return False

postprocess_recovered = valid_postprocess_recovery(status, recorded)

reconciled = ""
if unit and state in active_states and not unit_running:
    if recorded:
        reconciled = (f"systemd unit ended ({recorded.get('service_result')}, exit "
                      f"{recorded.get('exit_status')}) but status stayed '{state}'")
    elif unit_gone and age > 60:
        reconciled = f"systemd unit {unit} is no longer running but status stayed '{state}'"
elif (unit and state == "complete" and recorded
      and recorded.get("service_result") != "success" and not postprocess_recovered):
    reconciled = (f"status said complete but systemd reported {recorded.get('service_result')} "
                  f"(exit {recorded.get('exit_status')})")

if reconciled:
    status.update({
        "previous_state": state,
        "state": "failed",
        "failure": "status_mismatch" if state == "complete" else "runner_aborted",
        "message": reconciled,
        "updated_utc": datetime.now(timezone.utc).isoformat(),
    })
    fd, temporary = tempfile.mkstemp(prefix=".server-job-status-", dir=os.path.dirname(status_path))
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(status, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
    os.replace(temporary, status_path)

case_dir = os.path.dirname(status_path)
now = datetime.now(timezone.utc)

def seconds_since(value, until=None):
    if not value:
        return None
    try:
        start = datetime.fromisoformat(str(value))
        end = datetime.fromisoformat(str(until)) if until else now
        return max(0.0, (end - start).total_seconds())
    except (TypeError, ValueError):
        return None

elapsed = seconds_since(status.get("created_utc"), status.get("completed_utc"))
stage = {
    "queued": "queued",
    "postprocessing": "web_result",
    "complete": "complete",
    "failed": "failed",
    "viewer_failed": "web_result_failed",
    "stopped": "stopped",
}.get(str(status.get("state")), "preparing")

stage_logs = {
    "log.surfaceFeatures": "surface_features",
    "log.blockMesh": "base_mesh",
    "log.checkMesh.base": "base_mesh_check",
    "log.decomposePar": "decompose_mesh",
    "log.snappyHexMesh": "snappy_mesh",
    "log.checkMesh.snapped": "snapped_mesh_check",
    "log.addEmptyPatch": "boundary_patches",
    "log.setRefinedFields": "initializing",
    "log.blastFoam": "solving",
    "log.blastToVTK.ground": "converting_ground",
    "log.blastToVTK.walls": "converting_walls",
    "log.calculateImpulse": "calculating_impulse",
}
existing_stage_logs = []
for name, name_stage in stage_logs.items():
    path = os.path.join(case_dir, name)
    try:
        existing_stage_logs.append((os.path.getmtime(path), name, name_stage))
    except OSError:
        pass
latest_log = max(existing_stage_logs, default=(None, None, None))
blast_log = os.path.join(case_dir, "log.blastFoam")
if status.get("state") == "running":
    if latest_log[2]:
        stage = latest_log[2]

progress = {"stage": stage, "elapsed_seconds": elapsed, "active_log": latest_log[1]}
if stage == "complete":
    progress.update({"fraction": 1.0, "eta_seconds": 0.0, "confidence": "actual"})
elif stage == "solving":
    control_path = os.path.join(case_dir, "system", "controlDict")
    try:
        with open(control_path, encoding="utf-8", errors="replace") as stream:
            control_text = stream.read()
        match = re.search(r"(?m)^\s*endTime\s+([0-9.eE+-]+)\s*;", control_text)
        end_time = float(match.group(1)) if match else None
    except (OSError, TypeError, ValueError):
        end_time = None
    try:
        with open(blast_log, "rb") as stream:
            stream.seek(max(0, os.path.getsize(blast_log) - 4 * 1024 * 1024))
            log_text = stream.read().decode("utf-8", errors="replace")
        times = re.findall(r"(?m)^Time\s*=\s*([0-9.eE+-]+)\s*$", log_text)
        clocks = re.findall(r"ClockTime\s*=\s*([0-9.eE+-]+)\s*s", log_text)
        physical_time = float(times[-1]) if times else None
        solver_clock = float(clocks[-1]) if clocks else None
    except (OSError, TypeError, ValueError):
        physical_time = solver_clock = None
    progress.update({
        "physical_time": physical_time,
        "end_time": end_time,
        "solver_clock_seconds": solver_clock,
    })
    if end_time and end_time > 0 and physical_time is not None:
        fraction = max(0.0, min(0.999, physical_time / end_time))
        progress["fraction"] = fraction
        if solver_clock and physical_time > 0:
            progress["eta_seconds"] = max(0.0, solver_clock * (end_time / physical_time - 1.0))
            progress["confidence"] = "medium" if fraction >= 0.2 else "low"

status["progress"] = progress

status["systemd"] = {
    "unit": unit,
    "load_state": live.get("LoadState", ""),
    "active_state": live.get("ActiveState", ""),
    "sub_state": live.get("SubState", ""),
    "result": live.get("Result", ""),
    "exec_main_status": live.get("ExecMainStatus", ""),
    "recorded": recorded,
}
print(json.dumps(status, ensure_ascii=False))
PY
}

case ${1:-} in
    submit)
        [[ $# -ge 4 ]] || die "usage: $0 submit IMAGE CORES MEMORY_GIB [PLATFORM] [ACCEPT_NO_LINGER]"
        submit_job "$2" "$3" "$4" "${5:-}" "${6:-false}"
        ;;
    execute)
        [[ $# -ge 4 ]] || die "invalid execute request"
        execute_job "$2" "$3" "$4" "${5:-}" "${6:-unknown}" "${7:-false}"
        ;;
    check-linger)
        linger_state
        ;;
    resource-name)
        [[ $# -eq 3 ]] || die "usage: $0 resource-name CASE_NAME UNIQUE_SUFFIX"
        resource_name "$2" "$3"
        ;;
    record-unit-result)
        record_unit_result
        ;;
    stop)
        stop_job
        ;;
    status)
        show_status
        ;;
    *)
        die "use submit, status, or stop"
        ;;
esac
