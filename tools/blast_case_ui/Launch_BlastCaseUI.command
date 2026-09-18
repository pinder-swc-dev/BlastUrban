#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$SCRIPT_DIR"

if ! command -v python3 >/dev/null 2>&1; then
    osascript -e 'display alert "BlastUrban" message "ไม่พบ python3 กรุณาติดตั้ง Python 3 ก่อน" as critical'
    exit 1
fi

if [ "$(uname -s)" = "Darwin" ]; then
    # Apple's Command Line Tools Python links against the obsolete system
    # Tk 8.5 framework, which aborts on macOS 26.  The browser UI uses the
    # same case-building engine without loading Tk/AppKit.
    exec python3 blast_case_web.py
fi

exec python3 blast_case_ui.py
