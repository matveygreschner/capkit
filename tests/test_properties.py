"""Property-based tests (hypothesis): invariants that must hold for every input, not just worked examples."""
import contextlib
import io
import json
import math
from datetime import date, timedelta

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from capkit import api
from capkit import apr as A
from capkit.calendar import add_months
from capkit.products import analyze, level_payment, mca_fixed, term_loan

SETTINGS = settings()          # profile from conftest.py

rates = st.floats(0.005, 0.60)
terms = st.integers(2, 120)
amounts = st.floats(500, 2_000_000)
starts = st.dates(date(2000, 1, 1), date(2040, 12, 31))


def level_flows(amount, annual, n, start, fee=0.0):
    p = level_payment(amount, annual / 12, n)
    return [(start, amount - fee)] + [(add_months(start, k), -p) for k in range(1, n + 1)]


@SETTINGS
@given(amounts, rates, terms, starts)
def test_level_loan_without_fees_has_the_note_rate(amount, annual, n, start):
    assume(start.day <= 28)          # end-of-month starts are covered by the anchor tests
    assert A.apr_actuarial(level_flows(amount, annual, n, start)) == pytest.approx(annual, abs=1e-9)


@SETTINGS
@given(amounts, rates, terms, starts, st.floats(0.001, 0.08))
def test_a_fee_always_raises_the_apr(amount, annual, n, start, fee_share):
    assume(start.day <= 28)
    base = A.apr_actuarial(level_flows(amount, annual, n, start))
    with_fee = A.apr_actuarial(level_flows(amount, annual, n, start, fee=amount * fee_share))
    assert with_fee > base


@SETTINGS
@given(amounts, rates, terms, starts, st.floats(0.01, 1000))
def test_apr_is_invariant_to_currency_scale(amount, annual, n, start, k):
    assume(start.day <= 28)
    f = level_flows(amount, annual, n, start, fee=amount * 0.02)
    g = [(d, a * k) for d, a in f]
    assert A.apr_actuarial(g) == pytest.approx(A.apr_actuarial(f), rel=1e-9, abs=1e-12)


@SETTINGS
@given(amounts, rates, terms, starts)
def test_present_value_at_the_solved_rate_is_zero(amount, annual, n, start):
    assume(start.day <= 28)
    f = level_flows(amount, annual, n, start, fee=amount * 0.03)
    i = A.periodic_rate_actuarial(f, "month")
    pos = A._positions(A._flows(f), "month")
    assert abs(A._pv(pos, i)) < 1e-6 * amount


@SETTINGS
@given(amounts, rates, terms, starts)
def test_us_rule_equals_actuarial_when_payments_cover_interest(amount, annual, n, start):
    assume(start.day <= 28)
    f = level_flows(amount, annual, n, start, fee=amount * 0.01)
    assert A.apr_us_rule(f) == pytest.approx(A.apr_actuarial(f), abs=1e-9)


@SETTINGS
@given(st.floats(1000, 500_000), st.floats(1.05, 1.6), st.integers(20, 400), starts, st.integers(-3000, 3000))
def test_daily_mca_apr_is_invariant_to_moving_the_calendar_without_holidays(adv, factor, n, start, shift):
    """With no holidays, shifting the funding date by a whole number of weeks keeps every gap the same."""
    pay = adv * factor / n
    a = analyze(mca_fixed(adv, factor, pay, "business_day", start, holidays=None))
    b = analyze(mca_fixed(adv, factor, pay, "business_day", start + timedelta(7 * shift // 7 * 7),
                          holidays=None))
    assert a["apr_actuarial"] == pytest.approx(b["apr_actuarial"], rel=1e-10)


@SETTINGS
@given(st.floats(1000, 500_000), st.floats(1.05, 1.6), st.integers(20, 400), starts)
def test_mca_collects_exactly_the_purchased_amount(adv, factor, n, start):
    s = mca_fixed(adv, factor, adv * factor / n, "business_day", start)
    assert -sum(f.amount for f in s.flows[1:]) == pytest.approx(adv * factor, rel=1e-12)
    assert all(f.when.weekday() < 5 for f in s.flows[1:])


@SETTINGS
@given(st.floats(1000, 500_000), st.floats(1.05, 1.6), st.integers(20, 300), st.floats(1.01, 1.5))
def test_paying_back_faster_never_lowers_the_apr(adv, factor, n, speed):
    slow = analyze(mca_fixed(adv, factor, adv * factor / n, "week"))
    fast = analyze(mca_fixed(adv, factor, adv * factor / n * speed, "week"))
    assert fast["apr_actuarial"] >= slow["apr_actuarial"] - 1e-12


@SETTINGS
@given(amounts, rates, st.integers(2, 360), starts)
def test_cent_rounding_stays_far_inside_the_reg_z_tolerance(amount, annual, n, start):
    s = term_loan(amount, annual, n, funding_date=start)
    assert abs(analyze(s)["apr_actuarial"] - annual) < 0.000125          # 1/1000 of the 1/8-point tolerance
    pmt, final = s.terms["payment"], s.terms["final_payment"]
    assert abs(pmt - level_payment(amount, annual / 12, n)) < 0.01           # billed within a cent of level
    assert final > 0                                                         # never a refund
    assert -sum(f.amount for f in s.flows[1:]) == pytest.approx(pmt * (n - 1) + final, abs=0.005)


@SETTINGS
@given(st.floats(100, 1e6), st.floats(1.0001, 3.0), st.integers(1, 360))
def test_single_payment_rule_matches_its_closed_form(adv, mult, days):
    d0 = date(2027, 1, 4)
    d1 = d0 + timedelta(days)
    got = A.apr_actuarial([(d0, adv), (d1, -adv * mult)])
    months, cur = A._months_back(d0, d1)
    w = 12 / months if (cur == d0 and months) else 365 / days
    assert got == pytest.approx(w * (mult - 1), rel=1e-12)


json_values = st.recursive(
    st.none() | st.booleans() | st.integers(-10**9, 10**9) | st.floats(allow_nan=True, allow_infinity=True)
    | st.text(max_size=12),
    lambda inner: st.lists(inner, max_size=4) | st.dictionaries(st.text(max_size=10), inner, max_size=4),
    max_leaves=12)


@SETTINGS
@given(cmd=st.sampled_from(["true_cost", "compare_offers", "apr", "early_pay_cost", "disclosure_estimate",
                            "check_disclosure", "sba_fee", "params"]),
       args=st.dictionaries(st.sampled_from(["offer", "offers", "flows", "unit", "discount", "discount_days",
                                             "net_days", "funding_provided", "total_owed", "split_rate",
                                             "avg_monthly_sales", "disclosed_apr", "amount", "approval_date",
                                             "months", "rate", "key", "state", "marginal_rate"]),
                            json_values, max_size=6))
def test_the_json_api_never_crashes_or_returns_non_finite_numbers(cmd, args):
    """Arbitrary JSON in -> a JSON result or a JSON error out, never a traceback or NaN."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = api.main([cmd, json.dumps(args)])
    out = json.loads(buf.getvalue())
    assert code in (0, 1) and (("error" in out) == (code == 1))

    def finite(o):
        if isinstance(o, float):
            assert math.isfinite(o)
        elif isinstance(o, dict):
            for v in o.values():
                finite(v)
        elif isinstance(o, list):
            for v in o:
                finite(v)
    finite(out)


@SETTINGS
@given(st.floats(100, 1e6), starts,
       st.lists(st.tuples(st.integers(0, 200), st.floats(0.0, 3.0)), min_size=1, max_size=40),
       st.sampled_from(["month", "week", "day", "semimonth", "quarter"]))
def test_the_single_root_fast_path_matches_the_full_scan(adv, start, steps, unit):
    """With every advance first there is one rate; bisection must find the same one a full scan does."""
    d, flows = start, [(start, adv)]
    for gap, share in steps:
        d += timedelta(gap)
        flows.append((d, -adv * share / len(steps)))
    pos = A._positions(A._flows(flows), unit)
    assert A._conventional([((t, f), a) for t, f, a in pos])
    events = sorted((t + f, a) for t, f, a in pos)
    for fn, ok in ((lambda i: A._pv(pos, i), True),
                   (lambda i: A._us_rule_residual(events, i), A._us_rule_residual(events, 0.0) < 0)):
        if not ok:
            continue
        try:
            fast = A._rate(fn, -0.5, monotone=True)
        except ValueError:
            fast = None
        try:
            slow = A._rate(fn, -0.5)
        except ValueError:
            slow = None
        assert (fast is None) == (slow is None)
        if fast is not None:
            assert fast == pytest.approx(slow, rel=1e-9, abs=1e-12)
