#!/bin/sh
set -eu

REPO_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
UI_SCRIPT="$REPO_DIR/tools/blast_case_ui/blast_case_web.py"

if ! command -v python3 >/dev/null 2>&1; then
    if command -v osascript >/dev/null 2>&1; then
        osascript -e 'display alert "BlastUrban" message "ไม่พบ python3 กรุณาติดตั้ง Python 3 ก่อน" as critical'
    else
        printf '%s\n' 'BlastUrban: python3 is required' >&2
    fi
    exit 1
fi

cd "$REPO_DIR"
exec python3 "$UI_SCRIPT"
