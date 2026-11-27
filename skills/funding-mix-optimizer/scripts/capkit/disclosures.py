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
* Tolerance: 1/8 point, 1/4 point if irregular, or a signed percentage difference (determined -
  disclosed) / disclosed of 2.5% or less (CA 10 CCR 955(a); NY 23 NYCRR 600.4(a)).
* Coverage: CA offers of $500,000 or less (Fin. Code 22800(n)); NY offers of $2,500,000 or less
  (23 NYCRR 600.19).

Assumption CapKit makes explicit (the regulations give no closed form): monthly sales are spread
evenly over the payment periods in a year - for business-day debits, over the business days in the
twelve months after funding on the Federal Reserve calendar.
"""
from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Sequence, cast

from . import apr as A
from . import params as P
from .calendar import add_months, business_days_after, is_business_day, parse

STATES = ("CA", "NY")


def historical_average(monthly_sales: Sequence[float], window: int, state: str = "CA",
                       method: str = "preceding", exclude: Sequence[int] = ()) -> float:
    """Average monthly sales under the historical method.

    ``monthly_sales`` is oldest-to-newest. ``window`` must be 4-12 months (a business with a shorter
    history may use the months it has). ``exclude`` = indexes (into ``monthly_sales``) the provider
    excludes inside the window (non-recurring events, undocumented months); the window does NOT reach
    back to replace them. NY ``method="highest"`` averages the ``window`` highest months within the last
    twelve."""
    sales = list(monthly_sales)
    if not sales or any(x < 0 for x in sales):
        raise ValueError("monthly_sales must be a non-empty list of zero or positive amounts")
    if not 4 <= window <= 12 and len(sales) >= 4:
        raise ValueError("the historical window must be 4 to 12 months (10 CCR 930; 23 NYCRR 600.8)")
    window = min(window, len(sales))
    if any(isinstance(k, bool) or not isinstance(k, (int, float)) or k != int(k) or not 0 <= k < len(sales)
           for k in exclude):
        raise ValueError(f"exclude_months are 0-based indexes into monthly_sales (0 to {len(sales) - 1}, "
                         "oldest first); negative or out-of-range indexes are not accepted")
    drop = {int(k) for k in exclude}
    if method == "highest":
        if state != "NY":
            raise ValueError("the highest-months option is New York's (23 NYCRR 600.8)")
        last12 = [(k, x) for k, x in enumerate(sales) if k >= len(sales) - 12 and k not in drop]
        pick = sorted((x for _, x in last12), reverse=True)[:window]
    else:
        pick = [x for k, x in enumerate(sales) if k >= len(sales) - window and k not in drop]
    if not pick:
        raise ValueError("every month in the window is excluded")
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


FREQUENCIES = ("business_day", "day", "week", "biweek", "month")


def _months_since(fd, d) -> int:
    """Whole contract months elapsed from the funding date (month 1 = the first month after funding)."""
    k = (d.year - fd.year) * 12 + d.month - fd.month      # O(1); add_months is non-decreasing in k
    if add_months(fd, k) > d:
        k -= 1
    return k + 1


def estimate(funding_provided: float, total_owed: float, split_rate: float, avg_monthly_sales: float,
             frequency: str = "business_day", funding_date="2027-01-04", prepaid_fees: float = 0.0,
             minimum_payment: float = 0.0, holidays="frb", state: str = "CA", paid_on_behalf: float = 0.0,
             split_schedule=None, funding_basis: str = "net") -> dict:
    """Estimated disclosure figures for a sales-based financing under the historical method.

    ``funding_provided`` = cash to the recipient; ``paid_on_behalf`` = amounts paid to others for the
    recipient (e.g. paying off a prior advance). Both are part of the amount financed, which is what
    the coverage threshold and the APR use. ``prepaid_fees`` are fees withheld from the funding. With
    ``funding_basis="net"`` (default) ``funding_provided`` is already net of them, so they are reported
    but not subtracted again; with ``"gross"`` it is the amount before they are withheld (excluding
    ``paid_on_behalf``) and they are subtracted (12 CFR 1026.18(b)(3)). ``split_schedule`` = [[from_month, rate], ...] for a split
    that changes over time (month 1 = the first month after funding); otherwise ``split_rate`` applies
    throughout."""
    if state not in STATES:
        raise ValueError(f"state must be one of {STATES}")
    if frequency not in FREQUENCIES:
        raise ValueError(f"frequency must be one of {FREQUENCIES}")
    for name, v in (("funding_provided", funding_provided), ("total_owed", total_owed),
                    ("avg_monthly_sales", avg_monthly_sales)):
        if not (isinstance(v, (int, float)) and math.isfinite(v) and v > 0):
            raise ValueError(f"{name} must be a positive number")
    if not all(math.isfinite(v) and v >= 0 for v in (prepaid_fees, minimum_payment, paid_on_behalf)):
        raise ValueError("fees, minimum payment and amounts paid on behalf must be zero or positive")
    raw = split_schedule or [[1, split_rate]]
    if any(isinstance(m, bool) or not isinstance(m, (int, float)) or m != int(m) or m < 1 for m, _ in raw):
        raise ValueError("split_schedule months must be whole numbers from 1 (month 1 = first month after funding)")
    if len({int(m) for m, _ in raw}) != len(raw):
        raise ValueError("split_schedule lists the same month twice")
    steps = sorted((int(m), float(r)) for m, r in raw)
    if steps[0][0] != 1:
        steps = [(1, float(split_rate)), *steps]
    if any(not (0 < r <= 1) for _, r in steps):
        raise ValueError("split rates must be between 0 and 1")
    if funding_basis not in ("net", "gross"):
        raise ValueError("funding_basis must be 'net' (cash after fees are withheld) or 'gross'")
    if funding_basis == "gross" and prepaid_fees >= funding_provided:
        raise ValueError("prepaid fees must be less than the gross funding")
    # 12 CFR 1026.18(b)(3): prepaid finance charges are not part of the amount financed. A net figure
    # already excludes them; a gross one has them subtracted here (as products.mca_fixed does with fees).
    cash = funding_provided - prepaid_fees if funding_basis == "gross" else funding_provided
    amount_financed = cash + paid_on_behalf
    if total_owed <= amount_financed:
        raise ValueError("total owed must exceed the amount financed")
    limit = P.param("ca_cfdl_max_amount" if state == "CA" else "ny_cfdl_max_amount")
    n = periods_per_year(frequency, funding_date, holidays)
    fd = parse(funding_date)
    rate_for = lambda m: [r for start, r in steps if start <= m][-1]
    flows, owed, k = [A.Flow(fd, amount_financed)], total_owed, 0
    d = fd
    pays = []
    while owed > 1e-9:
        k += 1
        if k > 20_000:
            raise ValueError("the estimated payments do not repay the amount owed; check the split and sales")
        d = business_days_after(d, 1, holidays)[0] if frequency == "business_day" else \
            (add_months(fd, k) if frequency == "month" else fd + timedelta(k * {"day": 1, "week": 7, "biweek": 14}[frequency]))
        per = max(rate_for(_months_since(fd, d)) * avg_monthly_sales * 12 / n, minimum_payment)
        amt = min(per, owed)
        flows.append(A.Flow(d, -amt))
        pays.append(amt)
        owed -= amt
    unit = {"business_day": "day", "day": "day", "week": "week", "biweek": "biweek", "month": "month"}[frequency]
    first, last = cast(date, flows[0].when), cast(date, flows[-1].when)
    term_days = (last - first).days
    total_pay = sum(pays)
    apr_a = A.apr_actuarial(flows, unit)
    apr_u = A.apr_us_rule(flows, unit)
    irregular_why = A.irregular_features(flows)
    out = {
        "state": state,
        "covered": amount_financed <= limit,
        "coverage_limit": limit,
        "coverage_basis": "amount financed (funding provided net of prepaid fees + amounts paid on the "
                          "recipient's behalf); "
                          "check the exemptions too (Cal. Fin. Code 22801; 23 NYCRR 600.19)",
        "funding_provided": round(funding_provided, 2),
        "paid_on_behalf": round(paid_on_behalf, 2),
        "prepaid_fees": round(prepaid_fees, 2),
        "funding_basis": funding_basis,
        "amount_financed": round(amount_financed, 2),
        "estimated_apr_actuarial": apr_a,
        "estimated_apr_us_rule": apr_u,
        "irregular": bool(irregular_why),
        "irregular_features": irregular_why,
        "holiday_calendar": "Federal Reserve" if holidays == "frb" else ("none" if not holidays else "custom"),
        "_schedule": [(f.when, f.amount) for f in flows],
        "finance_charge": round(total_pay - amount_financed, 2),
        "estimated_total_payment_amount": round(total_pay, 2),
        "estimated_payment": round(sum(pays) / len(pays), 2),
        "first_payment": round(pays[0], 2),
        "payment_frequency": frequency,
        "number_of_payments": len(pays),
        "estimated_term_days": term_days,
        "estimated_term_months": round(term_days / 30.4, 1),
        "estimated_monthly_cost": round(total_pay / (term_days / 30.4), 2) if frequency != "month" else None,
        "assumed_average_monthly_sales": round(avg_monthly_sales, 2),
        "split_schedule": [[m, r] for m, r in steps],
        "unit_period": unit,
        "last_payment_date": last.isoformat(),
        "modeled": ["split rate (or stepped split schedule)", "contractual minimum debit",
                    "prepaid fees (" + ("subtracted from the gross funding" if funding_basis == "gross"
                                       else "assumed already withheld from funding_provided") + ")",
                    "amounts paid on the recipient's behalf", "Federal Reserve business-day calendar"],
        "not_modeled": list(NOT_MODELED_ESTIMATE),
        "sources": ["10 CCR 930, 940, 942, 914, 955" if state == "CA" else "23 NYCRR 600.3, 600.4, 600.6-600.8"],
        "caveat": "Educational reproduction of the estimate math under the inputs given; not a compliance "
                  "certification. A result is only as complete as the contract features entered.",
    }
    if funding_basis == "net" and 0 < prepaid_fees < funding_provided:
        # The input is ambiguous: a contract's headline funding figure is often BEFORE the fee is withheld.
        # Report the other reading next to this one instead of guessing (the gross reading is never lower).
        try:
            g = estimate(funding_provided, total_owed, split_rate, avg_monthly_sales, frequency, funding_date,
                         prepaid_fees, minimum_payment, holidays, state, paid_on_behalf, split_schedule, "gross")
        except ValueError as e:     # e.g. no APR solves the gross reading: report that, keep the net result
            out["if_funding_provided_is_before_fees"] = {"error": str(e)}
            return out
        out["if_funding_provided_is_before_fees"] = {
            "amount_financed": g["amount_financed"], "estimated_apr_actuarial": g["estimated_apr_actuarial"],
            "estimated_apr_us_rule": g["estimated_apr_us_rule"], "covered": g["covered"]}
        out["warning"] = (f"prepaid_fees were treated as already withheld from funding_provided (funding_basis "
                          f"'net'). If {funding_provided:,.2f} is the amount BEFORE the fee, the estimated APR is "
                          f"{g['estimated_apr_actuarial']:.2%}, not {apr_a:.2%}: pass funding_basis 'gross'.")
    return out


NOT_MODELED_ESTIMATE = ("true-ups / reconciliations", "payments triggered when sales fall below a threshold",
                        "fees or charges not entered as prepaid fees", "a different payment calendar than the "
                        "Federal Reserve business-day calendar")


NOT_MODELED = ("true-ups / reconciliations", "stepped or changing split rates",
               "payments triggered when sales fall below a threshold", "fees outside the finance charge entered here",
               "a different sales history, averaging window or excluded months", "a different payment calendar")


def check_disclosed_apr(disclosed_apr: float, computed: dict, state: str = "CA", irregular=None) -> dict:
    """Is a disclosed (estimated) APR reproduced by either permitted Appendix J method?

    A match means the disclosed figure is consistent with the inputs given. No match does NOT prove the
    disclosure is wrong: the contract may have features this estimate does not model (listed in
    ``not_modeled``), or the provider may have used different sales data."""
    if not (isinstance(disclosed_apr, (int, float)) and math.isfinite(disclosed_apr)) or disclosed_apr < 0:
        raise ValueError("disclosed_apr must be a finite, non-negative decimal (e.g. 0.6781 for 67.81%)")
    if disclosed_apr > 20:
        raise ValueError("disclosed_apr looks like a percentage; pass a decimal (0.6781, not 67.81)")
    if irregular is None:
        irregular = bool(computed.get("irregular", False))
    res = {}
    for method, key in (("actuarial", "estimated_apr_actuarial"), ("us_rule", "estimated_apr_us_rule")):
        v = computed[key]
        ok = A.within_tolerance(disclosed_apr, v, irregular)
        if not ok and disclosed_apr > 0:
            # CA 10 CCR 955(a) and NY 23 NYCRR 600.4(a): percentage difference = (determined - disclosed)
            # / disclosed x 100, accurate if 2.5 or less (signed, as written).
            ok = (v - disclosed_apr) / disclosed_apr * 100 <= 2.5 + 1e-12
        res[method] = {"computed": v, "consistent": ok}
    matches = [m for m, r in res.items() if r["consistent"]]
    if matches:
        verdict = "consistent (" + " and ".join({"actuarial": "actuarial method",
                                                 "us_rule": "U.S. Rule method"}[m] for m in matches) + ")"
    else:
        verdict = "not reproduced by either permitted method with these inputs"
    tol_note = (f"{'CA 10 CCR 955(a)' if state == 'CA' else 'NY 23 NYCRR 600.4(a)'}: accurate within 1/8 point "
                f"(1/4 if irregular; this schedule was treated as {'irregular' if irregular else 'regular'}) "
                "or a signed percentage difference (determined - disclosed) / disclosed of 2.5% or less")
    out = {"disclosed": disclosed_apr, "methods": res, "verdict": verdict, "tolerance": tol_note,
           "irregular": irregular,
           "scope": "A match means the disclosed APR is consistent with the inputs and modeled features only "
                    "(see 'modeled' and 'not_modeled' in the estimate). It is not a compliance certification."}
    if not matches:
        out["what_to_check"] = ("This is not proof the disclosure is wrong. Before concluding anything, check "
                                "whether the contract has features this estimate does not model.")
        out["not_modeled"] = list(NOT_MODELED)
    return out
