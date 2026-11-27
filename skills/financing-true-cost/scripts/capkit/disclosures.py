"""California and New York commercial financing disclosures for sales-based financing (MCA, RBF).

Reproduces the *math* of the "estimated" figures under the historical method and checks a disclosed APR
against both permitted Appendix J methods. It is an educational and self-checking tool, not a
compliance certification.

Rules implemented (text verified on law.cornell.edu, 2026-11-26):

* APR: "either the United States Rule method or the actuarial method, as both are set forth in
  Appendix J" - 10 CCR 940(a); 23 NYCRR 600.3(b). The checker computes both and accepts either.
* Historical method: the projection is the recipient's average monthly sales over a provider-fixed
  window of 4 to 12 months (10 CCR 930; 23 NYCRR 600.8). New York also allows the average of the same
  number of months with the highest sales in the past twelve.
* Estimated payments, term and APR follow from that projection, accounting for specified payment
  amounts, split-rate changes and contractual minimums (10 CCR 942; 23 NYCRR 600.7).
* Tolerance: New York - 1/8 point, 1/4 point if irregular, or a percentage difference of 2.5% or
  less (23 NYCRR 600.4). California's subchapter has no separate tolerance provision that CapKit
  located; it reports the Reg Z 1/8-point figure for reference and labels it as such.
* Coverage: CA offers of $500,000 or less (Fin. Code 22800(n)); NY offers of $2,500,000 or less
  (23 NYCRR 600.19).

Assumption CapKit makes explicit (the regulations give no closed form): monthly sales are spread
evenly over the payment periods in a year - for business-day debits, over the business days in the
twelve months after funding on the Federal Reserve calendar.
"""
from __future__ import annotations

from datetime import timedelta
from typing import List, Optional, Sequence

from . import apr as A
from . import params as P
from .calendar import add_months, is_business_day, parse
from .products import mca_split

STATES = ("CA", "NY")


def historical_average(monthly_sales: Sequence[float], window: int, state: str = "CA",
                       method: str = "preceding", exclude: Sequence[int] = ()) -> float:
    """Average monthly sales under the historical method.

    ``monthly_sales`` is oldest-to-newest. ``window`` must be 4-12 months (a business with a shorter
    history may use the months it has). ``exclude`` = indexes the provider excludes (non-recurring
    events, undocumented months). NY ``method="highest"`` averages the ``window`` highest months
    within the last twelve."""
    sales = [s for k, s in enumerate(monthly_sales) if k not in set(exclude)]
    if not 4 <= window <= 12 and len(sales) >= 4:
        raise ValueError("the historical window must be 4 to 12 months (10 CCR 930; 23 NYCRR 600.8)")
    if len(sales) < window:
        window = len(sales)
    if method == "highest":
        if state != "NY":
            raise ValueError("the highest-months option is New York's (23 NYCRR 600.8)")
        pick = sorted(sales[-12:], reverse=True)[:window]
    else:
        pick = sales[-window:]
    return sum(pick) / len(pick)


def periods_per_year(frequency: str, funding_date, holidays="frb") -> int:
    fd = parse(funding_date)
    if frequency == "business_day":
        end = add_months(fd, 12)
        n, d = 0, fd
        while d < end:
            d += timedelta(1)
            if is_business_day(d, holidays):
                n += 1
        return n
    return {"day": 365, "week": 52, "biweek": 26, "month": 12}[frequency]


def estimate(funding_provided: float, total_owed: float, split_rate: float, avg_monthly_sales: float,
             frequency: str = "business_day", funding_date="2027-01-04", prepaid_fees: float = 0.0,
             minimum_payment: float = 0.0, holidays="frb", state: str = "CA") -> dict:
    """Estimated disclosure figures for a sales-based financing under the historical method."""
    if state not in STATES:
        raise ValueError(f"state must be one of {STATES}")
    limit = P.param("ca_cfdl_max_amount" if state == "CA" else "ny_cfdl_max_amount")
    n = periods_per_year(frequency, funding_date, holidays)
    per = max(split_rate * avg_monthly_sales * 12 / n, minimum_payment)
    advance = funding_provided + prepaid_fees            # face amount the factor applies to
    s = mca_split(advance, total_owed / advance, 1.0, [per], frequency, funding_date, prepaid_fees, holidays)
    pays = [f for f in s.flows if f.amount < 0]
    first, last = s.flows[0].when, pays[-1].when
    term_days = (last - first).days
    total_pay = -sum(f.amount for f in pays)
    apr_a = A.apr_actuarial(s.flows, s.unit)
    apr_u = A.apr_us_rule(s.flows, s.unit)
    out = {
        "state": state,
        "covered": funding_provided <= limit,
        "coverage_limit": limit,
        "funding_provided": round(funding_provided, 2),
        "estimated_apr_actuarial": apr_a,
        "estimated_apr_us_rule": apr_u,
        "finance_charge": round(total_pay - funding_provided, 2),
        "estimated_total_payment_amount": round(total_pay, 2),
        "estimated_payment": round(per, 2),
        "payment_frequency": frequency,
        "number_of_payments": len(pays),
        "estimated_term_days": term_days,
        "estimated_term_months": round(term_days / 30.4, 1),
        "estimated_monthly_cost": round(total_pay / (term_days / 30.4), 2) if frequency != "month" else None,
        "assumed_average_monthly_sales": round(avg_monthly_sales, 2),
        "unit_period": s.unit,
        "last_payment_date": last.isoformat(),
        "sources": ["10 CCR 930, 940, 942, 914" if state == "CA" else "23 NYCRR 600.3, 600.6-600.8"],
        "caveat": "Educational reproduction of the estimate math; not a compliance certification.",
    }
    return out


def check_disclosed_apr(disclosed_apr: float, computed: dict, state: str = "CA", irregular: bool = False) -> dict:
    """Is a disclosed (estimated) APR consistent with either permitted Appendix J method?"""
    res = {}
    for method, key in (("actuarial", "estimated_apr_actuarial"), ("us_rule", "estimated_apr_us_rule")):
        v = computed[key]
        ok = A.within_tolerance(disclosed_apr, v, irregular)
        if state == "NY" and not ok:
            ok = abs((v - disclosed_apr) / disclosed_apr) * 100 <= 2.5 + 1e-12   # 23 NYCRR 600.4(c)
        res[method] = {"computed": v, "consistent": ok}
    matches = [m for m, r in res.items() if r["consistent"]]
    if matches:
        verdict = "consistent (" + " and ".join({"actuarial": "actuarial method",
                                                 "us_rule": "U.S. Rule method"}[m] for m in matches) + ")"
    else:
        verdict = "inconsistent with both permitted methods"
    tol_note = ("NY tolerance: 1/8 point (1/4 if irregular) or a 2.5% percentage difference (23 NYCRR 600.4)"
                if state == "NY" else
                "CA: compared at the Reg Z 1/8-point tolerance for reference; no separate CA tolerance located")
    return {"disclosed": disclosed_apr, "methods": res, "verdict": verdict, "tolerance": tol_note}
