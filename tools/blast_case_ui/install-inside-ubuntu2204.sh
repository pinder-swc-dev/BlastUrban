#!/usr/bin/env bash
# Install OpenFOAM 9 and build this blastFoam checkout inside Ubuntu 22.04.
# Run this script as root from a persistent clone of the BlastUrban repository.
set -Eeuo pipefail

die() {
    printf 'blasturban-install: %s\n' "$*" >&2
    exit 1
}

(( EUID == 0 )) || die "enter a root shell, then run: $0 [BUILD_JOBS]"
[[ -r /etc/os-release ]] || die "cannot identify the operating system"
source /etc/os-release
[[ ${ID:-} == ubuntu && ${VERSION_ID:-} == 22.04 ]] \
    || die "this installer requires Ubuntu 22.04; found ${PRETTY_NAME:-unknown}"

machine_arch=$(uname -m)
[[ $machine_arch == x86_64 ]] \
    || die "the OpenFOAM 9 Ubuntu package used here requires x86_64; found $machine_arch"

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd -- "$script_dir/../.." && pwd)
[[ -x $repo_root/Allwmake && -r $repo_root/etc/bashrc ]] \
    || die "run the installer from a complete BlastUrban repository clone"
case "$repo_root" in
    /tmp|/tmp/*) die "clone the repository outside /tmp before installing" ;;
esac

host_jobs=$(getconf _NPROCESSORS_ONLN 2>/dev/null || nproc 2>/dev/null || printf 8)
(( host_jobs > 16 )) && host_jobs=16
build_jobs=${1:-$host_jobs}
[[ $build_jobs =~ ^[1-9][0-9]*$ ]] \
    || die "BUILD_JOBS must be a positive integer"

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends \
    ca-certificates \
    software-properties-common \
    wget

add-apt-repository -y universe
wget -qO /etc/apt/trusted.gpg.d/openfoam.asc https://dl.openfoam.org/gpg.key
add-apt-repository -y http://dl.openfoam.org/ubuntu

apt-get update
apt-get install -y --no-install-recommends \
    build-essential \
    git \
    gnuplot \
    libopenmpi-dev \
    openfoam9 \
    openmpi-bin \
    python3 \
    python3-vtk9 \
    rsync

# Keep a stable path that the Web UI readiness check and server runner know.
if [[ $repo_root != /opt/blastfoam ]]; then
    if [[ -e /opt/blastfoam || -L /opt/blastfoam ]]; then
        current_target=$(readlink -f /opt/blastfoam 2>/dev/null || true)
        [[ $current_target == "$repo_root" ]] \
            || die "/opt/blastfoam already points to a different installation: ${current_target:-unknown}"
    else
        ln -s "$repo_root" /opt/blastfoam
    fi
fi

set +u
source /opt/openfoam9/etc/bashrc
source /opt/blastfoam/etc/bashrc
set -u

cd /opt/blastfoam
printf 'Building blastFoam from %s with %s jobs\n' "$repo_root" "$build_jobs"
./Allwmake -j "$build_jobs" 2>&1 | tee /opt/blastfoam/log.install-Allwmake

required_commands=(
    surfaceCheck surfaceFeatures blockMesh checkMesh decomposePar
    snappyHexMesh addEmptyPatch setRefinedFields blastFoam
    blastToVTK calculateImpulse mpirun
)
for required_command in "${required_commands[@]}"; do
    command -v "$required_command" >/dev/null \
        || die "build completed without required executable: $required_command"
done
blastFoam -help >/dev/null \
    || die "blastFoam exists but cannot execute"
/usr/bin/python3 -c 'import vtk; print("Python VTK", vtk.VTK_VERSION)' \
    || die "Python VTK cannot be imported"

profile_file=/etc/profile.d/blasturban.sh
printf '%s\n' \
    '# Load OpenFOAM 9 and blastFoam for Bash login shells.' \
    'if [ -n "${BASH_VERSION:-}" ] && [ -z "${BLASTURBAN_ENV_LOADED:-}" ]; then' \
    '    source /opt/openfoam9/etc/bashrc' \
    '    source /opt/blastfoam/etc/bashrc' \
    '    export BLASTURBAN_ENV_LOADED=1' \
    'fi' > "$profile_file"
chmod 0644 "$profile_file"

# Ubuntu's non-login interactive root shell reads ~/.bashrc, not profile.d.
root_bashrc=/root/.bashrc
touch "$root_bashrc"
profile_source='source /etc/profile.d/blasturban.sh'
grep -Fqx "$profile_source" "$root_bashrc" \
    || printf '\n%s\n' "$profile_source" >> "$root_bashrc"

runner=/usr/local/bin/blasturban-run
printf '%s\n' \
    '#!/usr/bin/env bash' \
    'set -Eeo pipefail' \
    'set +u' \
    'source /opt/openfoam9/etc/bashrc' \
    'source /opt/blastfoam/etc/bashrc' \
    'set -u' \
    '(( $# )) || set -- bash' \
    'exec "$@"' > "$runner"
chmod 0555 "$runner"

printf '\nINSTALL_COMPLETE\n'
printf 'OpenFOAM: %s\n' "${WM_PROJECT_VERSION:-unknown}"
printf 'blastFoam: %s\n' "$(command -v blastFoam)"
printf 'Use now: source %s\n' "$profile_file"
printf 'Non-interactive: blasturban-run blastFoam -help\n'
