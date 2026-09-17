#!/bin/sh
# Stage the repaired town case without copying any old mesh, logs, or results.
set -eu
case "$0" in */*) script_dir=${0%/*} ;; *) script_dir=. ;; esac
cd "$script_dir" || exit 1
target=${1:-townRun}
case "$target" in
    ''|*/*|*..*) echo "Use a new directory name inside building3DWorkshop" >&2; exit 1 ;;
esac
if [ -e "$target" ]; then
    echo "Case directory already exists: $target" >&2
    exit 1
fi
mkdir -p "$target/system" "$target/constant/triSurface" "$target/0"
cp system/blockMeshDict system/controlDict system/decomposeParDict \
   system/fvSchemes system/fvSolution system/setFieldsDict \
   system/snappyHexMeshDict system/surfaceFeaturesDict "$target/system/"
cp constant/dynamicMeshDict constant/phaseProperties "$target/constant/"
cp constant/triSurface/townBuildings.stl "$target/constant/triSurface/"
cp 0/*.orig "$target/0/"
cp Allrun Allclean "$target/"
printf 'Prepared %s from the repaired town STL. Run: cd %s && ./Allrun\n' "$target" "$target"
