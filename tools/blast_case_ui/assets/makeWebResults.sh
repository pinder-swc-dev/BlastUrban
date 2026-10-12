#!/usr/bin/env bash
# Build a compact, standalone browser viewer from calculated OpenFOAM fields.
set -Eeuo pipefail

case_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
cd "$case_dir"

case_name=${BLAST_CASE_NAME:-}
if [[ -z $case_name && -f case-builder.json ]] && command -v python3 >/dev/null 2>&1; then
    case_name=$(python3 - <<'PY'
import json
try:
    with open("case-builder.json", encoding="utf-8") as stream:
        print(json.load(stream).get("config", {}).get("case_name", ""))
except (OSError, ValueError, TypeError):
    pass
PY
)
fi
case_name=${case_name:-$(basename "$case_dir")}
case_name=$(printf '%s' "$case_name" | tr -cd 'A-Za-z0-9_.-' | cut -c1-80)
[[ -n $case_name ]] || case_name=blasturban-result

mkdir -p results-web/logs
if [[ ${1:-} != --package-only ]]; then
    command -v python3 >/dev/null 2>&1 || { echo "ERROR: python3 is required" >&2; exit 2; }
    vtk_python=python3
    if ! "$vtk_python" -c 'import vtk' >/dev/null 2>&1; then
        if [[ -x /usr/bin/python3 ]] && /usr/bin/python3 -c 'import vtk' >/dev/null 2>&1; then
            vtk_python=/usr/bin/python3
        else
            echo "ERROR: Python VTK is required (Ubuntu 22.04: apt install python3-vtk9)" >&2
            exit 2
        fi
    fi
    "$vtk_python" visualization/exportBlast3D.py \
        --case "$case_dir" \
        --output "$case_dir/results-web/blast3D.html" \
        --model-label "$case_name · calculated blastFoam fields"
fi

for file in server-job-status.json case-builder.json geometry-repair.json; do
    [[ ! -f $file ]] || cp "$file" results-web/
done
if [[ -f log.blastFoam ]]; then
    # Keep diagnostics useful without placing a multi-megabyte timestep log in
    # every downloaded Web package.  The complete log remains in the server job.
    tail -c 2097152 log.blastFoam > results-web/logs/log.blastFoam.tail
fi
for file in log.checkMesh* log.snappyHexMesh*; do
    [[ ! -f $file ]] || cp "$file" results-web/logs/
done

archive="$case_dir/${case_name}-web-result.tar.gz"
tar -czf "$archive" -C results-web .
if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "${archive##*/}" > "${archive}.sha256"
elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "${archive##*/}" > "${archive}.sha256"
fi
printf 'Web viewer: %s\nTransfer package: %s\n' "$case_dir/results-web/blast3D.html" "$archive"
