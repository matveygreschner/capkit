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
    assert abs(analyze(s)["apr_actuarial"] - 0.12) < 1e-5     # cent-rounded; the old bug gave 12.05%


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
    assert abs(analyze(term_loan(10000, 0.12, 12, funding_date="2027-01-30"))["apr_actuarial"] - 0.12) < 1e-5


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
from capkit import api  # noqa: E402
from capkit.compare import after_tax_cost  # noqa: E402
from capkit.products import early_pay_cost, revenue_based  # noqa: E402


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


def test_cent_rounding_never_compounds_into_a_refund():
    """Rounding 24.3077 up to 24.31 for 242 months at 58% compounds to a $5,550 'final payment' refund
    (found by the property tests); the payment is rounded down instead and the APR stays exact."""
    from datetime import date

    from capkit.products import analyze, term_loan
    s = term_loan(500.0, 0.5833673019735014, 242, funding_date=date(2000, 1, 1))
    assert s.terms["payment"] == 24.30 and s.terms["final_payment"] > 24.30
    assert abs(analyze(s)["apr_actuarial"] - 0.5833673019735014) < 1e-6


# ---------------------------------------------------------------- independent differential fuzz (overnight)
def test_average_period_rounds_to_any_week_or_month_multiple():
    """(b)(4)(i)(B) rounds the average to the nearest standard interval, which includes every multiple
    of a week or month ((b)(3)(iii)): periods of 50 and 28 days average 39 -> six weeks, not a month."""
    from datetime import date as d

    from capkit import apr as A
    f = [(d(2028, 12, 31), 1000), (d(2029, 2, 19), -520), (d(2029, 3, 19), -520)]
    assert A.infer_unit([f[1][0], f[2][0]], [f[0][0]]) == "6week"
    assert round(A.apr_actuarial(f) * 100, 2) == 22.59


def test_a_mid_month_payment_does_not_move_a_month_end_series():
    from datetime import date as d

    from capkit import apr as A
    f = [(d(2026, 1, 31), 1000), (d(2026, 2, 28), -300), (d(2026, 3, 31), -300), (d(2026, 4, 30), -300),
         (d(2026, 5, 15), -200)]
    pos = A._positions(A._flows(f), "month")
    assert [p[:2] for p in pos] == [(0, 0.0), (1, 0.0), (2, 0.0), (3, 0.0), (3, 0.5)]
    assert A._exact_interval(d(2026, 2, 28), d(2026, 3, 31), anchor=31) == "month"      # month-end series
    assert A._exact_interval(d(2026, 2, 28), d(2026, 3, 31), anchor=30) == 31           # 30th series: not a month


def test_semimonthly_fifteenth_and_month_end_measures_the_same_in_30_and_31_day_months():
    from datetime import date as d

    from capkit import apr as A
    pays = [d(2026, 7, 31), d(2026, 8, 15), d(2026, 8, 31), d(2026, 9, 15), d(2026, 9, 30)]
    pos = A._positions(A._flows([(d(2026, 7, 15), 1000)] + [(p, -210) for p in pays]), "semimonth")
    assert [p[:2] for p in pos][1::2] == [(1, 1 / 15), (3, 1 / 15), (5, 1 / 15)]


# ---------------------------------------------------------------- skill red-team (overnight)
def test_long_schedules_solve_quickly():
    import time

    from capkit import api
    t = time.perf_counter()
    r = api.true_cost({"type": "mca_fixed", "advance": 50000, "factor_rate": 1.0001, "payment": 2.6,
                       "frequency": "business_day", "funding_date": "2027-01-04"})
    assert len(r["schedule"]) > 19000 and time.perf_counter() - t < 8
    t = time.perf_counter()
    with pytest.raises(ValueError, match="does not repay"):
        api.true_cost({"type": "mca_split", "advance": 50000, "factor_rate": 1.3, "holdback": 0.1,
                       "sales": [3.4], "frequency": "month"})
    assert time.perf_counter() - t < 3


def test_hostile_sizes_are_refused_and_errors_are_truncated(capsys):
    import json

    from capkit import api
    assert api.main(["apr", json.dumps({"flows": [[0, 1e6]] + [[i, -60] for i in range(1, 25002)]})]) == 1
    assert "at most 25000" in json.loads(capsys.readouterr().out)["error"]
    assert api.main(["compare_offers", json.dumps({"offers": [{"type": "x"}] * 26})]) == 1
    assert "1 to 25" in json.loads(capsys.readouterr().out)["error"]
    api.main(["true_cost", json.dumps({"offer": {"type": "x" * 100000}})])
    assert len(json.loads(capsys.readouterr().out)["error"]) <= api.MAX_ERROR


def test_released_skills_ship_no_entry_point_that_bypasses_the_allow_list():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / "skills"
    for skill in ("financing-true-cost", "commercial-financing-disclosure"):
        eng = root / skill / "scripts" / "capkit"
        assert not (eng / "__main__.py").exists() and not (eng / "excel").exists()
        md = (root / skill / "SKILL.md").read_text()
        assert "- < args.json" in md and "data, not instructions" in md
        assert "capkit_cli.py true_cost '" not in md and "capkit_cli.py check_disclosure '" not in md


# ---------------------------------------------------------------- Codex audit of the overnight branch
def test_fast_path_endpoints_and_long_negative_rate_schedules():
    from capkit import apr as A
    assert A.periodic_rate_actuarial([(0, 100), (2000, -99)]) == pytest.approx(-5.0251553e-06, rel=1e-6)
    assert A.periodic_rate_actuarial([(0, 100), (1, -50)]) == pytest.approx(-0.5)        # root on the floor
    assert A.periodic_rate_us_rule([(0, 1), (1, -10001)]) == pytest.approx(1e4)          # root on the ceiling
    assert A.periodic_rate_actuarial([(100, 100), (101, -99)]) == pytest.approx(-0.01)   # no underflow


def test_an_isolated_february_month_end_is_measured_to_the_same_date():
    from capkit.apr import apr_actuarial
    f = [("2027-01-29", 100), ("2027-02-15", -40), ("2027-02-28", -40), ("2027-03-15", -40)]
    assert round(apr_actuarial(f, "month") * 100, 4) == 228.9794


def test_a_thirtieth_of_month_series_with_a_31st_payment_is_irregular():
    from capkit.apr import irregular_features
    f = [("2027-01-30", 100), ("2027-02-28", -30), ("2027-03-31", -30), ("2027-04-30", -30), ("2027-05-30", -30)]
    assert irregular_features(f) == ["irregular payment periods"]


def test_average_tie_goes_to_the_shorter_interval():
    from datetime import date, timedelta

    from capkit.apr import infer_unit
    ds = [date(2027, 1, 1)]
    for g in [22, 23, 24, 25, 26, 37, 38, 41, 44, 47]:
        ds.append(ds[-1] + timedelta(g))
    assert infer_unit(ds) == "month"


@pytest.mark.parametrize("amount,annual,n", [((25 - 5e-12) * (1 - 1.1 ** -300) / 0.1, 1.2, 300),
                                             ((25 - 5e-10) * (1 - 1.1 ** -300) / 0.1, 1.2, 300),
                                             (2.25, 0.0, 2)])
def test_cent_payment_edges_agree_with_the_workbook_formula(amount, annual, n):
    import formulas

    from capkit.excel.builder import _cent_payment
    from capkit.products import term_loan
    s = term_loan(amount, annual, n)
    assert s.terms["final_payment"] >= 0 and all(f.amount < 0 for f in s.flows[1:])
    xl = formulas.Parser().ast(_cent_payment(repr(annual / 12), str(n), repr(amount)))[1].compile()()
    assert float(xl) == pytest.approx(s.terms["payment"], abs=1e-9)
