"""Workbook portability + structure, and the packaged skills running from their unpacked archives."""
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[1]
BANNED = ("XLOOKUP", "XMATCH", "LET(", "LAMBDA(", "FILTER(", "SORT(", "UNIQUE(", "SEQUENCE(", "_xlfn", "[@",
          "INDIRECT(", "OFFSET(", "MATCH(TRUE")
SKILL_NAMES = ("financing-true-cost", "commercial-financing-disclosure")


@pytest.fixture(scope="module")
def book(tmp_path_factory):
    from capkit.excel.builder import build_workbook
    p = tmp_path_factory.mktemp("wb") / "CapKit.xlsx"
    build_workbook(p)
    return p


def test_workbook_formulas_are_portable(book):
    wb = load_workbook(book)
    n = 0
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for c in row:
                if isinstance(c.value, str) and c.value.startswith("="):
                    n += 1
                    for b in BANNED:
                        assert b not in c.value.upper(), f"{ws.title}!{c.coordinate} uses {b}: {c.value}"
    assert n > 8000
    assert not wb.defined_names, "no defined names (portability)"


def test_workbook_sheets_and_named_cells(book):
    wb = load_workbook(book)
    assert wb.sheetnames == ["Start", "APR", "Daily_MCA", "Loans", "EarlyPay_Factoring", "Disclosure",
                             "Params_Sources", "Holidays"]
    cells = json.loads(book.with_suffix(".cells.json").read_text())
    for sheet, names in cells.items():
        for name, addr in names.items():
            assert wb[sheet][addr].value is not None or name in ("sba_spread_in", "sba_fee_in"), (sheet, name)


def test_skills_valid_and_in_sync():
    r = subprocess.run([sys.executable, str(ROOT / "scripts/build_skills.py"), "--check"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


@pytest.fixture(scope="module")
def unpacked(tmp_path_factory):
    subprocess.run([sys.executable, str(ROOT / "scripts/build_skills.py")], check=True, capture_output=True)
    d = tmp_path_factory.mktemp("installed")
    for name in SKILL_NAMES:
        with zipfile.ZipFile(ROOT / "dist" / f"{name}.zip") as z:
            z.extractall(d)
    return d


def _run(skill_dir: Path, *args, cwd, stdin=None, isolated=True):
    # -I: isolated mode, so only the skill's vendored engine can be imported (not ./src). The optimizer
    # test uses -E instead so a user-site scipy stays importable; capkit itself is never installed.
    flags = ["-I", "-B"] if isolated else ["-E", "-B"]
    r = subprocess.run([sys.executable, *flags, str(skill_dir / "scripts/capkit_cli.py"), *args],
                       capture_output=True, text=True, cwd=cwd, input=stdin)
    return r.returncode, json.loads(r.stdout)


def test_true_cost_from_archive(unpacked, tmp_path):
    code, out = _run(unpacked / "financing-true-cost", "true_cost",
                     json.dumps({"offer": {"type": "mca_fixed", "advance": 50000, "factor_rate": 1.35, "payment": 450,
                                           "frequency": "business_day", "funding_date": "2027-01-04"}}), cwd=tmp_path)
    assert code == 0 and round(out["result"]["apr_actuarial"] * 100, 2) == 107.14


def test_disclosure_from_archive(unpacked, tmp_path):
    code, out = _run(unpacked / "commercial-financing-disclosure", "check_disclosure",
                     json.dumps({"disclosed_apr": 0.6781, "funding_provided": 50000, "total_owed": 67500,
                                 "split_rate": 0.10, "avg_monthly_sales": 60000}), cwd=tmp_path)
    assert code == 0 and "U.S. Rule method" in out["result"]["check"]["verdict"]
    code, out = _run(unpacked / "commercial-financing-disclosure", "check_disclosure",
                     json.dumps({"disclosed_apr": 0.60, "funding_provided": 50000, "total_owed": 67500,
                                 "split_rate": 0.10, "avg_monthly_sales": 60000}), cwd=tmp_path)
    assert out["result"]["check"]["verdict"] == "inconsistent with both permitted methods"


def test_optimizer_skill_is_not_released():
    """The funding-mix optimizer is frozen (experimental): it must not ship as a release asset."""
    assert not (ROOT / "dist" / "funding-mix-optimizer.zip").exists()


def test_released_skills_cannot_run_frozen_commands(unpacked, tmp_path):
    sc = json.loads((ROOT / "examples/bakery.json").read_text())
    code, out = _run(unpacked / "financing-true-cost", "optimize_mix", json.dumps({"scenario": sc}), cwd=tmp_path)
    assert code == 1 and "not available in this skill" in out["error"]
    assert not (unpacked / "financing-true-cost/scripts/capkit/optimize").exists()


def test_archive_layout(unpacked):
    for name in SKILL_NAMES:
        d = unpacked / name
        assert (d / "SKILL.md").exists() and (d / "scripts/capkit/apr.py").exists()
        assert (d / "references/commands.md").exists() and (d / "references/parameters.md").exists()
        assert not (d / "evals").exists()
