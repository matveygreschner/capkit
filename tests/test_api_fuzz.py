"""Fuzz of the JSON contract of every released skill command: for ANY JSON arguments, the CLI prints one
JSON document and either returns a result (exit 0) or ``{"error": "ValueError: ..."}`` (exit 1). A raw
TypeError/KeyError/... or a traceback fails the test. Runs in-process on src/ (build_skills.py --check keeps
the vendored copies byte-identical); test_cli_contract.py runs the real vendored CLIs on fixed inputs."""
import inspect
import io
import json
import re
from contextlib import redirect_stdout
from pathlib import Path

import pytest
from hypothesis import example, given
from hypothesis import strategies as st

from capkit import api
from capkit import products as PR

ROOT = Path(__file__).resolve().parents[1]


def _allowed(skill):
    text = (ROOT / "skills" / skill / "scripts" / "capkit_cli.py").read_text()
    return json.loads(re.search(r"COMMANDS = (\[.*\])", text).group(1).replace("'", '"'))


ALLOWED = {s: _allowed(s) for s in ("financing-true-cost", "commercial-financing-disclosure")}
OFFER = {"type": "term_loan", "amount": 10_000, "annual_rate": 0.1, "months": 12}
OFFERS = {                     # one valid offer per builder; the fuzz breaks the terms of each
    "mca_fixed": {"advance": 50_000, "factor_rate": 1.35, "payment": 2_250, "frequency": "week"},
    "mca_split": {"advance": 50_000, "factor_rate": 1.3, "holdback": 0.1, "sales": [80_000] * 12},
    "revenue_based": {"advance": 50_000, "cap_multiple": 1.4, "revenue_share": 0.08, "revenue": [90_000] * 24},
    "term_loan": {"amount": 10_000, "annual_rate": 0.1, "months": 12},
    "sba_7a": {"amount": 100_000, "approval_date": "2026-11-01"},
    "line_of_credit": {"draw": 10_000, "annual_rate": 0.2, "weeks": 8},
    "factoring": {"face": 10_000, "advance_rate": 0.8, "fee_per_30_days": 0.03, "days_to_pay": 45},
    "trade_credit": {"invoice": 10_000, "discount": 0.02, "discount_days": 10, "net_days": 30},
    "equipment_lease": {"equipment_cost": 10_000, "payment": 500, "months": 24},
}
assert set(OFFERS) == set(PR.BUILDERS), set(PR.BUILDERS) ^ set(OFFERS)
EST = {"funding_provided": 100_000, "total_owed": 130_000, "split_rate": 0.1, "avg_monthly_sales": 60_000}
BASE = {                       # one valid call per command; the fuzz breaks it one value at a time
    "true_cost": {"offer": OFFER},
    "compare_offers": {"offers": [OFFER, {"type": "mca_fixed", "advance": 50_000, "factor_rate": 1.35,
                                          "payment": 2_250, "frequency": "week"}]},
    "apr": {"flows": [["2027-01-04", 10_000], ["2027-02-04", -5_100], ["2027-03-04", -5_100]]},
    "early_pay_cost": {},
    "sba_fee": {"amount": 100_000, "approval_date": "2026-11-01"},
    "params": {},
    "disclosure_estimate": dict(EST),
    "check_disclosure": {"disclosed_apr": 0.5, **EST},
}
CMDS = sorted({c for cmds in ALLOWED.values() for c in cmds} - {"prime_rate"})     # prime_rate is network
assert set(CMDS) <= set(BASE), set(CMDS) - set(BASE)

WORDS = ["2027-01-04", "2027-02-29", "20270104", "business_day", "week", "month", "day", "CA", "NY", "gross",
         "net", "own", "return", "term_loan", "mca_fixed", "mca_split", "equipment_lease", "sba_7a", ""]
scalars = (st.none() | st.booleans() | st.integers(-10**6, 10**6) | st.integers(-3, 30)
           | st.integers(-3, 400).map(float)          # 12.0 for an int term: JSON writers emit these
           | st.floats(-1e7, 1e7, allow_nan=False) | st.floats(0, 1) | st.sampled_from(WORDS) | st.text(max_size=4))
values = st.recursive(scalars, lambda inner: st.lists(inner, max_size=4)
                      | st.dictionaries(st.sampled_from(sorted(OFFER) + ["type", "x"]), inner, max_size=4),
                      max_leaves=10)


def _keys(cmd):
    return sorted(api.describe(cmd)["args"]) + ["unknown"]


@st.composite
def calls(draw):
    cmd = draw(st.sampled_from(CMDS))
    args = json.loads(json.dumps(BASE[cmd]))
    if cmd == "true_cost":                           # any builder, not only the term loan
        kind = draw(st.sampled_from(sorted(OFFERS)))
        args["offer"] = {"type": kind, **json.loads(json.dumps(OFFERS[kind]))}
    for _ in range(draw(st.integers(1, 3))):          # replace 1-3 values: top level or inside the offer/flows
        where = draw(st.sampled_from(["top", "nested"]))
        if where == "nested" and "offer" in args and isinstance(args["offer"], dict):
            kind = args["offer"].get("type")
            known = isinstance(kind, str) and kind in PR.BUILDERS
            terms = sorted(inspect.signature(PR.BUILDERS[kind]).parameters) if known else sorted(OFFER)
            args["offer"][draw(st.sampled_from(terms + ["colour"]))] = draw(values)
        elif where == "nested" and isinstance(args.get("flows"), list) and args["flows"]:
            args["flows"][draw(st.integers(0, len(args["flows"]) - 1))] = draw(values)
        else:
            args[draw(st.sampled_from(_keys(cmd)))] = draw(values)
    return cmd, args


def _run(cmd, args):
    buf = io.StringIO()
    skill = next(s for s, cmds in ALLOWED.items() if cmd in cmds)
    with redirect_stdout(buf):
        code = api.main([cmd, json.dumps(args)], ALLOWED[skill])
    return code, json.loads(buf.getvalue())


@given(calls())
def test_any_json_arguments_give_a_result_or_a_value_error(call):
    code, out = _run(*call)
    if code == 0:
        assert "result" in out
    else:
        assert code == 1 and out["error"].startswith("ValueError: "), (call, out)


@given(calls())
@example(("true_cost", {"offer": {"type": "term_loan", "amount": 10_000, "annual_rate": 0.1, "months": 12.0}}))
@example(("true_cost", {"offer": {"type": "line_of_credit", "draw": 10_000, "annual_rate": 0.2, "weeks": 8.0}}))
@example(("true_cost", {"offer": {"type": "equipment_lease", "equipment_cost": 10_000, "payment": 500,
                                  "months": 24.0}}))
@example(("true_cost", {"offer": {**OFFER, "funding_date": 5}}))
@example(("true_cost", {"offer": {"type": "mca_fixed", **OFFERS["mca_fixed"], "holidays": 5}}))
def test_the_typed_guard_alone_holds_the_contract(call):
    """The same property with the fallback switched off: the typed guard itself must turn every bad input
    into a ValueError (the fallback is a safety net for engine bugs, not the mechanism)."""
    cmd, args = call
    saved, api._CONTRACT_ERRORS = api._CONTRACT_ERRORS, ()
    try:
        api.call(cmd, args)
    except ValueError:
        pass
    finally:
        api._CONTRACT_ERRORS = saved


@pytest.mark.parametrize("kind, term, whole", [("term_loan", "months", 12.0), ("line_of_credit", "weeks", 8.0),
                                               ("equipment_lease", "months", 24.0)])
def test_whole_number_floats_are_accepted_for_int_terms(kind, term, whole):
    offer = {"type": kind, **OFFERS[kind]}
    as_int = api.true_cost(offer)
    offer[term] = whole
    assert api.call("true_cost", {"offer": offer}) == as_int
