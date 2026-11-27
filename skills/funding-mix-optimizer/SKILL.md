---
name: funding-mix-optimizer
description: Finds the cheapest combination of small-business funding (merchant cash advance, line of credit, SBA 7(a) or term loan, supplier early-payment discounts, invoice factoring) that keeps cash above a floor every week of a 13-to-52-week forecast. It decides how much of each source to take, in which week, and whether to refinance or prepay, by solving a mixed-integer program (HiGHS) with weekly debit-affordability limits. Every plan is re-priced as a cross-check, and savings are reported against simply taking the offer on the table. Use this whenever a business owner, bookkeeper or CPA asks which financing to take, how to cover a cash shortfall or a slow season, whether to take an MCA or wait for an SBA loan, whether to refinance an advance, whether to use the line of credit to take 2/10 net 30, or wants a 13-week cash plan with funding, even if they don't say "optimize".
---

# Funding-mix optimizer (CapKit Mix, experimental)

> **Experimental, not released.** The model cannot enforce use-of-proceeds rules: for example, SBA
> 7(a) proceeds generally cannot refinance a merchant cash advance (SOP 50 10 8 / 8.1). Never present
> a plan that pays one lender off with another's money without saying that the lender must approve
> that use. Present every plan as a starting point, not a recommendation.

Decides **which money to take, how much, and when**. The bundled **CapKit** engine builds a weekly
mixed-integer model from a cash forecast and the offers. HiGHS solves it, and a re-pricer then
cross-checks every plan before it is shown.

## Step 0: dependency check (do this first)
```bash
python -c "import scipy; print(scipy.__version__)"
```
The optimizer needs **scipy ≥ 1.9** (it bundles the HiGHS solver).
- If scipy is missing on the user's machine: `pip install "scipy>=1.9"`.
- If it cannot be installed, **do not improvise a solver.** Use `evaluate_mix` to check the plans the
  user is considering, plus the obvious baselines. Say plainly that no optimum was computed.

## Workflow

### 1. Build the scenario
The format is in `references/scenario.md`, and a full worked example is in `assets/bakery.json`.
Collect:
- the horizon (default 13 weeks), starting cash, the minimum cash floor, and weekly revenue for the
  affordability limit (default: debits ≤ 15% of revenue, a policy choice);
- **operating cash flow per week**, excluding supplier invoices and receivables if those are
  modeled separately (otherwise they get counted twice);
- each offer:
  - MCA: min/max, factor, weekly debit per dollar, payoff discount;
  - SBA 7(a): min/max, availability week, Prime (tiers, spreads and fees are automatic);
  - term loan: rate, months, fee share;
  - line of credit: limit, rate;
  - recurring supplier invoices with discount terms;
  - factoring facility and receivables;
- what the user would do otherwise, as `"baseline": {"force": {"MCA": 50000}}`.

If the user has bank statements or a P&L instead of a forecast, build a 13-week forecast with them
first and label it an estimate.

### 2. Solve
```bash
python scripts/capkit_cli.py optimize_mix - < scenario.json
python scripts/capkit_cli.py evaluate_mix '{"scenario": {...}, "plan": {...}}'      # check any proposed mix
```

### 3. Report
1. **The plan in plain words:** week by week, what to draw, prepay, pay early or factor.
2. **Saving vs the baseline** at **H = 0** (open balances valued at payoff at the horizon) and
   **H = 52** (each open balance carried one more year at its own rate). If the two plans differ, say
   the choice depends on how long the debt will really be carried, and suggest a longer horizon.
3. **What binds:** the weeks where cash sits at the floor, the affordability limit, and the LOC limit.
   Use the `sensitivity` rows, which are actual re-solves with the floor moved, not shadow prices.
4. **The APR of each chosen source**, from the financing-true-cost skill's `true_cost` command.
5. **Checks:** confirm `check.feasible` is true and that the re-priced terminal value equals the
   objective. If the status is not `optimal`, say "best plan found, not proven optimal".
6. **Assumptions** (from the output): weekly grid, one prepayment per offer, fixed MCA debits. For a
   split-percentage MCA, stress-test the sales.

Offer the Excel/Google Sheets workbook (`workbook` command). Its `Mix_Evaluator` sheet lets the user
try their own mix.

Read `references/model.md` before explaining *why* the optimizer chose something. It covers the
formulation, the terminal valuation and the known approximations.

## Guardrails
- The model borrows only what the floor needs: idle borrowed cash earns only the deposit rate. If
  the plan looks like it under-borrows, check the floor and the forecast; never add a hurdle rate.
- An MCA is usually a purchase of receivables, not a loan. Prepayment/payoff discounts must come from
  the actual contract.
- SBA availability and timing are not guaranteed. Present SBA-dependent plans with a fallback, i.e.
  the plan with SBA removed.
- Not legal, tax or financial advice. Lenders' approval, covenants and state law can change the answer.
