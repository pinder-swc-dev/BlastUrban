#!/bin/bash
# Sod mesh-convergence study for a chosen flux scheme / time integrator.
# Copies validation/blastFoam/Sod_shockTube into $OUT; the source case is untouched.
# Requires OpenFOAM 9 + blastFoam in the environment. NOT executed on the
# authoring workstation (no OpenFOAM there) - see docs/BLASTURBAN_CFD_VERIFICATION.md.
#   usage: run_sod_convergence.sh OUT_DIR [FLUX=HLLC] [INTEGRATOR="RK3SSP 4"] [END_TIME=12]
set -euo pipefail
OUT=${1:?output dir}; FLUX=${2:-HLLC}; INTEG=${3:-RK3SSP 4}; END=${4:-12}
HERE=$(cd "$(dirname "$0")" && pwd)
SRC="$HERE/../blastFoam/Sod_shockTube"
[ -e "$OUT" ] && { echo "refusing to reuse existing $OUT" >&2; exit 1; }
mkdir -p "$OUT"
for N in 125 250 500 1000; do
  C="$OUT/n$N"; cp -r "$SRC" "$C"; rm -rf "$C/validation"
  sed -i "s/^fluxScheme .*/fluxScheme      $FLUX;/; s/timeIntegrator .*/timeIntegrator  $INTEG;/" "$C/system/fvSchemes"
  sed -i "s/^endTime .*/endTime         $END;/" "$C/system/controlDict"
  sed -i "s/(500 1 1)/($N 1 1)/" "$C/system/blockMeshDict"
  ( cd "$C" && blockMesh >log.blockMesh && setFields >log.setFields \
      && blastFoam >log.blastFoam && postProcess -func sampleDict -latestTime >log.sample )
done
echo "done: compare with: python3 $HERE/analyze_sod.py $OUT $END"
