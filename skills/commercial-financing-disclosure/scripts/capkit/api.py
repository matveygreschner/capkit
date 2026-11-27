"""JSON command interface over the engine - used by the Claude skills and scripts.

    python -m capkit.api list                         # every command and its arguments
    python -m capkit.api describe true_cost           # one command's arguments + docstring
    python -m capkit.api true_cost '{"offer": {"type": "mca_fixed", "advance": 50000, "factor_rate": 1.35,
                                     "payment": 2250, "frequency": "week"}}'
    python -m capkit.api optimize_mix - < examples/bakery.json      # (wraps a bare scenario automatically)

Output is always JSON: {"command": ..., "inputs": ..., "result": ...} or {"error": ...}.
"""
from __future__ import annotations

import inspect
import json
import math
import sys
from datetime import date
from typing import Any, Callable, Dict, Optional

from . import apr as A
from . import compare as C
from . import disclosures as D
from . import params as P
from . import products as PR


def true_cost(offer: dict, marginal_rate: float = 0.0, interest_limited: bool = False):
    """What one financing offer really costs. ``offer`` = {"type": ..., terms...}; types:
    mca_fixed(advance, factor_rate, payment, frequency=business_day|week|day|month, funding_date, fees),
    mca_split(advance, factor_rate, holdback, sales[list per period], frequency, funding_date, fees),
    revenue_based(advance, cap_multiple, revenue_share, revenue[list], frequency=month),
    term_loan(amount, annual_rate, months, fee), sba_7a(amount, prime, spread=None->SOP max, months=120,
    fee_rate=None->FY table), line_of_credit(draw, annual_rate, weeks, draw_fee),
    factoring(face, advance_rate, fee_per_30_days, days_to_pay), trade_credit(invoice, discount,
    discount_days, net_days), equipment_lease(equipment_cost, payment, months, buyout, advance_payments).

    Returns APR by both Appendix J methods, EAR, XIRR, finance charge, the naive simple-annualized quote,
    the dated schedule and, with ``marginal_rate``, an after-tax finance charge."""
    s = PR.build(offer)
    a = PR.analyze(s)
    if marginal_rate:
        a.update(C.after_tax_cost(a["finance_charge"], a["tax_character"], marginal_rate, interest_limited))
    a["schedule"] = s.to_dict()["flows"]
    return a


def compare_offers(offers: list, marginal_rate: float = 0.0, interest_limited: bool = False):
    """Rank several offers (each a true_cost ``offer`` dict, optionally with a "name") on one basis."""
    return C.compare(offers, marginal_rate, interest_limited)


def apr(flows: list, unit: Optional[str] = None, method: str = "both"):
    """APR of arbitrary cash flows. ``flows`` = [[date-or-period, amount], ...]; advances +, payments -.
    ``unit`` = day|week|biweek|4week|semimonth|month|bimonth|quarter|semiannual|year (default: the most
    common payment interval). ``method`` = actuarial|us_rule|both."""
    out = {}
    if method in ("actuarial", "both"):
        out["apr_actuarial"] = A.apr_actuarial(flows, unit)
    if method in ("us_rule", "both"):
        out["apr_us_rule"] = A.apr_us_rule(flows, unit)
    fl = A._flows(flows)
    out["unit_period"] = unit or A._default_unit(fl)
    return out


def early_pay_cost(discount: float = 0.02, discount_days: int = 10, net_days: int = 30):
    """Annualized cost of passing up an early-payment discount such as 2/10 net 30."""
    return PR.early_pay_cost(discount, discount_days, net_days)


def disclosure_estimate(funding_provided: float, total_owed: float, split_rate: float,
                        avg_monthly_sales: Optional[float] = None, monthly_sales: Optional[list] = None,
                        window: int = 6, window_method: str = "preceding", state: str = "CA",
                        frequency: str = "business_day", funding_date: str = "2027-01-04",
                        prepaid_fees: float = 0.0, minimum_payment: float = 0.0):
    """CA/NY estimated APR, term, payment and finance charge for a sales-based financing (MCA/RBF) under
    the historical method. Give ``avg_monthly_sales`` or ``monthly_sales`` (oldest first) + ``window``."""
    if avg_monthly_sales is None:
        if not monthly_sales:
            raise ValueError("give avg_monthly_sales or monthly_sales")
        avg_monthly_sales = D.historical_average(monthly_sales, window, state, window_method)
    return D.estimate(funding_provided, total_owed, split_rate, avg_monthly_sales, frequency, funding_date,
                      prepaid_fees, minimum_payment, state=state)


def check_disclosure(disclosed_apr: float, funding_provided: float, total_owed: float, split_rate: float,
                     avg_monthly_sales: Optional[float] = None, monthly_sales: Optional[list] = None,
                     window: int = 6, window_method: str = "preceding", state: str = "CA",
                     frequency: str = "business_day", funding_date: str = "2027-01-04",
                     prepaid_fees: float = 0.0, minimum_payment: float = 0.0, irregular: bool = False):
    """Recompute a CA/NY disclosure and say whether the disclosed estimated APR is consistent with the
    actuarial method, the U.S. Rule method, both, or neither."""
    est = disclosure_estimate(funding_provided, total_owed, split_rate, avg_monthly_sales, monthly_sales,
                              window, window_method, state, frequency, funding_date, prepaid_fees, minimum_payment)
    return {"recomputed": est, "check": D.check_disclosed_apr(disclosed_apr, est, state, irregular)}


def optimize_mix(scenario: dict, carries: list = (0, 52), sensitivity: bool = True, time_limit: float = 60.0):
    """Cheapest funding mix for a weekly cash forecast (needs scipy >= 1.9). See examples/bakery.json for
    the scenario format. Reports the plan at post-horizon carries H=0 and H=52, the saving versus the
    scenario's baseline, floor sensitivity, and an independent re-pricing check of every plan."""
    from .optimize.report import run
    return run(scenario, tuple(carries), sensitivity, time_limit)


def evaluate_mix(scenario: dict, plan: dict, H: float = 0.0):
    """Check any proposed plan (stdlib, no solver): feasibility, every violated rule, weekly cash and
    terminal net position. ``plan`` = {"fundings": [{"offer", "week", "amount", "prepay_week"}],
    "loc_balance": [balance after each week], "early_pay": {invoice_index: share},
    "factoring": [{"receivable", "week", "share"}]}."""
    from .verify.reprice import evaluate
    return evaluate(scenario, plan, H)


def sba_fee(amount: float, fy: int = 2026, rate: Optional[float] = None):
    """SBA 7(a) upfront guaranty fee: rate x guaranteed portion, checked against the statutory ceiling."""
    return {"amount": amount, "guaranty_share": P.sba_guaranty_share(amount),
            "fee": round(P.sba_upfront_fee(amount, fy, rate), 2), "ceiling": round(P.sba_fee_ceiling(amount), 2),
            "max_rate_at_prime": P.sba_max_rate(amount)}


def params(key: Optional[str] = None):
    """Every parameter with its value, source, verified-on date and status (or one ``key``)."""
    if key:
        return {key: P.PARAMS[key]}
    return P.PARAMS


def prime_rate():
    """Latest Bank Prime Loan Rate from FRED (series DPRIME). Needs network access."""
    from .live import prime_rate as pr
    return pr()


def workbook(path: str = "CapKit.xlsx"):
    """Generate the formula-driven Excel / Google Sheets workbook."""
    from .excel.builder import build_workbook
    build_workbook(path)
    return {"wrote": path}


COMMANDS: Dict[str, Callable] = {f.__name__: f for f in (
    true_cost, compare_offers, apr, early_pay_cost, disclosure_estimate, check_disclosure, optimize_mix,
    evaluate_mix, sba_fee, params, prime_rate, workbook)}


def describe(name: str) -> dict:
    f = COMMANDS[name]
    sig = inspect.signature(f)
    args = {k: ("REQUIRED" if v.default is inspect._empty else v.default) for k, v in sig.parameters.items()}
    return {"command": name, "args": args, "doc": inspect.getdoc(f)}


def _default(o):
    if isinstance(o, date):
        return o.isoformat()
    if isinstance(o, float) and not math.isfinite(o):
        return str(o)
    if isinstance(o, (set, frozenset, tuple)):
        return list(o)
    return str(o)


def _clean(o):
    if isinstance(o, float):
        return o if math.isfinite(o) else str(o)
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    return o


def call(name: str, args: Dict[str, Any]):
    if name == "optimize_mix" and "scenario" not in args and "horizon_weeks" in args:
        args = {"scenario": args}
    return COMMANDS[name](**args)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd = argv[0]
    try:
        if cmd == "list":
            out = {n: describe(n)["args"] for n in COMMANDS}
        elif cmd == "describe":
            out = describe(argv[1])
        else:
            raw = argv[1] if len(argv) > 1 else "{}"
            args = json.load(sys.stdin) if raw == "-" else json.loads(raw)
            out = {"command": cmd, "inputs": args, "result": call(cmd, args)}
        print(json.dumps(_clean(out), indent=2, default=_default))
        return 0
    except Exception as e:   # report, don't trace, for the skills
        print(json.dumps({"error": f"{type(e).__name__}: {e}"}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
