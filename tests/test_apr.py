"""Regulation Z Appendix J: every numeric example in Appendix J (b)(9) and (c), plus properties.

Example inputs transcribed from the Appendix J equations (12 CFR 1026, Appendix J; published as
images ER22DE11.062-.071). Appendix J rounds results to two decimals, so each test checks the
published figure to +/- 0.005 percentage points - far inside the 1/8-point Reg Z tolerance.
"""
import random
from datetime import date

import pytest

from capkit.apr import (UNITS, apr_actuarial, apr_us_rule, ear, period_position, simple_annualized,
                        within_tolerance, xirr)
from capkit.calendar import add_months
from capkit import apr as A


def pct(x):
    return round(x * 100, 2)


def series(start, n, amount, step):
    """n payments of ``amount`` starting ``start``, ``step`` = days (int) or ('m', months)."""
    out = []
    for k in range(n):
        if isinstance(step, tuple):
            d = add_months(start, step[1] * k)
        else:
            d = date.fromordinal(start.toordinal() + step * k)
        out.append((d, -amount))
    return out


def semimonthly(start, n, amount):
    out, d = [], start
    for k in range(n):
        out.append((d, -amount))
        d = d.replace(day=16) if d.day == 1 else add_months(d.replace(day=1), 1)
    return out


# ---------------------------------------------------------------- (b)(9) iteration example
def test_b9_iteration_example():
    flows = [(0, 1000)] + [(k, -33.61) for k in range(1, 37)]
    assert abs(apr_actuarial(flows, "month") * 100 - 12.82557529) < 1e-6


# ---------------------------------------------------------------- (c)(1) single advance, regular
def test_c1_i_monthly():
    f = [(date(1978, 1, 10), 5000)] + series(date(1978, 2, 10), 24, 230, ("m", 1))
    assert pct(apr_actuarial(f, "month")) == 9.69


def test_c1_ii_monthly_odd_first_period():
    f = [(date(1978, 2, 10), 6000)] + series(date(1978, 4, 1), 36, 200, ("m", 1))
    assert period_position(date(1978, 2, 10), date(1978, 4, 1), "month") == (1, 19 / 30)
    assert pct(apr_actuarial(f, "month")) == 11.82


def test_c1_iii_semimonthly():
    f = [(date(1978, 2, 23), 5000)] + semimonthly(date(1978, 3, 1), 24, 219.17)
    assert period_position(date(1978, 2, 23), date(1978, 3, 1), "semimonth") == (0, 6 / 15)
    assert pct(apr_actuarial(f, "semimonth")) == 10.34


def test_c1_iv_quarterly():
    f = [(date(1978, 5, 23), 10000)] + series(date(1978, 10, 1), 40, 385, ("m", 3))
    assert period_position(date(1978, 5, 23), date(1978, 10, 1), "quarter") == (1, 39 / 90)
    assert pct(apr_actuarial(f, "quarter")) == 8.97


def test_c1_v_weekly():
    f = [(date(1978, 3, 20), 500)] + series(date(1978, 4, 21), 30, 17.60, 7)
    assert period_position(date(1978, 3, 20), date(1978, 4, 21), "week") == (4, 4 / 7)
    assert pct(apr_actuarial(f, "week")) == 14.96


# ---------------------------------------------------------------- (c)(2) odd first payment
def test_c2_i():
    f = [(date(1978, 1, 10), 5000), (date(1978, 2, 10), -250)] + series(date(1978, 3, 10), 23, 230, ("m", 1))
    assert pct(apr_actuarial(f, "month")) == 10.08


def test_c2_ii_four_weekly():
    f = [(date(1978, 3, 18), 400), (date(1978, 4, 20), -39.50)] + series(date(1978, 5, 18), 11, 38.31, 28)
    assert period_position(date(1978, 3, 18), date(1978, 4, 20), "4week") == (1, 5 / 28)
    assert pct(apr_actuarial(f, "4week")) == 28.50


# ---------------------------------------------------------------- (c)(3) odd final payment
def test_c3_i():
    f = [(date(1978, 1, 10), 5000)] + series(date(1978, 2, 10), 23, 230, ("m", 1)) + [(date(1980, 1, 10), -280)]
    assert pct(apr_actuarial(f, "month")) == 10.50


def test_c3_ii_biweekly():
    f = [(date(1978, 4, 3), 200)] + series(date(1978, 4, 11), 19, 9.50, 14)
    f.append((date.fromordinal(date(1978, 4, 11).toordinal() + 14 * 19), -30))
    assert pct(apr_actuarial(f, "biweek")) == 12.22


# ---------------------------------------------------------------- (c)(4) odd first and final payments
def test_c4_i():
    f = ([(date(1978, 1, 10), 5000), (date(1978, 2, 10), -250)] + series(date(1978, 3, 10), 22, 230, ("m", 1))
         + [(date(1980, 1, 10), -280)])
    assert pct(apr_actuarial(f, "month")) == 10.90


def test_c4_ii_bimonthly():
    f = ([(date(1978, 1, 10), 8000), (date(1978, 3, 1), -449.36)] + series(date(1978, 5, 1), 18, 465, ("m", 2))
         + [(add_months(date(1978, 3, 1), 2 * 19), -200)])
    assert period_position(date(1978, 1, 10), date(1978, 3, 1), "bimonth") == (0, 52 / 60)
    assert pct(apr_actuarial(f, "bimonth")) == 7.30


# ---------------------------------------------------------------- (c)(5) single advance, single payment
@pytest.mark.parametrize("adv,pay,d0,d1,expected", [
    (1000, 1080, date(1978, 1, 3), date(1978, 9, 15), 11.45),
    (1000, 1044, date(1978, 7, 15), date(1979, 1, 15), 8.80),
    (1000, 1135.19, date(1978, 7, 17), date(1980, 1, 17), 8.76),
    (1000, 1240, date(1978, 1, 3), date(1980, 1, 3), 11.36),
])
def test_c5_single_payment(adv, pay, d0, d1, expected):
    assert pct(A.apr_single_payment(adv, pay, d0, d1)) == expected


# ---------------------------------------------------------------- (c)(6) complex single advance
def test_c6_i_skipped_payments():
    pos = ([k + 26 / 28 for k in range(9)] + [10 + 12 / 28 + k for k in range(6)]
           + [16 + 26 / 28 + k for k in range(6)] + [23 + 12 / 28 + k for k in range(3)])
    f = [(0.0, 2135)] + [(p, -100) for p in pos]
    assert len(pos) == 24
    assert pct(apr_actuarial(f, "4week")) == 12.00


def test_c6_ii_irregular():
    f = ([(0.0, 7350)] + [(t + 12 / 30, -1000) for t in (6, 7, 8)] + [(12 + 12 / 30, -2000)]
         + [(t + 12 / 30, -750) for t in (18, 19, 20)] + [(22 + 29 / 30, -1000)])
    assert pct(apr_actuarial(f, "month")) == 10.22


def test_c6_iii_graduated_mortgage():
    pays = [291.81, 300.18, 308.78, 317.61, 326.65, 335.92, 345.42, 355.15, 365.12, 375.33, 385.76, 385.42,
            385.03, 384.62, 384.17, 383.67, 383.13, 382.54, 381.90, 381.20, 380.43, 379.60, 378.68, 377.69,
            376.60, 375.42, 374.13, 372.72, 371.18, 369.50]
    f = [(0.0, 39688.56)]
    for y, p in enumerate(pays):
        for j in range(12):
            f.append((1 + 12 * y + j + 21 / 30, -p))
    assert pct(apr_actuarial(f, "month")) == 9.80


# ---------------------------------------------------------------- (c)(7) multiple advances
def test_c7_i_construction_loan():
    f = [(0.0, 20000), (2 + 2 / 30, 20000), (5 + 8 / 30, 20000)] + [(8 + k, -612.36) for k in range(240)]
    assert pct(apr_actuarial(f, "month")) == 10.25


def test_c7_ii_student_loan_payment_before_advance():
    f = [(0.0, -240)] + [(k, -240) for k in range(1, 50)]
    f += [(k + 4 / 30, 1800) for k in (2, 14, 26, 38)] + [(k + 4 / 30, 1000) for k in (6, 18, 30, 42)]
    assert pct(apr_actuarial(f, "month")) == 32.04


def test_c7_ii_dated_zero_point_is_first_payment():
    pays = series(date(1978, 7, 1), 50, 240, ("m", 1))
    adv = [(date(y, 9, 5), 1800) for y in (1978, 1979, 1980, 1981)] + [(date(y, 1, 5), 1000) for y in (1979, 1980, 1981, 1982)]
    assert pct(apr_actuarial(pays + adv, "month")) == 32.04


# ---------------------------------------------------------------- U.S. Rule (no published examples)
def test_us_rule_equals_actuarial_when_every_payment_covers_interest():
    rnd = random.Random(7)
    for _ in range(200):
        n = rnd.randint(2, 60)
        rate = rnd.uniform(0.001, 0.05)
        amt = rnd.uniform(1000, 100000)
        pmt = amt * rate / (1 - (1 + rate) ** -n) * rnd.uniform(1.0, 1.02)
        f = [(0, amt)] + [(k, -pmt) for k in range(1, n + 1)]
        assert abs(apr_actuarial(f, "month") - apr_us_rule(f, "month")) < 1e-9


def test_us_rule_differs_with_zero_payment_periods():
    f = [(0, 10000)] + [(k, -1150) for k in range(3, 13)]
    assert round(apr_actuarial(f, "month") * 100, 4) == 22.8099
    assert round(apr_us_rule(f, "month") * 100, 4) == 22.9843
    assert not within_tolerance(apr_us_rule(f, "month"), apr_actuarial(f, "month"))


# ---------------------------------------------------------------- properties
def test_level_loan_without_fees_equals_note_rate():
    rnd = random.Random(1)
    for _ in range(100):
        r, n, amt = rnd.uniform(0.01, 0.3), rnd.randint(6, 360), rnd.uniform(1e3, 1e6)
        i = r / 12
        pmt = amt * i / (1 - (1 + i) ** -n)
        assert abs(apr_actuarial([(0, amt)] + [(k, -pmt) for k in range(1, n + 1)], "month") - r) < 1e-9


def test_fee_raises_apr_and_scaling_invariance():
    base = [(0, 10000)] + [(k, -900) for k in range(1, 13)]
    fee = [(0, 9800)] + [(k, -900) for k in range(1, 13)]
    assert apr_actuarial(fee, "month") > apr_actuarial(base, "month")
    big = [(t, a * 37.5) for t, a in base]
    assert abs(apr_actuarial(big, "month") - apr_actuarial(base, "month")) < 1e-12


def test_ear_at_least_apr():
    assert ear(0.12, "month") > 0.12
    assert abs(ear(0.12, "month") - (1.01 ** 12 - 1)) < 1e-12


def test_xirr_simple():
    assert abs(xirr([(date(2027, 1, 1), 1000), (date(2028, 1, 1), -1100)]) - 0.10) < 1e-9


def test_tolerances():
    assert within_tolerance(0.1912, 0.1900)
    assert not within_tolerance(0.1914, 0.1900)
    assert within_tolerance(0.1924, 0.1900, irregular=True)


def test_simple_annualized_quote():
    assert round(simple_annualized(50000, 67500, 30 / 52), 4) == 0.6067
