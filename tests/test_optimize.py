"""Funding-mix optimizer: the bakery reference instance, re-pricing oracle, exploit and brute-force checks."""
import copy
import itertools
import json
import random
from pathlib import Path

import pytest

pytest.importorskip("scipy")

from capkit.optimize.model import NEVER, build_model
from capkit.optimize.report import extract_plan, optimize, run
from capkit.optimize.solve import solve
from capkit.verify.reprice import evaluate

ROOT = Path(__file__).resolve().parents[1]
# The reference fixture lets the MCA be prepaid out of SBA proceeds, which SBA SOP 50 10 8/8.1 restricts.
# It is NOT an executable plan; it is kept because an independent reference script pins its optimum.
BAKERY = json.loads((ROOT / "tests" / "fixtures" / "bakery_reference.json").read_text())
SAFE = json.loads((ROOT / "examples" / "bakery.json").read_text())


def variant(**changes):
    sc = copy.deepcopy(BAKERY)
    for k, v in changes.items():
        if k == "pi":
            sc["offers"][0]["payoff_discount"] = v
        elif k == "sba_fee_rate":
            sc["offers"][1]["fee_rate_of_guaranteed"] = v
        else:
            sc[k] = v
    return sc


# Expected values from the reference implementation that came with the design (HiGHS, scipy 1.13.1),
# reproduced here by CapKit's own builder.
@pytest.mark.parametrize("changes,kw,expected", [
    ({}, {}, -87156.81),
    ({"pi": 0.0}, {}, -88121.82),
    ({}, {"force": {"MCA": 50000}}, -96112.74),
    ({"pi": 0.0}, {"force": {"MCA": 50000}}, -102365.85),
    ({"sba_fee_rate": 0.0}, {}, -86359.52),
    ({}, {"H": 52}, -95250.73),
    ({}, {"H": 52, "force": {"MCA": 50000}}, -105619.58),
])
def test_bakery_reference_values(changes, kw, expected):
    r = optimize(variant(**changes), **kw)
    assert r["optimal"]
    assert round(r["objective"], 2) == expected
    assert r["check"]["feasible"], r["check"]["problems"]
    assert abs(r["check"]["terminal_net_position"] - r["objective"]) < 1e-5


def test_bakery_plan_shape():
    r = optimize(BAKERY)
    f = {x["offer"]: x for x in r["plan"]["fundings"]}
    assert f["MCA"]["amount"] == pytest.approx(10000) and f["MCA"]["week"] == 6 and f["MCA"]["prepay_week"] == 7
    assert f["SBA 7(a) tier 1"]["amount"] == pytest.approx(42548.02, abs=0.01) and f["SBA 7(a) tier 1"]["week"] == 7
    assert r["binaries"] == 147 and r["variables"] == 358
    cash = [w["cash"] for w in r["check"]["weeks"]]
    assert all(c >= 5000 - 1e-6 for c in cash)


def test_savings_vs_baseline():
    out = run(BAKERY, sensitivity=False)
    assert round(out["results"]["H=0"]["saving_vs_baseline"], 2) == 8955.94
    assert round(out["results"]["H=52"]["saving_vs_baseline"], 2) == 10368.86


def test_public_example_never_refinances_the_mca():
    """The shipped example forbids MCA prepayment, so no plan pays the advance off with SBA money."""
    r = optimize(SAFE)
    assert r["optimal"] and round(r["objective"], 2) == -88121.82
    assert all(f["prepay_week"] is None for f in r["plan"]["fundings"])
    assert r["check"]["feasible"]
    base = optimize(SAFE, force={"MCA": 50000})
    assert not base["optimal"]          # the full $50,000 MCA cannot keep cash above the floor


def test_fee_on_face_is_rejected_by_the_statutory_ceiling():
    """Charging 2% of the *face* amount (instead of 2% of the 85% guaranteed portion) exceeds the
    15 U.S.C. 636(a)(18)(A) ceiling, so the builder refuses it rather than optimizing on a wrong fee."""
    with pytest.raises(ValueError, match="statutory ceiling"):
        optimize(variant(sba_fee_rate=0.02 / 0.85))


def test_optimizer_does_not_overborrow():
    r = optimize(BAKERY)
    sba = sum(f["amount"] for f in r["plan"]["fundings"] if f["offer"].startswith("SBA"))
    assert sba < 50000          # $150,000 was available


def test_prepay_before_funding_is_rejected_by_reprice():
    bad = {"fundings": [{"offer": "MCA", "week": 6, "amount": 10000, "prepay_week": 3},
                        {"offer": "SBA 7(a)", "week": 7, "amount": 40000, "prepay_week": 2}]}
    res = evaluate(BAKERY, bad)
    assert not res["feasible"]
    assert any("not after funding" in p for p in res["problems"])


def test_reprice_rejects_out_of_range_and_double_take():
    bad = {"fundings": [{"offer": "MCA", "week": 6, "amount": 5000},
                        {"offer": "SBA 7(a)", "week": 3, "amount": 40000},
                        {"offer": "SBA 7(a)", "week": 8, "amount": 60000}]}
    probs = " | ".join(evaluate(BAKERY, bad)["problems"])
    assert "outside its $10,000" in probs and "outside its availability" in probs and "taken 2 times" in probs


def _random_scenario(rnd, T):
    c = [rnd.choice([-1, 1]) * rnd.uniform(0, 9000) for _ in range(T)]
    sc = {"horizon_weeks": T, "starting_cash": rnd.uniform(5000, 30000), "cash_floor": rnd.uniform(0, 6000),
          "revenue": rnd.uniform(8000, 25000), "affordability_share": rnd.uniform(0.1, 0.3),
          "deposit_rate": rnd.uniform(0, 0.05), "operating_cash_flow": c,
          "recurring_invoices": {"amount": rnd.uniform(1000, 6000), "weeks": [1, T], "discount": 0.02,
                                 "discount_lag": 1, "net_lag": rnd.choice([3, 4])},
          "line_of_credit": {"limit": rnd.uniform(0, 30000), "annual_rate": rnd.uniform(0.08, 0.2)},
          "offers": [{"name": "MCA", "type": "mca", "weeks": [1, T], "min": 5000, "max": rnd.uniform(20000, 60000),
                      "factor_rate": rnd.uniform(1.15, 1.45), "weekly_debit_per_dollar": rnd.uniform(0.03, 0.06),
                      "payoff_discount": rnd.choice([0, 0.05, 0.1])},
                     {"name": "Loan", "type": "amortizing", "weeks": [rnd.randint(1, T), T], "min": 10000,
                      "max": 80000, "annual_rate": rnd.uniform(0.09, 0.2), "months": rnd.choice([12, 24, 60]),
                      "fee": rnd.uniform(0, 0.04)}]}
    if rnd.random() < 0.5:
        sc["factoring"] = {"advance_rate": 0.8, "fee_per_30_days": rnd.uniform(0.01, 0.04),
                           "limit": rnd.uniform(5000, 40000),
                           "receivables": [{"face": rnd.uniform(2000, 15000), "issue_week": w,
                                            "collect_week": w + rnd.randint(3, 8)} for w in range(1, T, 2)]}
    return sc


def test_fuzz_reprice_matches_optimizer():
    """Builder-coefficient oracle: on random instances the independent re-pricing of the optimal plan
    must equal the MILP objective and satisfy every rule."""
    rnd = random.Random(2026)
    checked = 0
    for _ in range(40):
        sc = _random_scenario(rnd, rnd.randint(6, 13))
        for H in (0, 52):
            r = optimize(sc, H=H)
            if not r.get("optimal"):
                continue
            checked += 1
            assert r["check"]["feasible"], r["check"]["problems"]
            assert abs(r["check"]["terminal_net_position"] - r["objective"]) < 1e-4 * max(1, abs(r["objective"]))
    assert checked >= 30


def test_brute_force_small_instances():
    """On small instances, enumerate every (funding week, prepay week) choice per offer, fix it, solve
    the remaining LP, and confirm the MILP optimum equals the best enumerated value."""
    rnd = random.Random(11)
    done = 0
    for _ in range(12):
        T = rnd.randint(4, 6)
        sc = _random_scenario(rnd, T)
        sc.pop("factoring", None)
        m, info = build_model(sc)
        r = solve(m)
        choices = {j: [None] + pairs for j, pairs in info["X"].items()}
        best = None
        for combo in itertools.product(*choices.values()):
            mm, _ = build_model(sc)
            for (j, pairs), pick in zip(info["X"].items(), combo):
                for s, u in pairs:
                    k = mm.index[("z", j, s, u)]
                    v = 1.0 if pick == (s, u) else 0.0
                    mm.lb[k] = mm.ub[k] = v
            rr = solve(mm, relax=True)
            if rr["objective"] is not None and rr["status"] == 0:
                best = rr["objective"] if best is None else max(best, rr["objective"])
        if best is None:
            assert r["x"] is None
            continue
        done += 1
        assert abs(r["objective"] - best) < 1e-5 * max(1, abs(best))
    assert done >= 6


def test_infeasible_reported_cleanly():
    sc = variant(cash_floor=1_000_000)
    r = optimize(sc)
    assert not r["optimal"] and "floor" in r["message"]
