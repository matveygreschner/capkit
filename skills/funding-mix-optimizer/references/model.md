# The funding-mix model

**Decision.** How much of each funding source to use, in which week, and whether to prepay it. The
goal is to cover a forecast cash shortfall at the lowest cost.

## Variables (weeks t = 1…T)

- **Lump-sum offers j** (MCA, term loan, each SBA tier): *x[j,s,u]* ≥ 0 is the dollar amount funded
  in week *s* and prepaid in full in week *u*, where *u* = "never" means not prepaid inside the
  horizon. Each has a binary *z[j,s,u]*.
  - Every debit, prepayment and terminal payoff is a fixed per-dollar coefficient times one *x*.
    This is the *disaggregated* formulation.
  - "Prepay before funding" cannot be expressed, because *u* > *s* by construction.
  - On the bakery example, the LP relaxation bound is $694 from the integer optimum. A big-M
    formulation's bound is $202,279 away.
- **Line of credit:** draw *d_t*, repayment *p_t*, balance 0 ≤ *b_t* ≤ limit. Interest on *b_{t−1}* is
  paid weekly.
- **Supplier invoices:** *e_i* ∈ [0,1] is the share of invoice *i* paid early, in its discount week,
  at (1 − discount).
- **Factoring:** *y[r,q]* ∈ [0,1] is the share of receivable *r* sold in week *q*, before collection.

## Constraints

1. **Cash:** B_t = (1 + i_dep)·B_{t−1} + c_t + funding net of fees − scheduled debits − prepayments
   + LOC draws − repayments − LOC interest − invoice payments + factoring advances and rebates.
   B_t ≥ floor_t.
2. **Each offer is taken at most once**, with one funding week, one prepay choice and min/max
   amounts. Offers in a group, such as SBA spread tiers, are mutually exclusive.
3. **Affordability:** scheduled debits + LOC interest ≤ α × revenue_t, every week. Default α = 15%.
4. **Factoring:** each receivable is sold at most once, and outstanding advances stay within the
   facility limit.
5. **Optional debt-service coverage** over the horizon.

## Objective: terminal net position

The model maximizes:

  (1 + i_dep·H)·B_T − (1 + i_LOC·H)·b_T − Σ_j (1 + r_j·H)·payoff_j(T) − unpaid invoices + receivables still to collect

- **No hurdle or discount rate.** Borrowed cash that sits idle earns only the deposit rate, so the
  model borrows only what the floor needs, or what pays for itself. An example of the second case is
  a line of credit at 11% funding a 2/10 discount worth about 37%.
- **H = 0 (default):** every balance still open at T counts at its **payoff amount**, as if repaid at
  T. This is a liquidation basis.
- **H = 52:** each open balance is also carried one more year at its own contract rate. Reports show
  both. If the plans differ, the right choice depends on how long the debt will really be carried.

## Approximations (stated in every output)

- Weekly grid. A monthly payment falls in week ⌈m·52/12⌉ after funding, and accrued interest counts
  from the contractual due date. Reported APRs are computed separately on actual dates.
- Prepayment is all-or-nothing and happens at most once per offer.
- MCA debits are a fixed amount per advance dollar. A split-percentage MCA depends on sales, so use
  the stress test.
- A rate that depends on the amount (SBA tiers) is modeled as one offer per tier inside a group.
- Factoring uses each receivable's *expected* collection week. Late payment is a stress scenario.

## How a plan is checked

- **Solver.** HiGHS, through `scipy.optimize.milp`, with a relative gap of 1e-9. If the time limit is
  hit, the result is labelled "not proven optimal".
- **Independent re-pricing** (`capkit.verify.reprice`). It rebuilds every cash flow from the offer
  terms without the matrix:
  - the MCA debit by debit;
  - the amortizing loans from their level payment;
  - invoices and factoring from their own weeks.

  The re-pricing must reproduce the objective to 1e-6 and every rule must hold. The test suite runs
  this on 40 random instances. It caught a real double-count of factoring advances during
  development.
- **Brute force.** On small instances, every funding/prepay choice is enumerated and each remaining
  LP is solved. The MILP optimum must equal the best enumerated value.

## Sensitivity

A mixed-integer program has no dual prices. CapKit re-solves with the cash floor moved by ±$1,000
and ±$5,000, and reports the actual change in terminal net position. That captures jumps when the
set of offers taken changes.
