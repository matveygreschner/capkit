"""Run the optimizer end to end and report the plan, baselines, sensitivity and checks."""
from __future__ import annotations

import copy
import math

from .model import NEVER, build_model
from .solve import solve
from ..verify.reprice import evaluate


def extract_plan(model, info, x, tol=1e-6) -> dict:
    """Turn a solution vector into the plan format :func:`capkit.verify.reprice.evaluate` accepts."""
    v = lambda k: x[model.index[k]] if k in model.index else 0.0
    T = info["T"]
    fundings = []
    for name, pairs in info["X"].items():
        for s, u in pairs:
            amt = v(("x", name, s, u))
            if amt > tol:
                fundings.append({"offer": name, "week": s, "amount": round(amt, 6),
                                 "prepay_week": None if u == NEVER else u})
    plan = {"fundings": sorted(fundings, key=lambda f: f["week"])}
    if ("b", 1) in model.index:
        plan["loc_balance"] = [max(0.0, v(("b", t))) for t in range(1, T + 1)]
    plan["early_pay"] = {n: round(v(("e", n)), 9) for n in info["E"] if v(("e", n)) > tol}
    plan["factoring"] = [{"receivable": n, "week": q, "share": round(v(("y", n, q)), 9)}
                         for n, q in info["Y"] if v(("y", n, q)) > tol]
    return plan


def optimize(scenario: dict, H: float = 0.0, force=None, time_limit: float = 60.0) -> dict:
    m, info = build_model(scenario, H=H, force=force)
    r = solve(m, time_limit=time_limit)
    if r["x"] is None:
        return {"status": "infeasible" if r["status"] == 2 else r["message"], "optimal": False,
                "message": "No plan keeps cash above the floor with these offers." if r["status"] == 2 else r["message"]}
    plan = extract_plan(m, info, r["x"])
    check = evaluate(scenario, plan, H=H, tol=1e-4)
    agrees = check["feasible"] and abs(check["terminal_net_position"] - r["objective"]) <= 1e-4 * max(1.0, abs(r["objective"]))
    if not agrees:
        return {"status": "failed re-pricing check: the plan is NOT shown as optimal", "optimal": False,
                "objective": r["objective"], "plan": plan, "check": check,
                "message": "The solver's plan did not pass the independent re-pricing of every cash flow; "
                           "report this as a bug instead of using the plan."}
    return {"status": "optimal" if r["optimal"] else r.get("label", r["message"]), "optimal": r["optimal"],
            "objective": r["objective"], "plan": plan, "check": check, "seconds": r["seconds"],
            "binaries": sum(m.integer), "variables": len(m.names), "H": H}


def _describe(plan, info_offers=None):
    lines = []
    for f in plan["fundings"]:
        pre = f" and prepay it in week {f['prepay_week']}" if f["prepay_week"] else ""
        lines.append(f"Take ${f['amount']:,.2f} of {f['offer']} in week {f['week']}{pre}.")
    if plan.get("loc_balance"):
        peak = max(plan["loc_balance"])
        if peak > 0.005:
            lines.append(f"Use the line of credit, peaking at ${peak:,.2f}.")
    ep = plan.get("early_pay") or {}
    if ep:
        full = sum(1 for v in ep.values() if v > 1 - 1e-6)
        lines.append(f"Take the early-payment discount on {len(ep)} invoice(s) ({full} in full).")
    if plan.get("factoring"):
        lines.append(f"Factor {len(plan['factoring'])} receivable sale(s).")
    return lines


def run(scenario: dict, carries=(0, 52), sensitivity: bool = True, time_limit: float = 60.0) -> dict:
    """Full report: optimal plan at each post-horizon carry H, the baseline, savings, and the effect of
    moving the cash floor (parametric re-solves, not shadow prices)."""
    out = {"scenario": scenario.get("name"), "results": {}}
    base_force = (scenario.get("baseline") or {}).get("force")
    for H in carries:
        best = optimize(scenario, H=H, time_limit=time_limit)
        entry = {"optimal": best}
        if best.get("objective") is not None:
            entry["summary"] = _describe(best["plan"])
        if base_force and best.get("objective") is not None:
            base = optimize(scenario, H=H, force=base_force, time_limit=time_limit)
            entry["baseline"] = base
            if base.get("objective") is not None:
                entry["saving_vs_baseline"] = best["objective"] - base["objective"]
        out["results"][f"H={H}"] = entry
    if sensitivity and out["results"]["H=0"]["optimal"].get("objective") is not None:
        sens = []
        base_obj = out["results"]["H=0"]["optimal"]["objective"]
        for delta in (-5000, -1000, 1000, 5000):
            sc = copy.deepcopy(scenario)
            fl = sc.get("cash_floor", 0.0)
            sc["cash_floor"] = [max(0.0, v + delta) for v in fl] if isinstance(fl, list) else max(0.0, fl + delta)
            r = optimize(sc, H=0, time_limit=time_limit)
            sens.append({"cash_floor_change": delta,
                         "terminal_change": None if r.get("objective") is None else r["objective"] - base_obj})
        out["sensitivity"] = {"what": "re-solve with the cash floor moved; actual change in terminal net "
                                      "position (captures jumps when the set of offers changes)",
                              "rows": sens}
    out["assumptions"] = [
        "Terminal net position values every balance still open at the horizon at its payoff amount (H=0); "
        "H=52 also carries each open balance one more year at its own rate.",
        "Weekly grid: monthly loan payments fall in the week containing each due date; APRs of the chosen "
        "offers are computed separately on actual dates.",
        "Each offer is taken at most once and prepaid at most once, in full.",
        "MCA debits are fixed per advance dollar (a split-percentage MCA depends on sales; see stress test).",
    ]
    return out
