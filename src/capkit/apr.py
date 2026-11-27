"""Annual percentage rate by Regulation Z Appendix J, plus effective annual rate and the naive quotes.

Two Appendix J methods are implemented, because 12 CFR 1026.22(a)(1) and 10 CCR 940(a) permit either:

* :func:`apr_actuarial` - the general equation. Every advance and payment is discounted by
  ``(1 + f*i) * (1 + i)**t`` where ``t`` is the number of whole unit periods and ``f`` the fraction of
  a unit period between the flow and the first advance. Payments are applied first to the finance
  charge, any unpaid finance charge compounding with the balance.
* :func:`apr_us_rule` - the United States Rule: each payment pays accrued interest first, then
  principal, and interest is never charged on unpaid interest.

The two can give different rates: with zero-payment periods, deferred payments, or fractional
periods. On whole-period schedules where every payment covers accrued interest they agree.

Cash flows are ``Flow(when, amount)`` with ``amount > 0`` money to the borrower (advances, net of any
prepaid finance charge) and ``amount < 0`` money from the borrower (payments). ``when`` is either a
:class:`datetime.date` or a number of unit periods from the first advance (a float: whole part = t,
fractional part = f), which is the form used by the period-grid products and the tests.
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable, List, Sequence, Tuple, Union

from .calendar import add_months, parse
from .params import param

UNITS = {
    # name: (unit-periods per year w, counting rule, size). Appendix J (b)(5).
    "day": (365, "days", 1),
    "week": (52, "days", 7),
    "biweek": (26, "days", 14),
    "3week": (52 / 3, "days", 21),
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


_STANDARD_DAYS = {"day": 1, "week": 7, "biweek": 14, "3week": 21, "4week": 28}
_ORDER = ["day", "week", "biweek", "3week", "semimonth", "4week", "month", "bimonth", "quarter",
          "semiannual", "year"]
_APPROX = {"day": 1, "week": 7, "biweek": 14, "3week": 21, "semimonth": 15.2, "4week": 28, "month": 30.4,
           "bimonth": 60.8, "quarter": 91.3, "semiannual": 182.6, "year": 365.25}


def _is_month_end(d: date) -> bool:
    return (d + timedelta(1)).month != d.month


def _exact_interval(a: date, b: date):
    """The standard interval the gap a -> b is EXACTLY (month steps honour month-end clamping), or the
    raw day count when it is none. Inexact gaps never merge into a standard interval, so irregular
    schedules cannot manufacture a common period."""
    for name, k in (("year", 12), ("semiannual", 6), ("quarter", 3), ("bimonth", 2), ("month", 1)):
        if add_months(a, k) == b or (_is_month_end(b) and add_months(a, k).month == b.month
                                     and add_months(a, k).year == b.year and a.day >= b.day):
            return name
    days = (b - a).days
    if 13 <= days <= 16 and {a.day, b.day} <= {1, 15, 16} | {a.day if _is_month_end(a) else 0, b.day if _is_month_end(b) else 0}:
        return "semimonth"
    for name, size in _STANDARD_DAYS.items():
        if days == size:
            return name
    return days


def infer_unit(dates: Sequence[date], advances: Sequence[date] = ()) -> str:
    """Appendix J (b)(4): the unit-period is the common period, not over a year, that occurs most often
    in the transaction. Periods are counted between consecutive payments, between consecutive
    advances, and from the first advance to the first payment. On a tie the smaller period wins. With
    no common period, the average of all periods is rounded to the nearest standard interval (the
    lower if equally near). ``dates`` are payment dates (all flow dates if ``advances`` is empty)."""
    pays = sorted(set(dates))
    advs = sorted(set(advances))
    gaps = [(a, b) for a, b in zip(pays, pays[1:])] + [(a, b) for a, b in zip(advs, advs[1:])]
    if advs and pays and advs[0] < pays[0]:
        gaps.append((advs[0], pays[0]))
    if not gaps:
        return "month"
    kinds = [_exact_interval(a, b) for a, b in gaps]
    counts = Counter(kinds)
    days = lambda k: _APPROX[k] if isinstance(k, str) else k
    top = max(counts.values())
    commons = [k for k, c in counts.items() if c == top]
    if (top >= 2 or len(kinds) == 1):
        best = min(commons, key=days)
        if isinstance(best, str):
            return best
        if best <= 4 and top >= 2:       # business-day series: the common one-day period
            return "day"
    if counts.get(1, 0) >= 2 and counts[1] == top:
        return "day"
    avg = sum((b - a).days for a, b in gaps) / len(gaps)
    return min(_APPROX, key=lambda n: (abs(_APPROX[n] - avg), _APPROX[n]))


def _back(d: date, months: int, anchor: int | None = None) -> date:
    """``months`` before ``d``. A payment that fell on a short month's last day because its contractual
    day (``anchor``, e.g. the 30th or 31st) does not exist steps back to that contractual day
    (Appendix J (b)(3)(iv): month-end series run last day to last day)."""
    p = add_months(d, -months)
    if anchor and _is_month_end(d) and d.day < anchor:
        last = (date(p.year + (p.month == 12), p.month % 12 + 1, 1) - timedelta(1)).day
        p = p.replace(day=min(anchor, last))
    elif _is_month_end(d) and anchor is None:
        p = date(p.year + (p.month == 12), p.month % 12 + 1, 1) - timedelta(1)
    return p


def _months_back(base: date, d: date, step: int = 1):
    """Full ``step``-month periods measured back from ``d`` without passing ``base``, and the date reached."""
    t, cur = 0, d
    anchor = base.day if base.day > 28 else None
    while True:
        prev = _back(d, (t + 1) * step, anchor)
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


def _scan(fn, lo: float, hi: float, n: int, geometric: bool):
    if geometric:
        r = (hi / lo) ** (1 / n)
        grid = [0.0] + [lo * r ** k for k in range(n + 1)]
    else:
        grid = [lo + (hi - lo) * k / n for k in range(n + 1)]
    out = []
    for x in grid:
        try:
            out.append((x, fn(x)))
        except (OverflowError, ZeroDivisionError):
            continue
    return out


def _golden_min(fn, a, b, iters=80):
    g = (5 ** 0.5 - 1) / 2
    c, d = b - g * (b - a), a + g * (b - a)
    fc, fd = fn(c), fn(d)
    for _ in range(iters):
        if fc < fd:
            b, d, fd = d, c, fc
            c = b - g * (b - a)
            fc = fn(c)
        else:
            a, c, fc = c, d, fd
            d = a + g * (b - a)
            fd = fn(d)
    return (c, fc) if fc < fd else (d, fd)


def _brackets(fn, lo: float, hi: float, geometric: bool):
    """Every sign-change bracket of ``fn`` on [lo, hi]. A sampled scan finds ordinary crossings; local
    extrema of the samples are then searched (golden section) for a dip across zero that falls between
    two samples, e.g. two close roots such as 10.0% and 10.1% per period."""
    pts = _scan(fn, lo, hi, 400, geometric)
    out = []
    for (x0, v0), (x1, v1) in zip(pts, pts[1:]):
        if v0 == 0:
            out.append((x0, x0))
        elif v0 * v1 < 0:
            out.append((x0, x1))
    for k in range(1, len(pts) - 1):
        (xa, va), (xb, vb), (xc, vc) = pts[k - 1], pts[k], pts[k + 1]
        for sign in (1, -1):                      # a minimum of sign*f that might cross zero
            if sign * vb <= sign * va and sign * vb <= sign * vc and sign * vb > 0:
                xm, fm = _golden_min(lambda x: sign * fn(x), xa, xc)
                if fm < 0:
                    out += [(xa, xm), (xm, xc)]
    return sorted(set(out))


def _bisect(fn, lo, hi):
    if lo == hi:
        return lo
    flo = fn(lo)
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


def roots(fn, lo: float = 0.0, hi: float = 1e4):
    """All rates in [lo, hi] (per unit-period) that solve the equation."""
    if lo < 0:
        br = _brackets(fn, lo, hi, geometric=False)
    else:
        br = _brackets(fn, 1e-9, hi, geometric=True)
        try:
            if fn(0.0) == 0:
                br = [(0.0, 0.0)] + br
        except Exception:
            pass
    rs = []
    for a, b in br:
        r = _bisect(fn, a, b)
        if not rs or abs(r - rs[-1]) > 1e-4 * max(1e-3, abs(r)):     # a double root counts once
            rs.append(r)
    return rs


class MultipleRates(ValueError):
    pass


def _solve(fn, lo: float = 0.0, hi: float = 1e4) -> float:
    """The smallest rate above ``lo`` that solves the equation (or the root in [lo, hi] for a
    negative-rate bracket). Raises if there is none."""
    rs = roots(fn, lo, hi)
    if not rs:
        raise ValueError("no APR solves these cash flows (check signs: advances +, payments -)")
    return rs[0]


def _rate(fn, neg_floor: float, hi: float = 1e4) -> float:
    """Smallest positive solving rate; if none, the solving rate in (neg_floor, 0]."""
    probe = [fn(x) for x in (0.0, 0.01, 0.5)]
    if all(abs(v) < 1e-12 for v in probe):
        raise ValueError("every rate solves these cash flows (advances equal payments at the same time): "
                         "the APR is undefined")
    rs = roots(fn, 0.0, hi)
    if rs:
        return rs[0]
    rs = roots(fn, neg_floor, 0.0)
    if rs:
        return rs[-1]
    raise ValueError("no APR solves these cash flows (check signs: advances +, payments -)")


def periodic_rate_actuarial(flows, unit: str = "month") -> float:
    pos = _positions(_flows(flows), unit)
    fn = lambda i: _pv(pos, i)
    return _rate(fn, -0.5)


def _single_pair(fl: List[Flow]):
    if len(fl) == 2 and all(isinstance(f.when, date) for f in fl):
        adv = [f for f in fl if f.amount > 0]
        pay = [f for f in fl if f.amount < 0]
        if len(adv) == 1 and len(pay) == 1 and adv[0].when < pay[0].when:
            return adv[0], pay[0]
    return None


def count_rates(flows, unit: str = "month") -> int:
    """How many positive periodic rates solve the actuarial equation (more than one is a warning sign)."""
    pos = _positions(_flows(flows), unit)
    return len(roots(lambda i: _pv(pos, i), 0.0, 1e4))


def apr_actuarial(flows, unit: str | None = None) -> float:
    """APR (as a decimal, e.g. 0.1896) by the Appendix J actuarial method.

    With no ``unit`` given, a single advance repaid by a single payment uses the term as the
    unit-period (Appendix J (b)(4)(ii), (c)(5)); otherwise the most common interval is used."""
    fl = _flows(flows)
    pair = _single_pair(fl) if unit is None else None
    if pair:
        return apr_single_payment(pair[0].amount, -pair[1].amount, pair[0].when, pair[1].when)
    unit = unit or _default_unit(fl)
    return periodic_rate_actuarial(fl, unit) * UNITS[unit][0]


def _us_rule_residual(pos, i):
    """Balance left after the last flow under the U.S. Rule at periodic rate ``i`` (positive = still owed)."""
    events = sorted(((t + f), a) for t, f, a in pos)
    principal = interest = 0.0
    prev = events[0][0]
    for when, a in events:
        interest += max(principal, 0.0) * i * (when - prev)
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
    return _rate(fn, -0.5)


def apr_us_rule(flows, unit: str | None = None) -> float:
    """APR by the Appendix J United States Rule method."""
    fl = _flows(flows)
    pair = _single_pair(fl) if unit is None else None
    if pair:     # one advance, one payment: the two methods coincide
        return apr_single_payment(pair[0].amount, -pair[1].amount, pair[0].when, pair[1].when)
    unit = unit or _default_unit(fl)
    return periodic_rate_us_rule(fl, unit) * UNITS[unit][0]


def _default_unit(fl: List[Flow]) -> str:
    if all(isinstance(f.when, (int, float)) for f in fl):
        return "month"
    return infer_unit([f.when for f in fl if f.amount < 0], [f.when for f in fl if f.amount > 0])


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
    return _rate(fn, -0.9, hi=1e80)


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
