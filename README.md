# CapKit

[![CI](https://github.com/matveygreschner/capkit/actions/workflows/ci.yml/badge.svg)](https://github.com/matveygreschner/capkit/actions/workflows/ci.yml)

**What a business loan really costs.** Lenders quote cash advances and short-term loans in ways that are
hard to compare: a "1.35 factor rate", a "6% fee", a daily payment. CapKit turns any offer into one
number, the annual percentage rate (APR), using the same method federal law requires for consumer
loans, so two offers can be compared side by side.

For example, a $50,000 cash advance at a 1.35 factor rate looks like it costs 35%. Repaid at $450 per
business day, it really costs about **107% a year**.

CapKit also checks the cost disclosure that California and New York require lenders to give you, and
tells you whether the APR on it holds up.

**Use it:** download the [Excel workbook](workbook/CapKit.xlsx) and type in your offer, or add the free
Claude skill and paste in a term sheet. CapKit is free, takes no money from lenders, and does not give
legal or financial advice.

## How it works

CapKit is a Python engine (standard library only) with a formula-driven Excel/Google Sheets workbook
and two Claude skills built on it. It computes Regulation Z Appendix J APRs on actual payment dates
for merchant cash advances, revenue-based financing, term loans, SBA 7(a), lines of credit, factoring,
supplier discounts and leases, and reproduces California and New York commercial financing
disclosure estimates.

## Example

A $50,000 merchant cash advance at a 1.35 factor rate, repaid at $450 per business day:

| Measure | Value |
|---|---|
| Factor cost | 35% |
| Cost ÷ term | 59.7% |
| Appendix J APR (one-day unit period, Federal Reserve holidays) | 107.14% |

```bash
PYTHONPATH=src python -m capkit true_cost '{"offer": {"type": "mca_fixed", "advance": 50000,
  "factor_rate": 1.35, "payment": 450, "frequency": "business_day", "funding_date": "2027-01-04"}}'
```

## Components

| Component | Description |
|---|---|
| `src/capkit` | Engine: Appendix J (actuarial and U.S. Rule), Federal Reserve business-day calendar, product schedules, SBA 7(a) fees (FY2026–FY2027 notices), CA 10 CCR 900+ and NY 23 NYCRR 600 disclosure estimates |
| [`financing-true-cost`](https://github.com/matveygreschner/capkit/releases/latest/download/financing-true-cost.zip) | Claude skill: cost of one or more offers on a common basis |
| [`commercial-financing-disclosure`](https://github.com/matveygreschner/capkit/releases/latest/download/commercial-financing-disclosure.zip) | Claude skill: recomputes a CA/NY sales-based financing disclosure and checks the disclosed APR |
| [`workbook/CapKit.xlsx`](workbook/CapKit.xlsx) | The core calculations as portable spreadsheet formulas (Excel, Google Sheets) |

A merchant-side remittance and reconciliation audit for MCAs is in development. A funding-mix
optimizer (`src/capkit/optimize`) is experimental and not included in releases.

Skills install by uploading the zip in Claude (Settings → Capabilities → Skills) or unzipping into
`~/.claude/skills/`. They need Python 3.9+.

## Verification

- Every numeric example in Appendix J, (b)(9) and (c)(1)–(c)(7), is a unit test.
- Regression tests cover the findings of two independent code audits.
- `scripts/verify_workbook.py` recalculates the workbook with an independent formula engine and
  compares it with the Python engine on randomized inputs.
- CI runs the suite and the workbook check on Python 3.9, 3.10 and 3.13.

```bash
pip install -r requirements-dev.txt
python -m pytest -q
python scripts/verify_workbook.py --fuzz 10
```

## Scope

- The tools compute and show their work; they do not interpret contracts, give legal, tax or
  financial advice, or certify compliance.
- A merchant cash advance is usually structured as a purchase of receivables. Its APR is a comparison
  measure, as California and New York require for these products.
- Parameters carry a source and a verified-on date in `src/capkit/params.py`; those marked `verify`
  should be confirmed before use. The default Prime rate is a placeholder.
- The project accepts no compensation from funders, lenders or processors.

Method notes: [docs/method.md](docs/method.md), [docs/disclosure-rules.md](docs/disclosure-rules.md).
Changes: [CHANGELOG.md](CHANGELOG.md). MIT licensed.
