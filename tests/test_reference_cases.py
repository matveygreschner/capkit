"""Reference cases from the Regulation Z official commentary, Appendix J and independent open-source APR
engines (values collected in a read-only competitor teardown; no third-party code is used)."""
from datetime import date, timedelta

import pytest

from capkit import apr as A
from capkit.calendar import add_months

ADV = date(2026, 1, 1)


def monthly(series, start=date(2026, 2, 1)):
    """[(count, amount), ...] -> dated monthly payments from ``start``."""
    out, k = [], 0
    for n, amt in series:
        for _ in range(n):
            out.append((add_months(start, k), -amt))
            k += 1
    return out


def pct(x):
    return round(x * 100, 2)


# ---------------------------------------------------------------- official commentary
def test_step_rate_comment_22a1_4():
    f = [(ADV, 10000)] + monthly([(24, 210.71), (24, 220.25), (12, 222.59)])
    assert pct(A.apr_actuarial(f)) == 10.75 and pct(A.apr_us_rule(f)) == 10.75


@pytest.mark.parametrize("series,apr,fc,us", [
    ([(12, 804.62), (348, 1025.31)], 11.63, 266463.32, 11.69),
    ([(12, 804.62), (12, 950.09), (336, 1024.34)], 11.53, 265234.76, 11.60),
    ([(12, 804.62), (12, 864.97), (12, 929.84), (12, 999.58), (312, 1070.04)], 11.64, 277040.60, 11.85),
])
def test_discounted_variable_rate_comment_17c1_10(series, apr, fc, us):
    f = [(ADV, 100000)] + monthly(series)
    assert pct(A.apr_actuarial(f)) == apr
    assert round(-sum(a for _, a in f[1:]) - 100000, 2) == fc
    assert pct(A.apr_us_rule(f)) == us                  # regression pin


@pytest.mark.parametrize("n,apr", [(3, 14.94), (21, 18.18), (60, 17.27)])
def test_add_on_rate_comment_22c_1(n, apr):
    pay = round(1000 * (1 + 0.10 * n / 12) / n, 2)
    f = [(ADV, 1000)] + monthly([(n, pay)])
    assert pct(A.apr_actuarial(f)) == apr


def test_tolerance_edges_comment_22a2_1():
    exact = 0.10125
    assert A.within_tolerance(0.1000, exact) and A.within_tolerance(0.1025, exact)
    assert not A.within_tolerance(0.099999, exact) and not A.within_tolerance(0.102501, exact)
    assert A.within_tolerance(0.10375, exact, irregular=True)
    assert not A.within_tolerance(0.103751, exact, irregular=True)


# ---------------------------------------------------------------- Appendix J examples built from dates
def test_c6_i_from_dates_infers_four_weeks():
    pays, d = [], date(1978, 2, 20)
    for n in (9, 6, 6, 3):
        for k in range(n):
            pays.append(d + timedelta(28 * k))
        d = pays[-1] + timedelta(42)
    f = [(date(1978, 1, 25), 2135)] + [(p, -100) for p in pays]
    assert A.infer_unit(pays, [date(1978, 1, 25)]) == "4week"
    assert pct(A.apr_actuarial(f)) == 12.00


def test_c6_ii_from_dates():
    f = ([(date(1978, 3, 3), 7350)] + [(add_months(date(1978, 9, 15), k), -1000) for k in range(3)]
         + [(date(1979, 3, 15), -2000)] + [(add_months(date(1979, 9, 15), k), -750) for k in range(3)]
         + [(date(1980, 2, 1), -1000)])
    assert pct(A.apr_actuarial(f, "month")) == 10.22
    assert A.period_position(date(1978, 3, 3), date(1980, 2, 1), "month") == (22, 29 / 30)


def test_c6_iii_graduated_mortgage_from_dates():
    yearly = [291.81, 300.18, 308.78, 317.61, 326.65, 335.92, 345.42, 355.15, 365.12, 375.33, 385.76, 385.42,
              385.03, 384.62, 384.17, 383.67, 383.13, 382.54, 381.90, 381.20, 380.43, 379.60, 378.68, 377.69,
              376.60, 375.42, 374.13, 372.72, 371.18, 369.50]
    f = [(date(1978, 4, 10), 39688.56)] + monthly([(12, p) for p in yearly], date(1978, 6, 1))
    assert pct(A.apr_actuarial(f)) == 9.80


def test_c7_i_construction_loan_from_dates():
    f = ([(date(1979, 4, 10), 20000), (date(1979, 6, 12), 20000), (date(1979, 9, 18), 20000)]
         + monthly([(240, 612.36)], date(1979, 12, 10)))
    assert pct(A.apr_actuarial(f, "month")) == 10.25
    assert pct(A.apr_us_rule(f, "month")) == 10.31


def test_c7_ii_has_two_rates():
    f = [(0.0, -240)] + [(k, -240) for k in range(1, 50)]
    f += [(k + 4 / 30, 1800) for k in (2, 14, 26, 38)] + [(k + 4 / 30, 1000) for k in (6, 18, 30, 42)]
    pos = A._positions(A._flows(f), "month")
    rs = A.roots(lambda i: A._pv(pos, i))
    assert [pct(r * 12) for r in rs] == [32.04, 922.11]
    assert pct(A.apr_us_rule(f, "month")) == 29.17


# ---------------------------------------------------------------- independent engines
@pytest.mark.parametrize("adv,pay,d0,d1,expected", [
    (300, 345, date(2026, 1, 1), date(2026, 1, 15), 391.07),
    (85, 100, date(2026, 1, 1), date(2026, 1, 15), 460.08),
    (700, 850, date(2025, 12, 2), date(2025, 12, 19), 460.08),
    (500, 501, date(2026, 1, 1), date(2026, 1, 2), 73.00),
])
def test_single_payment_cases(adv, pay, d0, d1, expected):
    assert pct(A.apr_actuarial([(d0, adv), (d1, -pay)])) == expected


def test_zero_cost_is_exactly_zero():
    assert A.apr_actuarial([(ADV, 1200)] + monthly([(12, 100)])) == 0.0


def test_level_loan_to_four_decimals():
    assert round(A.apr_actuarial([(ADV, 5000)] + monthly([(36, 166.07)])), 4) == 0.1200


def test_two_roots_ten_and_twenty_percent():
    pos = A._positions(A._flows([(0, -100), (1, 230), (2, -132)]), "month")
    assert [round(r, 9) for r in A.roots(lambda i: A._pv(pos, i))] == [0.1, 0.2]


@pytest.mark.parametrize("pays,advs,unit", [
    ([date(2026, 1, 15), date(2026, 1, 29), date(2026, 2, 12), date(2026, 3, 12), date(2026, 4, 12)], [ADV], "biweek"),
    ([date(2026, 1, 11), date(2026, 1, 31), date(2026, 3, 17)], [ADV], "4week"),
    ([date(2026, 1, 31), date(2026, 2, 28)], [date(2026, 1, 15)], "3week"),
    ([date(2026, 1, 5), date(2026, 1, 20), date(2026, 2, 5), date(2026, 2, 20)], [ADV], "semimonth"),
    ([date(2026, 1, 15), date(2026, 1, 31), date(2026, 2, 15), date(2026, 2, 28)], [ADV], "semimonth"),
])
def test_unit_inference_pins(pays, advs, unit):
    assert A.infer_unit(pays, advs) == unit


@pytest.mark.parametrize("a,b,unit,expected", [
    (date(1979, 4, 10), date(1979, 9, 18), "month", (5, 8 / 30)),
    (date(2026, 1, 15), date(2026, 3, 31), "month", (2, 16 / 30)),
    (date(2026, 2, 2), date(2026, 4, 3), "month", (2, 1 / 30)),
    (date(1978, 2, 23), date(1978, 3, 16), "semimonth", (1, 6 / 15)),
    (date(1978, 2, 23), date(1978, 4, 1), "semimonth", (2, 6 / 15)),
    (date(2025, 1, 1), date(2026, 3, 11), "year", (1, 69 / 365)),
    (date(2026, 1, 20), date(2026, 3, 1), "year", (0, 40 / 365)),
])
def test_date_measurement_pins(a, b, unit, expected):
    t, f = A.period_position(a, b, unit)
    assert t == expected[0] and abs(f - expected[1]) < 1e-12


def test_year_unit_quirk():
    assert A.period_position(date(2000, 3, 1), date(2000, 12, 31), "year") == (0, 305 / 365)
    assert A.period_position(date(2000, 3, 1), date(2001, 1, 1), "year") == (0, 10 / 12)


# ---------------------------------------------------------------- fixed after the teardown
@pytest.mark.parametrize("base,day,expected", [
    (date(2027, 1, 10), 28, (1, 18 / 30)),
    (date(2027, 1, 5), 30, (1, 25 / 30)),
    (date(2027, 1, 30), 28, (0, 29 / 30)),
])
def test_february_payment_uses_the_series_day(base, day, expected):
    pays = [date(2027, 2, 28)] + [date(2027, m, day) for m in range(3, 8)]
    pos = A._positions(A._flows([(base, 1000)] + [(p, -100) for p in pays]), "month")
    assert pos[1][0] == expected[0] and abs(pos[1][1] - expected[1]) < 1e-12


def test_every_four_months_and_every_six_weeks_are_units():
    from capkit.products import level_payment
    p = level_payment(10000, 0.04, 9)
    f = [(date(2027, 1, 15), 10000)] + [(add_months(date(2027, 1, 15), 4 * j), -p) for j in range(1, 10)]
    assert A.infer_unit([d for d, a in f if a < 0], [f[0][0]]) == "4month"
    assert abs(A.apr_actuarial(f) - 0.12) < 1e-12
    p = level_payment(1000, 0.12 * 6 / 52, 8)
    f = [(date(2027, 1, 4), 1000)] + [(date(2027, 1, 4) + timedelta(42 * j), -p) for j in range(1, 9)]
    assert A.infer_unit([d for d, a in f if a < 0], [f[0][0]]) == "6week"
    assert abs(A.apr_actuarial(f) - 0.12) < 1e-12


@pytest.mark.parametrize("flows,features", [
    ([(ADV, 1000)] + monthly([(1, 130), (10, 100), (1, 97.12)]), []),
    ([(ADV, 1000)] + monthly([(1, 130), (4, 100), (1, 110), (5, 100), (1, 97.12)]), ["irregular payment amounts"]),
    ([(ADV, 500), (date(2026, 1, 15), 500)] + monthly([(12, 90)]), ["more than one advance"]),
    ([(ADV, 10000)] + monthly([(24, 210.71), (24, 220.25), (12, 222.59)]), ["irregular payment amounts"]),
])
def test_irregular_transaction_rule(flows, features):
    assert A.irregular_features(flows) == features


def test_finance_charge_implied_by_an_apr_round_trips():
    f = [(ADV, 5000)] + monthly([(36, 166.07)])
    apr = A.apr_actuarial(f)
    assert abs(A.finance_charge_at_apr(f, apr, "month") - (36 * 166.07 - 5000)) < 1e-6
