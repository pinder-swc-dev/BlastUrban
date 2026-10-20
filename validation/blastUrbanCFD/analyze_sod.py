#!/usr/bin/env python3
"""Compare run_sod_convergence.sh output with the exact Sod solution.

Assumes `setFormat raw` output with columns: x p rho Ux Uy Uz (the field order
of the Sod sampleDict). The layout is checked and the script aborts on mismatch.
Prints L1 errors, observed orders and a PASS/FAIL against explicit tolerances.
"""
import sys
from pathlib import Path

import cfd_verify as v

GAMMA, X0, LENGTH = 1.4, 50.0, 100.0
# A first-order-in-the-discontinuity scheme converges at ~O(h^(1/2..1)) in L1
# for a shock tube; 0.5 is a deliberately loose lower bound, not a target.
MIN_ORDER = 0.5


def load(case):
    files = sorted(Path(case, "postProcessing").rglob("Centerline_*.xy"))
    if not files:
        raise SystemExit(f"{case}: no Centerline_*.xy sample found")
    rows = [[float(t) for t in ln.split()] for ln in files[-1].read_text().splitlines()
            if ln.strip() and not ln.lstrip().startswith("#")]
    if any(len(r) != 6 for r in rows):
        raise SystemExit(f"{files[-1]}: expected 6 columns (x p rho Ux Uy Uz)")
    return rows


def main(out, t):
    t = float(t)
    errs = {}
    for d in sorted(Path(out).glob("n*"), key=lambda p: int(p.name[1:])):
        rows = load(d)
        x = [r[0] for r in rows]
        ex = v.sod_exact(x, t, x0=X0, gamma=GAMMA)
        vol = [LENGTH / len(rows)] * len(rows)
        problems = v.check_finite_positive("p", [r[1] for r in rows]) + \
                   v.check_finite_positive("rho", [r[2] for r in rows])
        if problems:
            raise SystemExit(f"{d.name}: invalid fields: {problems}")
        errs[int(d.name[1:])] = (
            v.l1_error([r[2] for r in rows], [e[0] for e in ex], vol),
            v.l1_error([r[1] for r in rows], [e[2] for e in ex], vol))
    ns = sorted(errs)
    ok = True
    for a, b in zip(ns, ns[1:]):
        for k, name in enumerate(("rho", "p")):
            o = v.observed_order(errs[a][k], errs[b][k], b / a)
            print(f"N {a}->{b}  {name}: L1 {errs[a][k]:.4e}->{errs[b][k]:.4e}  order {o:.2f}")
            ok &= o >= MIN_ORDER
    print("PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main(*sys.argv[1:3])
