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
from typing import List, Optional, Sequence, Tuple, Union, cast

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


class _Units(dict):
    """The named unit-periods plus any multiple of a week (up to 52) or a month (up to 12), written
    e.g. "6week" or "4month" (Appendix J (b)(3)(iii): multiples of a week or a month up to a year)."""

    def _parse(self, key):
        import re
        m = re.fullmatch(r"(\d+)(week|month)", str(key))
        if not m:
            return None
        k, kind = int(m.group(1)), m.group(2)
        if kind == "week" and 1 <= k <= 52:
            return (52 / k, "days", 7 * k)
        if kind == "month" and 1 <= k <= 12:
            return (12 / k, "month", 1) if k == 1 else (12 / k, "months30", 30 * k)
        return None

    def __missing__(self, key):
        v = self._parse(key)
        if v is None:
            raise KeyError(f"unknown unit-period {key!r}")
        return v

    def __contains__(self, key):
        return dict.__contains__(self, key) or self._parse(key) is not None


UNITS = _Units(UNITS)
_MONTH_NAMES = {1: "month", 2: "bimonth", 3: "quarter", 6: "semiannual", 12: "year"}
_WEEK_NAMES = {1: "week", 2: "biweek", 3: "3week", 4: "4week"}


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
            if isinstance(w, bool) or isinstance(a, bool):
                raise ValueError("a flow is [date-or-period, amount]; true/false is neither")
            out.append(Flow(w if isinstance(w, (int, float)) else parse(w), float(a)))
    if not out:
        raise ValueError("flows is empty: give at least one advance and one payment")
    if len({isinstance(f.when, (int, float)) for f in out}) > 1:
        raise ValueError("flows mix dates and numeric period positions; use one or the other")
    return out


_STANDARD_DAYS = {"day": 1, "week": 7, "biweek": 14, "3week": 21, "4week": 28}
_ORDER = ["day", "week", "biweek", "3week", "semimonth", "4week", "month", "bimonth", "quarter",
          "semiannual", "year"]
_APPROX = {"day": 1, "week": 7, "biweek": 14, "3week": 21, "semimonth": 15.2, "4week": 28, "month": 30.4,
           "bimonth": 60.8, "quarter": 91.3, "semiannual": 182.6, "year": 365.25}


def _is_month_end(d: date) -> bool:
    return (d + timedelta(1)).month != d.month


def _nominal_day(d: date, anchor: int | None) -> int:
    """A short month's last day stands for the series' nominal day (Appendix J (b)(3)(iv))."""
    return anchor if anchor and _is_month_end(d) and d.day < anchor else d.day


def _exact_interval(a: date, b: date, anchor: int | None = None):
    """The standard interval the gap a -> b is EXACTLY: a multiple of a month (checked first, so Feb 1 ->
    Mar 1 is a month, not four weeks; month-end clamping honoured, and with ``anchor`` - the series'
    nominal day of the month - Feb 28 -> Mar 29/30/31 in a series on the 29th/30th/31st is one month), a
    semimonth, or a multiple of a week, up to a year. Otherwise the raw day count, so irregular gaps
    never merge."""
    m = (b.year - a.year) * 12 + b.month - a.month
    if 1 <= m <= 12 and (add_months(a, m) == b or (_is_month_end(b) and a.day >= b.day)
                         or (anchor is not None and _nominal_day(a, anchor) == _nominal_day(b, anchor))):
        return _MONTH_NAMES.get(m, f"{m}month")
    days = (b - a).days
    if 13 <= days <= 17:
        same = (a.year, a.month) == (b.year, b.month)
        if (same and (b.day - a.day == 15 or (a.day == 15 and _is_month_end(b)))) or \
                (not same and (a.day - b.day == 15 or (_is_month_end(a) and b.day == 15))):
            return "semimonth"
    if days == 1:
        return "day"
    if days % 7 == 0 and 1 <= days // 7 <= 52:
        k = days // 7
        return _WEEK_NAMES.get(k, f"{k}week")
    return days


# Every standard interval of (b)(3)(iii) - a day, a semimonth, any multiple of a week or of a month up
# to a year - with its approximate length, for rounding an average period ((b)(4)(i)(B)).
# Lengths in tenths of a day (integers, so ties compare exactly).
_STANDARD = {"day": 10, "semimonth": 152,
             **{_WEEK_NAMES.get(k, f"{k}week"): 70 * k for k in range(1, 53)},
             **{_MONTH_NAMES.get(k, f"{k}month"): round(10 * _APPROX.get(_MONTH_NAMES.get(k, ""), 30.4 * k))
                for k in range(1, 13)}}


def _approx_days(name) -> float:
    return _APPROX.get(name) or 365.25 / UNITS[name][0]


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
    pa = series_day(pays) if pays else None
    aa = series_day(advs) if advs else None
    kinds = [_exact_interval(a, b, pa) for a, b in zip(pays, pays[1:])] + \
            [_exact_interval(a, b, aa) for a, b in zip(advs, advs[1:])]
    if advs and pays and advs[0] < pays[0]:
        kinds.append(_exact_interval(advs[0], pays[0], pa))
    counts = Counter(kinds)
    days = lambda k: _approx_days(k) if isinstance(k, str) else k
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
    total, count = sum((b - a).days for a, b in gaps), len(gaps)
    # |L/10 - total/count| compared exactly as |L*count - 10*total|, so a true tie goes to the shorter
    return min(_STANDARD, key=lambda n: (abs(_STANDARD[n] * count - 10 * total), _STANDARD[n]))


def _back(d: date, months: int, anchor: int | None = None) -> date:
    """``months`` before ``d``. ``anchor`` is the payment series' nominal day of the month: a payment on a
    short month's last day whose nominal day does not exist there (the 30th in February) steps back to
    the nominal day, so a month-end or 30th-of-month series runs whole months (Appendix J (b)(3)(iv))."""
    p = add_months(d, -months)
    if anchor and _is_month_end(d) and d.day < anchor:
        last = (date(p.year + (p.month == 12), p.month % 12 + 1, 1) - timedelta(1)).day
        p = p.replace(day=min(anchor, last))
    return p


def _months_back(base: date, d: date, step: int = 1, anchor: int | None = None):
    """Full ``step``-month periods measured back from ``d`` without passing ``base``, and the date reached."""
    t, cur = 0, d
    while True:
        prev = _back(d, (t + 1) * step, anchor)
        if prev < base:
            return t, cur
        cur, t = prev, t + 1


def series_day(dates: Sequence[date]) -> int:
    """Nominal day of the month for payments that fall on a month's last day (Appendix J (b)(3)(iv)):
    * the most common late day (28th-30th) among the other payments - a 30th-of-month series whose
      February payment is the 28th;
    * else 31 (a month-end series) when month-end payments are at least as common as any other day,
      so a single mid-month payment does not move a month-end schedule;
    * else the most common day, and an isolated month-end date is measured to the same date."""
    regular = Counter(d.day for d in dates if not _is_month_end(d))
    late = Counter({k: c for k, c in regular.items() if k >= 28})
    if late:
        return max(late, key=lambda k: (late[k], -k))
    ends = sum(1 for d in dates if _is_month_end(d))
    if not regular or ends >= max(regular.values()):
        return 31
    return max(regular, key=lambda k: (regular[k], -k))


def period_position(base: date, d: date, unit: str, anchor: int | None = None) -> Tuple[int, float]:
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
        t, cur = _months_back(base, d, 1, anchor)
        return t, (cur - base).days / dpm
    if rule == "months30":
        months, cur = _months_back(base, d, 1, anchor)
        days = dpm * months + (cur - base).days
        return int(days // size), (days % size) / size
    # year
    t, cur = _months_back(base, d, 12, anchor)
    months, cur2 = _months_back(base, cur, 1, anchor)
    if cur2 == base:
        return t, months / 12
    return t, (cur - base).days / 365


def _positions(flows: List[Flow], unit: str):
    if all(isinstance(f.when, (int, float)) for f in flows):
        nums = [(cast(float, f.when), f.amount) for f in flows]
        return [(math.floor(w + 1e-12), w - math.floor(w + 1e-12), a) for w, a in nums]
    dated = [(cast(date, f.when), f.amount) for f in flows]
    base = min(d for d, _ in dated)    # zero point: the earliest flow (Appendix J (c)(7)(ii))
    pays = [d for d, a in dated if a < 0]
    if len(pays) >= 2:
        anchor: int | None = series_day(pays)
    else:
        # One payment is not a series: it has no nominal day of its own, so it is measured back to the zero
        # point's day, as apr_single_payment does (Jan 28 -> Feb 28 is one month, Jan 31 -> Feb 28 too).
        anchor = base.day if base.day > 28 else None
    return [period_position(base, d, unit, anchor) + (a,) for d, a in dated]


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
        (xa, va), (_xb, vb), (xc, vc) = pts[k - 1], pts[k], pts[k + 1]
        for sign in (1, -1):                      # a minimum of sign*f that might cross zero
            if sign * vb <= sign * va and sign * vb <= sign * vc and sign * vb > 0:
                xm, fm = _golden_min(lambda x, s=sign: s * fn(x), xa, xc)
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
    rs: List[float] = []
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


def _conventional(keys_amounts) -> bool:
    """True when every advance sits at the earliest position and every payment at or after it.

    The equation is then strictly increasing in the rate on (-0.5, inf): divide it by the advance's
    discount factor and each payment's relative factor (1+f0 i)/((1+fk i)(1+i)^(tk-t0)) falls as the rate
    rises (f0 < 1). So exactly one rate solves it, and bisection finds it without a scan."""
    adv = {k for k, a in keys_amounts if a > 0}
    if len(adv) != 1:
        return False
    k0 = next(iter(adv))
    return all(k >= k0 for k, a in keys_amounts if a < 0)


def _monotone_root(fn, neg_floor: float, hi: float) -> Optional[float]:
    """The single root of an increasing ``fn`` in [neg_floor, hi], or None. Endpoints that solve exactly
    count; a lower end too far out to evaluate (overflow over a long schedule) is moved toward zero."""
    f0 = fn(0.0)
    if f0 == 0:
        return 0.0
    if f0 > 0:
        lo = neg_floor
        while True:
            try:
                flo = fn(lo)
                break
            except (OverflowError, ZeroDivisionError):
                lo /= 2
                if lo > -1e-12:
                    return None
        if flo == 0:
            return lo
        return _bisect(fn, lo, 0.0) if flo < 0 else None
    x, prev = 1e-3, 0.0
    while True:
        try:
            fx = fn(x)
        except (OverflowError, ZeroDivisionError):
            return None
        if fx == 0:
            return x
        if fx > 0:
            return _bisect(fn, prev, x)
        if x >= hi:
            return None
        prev, x = x, min(x * 4, hi)


def _rate(fn, neg_floor: float, hi: float = 1e4, monotone: bool = False) -> float:
    """Smallest positive solving rate; if none, the solving rate in (neg_floor, 0]."""
    probe = [fn(x) for x in (0.0, 0.01, 0.5)]
    if all(abs(v) < 1e-12 for v in probe):
        raise ValueError("every rate solves these cash flows (advances equal payments at the same time): "
                         "the APR is undefined")
    if monotone:
        r = _monotone_root(fn, neg_floor, hi)
        if r is None:
            raise ValueError("no APR solves these cash flows (check signs: advances +, payments -)")
        return r
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
    return _rate(fn, -0.5, monotone=_conventional([((t, f), a) for t, f, a in pos]))


def _single_pair(fl: List[Flow]):
    if len(fl) == 2 and all(isinstance(f.when, date) for f in fl):
        adv = [f for f in fl if f.amount > 0]
        pay = [f for f in fl if f.amount < 0]
        if len(adv) == 1 and len(pay) == 1 and cast(date, adv[0].when) < cast(date, pay[0].when):
            return adv[0], pay[0]
    return None


def count_rates(flows, unit: str = "month") -> int:
    """How many positive periodic rates solve the actuarial equation (more than one is a warning sign)."""
    pos = _positions(_flows(flows), unit)
    fn = lambda i: _pv(pos, i)
    if _conventional([((t, f), a) for t, f, a in pos]):
        return 0 if _monotone_root(fn, 0.0, 1e4) is None else 1
    return len(roots(fn, 0.0, 1e4))


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
    events = pos if pos and len(pos[0]) == 2 else sorted(((t + f), a) for t, f, a in pos)
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
    events = sorted(((t + f), a) for t, f, a in pos)       # sort once, not on every evaluation
    fn = lambda i: _us_rule_residual(events, i)
    # With every advance first, a higher rate accrues more interest, so less of each payment reaches
    # principal and the final balance cannot fall: one positive root. (Below zero that argument fails,
    # so a negative rate still gets the full scan.)
    monotone = _conventional([((t, f), a) for t, f, a in pos]) and fn(0.0) < 0
    return _rate(fn, -0.5, monotone=monotone)


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
    return infer_unit([cast(date, f.when) for f in fl if f.amount < 0],
                      [cast(date, f.when) for f in fl if f.amount > 0])


def ear(apr: float, unit: str) -> float:
    """Effective annual rate implied by an APR compounded once per unit period."""
    n = UNITS[unit][0]
    return (1 + apr / n) ** n - 1


def xirr(flows) -> float:
    """Annual IRR on actual days / 365 (Excel XIRR convention). Flows must be dated."""
    fl = _flows(flows)
    dated = [(cast(date, f.when), f.amount) for f in fl]
    base = min(d for d, _ in dated)
    pos = [((d - base).days / 365.0, a) for d, a in dated]
    fn = lambda r: sum(a * math.exp(-y * math.log1p(r)) for y, a in pos)
    return _rate(fn, -0.9, hi=1e80, monotone=_conventional(pos))


def simple_annualized(net_advance: float, total_repaid: float, term_years: float) -> float:
    """The number brokers often quote: (cost / amount) / term in years. Not an APR."""
    return (total_repaid - net_advance) / net_advance / term_years


def irregular_features(flows) -> List[str]:
    """Why a transaction is "irregular" for the 1/4-point tolerance (12 CFR 1026.22(a)(3); CA 10 CCR
    955(a)(2)): more than one advance; payment periods that are not all the same (the first period is
    ignored); payment amounts that differ (the first and last payments are ignored). An empty list means
    regular. A business-day debit series mixes 1-day and weekend gaps, so on a literal reading its payment
    periods are irregular."""
    fl = sorted(_flows(flows), key=lambda f: (f.when if isinstance(f.when, (int, float)) else f.when.toordinal()))
    adv = [f for f in fl if f.amount > 0]
    pay = [f for f in fl if f.amount < 0]
    out = []
    if len(adv) > 1:
        out.append("more than one advance")
    if len(pay) >= 3:
        kinds: set
        if all(isinstance(f.when, date) for f in pay):
            ds = [cast(date, f.when) for f in pay]
            kinds = {_exact_interval(a, b, series_day(ds)) for a, b in zip(ds, ds[1:])}
        else:
            ts = [cast(float, f.when) for f in pay]
            kinds = {round(b - a, 9) for a, b in zip(ts, ts[1:])}
        if len(kinds) > 1:
            out.append("irregular payment periods")
    middle = [round(-f.amount, 2) for f in pay[1:-1]]
    if len(set(middle)) > 1:
        out.append("irregular payment amounts")
    return out


def finance_charge_at_apr(flows, annual_rate: float, unit: str) -> float:
    """The finance charge a schedule would have if its APR were ``annual_rate``: total payments minus the
    amount financed that ``annual_rate`` implies (the actuarial present value of the payments)."""
    fl = _flows(flows)
    pos = _positions(fl, unit)
    i = annual_rate / UNITS[unit][0]
    pay = [(t, f, -a) for t, f, a in pos if a < 0]
    implied_af = sum(a * math.exp(-t * math.log1p(i)) / (1 + f * i) for t, f, a in pay)
    total = sum(a for _, _, a in pay)
    return total - implied_af


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
        months, cur = _months_back(d0, d1, 1, d0.day if d0.day > 28 else None)
        w = 12 / months if (cur == d0 and months) else 365 / (d1 - d0).days
        return w * (payment / advance - 1)
    return apr_actuarial([(d0, advance), (d1, -payment)], "year")
