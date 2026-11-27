# How CapKit computes cost

## One basis for every product

Each product becomes a dated cash-flow schedule from the borrower's side: `+` for money received
(net of fees withheld) and `−` for payments. Every measure is computed from that schedule, so a
merchant cash advance, an SBA loan and a forgone supplier discount become comparable.

## APR: Regulation Z, Appendix J

**General equation (actuarial method), Appendix J (b)(8):**

Σ_k A_k / [(1 + e_k·i)(1 + i)^q_k] = Σ_j P_j / [(1 + f_j·i)(1 + i)^t_j]

- *A_k* is an advance and *P_j* a payment.
- *q*, *t* are whole unit periods from the zero point (the earliest flow).
- *e*, *f* are the remaining fractions of a unit period. Those are charged simple interest, per (b)(6).

APR = *i* × unit periods per year. The rate is solved to machine precision by bisection, after a scan
for the first sign change. Flows that begin with a payment, as in Appendix J (c)(7)(ii), make the
equation non-monotone, which is why the scan is needed.

**Unit period, (b)(4).** The most common interval between payments, capped at one year. On a tie,
the smaller interval wins. A single advance repaid by a single payment uses the term itself
((c)(5)).

**Counting periods, (b)(5):**

| Unit | Whole periods | Fraction |
|---|---|---|
| month | full months measured back from the later date | remaining days ÷ 30 |
| semimonth, quarter, multi-month | days = 30 × full months back + remaining days | ÷ 15 or ÷ (30 × months) |
| day, week, 2 or 4 weeks | days ÷ days per period | remainder |
| year | full years back | months ÷ 12 if whole, else days ÷ 365 |

**United States Rule.** Each payment pays accrued interest first, then principal. Unpaid interest is
carried but never charged interest. 12 CFR 1026.22 and both state disclosure laws allow either
method.
- The two agree whenever every payment covers the interest accrued since the previous flow.
- They differ otherwise. Example: a $10,000 advance with two zero-payment months, then 10 × $1,150,
  gives **22.8099%** actuarial vs **22.9843%** U.S. Rule.

**Tolerance.** 1/8 percentage point, or 1/4 for irregular transactions (12 CFR 1026.22(a)(2)–(3)).

**Tests.** Every numeric example in Appendix J is a unit test: (b)(9) and (c)(1)–(c)(7), 17
examples in all, reproduced to the published two decimals.

## Daily debits: the convention that moves the answer

A typical MCA debits every business day. Under Appendix J the most common interval is **one
calendar day**. So the unit period is a day, each weekend is a three-day gap, and APR = daily
rate × 365.

The same $50,000 / $450 × 150-debit contract gives:

| Convention | APR |
|---|---|
| Calendar-day grid, funded Mon 2027-01-04, no holidays | 110.40% |
| Same, skipping Federal Reserve holidays (CapKit default) | **107.14%** |
| Business-day rate × 252 (not an Appendix J figure) | 105.9% |
| Business-day rate × 365 (wrong; never output) | 153.3% |

The holiday calendar is the **Federal Reserve's**. A holiday that falls on a Sunday moves to Monday.
A holiday that falls on a Saturday is not observed on Friday, so ACH debits still settle that day.

## Other measures

- **EAR** = (1 + APR/n)^n − 1.
- **XIRR**: actual days / 365.
- **Finance charge** = total paid − total received.
- **Simple annualized quote** = (cost ÷ amount) ÷ term in years. This is the number brokers often
  quote, and it is **not** an APR: a $50,000 weekly MCA at factor 1.35 shows 60.67% simple vs 106.96%
  APR.
- **Cost of forgoing 2/10 net 30** = d/(1−d) × 365/(N−D) = **37.24%** nominal, or (1 + d/(1−d))^(365/20) − 1
  = **44.59%** effective.

## SBA 7(a) specifics

- **Rate.** Prime plus the SOP 50 10 maximum spread for the loan size (6.5% ≤ $50,000; 6.0% to
  $250,000; 4.5% to $350,000; 3.0% above). These are `verify` parameters.
- **Upfront guaranty fee.** Fiscal-year rate × the **guaranteed portion**: 85% of the loan at or below
  $150,000, 75% above. It is not charged on the face amount. Every stored rate is tested against the
  statutory ceiling of 15 U.S.C. 636(a)(18)(A): 2% / 3% / 3.5% of the guaranteed portion by size, plus
  0.25% on any guaranteed portion above $1,000,000.

## After-tax cost

Each product carries a tax-character tag:
- **Interest**: deductible, subject to §163(j) unless exempt.
- **Character uncertain**: MCA and factoring costs, which depend on whether the deal is treated as a
  sale of receivables or as debt.
- **Rent**: leases.
- **Purchase cost**: forgone supplier discounts.

The after-tax figure applies a user-supplied marginal rate. Uncertain items show both treatments.
Confirm with a tax professional.
