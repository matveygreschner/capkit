"""Hand-checked product cases, the day-count convention cases, SBA fee rules, disclosures and the API."""
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

from capkit import api, params as P
from capkit import disclosures as D
from capkit.calendar import frb_holidays
from capkit.products import (analyze, early_pay_cost, factoring, loc_draw, mca_fixed, sba_7a, term_loan,
                             trade_credit, equipment_lease, mca_split)

ROOT = Path(__file__).resolve().parents[1]


def r2(x):
    return round(x * 100, 2)


def test_weekly_mca():
    a = analyze(mca_fixed(50000, 1.35, 2250, "week"))
    assert r2(a["apr_actuarial"]) == 106.96
    assert round(a["simple_annualized"], 4) == 0.6067
    assert a["finance_charge"] == 17500


def test_weekly_mca_with_fee():
    assert r2(analyze(mca_fixed(50000, 1.35, 2250, "week", fees=1500))["apr_actuarial"]) == 118.60


def test_term_loan():
    s = term_loan(50000, 0.15, 24, fee=1500)
    assert s.terms["payment"] == 2424.33
    assert r2(analyze(s)["apr_actuarial"]) == 18.13
    assert abs(analyze(term_loan(50000, 0.15, 24))["apr_actuarial"] - 0.15) < 1e-9


def test_early_pay():
    c = early_pay_cost(0.02, 10, 30)
    assert round(c["nominal"] * 100, 2) == 37.24 and round(c["effective"] * 100, 2) == 44.59


@pytest.mark.parametrize("fund,hol,expected,last", [
    ("2027-01-04", None, 110.40, date(2027, 8, 2)),
    ("2027-01-04", "frb", 107.14, date(2027, 8, 6)),
    ("2027-01-08", None, 108.55, date(2027, 8, 6)),
    ("2027-01-10", None, 110.87, date(2027, 8, 6)),
])
def test_daily_mca_calendar_day_convention(fund, hol, expected, last):
    s = mca_fixed(50000, 1.35, 450, "business_day", fund, holidays=hol)
    assert s.unit == "day" and s.flows[-1].when == last
    assert r2(analyze(s)["apr_actuarial"]) == expected


def test_business_day_x_365_is_never_the_apr():
    a = analyze(mca_fixed(50000, 1.35, 450, "business_day", "2027-01-04"))
    assert abs(a["apr_actuarial"] - 1.533) > 0.3


def test_frb_holidays_saturday_rule():
    h = frb_holidays(2027)    # Juneteenth and Christmas 2027 fall on Saturday: no Friday observance
    assert date(2027, 6, 18) not in h and date(2027, 12, 24) not in h
    assert date(2027, 7, 5) in h            # July 4 2027 is a Sunday -> Monday
    assert {date(2027, 1, 18), date(2027, 2, 15), date(2027, 5, 31)} <= h


def test_sba_fee_on_guaranteed_portion_and_ceiling():
    s = sba_7a(42548.02, prime=0.07)
    assert s.terms["payment"] == 647.90 and s.terms["upfront_fee"] == 723.32
    assert s.terms["spread"] == pytest.approx(0.065)
    with pytest.raises(ValueError, match="statutory ceiling"):
        P.sba_upfront_fee(100_000, rate=0.03)
    assert P.sba_upfront_fee(100_000) == pytest.approx(1700.0)
    with pytest.raises(ValueError, match="exceeds the SOP"):
        sba_7a(100_000, prime=0.07, spread=0.07)


def test_every_stored_sba_fee_is_within_ceiling():
    for fy, table in P.param("sba_fee_fy").items():
        for bound, rate in table:
            for amt in (bound * 0.5, bound):
                assert rate * P.sba_guaranty_share(amt) * amt <= P.sba_fee_ceiling(amt) + 1e-6


def test_factoring_and_trade_credit_and_loc_and_lease():
    f = factoring(10000, 0.8, 0.03, 45)
    assert f.terms["fee"] == 600 and f.terms["rebate"] == 1400
    assert analyze(f)["apr_actuarial"] > 0.5
    t = analyze(trade_credit(6000, 0.02, 10, 30))
    assert round(t["ear"] * 100, 2) == 44.59
    assert abs(analyze(loc_draw(10000, 0.11, 8))["apr_actuarial"] - 0.11) < 1e-9
    lease = analyze(equipment_lease(30000, 950, 36, buyout=1))
    assert 0.08 < lease["apr_actuarial"] < 0.09     # 30,000 financed by 36 x 950 + $1 buyout


def test_split_mca_stretches_when_sales_fall():
    base = analyze(mca_split(50000, 1.35, 0.10, [2400], "business_day"))
    slow = analyze(mca_split(50000, 1.35, 0.10, [2400 * 0.8], "business_day"))
    assert slow["term_days"] > base["term_days"] and slow["apr_actuarial"] < base["apr_actuarial"]


# ---------------------------------------------------------------- disclosures
def test_historical_window_rules():
    sales = [50, 60, 70, 80, 90, 100, 110, 120, 130, 140, 150, 160, 170]
    assert D.historical_average(sales, 4) == 155
    assert D.historical_average(sales, 4, "NY", "highest") == 155
    with pytest.raises(ValueError):
        D.historical_average(sales, 3)
    with pytest.raises(ValueError):
        D.historical_average(sales, 4, "CA", "highest")


def test_disclosure_estimate_and_both_methods():
    est = D.estimate(50000, 67500, 0.10, 60000, "business_day", "2027-01-04")
    assert est["finance_charge"] == 17500 and est["covered"]
    assert est["number_of_payments"] == 238
    # Holiday gaps make some periods' payment smaller than the interest accrued, so the methods differ.
    assert est["estimated_apr_us_rule"] != est["estimated_apr_actuarial"]
    a, u = est["estimated_apr_actuarial"], est["estimated_apr_us_rule"]
    assert "actuarial" in D.check_disclosed_apr(a, est)["verdict"]
    assert "U.S. Rule" in D.check_disclosed_apr(u, est)["verdict"]
    assert D.check_disclosed_apr(0.35, est)["verdict"] == "inconsistent with both permitted methods"


def test_zero_payment_schedule_disclosure_check_accepts_us_rule():
    """A disclosure made with the U.S. Rule must never be flagged when the methods differ."""
    from capkit.apr import apr_actuarial, apr_us_rule
    f = [(0, 10000)] + [(k, -1150) for k in range(3, 13)]
    comp = {"estimated_apr_actuarial": apr_actuarial(f, "month"), "estimated_apr_us_rule": apr_us_rule(f, "month")}
    assert D.check_disclosed_apr(0.229843, comp)["verdict"] == "consistent (U.S. Rule method)"
    assert D.check_disclosed_apr(0.228099, comp)["verdict"] == "consistent (actuarial method)"
    assert D.check_disclosed_apr(0.2450, comp)["verdict"] == "inconsistent with both permitted methods"


def test_ny_percentage_tolerance():
    comp = {"estimated_apr_actuarial": 1.00, "estimated_apr_us_rule": 1.00}
    assert D.check_disclosed_apr(0.98, comp, "NY")["verdict"].startswith("consistent")      # 2.0% difference
    assert not D.check_disclosed_apr(0.98, comp, "CA")["verdict"].startswith("consistent")


# ---------------------------------------------------------------- params freshness + API
def test_params_have_sources_and_are_fresh():
    for k, e in P.PARAMS.items():
        assert e["source"] and e["verified_on"] and e["status"] in ("verified", "verify", "placeholder")
        assert P.age_days(k) <= P.MAX_AGE_DAYS, f"{k} was last verified {e['verified_on']}: re-check it"


def test_api_list_and_cli_roundtrip():
    assert "optimize_mix" in api.COMMANDS
    out = subprocess.run([sys.executable, "-m", "capkit", "early_pay_cost", '{"discount": 0.02}'],
                         capture_output=True, text=True, cwd=ROOT, env={"PYTHONPATH": str(ROOT / "src")})
    assert round(json.loads(out.stdout)["result"]["nominal"], 4) == 0.3724
    bad = subprocess.run([sys.executable, "-m", "capkit", "sba_fee", '{"amount": 100000, "rate": 0.03}'],
                         capture_output=True, text=True, cwd=ROOT, env={"PYTHONPATH": str(ROOT / "src")})
    assert "statutory ceiling" in json.loads(bad.stdout)["error"]
