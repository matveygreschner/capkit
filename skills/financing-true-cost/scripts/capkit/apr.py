"""Annual percentage rate by Regulation Z Appendix J, plus effective annual rate and the naive quotes.

Two Appendix J methods are implemented, because 12 CFR 1026.22(a)(1) and 10 CCR 940(a) permit either:

* :func:`apr_actuarial` - the general equation. Every advance and payment is discounted by
  ``(1 + f*i) * (1 + i)**t`` where ``t`` is the number of whole unit periods and ``f`` the fraction of
  a unit period between the flow and the first advance. Payments are applied first to the finance
  charge, any unpaid finance charge compounding with the balance.
* :func:`apr_us_rule` - the United States Rule: each payment pays accrued interest first, then
  principal, and interest is never charged on unpaid interest.

The two give the same rate whenever every payment covers the interest accrued since the previous
flow, and differ when one does not (deferred payments, zero-payment periods).

Cash flows are ``Flow(when, amount)`` with ``amount > 0`` money to the borrower (advances, net of any
prepaid finance charge) and ``amount < 0`` money from the borrower (payments). ``when`` is either a
:class:`datetime.date` or a number of unit periods from the first advance (a float: whole part = t,
fractional part = f), which is the form used by the period-grid products and the tests.
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from datetime import date
from typing import Iterable, List, Sequence, Tuple, Union

from .calendar import add_months, parse
from .params import param

UNITS = {
    # name: (unit-periods per year w, counting rule, size). Appendix J (b)(5).
    "day": (365, "days", 1),
    "week": (52, "days", 7),
    "biweek": (26, "days", 14),
    "4week": (13, "days", 28),
    "semimonth": (24, "months30", 15),
    "month": (12, "month", 1),
    "bimonth": (6, "months30", 60),
    "quarter": (4, "months30", 90),
    "semiannual": (2, "months30", 180),
    "year": (1, "year", 12),
}


@dataclass(frozen=True)
class Flow:
    when: Union[date, float]
    amount: float


def _flows(flows) -> List[Flow]:
    out = []
    for f in flows:
        if isinstance(f, Flow):
            out.append(f)
        else:
            w, a = f
            out.append(Flow(w if isinstance(w, (int, float)) else parse(w), float(a)))
    return out


def infer_unit(dates: Sequence[date]) -> str:
    """Appendix J (b)(3): the unit period is the most common interval between payments."""
    ds = sorted(dates)
    gaps = [(b - a).days for a, b in zip(ds, ds[1:])]
    if not gaps:
        return "month"
    common = Counter(min(max(g, 1), 400) for g in gaps).most_common(1)[0][0]
    if common <= 1:
        return "day"
    if common <= 4 and any(g in (3, 4) for g in gaps) and gaps.count(1) >= len(gaps) / 2:
        return "day"   # Monday-Friday debits: the most common gap is one day
    for name, lo, hi in (("week", 5, 9), ("biweek", 12, 16), ("semimonth", 13, 17), ("month", 27, 32),
                         ("quarter", 88, 93), ("semiannual", 180, 185), ("year", 360, 367)):
        if lo <= common <= hi:
            return name
    return "day"


def _months_back(base: date, d: date, step: int = 1):
    """Full ``step``-month periods measured back from ``d`` without passing ``base``, and the date reached."""
    t, cur = 0, d
    while True:
        prev = add_months(d, -(t + 1) * step)
        if prev < base:
            return t, cur
        cur, t = prev, t + 1


def period_position(base: date, d: date, unit: str) -> Tuple[int, float]:
    """(t, f): whole unit-periods and the remaining fraction from ``base`` to ``d`` (Appendix J (b)(5)).

    * (ii) monthly: full months measured back from the later date; the remaining days, counted forward
      from the earlier date to the start of the first full month, divided by 30.
    * (iii) semimonthly / multi-month: days = 30 x full months back + remaining days, divided by 15 or
      by 30 x months.
    * (iv) day / week / multiples of a week: days divided by the days in a unit-period.
    * (v) year: full years back; the remainder is months/12 if a whole number of months, else days/365.
    """
    if d < base:
        raise ValueError("flow dated before the zero point")
    _, rule, size = UNITS[unit]
    if rule == "days":
        days = (d - base).days
        return days // size, (days % size) / size
    dpm = param("appj_days_per_month")
    if rule == "month":
        t, cur = _months_back(base, d)
        return t, (cur - base).days / dpm
    if rule == "months30":
        months, cur = _months_back(base, d)
        days = dpm * months + (cur - base).days
        return int(days // size), (days % size) / size
    # year
    t, cur = _months_back(base, d, 12)
    months, cur2 = _months_back(base, cur)
    if cur2 == base:
        return t, months / 12
    return t, (cur - base).days / 365


def _positions(flows: List[Flow], unit: str):
    if all(isinstance(f.when, (int, float)) for f in flows):
        return [(int(math.floor(f.when + 1e-12)), f.when - math.floor(f.when + 1e-12), f.amount) for f in flows]
    base = min(f.when for f in flows)    # zero point: the earliest flow (Appendix J (c)(7)(ii))
    return [period_position(base, f.when, unit) + (f.amount,) for f in flows]


def _pv(pos, i):
    li = math.log1p(i)
    return sum(a * math.exp(-t * li) / (1 + f * i) for t, f, a in pos)


def _solve(fn, lo: float = 0.0, hi: float = 1.0) -> float:
    """Smallest root of ``fn`` above ``lo`` (or the root in [lo, hi] for a negative-rate bracket).

    A coarse geometric scan finds the first sign change (cash flows that start with a payment, as in
    Appendix J (c)(7)(ii), make the function non-monotone), then bisection to machine precision."""
    if lo < 0:
        grid = [lo + (hi - lo) * k / 200 for k in range(201)]
    else:
        grid = [0.0] + [1e-7 * 1.25 ** k for k in range(105)]
    vals = [fn(x) for x in grid]
    for (x0, v0), (x1, v1) in zip(zip(grid, vals), zip(grid[1:], vals[1:])):
        if v0 == 0:
            return x0
        if v0 * v1 < 0:
            lo, hi, flo = x0, x1, v0
            break
    else:
        raise ValueError("no APR solves these cash flows (check signs: advances +, payments -)")
    for _ in range(200):
        mid = (lo + hi) / 2
        fm = fn(mid)
        if fm == 0 or hi - lo < 1e-16:
            return mid
        if (fm > 0) == (flo > 0):
            lo, flo = mid, fm
        else:
            hi = mid
    return (lo + hi) / 2


def _sign_positive_rate(fn) -> bool:
    """True when the cash flows cost the borrower something, i.e. the rate is positive."""
    try:
        _solve(fn)
        return True
    except ValueError:
        return False


def periodic_rate_actuarial(flows, unit: str = "month") -> float:
    pos = _positions(_flows(flows), unit)
    fn = lambda i: _pv(pos, i)
    return _solve(fn) if _sign_positive_rate(fn) else _solve(fn, -0.5, 0.0)


def apr_actuarial(flows, unit: str | None = None) -> float:
    """APR (as a decimal, e.g. 0.1896) by the Appendix J actuarial method."""
    fl = _flows(flows)
    unit = unit or _default_unit(fl)
    return periodic_rate_actuarial(fl, unit) * UNITS[unit][0]


def _us_rule_residual(pos, i):
    """Balance left after the last flow under the U.S. Rule at periodic rate ``i`` (positive = still owed)."""
    events = sorted(((t + f), a) for t, f, a in pos)
    principal = interest = 0.0
    prev = events[0][0]
    for when, a in events:
        interest += principal * i * (when - prev)
        prev = when
        if a > 0:
            principal += a
        else:
            pay = -a
            to_int = min(pay, interest)
            interest -= to_int
            principal -= pay - to_int
    return principal + interest


def periodic_rate_us_rule(flows, unit: str = "month") -> float:
    pos = _positions(_flows(flows), unit)
    fn = lambda i: _us_rule_residual(pos, i)
    return _solve(fn) if _sign_positive_rate(fn) else _solve(fn, -0.5, 0.0)


def apr_us_rule(flows, unit: str | None = None) -> float:
    """APR by the Appendix J United States Rule method."""
    fl = _flows(flows)
    unit = unit or _default_unit(fl)
    return periodic_rate_us_rule(fl, unit) * UNITS[unit][0]


def _default_unit(fl: List[Flow]) -> str:
    if all(isinstance(f.when, (int, float)) for f in fl):
        return "month"
    return infer_unit([f.when for f in fl if f.amount < 0])


def ear(apr: float, unit: str) -> float:
    """Effective annual rate implied by an APR compounded once per unit period."""
    n = UNITS[unit][0]
    return (1 + apr / n) ** n - 1


def xirr(flows) -> float:
    """Annual IRR on actual days / 365 (Excel XIRR convention). Flows must be dated."""
    fl = _flows(flows)
    base = min(f.when for f in fl)
    pos = [((f.when - base).days / 365.0, f.amount) for f in fl]
    fn = lambda r: sum(a * math.exp(-y * math.log1p(r)) for y, a in pos)
    return _solve(fn) if _sign_positive_rate(fn) else _solve(fn, -0.9, 0.0)


def simple_annualized(net_advance: float, total_repaid: float, term_years: float) -> float:
    """The number brokers often quote: (cost / amount) / term in years. Not an APR."""
    return (total_repaid - net_advance) / net_advance / term_years


def within_tolerance(disclosed: float, computed: float, irregular: bool = False) -> bool:
    tol = param("regz_tolerance_irregular" if irregular else "regz_tolerance_regular") / 100
    return abs(disclosed - computed) <= tol + 1e-12


def apr_single_payment(advance: float, payment: float, advance_date, payment_date) -> float:
    """Single advance repaid by a single payment (Appendix J (b)(4)(ii), (b)(5)(vi)-(vii), (c)(5)).

    The unit-period is the term, capped at one year. Under a year: APR = w x (P/A - 1) with
    w = 12 / months for a whole number of months, else 365 / days. A year or more: the yearly unit
    with the general equation."""
    d0, d1 = parse(advance_date), parse(payment_date)
    if add_months(d0, 12) > d1:
        months, cur = _months_back(d0, d1)
        w = 12 / months if (cur == d0 and months) else 365 / (d1 - d0).days
        return w * (payment / advance - 1)
    return apr_actuarial([(d0, advance), (d1, -payment)], "year")
