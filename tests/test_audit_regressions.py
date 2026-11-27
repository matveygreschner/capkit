"""Regression tests: every concrete counterexample from the independent Codex audit (Nov 2026)."""
from datetime import date

import pytest

from capkit import apr as A
from capkit import disclosures as D
from capkit.products import analyze, equipment_lease, factoring, mca_fixed, mca_split, term_loan


# ---------------------------------------------------------------- APR engine
def test_two_close_roots_are_both_found():
    fn = lambda i: 100 - 220.1 / (1 + i) + 121.11 / (1 + i) ** 2
    assert [round(r, 6) for r in A.roots(fn)] == [0.1, 0.101]
    assert A.count_rates([(0, 100), (1, -220.1), (2, 121.11)], "month") == 2


def test_single_advance_single_payment_uses_term_as_unit():
    # $100 on Jan 4, $110 on Jan 24: Appendix J (c)(5) Form 1 -> 365/20 x 10% = 182.50%
    assert round(A.apr_actuarial([(date(2027, 1, 4), 100), (date(2027, 1, 24), -110)]) * 100, 2) == 182.50


def test_month_end_series_counts_whole_months():
    # a fee-free 12% loan funded Jan 31 with month-end payments is exactly 12%, not 12.05%
    s = term_loan(10000, 0.12, 12, funding_date="2027-01-31")
    assert abs(analyze(s)["apr_actuarial"] - 0.12) < 1e-9


@pytest.mark.parametrize("dates,unit", [
    ([date(2027, 1, 1)] + [date.fromordinal(date(2027, 1, 1).toordinal() + 28 * k) for k in range(1, 10)], "4week"),
    ([date(2027, 1, 1), date(2027, 1, 16), date(2027, 2, 1), date(2027, 2, 16), date(2027, 3, 1)], "semimonth"),
    ([date(2027, 1, 15), date(2027, 2, 15), date(2027, 3, 15), date(2027, 4, 15)], "month"),
])
def test_unit_period_inference(dates, unit):
    assert A.infer_unit(dates) == unit


def test_us_rule_does_not_accrue_on_a_credit_balance():
    # a payment before the advance must not earn the borrower phantom interest
    v = A.apr_us_rule([(0, -10), (1, 110), (2, -105)], "month")
    assert v > 0


def test_fractional_period_methods_can_differ():
    f = [(0, 100), (0.5, -20), (1, -89.25)]
    assert round(A.apr_actuarial(f, "month") * 100, 2) == 122.67
    assert round(A.apr_us_rule(f, "month") * 100, 2) == 120.00


def test_extreme_short_schedule_does_not_crash_analysis():
    a = analyze(mca_fixed(100, 1.35, 135, "day"))
    assert a["apr_actuarial"] > 1 and a["xirr"] > 1e40          # finite: about 3.731e47


def test_double_root_counts_once_and_undefined_rate_is_an_error():
    assert len(A.roots(lambda i: 100 - 220 / (1 + i) + 121 / (1 + i) ** 2)) == 1
    with pytest.raises(ValueError, match="undefined"):
        A.apr_actuarial([(0, 100), (0, -100)], "month")


def test_irregular_and_multiple_advance_unit_periods():
    d = date
    f = [(d(2027, 1, 4), 100), (d(2027, 1, 12), -30), (d(2027, 1, 21), -30), (d(2027, 2, 15), -55)]
    assert round(A.apr_actuarial(f) * 100, 2) == 202.74                 # no common period -> biweek average
    g = [(d(2027, 1, 1), 100), (d(2027, 1, 8), -20), (d(2027, 1, 22), 100), (d(2027, 1, 29), -100),
         (d(2027, 2, 19), -100)]
    assert round(A.apr_actuarial(g) * 100, 2) == 143.38                 # common 21-day period
    assert abs(analyze(term_loan(10000, 0.12, 12, funding_date="2027-01-30"))["apr_actuarial"] - 0.12) < 1e-9


# ---------------------------------------------------------------- products
def test_lease_net_proceeds_match_the_opening_flow():
    s = equipment_lease(10000, 500, 24, advance_payments=2, fees=100)
    assert s.net_proceeds == s.flows[0].amount == 8900


def test_split_mca_rejects_negative_sales_and_never_overruns_dates():
    with pytest.raises(ValueError, match="zero or positive"):
        mca_split(100, 1.2, 1, [1, -2], frequency="month")
    s = mca_split(50000, 1.35, 0.10, [2400], "month")          # 282 monthly payments: no date-array overrun
    assert len(s.flows) == 283


def test_factoring_is_priced_as_single_payment():
    a = analyze(factoring(10000, 0.8, 0.03, 45))
    assert a["unit_period"] == "term" and round(a["apr_actuarial"] * 100, 2) == 60.83


# ---------------------------------------------------------------- disclosures
def test_excluded_month_does_not_pull_in_older_months():
    assert D.historical_average([1000, 100, 100, 100, 0], 4, exclude=[4]) == 100


def test_ny_percentage_difference_is_signed_and_zero_safe():
    comp = {"estimated_apr_actuarial": 0.50, "estimated_apr_us_rule": 0.50}
    assert D.check_disclosed_apr(0.60, comp, "NY")["verdict"].startswith("consistent")      # over-disclosure
    zero = D.check_disclosed_apr(0.0, comp, "NY")
    assert zero["verdict"].startswith("not reproduced") and zero["not_modeled"]


def test_non_match_is_never_called_a_violation():
    comp = {"estimated_apr_actuarial": 0.50, "estimated_apr_us_rule": 0.50}
    r = D.check_disclosed_apr(0.30, comp, "CA")
    assert "not proof" in r["what_to_check"] and "inconsistent" not in r["verdict"]


# ---------------------------------------------------------------- experimental optimizer's evaluator
def test_evaluator_rejects_early_pay_share_above_one():
    from capkit.verify.reprice import evaluate
    sc = {"horizon_weeks": 2, "starting_cash": 200, "operating_cash_flow": [0, 0],
          "invoices": [{"week": 1, "amount": 100, "discount": 0.02, "discount_week": 1, "net_week": 2}]}
    r = evaluate(sc, {"early_pay": {"0": 2}})
    assert not r["feasible"] and "between 0 and 1" in r["problems"][0]


def test_evaluator_applies_mca_prepay_penalty_like_the_model():
    pytest.importorskip("scipy")
    from capkit.optimize.report import optimize
    sc = {"horizon_weeks": 4, "starting_cash": 0, "operating_cash_flow": [-100, 200, 0, 0],
          "offers": [{"name": "MCA", "type": "mca", "weeks": [1, 1], "min": 100, "max": 100, "factor_rate": 1.2,
                      "weekly_debit_per_dollar": 0.1, "payoff_discount": 0.5, "prepay_penalty": 0.2}]}
    r = optimize(sc)
    assert r["optimal"] and abs(r["check"]["terminal_net_position"] - r["objective"]) < 1e-6


# ---------------------------------------------------------------- second Codex audit: input validation
from capkit.products import early_pay_cost, revenue_based, sba_7a  # noqa: E402
from capkit.compare import after_tax_cost  # noqa: E402
from capkit import api  # noqa: E402


@pytest.mark.parametrize("call", [
    lambda: early_pay_cost(0.02, 30, 10),                           # discount after net date
    lambda: factoring(10000, 0.8, 0.03, 45, fee_basis="typo"),      # unknown fee basis
    lambda: revenue_based(100, 1.5, 1.2, [100]),                    # 120% revenue share
    lambda: mca_fixed(100, 1.35, 0.000001),                         # would need ~135 million debits
    lambda: mca_fixed(100, 1.35, 10, "fortnightly"),                # unknown frequency
    lambda: term_loan(1000, float("nan"), 12),
    lambda: after_tax_cost(100, "interest", 2.0),                   # 200% marginal rate
])
def test_bad_inputs_raise_instead_of_returning_numbers(call):
    with pytest.raises(ValueError):
        call()


def test_holiday_strings_are_honoured():
    s = mca_fixed(1000, 1.1, 100, "business_day", "2027-01-15", holidays=["2027-01-18"])
    assert date(2027, 1, 18) not in [f.when for f in s.flows]


def test_api_rejects_nan_and_hides_frozen_commands_when_absent():
    with pytest.raises(ValueError, match="not a finite"):
        api.call("early_pay_cost", {"discount": float("nan")})


def test_conditional_sale_lease_gets_no_after_tax_figure():
    s = equipment_lease(10000, 500, 24, buyout=1)
    r = after_tax_cost(1400.70, s.tax_character, 0.30)
    assert r["after_tax_finance_charge"] is None and "conditional sale" in r["flag"]
