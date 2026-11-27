---
name: financing-true-cost
description: Computes what a small-business financing offer really costs, using exact Regulation Z Appendix J APR math (actuarial and U.S. Rule) on actual payment dates, plus effective annual rate, total dollar cost, after-tax cost and the misleading "simple" quote. It covers merchant cash advances (factor rate, daily or weekly debits, split-percentage holdback), revenue-based financing, term loans, SBA 7(a) (SOP maximum spreads, guaranty fee on the guaranteed portion), lines of credit, invoice factoring, 2/10 net 30 supplier discounts and equipment leases, and ranks several offers side by side. Use this whenever someone asks "what's the APR", "is this a good loan", "what does a 1.35 factor rate cost", compares funding offers or an MCA quote, asks about factoring fees or early-payment discounts, or wants to know why a broker's "35% cost" number differs from the APR, even if they never say APR.
---

# Financing true cost

Turns any financing offer into one dated cash-flow schedule and prices it the way the law does:
**Regulation Z Appendix J APR**, computed by both permitted methods. The math is done by the bundled
**CapKit** engine. It is tested against every numeric example in Appendix J and against an
independent spreadsheet recalculation. Do not estimate APRs by hand: the payment-day convention
alone moves an MCA's APR by tens of points.

## Workflow

### 1. Get the terms
Map what the user has (term sheet, broker email, contract summary) to an offer type. Field lists are in
`references/commands.md` under `true_cost`. Ask only for missing terms that matter:
- **MCA, fixed debit:** advance, factor rate (or total payback), debit amount, frequency
  (`business_day` / `week`), funding date, fees withheld at funding.
- **MCA, split-percentage / revenue-based:** advance, factor or cap, holdback %, and a sales or revenue
  path per period. If the user has none, ask for average sales and say the figure is an estimate.
- **Loans:** amount, rate, months, fees withheld. For **SBA 7(a)**, the amount and Prime. The spread
  defaults to the SOP 50 10 maximum for the loan size, and the guaranty fee to the fiscal-year rate on
  the *guaranteed portion*.
- **Factoring:** face, advance rate, fee per 30 days, days until the customer pays.
- **Supplier terms:** e.g. 2/10 net 30 → `early_pay_cost`.

Unknown dates: use a near-future Monday and say so. Dates matter for daily debits (weekends and
Federal Reserve holidays are skipped).

### 2. Run it
```bash
python scripts/capkit_cli.py true_cost '{"offer": {"type": "mca_fixed", "advance": 50000, "factor_rate": 1.35, "payment": 450, "frequency": "business_day", "funding_date": "2027-01-04"}}'
python scripts/capkit_cli.py compare_offers '{"offers": [{...}, {...}], "marginal_rate": 0.30}'
python scripts/capkit_cli.py early_pay_cost '{"discount": 0.02, "discount_days": 10, "net_days": 30}'
python scripts/capkit_cli.py apr '{"flows": [["2027-01-04", 10000], ["2027-02-04", -900], ...]}'
```
Python 3.9+ standard library only. Large inputs: write JSON to a file and pass `-` with stdin.

### 3. Explain the number
Lead with a small table: offer, APR, EAR, total dollar cost, cost per $100 per month, and peak
payment. Then explain:
- **Why the quote differs.** "Factor 1.35 = 35% cost" ignores time. Simple annualization ignores
  that the balance falls with each payment. The APR measures the cost per dollar actually outstanding.
  Show all three numbers.
- **Which APR.** Report the actuarial APR. Mention the U.S. Rule figure only when it differs by
  1/8 point or more. That happens when some payment periods don't cover the interest, for example
  holiday gaps on daily debits or deferred payments.
- **Day convention.** For business-day debits the unit period is one calendar day (APR = daily rate ×
  365, weekends as multi-day gaps). Never multiply a business-day rate by 365. The engine never does.
- **Dollars still matter.** A lower APR on a longer term can cost more in total. Say so when it does.
- **After-tax.** With `marginal_rate`, MCA and factoring costs are flagged "character uncertain" (sale
  of receivables vs. debt). Show the alternative, and recommend a tax professional.

Read `references/method.md` for the formulas and conventions, and `references/parameters.md` for
every rate and limit with its source and verified-on date.

## Guardrails
- An MCA is usually a **purchase of future receivables**, not a loan. Never call it a loan or
  usurious. The APR is a comparison measure, the same one California and New York require for these
  products.
- SBA parameters (spreads, fees) change by fiscal year and are flagged `verify` in the parameter
  table. Say so when they drive the answer.
- Not legal, tax or financial advice. If the user is deciding *which* money to take, or how much and
  when, hand off to the **funding-mix-optimizer** skill if installed.
