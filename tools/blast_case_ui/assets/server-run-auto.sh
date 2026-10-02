#!/usr/bin/env bash
# Submit through Slurm when available, otherwise run politely on a standalone server.
set -Eeuo pipefail

case_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
cd "$case_dir"

config_file=${BLAST_JOB_CONFIG:-"$case_dir/server-job.env"}
if [[ -f "$config_file" ]]; then
    while IFS='=' read -r key value; do
        [[ -z $key || $key == \#* ]] && continue
        case "$key" in
            BLAST_JOB_NAME|BLAST_JOB_CORES|BLAST_MAX_CORES|BLAST_MIN_CORES|\
            BLAST_RESERVE_CORES|BLAST_MEMORY_GIB|BLAST_RESERVE_MEMORY_GIB|\
            BLAST_WALLTIME|BLAST_SCHEDULER|BLAST_WAIT_FOR_RESOURCES|\
            BLAST_MAX_WAIT_MINUTES|BLAST_NICE|BLAST_OPENFOAM_BASHRC|\
            BLAST_REPO_BASHRC|BLAST_SLURM_PARTITION)
                printf -v "$key" '%s' "$value"
                ;;
            *)
                printf 'Ignoring unknown setting in server-job.env: %s\n' "$key" >&2
                ;;
        esac
    done < "$config_file"
fi

BLAST_JOB_NAME=${BLAST_JOB_NAME:-$(basename "$case_dir")}
BLAST_JOB_CORES=${BLAST_JOB_CORES:-auto}
BLAST_MAX_CORES=${BLAST_MAX_CORES:-10}
BLAST_MIN_CORES=${BLAST_MIN_CORES:-2}
BLAST_RESERVE_CORES=${BLAST_RESERVE_CORES:-2}
BLAST_MEMORY_GIB=${BLAST_MEMORY_GIB:-40}
BLAST_RESERVE_MEMORY_GIB=${BLAST_RESERVE_MEMORY_GIB:-8}
BLAST_WALLTIME=${BLAST_WALLTIME:-24:00:00}
BLAST_SCHEDULER=${BLAST_SCHEDULER:-auto}
BLAST_WAIT_FOR_RESOURCES=${BLAST_WAIT_FOR_RESOURCES:-1}
BLAST_MAX_WAIT_MINUTES=${BLAST_MAX_WAIT_MINUTES:-1440}
BLAST_NICE=${BLAST_NICE:-10}
BLAST_OPENFOAM_BASHRC=${BLAST_OPENFOAM_BASHRC:-/opt/openfoam9/etc/bashrc}
BLAST_REPO_BASHRC=${BLAST_REPO_BASHRC:-}
BLAST_SLURM_PARTITION=${BLAST_SLURM_PARTITION:-}

die() { printf 'server-run-auto: %s\n' "$*" >&2; exit 1; }
is_positive_int() { [[ $1 =~ ^[1-9][0-9]*$ ]]; }

for value in "$BLAST_MAX_CORES" "$BLAST_MIN_CORES" "$BLAST_MEMORY_GIB" \
             "$BLAST_RESERVE_MEMORY_GIB" "$BLAST_MAX_WAIT_MINUTES"; do
    is_positive_int "$value" || die "resource settings must be positive integers"
done
[[ $BLAST_RESERVE_CORES =~ ^[0-9]+$ ]] || die "BLAST_RESERVE_CORES must be zero or a positive integer"
[[ $BLAST_JOB_CORES == auto ]] || is_positive_int "$BLAST_JOB_CORES" \
    || die "BLAST_JOB_CORES must be auto or a positive integer"

status_file="$case_dir/server-job-status.json"
write_status() {
    local state=$1 message=$2 cores=${3:-0}
    python3 - "$status_file" "$state" "$message" "$cores" "$BLAST_MEMORY_GIB" <<'PY'
import json, os, socket, sys, tempfile
from datetime import datetime, timezone
path, state, message, cores, memory = sys.argv[1:]
data = {
    "state": state,
    "message": message,
    "updated_utc": datetime.now(timezone.utc).isoformat(),
    "host": socket.gethostname(),
    "pid": os.getpid(),
    "cores": int(cores),
    "memory_gib_planned": int(memory),
    "slurm_job_id": os.environ.get("SLURM_JOB_ID", ""),
}
fd, temporary = tempfile.mkstemp(prefix=".server-job-status-", dir=os.path.dirname(path))
with os.fdopen(fd, "w", encoding="utf-8") as stream:
    json.dump(data, stream, indent=2, ensure_ascii=False)
    stream.write("\n")
os.replace(temporary, path)
PY
}

total_cores() { getconf _NPROCESSORS_ONLN 2>/dev/null || nproc; }
available_memory_gib() {
    awk '/^MemAvailable:/ {printf "%d\n", $2/1048576}' /proc/meminfo
}
load_ceil() {
    awk '{value=$1; rounded=int(value); if (value>rounded) rounded++; print rounded}' /proc/loadavg
}

choose_cores() {
    local total usable busy idle selected
    total=$(total_cores)
    usable=$((total - BLAST_RESERVE_CORES))
    (( usable >= 1 )) || usable=1
    if [[ $BLAST_JOB_CORES == auto ]]; then
        busy=$(load_ceil)
        idle=$((total - busy - BLAST_RESERVE_CORES))
        (( idle >= 1 )) || idle=1
        selected=$idle
        (( selected > usable )) && selected=$usable
        (( selected > BLAST_MAX_CORES )) && selected=$BLAST_MAX_CORES
    else
        selected=$BLAST_JOB_CORES
        (( selected > usable )) && die "requested $selected cores but only $usable are available after reserve"
    fi
    printf '%s\n' "$selected"
}

resources_ready() {
    local cores=$1 available required
    available=$(available_memory_gib)
    required=$((BLAST_MEMORY_GIB + BLAST_RESERVE_MEMORY_GIB))
    (( cores >= BLAST_MIN_CORES && available >= required ))
}

submit_slurm() {
    local cores partition_args=()
    if [[ $BLAST_JOB_CORES == auto ]]; then
        cores=$BLAST_MAX_CORES
    else
        cores=$BLAST_JOB_CORES
    fi
    [[ -n $BLAST_SLURM_PARTITION ]] && partition_args=(--partition="$BLAST_SLURM_PARTITION")
    write_status queued "submitted to Slurm" "$cores"
    sbatch --parsable --job-name="$BLAST_JOB_NAME" --ntasks="$cores" \
        --mem="${BLAST_MEMORY_GIB}G" --time="$BLAST_WALLTIME" --chdir="$case_dir" \
        --output="$case_dir/log.server-job.%j" --export=ALL "${partition_args[@]}" \
        "$case_dir/server-run-auto.sh" --execute
}

if [[ ${1:-} != --execute && -z ${SLURM_JOB_ID:-} ]]; then
    if [[ $BLAST_SCHEDULER == slurm ]] || { [[ $BLAST_SCHEDULER == auto ]] && command -v sbatch >/dev/null 2>&1; }; then
        job_id=$(submit_slurm) || {
            write_status failed "sbatch could not submit the job" "$BLAST_MAX_CORES"
            die "sbatch could not submit the job"
        }
        printf 'Submitted Slurm job %s\n' "$job_id"
        exit 0
    fi
    [[ $BLAST_SCHEDULER != slurm ]] || die "BLAST_SCHEDULER=slurm but sbatch is unavailable"
fi

command -v flock >/dev/null 2>&1 || die "flock is required to prevent duplicate case runs"
exec 9>"$case_dir/.server-job.lock"
flock -n 9 || die "this case is already running"

# Installed only after the lock is held: a refused duplicate run must never
# overwrite the status of the job that is really running.  From here on, any
# exit without a final status is recorded, so state cannot stay waiting/running.
final_status_written=0
cores=0
decompose_backup=
restore_decompose() {
    cp "$decompose_backup" "$decompose" 2>/dev/null || true
    rm -f "$decompose_backup"
}
finish_execute() {
    local code=$?
    trap - EXIT
    [[ -z $decompose_backup ]] || restore_decompose
    if (( final_status_written == 0 )); then
        case $code in
            130|143) write_status stopped "job terminated by signal (exit $code), e.g. scancel or Ctrl-C" "$cores" || true ;;
            *)       write_status failed "job ended before a final status (exit $code); inspect log files" "$cores" || true ;;
        esac
    fi
    exit "$code"
}
final_status() { final_status_written=1; write_status "$@"; }

# bash delays trap handlers until the foreground child exits, so a plain
# `kill` of this script would wait for the whole calculation.  Heavy steps run
# in their own process group and are waited on, letting signals take effect
# at once and reach mpirun and its ranks.
child=
run_step() {
    local code=0
    setsid "$@" &
    child=$!
    wait "$child" || code=$?
    child=
    return "$code"
}
terminate() {
    local code=$1
    if [[ -n $child ]]; then
        kill -TERM -- "-$child" 2>/dev/null || true
        wait "$child" 2>/dev/null || true
        child=
    fi
    exit "$code"
}
trap finish_execute EXIT
trap 'terminate 130' INT
trap 'terminate 143' TERM

waited=0
while :; do
    cores=${SLURM_NTASKS:-$(choose_cores)}
    if [[ -n ${SLURM_JOB_ID:-} ]] || resources_ready "$cores"; then
        break
    fi
    [[ $BLAST_WAIT_FOR_RESOURCES == 1 ]] || die "not enough idle CPU or free RAM"
    (( waited < BLAST_MAX_WAIT_MINUTES )) || die "resource wait timed out"
    write_status waiting "waiting for idle CPU and free RAM" "$cores"
    printf 'Waiting: selected=%s cores, available=%s GiB, need=%s+%s GiB\n' \
        "$cores" "$(available_memory_gib)" "$BLAST_MEMORY_GIB" "$BLAST_RESERVE_MEMORY_GIB"
    sleep 60
    waited=$((waited + 1))
done

if [[ -z ${WM_PROJECT_DIR:-} ]]; then
    [[ -f $BLAST_OPENFOAM_BASHRC ]] || die "OpenFOAM environment is not loaded and $BLAST_OPENFOAM_BASHRC is missing"
    set +eu
    source "$BLAST_OPENFOAM_BASHRC"
    [[ -z $BLAST_REPO_BASHRC || ! -f $BLAST_REPO_BASHRC ]] || source "$BLAST_REPO_BASHRC"
    set -eu
fi
command -v blastFoam >/dev/null 2>&1 || die "blastFoam is not available in PATH"

decompose="$case_dir/system/decomposeParDict"
[[ -f $decompose ]] || die "missing system/decomposeParDict"
decompose_backup=$(mktemp "$case_dir/.decomposeParDict.XXXXXX")
cp "$decompose" "$decompose_backup"
awk -v count="$cores" '
    /^[[:space:]]*numberOfSubdomains[[:space:]]+/ && !changed {
        sub(/[0-9]+[[:space:]]*;/, count ";"); changed=1
    }
    { print }
' "$decompose_backup" > "$decompose"

export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
write_status running "preflight and blastFoam calculation are running" "$cores"
printf 'Running %s with %s cores; reserving %s cores and %s GiB for the server\n' \
    "$BLAST_JOB_NAME" "$cores" "$BLAST_RESERVE_CORES" "$BLAST_RESERVE_MEMORY_GIB"

runner=(nice -n "$BLAST_NICE")
command -v ionice >/dev/null 2>&1 && runner+=(ionice -c 2 -n 7)
if run_step "${runner[@]}" bash -c './preflight.sh && ./Allrun'; then
    write_status postprocessing "calculation finished; building Web result" "$cores"
else
    code=$?
    final_status failed "calculation failed with exit code $code; inspect log files" "$cores"
    exit "$code"
fi

if [[ -x ./makeWebResults.sh ]]; then
    if run_step "${runner[@]}" ./makeWebResults.sh; then
        final_status complete "calculation and Web result completed" "$cores"
    else
        code=$?
        final_status viewer_failed "calculation completed but Web export failed with exit code $code" "$cores"
        exit "$code"
    fi
else
    final_status complete "calculation completed; no Web exporter was included" "$cores"
fi

printf 'Completed. Web files: %s/results-web\n' "$case_dir"
