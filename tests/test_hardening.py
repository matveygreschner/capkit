"""Regression and property tests for the defects fixed in the hardening pass, plus independent oracles."""
import time
from datetime import date, timedelta

import pytest
from hypothesis import assume, example, given, settings
from hypothesis import strategies as st

from capkit import api
from capkit import apr as A
from capkit import disclosures as D
from capkit import params as P
from capkit import products as PR
from capkit.calendar import add_months

SETTINGS = settings()
dates = st.dates(date(2025, 1, 1), date(2035, 12, 31))


# ---- D1: a regular monthly series that starts at a month end is not "irregular" -------------------
@SETTINGS
@given(dates, st.integers(3, 60))
def test_level_monthly_series_is_regular_for_every_funding_date(fd, months):
    s = PR.term_loan(10_000, 0.12, months, funding_date=fd)
    assert "irregular payment periods" not in A.irregular_features(s.flows)


def test_month_end_funding_does_not_loosen_the_disclosure_tolerance():
    verdicts = []
    for fd in ("2027-01-04", "2027-01-29", "2027-01-30", "2027-01-31"):
        e = D.estimate(100_000, 103_000, 0.10, 100_000, frequency="month", funding_date=fd)
        assert e["irregular"] is False
        verdicts.append(D.check_disclosed_apr(e["estimated_apr_actuarial"] - 0.002, e)["verdict"])
    assert set(verdicts) == {"not reproduced by either permitted method with these inputs"}


@SETTINGS
@given(dates, st.floats(500, 2e6), st.floats(0.0, 0.40), st.integers(2, 120))
def test_fee_free_loan_has_its_note_rate_on_every_funding_date(fd, amount, rate, months):
    a = PR.analyze(PR.term_loan(amount, rate, months, funding_date=fd))
    assert abs(a["apr_actuarial"] - rate) < 1e-4 and abs(a["apr_us_rule"] - rate) < 1e-4


# ---- D2: prepaid fees, net vs gross funding (12 CFR 1026.18(b)(3)) ---------------------------------
def test_net_basis_is_the_documented_contract_and_is_unchanged():
    """funding_provided = cash to the recipient (docstring). A fee already withheld is not subtracted twice."""
    a = D.estimate(47_500, 67_500, 0.10, 60_000, prepaid_fees=2_500)
    b = D.estimate(47_500, 67_500, 0.10, 60_000)
    assert a["amount_financed"] == 47_500 and a["finance_charge"] == 20_000
    assert a["estimated_apr_actuarial"] == b["estimated_apr_actuarial"]
    assert a["estimated_apr_actuarial"] == pytest.approx(0.801500742820233, rel=1e-9)
    assert a["funding_basis"] == "net" and any("already withheld" in m for m in a["modeled"])
    assert "warning" not in b                                  # no fee, nothing ambiguous


def test_net_basis_with_a_fee_reports_the_gross_reading_too():
    """$50,000 headline + $2,500 fee entered on the default basis: the 80.15% reading is shown, not hidden."""
    e = D.estimate(50_000, 67_500, 0.10, 60_000, prepaid_fees=2_500)
    other = e["if_funding_provided_is_before_fees"]
    assert e["estimated_apr_actuarial"] == pytest.approx(0.6775182345696981, rel=1e-9)
    assert other["estimated_apr_actuarial"] == pytest.approx(0.801500742820233, rel=1e-9)
    assert "80.15%" in e["warning"] and "funding_basis" in e["warning"]
    c = api.check_disclosure(0.68, 50_000, 67_500, 0.10, 60_000, prepaid_fees=2_500)
    assert c["check"]["verdict"].startswith("consistent")
    assert c["check_if_funding_provided_is_before_fees"].startswith("not reproduced")


def test_gross_basis_subtracts_the_fee_once():
    g = D.estimate(50_000, 67_500, 0.10, 60_000, prepaid_fees=2_500, funding_basis="gross")
    n = D.estimate(47_500, 67_500, 0.10, 60_000)
    assert g["amount_financed"] == 47_500 and g["finance_charge"] == 20_000
    assert g["estimated_apr_actuarial"] == pytest.approx(n["estimated_apr_actuarial"], rel=1e-12)
    with pytest.raises(ValueError):
        D.estimate(2_500, 67_500, 0.10, 60_000, prepaid_fees=2_500, funding_basis="gross")
    with pytest.raises(ValueError):
        D.estimate(50_000, 67_500, 0.10, 60_000, funding_basis="Gross")


def test_paid_on_behalf_is_counted_once_on_the_gross_basis():
    g = D.estimate(40_000, 67_500, 0.10, 60_000, prepaid_fees=2_500, paid_on_behalf=10_000, funding_basis="gross")
    assert g["amount_financed"] == 47_500


def test_coverage_is_tested_on_the_amount_financed():
    """23 NYCRR 600.19 as documented in docs/disclosure-rules.md: the amount financed for closed-end offers."""
    g = D.estimate(2_501_000, 3_000_000, 0.10, 3_000_000, prepaid_fees=2_000, state="NY", funding_basis="gross")
    assert g["amount_financed"] == 2_499_000 and g["covered"] is True


@SETTINGS
@given(st.floats(10_000, 400_000), st.floats(0, 0.2), st.floats(0, 20_000), st.floats(1.1, 1.5),
       st.integers(3, 18))
def test_gross_minus_fee_equals_net(cash, fee_share, behalf, factor, months):
    """The term is drawn directly (sales sized to repay in ``months``): the equivalence does not depend on
    it, and an unbounded term made 2,000 examples of daily schedules take most of an hour."""
    fee = cash * fee_share
    owed = (cash + behalf) * factor
    sales = owed / (0.10 * months)
    g = D.estimate(cash + fee, owed, 0.10, sales, prepaid_fees=fee, paid_on_behalf=behalf, funding_basis="gross")
    n = D.estimate(cash, owed, 0.10, sales, prepaid_fees=fee, paid_on_behalf=behalf)
    assert g["amount_financed"] == pytest.approx(n["amount_financed"], abs=0.01)
    assert g["estimated_apr_actuarial"] == pytest.approx(n["estimated_apr_actuarial"], rel=1e-9)


def test_prepaid_fee_matches_the_mca_builder_convention():
    """Same schedule two ways: estimate(gross, prepaid_fees) and products.mca_fixed(fees)."""
    e = D.estimate(50_000, 67_500, 0.10, 60_000, prepaid_fees=2_500, funding_basis="gross")
    pay = 0.10 * 60_000 * 12 / D.periods_per_year("business_day", "2027-01-04")
    s = PR.mca_fixed(50_000, 1.35, pay, "business_day", "2027-01-04", fees=2_500)
    assert A.apr_actuarial(s.flows, "day") == pytest.approx(e["estimated_apr_actuarial"], rel=1e-9)


# ---- D3: work is linear in the number of periods ---------------------------------------------------
@pytest.mark.parametrize("call", [
    lambda: PR.revenue_based(100_000, 1.2, 0.1, [0.0001], frequency="month"),
    lambda: D.estimate(100, 1e6, 0.01, 1, frequency="month"),
    lambda: D.estimate(100, 1e6, 0.01, 1, frequency="business_day"),
])
def test_unrepayable_inputs_fail_fast(call):
    t = time.perf_counter()
    with pytest.raises(ValueError):
        call()
    assert time.perf_counter() - t < 10


@SETTINGS
@given(dates, st.integers(0, 20_000))
def test_months_since_matches_the_reference_loop(fd, days):
    d = fd + timedelta(days)
    k = 0
    while add_months(fd, k + 1) <= d:
        k += 1
    assert D._months_since(fd, d) == k + 1


# ---- D4: a lease with no purchase option is a true lease for the after-tax view --------------------
def test_lease_character_follows_the_end_of_term():
    assert PR.equipment_lease(10_000, 500, 24, end_of_term="return").tax_character == "rent"
    assert PR.equipment_lease(10_000, 500, 24, buyout=1).tax_character == "conditional_sale_likely"
    assert PR.equipment_lease(10_000, 500, 24, end_of_term="own").tax_character == "conditional_sale_likely"
    s = PR.equipment_lease(10_000, 500, 24)          # nothing said: not called a purchase, and explained
    assert s.tax_character == "lease_character_unknown" and "end_of_term" in s.notes[-1]


def test_after_tax_flag_never_mentions_a_buyout_the_lease_does_not_have():
    lease = {"type": "equipment_lease", "equipment_cost": 10_000, "payment": 500, "months": 24}
    unknown = api.true_cost(lease, marginal_rate=0.3)
    assert unknown["after_tax_finance_charge"] is None and "buyout" not in unknown["flag"].split("(")[0]
    assert "end_of_term" in unknown["flag"]
    rent = api.true_cost({**lease, "end_of_term": "return"}, marginal_rate=0.3)
    assert rent["tax_character"] == "rent" and rent["after_tax_finance_charge"] == pytest.approx(
        rent["finance_charge"] * 0.7, abs=0.01)
    own = api.true_cost({**lease, "buyout": 1}, marginal_rate=0.3)
    assert own["after_tax_finance_charge"] is None and own["flag"].startswith("A nominal buyout")


def test_tiny_positive_rate_does_not_divide_by_zero():
    s = PR.term_loan(500, 4.75e-30, 2)
    assert s.terms["payment"] == 250.0


def _bisect(f, lo=1e-9, hi=1.0):
    """Root of an increasing f on [lo, hi]."""
    for _ in range(200):
        mid = (lo + hi) / 2
        lo, hi = (lo, mid) if f(mid) > 0 else (mid, hi)
    return (lo + hi) / 2


def test_monthly_series_on_the_30th_has_a_monthly_unit_and_the_appendix_j_rate():
    """Payments on the 30th (Feb 28 standing for the 30th): every payment period is one month, so the unit
    period is a month (Appendix J (b)(4)). Unpatched code inferred "5week" and gave 0.223735. Independent
    rate: the first period is 1 month + 20/30 (Dec 10 -> Dec 30 -> Jan 30), Appendix J (b)(5)(iii)."""
    flows = [["2026-12-10", 10_000], ["2027-01-30", -3_500], ["2027-02-28", -3_500], ["2027-03-30", -3_500]]
    r = api.apr(flows)
    i = _bisect(lambda i: 10_000 - sum(3_500 / ((1 + 20 / 30 * i) * (1 + i) ** t) for t in (1, 2, 3)))
    assert r["unit_period"] == "month"
    assert r["apr_actuarial"] == pytest.approx(12 * i, abs=1e-9)


@SETTINGS
@given(st.integers(28, 31), st.integers(3, 12), st.integers(1, 60), st.dates(date(2025, 1, 1), date(2034, 12, 1)))
@example(30, 3, 51, date(2027, 1, 1))
def test_a_monthly_series_on_any_day_has_a_monthly_unit(day, n, gap, month):
    """For a payment series on day 28-31 of each month (clamped to short months), n >= 3 payments and any
    first period, the inferred unit is a month and the APR equals the APR with unit="month" given."""
    starts = [add_months(month.replace(day=1), k) for k in range(n)]
    pays = [m.replace(day=min(day, (add_months(m, 1) - timedelta(1)).day)) for m in starts]
    flows = [[(pays[0] - timedelta(gap)).isoformat(), 10_000]] + [[p.isoformat(), -4_000] for p in pays]
    inferred = api.apr(flows)
    assert inferred["unit_period"] == "month", flows
    assert inferred["apr_actuarial"] == pytest.approx(api.apr(flows, unit="month")["apr_actuarial"], abs=1e-12)


# ---- D5: the sba_fee command reports the ceiling it enforces ---------------------------------------
def test_sba_fee_with_90_day_aggregation_matches_a_hand_calculation():
    """15 U.S.C. 636(a)(18)(A), loans within 90 days combined. Combined $200,000: 75% guaranteed = $150,000;
    3% tier = $4,500, less the $1,700 already charged (2% of 85% of the first $100,000) = $2,800."""
    r = api.sba_fee(100_000, "2026-11-01", prior_90_day_amount=100_000, prior_90_day_fee=1_700)
    assert (r["fee"], r["ceiling"], r["ceiling_combined_loans"]) == (2_800.0, 2_800.0, 4_500.0)
    assert r["ceiling_this_loan_alone"] == 1_700.0 and r["prime_status"] == "placeholder"
    short = api.sba_fee(100_000, "2026-11-01", months=12)          # 0.25% short-term: fee well under ceiling
    assert (short["fee"], short["ceiling"]) == (212.5, 1_700.0)


def test_sba_fee_needs_the_prior_fee_and_never_reports_a_negative_ceiling():
    with pytest.raises(ValueError, match="prior_90_day_fee"):
        api.sba_fee(100_000, "2026-11-01", prior_90_day_amount=100_000)      # used to assume $0 silently
    with pytest.raises(ValueError, match="prior_90_day_amount"):
        api.sba_fee(100_000, "2026-11-01", prior_90_day_fee=1_700)           # used to be ignored silently
    assert api.sba_fee(100_000, "2026-11-01", prior_90_day_fee=0)["fee"] == 1_700.0   # 0 is "none": fine
    r = api.sba_fee(100_000, "2026-11-01", prior_90_day_amount=50_000, prior_90_day_fee=5_000)
    assert r["fee"] == 0.0 and r["ceiling"] == 0.0 and "exceeds" in r["warning"]   # used to raise, ceiling -2,450


def test_sba_7a_offer_combines_90_day_loans_like_sba_fee():
    """The prior-90-day rule holds on the APR path too (true_cost / compare_offers), not only in sba_fee."""
    base = {"type": "sba_7a", "amount": 100_000, "prime": 0.075, "approval_date": "2026-11-01",
            "funding_date": "2026-11-15"}
    with pytest.raises(ValueError, match="prior_90_day_fee"):
        api.call("true_cost", {"offer": {**base, "prior_90_day_amount": 100_000}})   # was: fee 4,500, APR 14.69%
    with pytest.raises(ValueError, match="prior_90_day_amount"):
        api.call("true_cost", {"offer": {**base, "prior_90_day_fee": 1_700}})        # was: silently ignored
    r = api.true_cost({**base, "prior_90_day_amount": 100_000, "prior_90_day_fee": 1_700})
    assert r["terms"]["upfront_fee"] == 2_800.0                     # $4,500 combined less $1,700 (hand, above)
    alone = api.true_cost({"type": "term_loan", "amount": 100_000, "annual_rate": 0.135, "months": 120,
                           "fee": 2_800.0, "funding_date": "2026-11-15"})       # Prime 7.5% + 6% spread
    assert r["apr_actuarial"] == pytest.approx(alone["apr_actuarial"], abs=1e-12)
    assert r["finance_charge"] == alone["finance_charge"]
    assert api.true_cost({**base, "prior_90_day_fee": 0})["apr_actuarial"] == api.true_cost(base)["apr_actuarial"]


@pytest.mark.parametrize("amount,prior,fee", [(100_000, 100_000, 1_700), (100_000, 50_000, 5_000),
                                              (400_000, 300_000, 0), (40_000, 60_000, 1_020)])
def test_sba_fee_and_the_sba_7a_offer_charge_the_same_fee(amount, prior, fee):
    a = api.sba_fee(amount, "2026-11-01", prior_90_day_amount=prior, prior_90_day_fee=fee)["fee"]
    o = PR.sba_7a(amount, prime=0.075, approval_date="2026-11-01", prior_90_day_amount=prior,
                  prior_90_day_fee=fee).terms["upfront_fee"]
    assert a == o


# ---- D6: split schedules are validated ---------------------------------------------------------------
@pytest.mark.parametrize("bad", [[[0, 0.2]], [[1.5, 0.2]], [[2, 0.1], [2, 0.2]], [[True, 0.1]]])
def test_bad_split_schedules_are_rejected(bad):
    with pytest.raises(ValueError):
        D.estimate(100, 120, 0.1, 1_000, split_schedule=bad)


def test_extreme_single_payment_does_not_crash_analyze():
    a = PR.analyze(PR.trade_credit(100, 0.99, 0, 1))
    assert a["ear"] is None and a["apr_actuarial"] > 0


def test_parameter_dates_are_not_in_the_future():
    for k in P.PARAMS:
        assert 0 <= P.age_days(k) <= P.MAX_AGE_DAYS, k


# ---- Independent oracles -------------------------------------------------------------------------------
@SETTINGS
@given(dates, st.floats(1_000, 1e6), st.floats(1.01, 1.6), st.integers(5, 300))
def test_one_day_unit_apr_agrees_with_xirr(fd, adv, factor, n):
    """With whole-day positions (1 + APR/365)^365 - 1 is exactly the XIRR, a different equation and solver."""
    s = PR.mca_fixed(adv, factor, adv * factor / n, "business_day", fd)
    assert A.ear(A.apr_actuarial(s.flows, "day"), "day") == pytest.approx(A.xirr(s.flows), rel=1e-7)


@SETTINGS
@given(dates, st.floats(1_000, 1e6), st.lists(st.floats(1, 5_000), min_size=1, max_size=60), st.floats(1.001, 1.5))
@example(date(2027, 1, 28), 1_000.0, [1.0], 1.01)       # one payment, Jan 28 -> Feb 28
@example(date(2027, 1, 30), 1_000.0, [1.0] * 13, 1.2)    # a series on the 30th through February
def test_monthly_apr_agrees_with_brentq(fd, adv, raw, markup):
    """Payments on monthly anniversaries (clamped to the month end, so funding on the 29th-31st is included,
    and a single payment is included): Appendix J reduces to sum a_k (1+i)^-k = 0, solved here by
    scipy's brentq, which shares no code with CapKit's scan-and-bisect solver. markup >= 1.001 keeps the
    root clear of 0, where pv changes sign only in the last bits; the bracket is checked, not assumed."""
    brentq = pytest.importorskip("scipy.optimize").brentq
    total = sum(raw)
    assume(total > 0)
    pays = [x / total * adv * markup for x in raw]
    flows = [(fd, adv)] + [(add_months(fd, k + 1), -p) for k, p in enumerate(pays) if p > 0]
    assume(len(flows) >= 2)                        # at least one payment; one payment is kept on purpose
    pv = lambda i: adv - sum(p / (1 + i) ** (k + 1) for k, p in enumerate(pays))
    lo, hi = 1e-9, 10.0
    assume(pv(lo) < 0 < pv(hi))                    # a root inside the bracket (pv rises in i)
    i = brentq(pv, lo, hi, xtol=1e-15)
    assert A.apr_actuarial(flows, "month") == pytest.approx(12 * i, rel=1e-8, abs=1e-10)


# ---- Input validation in the disclosure path: every rejection is a ValueError with a message -----------
@pytest.mark.parametrize("call", [
    lambda: D.historical_average([], 6, "CA"),
    lambda: D.historical_average([1.0, 2.0], 2, "CA", "preceding", (0, 1)),
    lambda: D.estimate(100, 120, 0.1, 1_000, state="TX"),
    lambda: D.estimate(float("nan"), 120, 0.1, 1_000),
    lambda: D.estimate(100, 120, 0.1, 1_000, prepaid_fees=-1),
    lambda: D.estimate(100, 120, 1.5, 1_000),
    lambda: D.estimate(100, 100, 0.1, 1_000),
])
def test_disclosure_inputs_are_validated(call):
    with pytest.raises(ValueError):
        call()


def test_split_schedule_starting_after_month_1_uses_split_rate_first():
    e = D.estimate(100, 130, 0.1, 1_000, frequency="month", split_schedule=[[3, 0.2]])
    assert e["split_schedule"][0] == [1, 0.1] and e["split_schedule"][1] == [3, 0.2]


# ---- one payment under an explicit monthly unit: measured to the zero point's day -------------------------
@pytest.mark.parametrize("fd,pd", [("2027-01-28", "2027-02-28"), ("2027-03-30", "2027-04-30"),
                                   ("2027-01-30", "2027-02-28"), ("2027-01-31", "2027-02-28"),
                                   ("2027-01-15", "2027-02-15")])
def test_one_month_single_payment_is_one_month_under_a_monthly_unit(fd, pd):
    """1% for exactly one month is 12% (Appendix J (b)(5)(ii); the same figure apr_single_payment gives).
    Before the fix Jan 28 -> Feb 28 gave 10.900% and Mar 30 -> Apr 30 gave 11.609%."""
    flows = [(fd, 100), (pd, -101)]
    assert api.apr(flows, "month")["apr_actuarial"] == pytest.approx(0.12, abs=1e-12)
    assert api.apr(flows, "month")["apr_us_rule"] == pytest.approx(0.12, abs=1e-12)
    assert A.apr_actuarial(flows) == pytest.approx(0.12, abs=1e-12)


@SETTINGS
@given(dates, st.integers(1, 11), st.floats(1.001, 1.5))
@example(date(2027, 1, 28), 1, 1.01)       # the two inputs that gave 10.900% and 11.609% instead of 12%
@example(date(2027, 3, 30), 1, 1.01)
def test_single_payment_under_a_monthly_unit_has_the_closed_form_rate(fd, months, markup):
    """One advance A, one payment A x m exactly ``months`` later (clamped to the month end): the general
    equation with a monthly unit is (1 + i)^months = m, so APR = 12 x (m^(1/months) - 1). Every funding day,
    the 29th-31st included. (The term-as-unit rule of apr_single_payment agrees only for one month.)"""
    pd = add_months(fd, months)
    flows = [(fd, 1_000.0), (pd, -1_000.0 * markup)]
    assert A.apr_actuarial(flows, "month") == pytest.approx(12 * (markup ** (1 / months) - 1), rel=1e-9)
    if months == 1:
        assert A.apr_actuarial(flows, "month") == pytest.approx(
            A.apr_single_payment(1_000.0, 1_000.0 * markup, fd, pd), rel=1e-9)


# ---- API contract: wrong inputs are errors with a message, never a silent partial answer ----------------
@pytest.mark.parametrize("call,match", [
    (lambda: api.apr([["2027-01-01", 100], ["2027-02-01", -50], ["2027-03-01", -52]], method="actuarail"),
     "method"),
    (lambda: api.apr([["2027-01-01", 100], [1, -50], [2, -52]]), "mix"),
    (lambda: api.apr([]), "empty"),
    (lambda: api.apr([["2027-01-01", True], ["2027-02-01", -101]]), "true/false"),
    (lambda: D.historical_average([1, 2, 3, 4, 5], 4, "CA", "preceding", [-1]), "indexes"),
    (lambda: D.historical_average([1, 2, 3, 4, 5], 4, "CA", "preceding", [5]), "indexes"),
])
def test_contract_violations_are_value_errors(call, match):
    with pytest.raises(ValueError, match=match):
        call()


def test_early_pay_cost_returns_the_finite_nominal_rate_when_the_effective_rate_overflows():
    r = api.early_pay_cost(0.99, 0, 1)
    assert r["nominal"] == pytest.approx(0.99 / 0.01 * 365) and r["effective"] is None and "warning" in r


# --- review follow-ups (each failed before its fix) -------------------------------------------------------

def test_gross_reading_never_breaks_the_net_estimate():
    # The gross reading of these inputs has no solvable APR; the net estimate must still be returned.
    e = D.estimate(100, 120, 0.10, 1000, frequency="month", prepaid_fees=99.999)
    assert e["amount_financed"] == pytest.approx(100)
    assert "error" in e["if_funding_provided_is_before_fees"]


def test_lender_paid_sba_fee_needs_no_prior_fee():
    s = PR.sba_7a(100000, 0.075, borrower_pays_fee=False, approval_date="2026-11-01",
                  funding_date="2026-11-15", prior_90_day_amount=100000)
    assert s.terms["upfront_fee"] == 0.0


def test_returned_lease_has_no_buyout():
    with pytest.raises(ValueError, match="no buyout"):
        PR.equipment_lease(10000, 500, 24, buyout=1, end_of_term="return")


def test_owned_lease_flag_does_not_blame_a_buyout():
    r = api.true_cost({"type": "equipment_lease", "equipment_cost": 10000, "payment": 500, "months": 24,
                       "end_of_term": "own"}, marginal_rate=0.3)
    assert "keeping the equipment" in r["flag"]


def test_huge_integer_is_a_named_value_error():
    with pytest.raises(ValueError, match="net_days is too large"):
        api.call("early_pay_cost", {"discount": 0.02, "discount_days": 10, "net_days": 10 ** 400})
