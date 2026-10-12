#!/usr/bin/env bash
# Export one requested physical time per MPI process so dynamic-mesh addressing
# cannot leak between hundreds of blastToVTK samples.
set -Eeuo pipefail

case_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
cd "$case_dir"

patch=${1:-}
dt=${2:-}
scheme=${3:-}
output_dir=${4:-VTK}
[[ $patch =~ ^[A-Za-z0-9_.-]+$ ]] || { echo "invalid patch name" >&2; exit 2; }
[[ $dt =~ ^[0-9.eE+-]+$ ]] || { echo "invalid sampling interval" >&2; exit 2; }
[[ $scheme =~ ^[A-Za-z0-9_.-]+$ ]] || { echo "invalid interpolation scheme" >&2; exit 2; }
[[ $output_dir =~ ^[A-Za-z0-9_./-]+$ && $output_dir != /* && $output_dir != *..* ]] \
    || { echo "invalid output directory" >&2; exit 2; }
[[ -n ${WM_PROJECT_DIR:-} ]] || { echo "OpenFOAM environment is not loaded" >&2; exit 2; }
[[ -d processor0 ]] || { echo "parallel processor directories are missing" >&2; exit 2; }

. "$WM_PROJECT_DIR/bin/tools/RunFunctions"

mapfile -t sample_times < <(python3 - "$dt" <<'PY'
import math
import pathlib
import sys

dt = float(sys.argv[1])
if not math.isfinite(dt) or dt <= 0:
    raise SystemExit("sampling interval must be finite and positive")
times = []
for path in pathlib.Path("processor0").iterdir():
    if not path.is_dir():
        continue
    try:
        value = float(path.name)
    except ValueError:
        continue
    if math.isfinite(value) and value > 0:
        times.append(value)
if not times:
    raise SystemExit("no positive processor0 time directories found")
t_min, t_max = min(times), max(times)
count = int((t_max - t_min) / dt) + 1
for index in range(count):
    print(format(t_min + dt * index, ".12g"))
PY
)

((${#sample_times[@]} > 0)) || { echo "no sampling times selected" >&2; exit 2; }
printf 'Isolated blastToVTK: patch=%s frames=%s first=%s last=%s\n' \
    "$patch" "${#sample_times[@]}" "${sample_times[0]}" "${sample_times[-1]}"

index=0
output_slug=$(basename -- "$output_dir" | tr -cd 'A-Za-z0-9_.-')
for sample_time in "${sample_times[@]}"; do
    index=$((index + 1))
    suffix=$(printf '%s-%s-%04d' "$patch" "$output_slug" "$index")
    printf '[%d/%d] %s at %s\n' "$index" "${#sample_times[@]}" "$patch" "$sample_time"
    runParallel -s "$suffix" blastToVTK "$patch" \
        -sampleTime "$sample_time" -interpolationScheme "$scheme" \
        -outputDir "$output_dir"
done
