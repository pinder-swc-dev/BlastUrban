#!/usr/bin/env bash
# Load the solver environment for every non-interactive Docker command.
set -Eeo pipefail

openfoam_setup=/opt/openfoam9/etc/bashrc
blastfoam_setup=/opt/blastfoam/etc/bashrc

[[ -r $openfoam_setup ]] || {
    printf 'blasturban-entrypoint: missing %s\n' "$openfoam_setup" >&2
    exit 10
}
[[ -r $blastfoam_setup ]] || {
    printf 'blasturban-entrypoint: missing %s\n' "$blastfoam_setup" >&2
    exit 11
}

# OpenFOAM startup files are not guaranteed to be nounset-safe.
set +u
source "$openfoam_setup"
source "$blastfoam_setup"
set -u

(( $# )) || set -- bash
exec "$@"
