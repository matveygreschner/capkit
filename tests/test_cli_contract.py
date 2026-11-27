"""The released skill entry points, run the way Claude runs them: a fresh, isolated interpreter (-I: no
PYTHONPATH, no user site, no src/ on the path), so only the vendored engine can be imported."""
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RELEASED = ("financing-true-cost", "commercial-financing-disclosure")
FROZEN = ("optimize_mix", "evaluate_mix", "workbook")


def run(skill, *args, stdin=None):
    cli = ROOT / "skills" / skill / "scripts" / "capkit_cli.py"
    p = subprocess.run([sys.executable, "-I", str(cli), *args], input=stdin, capture_output=True, text=True,
                       timeout=120, cwd=ROOT / "skills" / skill)
    out = json.loads(p.stdout)                      # always exactly one JSON document on stdout
    assert p.stderr == "", p.stderr                 # never a traceback
    assert (p.returncode == 1) == ("error" in out)
    return p.returncode, out


@pytest.mark.parametrize("skill", RELEASED)
def test_list_exposes_only_the_skill_commands(skill):
    code, out = run(skill, "list")
    allowed = re.search(r"COMMANDS = (\[.*\])", (ROOT / "skills" / skill / "scripts/capkit_cli.py").read_text())
    assert code == 0 and sorted(out) == sorted(json.loads(allowed.group(1).replace("'", '"')))
    assert not set(out) & set(FROZEN)


@pytest.mark.parametrize("skill", RELEASED)
@pytest.mark.parametrize("cmd", FROZEN)
def test_frozen_commands_are_refused(skill, cmd):
    code, out = run(skill, cmd, "{}")
    assert code == 1 and "not available" in out["error"]


@pytest.mark.parametrize("skill", RELEASED)
@pytest.mark.parametrize("raw", ["", "{", "[]", '{"x": NaN}', '{"offer": {"type": "mca_fixed"}}', "null"])
def test_malformed_input_is_a_json_error(skill, raw):
    code, out = run(skill, "apr", raw)
    assert code == 1 and isinstance(out["error"], str)
    assert not re.match(r"(TypeError|KeyError|IndexError|AttributeError|OverflowError|ZeroDivisionError)", out["error"])


@pytest.mark.parametrize("cmd,args", [
    ("apr", '{"flows": [["2027-01-01",100],["2027-02-01",-50],["2027-03-01",-52]], "method": "actuarail"}'),
    ("apr", '{"flows": [["2027-01-01",100],[1,-50],[2,-52]]}'),
    ("apr", '{"flows": []}'),
])
def test_bad_values_are_value_errors_not_silent_or_raw(cmd, args):
    code, out = run("financing-true-cost", cmd, args)
    assert code == 1 and out["error"].startswith("ValueError: ")


_SBA = '"type": "sba_7a", "amount": 100000, "prime": 0.075, "approval_date": "2026-11-01"'
_EST = '"funding_provided": 100000, "total_owed": 130000, "split_rate": 0.1, "avg_monthly_sales": 60000'


@pytest.mark.parametrize("skill,cmd,args", [         # each one was a raw TypeError/KeyError or a silent 1
    ("financing-true-cost", "apr", '{"flows": [5, ["2027-02-01", -101]]}'),
    ("financing-true-cost", "apr", '{"flows": [["2027-01-01", 100], ["2027-02-01", null]]}'),
    ("financing-true-cost", "apr", '{"flows": [["2027-01-01", 100], ["2027-02-01", [1]]]}'),
    ("financing-true-cost", "true_cost", '{"offer": {"type": "term_loan", "amount": 1e4, "annual_rate": true, '
                                         '"months": 12}}'),
    ("financing-true-cost", "true_cost", '{"offer": {"type": "term_loan", "amount": 1e4, "annual_rate": 0.1, '
                                         '"months": 12, "colour": "red"}}'),
    ("financing-true-cost", "sba_fee", '{"amount": 100000, "approval_date": "2026-11-01", "prior_90_day_fee": 1700}'),
    ("commercial-financing-disclosure", "disclosure_estimate", "{" + _EST + ', "split_schedule": [5]}'),
    ("commercial-financing-disclosure", "disclosure_estimate", "{" + _EST + ', "split_schedule": [[1, true]]}'),
    ("commercial-financing-disclosure", "disclosure_estimate", "{" + _EST + ', "split_schedule": [[1, "0.2"]]}'),
    ("commercial-financing-disclosure", "disclosure_estimate",
     '{"funding_provided": 100000, "total_owed": 130000, "split_rate": 0.1, "monthly_sales": [1, 2, "x", 4, 5, 6]}'),
    ("commercial-financing-disclosure", "disclosure_estimate", "{" + _EST + ', "prepaid_fees": null}'),
    ("commercial-financing-disclosure", "disclosure_estimate", "{" + _EST + ', "frequency": null}'),
    ("commercial-financing-disclosure", "disclosure_estimate", "{" + _EST + ', "window": true}'),
    ("commercial-financing-disclosure", "disclosure_estimate", "{" + _EST + ', "exclude_months": [true]}'),
    ("commercial-financing-disclosure", "check_disclosure", '{"disclosed_apr": 0.5, ' + _EST + ', "irregular": "false"}'),
    ("financing-true-cost", "true_cost", '{"offer": {' + _SBA + ', "prior_90_day_amount": 100000}}'),
    ("financing-true-cost", "true_cost", '{"offer": {' + _SBA + ', "prior_90_day_fee": 1700}}'),
])
def test_wrong_json_types_are_value_errors_through_the_skill(skill, cmd, args):
    code, out = run(skill, cmd, args)
    assert code == 1 and out["error"].startswith("ValueError: "), out


@pytest.mark.parametrize("offer,named", [         # each one named no argument, or was a raw TypeError
    ('{"type": "term_loan", "amount": 1e4, "annual_rate": 0.1, "months": 12, "funding_date": 5}', "offer.funding_date"),
    ('{"type": "term_loan", "amount": 1e4, "annual_rate": 0.1, "months": 12, "funding_date": [1]}', "offer.funding_date"),
    ('{"type": "term_loan", "amount": 1e4, "annual_rate": 0.1, "months": 12, "funding_date": "20270104"}',
     "offer.funding_date"),
    ('{"type": "mca_fixed", "advance": 5e4, "factor_rate": 1.3, "payment": 500, "holidays": 5}', "offer.holidays"),
    ('{"type": "term_loan", "amount": 1e4, "annual_rate": 0.1, "months": 12.5}', "offer.months"),
])
def test_value_errors_name_the_argument(offer, named):
    code, out = run("financing-true-cost", "true_cost", '{"offer": ' + offer + "}")
    assert code == 1 and out["error"].startswith(f"ValueError: {named}"), out


@pytest.mark.parametrize("offer", [
    '{"type": "term_loan", "amount": 10000, "annual_rate": 0.1, "months": 12.0}',
    '{"type": "line_of_credit", "draw": 10000, "annual_rate": 0.2, "weeks": 8.0}',
    '{"type": "equipment_lease", "equipment_cost": 10000, "payment": 500, "months": 24.0}',
])
def test_whole_number_floats_for_int_terms_are_accepted(offer):
    code, out = run("financing-true-cost", "true_cost", '{"offer": ' + offer + "}")
    as_int = run("financing-true-cost", "true_cost", '{"offer": ' + offer.replace(".0}", "}") + "}")[1]
    assert code == 0 and out["result"] == as_int["result"], out


def test_huge_effective_rate_still_returns_the_nominal_rate():
    code, out = run("financing-true-cost", "early_pay_cost", '{"discount":0.99,"discount_days":0,"net_days":1}')
    assert code == 0 and out["result"]["effective"] is None and out["result"]["nominal"] > 36_000


@pytest.mark.parametrize("skill", RELEASED)
def test_describe_without_a_name_is_a_json_error(skill):
    code, out = run(skill, "describe")
    assert code == 1 and out["error"].startswith("ValueError: ")


def _skill_examples(skill):
    """The documented ``args.json`` examples: lines of the form - `command`: `{...}` in SKILL.md."""
    text = (ROOT / "skills" / skill / "SKILL.md").read_text()
    found = re.findall(r"^- `(\w+)`: `(\{.*\})`$", text, re.M)
    return [(cmd, args) for cmd, args in found if "..." not in args]


def test_the_example_parser_finds_the_examples():      # so the next test can never pass by finding none
    assert len(_skill_examples("financing-true-cost")) >= 2
    assert len(_skill_examples("commercial-financing-disclosure")) >= 2


@pytest.mark.parametrize("skill,cmd,args", [(s, c, a) for s in RELEASED for c, a in _skill_examples(s)])
def test_every_documented_example_runs(skill, cmd, args):
    """Run exactly as SKILL.md says: the arguments on stdin (``capkit_cli.py <cmd> - < args.json``)."""
    code, out = run(skill, cmd, "-", stdin=args)
    assert code == 0, out


def test_readme_headline_number():
    code, out = run("financing-true-cost", "true_cost", '{"offer": {"type": "mca_fixed", "advance": 50000, '
                    '"factor_rate": 1.35, "payment": 450, "frequency": "business_day", "funding_date": "2027-01-04"}}')
    assert code == 0 and round(out["result"]["apr_actuarial"] * 100, 2) == 107.14


def test_stdin_input():
    code, out = run("financing-true-cost", "early_pay_cost", "-", stdin='{"discount": 0.02}')
    assert code == 0 and round(out["result"]["nominal"], 4) == 0.3724
