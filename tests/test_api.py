"""The JSON command layer the skills call: every command end to end, the allow-list, and error reporting."""
import contextlib
import io
import json
import runpy
import sys

import pytest

from capkit import api, compare, live

MCA = {"type": "mca_fixed", "advance": 50000, "factor_rate": 1.35, "payment": 2250, "frequency": "week",
       "funding_date": "2027-01-04"}
LOAN = {"type": "term_loan", "amount": 50000, "annual_rate": 0.11, "months": 36, "fee": 1000,
        "funding_date": "2027-01-04", "name": "bank"}


def run(*argv, allowed=None, stdin=None):
    buf = io.StringIO()
    old = sys.stdin
    if stdin is not None:
        sys.stdin = io.StringIO(stdin)
    try:
        with contextlib.redirect_stdout(buf):
            code = api.main(list(argv), allowed)
    finally:
        sys.stdin = old
    return code, json.loads(buf.getvalue()) if buf.getvalue().lstrip().startswith(("{", "[")) else buf.getvalue()


def ok(*argv, **kw):
    code, out = run(*argv, **kw)
    assert code == 0, out
    return out["result"] if isinstance(out, dict) and "result" in out else out


def err(*argv, **kw):
    code, out = run(*argv, **kw)
    assert code == 1 and "error" in out
    return out["error"]


def test_help_list_and_describe():
    assert "python -m capkit.api" in run()[1] and "python -m capkit.api" in run("--help")[1]
    listing = ok("list")
    assert {"true_cost", "check_disclosure", "sba_fee"} <= set(listing)
    d = ok("describe", "sba_fee")
    assert d["args"]["amount"] == "REQUIRED" and "approval_date" in d["doc"]


def test_allow_list_hides_and_blocks_commands():
    allowed = ["apr", "params"]
    assert set(ok("list", allowed=allowed)) == set(allowed)
    assert "not available in this skill" in err("true_cost", json.dumps({"offer": MCA}), allowed=allowed)
    assert "not available in this skill" in err("describe", "true_cost", allowed=allowed)


def test_true_cost_with_after_tax_view():
    r = ok("true_cost", json.dumps({"offer": MCA, "marginal_rate": 0.3}))
    assert r["apr_actuarial"] > 0.5 and r["schedule"][0]["amount"] == 50000
    assert r["after_tax_finance_charge"] == pytest.approx(r["finance_charge"] * 0.7, abs=0.01)
    assert "if_treated_as_interest" in r


def test_compare_offers_ranks_by_apr():
    r = ok("compare_offers", json.dumps({"offers": [MCA, LOAN], "marginal_rate": 0.25, "interest_limited": True}))
    names = [o["name"] for o in r["offers"]]
    assert names == ["bank", "mca_fixed"] and [o["rank"] for o in r["offers"]] == [1, 2]
    bank = r["offers"][0]
    assert bank["assumed_deductible"] is False and bank["after_tax_finance_charge"] == pytest.approx(bank["finance_charge"])


def test_apr_command_reads_stdin_and_reports_multiple_rates():
    r = ok("apr", "-", stdin=json.dumps({"flows": [[0, -100], [1, 230], [2, -132]], "unit": "month"}))
    assert r["rates_that_solve"] == 2 and "warning" in r
    r = ok("apr", json.dumps({"flows": [["2027-01-04", 1000], ["2027-02-04", -1010]], "method": "actuarial"}))
    assert r["unit_period"] == "term" and "apr_us_rule" not in r
    assert "unit must be one of" in err("apr", json.dumps({"flows": [[0, 1], [1, -2]], "unit": "fortnight"}))


def test_early_pay_cost():
    r = ok("early_pay_cost", json.dumps({"discount": 0.02, "discount_days": 10, "net_days": 30}))
    assert r["nominal"] == pytest.approx(0.02 / 0.98 * 365 / 20) and r["effective"] > r["nominal"]


DISC = {"funding_provided": 50000, "total_owed": 65000, "split_rate": 0.10, "funding_date": "2027-01-04"}


def test_disclosure_estimate_from_monthly_sales():
    r = ok("disclosure_estimate", json.dumps({**DISC, "monthly_sales": [90000, 100000, 110000, 95000, 105000, 100000],
                                               "state": "NY", "exclude_months": [0]}))
    assert r["estimated_apr_actuarial"] > 0 and "_schedule" not in r
    assert "give avg_monthly_sales" in err("disclosure_estimate", json.dumps(DISC))


def test_check_disclosure_round_trip_and_implied_finance_charge():
    est = ok("disclosure_estimate", json.dumps({**DISC, "avg_monthly_sales": 100000}))
    r = ok("check_disclosure", json.dumps({**DISC, "avg_monthly_sales": 100000,
                                           "disclosed_apr": est["estimated_apr_actuarial"]}))
    assert r["check"]["verdict"].startswith("consistent")
    assert r["check"]["finance_charge_implied_by_disclosed_apr"] == pytest.approx(15000, abs=1)
    assert "_schedule" not in r["recomputed"] and "no_holiday_calendar" in r
    far = ok("check_disclosure", json.dumps({**DISC, "monthly_sales": [100000] * 6, "disclosed_apr": 0.05}))
    assert far["check"]["verdict"].startswith("not reproduced")
    assert "give avg_monthly_sales" in err("check_disclosure", json.dumps({**DISC, "disclosed_apr": 0.3}))


def test_sba_fee_requires_and_uses_the_approval_date():
    assert "approval_date is required" in err("sba_fee", json.dumps({"amount": 500000}))
    r = ok("sba_fee", json.dumps({"amount": 500000, "approval_date": "2026-10-15"}))
    assert r["fiscal_year"] == 2027 and r["fee"] <= r["ceiling"] and r["zero_fee_rule"]


def test_params():
    assert "sba_fee_fy" in ok("params")
    assert list(ok("params", json.dumps({"key": "sba_fee_fy"}))) == ["sba_fee_fy"]


def test_inputs_must_be_finite_json_objects():
    assert "not a finite number" in err("true_cost", '{"offer": {"type": "mca_fixed", "advance": NaN}}')
    assert "JSON object" in err("apr", "[1, 2]")
    assert "JSONDecodeError" in err("apr", "{not json")


def test_workbook_command_writes_a_file(tmp_path):
    p = tmp_path / "w.xlsx"
    assert ok("workbook", json.dumps({"path": str(p)}))["wrote"] == str(p) and p.stat().st_size > 10000


def test_optimize_mix_wraps_a_bare_scenario(monkeypatch):
    seen = {}
    monkeypatch.setitem(api.COMMANDS, "optimize_mix", lambda scenario, **kw: seen.setdefault("s", scenario))
    api.call("optimize_mix", {"horizon_weeks": 4})
    assert seen["s"] == {"horizon_weeks": 4}


def test_module_entry_point(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["capkit", "early_pay_cost"])
    with pytest.raises(SystemExit) as e:
        runpy.run_module("capkit", run_name="__main__")
    assert e.value.code == 0 and '"nominal"' in capsys.readouterr().out


# ---------------------------------------------------------------- live data (network mocked)
class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_prime_rate_skips_missing_observations(monkeypatch):
    seen = {}

    def fake(req, timeout):
        seen["url"], seen["ua"] = req.full_url, req.get_header("User-agent")
        return _Resp(b"observation_date,DPRIME\n2027-01-04,7.50\n2027-01-05,7.25\n2027-01-06,.\n")
    monkeypatch.setattr(live.urllib.request, "urlopen", fake)
    r = ok("prime_rate")
    assert r["value"] == pytest.approx(0.0725) and r["date"] == "2027-01-05"
    assert seen["url"].endswith("id=DPRIME") and seen["ua"] == "capkit"
    monkeypatch.setattr(live.urllib.request, "urlopen", lambda req, timeout: _Resp(b"d,SOFR\n2027-01-04,.\n"))
    with pytest.raises(ValueError, match="no observations"):
        live.sofr()


def test_after_tax_characters():
    assert compare.after_tax_cost(1000, "rent", 0.3)["after_tax_finance_charge"] == 700
    cs = compare.after_tax_cost(1000, "conditional_sale_likely", 0.3)
    assert cs["after_tax_finance_charge"] is None and "conditional sale" in cs["flag"]
    assert compare.after_tax_cost(1000, "purchase_cost", 0.3)["assumed_deductible"] is True
    for bad in (-0.1, 1.0, float("nan"), "0.3"):
        with pytest.raises(ValueError):
            compare.after_tax_cost(1000, "interest", bad)
