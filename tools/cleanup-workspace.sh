#!/usr/bin/env bash
# Inventory disposable BlastUrban workspace artifacts.  Nothing is moved
# unless --yes and at least one explicit --item NAME_OR_PATH are both given.
set -Eeuo pipefail

workspace=${BLASTURBAN_WORKSPACE:-$HOME/BlastUrbanWorkspace}
repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
trash_root=$HOME/.Trash
confirmed=false
declare -a requested=() candidates=() reasons=()

usage() {
    cat <<'EOF'
Usage:
  tools/cleanup-workspace.sh
  tools/cleanup-workspace.sh --yes --item NAME_OR_ABSOLUTE_PATH [--item ...]

The default is a read-only dry-run.  Confirmed items are moved to ~/.Trash;
they are not permanently deleted.
EOF
}

while (( $# )); do
    case $1 in
        --yes) confirmed=true; shift ;;
        --item)
            (( $# >= 2 )) || { printf '%s\n' '--item requires a name or path' >&2; exit 2; }
            requested+=("$2"); shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) printf 'Unknown argument: %s\n' "$1" >&2; usage >&2; exit 2 ;;
    esac
done

add_candidate() {
    local path=$1 reason=$2 existing
    [[ -e $path || -L $path ]] || return 0
    for existing in "${candidates[@]-}"; do [[ $existing != "$path" ]] || return 0; done
    candidates+=("$path")
    reasons+=("$reason")
}

if [[ -d $workspace/temp ]]; then
    while IFS= read -r -d '' path; do
        owner_pid=$(python3 - "$path/.owner.json" <<'PY' 2>/dev/null || true
import json, sys
try:
    with open(sys.argv[1], encoding="utf-8") as stream:
        print(int(json.load(stream).get("pid", 0)))
except (OSError, ValueError, TypeError):
    pass
PY
)
        if [[ $owner_pid =~ ^[1-9][0-9]*$ ]] && kill -0 "$owner_pid" 2>/dev/null; then
            continue
        fi
        add_candidate "$path" "stale .ui-work directory; owner process is not active"
    done < <(find "$workspace/temp" -mindepth 1 -maxdepth 1 -type d -name '.ui-work-*' -print0)
    while IFS= read -r -d '' path; do
        add_candidate "$path" "temporary upload larger than 100 MiB"
    done < <(find "$workspace/temp" -type f -size +100M -print0)
fi

if [[ -d $workspace/cases ]]; then
    while IFS= read -r -d '' path; do
        add_candidate "$path" "temporary upload artifact in cases larger than 100 MiB"
    done < <(find "$workspace/cases" -type f \
        \( -name '.upload-*' -o -name '*.upload' -o -name '*.tmp' \) -size +100M -print0)
fi

if [[ -d $workspace/results ]]; then
    while IFS= read -r -d '' path; do
        add_candidate "$path" "result directory older than 30 days"
    done < <(find "$workspace/results" -mindepth 1 -maxdepth 1 -type d -mtime +30 -print0)
fi

if [[ -d $repo_root/server-results ]]; then
    add_candidate "$repo_root/server-results" "gitignored legacy server-results directory"
fi
add_candidate "$HOME/.ssh/known_hosts.old" "backup created during SSH host-key testing"

printf 'BlastUrban cleanup dry-run — no files have been moved\n'
if (( ${#candidates[@]} == 0 )); then
    printf 'No candidates found.\n'
    exit 0
fi
for index in "${!candidates[@]}"; do
    size=$(du -sk -- "${candidates[$index]}" 2>/dev/null | awk '{print $1 " KiB"}' || true)
    printf '[%d] %s\n    reason: %s\n    size: %s\n' \
        "$((index + 1))" "${candidates[$index]}" "${reasons[$index]}" "${size:-unknown}"
done

if [[ $confirmed != true ]]; then
    printf '\nTo move selected candidates to Trash, rerun with --yes and one --item per exact name/path.\n'
    exit 0
fi
(( ${#requested[@]} > 0 )) || { printf '%s\n' '--yes also requires at least one --item' >&2; exit 2; }
mkdir -p -- "$trash_root" "$workspace"
log_file=$workspace/cleanup-actions.log
timestamp=$(date -u +%Y%m%dT%H%M%SZ)

for requested_item in "${requested[@]}"; do
    matched=-1
    for index in "${!candidates[@]}"; do
        if [[ $requested_item == "${candidates[$index]}" || $requested_item == "$(basename -- "${candidates[$index]}")" ]]; then
            (( matched == -1 )) || { printf 'Ambiguous candidate name: %s\n' "$requested_item" >&2; exit 2; }
            matched=$index
        fi
    done
    (( matched >= 0 )) || { printf 'Refusing unlisted candidate: %s\n' "$requested_item" >&2; exit 2; }
    source_path=${candidates[$matched]}
    destination=$trash_root/BlastUrban-$timestamp-$(basename -- "$source_path")
    counter=0
    while [[ -e $destination || -L $destination ]]; do
        counter=$((counter + 1))
        destination=$trash_root/BlastUrban-$timestamp-$counter-$(basename -- "$source_path")
    done
    mv -- "$source_path" "$destination"
    printf '%s|MOVE_TO_TRASH|%s|%s|%s\n' \
        "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$source_path" "$destination" "${reasons[$matched]}" >> "$log_file"
    printf 'Moved to Trash: %s -> %s\n' "$source_path" "$destination"
done
