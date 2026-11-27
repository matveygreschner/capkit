# CapKit

[![CI](https://github.com/matveygreschner/capkit/actions/workflows/ci.yml/badge.svg)](https://github.com/matveygreschner/capkit/actions/workflows/ci.yml)

**What does this money really cost, and which money should I take?**

CapKit is a tested, open-source engine for small-business financing. It ships as three downloadable
Claude skills and a formula-verified Excel / Google Sheets workbook. It does three things:

1. **Puts every product on one cash-flow basis.** The products are merchant cash advances (fixed or
   split-percentage), revenue-based financing, term loans, SBA 7(a), lines of credit, invoice
   factoring, supplier early-payment discounts and equipment leases. Each is priced with the exact
   **Regulation Z Appendix J APR**, by both permitted methods (actuarial and U.S. Rule), on actual
   payment dates.
2. **Reproduces California (SB 1235) and New York (CFDL) disclosure math.** It computes the
   historical-method estimated APR, term and payment for sales-based financing, and checks a
   disclosed APR against both permitted methods.
3. **Optimizes the funding mix.** A mixed-integer program chooses how much of each source to take,
   in which week, and whether to refinance or prepay. It keeps cash above a floor every week at the
   lowest cost. Every plan is re-priced independently before it is shown.

It follows the architecture of my earlier [TaxKit](https://github.com/matveygreschner/taxkit) project, and reuses it for the
after-tax view.

## Why it exists

A bakery is offered a $50,000 merchant cash advance at a 1.35 factor rate, repaid at $450 every
business day. The broker calls it a "35% cost". A typical online calculator says about 60%.

| Measure | Value |
|---|---|
| Factor cost ("35%") | 35% |
| Simple annualized (cost ÷ term) | 59.7% |
| **Appendix J APR, calendar-day unit period, Fed holidays** | **107.14%** |
| Business-day rate × 365 (a common error) | 153.3% |

Calculators disagree because they use different conventions. CapKit implements the regulation's.
It is tested against **every numeric example in Appendix J**.

The bakery also has a $40,000 line of credit, 2/10 net 30 flour invoices, and an SBA 7(a) loan
available from week 7. The optimizer's plan over 13 weeks:
- take only the **$10,000 minimum** MCA in week 6;
- **refinance it in week 7** out of a **$42,548 SBA loan**, using the 10% early-payoff discount;
- run the line of credit to its limit;
- take early-pay discounts on most invoices, except in the weeks when cash is tightest.

It beats "take the $50,000 MCA" by **$8,956**, or **$10,369** if open balances are carried another
year. The optimizer does not over-borrow: $150,000 of SBA was available.

## Claude skills (download)

| Skill | What it does | Download |
|---|---|---|
| **financing-true-cost** | APR (both Appendix J methods), EAR, dollar cost, after-tax cost and the misleading simple quote for any offer; ranks offers side by side | [zip](https://github.com/matveygreschner/capkit/releases/latest/download/financing-true-cost.zip) |
| **funding-mix-optimizer** | Which money to take, how much and when, from a weekly forecast; savings vs. the default choice, binding constraints, independent re-pricing | [zip](https://github.com/matveygreschner/capkit/releases/latest/download/funding-mix-optimizer.zip) |
| **commercial-financing-disclosure** | Recomputes CA / NY sales-based financing disclosures and checks the disclosed APR against both permitted methods, citing each section | [zip](https://github.com/matveygreschner/capkit/releases/latest/download/commercial-financing-disclosure.zip) |

**Install:**
- **Claude.ai / desktop:** Settings → Capabilities → Skills → upload the zip.
- **Claude Code:** unzip into `~/.claude/skills/`.

Each skill vendors the engine. It needs Python 3.9+, plus scipy ≥ 1.9 for the optimizer only.

Try:
- "A funder offered me $50K at a 1.35 factor, $450 a business day. What's the real APR?"
- "Here's my 13-week cash forecast and three offers. What should I take, and when?"
- "Is the 67.8% estimated APR on this California MCA disclosure right?"

## Workbook

[`workbook/CapKit.xlsx`](workbook/CapKit.xlsx) opens in Excel, or in Google Sheets via *File → Import*.

| Sheet | What it does |
|---|---|
| `APR` | Fixed-debit financing on its unit-period grid: APR = IRR × periods per year, EAR, the simple quote |
| `Daily_MCA` | Business-day debits on a 1,100-day calendar grid, skipping weekends and Federal Reserve holidays |
| `Loans` | Term loan and SBA 7(a): payment and APR with fees, SOP maximum spread, guaranty fee on the guaranteed portion, statutory ceiling check |
| `EarlyPay_Factoring` | Cost of forgoing 2/10 net 30; factoring advance, fee, rebate and APR |
| `Disclosure` | CA / NY historical-method estimate: average sales over a 4–12-month window, payment, term, monthly cost, estimated APR |
| `Mix_Evaluator` | Type any funding plan for the 13-week scenario. Every rule is checked and the terminal net position computed with the engine's objective. Pre-filled with the optimal plan |
| `Params_Sources`, `Holidays` | Every parameter with its source and verified-on date, and the FRB holiday list |

The formulas are portable: no XLOOKUP, LET, dynamic arrays, defined names or macros, and a test
enforces this. The optimizer is not in the sheet, because Excel Solver doesn't exist in Google
Sheets. The sheet evaluates any plan exactly, and the engine finds the best one.

## How it's verified

| Layer | What it checks |
|---|---|
| `tests/test_apr.py` | All 17 numeric examples in Reg Z Appendix J, plus the (b)(9) iteration example: single advance, odd first and last periods, semimonthly, quarterly, 4-weekly, skipped payments, graduated mortgage, construction and student loans (a payment before the first advance). Also U.S. Rule vs. actuarial properties and tolerances |
| `tests/test_products.py` | Hand-checked products; the day-count cases (110.40 / 107.14 / 108.55 / 110.87%); the FRB Saturday-holiday rule; the SBA fee base and statutory ceiling; CA/NY disclosure verdicts, including that a correct U.S. Rule disclosure is never flagged; parameter freshness (fails if any rule is older than 12 months) |
| `tests/test_optimize.py` | The bakery instance reproduced to the cent in 7 variants; an **independent re-pricing oracle** on 40 random instances (it caught a real factoring double-count during development); **brute-force enumeration** on small instances; the prepay-before-funding exploit rejected |
| `scripts/verify_workbook.py` | Recalculates the workbook with the independent [`formulas`](https://pypi.org/project/formulas/) engine and compares it with Python on fixed and randomized inputs, including random funding plans in the Mix_Evaluator |
| `tests/test_workbook_and_skills.py` | Portable formulas, sheet structure, and skills that are valid, in sync and run from the unpacked zip in isolated mode |
| CI | All of the above on Python 3.10 and 3.13 (the code is also tested locally on 3.9) |

## Quick start

```bash
pip install -r requirements-dev.txt
python -m pytest -q
PYTHONPATH=src python -m capkit true_cost '{"offer": {"type": "mca_fixed", "advance": 50000, "factor_rate": 1.35, "payment": 450, "frequency": "business_day"}}'
PYTHONPATH=src python -m capkit optimize_mix - < examples/bakery.json
PYTHONPATH=src python -m capkit workbook '{"path": "workbook/CapKit.xlsx"}'
python scripts/verify_workbook.py --fuzz 10
python scripts/build_skills.py            # dist/*.zip
```

## Docs

- [How cost is computed](docs/method.md)
- [The optimization model](docs/model.md)
- [Scenario format](docs/scenario.md)
- [CA/NY rules behind each disclosure line](docs/disclosure-rules.md)

## What's already out there, and what's new

Open-source Appendix J solvers already exist in other languages: the Ruby gem *Amortizy*, whose
v2.1 adds a state disclosure module, and the npm package *loan-amortization-calculator*. CapKit
does not claim to be the first APR calculator. What I could not find free or open source:
- the CA/NY historical-method estimate together with a both-methods checker;
- nine product types on one dated cash-flow basis;
- a **funding-mix optimizer** with cash-floor, affordability and refinancing decisions;
- a verified portable spreadsheet;
- Claude skills that do this math.

## Limits and legal

- **An MCA is usually a purchase of future receivables, not a loan.** Its APR is a cost-comparison
  measure, which is exactly how California and New York require it to be disclosed. CapKit never
  labels an MCA a loan.
- This is **not legal, tax, compliance or financial advice**. The disclosure tool reproduces the math
  and does not certify compliance.
- Parameters marked `verify` must be re-checked against their source before you rely on them: SBA
  spreads and fees, coverage thresholds, and Prime (a placeholder; `prime_rate` fetches FRED DPRIME).
- The tax character of MCA and factoring costs is uncertain (sale vs. debt). It is shown both ways.
  Confirm with a tax professional.

MIT licensed.
