"""Business-day calendar for ACH debits (Federal Reserve holidays) and date helpers.

The Federal Reserve observes a holiday that falls on Sunday on the following Monday. A holiday that
falls on Saturday is NOT moved to Friday (unlike the OPM federal schedule): the Reserve Banks are open
that Friday, so an ACH debit still settles. Source: Federal Reserve Financial Services holiday schedule.
"""
from __future__ import annotations

from datetime import date, timedelta
from functools import cache


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    d = date(year, month, 1)
    d += timedelta((weekday - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def _last_weekday(year: int, month: int, weekday: int) -> date:
    d = date(year + (month == 12), month % 12 + 1, 1) - timedelta(1)
    return d - timedelta((d.weekday() - weekday) % 7)


@cache
def frb_holidays(year: int) -> frozenset:
    """Federal Reserve Bank holidays observed in ``year``."""
    fixed = [date(year, 1, 1), date(year, 6, 19), date(year, 7, 4), date(year, 11, 11), date(year, 12, 25)]
    out = set()
    for d in fixed:
        if d.weekday() == 6:          # Sunday -> Monday
            out.add(d + timedelta(1))
        elif d.weekday() < 5:         # Saturday holidays are not observed on Friday
            out.add(d)
    out |= {
        _nth_weekday(year, 1, 0, 3),   # Martin Luther King Jr. Day
        _nth_weekday(year, 2, 0, 3),   # Washington's Birthday
        _last_weekday(year, 5, 0),     # Memorial Day
        _nth_weekday(year, 9, 0, 1),   # Labor Day
        _nth_weekday(year, 10, 0, 2),  # Columbus Day
        _nth_weekday(year, 11, 3, 4),  # Thanksgiving
    }
    return frozenset(out)


def _holiday_set(holidays):
    if holidays in ("frb", None, False) or (isinstance(holidays, (set, frozenset)) and all(
            isinstance(h, date) for h in holidays)):
        return holidays
    return frozenset(parse(h) for h in holidays)      # accept ISO strings as well as dates


def is_business_day(d: date, holidays="frb") -> bool:
    if d.weekday() >= 5:
        return False
    if holidays == "frb":
        return d not in frb_holidays(d.year)
    if holidays:
        return d not in _holiday_set(holidays)
    return True


def business_days_after(start: date, n: int, holidays="frb") -> list:
    """The next ``n`` business days strictly after ``start``."""
    holidays = _holiday_set(holidays)
    out: list = []
    d = start
    while len(out) < n:
        d += timedelta(1)
        if is_business_day(d, holidays):
            out.append(d)
    return out


def add_months(d: date, k: int) -> date:
    """``d`` plus ``k`` months (k may be negative), clamping the day to the month's end."""
    m = d.month - 1 + k
    y, m = d.year + m // 12, m % 12 + 1
    last = (date(y + (m == 12), m % 12 + 1, 1) - timedelta(1)).day
    return date(y, m, min(d.day, last))


def parse(d) -> date:
    return d if isinstance(d, date) else date.fromisoformat(str(d))
