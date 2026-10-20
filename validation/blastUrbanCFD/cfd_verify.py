#!/usr/bin/env python3
"""Solver-independent verification helpers for BlastUrban CFD cases.

Pure standard library. Reads OpenFOAM ASCII fields and compares them against
analytic references. It never writes into a case directory.
"""
from __future__ import annotations

import math
import re
from pathlib import Path


# ---------------------------------------------------------------- field I/O
def read_internal_scalar(path):
    """Return the internalField of an ASCII volScalarField as a list of floats."""
    text = Path(path).read_text()
    m = re.search(r"internalField\s+nonuniform\s+List<scalar>\s*(\d+)\s*\(", text)
    if m:
        n = int(m.group(1))
        body = text[m.end():]
        values = []
        for tok in re.finditer(r"[-+0-9.eE]+|\)", body):
            if tok.group() == ")":
                break
            values.append(float(tok.group()))
            if len(values) == n:
                break
        if len(values) != n:
            raise ValueError(f"{path}: expected {n} values, found {len(values)}")
        return values
    m = re.search(r"internalField\s+uniform\s+([-+0-9.eE]+)\s*;", text)
    if m:
        return [float(m.group(1))]
    raise ValueError(f"{path}: no scalar internalField found")


def check_finite_positive(name, values, positive=True):
    """Return a list of problem strings (empty means the field is valid)."""
    problems = []
    bad = [v for v in values if not math.isfinite(v)]
    if bad:
        problems.append(f"{name}: {len(bad)} non-finite values")
    if positive and any(v <= 0 for v in values if math.isfinite(v)):
        problems.append(f"{name}: non-positive values (min={min(values):.6g})")
    return problems


# ------------------------------------------------------------ conservation
def conserved_totals(rho, u, p, vol, gamma):
    """Total mass, momentum and energy of 1-D cell data (ideal gas)."""
    mass = sum(r * v for r, v in zip(rho, vol))
    mom = sum(r * w * v for r, w, v in zip(rho, u, vol))
    en = sum((pp / (gamma - 1.0) + 0.5 * r * w * w) * v
             for r, w, pp, v in zip(rho, u, p, vol))
    return mass, mom, en


def relative_drift(initial, final, scale=None):
    """|final-initial| / max(|initial|, scale). Use scale for quantities that start at 0."""
    denom = max(abs(initial), scale or 0.0)
    if denom == 0.0:
        raise ValueError("zero denominator; supply scale")
    return abs(final - initial) / denom


# ----------------------------------------------------------- convergence
def observed_order(err_coarse, err_fine, refinement_ratio=2.0):
    """p = ln(e_c/e_f)/ln(r)."""
    if err_coarse <= 0 or err_fine <= 0:
        raise ValueError("errors must be positive")
    return math.log(err_coarse / err_fine) / math.log(refinement_ratio)


def l1_error(numerical, exact, vol):
    return sum(abs(a - b) * v for a, b, v in zip(numerical, exact, vol)) / sum(vol)


# --------------------------------------------------- exact Sod Riemann sol.
def sod_exact(x, t, x0=0.5, gamma=1.4,
              left=(1.0, 0.0, 1.0), right=(0.125, 0.0, 0.1)):
    """Exact ideal-gas Riemann solution (Toro, ch. 4). Returns rho, u, p at x."""
    rl, ul, pl = left
    rr, ur, pr = right
    g = gamma
    cl, cr = math.sqrt(g * pl / rl), math.sqrt(g * pr / rr)

    def f(p, rk, pk, ck):
        if p > pk:  # shock
            a, b = 2.0 / ((g + 1) * rk), (g - 1) / (g + 1) * pk
            return (p - pk) * math.sqrt(a / (p + b))
        return 2 * ck / (g - 1) * ((p / pk) ** ((g - 1) / (2 * g)) - 1)

    ps = 0.5 * (pl + pr)
    for _ in range(100):
        fv = f(ps, rl, pl, cl) + f(ps, rr, pr, cr) + (ur - ul)
        h = 1e-7 * ps
        d = (f(ps + h, rl, pl, cl) + f(ps + h, rr, pr, cr) + (ur - ul) - fv) / h
        new = max(ps - fv / d, 1e-12)
        if abs(new - ps) < 1e-12 * ps:
            ps = new
            break
        ps = new
    us = 0.5 * (ul + ur) + 0.5 * (f(ps, rr, pr, cr) - f(ps, rl, pl, cl))

    out = []
    for xi in x:
        s = (xi - x0) / t if t > 0 else 0.0
        out.append(_sample(s, ps, us, g, left, right, cl, cr))
    return out


def _sample(s, ps, us, g, left, right, cl, cr):
    rl, ul, pl = left
    rr, ur, pr = right
    if s <= us:  # left of contact
        if ps > pl:  # left shock
            sh = ul - cl * math.sqrt((g + 1) / (2 * g) * ps / pl + (g - 1) / (2 * g))
            if s < sh:
                return rl, ul, pl
            r = rl * ((ps / pl + (g - 1) / (g + 1)) / ((g - 1) / (g + 1) * ps / pl + 1))
            return r, us, ps
        csl = cl * (ps / pl) ** ((g - 1) / (2 * g))
        head, tail = ul - cl, us - csl
        if s < head:
            return rl, ul, pl
        if s > tail:
            return rl * (ps / pl) ** (1 / g), us, ps
        c = 2 / (g + 1) * (cl + (g - 1) / 2 * (ul - s))
        u = 2 / (g + 1) * (cl + (g - 1) / 2 * ul + s)
        return rl * (c / cl) ** (2 / (g - 1)), u, pl * (c / cl) ** (2 * g / (g - 1))
    if ps > pr:  # right shock
        sh = ur + cr * math.sqrt((g + 1) / (2 * g) * ps / pr + (g - 1) / (2 * g))
        if s > sh:
            return rr, ur, pr
        r = rr * ((ps / pr + (g - 1) / (g + 1)) / ((g - 1) / (g + 1) * ps / pr + 1))
        return r, us, ps
    raise NotImplementedError("right rarefaction not needed for Sod")
