#!/bin/sh
# Move surfaceCheck diagnostics out of the case root.
set -eu

surface_stem=${1:-townBuildings}
if [ -n "${SURFACE_CHECK_RUN_ID:-}" ]; then
    run_id=$SURFACE_CHECK_RUN_ID
else
    run_id="manual-$(date +%Y%m%d-%H%M%S)-$$"
fi

diagnostic_dir="diagnostics/surfaceCheck/$run_id"
parts_dir="$diagnostic_dir/connectedParts"
mkdir -p "$parts_dir"

for object_file in "${surface_stem}"_*.obj; do
    [ -f "$object_file" ] || continue
    mv "$object_file" "$parts_dir/"
done

zone_file="zone_${surface_stem}.vtk"
if [ -f "$zone_file" ]; then
    mv "$zone_file" "$diagnostic_dir/"
fi

if [ -f log.surfaceCheck ]; then
    mv log.surfaceCheck "$diagnostic_dir/surfaceCheck.log"
fi
if [ -f log.preflight.surfaceCheck ]; then
    mv log.preflight.surfaceCheck "$diagnostic_dir/preflight.surfaceCheck.log"
fi

# Remove an empty connectedParts directory while keeping the run folder/log.
rmdir "$parts_dir" 2>/dev/null || true
echo "surfaceCheck files: $diagnostic_dir"
