"""Thin adapter: hand a :class:`~capkit.optimize.model.Model` to HiGHS through ``scipy.optimize.milp``.

This is the only module that imports scipy, and it does so lazily, so every other CapKit command works
without it. Install with ``pip install "capkit[optimize]"`` (scipy >= 1.9 bundles HiGHS).
"""
from __future__ import annotations

import math
import time


class SolverUnavailable(RuntimeError):
    pass


def _scipy():
    try:
        import numpy as np
        import scipy
        from scipy.optimize import Bounds, LinearConstraint, milp
        from scipy.sparse import csr_matrix
    except ImportError as e:   # pragma: no cover
        raise SolverUnavailable('the optimizer needs scipy >= 1.9: pip install "scipy>=1.9" '
                                '(evaluate_mix works without it)') from e
    major, minor = (int(p) for p in scipy.__version__.split(".")[:2])
    if (major, minor) < (1, 9):   # pragma: no cover
        raise SolverUnavailable(f"scipy {scipy.__version__} is too old; need >= 1.9 for scipy.optimize.milp")
    return np, Bounds, LinearConstraint, milp, csr_matrix


def solve(model, time_limit: float = 60.0, mip_gap: float = 1e-9, relax: bool = False) -> dict:
    """Maximize the model. Returns {"status", "optimal", "objective", "x", "mip_gap", "seconds"}."""
    np, Bounds, LinearConstraint, milp, csr_matrix = _scipy()
    n = len(model.names)
    data, ri, ci = [], [], []
    for r, row in enumerate(model.rows):
        for j, v in row.items():
            data.append(v)
            ri.append(r)
            ci.append(j)
    A = csr_matrix((data, (ri, ci)), shape=(len(model.rows), n))
    c = np.zeros(n)
    for j, v in model.obj.items():
        c[j] = -v
    integ = np.zeros(n) if relax else np.array(model.integer, dtype=float)
    t0 = time.time()
    res = milp(c, constraints=LinearConstraint(A, model.lo, model.hi), integrality=integ,
               bounds=Bounds(model.lb, model.ub),
               options={"mip_rel_gap": mip_gap, "time_limit": time_limit, "presolve": True})
    dt = time.time() - t0
    out = {"status": res.status, "message": res.message, "seconds": dt,
           "optimal": res.status == 0, "x": None, "objective": None,
           "mip_gap": getattr(res, "mip_gap", None)}
    if res.x is not None:
        out["x"] = [float(v) for v in res.x]
        out["objective"] = -float(res.fun) + model.constant
    if res.status == 1 and res.x is not None:
        out["label"] = "time limit reached: best plan found, NOT proven optimal"
    return out
