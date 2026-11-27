# CapKit

[![CI](https://github.com/matveygreschner/capkit/actions/workflows/ci.yml/badge.svg)](https://github.com/matveygreschner/capkit/actions/workflows/ci.yml)

**Capital Kit: free, open-source tools that put small businesses on equal footing with the companies
that finance them.**

Funders, processors and platforms run detailed math on every deal. The small business on the other
side usually has a sales pitch and a contract. CapKit is one tested financial engine with several
small products built on top of it. Each product answers one question a business owner can't easily
check alone. Everything is free, runs locally, and takes no money from funders.

> **Errata for v0.1.0.** The first release led with a "bakery" example that saved $8,956 by paying off
> a merchant cash advance with SBA 7(a) loan proceeds. SBA rules (SOP 50 10 8 / 8.1) restrict using
> 7(a) money to refinance a merchant cash advance, so that plan is not one a business could normally
> carry out. The example is fixed: the public scenario no longer allows that refinance. The
> optimizer that produced it is now marked experimental and is not released. An independent code
> audit (OpenAI Codex) found this issue and others; the fixes are tracked in this repository.

## The CapKit family

| Product | The question it answers | Status |
|---|---|---|
| **CapKit Core** | The engine: Regulation Z Appendix J APR (actuarial and U.S. Rule) on real payment dates, the Federal Reserve business-day calendar, dated schedules for nine kinds of financing, CA/NY disclosure math | Released (Python, standard library only) |
| **CapKit True Cost** | "What does this offer *really* cost?" One honest number for a cash advance, loan, factoring deal, supplier discount or lease, next to the number the salesperson quoted | Released: Claude skill + workbook |
| **CapKit Disclosure Check** | "Is the APR on my California or New York disclosure form right?" | Released: Claude skill + workbook |
| **CapKit Remit** | "Is my cash advance company taking more than my contract allows?" It compares what the funder debited with the contract's percentage of actual sales, and builds the figures for a reconciliation request | **In development (next release)** |
| CapKit Mix | "Which combination of funding covers my cash gap most cheaply?" (a mixed-integer optimizer) | Experimental: in the repo with its tests, not released |
| CapKit Fees *(planned)* | "Is my card processor overcharging me?" | Idea stage |

Every product uses the same engine, the same tests and the same promise: the tool does the math and
shows its work, and the business owner decides.

## Why it exists

A bakery is offered a $50,000 merchant cash advance at a 1.35 factor rate, repaid at $450 every
business day. The broker calls it a "35% cost".

| Measure | Value |
|---|---|
| Factor cost ("35%") | 35% |
| Simple annualized (cost ÷ term) | 59.7% |
| **Appendix J APR, calendar-day unit period, Federal Reserve holidays** | **107.14%** |
| Business-day rate × 365 (a common error) | 153.3% |

Calculators disagree because they use different conventions. CapKit implements the regulation's and
is tested against every numeric example in Appendix J.

Free APR calculators already exist (NerdWallet, Nav and others). CapKit's aim is the moments they
don't cover, starting with **after you sign**: when sales have dropped and the daily debits haven't.

## Download the released skills

| Skill | What it does | Download |
|---|---|---|
| **financing-true-cost** (CapKit True Cost) | APR by both Appendix J methods, effective annual rate, dollar cost, after-tax cost and the misleading simple quote for any offer; ranks offers side by side | [zip](https://github.com/matveygreschner/capkit/releases/latest/download/financing-true-cost.zip) |
| **commercial-financing-disclosure** (CapKit Disclosure Check) | Recomputes a CA / NY sales-based financing disclosure and checks the disclosed APR against both permitted methods, citing each section | [zip](https://github.com/matveygreschner/capkit/releases/latest/download/commercial-financing-disclosure.zip) |

**Install:**
- **Claude.ai / desktop:** Settings → Capabilities → Skills → upload the zip.
- **Claude Code:** unzip into `~/.claude/skills/`.

Each skill vendors the engine and needs only Python 3.9+. A released skill runs only its own
commands, and the experimental optimizer is not included in it.

Try:
- "A funder offered me $50K at a 1.35 factor, $450 a business day. What's the real APR?"
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
| `Params_Sources`, `Holidays` | Every parameter with its source and verified-on date, and the FRB holiday list |

The formulas are portable: no XLOOKUP, LET, dynamic arrays, defined names or macros, and a test
enforces this.

## How it's verified

| Layer | What it checks |
|---|---|
| `tests/test_apr.py` | All 17 numeric examples in Reg Z Appendix J, plus the (b)(9) iteration example, U.S. Rule vs. actuarial cases and tolerances |
| `tests/test_products.py` | Hand-checked products; the day-count cases (110.40 / 107.14 / 108.55 / 110.87%); the FRB Saturday-holiday rule; the SBA fee base and statutory ceiling; CA/NY disclosure verdicts, including that a correct U.S. Rule disclosure is never flagged; parameter freshness |
| `tests/test_optimize.py` | The experimental optimizer: a pinned reference instance (`tests/fixtures/`), a re-pricing check on 40 random instances, brute-force enumeration on small ones, and a test that the public example never refinances an advance with SBA money |
| `scripts/verify_workbook.py` | Recalculates the workbook with the [`formulas`](https://pypi.org/project/formulas/) engine and compares it with Python on fixed and randomized inputs |
| `tests/test_workbook_and_skills.py` | Portable formulas, sheet structure, and released skills that are valid, in sync, run from the unpacked zip in isolated mode, and refuse commands outside their own list |
| CI | All of the above on Python 3.10 and 3.13 (the code is also tested locally on 3.9) |

These checks show the engine agrees with the regulation's examples and with an independent
spreadsheet engine on the inputs tested. They are not a guarantee for every contract; known open
issues from the code audit are being fixed.

## Quick start

```bash
pip install -r requirements-dev.txt
python -m pytest -q
PYTHONPATH=src python -m capkit true_cost '{"offer": {"type": "mca_fixed", "advance": 50000, "factor_rate": 1.35, "payment": 450, "frequency": "business_day"}}'
PYTHONPATH=src python -m capkit workbook '{"path": "workbook/CapKit.xlsx"}'
python scripts/verify_workbook.py --fuzz 10
python scripts/build_skills.py            # dist/*.zip for the released skills
```

## Docs

- [How cost is computed](docs/method.md)
- [CA/NY rules behind each disclosure line](docs/disclosure-rules.md)
- [The experimental optimization model](docs/model.md) and its [scenario format](docs/scenario.md)

## What's already out there

Open-source Appendix J solvers already exist in other languages: the Ruby gem *Amortizy* and the npm
package *loan-amortization-calculator*. Free pre-signing calculators exist too (NerdWallet, Nav,
Merchant Maverick, FundingEstimate, usfundingclimate), as do AI contract readers (DebtMedx, 8x,
AuditDeal) and paid reconciliation services from law and debt-relief firms. For the after-signing
moment, Delancey Street's free calculator and BusCalc compare one period's receipts × the contract
percentage with the debits, and FundingTracker flags debits that differ from the fixed schedule.
CapKit doesn't claim to be the first APR calculator or the only reconciliation calculator. Remit's
aim is a multi-period audit from the merchant's own exported statements, request deadlines, honest
value figures and an evidence packet, open source and with no sales funnel behind it.

## Limits and legal

- **An MCA is usually a purchase of future receivables, not a loan.** Its APR is a cost-comparison
  measure, which is how California and New York require it to be disclosed.
- This is **not legal, tax, compliance or financial advice**. The tools do arithmetic and show their
  work. They don't interpret contracts, contact funders or negotiate.
- **No money from funders, lenders, processors or debt-relief firms**, no referral fees, and no
  selling data. CapKit stays on the small business's side.
- Parameters marked `verify` must be re-checked against their source before you rely on them: SBA
  spreads and fees, coverage thresholds, and Prime (a placeholder; `prime_rate` fetches FRED DPRIME).

MIT licensed.
