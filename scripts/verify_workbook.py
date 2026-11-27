"""Recalculate CapKit.xlsx with an independent formula engine (``formulas``) and compare every key
output with the Python engine, on fixed cases and randomized inputs.

    python scripts/verify_workbook.py workbook/CapKit.xlsx [--fuzz 10]

Exit code 0 only if every comparison matches (dollars within $0.01, rates within 1e-6).
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import formulas  # noqa: E402

from capkit import disclosures as D  # noqa: E402
from capkit import params as P  # noqa: E402
from capkit.products import analyze, early_pay_cost, factoring, mca_fixed, sba_7a, term_loan  # noqa: E402
from capkit.verify.reprice import evaluate  # noqa: E402

EXCEL_EPOCH = date(1899, 12, 30)


def xl_date(d: date) -> int:
    return (d - EXCEL_EPOCH).days


class Book:
    def __init__(self, path: Path):
        self.cells = json.loads(path.with_suffix(".cells.json").read_text())
        t = time.time()
        self.model = formulas.ExcelModel().loads(str(path)).finish()
        first = self.model.calculate()
        self.prefix = {}
        for k in first:
            if "!" in k and "]" in k:
                book_sheet, _ = k.rsplit("!", 1)
                self.prefix[book_sheet.split("]", 1)[1].rstrip("'").upper()] = book_sheet
        print(f"compiled workbook in {time.time() - t:.1f}s")

    def key(self, sheet, name):
        addr = self.cells[sheet].get(name, name).replace("$", "")
        return f"{self.prefix[sheet.upper()]}!{addr}"

    def run(self, inputs: dict, outputs: list):
        ins = {self.key(s, n): v for (s, n), v in inputs.items()}
        outs = [self.key(s, n) for s, n in outputs]
        sol = self.model.calculate(inputs=ins, outputs=outs)
        return {o: sol[k].value[0, 0] for o, k in zip(outputs, outs)}


class Checker:
    def __init__(self, book):
        self.book, self.n, self.fail = book, 0, []

    def check(self, label, inputs, expected, tol=0.011):
        got = self.book.run(inputs, list(expected))
        for k, exp in expected.items():
            self.n += 1
            g = got[k]
            if isinstance(exp, str):
                ok = str(g) == exp
            else:
                ok = isinstance(g, (int, float)) and abs(float(g) - float(exp)) <= (tol if abs(exp) >= 1 else 1e-6)
            if not ok:
                self.fail.append(f"{label}: {k[0]}.{k[1]} sheet={g!r} python={exp!r}")


def apr_cases(ch, rnd, n):
    cases = [(50000, 0, 1.35, 2250, 52)] + [
        (rnd.uniform(5e3, 2e5), rnd.uniform(0, 3000), rnd.uniform(1.1, 1.5), 0, rnd.choice([52, 26, 12]))
        for _ in range(n)]
    for adv, fee, fac, pay, ppy in cases:
        if not pay:
            pay = adv * fac / rnd.randint(8, 150)
        freq = {52: "week", 26: "biweek", 12: "month"}[ppy]
        a = analyze(mca_fixed(adv, fac, pay, freq, fees=fee))
        S = "APR"
        ch.check(f"APR {adv:.0f}/{fac:.3f}/{ppy}",
                 {(S, "advance"): adv, (S, "fees"): fee, (S, "factor"): fac, (S, "payment"): pay, (S, "ppy"): ppy},
                 {(S, "apr"): a["apr_actuarial"], (S, "finance_charge"): a["finance_charge"],
                  (S, "simple"): a["simple_annualized"]})


def daily_cases(ch, rnd, n):
    cases = [(date(2027, 1, 4), 50000, 0, 1.35, 450, "Y"), (date(2027, 1, 4), 50000, 0, 1.35, 450, "N"),
             (date(2027, 1, 8), 50000, 0, 1.35, 450, "N")]
    for _ in range(n):
        d = date(2026, 1, 1) + timedelta(rnd.randint(0, 700))
        adv = rnd.uniform(5e3, 1.5e5)
        fac = rnd.uniform(1.1, 1.5)
        cases.append((d, adv, rnd.uniform(0, 2000), fac, adv * fac / rnd.randint(60, 400), rnd.choice("YN")))
    S = "Daily_MCA"
    for d, adv, fee, fac, pay, hol in cases:
        s = mca_fixed(adv, fac, pay, "business_day", d, fees=fee, holidays="frb" if hol == "Y" else None)
        a = analyze(s)
        ch.check(f"Daily {d} {hol}",
                 {(S, "fund"): xl_date(d), (S, "advance"): adv, (S, "fees"): fee, (S, "factor"): fac,
                  (S, "payment"): pay, (S, "use_holidays"): hol},
                 {(S, "apr"): a["apr_actuarial"], (S, "last"): xl_date(s.flows[-1].when)})


def loan_cases(ch, rnd, n):
    S = "Loans"
    cases = [(50000, 0.15, 24, 1500, 42548.02, 0.07)] + [
        (rnd.uniform(1e4, 5e5), rnd.uniform(0.05, 0.3), rnd.choice([12, 24, 36, 60]), rnd.uniform(0, 5000),
         rnd.choice([rnd.uniform(25e3, 50e3), rnd.uniform(5e4, 2.5e5), rnd.uniform(2.5e5, 3.5e5),
                     rnd.uniform(3.5e5, 3e6)]), rnd.uniform(0.04, 0.09)) for _ in range(n)]
    for amt, rate, months, fee, sba_amt, prime in cases:
        tl = analyze(term_loan(amt, rate, months, fee))
        sb = sba_7a(sba_amt, prime=prime)
        sa = analyze(sb)
        ch.check(f"Loans {amt:.0f}/{sba_amt:.0f}",
                 {(S, "tl_amount"): amt, (S, "tl_rate"): rate, (S, "tl_months"): months, (S, "tl_fee"): fee,
                  (S, "sba_amount"): sba_amt, (S, "prime"): prime},
                 {(S, "tl_apr"): tl["apr_actuarial"], (S, "sba_fee"): sb.terms["upfront_fee"],
                  (S, "sba_ceiling"): P.sba_fee_ceiling(sba_amt), (S, "sba_apr"): sa["apr_actuarial"],
                  (S, "sba_rate"): sb.terms["annual_rate"], (S, "sba_fee_ok"): "OK"})


def earlypay_cases(ch, rnd, n):
    S = "EarlyPay_Factoring"
    for k in range(n + 1):
        d, dd, nd = (0.02, 10, 30) if k == 0 else (rnd.uniform(0.005, 0.05), rnd.randint(5, 15), rnd.randint(30, 90))
        face, ar, f30, days = (10000, 0.8, 0.03, 45) if k == 0 else (
            rnd.uniform(1e3, 1e5), rnd.uniform(0.7, 0.95), rnd.uniform(0.005, 0.05), rnd.randint(10, 120))
        e = early_pay_cost(d, dd, nd)
        fa = factoring(face, ar, f30, days)
        ch.check(f"EarlyPay {k}",
                 {(S, "disc"): d, (S, "dd"): dd, (S, "nd"): nd, (S, "face"): face, (S, "adv_rate"): ar,
                  (S, "fee30"): f30, (S, "days"): days},
                 {(S, "ep_nominal"): e["nominal"], (S, "ep_effective"): e["effective"],
                  (S, "fac_fee"): fa.terms["fee"], (S, "fac_apr"): analyze(fa)["apr_actuarial"]})


def disclosure_cases(ch, rnd, n):
    S = "Disclosure"
    base = [60000, 58000, 62000, 61000, 59000, 60000, 57000, 63000, 61000, 60000, 59000, 61000]
    cases = [(50000, 67500, 0, 0.10, 6, date(2027, 1, 4), base, 0)]
    for _ in range(n):
        f = rnd.uniform(1e4, 3e5)
        cases.append((f, f * rnd.uniform(1.1, 1.5), rnd.uniform(0, 2000), rnd.uniform(0.05, 0.2), rnd.randint(4, 12),
                      date(2026, 1, 1) + timedelta(rnd.randint(0, 600)),
                      [rnd.uniform(0.3, 3) * f / 2 for _ in range(12)], rnd.choice([0, 0, 100])))
    for fund, owed, fees, split, win, d, sales, minp in cases:
        avg = D.historical_average(sales, win)
        est = D.estimate(fund, owed, split, avg, "business_day", d, fees, minp)
        if est["estimated_term_days"] > 1090:
            continue
        ins = {(S, "funding"): fund, (S, "owed"): owed, (S, "fees"): fees, (S, "split"): split, (S, "window"): win,
               (S, "fund"): xl_date(d), (S, "minpay"): minp}
        ins.update({(S, f"sales{k + 1}"): v for k, v in enumerate(sales)})
        ch.check(f"Disclosure {fund:.0f} w{win}", ins,
                 {(S, "avg"): avg, (S, "payment"): est["estimated_payment"], (S, "n"): est["number_of_payments"],
                  (S, "term_days"): est["estimated_term_days"], (S, "apr"): est["estimated_apr_actuarial"]})


def mix_cases(ch, rnd, n, scenario):
    S = "Mix_Evaluator"
    cells = ch.book.cells[S]
    T = scenario["horizon_weeks"]
    for k in range(n):
        xm = rnd.choice([0, rnd.uniform(10000, 50000)])
        sm = rnd.randint(1, T)
        um = rnd.choice([0] + list(range(sm + 1, T + 1))) if sm < T else 0
        xs = rnd.choice([0, rnd.uniform(25000, 50000), rnd.uniform(50001, 150000)])
        ss = rnd.randint(7, T)
        b = [round(rnd.uniform(0, 40000), 2) for _ in range(T)]
        e = [round(rnd.random(), 4) for _ in range(T - 1)] + [0]
        H = rnd.choice([0, 52])
        plan = {"fundings": ([{"offer": "MCA", "week": sm, "amount": xm, "prepay_week": um or None}] if xm else [])
                + ([{"offer": "SBA 7(a)", "week": ss, "amount": xs}] if xs else []),
                "loc_balance": b, "early_pay": {i: e[i] for i in range(T - 1) if e[i]}}
        r = evaluate(scenario, plan, H=H)
        ins = {(S, "x_mca"): xm, (S, "s_mca"): sm, (S, "u_mca"): um, (S, "x_sba"): xs, (S, "s_sba"): ss, (S, "H"): H}
        ins.update({(S, f"b{t}"): b[t - 1] for t in range(1, T + 1)})
        ins.update({(S, f"e{t}"): e[t - 1] for t in range(1, T + 1)})
        exp = {(S, "terminal"): r["terminal_net_position"], (S, "feasible"): "FEASIBLE" if r["feasible"] else "NOT FEASIBLE"}
        exp.update({(S, f"cash{t}"): r["weeks"][t - 1]["cash"] for t in (1, 7, T)})
        ch.check(f"Mix {k} H={H}", ins, exp, tol=0.011)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", default=str(ROOT / "workbook" / "CapKit.xlsx"))
    ap.add_argument("--fuzz", type=int, default=10)
    ap.add_argument("--seed", type=int, default=2026)
    a = ap.parse_args()
    book = Book(Path(a.path))
    ch = Checker(book)
    rnd = random.Random(a.seed)
    scenario = json.loads((ROOT / "examples" / "bakery.json").read_text())
    S = "Mix_Evaluator"
    eng = book.run({}, [(S, "engine_terminal")])[(S, "engine_terminal")]
    ch.check("Mix optimal plan", {}, {(S, "terminal"): eng, (S, "feasible"): "FEASIBLE"})
    t = time.time()
    for fn in (apr_cases, daily_cases, loan_cases, earlypay_cases, disclosure_cases):
        fn(ch, rnd, a.fuzz)
    mix_cases(ch, rnd, a.fuzz * 3, scenario)
    print(f"{ch.n} comparisons in {time.time() - t:.1f}s, {len(ch.fail)} mismatches")
    for f in ch.fail[:40]:
        print("  MISMATCH", f)
    sys.exit(1 if ch.fail else 0)


if __name__ == "__main__":
    main()
