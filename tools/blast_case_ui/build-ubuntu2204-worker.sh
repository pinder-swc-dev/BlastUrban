#!/usr/bin/env bash
# Build and smoke-test the Ubuntu 22.04 OpenFOAM 9/blastFoam worker image.
set -Eeuo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd -- "$script_dir/../.." && pwd)
image=${1:-blasturban/blastfoam9:of9-ubuntu2204}

host_jobs=$(getconf _NPROCESSORS_ONLN 2>/dev/null || nproc 2>/dev/null || printf 8)
(( host_jobs > 16 )) && host_jobs=16
build_jobs=${2:-$host_jobs}

[[ $image =~ ^[A-Za-z0-9_./:@+-]+$ ]] || {
    printf 'Invalid image name: %s\n' "$image" >&2
    exit 2
}
[[ $build_jobs =~ ^[1-9][0-9]*$ ]] || {
    printf 'BUILD_JOBS must be a positive integer: %s\n' "$build_jobs" >&2
    exit 2
}
command -v docker >/dev/null 2>&1 || {
    printf 'Docker is not installed\n' >&2
    exit 2
}
docker info >/dev/null

build_args=(
    build
    --pull
    --progress=plain
    --build-arg "BUILD_JOBS=$build_jobs"
    --file "$script_dir/Dockerfile.ubuntu2204-worker"
    --tag "$image"
)
[[ ${BLAST_BUILD_NO_CACHE:-0} != 1 ]] || build_args+=(--no-cache)
build_args+=("$repo_root")

printf 'Building %s with %s compile jobs\n' "$image" "$build_jobs"
docker "${build_args[@]}"

printf 'Running non-CFD image readiness smoke test\n'
docker run --rm --env BLAST_WORKER_IMAGE="$image" "$image" bash -c '
set -e
for command in \
    surfaceCheck surfaceFeatures blockMesh checkMesh decomposePar \
    snappyHexMesh addEmptyPatch setRefinedFields blastFoam \
    blastToVTK calculateImpulse mpirun; do
    command -v "$command" >/dev/null
done
blastFoam -help >/dev/null
/usr/bin/python3 -c "import vtk; print(\"Python VTK\", vtk.VTK_VERSION)"
printf "READY_IMAGE=%s\\n" "$BLAST_WORKER_IMAGE"
'
